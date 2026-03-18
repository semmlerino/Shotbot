"""Orchestrates the full application startup sequence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QTimer

from logging_mixin import get_module_logger
from workers.process_pool_manager import ProcessPoolManager
from workers.startup_coordinator import StartupCoordinator


if TYPE_CHECKING:
    from cache import SceneDiskCache
    from controllers.refresh_coordinator import RefreshCoordinator
    from controllers.threede_controller import ThreeDEController
    from previous_shots import PreviousShotsModel
    from protocols import ProcessPoolInterface
    from shots.shot_grid_view import ShotGridView
    from shots.shot_model import ShotModel
    from threede import ThreeDEGridView, ThreeDEItemModel, ThreeDESceneModel

logger = get_module_logger(__name__)


class StartupTarget(Protocol):
    """Minimal interface required by StartupOrchestrator from its host window."""

    shot_model: ShotModel
    threede_scene_model: ThreeDESceneModel
    threede_item_model: ThreeDEItemModel
    previous_shots_model: PreviousShotsModel
    shot_grid: ShotGridView
    threede_shot_grid: ThreeDEGridView
    threede_controller: ThreeDEController
    refresh_coordinator: RefreshCoordinator
    scene_disk_cache: SceneDiskCache

    @property
    def last_selected_shot_name(self) -> str | None: ...
    def update_status(self, message: str) -> None: ...
    def _refresh_shots(self) -> None: ...
    def _refresh_shot_display(self) -> None: ...


class StartupOrchestrator:
    """Orchestrates the full application startup sequence.

    Manages cache-aware initial data loading and deferred refresh scheduling.
    """

    # Timer delays for UI paint and event loop yields (milliseconds)
    _PAINT_YIELD_MS: int = 500
    _EVENT_LOOP_YIELD_MS: int = 100

    def __init__(self, target: StartupTarget, process_pool: ProcessPoolInterface) -> None:
        self._target: StartupTarget = target
        self._process_pool: ProcessPoolInterface = process_pool
        self._session_warmer: StartupCoordinator | None = None

    @property
    def session_warmer(self) -> StartupCoordinator | None:
        return self._session_warmer

    def execute(self) -> None:
        """Run the startup sequence: session warming, cache check, render, schedule refresh."""
        target = self._target

        # Pre-warm bash sessions in background to avoid first-command delay
        # Only warm real process pools (test doubles don't spawn subprocesses)
        if isinstance(self._process_pool, ProcessPoolManager):
            self._session_warmer = StartupCoordinator(self._process_pool)
            self._session_warmer.start()
            logger.debug("StartupCoordinator started")

        has_cached_shots = bool(target.shot_model.shots)
        has_cached_scenes = bool(target.threede_scene_model.scenes)

        # Show cached shots immediately if available
        if has_cached_shots:
            target._refresh_shot_display()  # pyright: ignore[reportPrivateUsage]
            logger.info(f"Displayed {len(target.shot_model.shots)} cached shots instantly")
        else:
            logger.info("No cached shots found on initial check, attempting explicit cache load")
            if target.shot_model.try_load_from_cache():
                has_cached_shots = True
                target._refresh_shot_display()  # pyright: ignore[reportPrivateUsage]
                logger.info(f"Loaded and displayed {len(target.shot_model.shots)} shots from cache")

            # Restore last selected shot if available
            if isinstance(target.last_selected_shot_name, str):
                shot = target.shot_model.find_shot_by_name(target.last_selected_shot_name)
                if shot:
                    target.shot_grid.select_shot_by_name(shot.full_name)

        # Show cached 3DE scenes immediately if available
        if has_cached_scenes:
            target.threede_item_model.set_scenes(target.threede_scene_model.scenes)
            target.threede_shot_grid.populate_show_filter(target.threede_scene_model)

        # Update status with what was loaded from cache
        paint_yield_ms = self._PAINT_YIELD_MS
        event_loop_yield_ms = self._EVENT_LOOP_YIELD_MS
        if has_cached_shots and has_cached_scenes:
            target.update_status(
                f"Loaded {len(target.shot_model.shots)} shots and "
                f"{len(target.threede_scene_model.scenes)} 3DE scenes from cache"
            )
            QTimer.singleShot(paint_yield_ms, target._refresh_shots)  # pyright: ignore[reportPrivateUsage]
        elif has_cached_shots:
            target.update_status(f"Loaded {len(target.shot_model.shots)} shots from cache")
            QTimer.singleShot(paint_yield_ms, target._refresh_shots)  # pyright: ignore[reportPrivateUsage]
        elif has_cached_scenes:
            target.update_status(
                f"Loaded {len(target.threede_scene_model.scenes)} 3DE scenes from cache"
            )
        else:
            target.update_status("Loading shots and scenes...")
            logger.info("No cached data found - background refresh already in progress from initialize_async()")

        # If shots are already loaded from cache, trigger refresh immediately
        if target.shot_model.shots:
            logger.info("Shots already loaded from cache, triggering previous shots refresh immediately")
            QTimer.singleShot(event_loop_yield_ms, target.previous_shots_model.refresh_shots)

        # Only start 3DE discovery if we have shots AND cache is invalid/expired
        if has_cached_shots:
            if not target.scene_disk_cache.has_valid_threede_cache():
                logger.debug("3DE cache invalid/expired - starting discovery")
                if target.threede_controller:
                    QTimer.singleShot(event_loop_yield_ms, target.threede_controller.refresh_threede_scenes)
            else:
                logger.debug("3DE cache valid - skipping initial scan")
