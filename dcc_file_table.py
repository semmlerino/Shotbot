"""Embeddable file table widget for DCC sections.

Displays a collapsible list of scene files with selection, double-click launch,
and right-click context menu (open, copy path, open folder).
Extracted from DCCSection to isolate file-list concerns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import QModelIndex, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from design_system import design_system
from resizable_frame import ResizableFrame
from settings_manager import get_stored_height


if TYPE_CHECKING:
    from files_tab_widget import FileTableModel
    from scene_file import SceneFile
    from settings_manager import SettingsManager


class DCCFileTable(QWidget):
    """Collapsible file-table subsection for a DCC panel.

    Signals:
        file_selected: Emitted with the SceneFile when a file row is clicked.
        launch_file_requested: Emitted with the SceneFile when the user wants
            to open a file (double-click or context-menu "Open in ...").
    """

    file_selected: ClassVar[Signal] = Signal(object)  # SceneFile
    launch_file_requested: ClassVar[Signal] = Signal(object)  # SceneFile

    _DEFAULT_PANEL_HEIGHT: int = 120

    def __init__(
        self,
        *,
        dcc_name: str,
        display_name: str,
        accent_color: str,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the file table subsection.

        Args:
            dcc_name: Internal DCC name (e.g. "3de") used for settings keys.
            display_name: Human-readable DCC name for context-menu labels.
            accent_color: Hex colour string for selection highlighting.
            settings_manager: Optional settings manager for height persistence.
            parent: Optional parent widget.

        """
        super().__init__(parent)
        self._dcc_name: str = dcc_name
        self._display_name: str = display_name
        self._accent_color: str = accent_color
        self._settings_manager: SettingsManager | None = settings_manager

        self._files_expanded: bool = False
        self._files_count: int = 0
        self._current_selected_file: SceneFile | None = None

        # UI references populated by _setup_ui
        self._files_header_btn: QPushButton | None = None
        self._files_content: QWidget | None = None
        self._file_table: QTableView | None = None
        self._file_model: FileTableModel | None = None
        self._file_table_frame: ResizableFrame | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the collapsible files subsection."""
        from files_tab_widget import FileTableModel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        # Header button (collapsible)
        self._files_header_btn = QPushButton("\u25b6  Files (0)")
        self._files_header_btn.setFlat(True)
        self._files_header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ = self._files_header_btn.clicked.connect(self._toggle_files_expanded)
        layout.addWidget(self._files_header_btn)

        # Content container (hidden by default)
        self._files_content = QWidget()
        self._files_content.setVisible(False)
        content_layout = QVBoxLayout(self._files_content)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(0)

        # Table model and view
        self._file_model = FileTableModel(parent=self)
        self._file_table = QTableView()
        self._file_table.setModel(self._file_model)
        self._file_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._file_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._file_table.setAlternatingRowColors(True)
        self._file_table.setSortingEnabled(False)
        self._file_table.setShowGrid(False)
        self._file_table.verticalHeader().setVisible(False)

        # Configure header
        header = self._file_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        # Signals
        _ = self._file_table.clicked.connect(self._on_file_clicked)
        self._file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        _ = self._file_table.customContextMenuRequested.connect(
            self._show_file_context_menu
        )
        _ = self._file_table.doubleClicked.connect(self._on_file_double_clicked)

        # Resizable frame
        self._file_table_frame = ResizableFrame(
            child_widget=self._file_table,
            min_height=60,
            max_height=400,
            initial_height=self._get_stored_table_height(),
            accent_color=self._accent_color,
            parent=self,
        )
        _ = self._file_table_frame.height_changed.connect(self._on_table_height_changed)
        content_layout.addWidget(self._file_table_frame)
        layout.addWidget(self._files_content)

    # ------------------------------------------------------------------
    # Styling (called externally by DCCSection._apply_styles)
    # ------------------------------------------------------------------

    def apply_styles(self) -> None:
        """Apply / refresh styles using the current design system values."""
        if self._files_header_btn is not None:
            self._files_header_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    text-align: left;
                    padding: 4px 0px;
                    font-size: {design_system.typography.size_tiny}px;
                    font-weight: bold;
                    color: #888;
                }}
                QPushButton:hover {{
                    color: #aaa;
                }}
            """)

        if self._file_table is not None:
            color = self._accent_color
            self._file_table.setStyleSheet(f"""
                QTableView {{
                    background-color: #1e1e1e;
                    alternate-background-color: #232323;
                    color: #ecf0f1;
                    border: 1px solid #333;
                    border-radius: 3px;
                    selection-background-color: {color}40;
                    selection-color: #ecf0f1;
                }}
                QTableView::item {{
                    padding: 2px 6px;
                    font-size: {design_system.typography.size_small}px;
                }}
                QTableView::item:selected {{
                    background-color: {color}60;
                }}
                QHeaderView::section {{
                    background-color: #252525;
                    color: #888;
                    padding: 3px 6px;
                    border: none;
                    border-bottom: 1px solid #333;
                    font-weight: bold;
                    font-size: {design_system.typography.size_tiny}px;
                }}
            """)

    # ------------------------------------------------------------------
    # Expand / collapse
    # ------------------------------------------------------------------

    def _toggle_files_expanded(self) -> None:
        """Toggle the files subsection expanded state."""
        self._files_expanded = not self._files_expanded
        if self._files_content is not None:
            self._files_content.setVisible(self._files_expanded)
        self._update_files_header()

    def _update_files_header(self) -> None:
        """Update files header text with indicator and count."""
        if self._files_header_btn is not None:
            indicator = "\u25bc" if self._files_expanded else "\u25b6"
            self._files_header_btn.setText(f"{indicator}  Files ({self._files_count})")

    def set_files_expanded(self, expanded: bool) -> None:
        """Set the files subsection expanded state.

        Args:
            expanded: True to expand, False to collapse.

        """
        if self._files_expanded != expanded:
            self._files_expanded = expanded
            if self._files_content is not None:
                self._files_content.setVisible(expanded)
            self._update_files_header()

    def is_files_expanded(self) -> bool:
        """Return files subsection expanded state."""
        return self._files_expanded

    # ------------------------------------------------------------------
    # File selection and interaction
    # ------------------------------------------------------------------

    def _on_file_clicked(self, index: QModelIndex) -> None:
        """Handle file row click -- select but don't launch.

        Args:
            index: The clicked model index.

        """
        if self._file_model is not None:
            file = self._file_model.get_file(index.row())
            if file is not None:
                self._select_file(file)

    def _select_file(self, file: SceneFile) -> None:
        """Set *file* as the current selection and notify listeners.

        Args:
            file: SceneFile to select.

        """
        self._current_selected_file = file
        if self._file_model is not None:
            self._file_model.set_current_default(file)
        self.file_selected.emit(file)

    def _select_and_launch_file(self, file: SceneFile) -> None:
        """Select *file* and emit a launch signal.

        Args:
            file: SceneFile to select and launch.

        """
        self._select_file(file)
        self.launch_file_requested.emit(file)

    def _on_file_double_clicked(self, index: QModelIndex) -> None:
        """Handle file row double-click -- launch immediately.

        Args:
            index: The double-clicked model index.

        """
        if self._file_model is None:
            return
        file = self._file_model.get_file(index.row())
        if file is None:
            return
        self._select_and_launch_file(file)

    def _show_file_context_menu(self, pos: QPoint) -> None:
        """Show context menu for file table.

        Args:
            pos: Position where context menu was requested.

        """
        if self._file_table is None or self._file_model is None:
            return

        index = self._file_table.indexAt(pos)
        if not index.isValid():
            return

        file = self._file_model.get_file(index.row())
        if file is None:
            return

        menu = QMenu(self)

        open_action = menu.addAction(f"Open in {self._display_name}")
        _ = open_action.triggered.connect(lambda: self._launch_file(file))

        open_folder_action = menu.addAction("Open Containing Folder")
        _ = open_folder_action.triggered.connect(lambda: self._open_file_folder(file))

        _ = menu.addSeparator()

        copy_path_action = menu.addAction("Copy Path")
        _ = copy_path_action.triggered.connect(lambda: self._copy_file_path(file))

        _ = menu.exec(self._file_table.mapToGlobal(pos))

    def _launch_file(self, file: SceneFile) -> None:
        """Launch the DCC app with the specified file.

        Args:
            file: SceneFile to launch.

        """
        self._select_and_launch_file(file)

    @staticmethod
    def _open_file_folder(file: SceneFile) -> None:
        """Open the containing folder for a file.

        Args:
            file: SceneFile whose parent folder to open.

        """
        from pathlib import Path

        from PySide6.QtCore import QThreadPool

        from runnable_tracker import FolderOpenerWorker

        file_path = Path(file.path)
        if file_path.exists():
            folder_path = str(file_path.parent)
            worker = FolderOpenerWorker(folder_path)
            QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _copy_file_path(file: SceneFile) -> None:
        """Copy file path to clipboard.

        Args:
            file: SceneFile whose path to copy.

        """
        clipboard = QApplication.clipboard()
        clipboard.setText(str(file.path))

    # ------------------------------------------------------------------
    # Public data API
    # ------------------------------------------------------------------

    def set_files(self, files: list[SceneFile]) -> None:
        """Set files for display.

        Args:
            files: List of scene files to display.

        """
        if self._file_model is not None:
            self._file_model.set_files(files)
            self._files_count = len(files)
            self._update_files_header()

            if files:
                self._current_selected_file = files[0]
                self._file_model.set_current_default(files[0])
            else:
                self._current_selected_file = None

    def get_selected_file(self) -> SceneFile | None:
        """Get the currently selected file.

        Returns:
            Selected SceneFile or None.

        """
        return self._current_selected_file

    def set_default_file(self, file: SceneFile | None) -> None:
        """Mark a file as the default (shows arrow indicator).

        Args:
            file: The file to mark as default, or None to clear.

        """
        self._current_selected_file = file
        if self._file_model is not None:
            self._file_model.set_current_default(file)

    # ------------------------------------------------------------------
    # Height persistence
    # ------------------------------------------------------------------

    def _get_stored_table_height(self) -> int:
        """Get stored table height from settings."""
        if self._settings_manager is None:
            return self._DEFAULT_PANEL_HEIGHT
        return get_stored_height(
            self._settings_manager.settings,
            f"ui/table_height/{self._dcc_name}",
            self._DEFAULT_PANEL_HEIGHT,
        )

    def _on_table_height_changed(self, height: int) -> None:
        """Save new table height to settings.

        Args:
            height: The new height value.

        """
        if self._settings_manager is not None:
            self._settings_manager.settings.setValue(
                f"ui/table_height/{self._dcc_name}", height
            )
