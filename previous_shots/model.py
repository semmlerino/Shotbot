"""Model for managing previous/approved shots data."""

from __future__ import annotations

import logging

# Standard library imports
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast, final

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker, Qt, Signal, Slot
from typing_extensions import override

# Local application imports
from managers._shot_key import shot_key
from previous_shots.finder import ParallelShotsFinder
from previous_shots.worker import PreviousShotsWorker
from type_definitions import Shot
from ui.base_shot_model import BaseShotModel
from utils import safe_disconnect
from workers.worker_host import WorkerHost


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Local application imports
    from cache.shot_cache import ShotDataCache
    from type_definitions import RefreshResult, ShotDict


@final
class PreviousShotsModel(BaseShotModel):
    """Model for managing approved shots that are no longer active.

    This model maintains a list of shots the user has worked on that
    are no longer in the active workspace (i.e., approved/completed).

    Inherits common shot model infrastructure (signals, cache, accessors)
    from BaseShotModel and overrides cache strategy for persistent
    incremental caching of previous shots.
    """

    # Previous shots-specific signals (in addition to inherited BaseShotModel signals)
    shots_updated: ClassVar[Signal] = Signal()
    scan_started: ClassVar[Signal] = Signal()
    scan_finished: ClassVar[Signal] = Signal()
    scan_progress: ClassVar[Signal] = Signal(int, int)  # current, total

    def __init__(
        self,
        shot_model: BaseShotModel,
        cache_manager: ShotDataCache | None = None,
    ) -> None:
        """Initialize the previous shots model.

        Args:
            shot_model: The active shots model to compare against.
            cache_manager: Optional cache manager for persistence.

        """
        # Initialize BaseShotModel with load_cache=False; we load via our own
        # _load_from_cache() override after additional setup is done.
        super().__init__(cache_manager, load_cache=False, process_pool=None)

        self._shot_model = shot_model
        self._finder = ParallelShotsFinder()
        self._is_scanning = False
        self._worker_host: WorkerHost[PreviousShotsWorker] = WorkerHost()

        # THREAD SAFETY: Lock for protecting _is_scanning flag
        self._scan_lock = QMutex()

        # Load from cache on init (persistent cache - no expiration)
        # self.shots is populated here via our overridden _load_from_cache()
        self.shots = self._load_previous_shots_from_cache()

        logger.debug("PreviousShotsModel initialized")

        # Connect directly to cache migration events (bypasses MainWindow relay)
        if hasattr(self.cache_manager, "shots_migrated"):
            _ = self.cache_manager.shots_migrated.connect(
                self._on_cache_shots_migrated,  # pyright: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )

    @override
    def _load_from_cache(self) -> bool:
        """Override base cache loading with previous-shots-specific strategy.

        Returns:
            False — previous shots cache is loaded separately in __init__
            via _load_previous_shots_from_cache() to keep the two-source
            merge logic isolated.

        """
        # Base class calls this during __init__ when load_cache=True.
        # We pass load_cache=False so this is never called by the base.
        # Overridden here as a safety net to prevent the base implementation
        # from overwriting self.shots with active-shot cache data.
        return False

    def _load_previous_shots_from_cache(self) -> list[Shot]:
        """Load previous shots from persistent cache, merging migrated + scanned.

        Returns:
            List of Shot objects (empty list if no cache)

        """
        try:
            # Load both sources (persistent - no TTL expiration)
            scanned_data: list[ShotDict] = (
                self.cache_manager.get_persistent_previous_shots() or []
            )
            migrated_data: list[ShotDict] = (
                self.cache_manager.get_shots_archive() or []
            )

            # Merge with deduplication using composite key
            shots_by_key: dict[tuple[str, str, str], ShotDict] = {}

            for shot_dict in scanned_data:
                key = (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
                shots_by_key[key] = shot_dict

            for shot_dict in migrated_data:
                key = (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
                shots_by_key[key] = (
                    shot_dict  # Overwrites if duplicate (prefer migrated)
                )

            # Convert to Shot objects using from_dict() to preserve discovered_at
            shots = [Shot.from_dict(s) for s in shots_by_key.values()]

            logger.info(
                f"Loaded {len(scanned_data)} scanned + {len(migrated_data)} migrated "
                f"= {len(shots)} total (after dedup)"
            )

            return shots

        except Exception:
            logger.exception("Error loading previous shots from cache")
            return []

    # =========================================================================
    # BaseShotModel abstract method implementations
    # =========================================================================



    @override
    def refresh_strategy(self) -> RefreshResult:
        """Implement abstract method — starts background scan.

        Returns:
            RefreshResult indicating background scan was initiated.

        """
        from type_definitions import RefreshResult

        _ = self.refresh_shots()
        return RefreshResult(success=True, has_changes=False)

    # =========================================================================
    # Previous shots-specific public API
    # =========================================================================

    def _reset_scanning_flag(self) -> None:
        """Reset the scanning flag with proper locking.

        This is a convenience method for callbacks and error handlers
        that need to reset the flag after async operations complete.
        """
        with QMutexLocker(self._scan_lock):
            self._is_scanning = False
            logger.debug("Reset scanning flag")

    # Auto-refresh removed for persistent incremental caching
    # Previous shots now use a persistent cache that accumulates over time
    # Only refreshes when user explicitly clicks "Refresh" button

    def _cleanup_worker_safely(self) -> None:
        """Centralized worker cleanup to prevent race conditions and crashes.

        Uses two-phase pattern to avoid holding lock during blocking wait().

        This method ensures proper cleanup sequence:
        1. Grab reference and clear atomically (fast)
        2. Request stop, wait, and cleanup OUTSIDE lock (may block)
        """
        # Phase 1: Atomically capture and clear the worker reference
        worker = self._worker_host.take()

        if worker is None:
            return

        # Phase 2: Stop, wait, and cleanup OUTSIDE lock (avoids UI freeze)
        logger.debug("Safely cleaning up worker thread")

        # Disconnect all signals to prevent late emissions
        safe_disconnect(worker.scan_finished, worker.worker_error, worker.scan_progress)

        worker.safe_shutdown()
        logger.debug("Worker thread cleanup completed")

    @override
    def refresh_shots(self) -> bool:  # type: ignore[override]
        """Refresh the list of previous shots using a background worker thread.

        Overrides BaseShotModel.refresh_shots() with background-scan semantics.
        Uses incremental caching strategy: new shots are merged with existing cache.
        The cache is never cleared unless explicitly requested via clear_cache().

        Returns:
            True if refresh was started, False if already scanning.

        """
        # Check and acquire lock atomically
        with QMutexLocker(self._scan_lock):
            if self._is_scanning:
                logger.debug("Already scanning for previous shots")
                return False
            self._is_scanning = True

        self.scan_started.emit()

        # Note: We do NOT clear caches - incremental merge preserves existing cache
        # This allows persistent accumulation of approved shots over time

        try:
            # Stop any existing worker
            if self._worker_host.has_worker:
                logger.debug("Stopping existing worker before starting new scan")
                self._cleanup_worker_safely()

            # Get active shots from the main model
            active_shots = self._shot_model.get_shots()

            # Create and configure worker thread
            # Local application imports
            from config import Config

            worker = PreviousShotsWorker(
                active_shots=active_shots,
                username=self._finder.username,
                shows_root=Path(Config.Paths.SHOWS_ROOT),  # Use configured shows root
                parent=self,  # Set parent for proper cleanup hierarchy
            )

            # Connect worker signals with QueuedConnection for thread safety
            _ = worker.scan_finished.connect(
                self._on_scan_finished, Qt.ConnectionType.QueuedConnection
            )
            _ = worker.scan_progress.connect(
                self._on_worker_progress, Qt.ConnectionType.QueuedConnection
            )
            _ = worker.worker_error.connect(
                self._on_scan_error, Qt.ConnectionType.QueuedConnection
            )

            self._worker_host.store(worker)

            # Start worker thread
            logger.info("Starting previous shots scan in background thread")
            worker.start()

            return True

        except Exception:
            logger.exception("Error starting previous shots scan")
            # Reset flag on error (worker not started)
            self._reset_scanning_flag()
            self.scan_finished.emit()
            return False

    @Slot(list)  # pyright: ignore[reportAny]
    def _on_cache_shots_migrated(self, migrated_shots: list[ShotDict]) -> None:
        """Handle shots migrated to Previous Shots cache.

        Connected directly to ShotDataCache.shots_migrated, bypassing
        MainWindow relay for simpler signal routing.

        Merges the migrated payload directly into the in-memory list and
        persists it — no filesystem scan required.

        Args:
            migrated_shots: List of ShotDict objects that were migrated

        """
        if not migrated_shots:
            return

        logger.info(
            f"{len(migrated_shots)} shots migrated to Previous Shots cache"
        )

        # Build a set of existing (show, sequence, shot) keys for deduplication
        existing_ids = {shot_key(s) for s in self.shots}

        # Convert incoming ShotDicts to Shot objects, skipping duplicates
        new_shots = [
            Shot.from_dict(shot_dict)
            for shot_dict in migrated_shots
            if (shot_dict["show"], shot_dict["sequence"], shot_dict["shot"])
            not in existing_ids
        ]

        if not new_shots:
            logger.debug("All migrated shots already present — cache unchanged")
            return

        self.shots.extend(new_shots)
        self._save_to_cache()
        self.shots_updated.emit()
        logger.info(
            f"Merged {len(new_shots)} migrated shots "
            f"(total: {len(self.shots)} shots)"
        )

    def _on_scan_finished(self, approved_shots: list[dict[str, str]]) -> None:
        """Handle worker completion with incremental merge strategy.

        This method merges newly discovered shots with existing cached shots,
        implementing persistent incremental caching.

        Args:
            approved_shots: List of approved shot dictionaries found by worker.

        """
        try:
            # Local application imports
            from discovery import extract_frame_range

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
            existing_ids = {shot_key(s) for s in self.shots}

            # Find truly new shots (not in existing cache)
            new_shots = [
                shot
                for shot in newly_found_shots
                if shot_key(shot) not in existing_ids
            ]

            if new_shots:
                # Merge: keep existing + add new
                self.shots.extend(new_shots)
                self._save_to_cache()
                self.shots_updated.emit()
                logger.info(
                    f"Added {len(new_shots)} new shots to cache "
                    f"(total: {len(self.shots)} shots)"
                )
            else:
                logger.debug("No new shots found - cache unchanged")

        except Exception:
            logger.exception("Error processing scan results")
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
        logger.error(f"Previous shots scan error: {error_msg}")
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

    @override
    def get_shots(self) -> list[Shot]:
        """Get the list of previous/approved shots.

        Overrides BaseShotModel.get_shots() to return a defensive copy,
        preventing external mutations of the internal shot list.

        Returns:
            Copy of the list of Shot objects for approved shots.

        """
        return self.shots.copy()

    def get_shot_by_name(self, shot_name: str) -> Shot | None:
        """Get a shot by its name.

        Args:
            shot_name: Name of the shot to find.

        Returns:
            Shot object if found, None otherwise.

        """
        for shot in self.shots:
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

    def _save_to_cache(self) -> None:
        """Save previous shots to cache."""
        try:
            # Use to_dict() to include discovered_at timestamp
            cache_data: list[ShotDict] = [s.to_dict() for s in self.shots]
            # Use the correct method: cache_previous_shots()
            self.cache_manager.cache_previous_shots(cache_data)
            logger.debug(
                f"Saved {len(self.shots)} previous shots to cache"
            )
        except Exception:
            logger.exception("Error saving previous shots to cache")

    def clear_cache(self) -> None:
        """Clear the cached previous shots."""
        try:
            self.cache_manager.clear_previous_shots_cache()
            logger.info("Cleared previous shots cache")
        except Exception:
            logger.exception("Error clearing previous shots cache")

    def cleanup(self) -> None:
        """Clean up resources and stop worker thread."""
        import warnings

        logger.debug("PreviousShotsModel cleanup initiated")
        # Disconnect cache migration signal (only if it was connected)
        if hasattr(self.cache_manager, "shots_migrated"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    _ = self.cache_manager.shots_migrated.disconnect(
                        self._on_cache_shots_migrated
                    )  # pyright: ignore[reportAny]
                except (RuntimeError, TypeError):
                    pass  # Already disconnected
        self._cleanup_worker_safely()  # Use centralized cleanup
        logger.debug("PreviousShotsModel cleanup completed")

    def is_scanning(self) -> bool:
        """Check if currently scanning for shots.

        Returns:
            True if scanning is in progress.

        """
        # THREAD SAFETY: Use lock when reading _is_scanning
        with QMutexLocker(self._scan_lock):
            return self._is_scanning
