"""Startup coordination for initial data loading.

Extracts the initial-load decision table from MainWindow into a testable
coordinator. The 4-case decision table loads cached data instantly and
schedules background refreshes as needed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, final

from PySide6.QtCore import QTimer

from thread_safe_worker import ThreadSafeWorker
from typing_compat import override


if TYPE_CHECKING:
    from cache.scene_cache_disk import SceneDiskCache
    from controllers.threede_controller import ThreeDEController
    from previous_shots_model import PreviousShotsModel
    from protocols import ProcessPoolInterface
    from refresh_orchestrator import RefreshOrchestrator
    from shot_grid_view import ShotGridView
    from shot_model import ShotModel
    from threede_grid_view import ThreeDEGridView
    from threede_item_model import ThreeDEItemModel
    from threede_scene_model import ThreeDESceneModel

logger = logging.getLogger(__name__)

# Timer delays for UI paint and event loop yields (milliseconds)
_PAINT_YIELD_MS: int = 500  # Delay to let Qt paint initial UI before refresh
_EVENT_LOOP_YIELD_MS: int = 100  # Delay to yield to event loop between operations


class SessionWarmer(ThreadSafeWorker):
    """Background thread for pre-warming bash sessions without blocking UI.

    This thread runs during idle time after the UI is displayed, initializing
    the bash environment and 'ws' function in the background. This prevents
    the ~8 second freeze that would occur if this initialization happened
    on the main thread during the first actual command execution.
    """

    def __init__(self, process_pool: ProcessPoolInterface) -> None:
        """Initialize session warmer with process pool.

        Args:
            process_pool: ProcessPoolInterface instance to warm up

        """
        super().__init__()
        self._process_pool: ProcessPoolInterface = process_pool

    @override
    def do_work(self) -> None:
        """Pre-warm bash sessions in background thread.

        Called by ThreadSafeWorker.run() to perform actual work.
        """
        try:
            # Check if we should stop before starting
            if self.should_stop():
                return

            logger.debug("Starting background session pre-warming")
            start_time = time.time()

            # Check if we should stop before executing
            if self.should_stop():
                return

            _ = self._process_pool.execute_workspace_command(
                "echo warming",
                cache_ttl=1,  # Short TTL since this is just for warming
                timeout=15,  # Give enough time for first initialization
                use_login_shell=True,  # Use bash -l to avoid terminal blocking
            )
            duration = time.time() - start_time
            logger.info(
                f"Bash session pre-warming completed successfully ({duration:.2f}s)"
            )
        except Exception:  # noqa: BLE001
            # Don't fail the app if pre-warming fails
            logger.warning("Session pre-warming failed (non-critical)", exc_info=True)


@final
class StartupCoordinator:
    """Coordinates the initial data loading sequence at application startup.

    Implements a 4-case decision table based on cache state:
        cached shots + cached scenes  → display both, schedule background refresh
        cached shots only             → display shots, schedule background refresh
        cached scenes only            → display scenes, no shot refresh scheduled
        no cache                      → show "Loading..." status; background refresh
                                        already in progress from initialize_async()
    """

    def __init__(
        self,
        *,
        shot_model: ShotModel,
        threede_scene_model: ThreeDESceneModel,
        threede_item_model: ThreeDEItemModel,
        previous_shots_model: PreviousShotsModel,
        cache_manager: SceneDiskCache,
        refresh_orchestrator: RefreshOrchestrator,
        process_pool: ProcessPoolInterface,
        threede_controller: ThreeDEController | None,
        shot_grid: ShotGridView,
        threede_shot_grid: ThreeDEGridView,
        update_status: Callable[[str], None],
        last_selected_shot_name: str | None,
        refresh_shots: Callable[[], None],
        refresh_shot_display: Callable[[], None],
    ) -> None:
        """Initialize with all dependencies needed for startup coordination.

        Args:
            shot_model: The shot data model.
            threede_scene_model: The 3DE scene data model.
            threede_item_model: The 3DE Qt item model.
            previous_shots_model: The previous shots model.
            cache_manager: The cache manager for validating 3DE cache.
            refresh_orchestrator: The refresh orchestrator for triggering refreshes.
            process_pool: The process pool interface for session warming.
            threede_controller: The 3DE controller, or None if unavailable.
            shot_grid: The shot grid view widget.
            threede_shot_grid: The 3DE shot grid view widget.
            update_status: Callable to update the status bar message.
            last_selected_shot_name: Name of the last selected shot to restore, or None.
            refresh_shots: Callable to trigger a shot refresh.
            refresh_shot_display: Callable to refresh the shot display.

        """
        self._shot_model = shot_model
        self._threede_scene_model = threede_scene_model
        self._threede_item_model = threede_item_model
        self._previous_shots_model = previous_shots_model
        self._cache_manager = cache_manager
        self._refresh_orchestrator = refresh_orchestrator
        self._process_pool = process_pool
        self._threede_controller = threede_controller
        self._shot_grid = shot_grid
        self._threede_shot_grid = threede_shot_grid
        self._update_status = update_status
        self._last_selected_shot_name = last_selected_shot_name
        self._refresh_shots = refresh_shots
        self._refresh_shot_display = refresh_shot_display

    def perform_initial_load(self) -> SessionWarmer | None:
        """Execute the initial data loading sequence.

        Starts session warming, loads data from cache, and schedules background
        refreshes as needed. Returns the SessionWarmer if one was started, so
        the caller can hold a reference for cleanup.

        Returns:
            The started SessionWarmer instance, or None if session warming was
            skipped (e.g. for test doubles that don't use ProcessPoolManager).

        """
        from process_pool_manager import ProcessPoolManager

        session_warmer: SessionWarmer | None = None

        # Pre-warm bash sessions in background to avoid first-command delay
        # Only warm real process pools (test doubles don't spawn subprocesses)
        if isinstance(self._process_pool, ProcessPoolManager):
            session_warmer = SessionWarmer(self._process_pool)
            session_warmer.start()
            logger.debug("SessionWarmer started")

        has_cached_shots = bool(self._shot_model.shots)
        has_cached_scenes = bool(self._threede_scene_model.scenes)

        # Show cached shots immediately if available (should already be loaded)
        if has_cached_shots:
            self._refresh_shot_display()
            logger.info(
                f"Displayed {len(self._shot_model.shots)} cached shots instantly"
            )
        else:
            # No cache, but let's check one more time
            logger.info(
                "No cached shots found on initial check, attempting explicit cache load"
            )
            if self._shot_model.try_load_from_cache():
                has_cached_shots = True
                self._refresh_shot_display()
                logger.info(
                    f"Loaded and displayed {len(self._shot_model.shots)} shots from cache"
                )

            # Restore last selected shot if available
            if isinstance(self._last_selected_shot_name, str):
                shot = self._shot_model.find_shot_by_name(self._last_selected_shot_name)
                if shot:
                    self._shot_grid.select_shot_by_name(shot.full_name)

        # Show cached 3DE scenes immediately if available
        if has_cached_scenes:
            self._threede_item_model.set_scenes(self._threede_scene_model.scenes)
            # Populate show filter with available shows
            self._threede_shot_grid.populate_show_filter(self._threede_scene_model)

        # Update status with what was loaded from cache
        if has_cached_shots and has_cached_scenes:
            self._update_status(
                (
                    f"Loaded {len(self._shot_model.shots)} shots and "
                    f"{len(self._threede_scene_model.scenes)} 3DE scenes from cache"
                ),
            )
            # Delay: let Qt finish painting the cached-shot grid before
            # spawning the subprocess that fetches fresh data from `ws -sg`.
            QTimer.singleShot(_PAINT_YIELD_MS, self._refresh_shots)
        elif has_cached_shots:
            self._update_status(
                f"Loaded {len(self._shot_model.shots)} shots from cache"
            )
            # Delay: same rationale as above — paint first, refresh second.
            QTimer.singleShot(_PAINT_YIELD_MS, self._refresh_shots)
        elif has_cached_scenes:
            self._update_status(
                f"Loaded {len(self._threede_scene_model.scenes)} 3DE scenes from cache",
            )
        else:
            self._update_status("Loading shots and scenes...")
            # No cache exists - background refresh already started by initialize_async()
            logger.info(
                "No cached data found - background refresh already in progress from initialize_async()",
            )

        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        # Previous shots now only refresh on explicit user action via "Refresh" button
        #
        # NOTE: Previous shots refresh is triggered by shots_loaded/shots_changed
        # signals connected directly to RefreshOrchestrator.trigger_previous_shots_refresh.

        # If shots are already loaded from cache, trigger refresh immediately
        if self._shot_model.shots:
            logger.info(
                "Shots already loaded from cache, triggering previous shots refresh immediately"
            )
            # Delay: yield to the event loop so the main shot grid
            # finishes its layout pass before the previous-shots refresh
            # triggers another model update.
            QTimer.singleShot(
                _EVENT_LOOP_YIELD_MS, self._previous_shots_model.refresh_shots
            )

        # Only start 3DE discovery if we have shots AND cache is invalid/expired
        # This avoids unnecessary scans when we already know there are no scenes
        if has_cached_shots:
            # Check if we have a valid cache (including valid empty results)
            if not self._cache_manager.has_valid_threede_cache():
                logger.debug("3DE cache invalid/expired - starting discovery")
                if self._threede_controller:
                    # 100ms delay: same rationale — yield for layout, then
                    # kick off 3DE filesystem scan in background.
                    QTimer.singleShot(
                        100, self._threede_controller.refresh_threede_scenes
                    )
            else:
                logger.debug("3DE cache valid - skipping initial scan")

        return session_warmer
