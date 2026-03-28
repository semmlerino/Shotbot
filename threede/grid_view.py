"""Optimized grid view for 3DE scene thumbnails using Qt Model/View architecture.

This module provides a QListView-based implementation that replaces the manual
widget management approach, providing virtualization, efficient scrolling,
loading indicators, and proper Model/View integration for 3DE scenes.

VFX Glossary:
    3DE / 3DEqualizer — Camera tracking/matchmove software by Science.D.Visions.
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import (
    QModelIndex,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import override

from threede.grid_delegate import ThreeDEGridDelegate

# Local application imports
from ui.base_grid_view import BaseGridView
from workers.runnable_tracker import FolderOpenerWorker


if TYPE_CHECKING:
    # Third-party imports

    # Local application imports
    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from threede.item_model import ThreeDEItemModel
    from type_definitions import ThreeDEScene
    from ui.base_thumbnail_delegate import BaseThumbnailDelegate


@final
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
    artist_filter_requested = Signal(str)  # artist name or empty string for all

    def __init__(
        self,
        model: ThreeDEItemModel | None = None,
        proxy: QSortFilterProxyModel | None = None,
        pin_manager: ShotPinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the 3DE grid view.

        Args:
            model: Optional 3DE item model
            proxy: Optional proxy model for filtering/sorting
            pin_manager: Optional pin manager for pinning shots
            notes_manager: Optional notes manager for shot notes
            parent: Optional parent widget

        """
        # Initialize widgets that will be created in template methods
        # These are set to None initially but will be assigned during super().__init__()
        self.loading_bar: QProgressBar
        self.loading_label: QLabel
        self.count_label: QLabel
        self.recover_button: QPushButton
        self.artist_combo: QComboBox
        self._pin_manager: ShotPinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager

        # Initialize base class (this calls _add_top_widgets and _add_toolbar_widgets)
        super().__init__(parent)

        # Set up Return/Enter shortcut for launching the selected scene
        self._setup_return_shortcut()

        # Update text filter placeholder for 3DE context
        self.text_filter_input.setPlaceholderText("Filter shot name...")
        self.text_filter_input.setToolTip("Filter by shot or sequence")

        # ThreeDEGridView-specific attributes
        self._selected_scene = None
        self._is_loading = False
        self._updating_filter = False  # Recursion guard for filter updates
        self._threede_model: ThreeDEItemModel | None = model

        # Enable context menu
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        _ = self.list_view.customContextMenuRequested.connect(self._show_context_menu)

        if model:
            self.set_model(model, proxy)

        self.logger.debug("ThreeDEGridView initialized")

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
    def _add_toolbar_widgets(self, layout: QHBoxLayout) -> None:
        """Add scene count label, sort buttons, and recovery button to toolbar.

        Args:
            layout: The toolbar horizontal layout

        """
        self.artist_combo = QComboBox()
        self.artist_combo.addItem("All Artists")
        self.artist_combo.setFixedWidth(130)
        self.artist_combo.setToolTip("Filter by artist")
        _ = self.artist_combo.currentTextChanged.connect(
            self._on_artist_filter_changed  # pyright: ignore[reportAny]
        )
        layout.addWidget(self.artist_combo)

        from ui.sort_button_bar import SortButtonBar

        self._sort_bar = SortButtonBar(
            on_order_changed=self.sort_order_changed.emit,
            parent=self,
        )
        self._sort_bar.add_to_layout(layout)

        # Add some spacing
        layout.addSpacing(10)

        # Recovery button
        self.recover_button = QPushButton("Recover Crashes...")
        self.recover_button.setToolTip(
            "Scan for and recover 3DE crash files in the current workspace"
        )
        _ = self.recover_button.clicked.connect(
            lambda: self.recover_crashes_requested.emit()
        )
        layout.addWidget(self.recover_button)

        # Push count label to far right
        layout.addStretch()

        # Scene count label
        self.count_label = QLabel("0 scenes")
        layout.addWidget(self.count_label)

    @override
    def _create_delegate(self) -> BaseThumbnailDelegate:
        """Create the 3DE grid delegate.

        Returns:
            ThreeDEGridDelegate instance

        """
        return ThreeDEGridDelegate(self)

    def set_model(
        self, model: ThreeDEItemModel, proxy: QSortFilterProxyModel | None = None
    ) -> None:
        """Set the item model.

        Args:
            model: ThreeDEItemModel instance configured for 3DE scenes
            proxy: Optional proxy model for filtering/sorting

        """
        self._model = model  # Set base class attribute for visibility tracking
        self._threede_model = model
        self.list_view.setModel(proxy if proxy is not None else model)
        self._connect_model_visibility(model)

        # Connect model signals
        _ = model.scenes_updated.connect(self._on_scenes_updated)  # pyright: ignore[reportAny]
        _ = model.thumbnail_loaded.connect(self._on_thumbnail_loaded)  # pyright: ignore[reportAny]
        _ = model.loading_started.connect(self._on_loading_started)  # pyright: ignore[reportAny]
        _ = model.loading_progress.connect(self._on_loading_progress)  # pyright: ignore[reportAny]
        _ = model.loading_finished.connect(self._on_loading_finished)  # pyright: ignore[reportAny]

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
            shows_list = cast("list[str]", shows)
        else:
            from threede.scene_model import ThreeDESceneModel

            assert isinstance(shows, ThreeDESceneModel)
            shows_list = shows.get_unique_shows()

        self._populate_filter_combo(self.show_combo, shows_list, "All Shows")
        self._log_filter_populated("show", len(shows_list))

    def populate_artist_filter(self, artists: list[str] | object) -> None:
        """Populate the artist filter combo box with available artists.

        Args:
            artists: List of artist names or ThreeDESceneModel to extract artists from

        """
        if isinstance(artists, list):
            artist_list = cast("list[str]", artists)
        else:
            from threede.scene_model import ThreeDESceneModel

            assert isinstance(artists, ThreeDESceneModel)
            artist_list = artists.get_unique_artists()

        self._populate_filter_combo(self.artist_combo, artist_list, "All Artists")
        self._log_filter_populated("artist", len(artist_list))

    def _populate_filter_combo(
        self,
        combo: QComboBox,
        values: list[str],
        all_label: str,
    ) -> None:
        """Populate a filter combo and preserve its selection when possible."""
        current_text = combo.currentText()
        previous_state = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(all_label)
            for value in sorted(values, key=str.casefold):
                combo.addItem(value)

            next_text = current_text if combo.findText(current_text) >= 0 else all_label
            combo.setCurrentText(next_text)
        finally:
            _ = combo.blockSignals(previous_state)

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_artist_filter_changed(self, artist_text: str) -> None:
        """Handle artist filter change."""
        artist_filter = "" if artist_text == "All Artists" else artist_text
        self.artist_filter_requested.emit(artist_filter)
        self.logger.info(f"Artist filter requested: {artist_text}")

    @Slot()  # pyright: ignore[reportAny]
    def _on_scenes_updated(self) -> None:
        """Handle scenes updated signal."""
        self._update_scene_count()
        self.list_view.viewport().update()

    @Slot(int)  # pyright: ignore[reportAny]
    def _on_thumbnail_loaded(self, row: int) -> None:
        """Handle thumbnail loaded signal.

        Args:
            row: Row index of loaded thumbnail

        """
        # Update the specific item
        if self._threede_model:
            source_index = self._threede_model.index(row, 0)
            proxy = self.list_view.model()
            if isinstance(proxy, QSortFilterProxyModel):
                view_index = proxy.mapFromSource(source_index)
                if view_index.isValid():
                    self.list_view.update(view_index)
            else:
                self.list_view.update(source_index)

    @Slot()  # pyright: ignore[reportAny]
    def _on_loading_started(self) -> None:
        """Handle loading started signal."""
        self._is_loading = True
        self.loading_bar.setVisible(True)
        self.loading_label.setVisible(True)
        self.loading_label.setText("Scanning for 3DE scenes...")
        self.loading_bar.setValue(0)

    @Slot(int, int)  # pyright: ignore[reportAny]
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

    @Slot()  # pyright: ignore[reportAny]
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

    def _resolve_source_index(self, index: QModelIndex) -> QModelIndex:
        """Map a view index through the proxy model to the source model index.

        Args:
            index: Index from the view (may be a proxy index)

        Returns:
            Source model index, unchanged if no proxy is active

        """
        proxy = self.list_view.model()
        if isinstance(proxy, QSortFilterProxyModel):
            return proxy.mapToSource(index)
        return index

    def _log_filter_populated(self, noun: str, count: int) -> None:
        """Log a 'populated filter' message with correct singular/plural noun.

        Args:
            noun: Singular form of the item noun (e.g. "show", "artist")
            count: Number of items populated

        """
        word = noun if count == 1 else f"{noun}s"
        self.logger.info(f"Populated {noun} filter with {count} {word}")

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Handle item click.

        Args:
            index: Clicked model index

        """
        if not self._threede_model:
            return

        source_index = self._resolve_source_index(index)
        scene = self._threede_model.get_scene(source_index)
        if scene:
            self._selected_scene = scene
            self.scene_selected.emit(scene)

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """Handle item double-click.

        Args:
            index: Double-clicked model index

        """
        if not self._threede_model:
            return

        source_index = self._resolve_source_index(index)
        scene = self._threede_model.get_scene(source_index)
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
            self._threede_model.set_visible_range(buffered_start, buffered_end)  # pyright: ignore[reportAny]

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show context menu at position.

        Args:
            pos: Context menu position

        """
        index = self.list_view.indexAt(pos)
        if not index.isValid() or not self._threede_model:
            return

        source_index = self._resolve_source_index(index)
        scene = self._threede_model.get_scene(source_index)
        if not scene:
            return

        # Create context menu with enlarged styling (50% larger)
        menu = QMenu(self)
        menu.setStyleSheet(self.CONTEXT_MENU_STYLE)

        # Pin/Unpin shot action (at the top for quick access)
        # Use workspace_path as the key for pinning
        is_pinned = (
            self._pin_manager.is_pinned_by_path(scene.workspace_path)
            if self._pin_manager
            else False
        )
        if is_pinned:
            unpin_action = menu.addAction("Unpin Shot")
            unpin_action.setIcon(self._create_icon("pin", "#FF6B6B"))
            _ = unpin_action.triggered.connect(
                lambda checked=False, s=scene: self._unpin_scene(s)  # noqa: ARG005
            )
        else:
            pin_action = menu.addAction("Pin Shot")
            pin_action.setIcon(self._create_icon("pin", "#FF6B6B"))
            _ = pin_action.triggered.connect(
                lambda checked=False, s=scene: self._pin_scene(s)  # noqa: ARG005
            )

        _ = menu.addSeparator()

        # Open in 3DE (scene-specific action)
        open_3de_action = menu.addAction("Open in 3DE")
        open_3de_action.setIcon(self._create_icon("target", "#00CED1"))
        _ = open_3de_action.triggered.connect(lambda: self._open_scene_in_3de(scene))

        # Open Scene Folder (scene file's directory — scene-specific, not shared)
        open_scene_folder_action = menu.addAction("Open Scene Folder")
        open_scene_folder_action.setIcon(self._create_icon("folder", "#95A5A6"))
        _ = open_scene_folder_action.triggered.connect(
            lambda: self._open_scene_folder(scene)
        )

        _ = menu.addSeparator()

        launch_apps = [
            ("3DEqualizer", "3", "3de", "target", "#00CED1"),
            ("Nuke", "N", "nuke", "palette", "#FF8C00"),
            ("Maya", "M", "maya", "cube", "#9B59B6"),
            ("RV", "R", "rv", "play", "#2ECC71"),
        ]
        self._build_launch_submenu(
            menu,
            launch_apps,
            lambda app_id, s=scene: self.app_launch_requested.emit(app_id, s),
        )

        _ = menu.addSeparator()

        # Copy Scene Path (scene file path — scene-specific, not shared)
        copy_scene_action = menu.addAction("Copy Scene Path")
        copy_scene_action.setIcon(self._create_icon("clipboard", "#95A5A6"))
        _ = copy_scene_action.triggered.connect(lambda: self._copy_scene_path(scene))

        has_note = (
            self._notes_manager.has_note_by_path(scene.workspace_path)
            if self._notes_manager
            else False
        )
        display_name = f"{scene.sequence}_{scene.shot}"
        self._build_shot_standard_actions(
            menu,
            scene.workspace_path,
            display_name,
            has_note,
            item_for_rv=scene,
        )

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
        clipboard = QApplication.clipboard()
        clipboard.setText(str(scene.scene_path))
        self.logger.info(f"Copied path to clipboard: {scene.scene_path}")

    def _pin_scene(self, scene: ThreeDEScene) -> None:
        """Pin a scene (by workspace path).

        Args:
            scene: Scene to pin

        """
        if self._pin_manager:
            self._pin_manager.pin_by_path(scene.workspace_path)
            self.logger.debug(f"Pinned scene: {scene.workspace_path}")

    def _unpin_scene(self, scene: ThreeDEScene) -> None:
        """Unpin a scene (by workspace path).

        Args:
            scene: Scene to unpin

        """
        if self._pin_manager:
            self._pin_manager.unpin_by_path(scene.workspace_path)
            self.logger.debug(f"Unpinned scene: {scene.workspace_path}")

    def _setup_return_shortcut(self) -> None:
        """Set up Return/Enter QAction for scene launch."""
        from PySide6.QtGui import QAction, QKeySequence

        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            action = QAction(self.list_view)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            _ = action.triggered.connect(self._on_return_pressed)
            self.list_view.addAction(action)

    def _on_return_pressed(self) -> None:
        """Handle Return/Enter key to launch selected scene."""
        current = self.list_view.currentIndex()
        if current.isValid() and self._threede_model:
            source_index = self._resolve_source_index(current)
            scene = self._threede_model.get_scene(source_index)
            if scene:
                self.scene_double_clicked.emit(scene)
                self.app_launch_requested.emit("3de", scene)

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
                # Map source index to proxy for view selection
                proxy = self.list_view.model()
                view_index = index
                if isinstance(proxy, QSortFilterProxyModel):
                    view_index = proxy.mapFromSource(index)
                self.list_view.setCurrentIndex(view_index)
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
