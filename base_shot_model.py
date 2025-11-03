"""Base class for shot models with shared functionality."""

from __future__ import annotations

# Standard library imports
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import QObject, Signal


if TYPE_CHECKING:
    from cache_manager import CacheManager
    from core.shot_types import RefreshResult
    from protocols import ProcessPoolInterface
    from type_definitions import PerformanceMetricsDict, Shot

# Local application imports
from logging_mixin import LoggingMixin
from optimized_shot_parser import OptimizedShotParser
from process_pool_manager import ProcessPoolManager
from qt_abc_meta import QABCMeta
from shot_filter import compose_filters, get_available_shows
from utils import ValidationUtils


# Enable verbose debug logging if environment variable is set
DEBUG_VERBOSE = os.environ.get("SHOTBOT_DEBUG_VERBOSE", "").lower() in (
    "1",
    "true",
    "yes",
)


# Import RefreshResult from type_definitions to avoid circular imports


class BaseShotModel(ABC, LoggingMixin, QObject, metaclass=QABCMeta):
    """Abstract base class for shot models with shared functionality.

    This base class provides common signals, shot parsing logic, caching,
    and performance metrics collection that is shared between ShotModel
    and OptimizedShotModel implementations.

    Subclasses must implement:
        - load_shots(): Method to load shots (sync or async)
        - refresh_strategy(): How to refresh the shot list
    """

    # Common Qt signals
    shots_loaded: Signal = Signal(list)  # List of Shot objects
    shots_changed: Signal = Signal(list)  # List of Shot objects
    refresh_started: Signal = Signal()
    refresh_finished: Signal = Signal(bool, bool)  # success, has_changes
    error_occurred: Signal = Signal(str)  # Error message
    shot_selected: Signal = Signal(object)  # Shot object
    cache_updated: Signal = Signal()

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        load_cache: bool = True,
        process_pool: ProcessPoolInterface | None = None,
    ) -> None:
        """Initialize base shot model.

        Args:
            cache_manager: cache manager instance
            load_cache: Whether to load from cache on init
            process_pool: Optional process pool instance (defaults to singleton)
        """
        super().__init__()
        # Local application imports
        from cache_manager import CacheManager

        self.shots: list[Shot] = []
        self.cache_manager = cache_manager or CacheManager()
        # Use OptimizedShotParser for improved performance
        self._parser = OptimizedShotParser()
        self._selected_shot: Shot | None = None
        self._filter_show: str | None = None  # Show filter
        self._filter_text: str | None = None  # Text filter for real-time search

        # Initialize process pool - use provided instance or default singleton
        self._process_pool = process_pool or ProcessPoolManager.get_instance()

        # Performance metrics
        self._last_refresh_time = 0.0
        self._total_refreshes = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # Load cache if requested
        if load_cache:
            _ = self._load_from_cache()

    def _load_from_cache(self) -> bool:
        """Load shots from cache if available.

        Returns:
            True if cache was loaded, False otherwise
        """
        # Local application imports
        from type_definitions import Shot  # Import here to avoid circular import

        cached_data = self.cache_manager.get_cached_shots()
        if cached_data:
            try:
                # Type annotation to help the type checker understand ShotDict compatibility
                self.shots = [Shot.from_dict(shot_data) for shot_data in cached_data]
                self.shots_loaded.emit(self.shots)
                self._cache_hits += 1
                self.logger.info(f"Loaded {len(self.shots)} shots from cache")
                return True
            except (KeyError, TypeError, ValueError) as e:
                # Handle corrupted cache data gracefully
                self.logger.warning(f"Corrupted cache data, ignoring: {e}")
                self.shots = []
                self._cache_misses += 1
                return False
        self._cache_misses += 1
        return False

    def _parse_ws_output(self, output: str) -> list[Shot]:
        """Parse ws -sg output to extract shots.

        Args:
            output: Raw output from ws -sg command

        Returns:
            List of Shot objects parsed from the output
        """
        # Input is guaranteed to be str by type annotation
        # Removed unnecessary isinstance check per basedpyright reportUnnecessaryIsInstance

        shots: list[Shot] = []
        lines = output.strip().split("\n")

        # If output is completely empty, that might indicate an issue
        if not output.strip():
            self.logger.warning("ws -sg returned empty output")
            return shots

        # Log the first few lines of output for debugging
        self.logger.info(f"Parsing ws output with {len(lines)} lines")
        if lines and len(lines) > 0:
            self.logger.info(f"First line of ws output: {lines[0][:200]}")
            # Log first 3 lines for debugging
            for i, line in enumerate(lines[:3]):
                self.logger.debug(f"ws output line {i + 1}: {line}")

        for line_num, line in enumerate(lines, 1):
            stripped_line = line.strip()
            if not stripped_line:
                continue

            # Use OptimizedShotParser for better performance
            result = self._parser.parse_workspace_line(stripped_line)
            if result:
                try:
                    workspace_path = result.workspace_path
                    show = result.show
                    sequence = result.sequence
                    shot = result.shot

                    # Log what we extracted for debugging
                    self.logger.debug(
                        f"Parsed line {line_num}: workspace_path={workspace_path}, "
                         f"show={show}, sequence={sequence}, shot={shot}"
                    )

                    # Validate extracted components using utility
                    if not ValidationUtils.validate_not_empty(
                        workspace_path,
                        show,
                        sequence,
                        shot,
                        names=["workspace_path", "show", "sequence", "shot"],
                    ):
                        self.logger.warning(
                            f"Line {line_num}: Missing required components in: {line}",
                        )
                        continue

                    # Local application imports
                    from type_definitions import (
                        Shot,
                    )  # Import here to avoid circular import

                    shots.append(
                        Shot(
                            show=show,
                            sequence=sequence,
                            shot=shot,
                            workspace_path=workspace_path,
                        ),
                    )
                except (IndexError, AttributeError) as e:
                    self.logger.warning(
                        f"Line {line_num}: Failed to parse shot data from: {line} ({e})",
                    )
                    continue
            else:
                # Log unmatched lines for debugging, but don't fail
                self.logger.debug(
                    f"Line {line_num}: No match for workspace pattern: {line}"
                )

        self.logger.info(f"Parsed {len(shots)} shots from ws -sg output")
        return shots

    def _check_for_changes(self, new_shots: list[Shot]) -> bool:
        """Check if the shot list has changed.

        Args:
            new_shots: New list of shots to compare

        Returns:
            True if shots changed, False otherwise
        """
        # Compare shot data including workspace paths
        old_shot_data = {(shot.full_name, shot.workspace_path) for shot in self.shots}
        new_shot_data = {(shot.full_name, shot.workspace_path) for shot in new_shots}
        return old_shot_data != new_shot_data

    def get_shots(self) -> list[Shot]:
        """Get current list of shots.

        Returns:
            List of Shot objects
        """
        return self.shots

    def get_shot_count(self) -> int:
        """Get number of shots.

        Returns:
            Number of shots
        """
        return len(self.shots)

    def select_shot(self, shot: Shot | None) -> None:
        """Select a shot and emit signal.

        Args:
            shot: Shot to select or None to clear selection
        """
        self._selected_shot = shot
        self.shot_selected.emit(shot)

    def get_selected_shot(self) -> Shot | None:
        """Get currently selected shot.

        Returns:
            Selected shot or None
        """
        return self._selected_shot

    def find_shot_by_name(self, full_name: str) -> Shot | None:
        """Find a shot by its full name.

        Args:
            full_name: Full shot name (SHOW.SEQ.SHOT)

        Returns:
            Shot object if found, None otherwise
        """
        for shot in self.shots:
            if shot.full_name == full_name:
                return shot
        return None

    def get_performance_metrics(self) -> PerformanceMetricsDict:
        """Get performance metrics.

        Returns:
            Performance metrics dictionary
        """
        cache_total = self._cache_hits + self._cache_misses
        return {
            "total_shots": len(self.shots),
            "total_refreshes": self._total_refreshes,
            "last_refresh_time": self._last_refresh_time,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits / max(1, cache_total),
            # Extended metrics for compatibility (defaults for base model)
            "cache_hit_count": self._cache_hits,
            "cache_miss_count": self._cache_misses,
            "loading_in_progress": False,
            "session_warmed": len(self.shots) > 0,
        }

    def set_show_filter(self, show: str | None) -> None:
        """Set the show filter.

        Args:
            show: Show name to filter by or None for all shows
        """
        self._filter_show = show
        self.logger.info(f"Show filter set to: {show if show else 'All Shows'}")

    def get_show_filter(self) -> str | None:
        """Get the current show filter."""
        return self._filter_show

    def set_text_filter(self, text: str | None) -> None:
        """Set the text filter for real-time search.

        Args:
            text: Text to filter by (case-insensitive substring match) or None for no filter
        """
        self._filter_text = text
        self.logger.info(f"Text filter set to: '{text if text else ''}'")

    def get_text_filter(self) -> str | None:
        """Get the current text filter."""
        return self._filter_text

    def get_filtered_shots(self) -> list[Shot]:
        """Get shots filtered by show and text filters.

        Applies both show filter and text filter (AND logic).

        Returns:
            Filtered list of shots
        """
        filtered = compose_filters(
            self.shots, show=self._filter_show, text=self._filter_text
        )

        self.logger.debug(
            f"Filtered {len(self.shots)} shots to {len(filtered)} "
             f"(show='{self._filter_show}', text='{self._filter_text}')"
        )
        return filtered

    def get_available_shows(self) -> set[str]:
        """Get all unique show names from current shots.

        Returns:
            Set of unique show names
        """
        return get_available_shows(self.shots)

    @abstractmethod
    def load_shots(self) -> RefreshResult:
        """Load shots using implementation-specific strategy.

        Subclasses must implement this to provide either synchronous
        or asynchronous loading behavior.

        Returns:
            RefreshResult with success and change status
        """

    @abstractmethod
    def refresh_strategy(self) -> RefreshResult:
        """Refresh shot list using implementation-specific strategy.

        Subclasses must implement this to define how refreshing works
        (e.g., synchronous blocking vs asynchronous background).

        Returns:
            RefreshResult with success and change status
        """

    def refresh_shots(self) -> RefreshResult:
        """Public API to refresh shots.

        Delegates to implementation-specific refresh_strategy.

        Returns:
            RefreshResult with success and change status
        """
        self._total_refreshes += 1
        return self.refresh_strategy()
