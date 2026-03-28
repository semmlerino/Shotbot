"""Filter and sort coordination for MainWindow grid views."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from PySide6.QtWidgets import QStatusBar

    from managers.settings_manager import SettingsManager
    from previous_shots.item_model import PreviousShotsItemModel
    from previous_shots.model import PreviousShotsModel
    from previous_shots.view import PreviousShotsView
    from threede.grid_view import ThreeDEGridView
    from threede.item_model import ThreeDEItemModel
    from ui.proxy_models import (
        PreviousShotsProxyModel,
        ShotProxyModel,
        ThreeDEProxyModel,
    )


@final
class FilterCoordinator(LoggingMixin):
    """Coordinates filter, sort, and show-filter updates across grid views.

    Extracted from MainWindow to reduce its handler count.
    """

    def __init__(
        self,
        *,
        shot_proxy: ShotProxyModel,
        previous_shots_proxy: PreviousShotsProxyModel,
        threede_proxy: ThreeDEProxyModel,
        threede_item_model: ThreeDEItemModel,
        previous_shots_item_model: PreviousShotsItemModel,
        threede_shot_grid: ThreeDEGridView,
        previous_shots_grid: PreviousShotsView,
        previous_shots_model: PreviousShotsModel,
        settings_manager: SettingsManager,
        status_bar: QStatusBar,
    ) -> None:
        super().__init__()
        self._shot_proxy = shot_proxy
        self._previous_shots_proxy = previous_shots_proxy
        self._threede_proxy = threede_proxy
        self._threede_item_model = threede_item_model
        self._previous_shots_item_model = previous_shots_item_model
        self._threede_shot_grid = threede_shot_grid
        self._previous_shots_grid = previous_shots_grid
        self._previous_shots_model = previous_shots_model
        self._settings_manager = settings_manager
        self._status_bar = status_bar

    def apply_show_filter(
        self, proxy: ShotProxyModel | PreviousShotsProxyModel, tab_label: str, show: str
    ) -> None:
        """Apply show filter to the given proxy model and update the status bar."""
        show_filter = show or None
        proxy.set_show_filter(show_filter)
        filtered_count = proxy.rowCount()
        total = proxy.sourceModel().rowCount()
        filter_desc = show or "All Shows"
        self._status_bar.showMessage(
            f"{tab_label}: {filtered_count} of {total} ({filter_desc})", 2500
        )
        self.logger.info(f"Applied {tab_label} show filter: {filter_desc}")

    def apply_text_filter(
        self, proxy: ShotProxyModel | PreviousShotsProxyModel, tab_label: str, text: str
    ) -> None:
        """Apply text filter to the given proxy model and update the status bar."""
        filter_text = text.strip() if text else None
        proxy.set_text_filter(filter_text)
        filtered_count = proxy.rowCount()
        total = proxy.sourceModel().rowCount()
        if filter_text:
            self._status_bar.showMessage(
                f"{tab_label}: {filtered_count} of {total} (filter: '{filter_text}')",
                2500,
            )
        else:
            self._status_bar.showMessage(f"{tab_label}: {total} shots", 2500)
        self.logger.debug(
            f"{tab_label} text filter: '{filter_text}' - {filtered_count} shots"
        )

    def on_previous_shots_updated(self) -> None:
        """Handle previous shots updated signal."""
        from shots.shot_filter import get_available_shows

        shows = sorted(get_available_shows(self._previous_shots_model.get_shots()))
        self._previous_shots_grid.populate_show_filter(shows)
        self.logger.debug("Previous shots updated, refreshed show filter")

    def on_sort_order_changed(
        self,
        settings_key: str,
        item_model: ThreeDEItemModel | PreviousShotsItemModel,
        order: str,
    ) -> None:
        """Handle sort order change for any grid view."""
        item_model.set_sort_order(order)
        if settings_key == "previous_shots":
            self._previous_shots_proxy.set_sort_order(order)
        elif settings_key == "threede_scenes":
            self._threede_proxy.set_sort_order(order)
        self._settings_manager.ui.set_sort_order(settings_key, order)
        self.logger.info(f"{settings_key} sort order changed to: {order}")

    def restore_sort_orders(self) -> None:
        """Restore sort order settings for each tab."""
        threede_order = self._settings_manager.ui.get_sort_order("threede_scenes")
        self._threede_item_model.set_sort_order(threede_order)
        self._threede_proxy.set_sort_order(threede_order)
        self._threede_shot_grid.set_sort_order(threede_order)
        self.logger.debug(f"Restored 3DE scenes sort order: {threede_order}")

        previous_order = self._settings_manager.ui.get_sort_order("previous_shots")
        self._previous_shots_item_model.set_sort_order(previous_order)
        self._previous_shots_proxy.set_sort_order(previous_order)
        self._previous_shots_grid.set_sort_order(previous_order)
        self.logger.debug(f"Restored Previous Shots sort order: {previous_order}")
