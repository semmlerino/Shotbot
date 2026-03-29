"""3DE tab signal wiring coordinator."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, final

from launch.launch_request import LaunchRequest


if TYPE_CHECKING:
    from controllers.filter_coordinator import FilterCoordinator
    from launch.command_launcher import CommandLauncher
    from threede.grid_view import ThreeDEGridView
    from threede.item_model import ThreeDEItemModel


@final
class ThreeDETabCoordinator:
    """Wires 3DE tab signals to their handlers.

    Owns 2 signal connections:
    1. app_launch_requested → CommandLauncher.launch (with scene)
    2. sort_order_changed → FilterCoordinator.on_sort_order_changed
    """

    def __init__(
        self,
        threede_shot_grid: ThreeDEGridView,
        threede_item_model: ThreeDEItemModel,
        filter_coordinator: FilterCoordinator,
        command_launcher: CommandLauncher,
    ) -> None:
        self._threede_shot_grid = threede_shot_grid
        self._threede_item_model = threede_item_model
        self._filter_coordinator = filter_coordinator
        self._command_launcher = command_launcher

    def connect_signals(self) -> None:
        """Connect 3DE tab signals."""
        _ = self._threede_shot_grid.app_launch_requested.connect(
            lambda app_name, scene: self._command_launcher.launch(  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
                LaunchRequest(app_name=app_name, scene=scene)  # pyright: ignore[reportUnknownArgumentType]
            )
        )
        _ = self._threede_shot_grid.sort_order_changed.connect(
            partial(
                self._filter_coordinator.on_sort_order_changed,
                "threede_scenes",
                self._threede_item_model,
            )
        )
