"""Selection and interaction handler for the 3DE shot grid.

Extracted from ThreeDEController to isolate all scene-selection, double-click,
tab-activation, crash-recovery, and filter-delegation logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Slot

from config import Config
from logging_mixin import LoggingMixin
from managers.notification_manager import NotificationManager
from type_definitions import Shot, ThreeDEScene


if TYPE_CHECKING:
    from collections.abc import Callable

    from launch.command_launcher import CommandLauncher
    from protocols import ThreeDESelectionTarget
    from threede.grid_view import ThreeDEGridView


class ThreeDESelectionHandler(LoggingMixin):
    """Handles scene selection, double-click, tab, crash recovery and filters.

    Owns all user-interaction handlers that were previously inline on
    ThreeDEController.  The controller constructs this object, passes ``self``
    as ``window``, and delegates signal setup via :meth:`setup_signals`.

    Args:
        window: Object implementing ThreeDESelectionTarget protocol.
        command_launcher: DCC command launcher used for double-click launch and
            clearing the current shot.
        refresh_callback: Zero-argument callable to trigger a full refresh of
            3DE scenes (used after crash recovery).

    """

    def __init__(
        self,
        window: ThreeDESelectionTarget,
        *,
        command_launcher: CommandLauncher,
        refresh_callback: Callable[[], None],
    ) -> None:
        super().__init__()
        self._window: ThreeDESelectionTarget = window
        self._command_launcher: CommandLauncher = command_launcher
        self._refresh_callback: Callable[[], None] = refresh_callback

    def setup_signals(self, grid: ThreeDEGridView) -> None:
        """Connect grid signals to this handler's slots.

        Args:
            grid: The 3DE grid view whose signals should be wired.

        """
        _ = grid.scene_selected.connect(self.on_scene_selected)  # pyright: ignore[reportAny]
        _ = grid.scene_double_clicked.connect(self.on_scene_double_clicked)  # pyright: ignore[reportAny]
        _ = grid.recover_crashes_requested.connect(self.on_recover_crashes_clicked)  # pyright: ignore[reportAny]
        _ = grid.show_filter_requested.connect(self.on_show_filter_requested)  # pyright: ignore[reportAny]
        _ = grid.artist_filter_requested.connect(self.on_artist_filter_requested)  # pyright: ignore[reportAny]
        self.logger.debug("ThreeDESelectionHandler signals connected")

    # ============================================================================
    # Scene Interaction Slots
    # ============================================================================

    @Slot(object)  # pyright: ignore[reportAny]
    def on_scene_selected(self, scene: ThreeDEScene) -> None:
        """Handle 3DE scene selection."""
        self.logger.info("ThreeDESelectionHandler.on_scene_selected() signal received")
        self.logger.info(f"   Scene: {scene.full_name} (user: {scene.user})")

        # Create a Shot object from the scene for compatibility with right panel
        shot = Shot(
            show=scene.show,
            sequence=scene.sequence,
            shot=scene.shot,
            workspace_path=scene.workspace_path,
        )

        self._window.right_panel.set_shot(shot)

        self._window.setWindowTitle(
            f"{Config.APP_NAME} - {scene.full_name} ({scene.user} - {scene.plate})",
        )

        self._window.update_status(
            f"Selected: {scene.full_name} - {scene.user} ({scene.plate})",
        )

    @Slot(object)  # pyright: ignore[reportAny]
    def on_scene_double_clicked(self, scene: ThreeDEScene) -> None:
        """Handle 3DE scene double click — launch 3DE with the scene."""
        from launch.launch_request import LaunchRequest

        self.logger.info(f"Scene double-clicked: {scene.full_name} - launching 3DE")
        _ = self._command_launcher.launch(LaunchRequest(app_name="3de", scene=scene))

    @Slot(int)  # pyright: ignore[reportAny]
    def on_tab_activated(self, tab_index: int) -> None:
        """Handle tab activation — update right panel when 3DE tab is selected."""
        from ui.tab_constants import TAB_OTHER_3DE

        if tab_index != TAB_OTHER_3DE:
            return

        selected_scene = self._window.threede_shot_grid.selected_scene
        if selected_scene is not None:
            self.on_scene_selected(selected_scene)  # pyright: ignore[reportAny]
        else:
            self._command_launcher.set_current_shot(None)
            self._window.right_panel.set_shot(None)

    @Slot()  # pyright: ignore[reportAny]
    def on_recover_crashes_clicked(self) -> None:
        """Handle recover-crashes button click.

        Scans for crash files in the current workspace and presents a recovery
        dialog if any are found.
        """
        scene = self._window.threede_shot_grid.selected_scene
        if not scene:
            NotificationManager.warning(
                "No Scene Selected",
                "Please select a 3DE scene before attempting crash recovery.",
            )
            return

        workspace_path = scene.workspace_path
        self.logger.info(f"Scanning for crash files in: {workspace_path}")

        from controllers.crash_recovery import execute_crash_recovery

        execute_crash_recovery(
            workspace_path=workspace_path,
            display_name=scene.full_name,
            parent_widget=self._window.threede_shot_grid,
            post_recovery_callback=self._refresh_callback,
        )

    # ============================================================================
    # Filter Slots
    # ============================================================================

    @Slot(str)  # pyright: ignore[reportAny]
    def on_show_filter_requested(self, show: str) -> None:
        """Handle show filter requests from 3DE grid."""
        filter_show = show.strip() if show else None
        self._window.threede_proxy.set_show_filter(filter_show)
        self.logger.debug(f"3DE show filter applied: {filter_show!r}")

    @Slot(str)  # pyright: ignore[reportAny]
    def on_artist_filter_requested(self, artist: str) -> None:
        """Handle artist filter requests from 3DE grid."""
        filter_artist = artist.strip() if artist else None
        self._window.threede_proxy.set_artist_filter(filter_artist)
        self.logger.debug(f"3DE artist filter applied: {filter_artist!r}")
