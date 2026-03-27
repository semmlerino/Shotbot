"""Protocol definitions for ShotBot application.

This module defines Protocol classes for better type safety and
interface design throughout the application.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable
    from pathlib import Path

    # Third-party imports
    from PySide6.QtCore import QByteArray, Signal
    from PySide6.QtWidgets import QTabWidget

    # Local application imports
    from cache import CacheCoordinator, SceneDiskCache
    from controllers.refresh_coordinator import RefreshCoordinator
    from controllers.threede_controller import ThreeDEController
    from managers.settings_manager import SettingsManager
    from previous_shots.model import PreviousShotsModel
    from previous_shots.view import PreviousShotsView
    from shots.shot_grid_view import ShotGridView
    from shots.shot_item_model import ShotItemModel
    from shots.shot_model import ShotModel
    from threede.grid_view import ThreeDEGridView
    from threede.item_model import ThreeDEItemModel
    from threede.scene_model import ThreeDESceneModel
    from type_definitions import Shot
    from ui.proxy_models import ThreeDEProxyModel
    from ui.right_panel import RightPanelWidget
    from ui.settings_dialog import SettingsDialog


@runtime_checkable
class SceneDataProtocol(Protocol):
    """Common interface for Shot and ThreeDEScene data objects.

    This protocol defines the shared interface between Shot and ThreeDEScene,
    allowing ItemModels to work with either type through a common interface.
    """

    show: str
    sequence: str
    shot: str
    workspace_path: str
    frame_start: int | None
    frame_end: int | None

    @property
    def full_name(self) -> str:
        """Get full name of the scene/shot."""
        ...

    def get_thumbnail_path(self) -> Path | None:
        """Get path to thumbnail image."""
        ...


@runtime_checkable
class ProcessPoolInterface(Protocol):
    """Protocol for process pool implementations.

    Both ProcessPoolManager and MockWorkspacePool must implement this interface.
    """

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        timeout: int | None = None,
        use_login_shell: bool = False,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> str:
        """Execute workspace command."""
        ...

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate command cache."""
        ...

    def shutdown(self, timeout: float = 5.0) -> None:
        """Shutdown the process pool."""
        ...


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


class SettingsTarget(Protocol):
    """Protocol defining the interface required by SettingsController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the SettingsController for proper operation. It includes window geometry
    methods, widget references, and layout management capabilities.
    """

    # Window geometry and state methods (positional-only params match Qt stubs)
    def restoreGeometry(self, __geometry: QByteArray | bytes | bytearray) -> bool: ...
    def saveGeometry(self) -> QByteArray: ...
    def restoreState(
        self, __state: QByteArray | bytes | bytearray, __version: int = ...
    ) -> bool: ...
    def saveState(self) -> QByteArray: ...
    def isMaximized(self) -> bool: ...
    def showMaximized(self) -> None: ...

    def resize(self, __w: int, __h: int, /) -> None: ...
    def get_window_size(self) -> tuple[int, int]: ...

    # Widget references needed for settings
    settings_manager: SettingsManager  # skylos: ignore
    cache_coordinator: CacheCoordinator  # skylos: ignore

    # Splitter and tab wrapper methods
    def get_splitter_state(self) -> QByteArray: ...
    def restore_splitter_state(
        self, __state: QByteArray | bytes | bytearray
    ) -> bool: ...
    def get_current_tab(self) -> int: ...
    def set_current_tab(self, __index: int) -> None: ...
    def reset_splitter_sizes(self, __sizes: list[int]) -> None: ...

    # Thumbnail size access methods
    def set_thumbnail_size(self, size: int) -> None: ...
    def get_thumbnail_size(self) -> int: ...

    # Settings dialog reference
    settings_dialog: SettingsDialog | None  # skylos: ignore


class RefreshCoordinatorMainWindowProtocol(Protocol):
    """Protocol defining the MainWindow interface needed by RefreshCoordinator.

    This avoids circular imports while providing proper type safety.
    TYPE_CHECKING imports provide proper types without creating circular
    import cycles at runtime.
    """

    tab_widget: QTabWidget
    shot_model: ShotModel
    previous_shots_model: PreviousShotsModel
    shot_item_model: ShotItemModel
    shot_grid: ShotGridView

    @property
    def last_selected_shot_name(self) -> str | None: ...

    def update_status(self, message: str) -> None:
        """Update the status bar with a message."""
        ...


class ThreeDETarget(Protocol):
    """Protocol defining interface required by ThreeDEController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ThreeDEController for proper operation. It includes widget references,
    model access, and required methods.
    """

    # Widget references needed for 3DE operations
    threede_shot_grid: ThreeDEGridView  # skylos: ignore
    right_panel: RightPanelWidget  # skylos: ignore

    # Model references for data access
    def get_active_shots(self) -> list[Shot]: ...  # skylos: ignore

    threede_scene_model: ThreeDESceneModel  # skylos: ignore
    threede_item_model: ThreeDEItemModel  # skylos: ignore
    threede_proxy: ThreeDEProxyModel  # skylos: ignore
    scene_disk_cache: SceneDiskCache  # skylos: ignore

    # Required methods
    def setWindowTitle(self, __title: str) -> None: ...
    def update_status(self, message: str) -> None: ...

    # Signals (Signal is a Qt descriptor; pyright can't resolve its methods)
    closing_started: ClassVar[Signal]  # pyright: ignore[reportAny]  # skylos: ignore


class ThreeDESelectionTarget(Protocol):
    """Protocol defining the window interface used by ThreeDESelectionHandler.

    This is a narrower subset of ThreeDETarget — only the attributes and
    methods that the selection handler actually touches.
    """

    # Widget references needed for selection handling
    threede_shot_grid: ThreeDEGridView  # skylos: ignore
    right_panel: RightPanelWidget  # skylos: ignore
    threede_proxy: ThreeDEProxyModel  # skylos: ignore

    # Required methods
    def setWindowTitle(self, __title: str) -> None: ...
    def update_status(self, message: str) -> None: ...


class ThumbnailSizeTarget(Protocol):
    """Protocol defining interface required by ThumbnailSizeManager.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ThumbnailSizeManager for proper operation.
    """

    # Grid views (each has size_slider and size_label)
    shot_grid: ShotGridView
    threede_shot_grid: ThreeDEGridView
    previous_shots_grid: PreviousShotsView

    # Tab widget for determining active tab
    tab_widget: QTabWidget


class ShotSelectionTarget(Protocol):
    """Protocol defining interface required by ShotSelectionController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ShotSelectionController for proper operation.
    """

    # Widget references needed for shot selection
    right_panel: RightPanelWidget
    shot_grid: ShotGridView
    previous_shots_grid: PreviousShotsView
    threede_shot_grid: ThreeDEGridView

    # State tracking
    @property
    def last_selected_shot_name(self) -> str | None: ...
    @last_selected_shot_name.setter
    def last_selected_shot_name(self, value: str | None) -> None: ...

    # Required methods
    def setWindowTitle(self, __title: str) -> None: ...
    def update_status(self, message: str) -> None: ...

    # Closing state for guard checks
    @property
    def closing(self) -> bool: ...
