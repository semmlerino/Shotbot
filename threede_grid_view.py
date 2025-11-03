"""Optimized grid view for 3DE scene thumbnails using Qt Model/View architecture.

This module provides a QListView-based implementation that replaces the manual
widget management approach, providing virtualization, efficient scrolling,
loading indicators, and proper Model/View integration for 3DE scenes.
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from typing import TYPE_CHECKING, override

# Third-party imports
from PySide6.QtCore import (
    QModelIndex,
    QPoint,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from base_grid_view import BaseGridView
from threede_grid_delegate import ThreeDEGridDelegate
from thumbnail_widget_base import FolderOpenerWorker


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import QKeyEvent

    # Local application imports
    from base_thumbnail_delegate import BaseThumbnailDelegate
    from threede_item_model import ThreeDEItemModel
    from threede_scene_model import ThreeDEScene


class ThreeDEGridView(BaseGridView):
    """Optimized grid view for displaying 3DE scene thumbnails.

    This view provides:
    - Virtualization (only renders visible items)
    - Efficient scrolling for large datasets
    - Lazy loading of thumbnails
    - Loading progress indicators
    - User filtering support
    - Proper Model/View integration
    - Dynamic grid layout based on window size
    """

    # Additional signals specific to ThreeDEGridView
    scene_selected = Signal(object)  # ThreeDEScene object
    scene_double_clicked = Signal(object)  # ThreeDEScene object
    # Override to add scene parameter
    app_launch_requested = Signal(str, object)  # app_name, scene
    recover_crashes_requested = Signal()  # User clicked recover crashes button

    def __init__(
        self,
        model: ThreeDEItemModel | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the 3DE grid view.

        Args:
            model: Optional 3DE item model
            parent: Optional parent widget
        """
        # Initialize widgets that will be created in template methods
        # These are set to None initially but will be assigned during super().__init__()
        self.loading_bar: QProgressBar
        self.loading_label: QLabel
        self.count_label: QLabel
        self.recover_button: QPushButton

        # Initialize base class (this calls _add_top_widgets and _customize_size_layout)
        super().__init__(parent)

        # ThreeDEGridView-specific attributes
        self._selected_scene = None
        self._is_loading = False
        self._updating_filter = False  # Recursion guard for filter updates
        self._threede_model: ThreeDEItemModel | None = model

        # Enable context menu
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        _ = self.list_view.customContextMenuRequested.connect(self._show_context_menu)

        if model:
            self.set_model(model)

        self.logger.info("ThreeDEGridView initialized with Model/View architecture")

    @override
    def _add_top_widgets(self, layout: QVBoxLayout) -> None:
        """Add loading indicators at the top.

        Args:
            layout: The main vertical layout
        """
        # Loading indicators
        loading_layout = QVBoxLayout()
        loading_layout.setSpacing(2)

        # Progress bar
        self.loading_bar = QProgressBar()
        self.loading_bar.setVisible(False)
        self.loading_bar.setMaximum(100)
        self.loading_bar.setTextVisible(True)
        loading_layout.addWidget(self.loading_bar)

        # Loading label
        self.loading_label = QLabel("")
        self.loading_label.setVisible(False)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)

        layout.addLayout(loading_layout)

    @override
    def _customize_size_layout(self, layout: QHBoxLayout) -> None:
        """Add scene count label and recovery button to size layout.

        Args:
            layout: The size control horizontal layout
        """
        # Recovery button
        self.recover_button = QPushButton("Recover Crashes...")
        self.recover_button.setToolTip(
            "Scan for and recover 3DE crash files in the current workspace"
        )
        _ = self.recover_button.clicked.connect(
            lambda: self.recover_crashes_requested.emit()
        )
        layout.addWidget(self.recover_button)

        # Scene count label
        layout.addStretch()
        self.count_label = QLabel("0 scenes")
        layout.addWidget(self.count_label)

    @override
    def _create_delegate(self) -> BaseThumbnailDelegate:
        """Create the 3DE grid delegate.

        Returns:
            ThreeDEGridDelegate instance
        """
        return ThreeDEGridDelegate(self)

    def set_model(self, model: ThreeDEItemModel) -> None:
        """Set the item model.

        Args:
            model: ThreeDEItemModel instance configured for 3DE scenes
        """
        self._model = model  # Set base class attribute for visibility tracking
        self._threede_model = model
        self.list_view.setModel(model)

        # Connect model signals
        _ = model.scenes_updated.connect(self._on_scenes_updated)
        _ = model.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        _ = model.loading_started.connect(self._on_loading_started)
        _ = model.loading_progress.connect(self._on_loading_progress)
        _ = model.loading_finished.connect(self._on_loading_finished)

        # Update grid size based on thumbnail size
        self._update_grid_size()

        # Update scene count
        self._update_scene_count()

    @override
    def populate_show_filter(self, shows: list[str] | object) -> None:
        """Populate the show filter combo box with available shows.

        Args:
            shows: List of show names or ThreeDESceneModel to extract shows from
        """
        if isinstance(shows, list):
            # Type narrowing: shows is list[str] after isinstance check
            shows_list: list[str] = shows
            super().populate_show_filter(shows_list)
        else:
            # Type narrowing: if not list, must be ThreeDESceneModel
            from threede_scene_model import ThreeDESceneModel

            assert isinstance(shows, ThreeDESceneModel)
            model_shows = shows.get_unique_shows()
            super().populate_show_filter(model_shows)
            self.logger.info(f"Populated show filter with {len(model_shows)} shows")

    @Slot()
    def _on_scenes_updated(self) -> None:
        """Handle scenes updated signal."""
        self._update_scene_count()
        self.list_view.viewport().update()

    @Slot(int)
    def _on_thumbnail_loaded(self, row: int) -> None:
        """Handle thumbnail loaded signal.

        Args:
            row: Row index of loaded thumbnail
        """
        # Update the specific item
        if self._threede_model:
            index = self._threede_model.index(row, 0)
            self.list_view.update(index)

    @Slot()
    def _on_loading_started(self) -> None:
        """Handle loading started signal."""
        self._is_loading = True
        self.loading_bar.setVisible(True)
        self.loading_label.setVisible(True)
        self.loading_label.setText("Scanning for 3DE scenes...")
        self.loading_bar.setValue(0)

    @Slot(int, int)
    def _on_loading_progress(self, current: int, total: int) -> None:
        """Handle loading progress signal.

        Args:
            current: Current item being loaded
            total: Total items to load
        """
        if total > 0:
            progress = int((current / total) * 100)
            self.loading_bar.setValue(progress)
            self.loading_label.setText(f"Found {current} scenes...")

    @Slot()
    def _on_loading_finished(self) -> None:
        """Handle loading finished signal."""
        self._is_loading = False
        self.loading_bar.setVisible(False)
        self.loading_label.setVisible(False)
        self._update_scene_count()

    def _update_scene_count(self) -> None:
        """Update the scene count label."""
        if self._threede_model:
            count = self._threede_model.rowCount()
            self.count_label.setText(f"{count} scene{'s' if count != 1 else ''}")

    @Slot(QModelIndex)
    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Handle item click.

        Args:
            index: Clicked model index
        """
        if not self._threede_model:
            return

        scene = self._threede_model.get_scene(index)
        if scene:
            self._selected_scene = scene
            self._threede_model.set_selected(index)
            self.scene_selected.emit(scene)

    @Slot(QModelIndex)
    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """Handle item double-click.

        Args:
            index: Double-clicked model index
        """
        if not self._threede_model:
            return

        scene = self._threede_model.get_scene(index)
        if scene:
            self.scene_double_clicked.emit(scene)
            # Launch 3DE by default
            self.app_launch_requested.emit("3de", scene)

    @override
    def _handle_visible_range_update(self, start: int, end: int) -> None:
        """Handle the visible range update with buffering.

        Args:
            start: Start row index
            end: End row index (exclusive)
        """
        if self._threede_model:
            # Add some buffer for smooth scrolling
            buffered_start = max(0, start - 5)
            buffered_end = min(self._threede_model.rowCount(), end + 5)
            self._threede_model.set_visible_range(buffered_start, buffered_end)

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show context menu at position.

        Args:
            pos: Context menu position
        """
        index = self.list_view.indexAt(pos)
        if not index.isValid() or not self._threede_model:
            return

        scene = self._threede_model.get_scene(index)
        if not scene:
            return

        menu = QMenu(self)

        # Add "Open in 3DE" action
        open_3de_action = menu.addAction("Open in 3DE")
        _ = open_3de_action.triggered.connect(lambda: self._open_scene_in_3de(scene))

        # Add "Open folder" action
        open_folder_action = menu.addAction("Open Folder")
        _ = open_folder_action.triggered.connect(lambda: self._open_scene_folder(scene))

        # Add separator
        _ = menu.addSeparator()

        # Add "Copy path" action
        copy_path_action = menu.addAction("Copy Path")
        _ = copy_path_action.triggered.connect(lambda: self._copy_scene_path(scene))

        _ = menu.exec(self.list_view.mapToGlobal(pos))

    def _open_scene_in_3de(self, scene: ThreeDEScene) -> None:
        """Open scene in 3DE.

        Args:
            scene: Scene to open
        """
        self.app_launch_requested.emit("3de", scene)

    def _open_scene_folder(self, scene: ThreeDEScene) -> None:
        """Open scene folder in file manager.

        Args:
            scene: Scene whose folder to open
        """
        scene_path = Path(scene.scene_path)
        if scene_path.exists():
            folder_path = str(scene_path.parent)
            worker = FolderOpenerWorker(folder_path)
            QThreadPool.globalInstance().start(worker)

    def _copy_scene_path(self, scene: ThreeDEScene) -> None:
        """Copy scene path to clipboard.

        Args:
            scene: Scene whose path to copy
        """
        # Third-party imports
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        clipboard.setText(str(scene.scene_path))
        self.logger.info(f"Copied path to clipboard: {scene.scene_path}")

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events.

        Args:
            event: Key press event
        """
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Launch selected scene
            current = self.list_view.currentIndex()
            if current.isValid() and self._threede_model:
                scene = self._threede_model.get_scene(current)
                if scene:
                    self.scene_double_clicked.emit(scene)
                    self.app_launch_requested.emit("3de", scene)
        else:
            super().keyPressEvent(event)

    def select_scene(self, scene: ThreeDEScene) -> None:
        """Select a scene programmatically.

        Args:
            scene: Scene to select
        """
        if not self._threede_model:
            return

        # Find scene in model
        for row in range(self._threede_model.rowCount()):
            index = self._threede_model.index(row, 0)
            model_scene = self._threede_model.get_scene(index)
            if model_scene and model_scene.full_name == scene.full_name:
                self.list_view.setCurrentIndex(index)
                self._threede_model.set_selected(index)
                self._selected_scene = scene
                self.scene_selected.emit(scene)
                break

    @property
    def selected_scene(self) -> ThreeDEScene | None:
        """Get the currently selected scene."""
        return self._selected_scene

    @property
    def is_loading(self) -> bool:
        """Check if loading is in progress."""
        return self._is_loading
