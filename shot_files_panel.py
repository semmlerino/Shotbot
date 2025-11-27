"""Shot files panel widget for displaying files associated with a shot."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qt_widget_mixin import QtWidgetMixin
from scene_file import FILE_TYPE_COLORS, FileType, SceneFile
from shot_file_finder import ShotFileFinder


if TYPE_CHECKING:
    from PySide6.QtCore import QPoint

    from type_definitions import Shot


@final
class FileListItem(QFrame):
    """Single file row displaying filename and modification time.

    Shows file name with relative age, supports right-click context menu.
    """

    # Signals
    open_requested = Signal(SceneFile)
    open_folder_requested = Signal(SceneFile)

    def __init__(
        self,
        scene_file: SceneFile,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize file list item.

        Args:
            scene_file: The scene file to display
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._scene_file = scene_file
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        # File name label
        name_label = QLabel(self._scene_file.name)
        name_label.setStyleSheet("color: #ddd; font-size: 11px;")
        layout.addWidget(name_label, 1)

        # User label
        user_label = QLabel(self._scene_file.user)
        user_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(user_label)

        # Age label
        age_label = QLabel(self._scene_file.relative_age)
        age_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(age_label)

        # Tooltip with full path
        self.setToolTip(str(self._scene_file.path))

        # Style
        self.setStyleSheet("""
            FileListItem {
                background-color: transparent;
                border-radius: 3px;
            }
            FileListItem:hover {
                background-color: #2a2a2a;
            }
        """)

        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        _ = self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show context menu at position.

        Args:
            pos: Menu position
        """
        menu = QMenu(self)

        # Open action
        open_action = QAction(f"Open in {self._scene_file.display_name}", self)
        _ = open_action.triggered.connect(
            lambda: self.open_requested.emit(self._scene_file)
        )
        menu.addAction(open_action)

        # Open folder action
        open_folder_action = QAction("Open Folder", self)
        _ = open_folder_action.triggered.connect(self._open_folder)
        menu.addAction(open_folder_action)

        _ = menu.addSeparator()

        # Copy path action
        copy_path_action = QAction("Copy Path", self)
        _ = copy_path_action.triggered.connect(self._copy_path)
        menu.addAction(copy_path_action)

        _ = menu.exec(self.mapToGlobal(pos))

    def _open_folder(self) -> None:
        """Open the containing folder in file manager."""
        folder_url = self._scene_file.path.parent.as_uri()
        _ = QDesktopServices.openUrl(folder_url)

    def _copy_path(self) -> None:
        """Copy the file path to clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(str(self._scene_file.path))


@final
class FileTypeSection(QtWidgetMixin, QWidget):
    """Collapsible section for one file type (3DE, Maya, or Nuke).

    Contains a header with expand/collapse button and a list of files.
    """

    # Signals
    file_open_requested = Signal(SceneFile)

    def __init__(
        self,
        file_type: FileType,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize file type section.

        Args:
            file_type: The type of files this section displays
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._file_type = file_type
        self._is_expanded = True
        self._files: list[SceneFile] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 5)
        layout.setSpacing(3)

        # Header with expand/collapse button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)

        # Expand/collapse button
        self._expand_button = QToolButton()
        self._expand_button.setArrowType(Qt.ArrowType.DownArrow)
        _ = self._expand_button.clicked.connect(self._toggle_expanded)
        self._expand_button.setMaximumSize(20, 20)
        self._expand_button.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
            }
            QToolButton:hover {
                background-color: #333;
                border-radius: 2px;
            }
        """)
        header_layout.addWidget(self._expand_button)

        # Type label with count
        color = FILE_TYPE_COLORS[self._file_type]
        self._header_label = QLabel(self._get_header_text(0))
        self._header_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: 11px;
                color: {color};
            }}
        """)
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Content container for file list
        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(20, 0, 0, 0)  # Indent content
        content_layout.setSpacing(2)

        # Placeholder for file items
        self._file_list_layout = content_layout

        layout.addWidget(self._content_widget)

    def _get_header_text(self, count: int) -> str:
        """Get header text with file count.

        Args:
            count: Number of files

        Returns:
            Header text like "3DEqualizer (5)"
        """
        type_names = {
            FileType.THREEDE: "3DEqualizer",
            FileType.MAYA: "Maya",
            FileType.NUKE: "Nuke",
        }
        name = type_names[self._file_type]
        return f"{name} ({count})"

    def _toggle_expanded(self) -> None:
        """Toggle expanded/collapsed state."""
        self._is_expanded = not self._is_expanded
        self._expand_button.setArrowType(
            Qt.ArrowType.DownArrow if self._is_expanded else Qt.ArrowType.RightArrow
        )
        self._content_widget.setVisible(self._is_expanded)

    def set_files(self, files: list[SceneFile]) -> None:
        """Set the files to display.

        Args:
            files: List of scene files to display
        """
        self._files = files

        # Clear existing items
        while self._file_list_layout.count():
            layout_item = self._file_list_layout.takeAt(0)
            widget = layout_item.widget() if layout_item else None
            if widget:
                widget.deleteLater()

        # Update header
        self._header_label.setText(self._get_header_text(len(files)))

        # Add file items
        for scene_file in files:
            item = FileListItem(scene_file, parent=self)
            _ = item.open_requested.connect(self.file_open_requested.emit)
            self._file_list_layout.addWidget(item)

        # Show/hide based on file count
        self.setVisible(len(files) > 0)

    def clear(self) -> None:
        """Clear all files."""
        self.set_files([])


@final
class ShotFilesPanel(QtWidgetMixin, QWidget):
    """Panel displaying files associated with the current shot.

    Contains collapsible sections for each file type (3DE, Maya, Nuke).
    """

    # Signals
    file_open_requested = Signal(SceneFile)

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize shot files panel.

        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._finder = ShotFileFinder()
        self._current_shot: Shot | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(5)

        # Section header
        header = QLabel("Files")
        header.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 12px;
                color: #aaa;
                padding-bottom: 5px;
            }
        """)
        layout.addWidget(header)

        # Create sections for each file type
        self._sections: dict[FileType, FileTypeSection] = {}
        for file_type in FileType:
            section = FileTypeSection(file_type, parent=self)
            _ = section.file_open_requested.connect(self.file_open_requested.emit)
            layout.addWidget(section)
            self._sections[file_type] = section

        # Add stretch at bottom
        layout.addStretch()

    def set_shot(self, shot: Shot | None) -> None:
        """Set the current shot and discover files.

        Args:
            shot: The shot to display files for, or None to clear
        """
        self._current_shot = shot

        if shot is None:
            self._clear_all()
            return

        # Discover files (synchronous for MVP)
        try:
            files_by_type = self._finder.find_all_files(shot)

            # Update each section
            for file_type, section in self._sections.items():
                files = files_by_type.get(file_type, [])
                section.set_files(files)

        except Exception as e:
            self.logger.error(f"Error discovering files for {shot.full_name}: {e}")
            self._clear_all()

    def _clear_all(self) -> None:
        """Clear all sections."""
        for section in self._sections.values():
            section.clear()
