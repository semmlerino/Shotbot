"""Launch coordination extracted from MainWindow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

from dcc.scene_file import SceneFile
from logging_mixin import LoggingMixin
from managers.notification_manager import NotificationManager


if TYPE_CHECKING:
    from launch.command_launcher import CommandLauncher
    from threede.grid_view import ThreeDEGridView


@final
class LaunchCoordinator(LoggingMixin):
    """Coordinates launch requests from the right panel and 3DE grid.

    Extracted from MainWindow to reduce its handler count.
    """

    def __init__(
        self,
        *,
        command_launcher: CommandLauncher,
        threede_shot_grid: ThreeDEGridView,
    ) -> None:
        super().__init__()
        self._command_launcher = command_launcher
        self._threede_shot_grid = threede_shot_grid

    def on_right_panel_launch(self, app_name: str, options: dict[str, Any]) -> None:
        """Handle launch request from right panel DCC section."""
        selected_file = options.get("selected_file")
        if isinstance(selected_file, SceneFile):
            workspace_path = self.get_current_workspace_path()
            if workspace_path:
                from launch.launch_request import LaunchRequest

                _ = self._command_launcher.launch(
                    LaunchRequest(
                        app_name=app_name,
                        file_path=selected_file.path,
                        workspace_path=workspace_path,
                    )
                )
                return
            NotificationManager.error(
                "Cannot Launch File",
                "No shot or scene context available. Select a shot first.",
            )
            return

        from launch.command_launcher import LaunchContext
        from launch.launch_request import LaunchRequest

        context = LaunchContext(
            open_latest_threede=bool(options.get("open_latest_threede", False)),  # pyright: ignore[reportAny]
            open_latest_maya=bool(options.get("open_latest_maya", False)),  # pyright: ignore[reportAny]
            open_latest_scene=bool(options.get("open_latest_scene", False)),  # pyright: ignore[reportAny]
            create_new_file=bool(options.get("create_new_file", False)),  # pyright: ignore[reportAny]
            selected_plate=options.get("selected_plate"),
            sequence_path=options.get("sequence_path"),
        )
        _ = self._command_launcher.launch(
            LaunchRequest(
                app_name=app_name,
                context=context,
            )
        )

    def get_current_workspace_path(self) -> str | None:
        """Get workspace path from current shot or selected 3DE scene."""
        current_shot = self._command_launcher.current_shot
        if current_shot:
            return current_shot.workspace_path
        selected_scene = self._threede_shot_grid.selected_scene
        if selected_scene:
            return selected_scene.workspace_path
        return None
