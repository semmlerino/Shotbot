"""Filter coordinator for MainWindow refactoring.

Manages filter logic across My Shots and Previous Shots tabs:
- Show filter handling (filter by show name)
- Text filter handling (filter by shot name)
- Status bar updates for filter results

This controller extracts filter functionality from MainWindow into
a focused, testable component following the Protocol-based dependency
injection pattern established by SettingsController and ThreeDEController.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final

from PySide6.QtCore import Slot

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from PySide6.QtWidgets import QStatusBar

    from previous_shots.item_model import PreviousShotsItemModel
    from previous_shots.model import PreviousShotsModel
    from previous_shots.view import PreviousShotsView
    from proxy_models import PreviousShotsProxyModel, ShotProxyModel
    from shot_grid_view import ShotGridView
    from shot_item_model import ShotItemModel
    from shot_model import ShotModel


class FilterTarget(Protocol):
    """Protocol defining interface required by FilterCoordinator.

    This protocol specifies the minimal interface that MainWindow must provide
    to the FilterCoordinator for proper operation.
    """

    # Grid views
    shot_grid: ShotGridView
    previous_shots_grid: PreviousShotsView

    # Data models
    shot_model: ShotModel
    previous_shots_model: PreviousShotsModel

    # Item models
    shot_item_model: ShotItemModel
    previous_shots_item_model: PreviousShotsItemModel

    # Proxy models
    shot_proxy: ShotProxyModel
    previous_shots_proxy: PreviousShotsProxyModel

    # Status bar
    status_bar: QStatusBar


@final
class FilterCoordinator(LoggingMixin):
    """Controller for filter operations across shot grids.

    This controller encapsulates all filter functionality that was
    previously part of MainWindow, providing clean separation of concerns
    and improved testability.

    Note: 3DE filtering is handled by ThreeDEController, not here.
    """

    def __init__(self, window: FilterTarget) -> None:
        """Initialize filter coordinator.

        Args:
            window: MainWindow instance implementing FilterTarget protocol

        """
        super().__init__()
        self.window: FilterTarget = window
        self._setup_signals()
        self.logger.debug("FilterCoordinator initialized")

    def _setup_signals(self) -> None:
        """Connect filter signals from grid views."""
        # My Shots filter signals
        _ = self.window.shot_grid.show_filter_requested.connect(
            self._on_shot_show_filter_requested  # pyright: ignore[reportAny]
        )
        _ = self.window.shot_grid.text_filter_requested.connect(
            self._on_shot_text_filter_requested  # pyright: ignore[reportAny]
        )

        # Previous Shots filter signals
        _ = self.window.previous_shots_grid.show_filter_requested.connect(
            self._on_previous_show_filter_requested  # pyright: ignore[reportAny]
        )
        _ = self.window.previous_shots_grid.text_filter_requested.connect(
            self._on_previous_text_filter_requested  # pyright: ignore[reportAny]
        )

        # Previous shots model updates (repopulate show filter when shots change)
        _ = self.window.previous_shots_item_model.shots_updated.connect(
            self._on_previous_shots_updated  # pyright: ignore[reportAny]
        )

        self.logger.debug("FilterCoordinator signals connected")

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_shot_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from My Shots grid view."""
        show_filter = show or None
        self.window.shot_proxy.set_show_filter(show_filter)

        filtered_count = self.window.shot_proxy.rowCount()
        total = self.window.shot_proxy.sourceModel().rowCount()
        filter_desc = show or "All Shows"
        self.window.status_bar.showMessage(
            f"My Shots: {filtered_count} of {total} ({filter_desc})", 2500
        )
        self.logger.info(f"Applied My Shots show filter: {filter_desc}")

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_shot_text_filter_requested(self, text: str) -> None:
        """Handle text filter request from My Shots grid view."""
        filter_text = text.strip() if text else None
        self.window.shot_proxy.set_text_filter(filter_text)

        filtered_count = self.window.shot_proxy.rowCount()
        total = self.window.shot_proxy.sourceModel().rowCount()
        if filter_text:
            self.window.status_bar.showMessage(
                f"My Shots: {filtered_count} of {total} (filter: '{filter_text}')", 2500
            )
        else:
            self.window.status_bar.showMessage(f"My Shots: {total} shots", 2500)
        self.logger.debug(f"My Shots text filter: '{filter_text}' - {filtered_count} shots")

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_previous_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from Previous Shots grid view."""
        show_filter = show or None
        self.window.previous_shots_proxy.set_show_filter(show_filter)

        filtered_count = self.window.previous_shots_proxy.rowCount()
        total = self.window.previous_shots_proxy.sourceModel().rowCount()
        filter_desc = show or "All Shows"
        self.window.status_bar.showMessage(
            f"Previous Shots: {filtered_count} of {total} ({filter_desc})", 2500
        )
        self.logger.info(f"Applied Previous Shots show filter: {filter_desc}")

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_previous_text_filter_requested(self, text: str) -> None:
        """Handle text filter request from Previous Shots grid view."""
        filter_text = text.strip() if text else None
        self.window.previous_shots_proxy.set_text_filter(filter_text)

        filtered_count = self.window.previous_shots_proxy.rowCount()
        total = self.window.previous_shots_proxy.sourceModel().rowCount()
        if filter_text:
            self.window.status_bar.showMessage(
                f"Previous Shots: {filtered_count} of {total} (filter: '{filter_text}')",
                2500,
            )
        else:
            self.window.status_bar.showMessage(
                f"Previous Shots: {total} shots", 2500
            )
        self.logger.debug(f"Previous Shots text filter: '{filter_text}' - {filtered_count} shots")

    @Slot()  # pyright: ignore[reportAny]
    def _on_previous_shots_updated(self) -> None:
        """Handle previous shots updated signal."""
        # Populate show filter with available shows
        self.window.previous_shots_grid.populate_show_filter(
            self.window.previous_shots_model
        )
        self.logger.debug("Previous shots updated, refreshed show filter")
