"""Thumbnail size manager for MainWindow refactoring.

Manages thumbnail size synchronization across all grid tabs:
- Size slider synchronization between My Shots, 3DE Scenes, and Previous Shots
- Keyboard shortcuts (Ctrl++, Ctrl+-) for size adjustment
- Thread-safe signal blocking to prevent recursion

This controller extracts thumbnail size functionality from MainWindow into
a focused, testable component following the Protocol-based dependency
injection pattern established by SettingsController and ThreeDEController.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final

from PySide6.QtCore import Slot

from config import Config
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from PySide6.QtWidgets import QTabWidget

    from previous_shots_view import PreviousShotsView
    from shot_grid_view import ShotGridView
    from threede_grid_view import ThreeDEGridView


class ThumbnailSizeTarget(Protocol):
    """Protocol defining interface required by ThumbnailSizeManager.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ThumbnailSizeManager for proper operation.
    """

    # Grid views (each has size_slider and size_label)
    shot_grid: ShotGridView
    threede_shot_grid: ThreeDEGridView
    previous_shots_grid: PreviousShotsView

    # Tab widget for determining active tab
    tab_widget: QTabWidget


@final
class ThumbnailSizeManager(LoggingMixin):
    """Controller for thumbnail size synchronization across grid tabs.

    This controller encapsulates all thumbnail size functionality that was
    previously part of MainWindow, providing clean separation of concerns
    and improved testability.

    Features:
    - Synchronizes size sliders across all 3 tabs
    - Handles Ctrl++/Ctrl+- menu actions
    - Uses signal blocking to prevent recursive updates
    """

    def __init__(self, window: ThumbnailSizeTarget) -> None:
        """Initialize thumbnail size manager.

        Args:
            window: MainWindow instance implementing ThumbnailSizeTarget protocol

        """
        super().__init__()
        self.window: ThumbnailSizeTarget = window
        self._setup_signals()
        self.logger.debug("ThumbnailSizeManager initialized")

    def _setup_signals(self) -> None:
        """Connect size slider signals from all grid views."""
        _ = self.window.shot_grid.size_slider.valueChanged.connect(
            self.sync_thumbnail_sizes  # pyright: ignore[reportAny]
        )
        _ = self.window.threede_shot_grid.size_slider.valueChanged.connect(
            self.sync_thumbnail_sizes  # pyright: ignore[reportAny]
        )
        _ = self.window.previous_shots_grid.size_slider.valueChanged.connect(
            self.sync_thumbnail_sizes  # pyright: ignore[reportAny]
        )

        self.logger.debug("ThumbnailSizeManager signals connected")

    @Slot(int)  # pyright: ignore[reportAny]
    def sync_thumbnail_sizes(self, value: int) -> None:
        """Synchronize thumbnail sizes between all tabs.

        Uses signal blocking instead of disconnection to prevent race conditions.
        This is thread-safe and guaranteed to restore signal state.

        Args:
            value: New thumbnail size in pixels

        """
        # Block signals temporarily to prevent recursion
        shot_grid_was_blocked = self.window.shot_grid.size_slider.blockSignals(True)
        threede_grid_was_blocked = self.window.threede_shot_grid.size_slider.blockSignals(
            True
        )
        previous_grid_was_blocked = self.window.previous_shots_grid.size_slider.blockSignals(
            True
        )

        try:
            # Update all sliders without triggering signals
            self.window.shot_grid.size_slider.setValue(value)
            self.window.threede_shot_grid.size_slider.setValue(value)
            self.window.previous_shots_grid.size_slider.setValue(value)

            # Update size labels
            self.window.shot_grid.size_label.setText(f"{value}px")
            self.window.threede_shot_grid.size_label.setText(f"{value}px")
            self.window.previous_shots_grid.size_label.setText(f"{value}px")
        finally:
            # Always restore signal state, even if an exception occurs
            _ = self.window.shot_grid.size_slider.blockSignals(shot_grid_was_blocked)
            _ = self.window.threede_shot_grid.size_slider.blockSignals(
                threede_grid_was_blocked
            )
            _ = self.window.previous_shots_grid.size_slider.blockSignals(
                previous_grid_was_blocked
            )

    def increase_size(self) -> None:
        """Increase thumbnail size by 20px (capped at MAX_THUMBNAIL_SIZE).

        Called by View menu action (Ctrl++ keyboard shortcut).
        """
        # Get current size from active tab
        tab_index = self.window.tab_widget.currentIndex()
        if tab_index == 0:
            current = self.window.shot_grid.size_slider.value()
        elif tab_index == 1:
            current = self.window.threede_shot_grid.size_slider.value()
        else:
            current = self.window.previous_shots_grid.size_slider.value()

        new_size = min(current + 20, Config.MAX_THUMBNAIL_SIZE)

        # Setting the slider value triggers sync_thumbnail_sizes via signal
        if tab_index == 0:
            self.window.shot_grid.size_slider.setValue(new_size)
        elif tab_index == 1:
            self.window.threede_shot_grid.size_slider.setValue(new_size)
        else:
            self.window.previous_shots_grid.size_slider.setValue(new_size)

    def decrease_size(self) -> None:
        """Decrease thumbnail size by 20px (floored at MIN_THUMBNAIL_SIZE).

        Called by View menu action (Ctrl+- keyboard shortcut).
        """
        # Get current size from active tab
        tab_index = self.window.tab_widget.currentIndex()
        if tab_index == 0:
            current = self.window.shot_grid.size_slider.value()
        elif tab_index == 1:
            current = self.window.threede_shot_grid.size_slider.value()
        else:
            current = self.window.previous_shots_grid.size_slider.value()

        new_size = max(current - 20, Config.MIN_THUMBNAIL_SIZE)

        # Setting the slider value triggers sync_thumbnail_sizes via signal
        if tab_index == 0:
            self.window.shot_grid.size_slider.setValue(new_size)
        elif tab_index == 1:
            self.window.threede_shot_grid.size_slider.setValue(new_size)
        else:
            self.window.previous_shots_grid.size_slider.setValue(new_size)
