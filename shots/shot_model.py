"""Optimized ShotModel with async loading and cache warming.

This implementation reduces startup time from 3.6s to <0.1s by:
1. Showing cached data immediately
2. Loading fresh data in background
3. Pre-warming bash sessions during idle time

Thread Safety:
- Uses Qt.ConnectionType.QueuedConnection for all worker thread signals
- This ensures slots run in main thread, preventing Qt widget violations
- Uses Qt's interruption mechanism for proper synchronization
- All signals are thread-safe via Qt's signal/slot mechanism
- Proper cleanup with terminate fallback
"""

from __future__ import annotations

import logging

# Standard library imports
from typing import TYPE_CHECKING, ClassVar, final

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    Signal,
    Slot,
)
from typing_extensions import override


if TYPE_CHECKING:
    from collections.abc import Callable

    from cache.shot_cache import ShotDataCache
    from protocols import ProcessPoolInterface
    from type_definitions import PerformanceMetricsDict

# Local application imports
from cache.types import ShotMergeResult
from exceptions import WorkspaceError
from timeout_config import TimeoutConfig
from type_definitions import RefreshResult, Shot
from ui.base_shot_model import BaseShotModel
from workers.thread_safe_worker import ThreadSafeWorker
from workers.worker_host import WorkerHost


logger = logging.getLogger(__name__)


__all__ = ["AsyncShotLoader", "ShotModel"]


