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

import logging
from typing import TYPE_CHECKING, final

from PySide6.QtCore import Slot

from config import Config


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from PySide6.QtWidgets import QSlider

    from protocols import ThumbnailSizeTarget


@final
class ThumbnailSizeManager:
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
        logger.debug("ThumbnailSizeManager initialized")

    def _active_slider(self) -> QSlider:
        """Get the size slider for the currently active tab.

        Returns:
            The QSlider for the active tab (shot, 3DE, or previous shots)

        """
        tab_index = self.window.tab_widget.currentIndex()
        if tab_index == 0:
            return self.window.shot_grid.size_slider
        if tab_index == 1:
            return self.window.threede_shot_grid.size_slider
        return self.window.previous_shots_grid.size_slider

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

        logger.debug("ThumbnailSizeManager signals connected")

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
        threede_grid_was_blocked = (
            self.window.threede_shot_grid.size_slider.blockSignals(True)
        )
        previous_grid_was_blocked = (
            self.window.previous_shots_grid.size_slider.blockSignals(True)
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
        slider = self._active_slider()
        current = slider.value()
        new_size = min(current + 20, Config.Thumbnail.MAX_SIZE)
        slider.setValue(new_size)

    def decrease_size(self) -> None:
        """Decrease thumbnail size by 20px (floored at MIN_THUMBNAIL_SIZE).

        Called by View menu action (Ctrl+- keyboard shortcut).
        """
        slider = self._active_slider()
        current = slider.value()
        new_size = max(current - 20, Config.Thumbnail.MIN_SIZE)
        slider.setValue(new_size)
