"""Files tab widget for viewing scene files by DCC type.

Provides a tabbed interface with tables showing scene files grouped by
DCC application (3DE, Maya, Nuke). Each table shows version, age, and
user information with click and double-click actions.
"""

from __future__ import annotations

from typing import Any, ClassVar, final

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qt_widget_mixin import QtWidgetMixin
from scene_file import FILE_TYPE_COLORS, FileType, SceneFile
from typing_compat import override
from ui.design_system import design_system


@final
class FileTableModel(QAbstractTableModel):
    """Table model for displaying scene files.

    Shows columns: Version, Age, User
    Stores SceneFile objects for retrieval on selection.
    """

    COLUMNS: ClassVar[list[str]] = ["Version", "Age", "User"]

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the model.

        Args:
            parent: Optional parent widget

        """
        super().__init__(parent)
        self._files: list[SceneFile] = []
        self._current_default: SceneFile | None = None

    def set_files(self, files: list[SceneFile]) -> None:
        """Set the files to display.

        Args:
            files: List of scene files to display

        """
        self.beginResetModel()
        self._files = list(files)
        self.endResetModel()

    def get_file(self, row: int) -> SceneFile | None:
        """Get the file at a specific row.

        Args:
            row: Row index

        Returns:
            SceneFile at that row or None if out of bounds

        """
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def set_current_default(self, file: SceneFile | None) -> None:
        """Mark a file as the current default (shows arrow indicator).

        Args:
            file: The file to mark as default, or None to clear

        """
        old_default = self._current_default
        self._current_default = file

        # Refresh affected rows
        self._refresh_row_for_file(old_default)
        self._refresh_row_for_file(file)

    def _refresh_row_for_file(self, file: SceneFile | None) -> None:
        """Emit dataChanged for the row containing this file.

        Args:
            file: The file whose row needs refresh, or None

        """
        if file is None:
            return
        try:
            row = self._files.index(file)
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx)
        except ValueError:
            pass  # File not in list

    @override
    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex | None = None
    ) -> int:
        """Return number of rows."""
        if parent is not None and parent.isValid():
            return 0
        return len(self._files)

    @override
    def columnCount(
        self, parent: QModelIndex | QPersistentModelIndex | None = None
    ) -> int:
        """Return number of columns."""
        if parent is not None and parent.isValid():
            return 0
        return len(self.COLUMNS)

    @override
    def headerData(  # pyright: ignore[reportAny]
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return header data."""
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                if 0 <= section < len(self.COLUMNS):
                    return self.COLUMNS[section]
        return None

    @override
    def data(  # pyright: ignore[reportAny]
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return data for the given index and role."""
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self._files):
            return None

        file = self._files[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:  # Version
                version_str = f"v{file.version:03d}" if file.version else "—"
                # Show arrow indicator if this is the current default
                if file == self._current_default:
                    return f"-> {version_str}"
                return version_str
            if col == 1:  # Age
                return file.relative_age
            if col == 2:  # User
                return file.user

        elif role == Qt.ItemDataRole.ToolTipRole:
            return f"{file.name}\n{file.path}\n{file.formatted_time}"

        elif role == Qt.ItemDataRole.UserRole:
            # Return the SceneFile object for easy retrieval
            return file

        return None


@final
class FilesTabWidget(QtWidgetMixin, QWidget):
    """Tabbed widget showing files by DCC type.

    Contains tabs for 3DE, Maya, and Nuke files, each with a table view
    showing version, age, and user columns.

    Attributes:
        file_selected: Signal(SceneFile) - emitted on single click

    """

    file_selected = Signal(object)  # SceneFile

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the files tab widget.

        Args:
            parent: Optional parent widget

        """
        super().__init__(parent)
        self._tables: dict[FileType, QTableView] = {}
        self._models: dict[FileType, FileTableModel] = {}
        self._tab_indices: dict[FileType, int] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #252525;
                color: #888;
                padding: 6px 12px;
                border: 1px solid #333;
                border-bottom: none;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ecf0f1;
            }
            QTabBar::tab:hover:!selected {
                background-color: #2a2a2a;
            }
        """)

        # Create a tab for each file type
        for file_type in FileType:
            table = self._create_table(file_type)
            model = FileTableModel(self)

            table.setModel(model)
            self._tables[file_type] = table
            self._models[file_type] = model

            # Get display name for tab
            display_name = self._get_file_type_display(file_type)

            # Add tab
            idx = self._tab_widget.addTab(table, display_name)
            self._tab_indices[file_type] = idx

        layout.addWidget(self._tab_widget)

    def _create_table(self, file_type: FileType) -> QTableView:
        """Create a table view for a file type.

        Args:
            file_type: The file type this table displays

        Returns:
            Configured QTableView

        """
        table = QTableView()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)

        # Configure header
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        # Styling
        color = FILE_TYPE_COLORS[file_type]
        table.setStyleSheet(f"""
            QTableView {{
                background-color: #1e1e1e;
                alternate-background-color: #232323;
                color: #ecf0f1;
                border: none;
                selection-background-color: {color}40;
                selection-color: #ecf0f1;
            }}
            QTableView::item {{
                padding: 4px 8px;
            }}
            QTableView::item:selected {{
                background-color: {color}60;
            }}
            QHeaderView::section {{
                background-color: #252525;
                color: #888;
                padding: 4px 8px;
                border: none;
                border-bottom: 1px solid #333;
                font-weight: bold;
                font-size: {design_system.typography.size_extra_tiny}px;
            }}
        """)

        # Connect signals
        _ = table.clicked.connect(
            lambda idx, ft=file_type: self._on_row_clicked(ft, idx)  # type: ignore[arg-type]
        )
        _ = table.doubleClicked.connect(
            lambda idx, ft=file_type: self._on_row_double_clicked(ft, idx)  # type: ignore[arg-type]
        )

        return table

    def _get_file_type_display(self, file_type: FileType) -> str:
        """Get display name for a file type.

        Args:
            file_type: The file type

        Returns:
            Display name string

        """
        display_names = {
            FileType.THREEDE: "3DE",
            FileType.MAYA: "Maya",
            FileType.NUKE: "Nuke",
        }
        return display_names.get(file_type, file_type.name)

    def _on_row_clicked(self, file_type: FileType, index: QModelIndex) -> None:
        """Handle row click.

        Args:
            file_type: The file type of the clicked table
            index: The clicked model index

        """
        model = self._models.get(file_type)
        if model:
            file = model.get_file(index.row())
            if file:
                self.file_selected.emit(file)

    def _on_row_double_clicked(self, file_type: FileType, index: QModelIndex) -> None:
        """Handle row double-click.

        Args:
            file_type: The file type of the clicked table
            index: The clicked model index

        """
        _ = (file_type, index)  # double-click handler retained for future use

    def set_files(self, files_by_type: dict[FileType, list[SceneFile]]) -> None:
        """Set files for all tabs.

        Args:
            files_by_type: Dict mapping FileType to list of SceneFiles

        """
        for file_type, files in files_by_type.items():
            model = self._models.get(file_type)
            if model:
                model.set_files(files)
                # Update tab with count
                idx = self._tab_indices.get(file_type)
                if idx is not None:
                    display_name = self._get_file_type_display(file_type)
                    if files:
                        self._tab_widget.setTabText(idx, f"{display_name} ({len(files)})")
                    else:
                        self._tab_widget.setTabText(idx, display_name)

    def clear_files(self) -> None:
        """Clear all files from all tabs."""
        for file_type in FileType:
            model = self._models.get(file_type)
            if model:
                model.set_files([])
            idx = self._tab_indices.get(file_type)
            if idx is not None:
                display_name = self._get_file_type_display(file_type)
                self._tab_widget.setTabText(idx, display_name)

    def get_total_file_count(self) -> int:
        """Get total count of files across all tabs.

        Returns:
            Total number of files

        """
        total = 0
        for model in self._models.values():
            total += model.rowCount()
        return total

    def get_selected_file(self) -> SceneFile | None:
        """Get currently selected file.

        Returns:
            Selected SceneFile or None

        """
        # Get current tab's table
        current_idx = self._tab_widget.currentIndex()
        for file_type, idx in self._tab_indices.items():
            if idx == current_idx:
                table = self._tables.get(file_type)
                model = self._models.get(file_type)
                if table and model:
                    selection = table.selectionModel()
                    if selection and selection.hasSelection():
                        rows = selection.selectedRows()
                        if rows:
                            return model.get_file(rows[0].row())
        return None

    def set_current_tab(self, file_type: FileType) -> None:
        """Set the current tab.

        Args:
            file_type: The file type tab to show

        """
        idx = self._tab_indices.get(file_type)
        if idx is not None:
            self._tab_widget.setCurrentIndex(idx)

    def set_default_file(self, file_type: FileType, file: SceneFile | None) -> None:
        """Set the default file indicator for a specific file type.

        Args:
            file_type: The file type (tab) to update
            file: The file to mark as default, or None to clear

        """
        model = self._models.get(file_type)
        if model:
            model.set_current_default(file)
