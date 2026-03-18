"""Factory functions and dataclasses for app infrastructure and model initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from cache import (
    CacheCoordinator,
    LatestFileCache,
    SceneDiskCache,
    ShotDataCache,
    ThumbnailCache,
    resolve_default_cache_dir,
)
from config import is_mock_mode
from controllers.refresh_coordinator import RefreshCoordinator
from controllers.settings_controller import SettingsController
from launch.command_launcher import CommandLauncher
from logging_mixin import get_module_logger
from managers.file_pin_manager import FilePinManager
from managers.hide_manager import HideManager
from managers.notes_manager import NotesManager
from managers.settings_manager import SettingsManager
from managers.shot_pin_manager import ShotPinManager
from previous_shots import PreviousShotsModel
from shots.shot_model import ShotModel
from threede import ThreeDEItemModel, ThreeDESceneModel
from ui.design_system import design_system
from workers.process_pool_manager import ProcessPoolManager


if TYPE_CHECKING:
    from protocols import ProcessPoolInterface
    from ui.base_shot_model import BaseShotModel  # used in cast()

logger = get_module_logger(__name__)


@dataclass
class AppInfrastructure:
    """Infrastructure services created during app initialization."""

    process_pool: ProcessPoolInterface
    cache_coordinator: CacheCoordinator
    shot_cache: ShotDataCache
    scene_disk_cache: SceneDiskCache
    thumbnail_cache: ThumbnailCache
    latest_file_cache: LatestFileCache
    pin_manager: ShotPinManager
    hide_manager: HideManager
    notes_manager: NotesManager
    file_pin_manager: FilePinManager
    refresh_coordinator: RefreshCoordinator
    settings_manager: SettingsManager
    settings_controller: SettingsController


@dataclass
class AppModels:
    """Data models created during app initialization."""

    shot_model: ShotModel
    threede_scene_model: ThreeDESceneModel
    threede_item_model: ThreeDEItemModel
    previous_shots_model: PreviousShotsModel
    command_launcher: CommandLauncher


def build_infrastructure(cache_dir: Path | None, parent: Any) -> AppInfrastructure:
    """Create process pool, caches, managers, and settings infrastructure."""
    process_pool: ProcessPoolInterface
    if is_mock_mode():
        from tests.fixtures.mock_workspace_pool import create_mock_pool_from_filesystem

        process_pool = create_mock_pool_from_filesystem()
        logger.info("Using MockWorkspacePool for process execution")
    else:
        process_pool = ProcessPoolManager.get_instance()
        logger.info("Using ProcessPoolManager for process execution")

    # Resolve cache directory
    _cache_dir = cache_dir if cache_dir is not None else resolve_default_cache_dir()
    _cache_dir.mkdir(parents=True, exist_ok=True)

    # Create domain-specific cache managers
    thumbnail_cache = ThumbnailCache(_cache_dir)
    shot_cache = ShotDataCache(_cache_dir)
    scene_disk_cache = SceneDiskCache(_cache_dir)
    latest_file_cache = LatestFileCache(_cache_dir)
    cache_coordinator = CacheCoordinator(
        _cache_dir,
        thumbnail_cache,
        shot_cache,
        scene_disk_cache,
        latest_file_cache,
        on_cleared=lambda: process_pool.invalidate_cache(),
    )

    pin_manager = ShotPinManager(_cache_dir)
    hide_manager = HideManager(_cache_dir)
    notes_manager = NotesManager(_cache_dir, parent=parent)
    file_pin_manager = FilePinManager(_cache_dir, parent=parent)

    refresh_coordinator = RefreshCoordinator(parent)

    settings_manager = SettingsManager()
    saved_scale = settings_manager.get_ui_scale()
    design_system.set_ui_scale(saved_scale)

    settings_controller = SettingsController(parent)

    return AppInfrastructure(
        process_pool=process_pool,
        cache_coordinator=cache_coordinator,
        shot_cache=shot_cache,
        scene_disk_cache=scene_disk_cache,
        thumbnail_cache=thumbnail_cache,
        latest_file_cache=latest_file_cache,
        pin_manager=pin_manager,
        hide_manager=hide_manager,
        notes_manager=notes_manager,
        file_pin_manager=file_pin_manager,
        refresh_coordinator=refresh_coordinator,
        settings_manager=settings_manager,
        settings_controller=settings_controller,
    )


def build_models(infra: AppInfrastructure, parent: Any) -> AppModels:
    """Create data models and command launcher."""
    threede_item_model = ThreeDEItemModel(cache_manager=infra.thumbnail_cache)

    logger.info("Creating ShotModel with 366x faster startup")
    shot_model = ShotModel(infra.shot_cache, process_pool=infra.process_pool)
    init_result = shot_model.initialize_async()
    if init_result.success:
        cached_count = len(shot_model.shots)
        logger.debug(f"Model initialized: {cached_count} shots in memory")

    threede_scene_model = ThreeDESceneModel(infra.scene_disk_cache)
    previous_shots_model = PreviousShotsModel(
        cast("BaseShotModel", shot_model),
        infra.shot_cache,
    )

    command_launcher = CommandLauncher(
        parent=parent,
        settings_manager=infra.settings_manager,
        cache_manager=infra.latest_file_cache,
    )

    return AppModels(
        shot_model=shot_model,
        threede_scene_model=threede_scene_model,
        threede_item_model=threede_item_model,
        previous_shots_model=previous_shots_model,
        command_launcher=command_launcher,
    )
