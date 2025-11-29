"""Files section widget providing a collapsible wrapper for scene files.

Uses CollapsibleSection to wrap FilesTabWidget, showing file count
in the header when collapsed. Collapsed by default per user preference.
"""

from __future__ import annotations

from typing import final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from collapsible_section import CollapsibleSection
from files_tab_widget import FilesTabWidget
from qt_widget_mixin import QtWidgetMixin
from scene_file import FileType, SceneFile


@final
class FilesSection(QtWidgetMixin, QWidget):
    """Collapsible section containing scene files by DCC type.

    Wraps FilesTabWidget in a CollapsibleSection, showing total file
    count in the header. Collapsed by default (per user preference).

    Attributes:
        file_selected: Signal(SceneFile) - emitted when file clicked
        file_open_requested: Signal(SceneFile) - emitted on double-click
        expanded_changed: Signal(bool) - emitted when expanded state changes
    """

    file_selected = Signal(object)  # SceneFile
    file_open_requested = Signal(object)  # SceneFile
    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str = "Files",
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the files section.

        Args:
            title: Section title (default "Files")
            expanded: Initial expanded state (default False per user preference)
            parent: Optional parent widget
        """
        super().__init__(parent)

        # Create the collapsible section
        self._section = CollapsibleSection(title, expanded=expanded, parent=self)
        _ = self._section.expanded_changed.connect(self.expanded_changed)

        # Create the files tab widget
        self._files_tab = FilesTabWidget(parent=self)
        _ = self._files_tab.file_selected.connect(self.file_selected)
        _ = self._files_tab.file_open_requested.connect(self.file_open_requested)

        # Set up layout
        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Add files tab as content
        self._section.set_content(self._files_tab)
        layout.addWidget(self._section)

    def set_files(self, files_by_type: dict[FileType, list[SceneFile]]) -> None:
        """Set files for all tabs and update header count.

        Args:
            files_by_type: Dict mapping FileType to list of SceneFiles
        """
        self._files_tab.set_files(files_by_type)
        self._update_count()

    def clear_files(self) -> None:
        """Clear all files from all tabs."""
        self._files_tab.clear_files()
        self._update_count()

    def _update_count(self) -> None:
        """Update the header with total file count."""
        count = self._files_tab.get_total_file_count()
        if count > 0:
            self._section.set_count(count)
        else:
            self._section.set_count(None)

    def set_expanded(self, expanded: bool) -> None:
        """Set the expanded state.

        Args:
            expanded: True to expand, False to collapse
        """
        self._section.set_expanded(expanded)

    def is_expanded(self) -> bool:
        """Return whether the section is expanded."""
        return self._section.is_expanded()

    def get_selected_file(self) -> SceneFile | None:
        """Get the currently selected file.

        Returns:
            Selected SceneFile or None
        """
        return self._files_tab.get_selected_file()

    def set_current_tab(self, file_type: FileType) -> None:
        """Set the current tab.

        Args:
            file_type: The file type tab to show
        """
        self._files_tab.set_current_tab(file_type)

    def get_total_file_count(self) -> int:
        """Get total count of files across all tabs.

        Returns:
            Total number of files
        """
        return self._files_tab.get_total_file_count()

    def set_default_file(self, file_type: FileType, file: SceneFile | None) -> None:
        """Set the default file indicator for a file type.

        Args:
            file_type: The file type (tab) to update
            file: The file to mark as default, or None to clear
        """
        self._files_tab.set_default_file(file_type, file)

    def clear_default_files(self) -> None:
        """Clear all default file indicators."""
        for file_type in FileType:
            self._files_tab.set_default_file(file_type, None)
