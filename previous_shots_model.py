"""Model for managing previous/approved shots data."""

from __future__ import annotations

# Standard library imports
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker, QObject, Qt, Signal

# Local application imports
from cache.shot_cache import ShotDataCache
from logging_mixin import LoggingMixin
from previous_shots_finder import ParallelShotsFinder
from previous_shots_worker import PreviousShotsWorker
from shot_filter import compose_filters, get_available_shows
from shot_model import Shot


if TYPE_CHECKING:
    # Local application imports
    from base_shot_model import BaseShotModel
    from type_definitions import ShotDict


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
        cache_manager: ShotDataCache | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the previous shots model.

        Args:
            shot_model: The active shots model to compare against.
            cache_manager: Optional cache manager for persistence.
            parent: Optional parent QObject.

        """
        super().__init__(parent)

        if cache_manager is None:
            import os
            import sys

            test_cache_dir = os.getenv("SHOTBOT_TEST_CACHE_DIR")
            if test_cache_dir:
                _default_dir = Path(test_cache_dir)
            elif "pytest" in sys.modules or os.getenv("SHOTBOT_MODE") == "test":
                _default_dir = Path.home() / ".shotbot" / "cache_test"
            elif os.getenv("SHOTBOT_MODE") == "mock":
                _default_dir = Path.home() / ".shotbot" / "cache" / "mock"
            else:
                _default_dir = Path.home() / ".shotbot" / "cache" / "production"
            _default_dir.mkdir(parents=True, exist_ok=True)
            cache_manager = ShotDataCache(_default_dir)

        self._shot_model = shot_model
        self._cache_manager: ShotDataCache = cache_manager
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

        self.logger.debug("PreviousShotsModel initialized")

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

        Uses two-phase pattern to avoid holding lock during blocking wait().

        This method ensures proper cleanup sequence:
        1. Grab reference and clear under lock (fast)
        2. Request stop, wait, and cleanup OUTSIDE lock (may block)
        """
        # Phase 1: Grab reference and clear under lock (fast, non-blocking)
        worker: PreviousShotsWorker | None = None
        with QMutexLocker(self._scan_lock):
            if self._worker is not None:
                worker = self._worker
                self._worker = None  # Clear immediately to prevent double-cleanup

        if worker is None:
            return

        # Phase 2: Stop, wait, and cleanup OUTSIDE lock (avoids UI freeze)
        self.logger.debug("Safely cleaning up worker thread")

        # Request stop
        worker.stop()

        # Wait with timeout (prevent hanging)
        if not worker.wait(2000):
            self.logger.warning("Worker did not stop gracefully within 2s")
            # Use safe_terminate which captures diagnostics and avoids raw terminate()
            if worker.isRunning():
                worker.safe_terminate()
                # safe_terminate already handles waiting and zombie tracking

        # Disconnect all signals to prevent late emissions
        # Note: We check receivers() before disconnecting to avoid RuntimeWarnings
        # from Qt when attempting to disconnect signals that have no connections.
        # Qt's receivers() method is not properly typed in PySide6 stubs
        try:
            if worker.scan_finished.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                _ = worker.scan_finished.disconnect()
            if worker.error_occurred.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                _ = worker.error_occurred.disconnect()
            # PreviousShotsWorker uses scan_progress, not progress
            # ThreeDESceneWorker uses progress signal
            # Runtime hasattr check handles polymorphism - attribute may not exist
            if hasattr(worker, "progress") and worker.progress.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                worker.progress.disconnect()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        except (RuntimeError, TypeError, AttributeError):
            pass  # Already disconnected or no connections

        # Schedule deletion on event loop
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
            _ = self._worker.scan_progress.connect(
                self._on_worker_progress, Qt.ConnectionType.QueuedConnection
            )
            _ = self._worker.error_occurred.connect(
                self._on_scan_error, Qt.ConnectionType.QueuedConnection
            )

            # Start worker thread
            self.logger.info("Starting previous shots scan in background thread")
            self._worker.start()

            return True

        except Exception:
            self.logger.exception("Error starting previous shots scan")
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
            # Local application imports
            from frame_range_extractor import extract_frame_range

            # Convert dictionaries to Shot objects with current timestamp
            current_time = time.time()
            newly_found_shots: list[Shot] = []

            if approved_shots:
                for shot_dict in approved_shots:
                    # Extract frame range for scrub preview
                    frame_range = extract_frame_range(shot_dict["workspace_path"])
                    frame_start = frame_range[0] if frame_range else None
                    frame_end = frame_range[1] if frame_range else None

                    newly_found_shots.append(
                        Shot(
                            show=shot_dict["show"],
                            sequence=shot_dict["sequence"],
                            shot=shot_dict["shot"],
                            workspace_path=shot_dict["workspace_path"],
                            discovered_at=current_time,
                            frame_start=frame_start,
                            frame_end=frame_end,
                        )
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

        except Exception:
            self.logger.exception("Error processing scan results")
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

    def _on_worker_progress(self, current: int, total: int, message: str) -> None:
        """Forward worker progress to model signal.

        Args:
            current: Current progress value
            total: Total progress value
            message: Progress message (not forwarded, model signal is simpler)

        """
        self.scan_progress.emit(current, total)

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
            # Load both sources (persistent - no TTL expiration)
            # Cast required because get_persistent_previous_shots is dynamically added
            scanned_data = cast(
                "list[ShotDict]",
                self._cache_manager.get_persistent_previous_shots() or [],  # type: ignore[attr-defined]
            )
            migrated_data: list[ShotDict] = self._cache_manager.get_shots_archive() or []

            # Merge with deduplication using composite key
            shots_by_key: dict[tuple[str, str, str], ShotDict] = {}

            for shot_dict in scanned_data:
                key = (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
                shots_by_key[key] = shot_dict

            for shot_dict in migrated_data:
                key = (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
                shots_by_key[key] = shot_dict  # Overwrites if duplicate (prefer migrated)

            # Convert to Shot objects using from_dict() to preserve discovered_at
            shots = [Shot.from_dict(s) for s in shots_by_key.values()]

            self.logger.info(
                f"Loaded {len(scanned_data)} scanned + {len(migrated_data)} migrated "
                 f"= {len(shots)} total (after dedup)"
            )

            return shots

        except Exception:
            self.logger.exception("Error loading previous shots from cache")
            return []

    def _save_to_cache(self) -> None:
        """Save previous shots to cache."""
        try:
            # Use to_dict() to include discovered_at timestamp
            cache_data: list[ShotDict] = [s.to_dict() for s in self._previous_shots]
            # Use the correct method: cache_previous_shots()
            self._cache_manager.cache_previous_shots(cache_data)
            self.logger.debug(
                f"Saved {len(self._previous_shots)} previous shots to cache"
            )
        except Exception:
            self.logger.exception("Error saving previous shots to cache")

    def clear_cache(self) -> None:
        """Clear the cached previous shots."""
        try:
            self._cache_manager.clear_cached_data("previous_shots")
            self.logger.info("Cleared previous shots cache")
        except Exception:
            self.logger.exception("Error clearing previous shots cache")

    def cleanup(self) -> None:
        """Clean up resources and stop worker thread."""
        self.logger.debug("PreviousShotsModel cleanup initiated")
        self._cleanup_worker_safely()  # Use centralized cleanup
        self.logger.debug("PreviousShotsModel cleanup completed")

    def is_scanning(self) -> bool:
        """Check if currently scanning for shots.

        Returns:
            True if scanning is in progress.

        """
        # THREAD SAFETY: Use lock when reading _is_scanning
        with QMutexLocker(self._scan_lock):
            return self._is_scanning
