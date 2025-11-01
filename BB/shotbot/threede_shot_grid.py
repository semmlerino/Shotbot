"""3DE scene grid widget for displaying scene thumbnails in a grid layout."""

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config import Config
from threede_scene_model import ThreeDEScene, ThreeDESceneModel
from threede_thumbnail_widget import ThreeDEThumbnailWidget


class ThreeDEShotGrid(QWidget):
    """Grid display of 3DE scene thumbnails."""

    # Signals
    scene_selected = Signal(object)  # ThreeDEScene
    scene_double_clicked = Signal(object)  # ThreeDEScene
    app_launch_requested = Signal(str)  # app_name

    def __init__(self, scene_model: ThreeDESceneModel):
        super().__init__()
        self.scene_model = scene_model
        self.thumbnails: Dict[str, ThreeDEThumbnailWidget] = {}
        self.selected_scene: Optional[ThreeDEScene] = None
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE
        self._is_loading = False
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

        # Loading indicator
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)  # Indeterminate
        self.loading_bar.setVisible(False)
        self.loading_bar.setMaximumHeight(3)
        layout.addWidget(self.loading_bar)

        # Loading label
        self.loading_label = QLabel("Scanning for 3DE scenes...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setVisible(False)
        self.loading_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.loading_label)

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

    def set_loading(self, loading: bool, message: str = "Scanning for 3DE scenes..."):
        """Set loading state."""
        self._is_loading = loading
        self.loading_bar.setVisible(loading)
        self.loading_label.setVisible(loading)
        self.loading_label.setText(message)

    def set_loading_progress(self, current: int, total: int):
        """Set loading progress."""
        if total > 0:
            self.loading_bar.setRange(0, total)
            self.loading_bar.setValue(current)
            self.loading_label.setText(f"Scanning shots ({current}/{total})...")

    def refresh_scenes(self):
        """Refresh the scene display."""
        # Clear existing thumbnails
        self._clear_grid()

        # Show empty state if no scenes
        if not self.scene_model.scenes:
            self._show_empty_state()
            return

        # Create thumbnails for all scenes
        for i, scene in enumerate(self.scene_model.scenes):
            thumbnail = ThreeDEThumbnailWidget(scene, self._thumbnail_size)
            thumbnail.clicked.connect(self._on_thumbnail_clicked)
            thumbnail.double_clicked.connect(self._on_thumbnail_double_clicked)

            # Use display name as key for uniqueness
            self.thumbnails[scene.display_name] = thumbnail

            # Add to grid
            row = i // self._get_column_count()
            col = i % self._get_column_count()
            self.grid_layout.addWidget(thumbnail, row, col)

    def _show_empty_state(self):
        """Show empty state message."""
        empty_label = QLabel("No 3DE scenes found from other users")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
        self.grid_layout.addWidget(empty_label, 0, 0)

    def _clear_grid(self):
        """Clear all thumbnails from grid."""
        # Remove all widgets from grid
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Clear thumbnail references
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
        for i, scene in enumerate(self.scene_model.scenes):
            if scene.display_name in self.thumbnails:
                thumbnail = self.thumbnails[scene.display_name]
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

    def _on_thumbnail_clicked(self, scene: ThreeDEScene):
        """Handle thumbnail click."""
        # Update selection
        if self.selected_scene:
            old_thumb = self.thumbnails.get(self.selected_scene.display_name)
            if old_thumb:
                old_thumb.set_selected(False)

        self.selected_scene = scene
        thumbnail = self.thumbnails.get(scene.display_name)
        if thumbnail:
            thumbnail.set_selected(True)

        self.scene_selected.emit(scene)

    def _on_thumbnail_double_clicked(self, scene: ThreeDEScene):
        """Handle thumbnail double click."""
        self.scene_double_clicked.emit(scene)

    def select_scene(self, scene: ThreeDEScene):
        """Select a scene programmatically."""
        self._on_thumbnail_clicked(scene)

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
        if not self.scene_model.scenes:
            super().keyPressEvent(event)
            return

        # Get current selection index
        current_index = -1
        if self.selected_scene:
            for i, scene in enumerate(self.scene_model.scenes):
                if scene.display_name == self.selected_scene.display_name:
                    current_index = i
                    break

        # Calculate grid dimensions
        columns = self._get_column_count()
        total_scenes = len(self.scene_model.scenes)

        new_index = current_index

        # Handle arrow keys
        if event.key() == Qt.Key.Key_Right:
            new_index = (
                min(current_index + 1, total_scenes - 1) if current_index >= 0 else 0
            )
        elif event.key() == Qt.Key.Key_Left:
            new_index = max(current_index - 1, 0) if current_index >= 0 else 0
        elif event.key() == Qt.Key.Key_Down:
            if current_index >= 0:
                new_index = min(current_index + columns, total_scenes - 1)
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
            new_index = total_scenes - 1
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Double-click on current selection
            if self.selected_scene:
                self.scene_double_clicked.emit(self.selected_scene)
            event.accept()
            return
        # Application launch shortcuts
        elif event.key() == Qt.Key.Key_3:
            # Launch 3de
            if self.selected_scene:
                self.app_launch_requested.emit("3de")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_N:
            # Launch Nuke
            if self.selected_scene:
                self.app_launch_requested.emit("nuke")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_M:
            # Launch Maya
            if self.selected_scene:
                self.app_launch_requested.emit("maya")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_R:
            # Launch RV
            if self.selected_scene:
                self.app_launch_requested.emit("rv")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_P:
            # Launch Publish
            if self.selected_scene:
                self.app_launch_requested.emit("publish")
            event.accept()
            return
        else:
            super().keyPressEvent(event)
            return

        # Select new scene if index changed
        if new_index != current_index and 0 <= new_index < total_scenes:
            new_scene = self.scene_model.scenes[new_index]
            self.select_scene(new_scene)

            # Ensure the selected thumbnail is visible
            if new_scene.display_name in self.thumbnails:
                thumbnail = self.thumbnails[new_scene.display_name]
                self.scroll_area.ensureWidgetVisible(thumbnail)

        event.accept()
