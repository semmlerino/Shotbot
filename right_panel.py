"""Right panel widget composing shot info, quick launch, DCC accordion, and files.

This is the composition root for the redesigned right panel UI. It brings together:
- ShotHeader: Compact shot info with DCC status strip
- QuickLaunchBar: Labeled pill buttons with visible shortcuts
- DCCAccordion: Collapsible DCC launch sections
- FilesSection: Collapsible files browser

The panel handles coordination between child widgets and provides a unified
interface for the main window to interact with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dcc_accordion import DCCAccordion
from files_section import FilesSection
from qt_widget_mixin import QtWidgetMixin
from quick_launch_bar import QuickLaunchBar
from scene_file import FileType, SceneFile
from shot_file_finder import ShotFileFinder
from shot_header import ShotHeader


if TYPE_CHECKING:
    from settings_manager import SettingsManager
    from shot_model import Shot


@final
class RightPanelWidget(QtWidgetMixin, QWidget):
    """Composition root for the redesigned right panel.

    Layout (top to bottom):
    1. Shot Header - shot name, show/sequence, path, DCC status
    2. Quick Launch Bar - labeled pill buttons for fast launching
    3. DCC Accordion - collapsible sections for each DCC
    4. Files Section - collapsible tabbed files browser

    Signals:
        launch_requested: Signal(str, dict) - app_name, options
        file_open_requested: Signal(SceneFile) - scene file to open
        path_copy_requested: Signal() - workspace path copy
    """

    launch_requested = Signal(str, dict)  # app_name, options
    file_open_requested = Signal(object)  # SceneFile
    path_copy_requested = Signal()

    def __init__(
        self,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the right panel widget.

        Args:
            settings_manager: Optional settings manager for persisting UI state
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._settings_manager = settings_manager
        self._current_shot: Shot | None = None
        self._file_finder = ShotFileFinder()

        # Per-DCC selected file state (user clicks file row to set)
        self._selected_files: dict[str, SceneFile | None] = {
            "3de": None,
            "nuke": None,
            "maya": None,
        }

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Set up the panel UI."""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scrollable content area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1a1a1a;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background-color: #444;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #555;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

        # Content widget
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(12)

        # 1. Shot Header
        self._shot_header = ShotHeader(parent=self)
        content_layout.addWidget(self._shot_header)

        # 2. Quick Launch Bar
        self._quick_launch = QuickLaunchBar(parent=self)
        content_layout.addWidget(self._quick_launch)

        # 3. DCC Accordion
        self._dcc_accordion = DCCAccordion(
            settings_manager=self._settings_manager,
            parent=self,
        )
        content_layout.addWidget(self._dcc_accordion)

        # 4. Files Section (restore expanded state from settings if available)
        files_expanded = False
        if self._settings_manager is not None:
            files_expanded = self._settings_manager.is_section_expanded("files")
        self._files_section = FilesSection(
            title="Files",
            expanded=files_expanded,
            parent=self,
        )
        content_layout.addWidget(self._files_section)

        # Stretch at bottom
        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

        # Overall panel styling
        self.setStyleSheet("""
            RightPanelWidget {
                background-color: #1a1a1a;
                border-left: 1px solid #333;
            }
        """)

    def _connect_signals(self) -> None:
        """Connect internal widget signals."""
        # Shot header signals
        _ = self._shot_header.path_copy_requested.connect(self.path_copy_requested)

        # Quick launch signals - forward with default options
        _ = self._quick_launch.launch_requested.connect(self._on_quick_launch)

        # DCC accordion signals - route through handler to inject selected file
        _ = self._dcc_accordion.launch_requested.connect(self._on_dcc_launch)

        # Files section signals
        _ = self._files_section.file_open_requested.connect(self.file_open_requested)
        _ = self._files_section.file_selected.connect(self._on_file_selected)

        # Save Files section expanded state to settings
        if self._settings_manager is not None:
            settings = self._settings_manager  # Capture for lambda

            def save_files_expanded(expanded: bool) -> None:
                settings.set_section_expanded("files", expanded)

            _ = self._files_section.expanded_changed.connect(save_files_expanded)

    def _on_quick_launch(self, app_name: str) -> None:
        """Handle quick launch request.

        Gets options from the corresponding DCC section, injects selected file,
        and emits launch signal.

        Args:
            app_name: Name of the app to launch
        """
        base_options = self._dcc_accordion.get_options(app_name) or {}
        # Create mutable options dict that can hold SceneFile
        options: dict[str, Any] = dict(base_options)
        # Inject selected file if available
        selected_file = self._selected_files.get(app_name)
        if selected_file:
            options["selected_file"] = selected_file
        self.launch_requested.emit(app_name, options)

    def _on_dcc_launch(
        self, app_name: str, base_options: dict[str, bool | str | None]
    ) -> None:
        """Handle launch from DCC accordion section.

        Injects selected file into options before forwarding.

        Args:
            app_name: Name of the app to launch
            base_options: Options from the DCC section
        """
        # Create mutable options dict that can hold SceneFile
        options: dict[str, Any] = dict(base_options)
        # Inject selected file if available
        selected_file = self._selected_files.get(app_name)
        if selected_file:
            options["selected_file"] = selected_file
        self.launch_requested.emit(app_name, options)

    def _on_file_selected(self, scene_file: SceneFile) -> None:
        """Handle user clicking a file row - set as default for that DCC.

        Args:
            scene_file: The selected scene file
        """
        app_name = self._file_type_to_app(scene_file.file_type)
        if app_name:
            self._selected_files[app_name] = scene_file
            self._update_default_indicators(app_name, scene_file)

    def _file_type_to_app(self, file_type: FileType) -> str | None:
        """Map FileType to app name string.

        Args:
            file_type: The file type to map

        Returns:
            App name string or None if not mappable
        """
        return {
            FileType.THREEDE: "3de",
            FileType.MAYA: "maya",
            FileType.NUKE: "nuke",
        }.get(file_type)

    def _update_default_indicators(
        self, app_name: str, file: SceneFile | None
    ) -> None:
        """Update all UI components when selected default changes.

        Args:
            app_name: The app name (e.g., "3de", "nuke", "maya")
            file: The selected file, or None to clear
        """
        if file:
            version = f"v{file.version:03d}" if file.version else None
            plate = self._dcc_accordion.get_selected_plate(app_name)

            # Update Files table arrow indicator
            self._files_section.set_default_file(file.file_type, file)

            # Update DCC launch description ("Opens: v005 | FG01")
            self._dcc_accordion.set_launch_description(app_name, version, plate)

            # Update Quick Launch tooltip
            self._quick_launch.set_latest_version(app_name, version)
        else:
            # Clear indicators
            file_type_map = {
                "3de": FileType.THREEDE,
                "maya": FileType.MAYA,
                "nuke": FileType.NUKE,
            }
            file_type = file_type_map.get(app_name)
            if file_type:
                self._files_section.set_default_file(file_type, None)
            self._dcc_accordion.set_launch_description(app_name, None)

    def set_shot(self, shot: Shot | None) -> None:
        """Set the current shot.

        Updates all child widgets with the new shot information.
        Also discovers and displays scene files for the shot.

        Args:
            shot: The shot to display, or None to clear
        """
        # Clear file selections when shot changes (files are shot-specific)
        if shot != self._current_shot:
            for app_name in self._selected_files:
                self._selected_files[app_name] = None
            self._files_section.clear_default_files()
            # Also clear launch descriptions
            for app_name in ["3de", "nuke", "maya"]:
                self._dcc_accordion.set_launch_description(app_name, None)

        self._current_shot = shot

        # Update all child widgets
        self._shot_header.set_shot(shot)
        self._quick_launch.set_shot(shot)
        self._dcc_accordion.set_shot(shot)

        # Discover and display files
        if shot is not None:
            try:
                files_by_type = self._file_finder.find_all_files(shot)
                self.set_files(files_by_type)
            except Exception as e:
                self.logger.error(f"Error discovering files for {shot.full_name}: {e}")
                self._files_section.clear_files()
        else:
            self._files_section.clear_files()

    def set_files(self, files_by_type: dict[FileType, list[SceneFile]]) -> None:
        """Set scene files for display.

        Updates both the files section and the shot header DCC status.

        Args:
            files_by_type: Dict mapping FileType to list of SceneFiles
        """
        # Update files section
        self._files_section.set_files(files_by_type)

        # Update shot header DCC status
        self._shot_header.update_from_files(files_by_type)

        # Update version info in quick launch tooltips
        # Map FileType to app names for when there are no files
        file_type_to_app = {
            FileType.THREEDE: "3de",
            FileType.MAYA: "maya",
            FileType.NUKE: "nuke",
        }

        for file_type, files in files_by_type.items():
            if files:
                latest = files[0]
                app_name = latest.app_name
                version = f"v{latest.version:03d}" if latest.version else None
                self._quick_launch.set_latest_version(app_name, version)
                self._dcc_accordion.set_version_info(app_name, version, latest.relative_age)
            else:
                # Clear version info when no files
                app_name = file_type_to_app.get(file_type)
                if app_name:
                    self._quick_launch.set_latest_version(app_name, None)
                    self._dcc_accordion.set_version_info(app_name, None)

    def set_available_plates(self, plates: list[str]) -> None:
        """Set available plates for plate selectors.

        Args:
            plates: List of plate names (e.g., ['FG01', 'BG01'])
        """
        self._dcc_accordion.set_available_plates(plates)

    def set_empty_message(self, message: str) -> None:
        """Set the message shown when no shot is selected.

        Args:
            message: The empty state message
        """
        self._shot_header.set_empty_message(message)

    def expand_dcc_section(self, app_name: str) -> None:
        """Expand a specific DCC section.

        Args:
            app_name: The DCC app name (e.g., "3de", "nuke")
        """
        self._dcc_accordion.set_section_expanded(app_name, True)

    def collapse_dcc_section(self, app_name: str) -> None:
        """Collapse a specific DCC section.

        Args:
            app_name: The DCC app name
        """
        self._dcc_accordion.set_section_expanded(app_name, False)

    def set_files_expanded(self, expanded: bool) -> None:
        """Set the files section expansion state.

        Args:
            expanded: True to expand, False to collapse
        """
        self._files_section.set_expanded(expanded)

    def get_dcc_options(self, app_name: str) -> dict[str, bool | str | None] | None:
        """Get launch options for a specific DCC.

        Args:
            app_name: The DCC app name

        Returns:
            Options dict or None if not found
        """
        return self._dcc_accordion.get_options(app_name)

    def get_selected_file(self) -> SceneFile | None:
        """Get the currently selected file from the files section.

        Returns:
            Selected SceneFile or None
        """
        return self._files_section.get_selected_file()

    # Keyboard shortcut handlers
    def handle_shortcut(self, key: str) -> bool:
        """Handle a keyboard shortcut press.

        Args:
            key: The pressed key (e.g., "3", "N", "M", "R")

        Returns:
            True if shortcut was handled, False otherwise
        """
        if self._current_shot is None:
            return False

        # Map keys to app names
        key_to_app = {
            "3": "3de",
            "n": "nuke",
            "m": "maya",
            "r": "rv",
        }

        app_name = key_to_app.get(key.lower())
        if app_name:
            options = self._dcc_accordion.get_options(app_name) or {}
            self.launch_requested.emit(app_name, options)
            return True

        return False