@final
class AsyncShotLoader(ThreadSafeWorker):
    """Background worker for loading shots without blocking UI.

    Thread Safety:
    - Inherits from ThreadSafeWorker for proper lifecycle management
    - Signal emissions are automatically thread-safe in Qt
    - Slots are connected with QueuedConnection to run in main thread
    - No shared mutable state
    """

    # Signals with proper type annotations
    shots_loaded: ClassVar[Signal] = Signal(object)  # List of Shot objects
    load_failed: ClassVar[Signal] = Signal(str)  # Error message string

    def __init__(
        self,
        process_pool: ProcessPoolInterface,
        parse_function: Callable[[str, dict[str, tuple[int, int]] | None], list[Shot]],
        model: BaseShotModel | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.process_pool = process_pool
        self.parse_function = parse_function  # Use base class's parse method
        self.model = model  # Reference to model for frame range lookup

    @override
    def do_work(self) -> None:
        """Load shots in background thread.

        Called by ThreadSafeWorker.run() to perform actual work.
        Uses thread-safe mechanisms to check for stop requests.
        """
        try:
            # Check for stop request before starting
            if self.should_stop():
                return

            # Execute ws -sg command
            output = self.process_pool.execute_workspace_command(
                "ws -sg",
                cache_ttl=300,  # 5 minute cache
                timeout=TimeoutConfig.SHOT_WORKSPACE_COMMAND,
            )

            # Thread-safe check for stop request
            if self.should_stop():
                return

            # Build frame range lookup from cached shots to skip disk scans
            cached_frame_ranges: dict[str, tuple[int, int]] | None = None
            if self.model:
                cached_frame_ranges = self.model.build_frame_range_lookup()
            # Use the base class's proper parsing method
            shots = self.parse_function(output, cached_frame_ranges)

            # Thread-safe check before emitting signal
            if not self.should_stop():
                self.shots_loaded.emit(shots)

        except TimeoutError as e:
            if not self.should_stop():
                self.load_failed.emit(f"Command timed out: {e}")
        except RuntimeError as e:
            if not self.should_stop():
                self.load_failed.emit(f"Process pool error: {e}")
        except Exception as e:  # noqa: BLE001
            # Only emit error if not stopped
            if not self.should_stop():
                self.load_failed.emit(f"Unexpected error: {e}")

    def stop(self) -> bool:
        """Stop the loader thread.

        Provides compatibility with tests expecting a stop() method.

        Returns:
            True if stop was requested successfully

        """
        return self.request_stop()


@final
class ShotModel(BaseShotModel):
    """Optimized ShotModel with async loading and instant UI display.

    This model provides asynchronous, non-blocking shot loading with instant
    UI display using cached data while fresh data loads in background.
    """

    # Additional signals beyond BaseShotModel
    background_load_started: ClassVar[Signal] = Signal()
    background_load_finished: ClassVar[Signal] = Signal()
    data_recovery_occurred: ClassVar[Signal] = Signal(str, str)  # (title, details)

    def __init__(
        self,
        cache_manager: ShotDataCache | None = None,
        load_cache: bool = True,
        process_pool: ProcessPoolInterface | None = None,
    ) -> None:
        super().__init__(cache_manager, load_cache, process_pool)

        # Background loader with thread safety.
        # _loader_lock guards both _loader_host and _loading_in_progress atomically.
        self._loader_lock = QMutex()
        self._loader_host: WorkerHost[AsyncShotLoader] = WorkerHost(
            shared_mutex=self._loader_lock
        )
        self._loading_in_progress = False

        # Pre-warm strategy
        self._warm_on_startup = True
        self._session_warmed = False

        # Performance metrics
        self._last_load_time = 0.0

        # Set to True to force synchronous refresh (test seam)
        self._force_sync_refresh: bool = False

    def initialize_async(self) -> RefreshResult:
        """Initialize with cached data and start background refresh.

        This method returns immediately with cached data (if available)
        and starts loading fresh data in the background.

        Returns:
            RefreshResult with cached data status

        """
        logger.debug("ShotModel.initialize_async() starting")

        # Step 1: Load cached shots immediately (< 1ms)
        cached_shots = self.cache_manager.get_shots_with_ttl()
        cache_loaded = False

        if cached_shots:
            try:
                self.shots = [Shot.from_dict(s) for s in cached_shots]
                logger.info(f"Loaded {len(self.shots)} shots from cache instantly")
                self.shots_loaded.emit(self.shots)
                cache_loaded = True
            except (KeyError, TypeError, ValueError) as e:
                # Handle corrupted cache data gracefully
                logger.warning(
                    f"Corrupted cache data in initialize_async, ignoring: {e}"
                )
                # Treat as cache miss and continue with fresh load

        if not cache_loaded:
            # Check if cache file exists but is expired
            persistent_cache = self.cache_manager.get_shots_no_ttl()
            if persistent_cache:
                logger.info(
                    f"Cache expired ({len(persistent_cache)} shots exist), "
                    "starting background refresh for fresh data"
                )
            else:
                logger.info("No cached shots, starting background load")
            # No cache, but still return immediately
            self.shots = []
            self.shots_loaded.emit(self.shots)

        # Step 2: Start background refresh
        self._start_background_refresh()

        return RefreshResult(success=True, has_changes=False)

    def load_cache_sync(self) -> RefreshResult:
        """Load cached shots synchronously. No background thread started.

        Called by build_models() so cached data is available before signal wiring.

        Note: Does not reset self.shots on cache miss, and does not perform the
        expired-cache check that initialize_async() does. Callers that need the
        full initialisation sequence should use initialize_async() instead.
        """
        logger.debug("ShotModel.load_cache_sync() starting")
        cached_shots = self.cache_manager.get_shots_with_ttl()
        if not cached_shots:
            return RefreshResult(success=False, has_changes=False)
        try:
            self.shots = [Shot.from_dict(s) for s in cached_shots]
            logger.info(f"Loaded {len(self.shots)} shots from cache (sync)")
            return RefreshResult(success=True, has_changes=False)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"Corrupted cache in load_cache_sync, ignoring: {e}")
            return RefreshResult(success=False, has_changes=False)

    def start_background_refresh(self) -> None:
        """Start async background refresh. Called by StartupOrchestrator after signal wiring."""
        self._start_background_refresh()

    def _start_background_refresh(self) -> None:
        """Start loading shots in background without blocking UI.

        Thread-safe method that ensures only one background loader
        is created at a time. Uses phased locking to avoid blocking
        while holding the mutex (prevents deadlocks).
        """
        logger.debug("_start_background_refresh() starting")

        # Phase 1: Check state and get old loader reference under lock
        old_loader: AsyncShotLoader | None = None
        with QMutexLocker(self._loader_lock):
            if self._loading_in_progress:
                logger.warning(
                    "Background load already in progress - returning early"
                )
                return
            # Capture old loader reference for cleanup outside lock
            old_loader = self._loader_host.take_unlocked()

        # Phase 2: Clean up old loader OUTSIDE lock (wait() can block for 1s)
        if old_loader:
            if old_loader.isRunning():
                logger.warning("Previous loader still running, stopping it")
                _ = old_loader.request_stop()
                _ = old_loader.wait(1000)
            old_loader.deleteLater()

        # Phase 3: Create and start new loader under lock
        with QMutexLocker(self._loader_lock):
            # Re-check after cleanup (another thread may have started)
            if self._loading_in_progress:
                logger.warning(
                    "Background load started by another thread - returning"
                )
                return

            self._loading_in_progress = True

            # Create and configure loader with proper parse function
            loader = AsyncShotLoader(
                self._process_pool,
                parse_function=self._parse_ws_output,  # Use base class's correct parsing
                model=self,  # Pass model for frame range lookup
            )
            # Signal.connect() cannot infer specific callable type from Signal(list)
            # Qt signals use generic signatures, so slot methods appear as Any
            _ = loader.shots_loaded.connect(
                self._on_shots_loaded,  # type: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )
            _ = loader.load_failed.connect(
                self._on_load_failed,  # type: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )
            _ = loader.finished.connect(
                self._on_loader_finished,  # type: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )

            self._loader_host.store_unlocked(loader)

            # Start background loading
            loader.start()
            logger.debug("AsyncShotLoader started")

        # Phase 4: Emit signal OUTSIDE lock (prevents deadlock if slot re-enters)
        self.background_load_started.emit()

    def _process_shot_merge(
        self,
        fresh_shots: list[Shot],
        operation_name: str = "refresh",
    ) -> ShotMergeResult:
        """Process shot merge with error handling and migration.

        Args:
            fresh_shots: Fresh shots from workspace scan
            operation_name: Operation name for logging (e.g., "refresh", "sync")

        Returns:
            ShotMergeResult with merged data

        """
        # Load cache
        cached_dicts = self.cache_manager.get_shots_no_ttl() or []
        fresh_dicts = [s.to_dict() for s in fresh_shots]

        # Log the data sources for clarity (sync path has different message)
        if operation_name == "sync":
            pass  # Sync path logs this elsewhere
        else:
            logger.info(
                f"{operation_name}: {len(fresh_dicts)} shots from workspace, "
                f"{len(cached_dicts)} shots from persistent cache"
            )

        # Merge with corruption recovery
        try:
            merge_result = self.cache_manager.update_shots_cache(
                cached_dicts, fresh_dicts
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(
                "Cache corruption detected, using fresh data only", exc_info=True
            )
            merge_result = ShotMergeResult(
                updated_shots=[s.to_dict() for s in fresh_shots],
                new_shots=[s.to_dict() for s in fresh_shots],
                removed_shots=[],
                has_changes=True,
            )
            self.data_recovery_occurred.emit(
                "Cache Recovery",
                f"Cache corruption detected during merge.\n"
                f"Using fresh workspace data only.\n\n"
                f"Technical details: {e}",
            )

        # Log statistics
        logger.info(
            f"Shot merge ({operation_name}): {len(merge_result.new_shots)} new, "
            f"{len(merge_result.removed_shots)} removed, "
            f"{len(merge_result.updated_shots)} total"
        )

        # Migrate removed shots
        if merge_result.removed_shots:
            migration_success = self.cache_manager.archive_shots_as_previous(
                merge_result.removed_shots
            )
            if migration_success:
                removed_names = [
                    f"{s['show']}:{s['sequence']}_{s['shot']}"
                    for s in merge_result.removed_shots[:3]
                ]
                logger.info(
                    f"Migrated {len(merge_result.removed_shots)} shots to Previous: "
                    f"{removed_names}{'...' if len(merge_result.removed_shots) > 3 else ''}"
                )
            else:
                # Migration failed to persist - CacheManager already logged error
                logger.warning(
                    f"Failed to persist {len(merge_result.removed_shots)} migrated shots"
                )

        return merge_result

    def _apply_and_cache_merge(
        self,
        merge_result: ShotMergeResult,
        fresh_shots: list[Shot],
        old_count: int,
        context: str,
    ) -> tuple[ShotMergeResult, bool]:
        """Deserialize merge result, update self.shots, write cache if changed.

        Returns (final_merge_result, did_change).
        On deserialization failure, falls back to fresh_shots and emits data_recovery_occurred.
        """
        try:
            new_shot_objects = [Shot.from_dict(d) for d in merge_result.updated_shots]
        except (KeyError, TypeError, ValueError) as e:
            logger.exception("Merge result corrupted, using fresh data")
            new_shot_objects = fresh_shots
            merge_result = ShotMergeResult(
                updated_shots=[s.to_dict() for s in fresh_shots],
                new_shots=[],
                removed_shots=[],
                has_changes=False,
            )
            self.data_recovery_occurred.emit(
                "Shot Data Recovery",
                f"Cache corruption detected. Using fresh data only.\n"
                f"Previous shot history may be incomplete.\n\n"
                f"Technical details: {e}",
            )

        old_shot_dicts = [s.to_dict() for s in self.shots]
        did_change = merge_result.updated_shots != old_shot_dicts

        if did_change:
            self.shots = new_shot_objects
            logger.info(
                f"{context} refresh complete: {old_count} → {len(self.shots)} shots "
                f"(+{len(merge_result.new_shots)} new, -{len(merge_result.removed_shots)} removed)"
            )
            if self.shots:
                try:
                    self.cache_manager.cache_shots(self.shots)
                    self.cache_updated.emit()
                except OSError:
                    logger.warning("Failed to cache shots", exc_info=True)
        else:
            logger.info(f"{context} refresh: no changes detected")

        return merge_result, did_change

    @Slot(list)  # type: ignore[reportAny]
    def _on_shots_loaded(self, fresh_shots: list[Shot]) -> None:
        """Handle shots loaded in background (INCREMENTAL VERSION).

        This slot receives the list of loaded shots from the background thread.
        Uses incremental merge to preserve shot history and auto-migrate removed shots.
        Properly decorated with @Slot for Qt efficiency.
        """
        old_count = len(self.shots)

        try:
            merge_result = self._process_shot_merge(
                fresh_shots, operation_name="background refresh"
            )
        except Exception as e:
            # Unexpected merge failure - report error and abort
            error_msg = f"Merge operation failed: {e}"
            logger.exception(error_msg)
            self.error_occurred.emit(error_msg)
            self.refresh_finished.emit(False, False)
            return

        merge_result, did_change = self._apply_and_cache_merge(
            merge_result, fresh_shots, old_count, "Background"
        )
        # Choose signal based on context:
        # - First load (0 → N shots): use shots_loaded so subscribers know initial data is ready
        # - Subsequent update with changes: use shots_changed
        if did_change:
            if old_count == 0 and len(self.shots) > 0:
                self.shots_loaded.emit(self.shots)
            elif merge_result.has_changes:
                self.shots_changed.emit(self.shots)

        # Always emit refresh finished with change status
        self.refresh_finished.emit(True, merge_result.has_changes)

    @Slot(str)  # type: ignore[reportAny]
    def _on_load_failed(self, error_msg: str) -> None:
        """Handle background load failure.

        This slot receives error messages from the background thread.
        Properly decorated with @Slot for Qt efficiency.
        """
        logger.error(f"Background shot loading failed: {error_msg}")
        self.error_occurred.emit(error_msg)
        self.refresh_finished.emit(False, False)

    @Slot()  # type: ignore[reportAny]
    def _on_loader_finished(self) -> None:
        """Handle loader thread completion.

        This slot is called when the background loader finishes.
        Properly decorated with @Slot for Qt efficiency.
        """
        with QMutexLocker(self._loader_lock):
            self._loading_in_progress = False
            # Clean up loader
            finished_loader = self._loader_host.take_unlocked()
        if finished_loader is not None:
            finished_loader.deleteLater()

        # Emit signal outside lock to avoid potential deadlock
        self.background_load_finished.emit()

    @override
    def refresh_strategy(self) -> RefreshResult:
        """Override to use async strategy if no shots loaded yet."""
        if self._force_sync_refresh:
            return self.refresh_shots_sync()

        # Check loading state with lock held
        with QMutexLocker(self._loader_lock):
            loading = self._loading_in_progress

        if not self.shots and not loading:
            # First load - use async strategy
            return self.initialize_async()
        if not loading:
            # For subsequent refreshes, start background refresh only if not already loading
            logger.info(
                "Shots already loaded and not loading - starting background refresh"
            )
            self._start_background_refresh()
            # Return immediately with current state
            logger.info("Returning immediately (background refresh started)")
            return RefreshResult(success=True, has_changes=False)
        # Already loading - return True to indicate no error (operation in progress)
        logger.info(
            "Already loading - skipping refresh request (returning success=True)"
        )
        return RefreshResult(success=True, has_changes=False)

    @override
    def get_performance_metrics(self) -> PerformanceMetricsDict:
        """Get performance metrics including cache statistics."""
        metrics = super().get_performance_metrics()
        # Read loading state with lock held
        with QMutexLocker(self._loader_lock):
            loading = self._loading_in_progress

        metrics.update(
            {
                "loading_in_progress": loading,
                "session_warmed": self._session_warmed,
            }
        )
        return metrics

    def cleanup(self) -> None:
        """Clean up resources with safe thread termination.

        Uses Qt's safe interruption mechanism instead of dangerous terminate().
        Thread-safe: captures loader reference under lock, then does blocking
        operations outside lock to prevent deadlocks.
        """
        # Phase 1: Atomically capture and clear loader reference under lock
        with QMutexLocker(self._loader_lock):
            loader = self._loader_host.take_unlocked()
            self._loading_in_progress = False

        # Phase 2: Clean up loader OUTSIDE lock (wait() can block for seconds)
        if loader:
            if loader.isRunning():
                logger.info("Stopping background loader")
                _ = loader.request_stop()  # Sets event and requests interruption

                # Give thread 2 seconds to stop gracefully
                if not loader.wait(2000):
                    logger.warning(
                        "Background loader did not stop gracefully within 2s"
                    )
                    # Use ThreadSafeWorker's safe_terminate method
                    loader.safe_terminate()

                    # Wait up to 2 more seconds for safe termination
                    if not loader.wait(2000):
                        # As last resort, we accept the thread will be abandoned
                        # safe_terminate already avoids dangerous terminate()
                        logger.error(
                            "Background loader thread abandoned - will be cleaned on exit"
                        )
                        # Mark it for deletion but don't force terminate

            # Clean up the loader object
            loader.deleteLater()

        # Note: parent ShotModel doesn't have cleanup method

    @override
    def invalidate_workspace_cache(self) -> None:
        """Manually invalidate the workspace command cache.

        Forces the next workspace command to fetch fresh data
        instead of using cached results.
        """
        if self._process_pool:
            self._process_pool.invalidate_cache("ws -sg")
            logger.debug("Workspace cache invalidated")

    def refresh_shots_sync(self) -> RefreshResult:
        """Synchronous refresh with incremental caching.

        This method provides synchronous shot refresh behavior required by tests.
        Uses incremental merge to preserve shot history and auto-migrate removed shots.

        Returns:
            RefreshResult with success status and change indicator

        """
        self.refresh_started.emit()
        old_count = len(self.shots)

        try:
            # Execute workspace command synchronously
            output = self._process_pool.execute_workspace_command(
                "ws -sg",
                cache_ttl=300,  # 5 minute cache (consistent with AsyncShotLoader)
                timeout=TimeoutConfig.SHOT_WORKSPACE_COMMAND,
            )

            # Build frame range lookup to skip expensive disk scans for cached shots
            cached_frame_ranges = self.build_frame_range_lookup()

            # Parse output
            fresh_shots = self._parse_ws_output(output, cached_frame_ranges)

            # Process shot merge with error handling and migration
            try:
                merge_result = self._process_shot_merge(
                    fresh_shots, operation_name="sync"
                )
            except Exception as e:
                # Unexpected merge failure - report error and abort
                error_msg = f"Merge operation failed: {e}"
                logger.exception(error_msg)
                self.error_occurred.emit(error_msg)
                self.refresh_finished.emit(False, False)
                return RefreshResult(success=False, has_changes=False)

            merge_result, did_change = self._apply_and_cache_merge(
                merge_result, fresh_shots, old_count, "Sync"
            )
            if did_change and merge_result.has_changes:
                self.shots_changed.emit(self.shots)

            self.refresh_finished.emit(True, merge_result.has_changes)
            return RefreshResult(success=True, has_changes=merge_result.has_changes)

        except (TimeoutError, RuntimeError, WorkspaceError) as e:
            error_msg = f"Failed to refresh shots: {e}"
            logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self.refresh_finished.emit(False, False)
            return RefreshResult(success=False, has_changes=False)
        except Exception as e:
            error_msg = f"Unexpected error while refreshing shots: {e}"
            logger.exception(error_msg)
            self.error_occurred.emit(error_msg)
            self.refresh_finished.emit(False, False)
            return RefreshResult(success=False, has_changes=False)

    def try_load_from_cache(self) -> bool:
        """Load from cache; used by startup orchestrator and tests."""
        return self._load_from_cache()
