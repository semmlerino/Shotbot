"""Shot grid widget for displaying thumbnails in a grid layout."""

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent, QWheelEvent
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
from shot_model import Shot, ShotModel
from thumbnail_widget import ThumbnailWidget


class ShotGrid(QWidget):
    """Grid display of shot thumbnails."""

    # Signals
    shot_selected = Signal(object)  # Shot
    shot_double_clicked = Signal(object)  # Shot

    def __init__(self, shot_model: ShotModel):
        super().__init__()
        self.shot_model = shot_model
        self.thumbnails: Dict[str, ThumbnailWidget] = {}
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

    def refresh_shots(self):
        """Refresh the shot display."""
        # Clear existing thumbnails
        self._clear_grid()

        # Create thumbnails for all shots
        for i, shot in enumerate(self.shot_model.shots):
            thumbnail = ThumbnailWidget(shot, self._thumbnail_size)
            thumbnail.clicked.connect(self._on_thumbnail_clicked)
            thumbnail.double_clicked.connect(self._on_thumbnail_double_clicked)

            self.thumbnails[shot.full_name] = thumbnail

            # Add to grid
            row = i // self._get_column_count()
            col = i % self._get_column_count()
            self.grid_layout.addWidget(thumbnail, row, col)

    def _clear_grid(self):
        """Clear all thumbnails from grid."""
        for thumbnail in self.thumbnails.values():
            self.grid_layout.removeWidget(thumbnail)
            thumbnail.deleteLater()
        self.thumbnails.clear()

    def _get_column_count(self) -> int:
        """Calculate number of columns based on width."""
        available_width = self.scroll_area.viewport().width()
        if available_width <= 0:
            return Config.GRID_COLUMNS

        # Calculate based on thumbnail size and spacing
        item_width = self._thumbnail_size + Config.THUMBNAIL_SPACING
        columns = max(1, available_width // item_width)
        return columns

    def _reflow_grid(self):
        """Reflow grid layout based on new size."""
        if not self.thumbnails:
            return

        # Remove all widgets
        for widget in self.thumbnails.values():
            self.grid_layout.removeWidget(widget)

        # Re-add in new positions
        for i, shot in enumerate(self.shot_model.shots):
            if shot.full_name in self.thumbnails:
                thumbnail = self.thumbnails[shot.full_name]
                row = i // self._get_column_count()
                col = i % self._get_column_count()
                self.grid_layout.addWidget(thumbnail, row, col)

    def _on_size_changed(self, value: int):
        """Handle thumbnail size change."""
        self._thumbnail_size = value
        self.size_label.setText(f"{value}px")

        # Update all thumbnails
        for thumbnail in self.thumbnails.values():
            thumbnail.set_size(value)

        # Reflow grid
        self._reflow_grid()

    def _on_thumbnail_clicked(self, shot: Shot):
        """Handle thumbnail click."""
        # Update selection
        if self.selected_shot:
            old_thumb = self.thumbnails.get(self.selected_shot.full_name)
            if old_thumb:
                old_thumb.set_selected(False)

        self.selected_shot = shot
        thumbnail = self.thumbnails.get(shot.full_name)
        if thumbnail:
            thumbnail.set_selected(True)

        self.shot_selected.emit(shot)

    def _on_thumbnail_double_clicked(self, shot: Shot):
        """Handle thumbnail double click."""
        self.shot_double_clicked.emit(shot)

    def select_shot(self, shot: Shot):
        """Select a shot programmatically."""
        self._on_thumbnail_clicked(shot)

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
