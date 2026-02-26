"""Optimized grid view for 3DE scene thumbnails using Qt Model/View architecture.

This module provides a QListView-based implementation that replaces the manual
widget management approach, providing virtualization, efficient scrolling,
loading indicators, and proper Model/View integration for 3DE scenes.
"""

from __future__ import annotations

# Standard library imports
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import (
    QModelIndex,
    QPoint,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from base_grid_view import BaseGridView
from runnable_tracker import FolderOpenerWorker
from threede_grid_delegate import ThreeDEGridDelegate
from typing_compat import override


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import QKeyEvent

    # Local application imports
    from base_thumbnail_delegate import BaseThumbnailDelegate
    from notes_manager import NotesManager
    from pin_manager import PinManager
    from threede_item_model import ThreeDEItemModel
    from threede_scene_model import ThreeDEScene


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
    sort_order_changed = Signal(str)  # "name" or "date"

    def __init__(
        self,
        model: ThreeDEItemModel | None = None,
        pin_manager: PinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the 3DE grid view.

        Args:
            model: Optional 3DE item model
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
        self.sort_name_btn: QPushButton
        self.sort_date_btn: QPushButton
        self._sort_button_group: QButtonGroup
        self._pin_manager: PinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager

        # Initialize base class (this calls _add_top_widgets and _add_toolbar_widgets)
        super().__init__(parent)

        # Update text filter placeholder for 3DE context
        self.text_filter_input.setPlaceholderText("Filter scenes...")

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
        # Sort toggle buttons
        sort_label = QLabel("Sort:")
        layout.addWidget(sort_label)

        self.sort_name_btn = QPushButton("Name")
        self.sort_name_btn.setCheckable(True)
        self.sort_name_btn.setToolTip("Sort by shot name alphabetically")
        self.sort_name_btn.setFixedWidth(50)
        layout.addWidget(self.sort_name_btn)

        self.sort_date_btn = QPushButton("Date")
        self.sort_date_btn.setCheckable(True)
        self.sort_date_btn.setChecked(True)  # Default: date (newest first)
        self.sort_date_btn.setToolTip("Sort by modification date (newest first)")
        self.sort_date_btn.setFixedWidth(50)
        layout.addWidget(self.sort_date_btn)

        # Button group for exclusive selection
        self._sort_button_group = QButtonGroup(self)
        self._sort_button_group.addButton(self.sort_name_btn, 0)
        self._sort_button_group.addButton(self.sort_date_btn, 1)
        _ = self._sort_button_group.idClicked.connect(self._on_sort_button_clicked)

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

    def set_model(self, model: ThreeDEItemModel) -> None:
        """Set the item model.

        Args:
            model: ThreeDEItemModel instance configured for 3DE scenes

        """
        self._model = model  # Set base class attribute for visibility tracking
        self._threede_model = model
        self.list_view.setModel(model)

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
            # Type narrowing: shows is list[str] after isinstance check
            shows_list = cast("list[str]", shows)
            super().populate_show_filter(shows_list)
        else:
            # Type narrowing: if not list, must be ThreeDESceneModel
            from threede_scene_model import ThreeDESceneModel

            assert isinstance(shows, ThreeDESceneModel)
            model_shows = shows.get_unique_shows()
            super().populate_show_filter(model_shows)
            show_count = len(model_shows)
            show_word = "show" if show_count == 1 else "shows"
            self.logger.info(f"Populated show filter with {show_count} {show_word}")

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
            index = self._threede_model.index(row, 0)
            self.list_view.update(index)

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

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
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

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
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
            self._threede_model.set_visible_range(buffered_start, buffered_end)  # pyright: ignore[reportAny]

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

        # Create context menu with enlarged styling (50% larger)
        menu = QMenu(self)
        menu_style = """
            QMenu {
                font-size: 18px;
                padding: 8px;
            }
            QMenu::item {
                padding: 12px 24px 12px 12px;
                min-width: 200px;
            }
            QMenu::item:selected {
                background-color: #3daee9;
            }
            QMenu::separator {
                height: 2px;
                margin: 6px 12px;
            }
        """
        menu.setStyleSheet(menu_style)

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

        # Open Scene Folder (scene file's directory)
        open_scene_folder_action = menu.addAction("Open Scene Folder")
        open_scene_folder_action.setIcon(self._create_icon("folder", "#95A5A6"))
        _ = open_scene_folder_action.triggered.connect(
            lambda: self._open_scene_folder(scene)
        )

        # Open Shot Folder (workspace directory)
        open_shot_folder_action = menu.addAction("Open Shot Folder")
        open_shot_folder_action.setIcon(self._create_icon("folder", "#FFB347"))
        _ = open_shot_folder_action.triggered.connect(
            lambda: self._open_shot_folder(scene)
        )

        # Open Main Plate in RV
        open_plate_action = menu.addAction("Open Main Plate in RV")
        open_plate_action.setIcon(self._create_icon("play", "#FF4757"))
        _ = open_plate_action.triggered.connect(
            lambda: self._open_main_plate_in_rv(scene)
        )

        _ = menu.addSeparator()

        # Launch Application submenu (with keyboard shortcuts visible)
        launch_menu = menu.addMenu("Launch Application")
        launch_menu.setStyleSheet(menu_style)
        launch_menu.setIcon(self._create_icon("rocket", "#95D5B2"))
        launch_apps = [
            ("3DEqualizer", "3", "3de", "target", "#00CED1"),
            ("Nuke", "N", "nuke", "palette", "#FF8C00"),
            ("Maya", "M", "maya", "cube", "#9B59B6"),
            ("RV", "R", "rv", "play", "#2ECC71"),
        ]
        for label, shortcut, app_id, icon_type, color in launch_apps:
            action = launch_menu.addAction(f"{label}  ({shortcut})")
            action.setIcon(self._create_icon(icon_type, color))
            # Emit signal with app_id and scene for context
            _ = action.triggered.connect(
                lambda checked=False, a=app_id, s=scene: self.app_launch_requested.emit(a, s)  # noqa: ARG005
            )

        _ = menu.addSeparator()

        # Copy Scene Path (scene file path)
        copy_scene_action = menu.addAction("Copy Scene Path")
        copy_scene_action.setIcon(self._create_icon("clipboard", "#95A5A6"))
        _ = copy_scene_action.triggered.connect(lambda: self._copy_scene_path(scene))

        # Copy Shot Path (workspace path)
        copy_shot_action = menu.addAction("Copy Shot Path")
        copy_shot_action.setIcon(self._create_icon("clipboard", "#95A5A6"))
        _ = copy_shot_action.triggered.connect(
            lambda: self._copy_path_to_clipboard(scene.workspace_path)
        )

        _ = menu.addSeparator()

        # Edit/Add Note action
        has_note = (
            self._notes_manager.has_note_by_path(scene.workspace_path)
            if self._notes_manager
            else False
        )
        note_label = "Edit Note" if has_note else "Add Note"
        edit_note_action = menu.addAction(note_label)
        edit_note_action.setIcon(self._create_icon("note", "#F1C40F"))
        _ = edit_note_action.triggered.connect(
            lambda checked=False, s=scene: self._edit_scene_note(s)  # noqa: ARG005
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

    def _copy_path_to_clipboard(self, path: str) -> None:
        """Copy a path to the system clipboard.

        Args:
            path: The path string to copy

        """
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(path)
            self.logger.debug(f"Copied path to clipboard: {path}")

    def _open_shot_folder(self, scene: ThreeDEScene) -> None:
        """Open the shot's workspace folder in system file manager.

        Args:
            scene: Scene object containing workspace path

        """
        workspace_path = scene.workspace_path
        if not workspace_path:
            self.logger.error(f"No workspace path for scene: {scene.scene_path}")
            return

        if not Path(workspace_path).exists():
            self.logger.error(f"Workspace path does not exist: {workspace_path}")
            return

        worker = FolderOpenerWorker(workspace_path)
        QThreadPool.globalInstance().start(worker)
        self.logger.info(f"Opening folder: {workspace_path}")

    def _open_main_plate_in_rv(self, scene: ThreeDEScene) -> None:
        """Open the main plate in RV.

        Args:
            scene: Scene object containing workspace path

        """
        from notification_manager import error as notify_error
        from publish_plate_finder import find_main_plate

        workspace_path = scene.workspace_path
        plate_path = find_main_plate(workspace_path)

        if plate_path is None:
            self.logger.warning(f"No plate found for shot at {workspace_path}")
            notify_error("No Plate Found", f"No plate found for shot at {workspace_path}")
            return

        self.logger.info(f"Opening plate in RV: {plate_path}")
        try:
            # Use bash -ilc to inherit shell environment where Rez adds RV to PATH
            # RV settings: 12fps, auto-play, ping-pong mode (setPlayMode(2))
            safe_path = shlex.quote(plate_path)
            rv_cmd = f"rv {safe_path} -fps 12 -play -eval 'setPlayMode(2)'"
            _ = subprocess.Popen(["bash", "-ilc", rv_cmd])
        except FileNotFoundError:
            self.logger.error("RV not found. Please ensure RV is installed and in PATH.")
            notify_error("RV Not Found", "Could not launch RV. Check that RV is installed.")
        except Exception as e:
            self.logger.error(f"Failed to open RV: {e}")
            notify_error("RV Launch Failed", f"Failed to open RV: {e}")

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

    def _edit_scene_note(self, scene: ThreeDEScene) -> None:
        """Open dialog to edit note for scene.

        Args:
            scene: Scene to edit note for

        """
        if not self._notes_manager:
            return

        # Use workspace_path as the key for notes
        current_note = self._notes_manager.get_note_by_path(scene.workspace_path)
        shot_name = f"{scene.sequence}_{scene.shot}"
        new_note, ok = QInputDialog.getMultiLineText(
            self,
            f"Note for {shot_name}",
            "Note:",
            current_note,
        )
        if ok:
            self._notes_manager.set_note_by_path(scene.workspace_path, new_note)
            self.logger.debug(f"Note updated for scene: {shot_name}")

    def _create_icon(self, icon_type: str, color: str, size: int = 33) -> QIcon:
        """Create a coloured shaped icon for menu items.

        Args:
            icon_type: Icon type - "pin", "folder", "rocket", "target",
                      "palette", "cube", "play", "clipboard", "note"
            color: Hex colour string (e.g., "#FF6B6B")
            size: Icon size in pixels

        Returns:
            QIcon with the specified shape and colour

        """
        from PySide6.QtGui import QPen

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)

        # Scale factor for drawing
        s = size

        if icon_type == "pin":
            # Pushpin: round head + long needle
            painter.drawEllipse(int(s * 0.25), int(s * 0.05), int(s * 0.5), int(s * 0.35))
            painter.drawRect(int(s * 0.42), int(s * 0.35), int(s * 0.16), int(s * 0.4))
            points = [
                QPoint(int(s * 0.42), int(s * 0.75)),
                QPoint(int(s * 0.58), int(s * 0.75)),
                QPoint(int(s * 0.5), int(s * 0.98)),
            ]
            painter.drawPolygon(points)

        elif icon_type == "folder":
            # Open folder with document
            painter.drawRoundedRect(
                int(s * 0.05), int(s * 0.2), int(s * 0.9), int(s * 0.65), 3, 3
            )
            painter.drawRoundedRect(
                int(s * 0.05), int(s * 0.12), int(s * 0.35), int(s * 0.15), 2, 2
            )
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(int(s * 0.25), int(s * 0.08), int(s * 0.5), int(s * 0.45))
            painter.setPen(QPen(QColor(color), 1))
            for i in range(3):
                y = int(s * (0.18 + i * 0.12))
                painter.drawLine(int(s * 0.32), y, int(s * 0.68), y)

        elif icon_type == "rocket":
            # Rocket with nose cone, body, fins, and flame
            painter.setBrush(QColor(color))
            nose = [
                QPoint(int(s * 0.5), 0),
                QPoint(int(s * 0.3), int(s * 0.25)),
                QPoint(int(s * 0.7), int(s * 0.25)),
            ]
            painter.drawPolygon(nose)
            painter.drawRect(int(s * 0.3), int(s * 0.25), int(s * 0.4), int(s * 0.45))
            fin_left = [
                QPoint(int(s * 0.3), int(s * 0.5)),
                QPoint(int(s * 0.05), int(s * 0.75)),
                QPoint(int(s * 0.3), int(s * 0.7)),
            ]
            painter.drawPolygon(fin_left)
            fin_right = [
                QPoint(int(s * 0.7), int(s * 0.5)),
                QPoint(int(s * 0.95), int(s * 0.75)),
                QPoint(int(s * 0.7), int(s * 0.7)),
            ]
            painter.drawPolygon(fin_right)
            painter.setBrush(QColor("#FF6600"))
            flame = [
                QPoint(int(s * 0.35), int(s * 0.7)),
                QPoint(int(s * 0.65), int(s * 0.7)),
                QPoint(int(s * 0.5), int(s * 0.98)),
            ]
            painter.drawPolygon(flame)
            painter.setBrush(QColor("#FFCC00"))
            inner_flame = [
                QPoint(int(s * 0.42), int(s * 0.7)),
                QPoint(int(s * 0.58), int(s * 0.7)),
                QPoint(int(s * 0.5), int(s * 0.88)),
            ]
            painter.drawPolygon(inner_flame)

        elif icon_type == "target":
            # Crosshair/target with lines through center
            painter.drawEllipse(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(int(s * 0.2), int(s * 0.2), int(s * 0.6), int(s * 0.6))
            painter.setBrush(QColor(color))
            painter.drawEllipse(int(s * 0.35), int(s * 0.35), int(s * 0.3), int(s * 0.3))
            painter.setPen(QPen(QColor(color), max(1, int(s * 0.06))))
            painter.drawLine(int(s * 0.5), 0, int(s * 0.5), int(s * 0.3))
            painter.drawLine(int(s * 0.5), int(s * 0.7), int(s * 0.5), s)
            painter.drawLine(0, int(s * 0.5), int(s * 0.3), int(s * 0.5))
            painter.drawLine(int(s * 0.7), int(s * 0.5), s, int(s * 0.5))

        elif icon_type == "palette":
            # Artist palette with thumb hole
            painter.drawEllipse(int(s * 0.05), int(s * 0.15), int(s * 0.9), int(s * 0.7))
            painter.setBrush(QColor("#00000000"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.drawEllipse(int(s * 0.12), int(s * 0.55), int(s * 0.2), int(s * 0.22))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            paint_colors = ["#E74C3C", "#3498DB", "#F1C40F", "#2ECC71", "#9B59B6"]
            positions = [(0.35, 0.25), (0.6, 0.22), (0.78, 0.35), (0.7, 0.55), (0.45, 0.5)]
            for c, (px, py) in zip(paint_colors, positions, strict=True):
                painter.setBrush(QColor(c))
                painter.drawEllipse(
                    int(s * px), int(s * py), int(s * 0.15), int(s * 0.15)
                )

        elif icon_type == "cube":
            # 3D cube with visible edges
            base_color = QColor(color)
            light_color = base_color.lighter(130)
            dark_color = base_color.darker(120)
            painter.setBrush(base_color)
            painter.drawRect(int(s * 0.1), int(s * 0.35), int(s * 0.5), int(s * 0.55))
            painter.setBrush(light_color)
            top = [
                QPoint(int(s * 0.1), int(s * 0.35)),
                QPoint(int(s * 0.35), int(s * 0.1)),
                QPoint(int(s * 0.85), int(s * 0.1)),
                QPoint(int(s * 0.6), int(s * 0.35)),
            ]
            painter.drawPolygon(top)
            painter.setBrush(dark_color)
            right = [
                QPoint(int(s * 0.6), int(s * 0.35)),
                QPoint(int(s * 0.85), int(s * 0.1)),
                QPoint(int(s * 0.85), int(s * 0.65)),
                QPoint(int(s * 0.6), int(s * 0.9)),
            ]
            painter.drawPolygon(right)

        elif icon_type == "play":
            # Classic play button - rounded rect with bold triangle
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(
                int(s * 0.02), int(s * 0.02), int(s * 0.96), int(s * 0.96), 4, 4
            )
            painter.setBrush(QColor("#FFFFFF"))
            play = [
                QPoint(int(s * 0.3), int(s * 0.15)),
                QPoint(int(s * 0.3), int(s * 0.85)),
                QPoint(int(s * 0.85), int(s * 0.5)),
            ]
            painter.drawPolygon(play)

        elif icon_type == "clipboard":
            # Clipboard with checkmark
            painter.drawRoundedRect(
                int(s * 0.1), int(s * 0.15), int(s * 0.8), int(s * 0.8), 3, 3
            )
            painter.setBrush(QColor("#888888"))
            painter.drawRoundedRect(
                int(s * 0.3), int(s * 0.02), int(s * 0.4), int(s * 0.2), 2, 2
            )
            painter.setPen(QPen(QColor("#FFFFFF"), max(2, int(s * 0.12))))
            painter.drawLine(
                int(s * 0.25), int(s * 0.55), int(s * 0.42), int(s * 0.75)
            )
            painter.drawLine(
                int(s * 0.42), int(s * 0.75), int(s * 0.75), int(s * 0.35)
            )

        elif icon_type == "note":
            # Sticky note with folded corner
            painter.drawRect(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
            painter.setBrush(QColor(color).darker(130))
            fold = [
                QPoint(int(s * 0.65), int(s * 0.08)),
                QPoint(int(s * 0.92), int(s * 0.08)),
                QPoint(int(s * 0.92), int(s * 0.35)),
            ]
            painter.drawPolygon(fold)
            painter.setPen(QPen(QColor("#FFFFFF").darker(110), 1))
            for i in range(3):
                y = int(s * (0.35 + i * 0.18))
                painter.drawLine(int(s * 0.18), y, int(s * 0.82), y)

        else:
            # Fallback: simple circle
            painter.drawEllipse(int(s * 0.1), int(s * 0.1), int(s * 0.8), int(s * 0.8))

        _ = painter.end()
        return QIcon(pixmap)

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

    # ============= Sort order methods =============

    def _on_sort_button_clicked(self, button_id: int) -> None:
        """Handle sort button click.

        Args:
            button_id: ID of clicked button (0=name, 1=date)

        """
        order = "name" if button_id == 0 else "date"
        self.sort_order_changed.emit(order)
        self.logger.info(f"Sort order changed to: {order}")

    def set_sort_order(self, order: str) -> None:
        """Set the sort order and update button states.

        Called by MainWindow when restoring settings or syncing with model.

        Args:
            order: Sort order ("name" or "date")

        """
        if order not in ("name", "date"):
            return

        # Update button states without emitting signal
        _ = self._sort_button_group.blockSignals(True)
        if order == "name":
            self.sort_name_btn.setChecked(True)
        else:
            self.sort_date_btn.setChecked(True)
        _ = self._sort_button_group.blockSignals(False)
