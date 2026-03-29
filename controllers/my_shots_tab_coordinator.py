"""My Shots tab signal wiring coordinator."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, final

from launch.launch_request import LaunchRequest


if TYPE_CHECKING:
    from controllers.filter_coordinator import FilterCoordinator
    from launch.command_launcher import CommandLauncher
    from managers.shot_pin_manager import ShotPinManager
    from shots.shot_grid_view import ShotGridView
    from type_definitions import Shot
    from ui.proxy_models import ShotProxyModel


@final
class MyShotsTabCoordinator:
    """Wires My Shots tab signals to their handlers.

    Owns 6 signal connections:
    1. show_filter_requested → FilterCoordinator.apply_show_filter
    2. text_filter_requested → FilterCoordinator.apply_text_filter
    3. app_launch_requested → CommandLauncher.launch
    4. shot_visibility_changed → shot_proxy.invalidate
    5. show_hidden_changed → shot_proxy.set_show_hidden
    6. pin_shot_requested → _on_pin_requested
    """

    def __init__(
        self,
        shot_grid: ShotGridView,
        shot_proxy: ShotProxyModel,
        filter_coordinator: FilterCoordinator,
        command_launcher: CommandLauncher,
        pin_manager: ShotPinManager,
    ) -> None:
        self._shot_grid = shot_grid
        self._shot_proxy = shot_proxy
        self._filter_coordinator = filter_coordinator
        self._command_launcher = command_launcher
        self._pin_manager = pin_manager

    def connect_signals(self) -> None:
        """Connect My Shots tab signals."""
        _ = self._shot_grid.show_filter_requested.connect(
            partial(
                self._filter_coordinator.apply_show_filter, self._shot_proxy, "My Shots"
            )  # pyright: ignore[reportAny]
        )
        _ = self._shot_grid.text_filter_requested.connect(
            partial(
                self._filter_coordinator.apply_text_filter, self._shot_proxy, "My Shots"
            )  # pyright: ignore[reportAny]
        )
        _ = self._shot_grid.app_launch_requested.connect(
            lambda app_name: self._command_launcher.launch(  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
                LaunchRequest(app_name=app_name)  # pyright: ignore[reportUnknownArgumentType]
            )
        )
        _ = self._shot_grid.shot_visibility_changed.connect(
            lambda: self._shot_proxy.invalidate()
        )
        _ = self._shot_grid.show_hidden_changed.connect(self._shot_proxy.set_show_hidden)
        _ = self._shot_grid.pin_shot_requested.connect(self._on_pin_requested)

    def _on_pin_requested(self, shot: Shot) -> None:
        """Handle pin request from the My Shots grid."""
        self._pin_manager.pin_shot(shot)
        self._shot_proxy.refresh_sort()
