"""Shot files panel widget for displaying files associated with a shot."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from design_system import design_system
from qt_widget_mixin import QtWidgetMixin
from scene_file import FILE_TYPE_COLORS, FileType, SceneFile
from shot_file_finder import ShotFileFinder


if TYPE_CHECKING:
    from PySide6.QtCore import QPoint

    from file_pin_manager import FilePinManager
    from type_definitions import Shot


@final
class FileListItem(QFrame):
    """Single file row displaying filename and modification time.

    Shows file name with relative age, supports right-click context menu.
    """

    # Signals
    open_requested = Signal(SceneFile)

    def __init__(
        self,
        scene_file: SceneFile,
        file_pin_manager: FilePinManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize file list item.

        Args:
            scene_file: The scene file to display
            file_pin_manager: Optional pin manager for pin operations
            parent: Optional parent widget

        """
        super().__init__(parent)
        self._scene_file = scene_file
        self._file_pin_manager = file_pin_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        # File name label
        name_label = QLabel(self._scene_file.name)
        name_label.setStyleSheet(f"color: #ddd; font-size: {design_system.typography.size_tiny}px;")
        layout.addWidget(name_label, 1)

        # User label
        user_label = QLabel(self._scene_file.user)
        user_label.setStyleSheet(f"color: #888; font-size: {design_system.typography.size_small}px;")
        layout.addWidget(user_label)

        # Age label
        age_label = QLabel(self._scene_file.relative_age)
        age_label.setStyleSheet(f"color: #666; font-size: {design_system.typography.size_small}px;")
        layout.addWidget(age_label)

        # Apply pin-aware styling (sets tooltip and stylesheet)
        self._apply_pin_styling()

        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        _ = self.customContextMenuRequested.connect(self._show_context_menu)

    def _apply_pin_styling(self) -> None:
        """Apply visual styling based on pin state."""
        is_pinned = (
            self._file_pin_manager is not None
            and self._file_pin_manager.is_pinned(self._scene_file.path)
        )

        if is_pinned and self._file_pin_manager is not None:
            # Pinned: gold/amber highlight with left border
            self.setStyleSheet("""
                FileListItem {
                    background-color: rgba(255, 193, 7, 0.15);
                    border-radius: 3px;
                    border-left: 3px solid #ffc107;
                }
                FileListItem:hover {
                    background-color: rgba(255, 193, 7, 0.25);
                }
            """)
            # Add comment to tooltip if present
            comment = self._file_pin_manager.get_comment(self._scene_file.path)
            if comment:
                self.setToolTip(f"{self._scene_file.path}\n\nPin Note: {comment}")
            else:
                self.setToolTip(f"{self._scene_file.path}\n(Pinned)")
        else:
            # Standard styling
            self.setStyleSheet("""
                FileListItem {
                    background-color: transparent;
                    border-radius: 3px;
                }
                FileListItem:hover {
                    background-color: #2a2a2a;
                }
            """)
            self.setToolTip(str(self._scene_file.path))

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

        # Pin actions (if pin manager available)
        if self._file_pin_manager:
            is_pinned = self._file_pin_manager.is_pinned(self._scene_file.path)

            if is_pinned:
                # Edit comment action
                edit_comment_action = QAction("Edit Pin Comment...", self)
                _ = edit_comment_action.triggered.connect(self._edit_pin_comment)
                menu.addAction(edit_comment_action)

                # Unpin action
                unpin_action = QAction("Unpin Version", self)
                _ = unpin_action.triggered.connect(self._unpin_file)
                menu.addAction(unpin_action)
            else:
                # Pin action
                pin_action = QAction("Pin Version...", self)
                _ = pin_action.triggered.connect(self._pin_file)
                menu.addAction(pin_action)

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

    def _pin_file(self) -> None:
        """Pin file with optional comment dialog."""
        if not self._file_pin_manager:
            return

        comment, ok = QInputDialog.getMultiLineText(
            self,
            f"Pin {self._scene_file.name}",
            "Comment (optional):",
            "",
        )
        if ok:
            self._file_pin_manager.pin_file(self._scene_file.path, comment)
            self._apply_pin_styling()

    def _unpin_file(self) -> None:
        """Remove pin from file."""
        if not self._file_pin_manager:
            return

        self._file_pin_manager.unpin_file(self._scene_file.path)
        self._apply_pin_styling()

    def _edit_pin_comment(self) -> None:
        """Edit comment on pinned file."""
        if not self._file_pin_manager:
            return

        current_comment = self._file_pin_manager.get_comment(self._scene_file.path)
        new_comment, ok = QInputDialog.getMultiLineText(
            self,
            f"Edit Pin Comment - {self._scene_file.name}",
            "Comment:",
            current_comment,
        )
        if ok:
            self._file_pin_manager.set_comment(self._scene_file.path, new_comment)
            self._apply_pin_styling()


