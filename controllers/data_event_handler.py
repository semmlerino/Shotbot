"""Data event handlers extracted from MainWindow."""
from __future__ import annotations

from typing import TYPE_CHECKING, final

from logging_mixin import LoggingMixin
from managers.notification_manager import NotificationManager


if TYPE_CHECKING:
    from PySide6.QtWidgets import QStatusBar

    from managers.shot_pin_manager import ShotPinManager
    from type_definitions import Shot
    from ui.proxy_models import PreviousShotsProxyModel, ShotProxyModel


@final
class DataEventHandler(LoggingMixin):
    """Handles shot model data events, visibility changes, and pin requests.

    Extracted from MainWindow to reduce its handler count.
    """

    def __init__(
        self,
        *,
        shot_proxy: ShotProxyModel,
        previous_shots_proxy: PreviousShotsProxyModel,
        pin_manager: ShotPinManager,
        status_bar: QStatusBar,
    ) -> None:
        super().__init__()
        self._shot_proxy = shot_proxy
        self._previous_shots_proxy = previous_shots_proxy
        self._pin_manager = pin_manager
        self._status_bar = status_bar

    def on_shot_error(self, error_msg: str) -> None:
        """Handle error signal from model."""
        self.logger.error(f"Shot model error: {error_msg}")
        self._status_bar.showMessage(f"Error: {error_msg}")

    def on_data_recovery(self, title: str, details: str) -> None:
        """Handle data recovery notification from model."""
        self.logger.warning(f"Data recovery: {title} - {details}")
        NotificationManager.warning(title, details)

    def on_background_load_started(self) -> None:
        """Handle background load started signal from model."""
        self._status_bar.showMessage("Fetching fresh data...")

    def on_background_load_finished(self) -> None:
        """Handle background load finished signal from model."""
        pass  # noqa: PIE790

    def on_cache_updated(self) -> None:
        """Handle cache updated signal from model."""
        self.logger.debug("Shot cache updated")

    def on_shot_visibility_changed(self) -> None:
        """Handle shot hide/unhide — refresh the shot grid display."""
        self._shot_proxy.invalidate()

    def on_show_hidden_changed(self, show: bool) -> None:
        """Handle Show Hidden checkbox toggle."""
        self._shot_proxy.set_show_hidden(show)

    def on_shot_grid_pin_requested(self, shot: Shot) -> None:
        """Handle pin request from the My Shots grid."""
        self._pin_manager.pin_shot(shot)
        self._shot_proxy.refresh_sort()

    def on_previous_shots_pin_requested(self, shot: Shot) -> None:
        """Handle pin request from the Previous Shots grid."""
        self._pin_manager.pin_shot(shot)
        self._previous_shots_proxy.refresh_sort()
