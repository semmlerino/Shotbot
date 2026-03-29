"""DCC section for file-based applications (3DEqualizer, Maya, Nuke).

Extends BaseDCCSection with an embedded DCCFileTable for browsing scene files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from PySide6.QtCore import Signal
from typing_extensions import override

from .dcc_file_table import DCCFileTable
from .dcc_section_base import BaseDCCSection


if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from managers.settings_manager import SettingsManager

    from .dcc_config import DCCConfig
    from .scene_file import SceneFile


@final
class FileDCCSection(BaseDCCSection):
    """DCC section for file-based DCCs: 3DEqualizer, Maya, Nuke.

    Adds an embedded DCCFileTable for browsing scene files.

    Attributes:
        file_selected: Signal(object) - emits SceneFile when user clicks a file

    """

    file_selected = Signal(object)  # SceneFile

    def __init__(
        self,
        config: DCCConfig,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the FileDCCSection.

        Args:
            config: Configuration for this DCC
            settings_manager: Settings manager for height persistence
            parent: Optional parent widget

        """
        self._dcc_file_table: DCCFileTable  # Will be set in _setup_ui
        super().__init__(config, settings_manager=settings_manager, parent=parent)

    @override
    def _setup_ui(self) -> None:
        """Set up UI, adding the file table after base chrome."""
        super()._setup_ui()

        self._dcc_file_table = DCCFileTable(
            dcc_name=self.config.name,
            display_name=self.config.display_name,
            accent_color=self.config.color,
            settings_manager=self._settings_manager,
            parent=self,
        )
        _ = self._dcc_file_table.file_selected.connect(self._on_embedded_file_selected)
        _ = self._dcc_file_table.launch_file_requested.connect(
            self._on_embedded_file_launch_requested
        )
        self._content_layout.addWidget(self._dcc_file_table)

    @override
    def _apply_styles(self) -> None:
        """Apply styles, including delegating to the file table."""
        super()._apply_styles()
        # Guard: _dcc_file_table may not exist yet during super().__init__ → _setup_ui
        if hasattr(self, "_dcc_file_table"):
            self._dcc_file_table.apply_styles()

    # ========== Embedded File Table Signal Handlers ==========

    def _on_embedded_file_selected(self, file: SceneFile) -> None:
        """Handle file_selected from embedded DCCFileTable.

        Updates the launch description and re-emits file_selected on FileDCCSection.

        Args:
            file: The selected SceneFile.

        """
        self._update_launch_button_from_file(file)
        self.file_selected.emit(file)

    def _on_embedded_file_launch_requested(self, file: SceneFile) -> None:
        """Handle launch_file_requested from embedded DCCFileTable.

        Updates the launch description and emits launch_requested on FileDCCSection.

        Args:
            file: The SceneFile the user wants to open.

        """
        self._update_launch_button_from_file(file)
        options = self.get_options()
        self.launch_requested.emit(self.config.name, options)

    def _update_launch_button_from_file(self, file: SceneFile) -> None:
        """Update launch button description from selected file.

        Args:
            file: The selected scene file.

        """
        if file.version is not None:
            version_str = f"v{file.version:03d}"
            plate = self.get_selected_plate()
            self.set_launch_description(version_str, plate)

    def set_files(self, files: list[SceneFile]) -> None:
        """Set files for the embedded files sub-section.

        Args:
            files: List of scene files to display.

        """
        self._dcc_file_table.set_files(files)
        # Update launch description from auto-selected first file
        if files:
            self._update_launch_button_from_file(files[0])

    def get_selected_file(self) -> SceneFile | None:
        """Get the currently selected file from the embedded table.

        Returns:
            Selected SceneFile or None.

        """
        return self._dcc_file_table.get_selected_file()

    def set_default_file(self, file: SceneFile | None) -> None:
        """Mark a file as the default (shows arrow indicator).

        Args:
            file: The file to mark as default, or None to clear.

        """
        self._dcc_file_table.set_default_file(file)
        if file is not None:
            self._update_launch_button_from_file(file)
