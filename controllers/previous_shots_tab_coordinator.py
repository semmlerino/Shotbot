"""Previous Shots tab signal wiring coordinator."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, final

from launch.launch_request import LaunchRequest


if TYPE_CHECKING:
    from controllers.filter_coordinator import FilterCoordinator
    from launch.command_launcher import CommandLauncher
    from managers.shot_pin_manager import ShotPinManager
    from previous_shots.item_model import PreviousShotsItemModel
    from previous_shots.view import PreviousShotsView
    from type_definitions import Shot
    from ui.proxy_models import PreviousShotsProxyModel


@final
class PreviousShotsTabCoordinator:
    """Wires Previous Shots tab signals to their handlers.

    Owns 6 signal connections:
    1. show_filter_requested → FilterCoordinator.apply_show_filter
    2. text_filter_requested → FilterCoordinator.apply_text_filter
    3. shots_updated → FilterCoordinator.on_previous_shots_updated
    4. app_launch_requested → CommandLauncher.launch
    5. sort_order_changed → FilterCoordinator.on_sort_order_changed
    6. pin_shot_requested → _on_pin_requested
    """

    def __init__(
        self,
        previous_shots_grid: PreviousShotsView,
        previous_shots_proxy: PreviousShotsProxyModel,
        previous_shots_item_model: PreviousShotsItemModel,
        filter_coordinator: FilterCoordinator,
        command_launcher: CommandLauncher,
        pin_manager: ShotPinManager,
    ) -> None:
        self._previous_shots_grid = previous_shots_grid
        self._previous_shots_proxy = previous_shots_proxy
        self._previous_shots_item_model = previous_shots_item_model
        self._filter_coordinator = filter_coordinator
        self._command_launcher = command_launcher
        self._pin_manager = pin_manager

    def connect_signals(self) -> None:
        """Connect Previous Shots tab signals."""
        _ = self._previous_shots_grid.show_filter_requested.connect(
            partial(
                self._filter_coordinator.apply_show_filter,
                self._previous_shots_proxy,
                "Previous Shots",
            )  # pyright: ignore[reportAny]
        )
        _ = self._previous_shots_grid.text_filter_requested.connect(
            partial(
                self._filter_coordinator.apply_text_filter,
                self._previous_shots_proxy,
                "Previous Shots",
            )  # pyright: ignore[reportAny]
        )
        _ = self._previous_shots_item_model.shots_updated.connect(
            self._filter_coordinator.on_previous_shots_updated  # pyright: ignore[reportAny]
        )
        _ = self._previous_shots_grid.app_launch_requested.connect(
            lambda app_name: self._command_launcher.launch(  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
                LaunchRequest(app_name=app_name)  # pyright: ignore[reportUnknownArgumentType]
            )
        )
        _ = self._previous_shots_grid.sort_order_changed.connect(
            partial(
                self._filter_coordinator.on_sort_order_changed,
                "previous_shots",
                self._previous_shots_item_model,
            )
        )
        _ = self._previous_shots_grid.pin_shot_requested.connect(self._on_pin_requested)

    def _on_pin_requested(self, shot: Shot) -> None:
        """Handle pin request from the Previous Shots grid."""
        self._pin_manager.pin_shot(shot)
        self._previous_shots_proxy.refresh_sort()