@final
class FileTypeSection(QtWidgetMixin, QWidget):
    """Collapsible section for one file type (3DE, Maya, or Nuke).

    Contains a header with expand/collapse button and a list of files.
    """

    def __init__(
        self,
        file_type: FileType,
        file_pin_manager: FilePinManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize file type section.

        Args:
            file_type: The type of files this section displays
            file_pin_manager: Optional pin manager for pin operations
            parent: Optional parent widget

        """
        super().__init__(parent)
        self._file_type = file_type
        self._file_pin_manager = file_pin_manager
        self._is_expanded = False  # Collapsed by default (chip style)
        self._files: list[SceneFile] = []
        self._chip_button: QPushButton  # Chip button for expand/collapse
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI with chip-style button."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Chip button (replaces expand arrow + header label)
        color = FILE_TYPE_COLORS[self._file_type]
        self._chip_button = QPushButton(self._get_header_text(0))
        self._chip_button.setCheckable(True)
        self._chip_button.setChecked(False)
        _ = self._chip_button.clicked.connect(self._toggle_expanded)
        self._chip_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: #eee;
                border-radius: 12px;
                padding: 4px 12px;
                font-size: {design_system.typography.size_tiny}px;
                font-weight: bold;
                border: 2px solid transparent;
            }}
            QPushButton:checked {{
                border: 2px solid #fff;
            }}
            QPushButton:hover {{
                background-color: {self._lighten_color(color, 20)};
            }}
        """)
        layout.addWidget(self._chip_button)

        # Content container for file list (hidden by default)
        self._content_widget = QWidget()
        self._content_widget.setVisible(False)
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 5, 0, 0)
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

    def _lighten_color(self, hex_color: str, percent: int) -> str:
        """Lighten a hex color by a percentage.

        Args:
            hex_color: Hex color like '#c0392b'
            percent: Percentage to lighten (0-100)

        Returns:
            Lightened hex color

        """
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        # Lighten
        r = min(255, r + int((255 - r) * percent / 100))
        g = min(255, g + int((255 - g) * percent / 100))
        b = min(255, b + int((255 - b) * percent / 100))

        return f"#{r:02x}{g:02x}{b:02x}"

    def _toggle_expanded(self) -> None:
        """Toggle expanded/collapsed state."""
        self._is_expanded = not self._is_expanded
        self._chip_button.setChecked(self._is_expanded)
        self._content_widget.setVisible(self._is_expanded)

    def set_files(self, files: list[SceneFile]) -> None:
        """Set the files to display with pinned files sorted first.

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

        # Update chip text
        self._chip_button.setText(self._get_header_text(len(files)))

        # Sort files with pinned first
        sorted_files = self._sort_with_pinned_first(files)

        # Add file items
        for scene_file in sorted_files:
            item = FileListItem(
                scene_file,
                file_pin_manager=self._file_pin_manager,
                parent=self,
            )
            self._file_list_layout.addWidget(item)

        # Show/hide based on file count
        self.setVisible(len(files) > 0)

    def _sort_with_pinned_first(self, files: list[SceneFile]) -> list[SceneFile]:
        """Sort files with pinned files first, preserving relative order.

        Args:
            files: Original file list (typically sorted by mtime)

        Returns:
            Sorted list with pinned files first

        """
        if not self._file_pin_manager:
            return files

        pinned: list[SceneFile] = []
        unpinned: list[SceneFile] = []

        for f in files:
            if self._file_pin_manager.is_pinned(f.path):
                pinned.append(f)
            else:
                unpinned.append(f)

        return pinned + unpinned

    def clear(self) -> None:
        """Clear all files."""
        self.set_files([])


@final
class ShotFilesPanel(QtWidgetMixin, QWidget):
    """Panel displaying files associated with the current shot.

    Contains collapsible sections for each file type (3DE, Maya, Nuke).
    """

    def __init__(
        self,
        file_pin_manager: FilePinManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize shot files panel.

        Args:
            file_pin_manager: Optional pin manager for pin operations
            parent: Optional parent widget

        """
        super().__init__(parent)
        self._file_pin_manager = file_pin_manager
        self._finder = ShotFileFinder()
        self._current_shot: Shot | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI with horizontal chip layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(5)

        # Section header
        header = QLabel("Files")
        header.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: {design_system.typography.size_small}px;
                color: #aaa;
                padding-bottom: 5px;
            }}
        """)
        layout.addWidget(header)

        # Horizontal chip row
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.setContentsMargins(0, 0, 0, 0)

        # Create sections for each file type
        self._sections: dict[FileType, FileTypeSection] = {}
        for file_type in FileType:
            section = FileTypeSection(
                file_type,
                file_pin_manager=self._file_pin_manager,
                parent=self,
            )
            chip_row.addWidget(section)
            self._sections[file_type] = section

        chip_row.addStretch()
        layout.addLayout(chip_row)

        # Scrollable expansion area for file lists
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setMaximumHeight(150)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        # Container for expanded file lists
        self._expansion_container = QWidget()
        expansion_layout = QVBoxLayout(self._expansion_container)
        expansion_layout.setContentsMargins(0, 5, 0, 0)
        expansion_layout.setSpacing(2)

        self._scroll_area.setWidget(self._expansion_container)
        layout.addWidget(self._scroll_area)

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

        except Exception:
            self.logger.exception(f"Error discovering files for {shot.full_name}")
            self._clear_all()

    def _clear_all(self) -> None:
        """Clear all sections."""
        for section in self._sections.values():
            section.clear()
