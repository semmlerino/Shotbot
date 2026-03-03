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

from typing import TYPE_CHECKING, Any, Protocol, final

from PySide6.QtCore import Slot

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from PySide6.QtWidgets import QStatusBar

    from base_shot_model import BaseShotModel  # used in cast()
    from previous_shots_item_model import PreviousShotsItemModel
    from previous_shots_model import PreviousShotsModel
    from previous_shots_view import PreviousShotsView
    from shot_grid_view import ShotGridView
    from shot_item_model import ShotItemModel
    from shot_model import ShotModel


class FilterableItemModel(Protocol):
    """Protocol for item models that support show filtering."""

    def set_show_filter(self, __model: Any, __show_filter: str | None) -> None: ...
    def rowCount(self) -> int: ...


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
            self._on_shot_show_filter_requested
        )
        _ = self.window.shot_grid.text_filter_requested.connect(
            self._on_shot_text_filter_requested
        )

        # Previous Shots filter signals
        _ = self.window.previous_shots_grid.show_filter_requested.connect(
            self._on_previous_show_filter_requested
        )
        _ = self.window.previous_shots_grid.text_filter_requested.connect(
            self._on_previous_text_filter_requested
        )

        # Previous shots model updates (repopulate show filter when shots change)
        _ = self.window.previous_shots_item_model.shots_updated.connect(
            self._on_previous_shots_updated
        )

        self.logger.debug("FilterCoordinator signals connected")

    def _apply_show_filter(
        self, item_model: FilterableItemModel, model: Any, show: str, tab_name: str
    ) -> None:
        """Generic show filter handler for all tabs.

        Args:
            item_model: The item model to apply the filter to
            model: The data model to pass to the item model
            show: Show name to filter by, or empty string for all shows
            tab_name: Human-readable tab name for logging

        """
        # Convert empty string back to None for the model
        show_filter = show if show else None

        # Apply filter to item model
        # Different item models have varying set_show_filter signatures
        item_model.set_show_filter(model, show_filter)

        # Get filtered count for status
        filtered_count = int(item_model.rowCount())
        filter_desc = show if show else "All Shows"
        self.window.status_bar.showMessage(
            f"{tab_name}: {filtered_count} shots ({filter_desc})", 2500
        )

        self.logger.info(
            f"Applied {tab_name} show filter: {show if show else 'All Shows'}"
        )

    @Slot(str)
    def _on_shot_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from My Shots grid view."""
        self._apply_show_filter(
            self.window.shot_item_model, self.window.shot_model, show, "My Shots"
        )

    @Slot(str)
    def _on_shot_text_filter_requested(self, text: str) -> None:
        """Handle text filter request from My Shots grid view."""
        from typing import cast

        filter_text = text.strip() if text else None
        # Cast to BaseShotModel to access inherited methods
        base_model = cast("BaseShotModel", self.window.shot_model)
        base_model.set_text_filter(filter_text)

        # Update item model with filtered shots
        filtered_shots = base_model.get_filtered_shots()
        # Use set_shots() to apply pin-aware sorting
        self.window.shot_item_model.set_shots(filtered_shots)

        # Show brief status with filter result
        total_shots = len(self.window.shot_model.shots)
        filtered_count = len(filtered_shots)
        if filter_text:
            self.window.status_bar.showMessage(
                f"My Shots: {filtered_count} of {total_shots} (filter: '{filter_text}')",
                2500,
            )
        else:
            self.window.status_bar.showMessage(f"My Shots: {total_shots} shots", 2500)

        self.logger.debug(
            f"My Shots text filter applied: '{filter_text}' - {len(filtered_shots)} shots"
        )

    @Slot(str)
    def _on_previous_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from Previous Shots grid view."""
        self._apply_show_filter(
            self.window.previous_shots_item_model,
            self.window.previous_shots_model,
            show,
            "Previous Shots",
        )

    @Slot(str)
    def _on_previous_text_filter_requested(self, text: str) -> None:
        """Handle text filter request from Previous Shots grid view."""
        filter_text = text.strip() if text else None
        self.window.previous_shots_model.set_text_filter(filter_text)

        # Update item model with filtered shots
        filtered_shots = self.window.previous_shots_model.get_filtered_shots()
        # Use set_shots() to apply pin-aware sorting
        self.window.previous_shots_item_model.set_shots(filtered_shots)

        # Show brief status with filter result
        total_shots = len(self.window.previous_shots_model.get_shots())
        filtered_count = len(filtered_shots)
        if filter_text:
            self.window.status_bar.showMessage(
                f"Previous Shots: {filtered_count} of {total_shots} (filter: '{filter_text}')",
                2500,
            )
        else:
            self.window.status_bar.showMessage(
                f"Previous Shots: {total_shots} shots", 2500
            )

        self.logger.debug(
            f"Previous Shots text filter applied: '{filter_text}' - {len(filtered_shots)} shots"
        )

    @Slot()
    def _on_previous_shots_updated(self) -> None:
        """Handle previous shots updated signal."""
        # Populate show filter with available shows
        self.window.previous_shots_grid.populate_show_filter(
            self.window.previous_shots_model
        )
        self.logger.debug("Previous shots updated, refreshed show filter")
