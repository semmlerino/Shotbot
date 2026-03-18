"""Factory function for building the main tab widget and all three shot-view tabs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget, QWidget

from ui.design_system import TAB_BAR_STYLESHEET
from ui.proxy_models import PreviousShotsProxyModel, ShotProxyModel, ThreeDEProxyModel


if TYPE_CHECKING:
    from cache import ThumbnailCache
    from managers.hide_manager import HideManager
    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from previous_shots import PreviousShotsModel
    from previous_shots.item_model import PreviousShotsItemModel
    from previous_shots.view import PreviousShotsView
    from shots.shot_grid_view import ShotGridView
    from shots.shot_item_model import ShotItemModel
    from shots.shot_model import ShotModel
    from threede import ThreeDEGridView, ThreeDEItemModel


@dataclass
class TabComponents:
    """All components created during tab construction."""

    tab_widget: QTabWidget
    shot_item_model: ShotItemModel
    shot_proxy: ShotProxyModel
    shot_grid: ShotGridView
    threede_proxy: ThreeDEProxyModel
    threede_shot_grid: ThreeDEGridView
    previous_shots_item_model: PreviousShotsItemModel
    previous_shots_proxy: PreviousShotsProxyModel
    previous_shots_grid: PreviousShotsView


def build_tabs(
    shot_model: ShotModel,
    threede_item_model: ThreeDEItemModel,
    previous_shots_model: PreviousShotsModel,
    thumbnail_cache: ThumbnailCache,
    pin_manager: ShotPinManager,
    notes_manager: NotesManager,
    hide_manager: HideManager,
    parent: QWidget | None = None,
) -> TabComponents:
    """Build the tab widget and all three shot-view tabs."""
    from previous_shots.item_model import PreviousShotsItemModel
    from previous_shots.view import PreviousShotsView
    from shots.shot_grid_view import ShotGridView
    from shots.shot_item_model import ShotItemModel
    from threede import ThreeDEGridView

    tab_widget = QTabWidget()
    tab_widget.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # Tab 1: My Shots
    shot_item_model = ShotItemModel(
        cache_manager=thumbnail_cache,
        pin_manager=pin_manager,
        notes_manager=notes_manager,
        hide_manager=hide_manager,
    )
    shot_model.set_hide_manager(hide_manager)
    shot_item_model.set_shots(shot_model.shots)  # ALL shots, unfiltered
    shot_proxy = ShotProxyModel(parent)
    shot_proxy.set_pin_manager(pin_manager)
    shot_proxy.set_hide_manager(hide_manager)
    shot_proxy.setSourceModel(shot_item_model)
    shot_proxy.sort(0)
    shot_grid = ShotGridView(
        model=shot_item_model,
        proxy=shot_proxy,
        pin_manager=pin_manager,
        notes_manager=notes_manager,
        hide_manager=hide_manager,
    )
    _ = tab_widget.addTab(shot_grid, "My Shots")

    # Tab 2: Other 3DE scenes
    threede_proxy = ThreeDEProxyModel(parent)
    threede_proxy.set_pin_manager(pin_manager)
    threede_proxy.setSourceModel(threede_item_model)
    threede_proxy.sort(0)
    threede_shot_grid = ThreeDEGridView(
        model=threede_item_model,
        proxy=threede_proxy,
        pin_manager=pin_manager,
        notes_manager=notes_manager,
    )
    _ = tab_widget.addTab(threede_shot_grid, "Other 3DE scenes")

    # Tab 3: Previous Shots (approved/completed)
    previous_shots_item_model = PreviousShotsItemModel(
        previous_shots_model,
        thumbnail_cache,
        pin_manager=pin_manager,
        notes_manager=notes_manager,
    )
    previous_shots_proxy = PreviousShotsProxyModel(parent)
    previous_shots_proxy.set_pin_manager(pin_manager)
    previous_shots_proxy.setSourceModel(previous_shots_item_model)
    previous_shots_proxy.sort(0)
    previous_shots_grid = PreviousShotsView(
        model=previous_shots_item_model,
        proxy=previous_shots_proxy,
        pin_manager=pin_manager,
        notes_manager=notes_manager,
    )
    _ = tab_widget.addTab(previous_shots_grid, "Previous Shots")

    tab_widget.tabBar().setStyleSheet(TAB_BAR_STYLESHEET)

    return TabComponents(
        tab_widget=tab_widget,
        shot_item_model=shot_item_model,
        shot_proxy=shot_proxy,
        shot_grid=shot_grid,
        threede_proxy=threede_proxy,
        threede_shot_grid=threede_shot_grid,
        previous_shots_item_model=previous_shots_item_model,
        previous_shots_proxy=previous_shots_proxy,
        previous_shots_grid=previous_shots_grid,
    )
