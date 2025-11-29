"""Right panel widget with DCC accordion containing integrated file sections.

This is the composition root for the right panel UI, containing only:
- DCCAccordion: Collapsible DCC sections with embedded file lists

Each DCC section (3DE, Maya, Nuke) has its own integrated files sub-section.
RV has no files section since it doesn't have scene files.

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
from qt_widget_mixin import QtWidgetMixin
from scene_file import FileType, SceneFile
from shot_file_finder import ShotFileFinder


if TYPE_CHECKING:
    from settings_manager import SettingsManager
    from shot_model import Shot


@final
class RightPanelWidget(QtWidgetMixin, QWidget):
    """Composition root for the right panel.

    Layout:
    - DCCAccordion with collapsible sections for each DCC
    - Each DCC section (3DE, Maya, Nuke) has embedded files sub-section
    - RV section has no files (no scene files for playback)

    Signals:
        launch_requested: Signal(str, dict) - app_name, options
    """

    launch_requested = Signal(str, dict)  # app_name, options

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

        # DCC Accordion (only main widget - each section has embedded files)
        self._dcc_accordion = DCCAccordion(
            settings_manager=self._settings_manager,
            parent=self,
        )
        content_layout.addWidget(self._dcc_accordion)

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
        # DCC accordion signals - route through handler to inject selected file
        _ = self._dcc_accordion.launch_requested.connect(self._on_dcc_launch)
        _ = self._dcc_accordion.file_selected.connect(self._on_file_selected_from_dcc)

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
        # Get selected file from the DCC section itself
        selected_file = self._dcc_accordion.get_selected_file(app_name)
        if selected_file:
            options["selected_file"] = selected_file
        self.launch_requested.emit(app_name, options)

    def _on_file_selected_from_dcc(
        self, app_name: str, scene_file: SceneFile
    ) -> None:
        """Handle file selection from a DCC section.

        Stores the selected file for later use in launch options.

        Args:
            app_name: The DCC app name (e.g., "3de", "nuke", "maya")
            scene_file: The selected scene file
        """
        self._selected_files[app_name] = scene_file

    def set_shot(self, shot: Shot | None, *, discover_files: bool = True) -> None:
        """Set the current shot.

        Updates all child widgets with the new shot information.
        Optionally discovers and displays scene files for the shot.

        Args:
            shot: The shot to display, or None to clear
            discover_files: If True, discover files synchronously (default).
                          If False, skip file discovery (caller will provide files via set_files).
        """
        # Clear file selections when shot changes (files are shot-specific)
        if shot != self._current_shot:
            for app_name in self._selected_files:
                self._selected_files[app_name] = None
            # Clear launch descriptions
            for app_name in ["3de", "nuke", "maya"]:
                self._dcc_accordion.set_launch_description(app_name, None)

        self._current_shot = shot

        # Update DCC accordion (handles enabling/disabling sections)
        self._dcc_accordion.set_shot(shot)

        # Discover and display files (unless caller will provide them)
        if shot is not None and discover_files:
            try:
                files_by_type = self._file_finder.find_all_files(shot)
                self.set_files(files_by_type)
            except Exception as e:
                self.logger.error(f"Error discovering files for {shot.full_name}: {e}")
                self._clear_files()

            # Discover sequences for RV section
            self.discover_rv_sequences(shot)
        elif shot is None:
            self._clear_files()
            # Clear RV sequences when shot is cleared
            self._clear_rv_sequences()

    def set_files(self, files_by_type: dict[FileType, list[SceneFile]]) -> None:
        """Set scene files for display in per-DCC embedded sections.

        Routes files to the appropriate DCC sections.

        Args:
            files_by_type: Dict mapping FileType to list of SceneFiles
        """
        # Map FileType to app names
        file_type_to_app = {
            FileType.THREEDE: "3de",
            FileType.MAYA: "maya",
            FileType.NUKE: "nuke",
        }

        for file_type, files in files_by_type.items():
            app_name = file_type_to_app.get(file_type)
            if app_name:
                # Route files to the DCC section (handles embedded display)
                self._dcc_accordion.set_files_for_dcc(app_name, files)

                if files:
                    # Track latest file for this DCC
                    latest = files[0]
                    self._selected_files[app_name] = latest
                    # Update version info in header
                    version = f"v{latest.version:03d}" if latest.version else None
                    self._dcc_accordion.set_version_info(
                        app_name, version, latest.relative_age
                    )
                else:
                    # Clear when no files
                    self._selected_files[app_name] = None
                    self._dcc_accordion.set_version_info(app_name, None)

    def _clear_files(self) -> None:
        """Clear files from all DCC sections."""
        for app_name in ["3de", "nuke", "maya"]:
            self._dcc_accordion.set_files_for_dcc(app_name, [])
            self._selected_files[app_name] = None
            self._dcc_accordion.set_version_info(app_name, None)

    def discover_rv_sequences(self, shot: Shot) -> None:
        """Discover Maya playblasts and Nuke renders for RV section.

        Args:
            shot: The current shot
        """
        try:
            from user_sequence_finder import UserSequenceFinder

            rv_section = self._dcc_accordion.get_section("rv")
            if rv_section is None:
                self.logger.warning("RV section not found - cannot display sequences")
                return

            self.logger.info(f"Discovering RV sequences for shot: {shot.workspace_path}")

            # Discover sequences for current user
            playblasts = UserSequenceFinder.find_maya_playblasts(shot.workspace_path)
            renders = UserSequenceFinder.find_nuke_renders(shot.workspace_path)

            # Update RV section
            rv_section.set_playblast_sequences(playblasts)
            rv_section.set_render_sequences(renders)

            self.logger.info(
                f"RV discovery complete: {len(playblasts)} playblast(s), {len(renders)} render(s)"
            )

        except Exception as e:
            self.logger.error(f"Error discovering sequences for RV: {e}", exc_info=True)

    def _clear_rv_sequences(self) -> None:
        """Clear sequences from RV section."""
        rv_section = self._dcc_accordion.get_section("rv")
        if rv_section is not None:
            rv_section.set_playblast_sequences([])
            rv_section.set_render_sequences([])

    def set_available_plates(self, plates: list[str]) -> None:
        """Set available plates for plate selectors.

        Args:
            plates: List of plate names (e.g., ['FG01', 'BG01'])
        """
        self._dcc_accordion.set_available_plates(plates)

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

    def get_dcc_options(self, app_name: str) -> dict[str, bool | str | None] | None:
        """Get launch options for a specific DCC.

        Args:
            app_name: The DCC app name

        Returns:
            Options dict or None if not found
        """
        return self._dcc_accordion.get_options(app_name)

    def get_selected_file(self, app_name: str) -> SceneFile | None:
        """Get the currently selected file for a specific DCC.

        Args:
            app_name: The DCC app name (e.g., "3de", "nuke", "maya")

        Returns:
            Selected SceneFile or None
        """
        return self._dcc_accordion.get_selected_file(app_name)

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
