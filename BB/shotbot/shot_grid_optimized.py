"""Memory-optimized shot grid widget with viewport-based loading.

DEPRECATED: This module is deprecated and will be removed in a future version.
Please use shot_grid_view.py and shot_item_model.py (Model/View architecture) instead.
The new implementation provides better memory optimization through virtualization.

Migration: See shot_grid.py for migration guide.
"""

from typing import Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config import Config
from memory_optimized_grid import MemoryOptimizedGrid, ThumbnailPlaceholder
from shot_model import Shot, ShotModel
from thumbnail_widget import ThumbnailWidget


class ShotGridOptimized(QWidget, MemoryOptimizedGrid):
    """Memory-optimized grid display of shot thumbnails."""

    # Signals
    shot_selected = Signal(object)  # Shot
    shot_double_clicked = Signal(object)  # Shot
    app_launch_requested = Signal(str)  # app_name

    def __init__(self, shot_model: ShotModel):
        QWidget.__init__(self)
        MemoryOptimizedGrid.__init__(self)

        self.shot_model = shot_model
        self.selected_shot: Optional[Shot] = None
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Size control
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

        # Scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Container widget
        self.container = QWidget()
        self.grid_layout = QGridLayout(self.container)
        self.grid_layout.setSpacing(Config.THUMBNAIL_SPACING)

        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)

        # Enable keyboard focus
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Set up viewport tracking
        self._setup_viewport_tracking(self.scroll_area)

    def refresh_shots(self):
        """Refresh the shot display with memory optimization."""
        # Clear existing - delete all widgets
        self._clear_grid(delete_widgets=True)
        self._loaded_thumbnails.clear()
        self._placeholders.clear()
        self._visible_indices.clear()

        # Create placeholders for all shots
        for i, shot in enumerate(self.shot_model.shots):
            row = i // self._get_column_count()
            col = i % self._get_column_count()

            placeholder = ThumbnailPlaceholder(index=i, row=row, col=col, data=shot)
            self._placeholders[shot.full_name] = placeholder

            # Add placeholder widget to grid
            placeholder_widget = self._create_placeholder_widget(row, col)
            self.grid_layout.addWidget(placeholder_widget, row, col)

        # Load initial visible thumbnails
        self._update_visible_thumbnails()

    def _clear_grid(self, delete_widgets: bool = False):
        """Clear all widgets from grid."""
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if delete_widgets and item.widget():
                item.widget().deleteLater()

    def _get_column_count(self) -> int:
        """Calculate number of columns based on width."""
        available_width = self.scroll_area.viewport().width()
        if available_width <= 0:
            return Config.GRID_COLUMNS

        # Calculate based on thumbnail size and spacing
        item_width = self._thumbnail_size + Config.THUMBNAIL_SPACING
        columns = max(1, available_width // item_width)
        return columns

    def _update_visible_thumbnails(self):
        """Update which thumbnails are loaded based on viewport."""
        if not self.shot_model.shots:
            return

        # Get visible range
        start_idx, end_idx = self._get_visible_range(
            self.scroll_area, self._get_column_count(), len(self.shot_model.shots)
        )

        # Update visible indices
        self._visible_indices = set(range(start_idx, end_idx))

        # Load visible thumbnails that aren't already loaded
        for idx in self._visible_indices:
            if 0 <= idx < len(self.shot_model.shots):
                shot = self.shot_model.shots[idx]
                key = shot.full_name

                if key not in self._loaded_thumbnails:
                    self._load_thumbnail_at_index(idx)

    def _load_thumbnail_at_index(self, index: int):
        """Load thumbnail at specific index."""
        if 0 <= index < len(self.shot_model.shots):
            shot = self.shot_model.shots[index]
            key = shot.full_name

            # Skip if already loaded
            if key in self._loaded_thumbnails:
                return

            # Get placeholder info
            placeholder = self._placeholders.get(key)
            if not placeholder:
                return

            # Create thumbnail widget
            thumbnail = ThumbnailWidget(shot, self._thumbnail_size)
            thumbnail.clicked.connect(self._on_thumbnail_clicked)
            thumbnail.double_clicked.connect(self._on_thumbnail_double_clicked)

            # Store in loaded dict
            self._loaded_thumbnails[key] = thumbnail

            # Replace placeholder in grid
            # First remove the placeholder widget
            item = self.grid_layout.itemAtPosition(placeholder.row, placeholder.col)
            if item and item.widget():
                item.widget().deleteLater()

            # Add thumbnail widget
            self.grid_layout.addWidget(thumbnail, placeholder.row, placeholder.col)

            # Restore selection if needed
            if self.selected_shot and self.selected_shot.full_name == key:
                thumbnail.set_selected(True)

    def _remove_from_grid(self, widget: QWidget):
        """Remove widget from grid layout."""
        self.grid_layout.removeWidget(widget)

    def _get_current_visible_indices(self) -> Set[int]:
        """Get currently visible indices."""
        return self._visible_indices.copy()

    def _reflow_grid(self):
        """Reflow grid layout based on new size."""
        if not self._placeholders:
            return

        # Clear grid without deleting widgets
        self._clear_grid(delete_widgets=False)

        # Recalculate positions
        columns = self._get_column_count()
        for i, shot in enumerate(self.shot_model.shots):
            key = shot.full_name
            if key in self._placeholders:
                # Update placeholder position
                self._placeholders[key].row = i // columns
                self._placeholders[key].col = i % columns
                self._placeholders[key].index = i

                # Add widget (either loaded thumbnail or placeholder)
                if key in self._loaded_thumbnails:
                    thumbnail = self._loaded_thumbnails[key]
                    self.grid_layout.addWidget(
                        thumbnail,
                        self._placeholders[key].row,
                        self._placeholders[key].col,
                    )
                else:
                    placeholder_widget = self._create_placeholder_widget(
                        self._placeholders[key].row, self._placeholders[key].col
                    )
                    self.grid_layout.addWidget(
                        placeholder_widget,
                        self._placeholders[key].row,
                        self._placeholders[key].col,
                    )

        # Update visible thumbnails
        self._update_visible_thumbnails()

    def _on_size_changed(self, value: int):
        """Handle thumbnail size change."""
        self._thumbnail_size = value
        self.size_label.setText(f"{value}px")

        # Update all loaded thumbnails
        for thumbnail in self._loaded_thumbnails.values():
            thumbnail.set_size(value)

        # Reflow grid
        self._reflow_grid()

    def _on_thumbnail_clicked(self, shot: Shot):
        """Handle thumbnail click."""
        # Update selection
        if self.selected_shot:
            old_key = self.selected_shot.full_name
            if old_key in self._loaded_thumbnails:
                self._loaded_thumbnails[old_key].set_selected(False)

        self.selected_shot = shot
        key = shot.full_name
        if key in self._loaded_thumbnails:
            self._loaded_thumbnails[key].set_selected(True)

        self.shot_selected.emit(shot)

    def _on_thumbnail_double_clicked(self, shot: Shot):
        """Handle thumbnail double click."""
        self.shot_double_clicked.emit(shot)

    def select_shot(self, shot: Shot):
        """Select a shot programmatically."""
        self._on_thumbnail_clicked(shot)

        # Ensure shot is visible and loaded
        key = shot.full_name
        if key in self._placeholders:
            placeholder = self._placeholders[key]

            # Scroll to make it visible
            if key in self._loaded_thumbnails:
                thumbnail = self._loaded_thumbnails[key]
                self.scroll_area.ensureWidgetVisible(thumbnail)
            else:
                # Load it if not already loaded
                self._load_thumbnail_at_index(placeholder.index)

                # Then ensure visible
                if key in self._loaded_thumbnails:
                    self.scroll_area.ensureWidgetVisible(self._loaded_thumbnails[key])

    def resizeEvent(self, event: QResizeEvent):
        """Handle resize to reflow grid."""
        super().resizeEvent(event)
        self._reflow_grid()

    def wheelEvent(self, event: QWheelEvent):
        """Handle wheel event for thumbnail size adjustment with Ctrl."""
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

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard navigation."""
        if not self.shot_model.shots:
            super().keyPressEvent(event)
            return

        # Get current selection index
        current_index = -1
        if self.selected_shot:
            for i, shot in enumerate(self.shot_model.shots):
                if shot.full_name == self.selected_shot.full_name:
                    current_index = i
                    break

        # Calculate grid dimensions
        columns = self._get_column_count()
        total_shots = len(self.shot_model.shots)

        new_index = current_index

        # Handle arrow keys
        if event.key() == Qt.Key.Key_Right:
            new_index = (
                min(current_index + 1, total_shots - 1) if current_index >= 0 else 0
            )
        elif event.key() == Qt.Key.Key_Left:
            new_index = max(current_index - 1, 0) if current_index >= 0 else 0
        elif event.key() == Qt.Key.Key_Down:
            if current_index >= 0:
                new_index = min(current_index + columns, total_shots - 1)
            else:
                new_index = 0
        elif event.key() == Qt.Key.Key_Up:
            if current_index >= 0:
                new_index = max(current_index - columns, 0)
            else:
                new_index = 0
        elif event.key() == Qt.Key.Key_Home:
            new_index = 0
        elif event.key() == Qt.Key.Key_End:
            new_index = total_shots - 1
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Double-click on current selection
            if self.selected_shot:
                self.shot_double_clicked.emit(self.selected_shot)
            event.accept()
            return
        # Application launch shortcuts
        elif event.key() == Qt.Key.Key_3:
            if self.selected_shot:
                self.app_launch_requested.emit("3de")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_N:
            if self.selected_shot:
                self.app_launch_requested.emit("nuke")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_M:
            if self.selected_shot:
                self.app_launch_requested.emit("maya")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_R:
            if self.selected_shot:
                self.app_launch_requested.emit("rv")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_P:
            if self.selected_shot:
                self.app_launch_requested.emit("publish")
            event.accept()
            return
        else:
            super().keyPressEvent(event)
            return

        # Select new shot if index changed
        if new_index != current_index and 0 <= new_index < total_shots:
            new_shot = self.shot_model.shots[new_index]
            self.select_shot(new_shot)

        event.accept()
