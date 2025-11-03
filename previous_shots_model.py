"""Model for managing previous/approved shots data."""

from __future__ import annotations

# Standard library imports
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker, QObject, Qt, Signal

# Local application imports
from cache_manager import CacheManager
from logging_mixin import LoggingMixin
from previous_shots_finder import ParallelShotsFinder
from previous_shots_worker import PreviousShotsWorker
from shot_filter import compose_filters, get_available_shows
from shot_model import Shot
from type_definitions import ShotDict


if TYPE_CHECKING:
    # Local application imports
    from base_shot_model import BaseShotModel


@final
class PreviousShotsModel(LoggingMixin, QObject):
    """Model for managing approved shots that are no longer active.

    This model maintains a list of shots the user has worked on that
    are no longer in the active workspace (i.e., approved/completed).
    """

    # Signals
    shots_updated = Signal()
    scan_started = Signal()
    scan_finished = Signal()
    scan_progress = Signal(int, int)  # current, total

    def __init__(
        self,
        shot_model: BaseShotModel,
        cache_manager: CacheManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the previous shots model.

        Args:
            shot_model: The active shots model to compare against.
            cache_manager: Optional cache manager for persistence.
            parent: Optional parent QObject.
        """
        super().__init__(parent)

        self._shot_model = shot_model
        self._cache_manager = cache_manager or CacheManager()
        self._finder = ParallelShotsFinder()
        self._previous_shots: list[Shot] = []
        self._is_scanning = False
        self._worker: PreviousShotsWorker | None = None
        self._filter_show: str | None = None  # Show filter
        self._filter_text: str | None = None  # Text filter for real-time search

        # THREAD SAFETY: Lock for protecting _is_scanning flag
        self._scan_lock = QMutex()

        # Load from cache on init (persistent cache - no expiration)
        self._previous_shots = self._load_from_cache()  # Now returns list

        self.logger.info("PreviousShotsModel initialized")

    @contextmanager
    def _scanning_lock(self) -> Generator[bool, None, None]:
        """Context manager for scanning lock with guaranteed cleanup.

        Yields:
            True if lock acquired, False if already scanning

        Usage:
            with self._scanning_lock() as acquired:
                if not acquired:
                    return False
                # ... do work ...
            # Lock automatically released here

        Note: For async operations (like refresh_shots), use manual lock management
        with _reset_scanning_flag() for cleanup instead.
        """
        # Try to acquire
        with QMutexLocker(self._scan_lock):
            if self._is_scanning:
                self.logger.debug("Scan lock already held")
                yield False
                return
            self._is_scanning = True
            self.logger.debug("Acquired scan lock")

        try:
            yield True
        finally:
            # Guaranteed cleanup even on exceptions
            with QMutexLocker(self._scan_lock):
                self._is_scanning = False
                self.logger.debug("Released scan lock")

    def _reset_scanning_flag(self) -> None:
        """Reset the scanning flag with proper locking.

        This is a convenience method for callbacks and error handlers
        that need to reset the flag after async operations complete.
        """
        with QMutexLocker(self._scan_lock):
            self._is_scanning = False
            self.logger.debug("Reset scanning flag")

    # Auto-refresh removed for persistent incremental caching
    # Previous shots now use a persistent cache that accumulates over time
    # Only refreshes when user explicitly clicks "Refresh" button

    def _cleanup_worker_safely(self) -> None:
        """Centralized worker cleanup to prevent race conditions and crashes.

        This method ensures proper cleanup sequence:
        1. Request stop first
        2. Wait with timeout to prevent hanging
        3. Clear reference before deletion
        4. Disconnect signals to prevent late emissions
        5. Schedule deletion on event loop
        """
        with QMutexLocker(self._scan_lock):
            if self._worker is not None:
                self.logger.debug("Safely cleaning up worker thread")

                # 1. Request stop first
                self._worker.stop()

                # 2. Wait with timeout (prevent hanging)
                if not self._worker.wait(2000):
                    self.logger.warning("Worker did not stop gracefully within 2s")
                    # Force termination if necessary
                    if self._worker.isRunning():
                        self._worker.terminate()
                        _ = self._worker.wait(1000)

                # 3. Clear reference BEFORE scheduling deletion
                worker = self._worker
                self._worker = None

                # 4. Disconnect all signals to prevent late emissions
                # Note: We check receivers() before disconnecting to avoid RuntimeWarnings
                # from Qt when attempting to disconnect signals that have no connections.
                # Qt's receivers() method is not properly typed in PySide6 stubs
                try:
                    if worker.scan_finished.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                        _ = worker.scan_finished.disconnect()
                    if worker.error_occurred.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                        _ = worker.error_occurred.disconnect()
                    # PreviousShotsWorker uses scan_progress, not progress
                    # ThreeDESceneWorker uses progress signal
                    # Runtime hasattr check handles polymorphism - attribute may not exist
                    if hasattr(worker, "progress") and worker.progress.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                        worker.progress.disconnect()  # pyright: ignore[reportAttributeAccessIssue]
                except (RuntimeError, TypeError, AttributeError):
                    pass  # Already disconnected or no connections

                # 5. Schedule deletion on event loop
                worker.deleteLater()
                self.logger.debug("Worker thread cleanup completed")

    def refresh_shots(self) -> bool:
        """Refresh the list of previous shots using a background worker thread.

        Uses incremental caching strategy: new shots are merged with existing cache.
        The cache is never cleared unless explicitly requested via clear_cache().

        Returns:
            True if refresh was started, False if already scanning.
        """
        # Check and acquire lock atomically
        with QMutexLocker(self._scan_lock):
            if self._is_scanning:
                self.logger.debug("Already scanning for previous shots")
                return False
            self._is_scanning = True

        self.scan_started.emit()

        # Note: We do NOT clear caches - incremental merge preserves existing cache
        # This allows persistent accumulation of approved shots over time

        try:
            # Stop any existing worker
            if self._worker is not None:
                self.logger.debug("Stopping existing worker before starting new scan")
                self._cleanup_worker_safely()

            # Get active shots from the main model
            active_shots = self._shot_model.get_shots()

            # Create and configure worker thread
            # Local application imports
            from config import Config

            self._worker = PreviousShotsWorker(
                active_shots=active_shots,
                username=self._finder.username,
                shows_root=Path(Config.SHOWS_ROOT),  # Use configured shows root
                parent=self,  # Set parent for proper cleanup hierarchy
            )

            # Connect worker signals with QueuedConnection for thread safety
            _ = self._worker.scan_finished.connect(
                self._on_scan_finished, Qt.ConnectionType.QueuedConnection
            )
            _ = self._worker.error_occurred.connect(
                self._on_scan_error, Qt.ConnectionType.QueuedConnection
            )

            # Start worker thread
            self.logger.info("Starting previous shots scan in background thread")
            self._worker.start()

            return True

        except Exception as e:
            self.logger.error(f"Error starting previous shots scan: {e}")
            # Reset flag on error (worker not started)
            self._reset_scanning_flag()
            self.scan_finished.emit()
            return False

    def _on_scan_finished(self, approved_shots: list[dict[str, str]]) -> None:
        """Handle worker completion with incremental merge strategy.

        This method merges newly discovered shots with existing cached shots,
        implementing persistent incremental caching.

        Args:
            approved_shots: List of approved shot dictionaries found by worker.
        """
        try:
            # Convert dictionaries to Shot objects
            newly_found_shots: list[Shot] = (
                [
                    Shot(
                        show=shot_dict["show"],
                        sequence=shot_dict["sequence"],
                        shot=shot_dict["shot"],
                        workspace_path=shot_dict["workspace_path"],
                    )
                    for shot_dict in approved_shots
                ]
                if approved_shots
                else []
            )

            # Incremental merge: combine existing cache with new findings
            # Create set of existing shot IDs for fast lookup
            existing_ids = {(s.show, s.sequence, s.shot) for s in self._previous_shots}

            # Find truly new shots (not in existing cache)
            new_shots = [
                shot
                for shot in newly_found_shots
                if (shot.show, shot.sequence, shot.shot) not in existing_ids
            ]

            if new_shots:
                # Merge: keep existing + add new
                self._previous_shots.extend(new_shots)
                self._save_to_cache()
                self.shots_updated.emit()
                self.logger.info(
                    f"Added {len(new_shots)} new shots to cache "
                     f"(total: {len(self._previous_shots)} shots)"
                )
            else:
                self.logger.debug("No new shots found - cache unchanged")

        except Exception as e:
            self.logger.error(f"Error processing scan results: {e}")
        finally:
            # Reset scanning flag using helper method
            self._reset_scanning_flag()
            # Use centralized cleanup
            self._cleanup_worker_safely()
            self.scan_finished.emit()

    def _on_scan_error(self, error_msg: str) -> None:
        """Handle worker error.

        Args:
            error_msg: Error message from worker.
        """
        self.logger.error(f"Previous shots scan error: {error_msg}")
        # Reset scanning flag using helper method
        self._reset_scanning_flag()
        # Use centralized cleanup
        self._cleanup_worker_safely()
        self.scan_finished.emit()

    def _has_changes(self, new_shots: list[Shot]) -> bool:
        """Check if the shot list has changed.

        Args:
            new_shots: New list of shots to compare.

        Returns:
            True if there are changes, False otherwise.
        """
        if len(new_shots) != len(self._previous_shots):
            return True

        # Create sets for comparison
        current_ids = {(s.show, s.sequence, s.shot) for s in self._previous_shots}
        new_ids = {(s.show, s.sequence, s.shot) for s in new_shots}

        return current_ids != new_ids

    def get_shots(self) -> list[Shot]:
        """Get the list of previous/approved shots.

        Returns:
            List of Shot objects for approved shots.
        """
        return self._previous_shots.copy()

    def get_shot_count(self) -> int:
        """Get the number of previous shots.

        Returns:
            Number of approved shots.
        """
        return len(self._previous_shots)

    def get_shot_by_name(self, shot_name: str) -> Shot | None:
        """Get a shot by its name.

        Args:
            shot_name: Name of the shot to find.

        Returns:
            Shot object if found, None otherwise.
        """
        for shot in self._previous_shots:
            if shot.shot == shot_name:
                return shot
        return None

    def get_shot_details(self, shot: Shot) -> dict[str, str]:
        """Get detailed information about a shot.

        Args:
            shot: Shot to get details for.

        Returns:
            Dictionary with shot details.
        """
        # Finder returns ShotDetailsDict (TypedDict with all str values)
        # Convert to dict[str, str] with cast after validation
        details = self._finder.get_shot_details(shot)
        # All fields in ShotDetailsDict are str, so this cast is safe
        return cast("dict[str, str]", dict(details))

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
            self._previous_shots, show=self._filter_show, text=self._filter_text
        )

        self.logger.debug(
            f"Filtered {len(self._previous_shots)} shots to {len(filtered)} "
             f"(show='{self._filter_show}', text='{self._filter_text}')"
        )
        return filtered

    def get_available_shows(self) -> set[str]:
        """Get all unique show names from current shots.

        Returns:
            Set of unique show names
        """
        return get_available_shows(self._previous_shots)

    def _load_from_cache(self) -> list[Shot]:
        """Load previous shots from persistent cache, merging migrated + scanned.

        Returns:
            List of Shot objects (empty list if no cache)
        """
        try:
            # Load both sources
            scanned_data = self._cache_manager.get_cached_previous_shots() or []
            migrated_data = self._cache_manager.get_migrated_shots() or []

            # Merge with deduplication using composite key
            shots_by_key: dict[tuple[str, str, str], ShotDict] = {}

            for shot_dict in scanned_data:
                key = (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
                shots_by_key[key] = shot_dict

            for shot_dict in migrated_data:
                key = (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
                shots_by_key[key] = shot_dict  # Overwrites if duplicate (prefer migrated)

            # Convert to Shot objects
            shots = [
                Shot(
                    show=s["show"],
                    sequence=s["sequence"],
                    shot=s["shot"],
                    workspace_path=s.get("workspace_path", ""),
                )
                for s in shots_by_key.values()
            ]

            self.logger.info(
                f"Loaded {len(scanned_data)} scanned + {len(migrated_data)} migrated "
                 f"= {len(shots)} total (after dedup)"
            )

            return shots

        except Exception as e:
            self.logger.error(f"Error loading previous shots from cache: {e}")
            return []

    def _save_to_cache(self) -> None:
        """Save previous shots to cache."""
        try:
            cache_data: list[ShotDict] = [
                ShotDict(
                    show=s.show,
                    sequence=s.sequence,
                    shot=s.shot,
                    workspace_path=s.workspace_path,
                )
                for s in self._previous_shots
            ]
            # Use the correct method: cache_previous_shots()
            self._cache_manager.cache_previous_shots(cache_data)
            self.logger.debug(
                f"Saved {len(self._previous_shots)} previous shots to cache"
            )
        except Exception as e:
            self.logger.error(f"Error saving previous shots to cache: {e}")

    def clear_cache(self) -> None:
        """Clear the cached previous shots."""
        try:
            self._cache_manager.clear_cached_data("previous_shots")
            self.logger.info("Cleared previous shots cache")
        except Exception as e:
            self.logger.error(f"Error clearing previous shots cache: {e}")

    def _clear_caches_for_refresh(self) -> None:
        """Clear all relevant caches for manual refresh.

        This method clears directory caches, path caches, and filesystem caches
        to ensure fresh data when manually refreshing.
        """
        try:
            # Clear our own cache
            self.clear_cache()

            # Clear directory cache in 3DE scene finder
            # Local application imports
            from threede_scene_finder import ThreeDESceneFinder

            if hasattr(ThreeDESceneFinder, "refresh_cache"):
                cleared_count = ThreeDESceneFinder.refresh_cache()
                self.logger.debug(f"Cleared {cleared_count} directory cache entries")

            # Clear path cache in utils
            # Local application imports
            from utils import clear_all_caches

            clear_all_caches()
            self.logger.debug("Cleared path validation caches")

            self.logger.info("Successfully cleared all caches for manual refresh")

        except Exception as e:
            self.logger.error(f"Error clearing caches for refresh: {e}")

    def cleanup(self) -> None:
        """Clean up resources and stop worker thread."""
        self.logger.debug("PreviousShotsModel cleanup initiated")
        self._cleanup_worker_safely()  # Use centralized cleanup
        self.logger.info("PreviousShotsModel cleanup completed")

    def is_scanning(self) -> bool:
        """Check if currently scanning for shots.

        Returns:
            True if scanning is in progress.
        """
        # THREAD SAFETY: Use lock when reading _is_scanning
        with QMutexLocker(self._scan_lock):
            return self._is_scanning
