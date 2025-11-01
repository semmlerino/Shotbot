"""Optimized grid view for shot thumbnails using Qt Model/View architecture.

This module provides a QListView-based implementation that replaces the manual
widget management approach, providing virtualization, efficient scrolling,
and proper Model/View integration.
"""

import logging
from typing import Optional

from PySide6.QtCore import (
    QModelIndex,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config import Config
from shot_grid_delegate import ShotGridDelegate
from shot_item_model import ShotItemModel, ShotRole

logger = logging.getLogger(__name__)


class ShotGridView(QWidget):
    """Optimized grid view for displaying shot thumbnails.

    This view provides:
    - Virtualization (only renders visible items)
    - Efficient scrolling for large datasets
    - Lazy loading of thumbnails
    - Proper Model/View integration
    - Dynamic grid layout based on window size
    """

    # Signals
    shot_selected = Signal(object)  # Shot object
    shot_double_clicked = Signal(object)  # Shot object
    app_launch_requested = Signal(str)  # app_name

    def __init__(
        self, model: Optional[ShotItemModel] = None, parent: Optional[QWidget] = None
    ):
        """Initialize the grid view.

        Args:
            model: Optional shot item model
            parent: Optional parent widget
        """
        super().__init__(parent)

        self._model = model
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE
        self._selected_shot = None

        self._setup_ui()

        if model:
            self.set_model(model)

        # Visibility tracking timer for lazy loading
        self._visibility_timer = QTimer()
        self._visibility_timer.timeout.connect(self._update_visible_range)
        self._visibility_timer.setInterval(100)
        self._visibility_timer.start()

        logger.info("ShotGridView initialized with Model/View architecture")

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Size control slider
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Thumbnail Size:"))

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setMinimum(Config.MIN_THUMBNAIL_SIZE)
        self.size_slider.setMaximum(Config.MAX_THUMBNAIL_SIZE)
        self.size_slider.setValue(self._thumbnail_size)
        self.size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.size_slider.setTickInterval(50)
        self.size_slider.valueChanged.connect(self._on_size_changed)
        size_layout.addWidget(self.size_slider)

        self.size_label = QLabel(f"{self._thumbnail_size}px")
        self.size_label.setMinimumWidth(50)
        size_layout.addWidget(self.size_label)

        layout.addLayout(size_layout)

        # Create QListView with grid mode
        self.list_view = QListView()
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setLayoutMode(QListView.LayoutMode.Batched)
        self.list_view.setBatchSize(20)  # Process 20 items at a time
        self.list_view.setUniformItemSizes(True)  # Optimization for equal-sized items
        self.list_view.setSpacing(Config.THUMBNAIL_SPACING)

        # Set selection behavior
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )

        # Enable smooth scrolling
        self.list_view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.list_view.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )

        # Create and set custom delegate
        self._delegate = ShotGridDelegate(self)
        self.list_view.setItemDelegate(self._delegate)

        # Connect signals
        self.list_view.clicked.connect(self._on_item_clicked)
        self.list_view.doubleClicked.connect(self._on_item_double_clicked)

        layout.addWidget(self.list_view)

        # Enable keyboard focus
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.list_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def refresh_shots(self) -> None:
        """Compatibility method for refreshing shots.

        This method exists for compatibility with the old ShotGrid interface.
        It's not needed for Model/View as updates happen through the model.
        """
        # Model/View updates automatically when model data changes
        # This method is kept for interface compatibility
        if self._model:
            # Force a view update
            self.list_view.viewport().update()
            logger.debug("View refresh requested (Model/View updates automatically)")

    def set_model(self, model: ShotItemModel) -> None:
        """Set the data model for the view.

        Args:
            model: Shot item model
        """
        self._model = model
        self.list_view.setModel(model)

        # Set up selection model
        selection_model = self.list_view.selectionModel()
        if selection_model:
            selection_model.currentChanged.connect(self._on_selection_changed)

        # Connect to model signals
        model.shots_updated.connect(self._on_model_updated)

        logger.debug(f"Model set with {model.rowCount()} items")

    @Slot()
    def _on_model_updated(self) -> None:
        """Handle model updates."""
        # Update grid layout based on new item count
        self._update_grid_size()

        # Reset visible range tracking
        self._update_visible_range()

    @Slot(QModelIndex)
    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Handle item click.

        Args:
            index: Clicked model index
        """
        if not index.isValid() or not self._model:
            return

        shot = index.data(ShotRole.ShotObjectRole)
        if shot:
            self._selected_shot = shot

            # Update selection in model
            self._model.setData(index, True, ShotRole.IsSelectedRole)

            # Emit signal
            self.shot_selected.emit(shot)

            logger.debug(f"Shot selected: {shot.full_name}")

    @Slot(QModelIndex)
    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """Handle item double-click.

        Args:
            index: Double-clicked model index
        """
        if not index.isValid() or not self._model:
            return

        shot = index.data(ShotRole.ShotObjectRole)
        if shot:
            self.shot_double_clicked.emit(shot)
            logger.debug(f"Shot double-clicked: {shot.full_name}")

    @Slot(QModelIndex, QModelIndex)
    def _on_selection_changed(
        self, current: QModelIndex, previous: QModelIndex
    ) -> None:
        """Handle selection change.

        Args:
            current: Current selection index
            previous: Previous selection index
        """
        if not self._model:
            return

        # Clear previous selection in model
        if previous.isValid():
            self._model.setData(previous, False, ShotRole.IsSelectedRole)

        # Set current selection in model
        if current.isValid():
            self._model.setData(current, True, ShotRole.IsSelectedRole)

            shot = current.data(ShotRole.ShotObjectRole)
            if shot:
                self._selected_shot = shot
                self.shot_selected.emit(shot)

    @Slot(int)
    def _on_size_changed(self, size: int) -> None:
        """Handle thumbnail size change.

        Args:
            size: New thumbnail size
        """
        self._thumbnail_size = size
        self.size_label.setText(f"{size}px")

        # Update delegate size
        self._delegate.set_thumbnail_size(size)

        # Update grid size
        self._update_grid_size()

        # Force view update
        self.list_view.viewport().update()

        logger.debug(f"Thumbnail size changed to {size}px")

    def _update_grid_size(self) -> None:
        """Update the grid size based on thumbnail size."""
        # Calculate item size including padding
        item_size = self._thumbnail_size + 2 * 8 + 40  # padding + text height

        # Set grid size on the view
        self.list_view.setGridSize(QSize(item_size, item_size))

        # Update uniform item sizes
        self.list_view.setUniformItemSizes(True)

    @Slot()
    def _update_visible_range(self) -> None:
        """Update the visible item range for lazy loading."""
        if not self._model:
            return

        # Get visible rectangle
        viewport = self.list_view.viewport()
        visible_rect = viewport.rect()

        # Find first and last visible items
        first_index = self.list_view.indexAt(visible_rect.topLeft())
        last_index = self.list_view.indexAt(visible_rect.bottomRight())

        if not first_index.isValid():
            first_index = self._model.index(0, 0)

        if not last_index.isValid():
            last_index = self._model.index(self._model.rowCount() - 1, 0)

        # Update model's visible range for lazy thumbnail loading
        if first_index.isValid() and last_index.isValid():
            self._model.set_visible_range(first_index.row(), last_index.row() + 1)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle wheel event for thumbnail size adjustment with Ctrl.

        Args:
            event: Wheel event
        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                new_size = min(self._thumbnail_size + 10, Config.MAX_THUMBNAIL_SIZE)
            else:
                new_size = max(self._thumbnail_size - 10, Config.MIN_THUMBNAIL_SIZE)

            self.size_slider.setValue(new_size)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts.

        Args:
            event: Key event
        """
        if not self._selected_shot:
            super().keyPressEvent(event)
            return

        # Application launch shortcuts
        key_map = {
            Qt.Key.Key_3: "3de",
            Qt.Key.Key_N: "nuke",
            Qt.Key.Key_M: "maya",
            Qt.Key.Key_R: "rv",
            Qt.Key.Key_P: "publish",
        }

        if event.key() in key_map:
            self.app_launch_requested.emit(key_map[event.key()])
            event.accept()
        else:
            # Let QListView handle navigation
            self.list_view.keyPressEvent(event)

    def select_shot_by_name(self, shot_name: str) -> None:
        """Select a shot by its full name.

        Args:
            shot_name: Full shot name to select
        """
        if not self._model:
            return

        # Find the shot in the model
        for row in range(self._model.rowCount()):
            index = self._model.index(row, 0)
            shot = index.data(ShotRole.ShotObjectRole)

            if shot and shot.full_name == shot_name:
                # Select in view
                self.list_view.setCurrentIndex(index)

                # Ensure it's visible
                self.list_view.scrollTo(
                    index, QAbstractItemView.ScrollHint.PositionAtCenter
                )

                # Trigger selection
                self._on_item_clicked(index)
                break

    def clear_selection(self) -> None:
        """Clear the current selection."""
        if self.list_view.selectionModel():
            self.list_view.selectionModel().clear()

        self._selected_shot = None

    def refresh_view(self) -> None:
        """Force a complete view refresh."""
        self.list_view.viewport().update()
        self._update_visible_range()


# Example usage
if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    from shot_model import Shot

    app = QApplication(sys.argv)

    # Create sample data
    shots = [
        Shot("show1", "seq01", f"shot{i:04d}", f"/shows/show1/shots/seq01/shot{i:04d}")
        for i in range(100)
    ]

    # Create model and view
    model = ShotItemModel()
    model.set_shots(shots)

    view = ShotGridView(model)
    view.resize(800, 600)
    view.show()

    # Connect signals
    view.shot_selected.connect(lambda shot: print(f"Selected: {shot.full_name}"))
    view.shot_double_clicked.connect(
        lambda shot: print(f"Double-clicked: {shot.full_name}")
    )

    sys.exit(app.exec())
