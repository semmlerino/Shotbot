"""DCC accordion widget containing collapsible DCC launch sections.

Provides a vertical stack of DCCSection widgets, each representing a
different DCC application (3DEqualizer, Nuke, Maya, RV). Supports
user-controlled expansion where multiple sections can be open simultaneously.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)

from ui.qt_widget_mixin import QtWidgetMixin

from .dcc_config import DEFAULT_DCC_CONFIGS
from .dcc_section_file import FileDCCSection
from .dcc_section_rv import create_dcc_section


if TYPE_CHECKING:
    from managers.settings_manager import SettingsManager
    from type_definitions import Shot

    from .dcc_config import DCCConfig
    from .dcc_section_base import BaseDCCSection
    from .scene_file import SceneFile


@final
class DCCAccordion(QtWidgetMixin, QWidget):
    """Accordion container for DCC launch sections.

    Contains multiple DCCSection widgets stacked vertically. Supports
    user-controlled expansion (multiple sections can be open at once).

    Attributes:
        launch_requested: Signal(str, object) - app_name, options dict
        file_selected: Signal(str, object) - app_name, SceneFile

    """

    launch_requested = Signal(str, object)  # app_name, options
    file_selected = Signal(str, object)  # app_name, SceneFile

    def __init__(
        self,
        configs: list[DCCConfig] | None = None,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the DCC accordion.

        Args:
            configs: List of DCC configurations. Uses defaults if None.
            settings_manager: Optional settings manager for persisting UI state.
            parent: Optional parent widget.

        """
        super().__init__(parent)
        self._configs = configs or DEFAULT_DCC_CONFIGS
        self._settings_manager = settings_manager
        self._sections: dict[str, BaseDCCSection] = {}
        self._current_shot: Shot | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the accordion UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Create a section for each DCC
        for config in self._configs:
            section = create_dcc_section(
                config,
                settings_manager=self._settings_manager,
                parent=self,
            )
            # Sections start disabled (via set_enabled) until shot is set

            # Forward signals
            _ = section.launch_requested.connect(self._on_section_launch)

            # Forward file_selected signal with app name (FileDCCSection only)
            if isinstance(section, FileDCCSection):

                def make_file_handler(
                    name: str,
                ) -> Callable[[SceneFile], None]:
                    def on_file_selected(f: SceneFile) -> None:
                        self._on_section_file_selected(name, f)

                    return on_file_selected

                _ = section.file_selected.connect(make_file_handler(config.name))

            # Restore expanded state from settings if available
            if self._settings_manager is not None:
                expanded = self._settings_manager.ui.is_section_expanded(config.name)
                section.set_expanded(expanded)

                # Save expanded state changes to settings
                def make_save_handler(
                    settings_mgr: SettingsManager,
                    name: str,
                ) -> Callable[[str, bool], None]:
                    def save_expanded(_app_name: str, is_expanded: bool) -> None:
                        settings_mgr.ui.set_section_expanded(name, is_expanded)

                    return save_expanded

                _ = section.expanded_changed.connect(
                    make_save_handler(self._settings_manager, config.name)
                )

            layout.addWidget(section)
            self._sections[config.name] = section

        layout.addStretch()

    def _on_section_launch(
        self, app_name: str, options: dict[str, bool | str | None]
    ) -> None:
        """Handle launch request from a section.

        Args:
            app_name: Name of the app to launch
            options: Launch options dict

        """
        self.launch_requested.emit(app_name, options)

    def _on_section_file_selected(self, app_name: str, file: SceneFile) -> None:
        """Handle file selection from a section.

        Args:
            app_name: Name of the app section
            file: The selected SceneFile

        """
        self.file_selected.emit(app_name, file)

    def set_shot(self, shot: Shot | None) -> None:
        """Update for the selected shot.

        Enables/disables all sections based on whether a shot is selected.

        Args:
            shot: Currently selected shot, or None

        """
        self._current_shot = shot
        enabled = shot is not None

        for section in self._sections.values():
            section.set_enabled(enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all sections.

        Args:
            enabled: True to enable, False to disable

        """
        for section in self._sections.values():
            section.set_enabled(enabled)

    def set_search_pending(self, pending: bool) -> None:
        """Set whether an async file search is in progress.

        Propagates to all sections.

        Args:
            pending: True if async search is in progress

        """
        for section in self._sections.values():
            section.set_search_pending(pending)

    def set_available_plates(self, plates: list[str]) -> None:
        """Update plate selector in all sections.

        Args:
            plates: List of plate names (e.g., ['FG01', 'BG01'])

        """
        for section in self._sections.values():
            section.set_available_plates(plates)

    def set_version_info(
        self,
        app_name: str,
        version: str | None,
        age: str | None = None,
    ) -> None:
        """Set version info for a specific DCC section.

        Args:
            app_name: App name (e.g., "3de", "nuke")
            version: Version string (e.g., "v005") or None
            age: Age string (e.g., "21m ago") or None

        """
        section = self._sections.get(app_name)
        if section:
            section.set_version_info(version, age)

    def clear_version_info(self) -> None:
        """Clear version info from all sections."""
        for section in self._sections.values():
            section.set_version_info(None, None)

    def get_section(self, app_name: str) -> BaseDCCSection | None:
        """Get a specific DCC section by app name.

        Args:
            app_name: App name (e.g., "3de", "nuke")

        Returns:
            The BaseDCCSection or None if not found

        """
        return self._sections.get(app_name)

    def set_section_expanded(self, app_name: str, expanded: bool) -> None:
        """Set expansion state of a specific section.

        Args:
            app_name: App name (e.g., "3de", "nuke")
            expanded: True to expand, False to collapse

        """
        section = self._sections.get(app_name)
        if section:
            section.set_expanded(expanded)

    def expand_all(self) -> None:
        """Expand all sections."""
        for section in self._sections.values():
            section.set_expanded(True)

    def collapse_all(self) -> None:
        """Collapse all sections."""
        for section in self._sections.values():
            section.set_expanded(False)

    def get_expanded_sections(self) -> list[str]:
        """Get names of currently expanded sections.

        Returns:
            List of app names that are currently expanded

        """
        return [
            name for name, section in self._sections.items() if section.is_expanded()
        ]

    def get_options(self, app_name: str) -> dict[str, bool | str | None] | None:
        """Get launch options for a specific DCC.

        Args:
            app_name: App name (e.g., "3de", "nuke")

        Returns:
            Options dict or None if section not found

        """
        section = self._sections.get(app_name)
        if section:
            return section.get_options()
        return None

    def set_launch_description(
        self, app_name: str, version: str | None, plate: str | None = None
    ) -> None:
        """Set launch description for a specific DCC section.

        Args:
            app_name: App name (e.g., "3de", "nuke")
            version: Version string (e.g., "v005") or None to hide
            plate: Plate name (e.g., "FG01") or None

        """
        section = self._sections.get(app_name)
        if section:
            section.set_launch_description(version, plate)

    def get_selected_plate(self, app_name: str) -> str | None:
        """Get the selected plate for a specific DCC section.

        Args:
            app_name: App name (e.g., "3de", "nuke")

        Returns:
            Selected plate name or None

        """
        section = self._sections.get(app_name)
        if section:
            return section.get_selected_plate()
        return None

    # ========== File Routing Methods ==========

    def set_files_for_dcc(self, app_name: str, files: list[SceneFile]) -> None:
        """Set files for a specific DCC section.

        Args:
            app_name: App name (e.g., "3de", "nuke", "maya")
            files: List of scene files to display

        """
        section = self._sections.get(app_name)
        if isinstance(section, FileDCCSection):
            section.set_files(files)

    def set_default_file_for_dcc(self, app_name: str, file: SceneFile | None) -> None:
        """Set the default file indicator for a DCC section.

        Args:
            app_name: App name (e.g., "3de", "nuke", "maya")
            file: The file to mark as default, or None to clear

        """
        section = self._sections.get(app_name)
        if isinstance(section, FileDCCSection):
            section.set_default_file(file)

    def get_selected_file(self, app_name: str) -> SceneFile | None:
        """Get the selected file for a specific DCC.

        Args:
            app_name: App name (e.g., "3de", "nuke", "maya")

        Returns:
            Selected SceneFile or None

        """
        section = self._sections.get(app_name)
        if isinstance(section, FileDCCSection):
            return section.get_selected_file()
        return None
