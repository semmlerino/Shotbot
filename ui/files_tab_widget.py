"""Table model for displaying scene files by DCC type."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, final

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)

from typing_compat import override


if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from dcc.scene_file import SceneFile


@final
class FileTableModel(QAbstractTableModel):
    """Table model for displaying scene files.

    Shows columns: Version, Age, User
    Stores SceneFile objects for retrieval on selection.
    """

    COLUMNS: ClassVar[list[str]] = ["Version", "Age", "User", "Comment"]

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

    def update_file_comment(self, row: int, comment: str) -> SceneFile | None:
        """Replace the comment on the file at *row* and refresh.

        Returns the updated :class:`SceneFile`, or ``None`` if *row* is out of
        range.
        """
        if row < 0 or row >= len(self._files):
            return None

        from dataclasses import replace

        old = self._files[row]
        updated = replace(old, comment=comment or None)
        self._files[row] = updated

        if old == self._current_default:
            self._current_default = updated

        top_left = self.index(row, 0)
        bottom_right = self.index(row, len(self.COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right)
        return updated

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
                if file.read_only:
                    version_str = f"{version_str} (published)"
                # Show arrow indicator if this is the current default
                if file == self._current_default:
                    return f"-> {version_str}"
                return version_str
            if col == 1:  # Age
                return file.relative_age
            if col == 2:  # User
                return file.user
            if col == 3:  # Comment
                return file.comment or ""

        elif role == Qt.ItemDataRole.ToolTipRole:
            tip = f"{file.name}\n{file.path}\n{file.formatted_time}"
            if file.comment:
                tip += f"\n\nComment: {file.comment}"
            return tip

        elif role == Qt.ItemDataRole.UserRole:
            # Return the SceneFile object for easy retrieval
            return file

        return None
