"""DCC section widget for individual DCC application launching.

Extracted and improved from AppLauncherSection. Provides a collapsible
section with launch button, options checkboxes, and plate selector.
Shows version info in collapsed header for quick reference.

VFX Glossary:
    DCC — Digital Content Creation application (Maya, Nuke, 3DEqualizer, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from managers.settings_manager import SettingsManager
    from ui.files_tab_widget import FileTableModel

from PySide6.QtCore import QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qt_widget_mixin import QtWidgetMixin
from scene_file import FileType, ImageSequence, SceneFile
from ui.design_system import (
    darken_color,
    design_system,
    get_tinted_background,
    lighten_color,
)

from .dcc_file_table import DCCFileTable
from .dcc_sequence_table import DCCSequenceTable


@final
@dataclass
class DCCConfig:
    """Configuration for a DCC section."""

    name: str  # Internal name: "3de", "nuke", "maya", "rv"
    display_name: str  # Display name: "3DEqualizer", "Nuke", etc.
    color: str  # Accent color hex
    shortcut: str  # Keyboard shortcut: "3", "N", "M", "R"
    tooltip: str = ""
    checkboxes: list[CheckboxConfig] | None = None
    has_plate_selector: bool = True
    has_files_section: bool = False  # Whether to show embedded files sub-section
    file_type: FileType | None = None  # Which FileType this DCC uses (None = no files)


@final
@dataclass
class CheckboxConfig:
    """Configuration for a checkbox option."""

    label: str
    tooltip: str
    key: str  # Settings key for persistence
    default: bool = False


# Default DCC configurations
DEFAULT_DCC_CONFIGS = [
    DCCConfig(
        name="3de",
        display_name="3DEqualizer",
        color="#2b4d6f",
        shortcut="3",
        tooltip="Launch 3DE for matchmove/tracking",
        checkboxes=[
            CheckboxConfig(
                label="Open latest 3DE scene (when available)",
                tooltip="Automatically open the latest scene file from the workspace",
                key="open_latest_threede",
                default=True,
            )
        ],
        has_files_section=True,
        file_type=FileType.THREEDE,
    ),
    DCCConfig(
        name="maya",
        display_name="Maya",
        color="#4d2b5d",
        shortcut="M",
        tooltip="Launch Maya for 3D work",
        checkboxes=[
            CheckboxConfig(
                label="Open latest Maya scene (when available)",
                tooltip="Automatically open the latest scene file from the workspace",
                key="open_latest_maya",
                default=True,
            )
        ],
        has_files_section=True,
        file_type=FileType.MAYA,
    ),
    DCCConfig(
        name="nuke",
        display_name="Nuke",
        color="#5d4d2b",
        shortcut="N",
        tooltip="Launch Nuke for compositing",
        checkboxes=[
            CheckboxConfig(
                label="Open latest scene",
                tooltip="Open the most recent Nuke script from workspace",
                key="open_latest_scene",
                default=True,
            ),
            CheckboxConfig(
                label="Create new file",
                tooltip="Always create a new version of the Nuke script",
                key="create_new_file",
                default=False,
            ),
        ],
        has_files_section=True,
        file_type=FileType.NUKE,
    ),
    DCCConfig(
        name="rv",
        display_name="RV",
        color="#2b5d4d",
        shortcut="R",
        tooltip="Launch RV for playback and review",
        has_files_section=False,
        file_type=None,
    ),
]


@final
class DCCSection(QtWidgetMixin, QWidget):
    """Collapsible DCC section with launch options.

    Shows a header bar with:
    - Expand/collapse indicator
    - DCC name
    - Version info (when available)
    - Keyboard shortcut badge

    Expands to show:
    - Launch button
    - Option checkboxes
    - Plate selector (if applicable)

    Attributes:
        launch_requested: Signal(str, object) - app_name, options dict
        expanded_changed: Signal(str, bool) - app_name, is_expanded
        file_selected: Signal(object) - emits SceneFile when user clicks a file

    """

    launch_requested = Signal(str, object)  # app_name, options
    expanded_changed = Signal(str, bool)  # app_name, is_expanded
    file_selected = Signal(object)  # SceneFile

    def __init__(
        self,
        config: DCCConfig,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the DCC section.

        Args:
            config: Configuration for this DCC
            settings_manager: Settings manager for height persistence
            parent: Optional parent widget

        """
        super().__init__(parent)
        self.config = config
        self._settings_manager = settings_manager
        self._expanded = False
        self._version_info: str | None = None
        self._age_info: str | None = None
        self._launch_in_progress = False
        self._should_be_enabled = False
        self._original_button_text = ""
        self._search_pending = False  # True while async file search is in progress

        # UI components
        self._checkboxes: dict[str, QCheckBox] = {}
        self._plate_selector: QComboBox | None = None

        # Composed sub-widgets (created in _setup_ui if applicable)
        self._dcc_file_table: DCCFileTable | None = None
        self._dcc_sequence_table: DCCSequenceTable | None = None

        # Store references for dynamic styling
        self._plate_label: QLabel | None = None

        self._setup_ui()

        # Connect to scale changes for live updates
        _ = design_system.scale_changed.connect(self._apply_styles)

    def _setup_ui(self) -> None:
        """Set up the section UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Container with left accent border
        self._container = QWidget()
        self._container.setStyleSheet(f"""
            QWidget#dccContainer {{
                background-color: {get_tinted_background(self.config.color)};
                border: 1px solid #333;
                border-left: 3px solid {self.config.color};
                border-radius: 4px;
            }}
        """)
        self._container.setObjectName("dccContainer")

        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(8, 6, 8, 6)
        container_layout.setSpacing(4)

        # Header row (always visible)
        header = QPushButton()
        header.setFlat(True)
        header.setStyleSheet("""
            QPushButton {
                border: none;
                text-align: left;
                padding: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        _ = header.clicked.connect(self._toggle_expanded)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Expand/collapse button (visual indicator only)
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._expand_btn.setMaximumSize(18, 18)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(self._expand_btn)

        # DCC name
        self._name_label = QLabel(self.config.display_name)
        header_layout.addWidget(self._name_label)

        # Version info (shown when available)
        self._version_label = QLabel()
        self._version_label.setVisible(False)
        header_layout.addWidget(self._version_label)

        header_layout.addStretch()

        container_layout.addWidget(header)

        # Content widget (hidden when collapsed)
        self._content = QWidget()
        self._content.setVisible(False)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(26, 4, 0, 4)  # Indent under expand arrow
        content_layout.setSpacing(8)

        # Launch button
        self._launch_btn = QPushButton("Launch")
        self._launch_btn.setEnabled(False)
        _ = self._launch_btn.clicked.connect(self._on_launch_clicked)

        tooltip = self.config.tooltip or f"Launch {self.config.display_name}"
        tooltip += f" (Shortcut: {self.config.shortcut.upper()})"
        self._launch_btn.setToolTip(tooltip)
        content_layout.addWidget(self._launch_btn)

        # Launch description label (shows what will be opened)
        self._launch_description = QLabel()
        self._launch_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._launch_description.setVisible(False)
        content_layout.addWidget(self._launch_description)

        # Checkboxes
        if self.config.checkboxes:
            for cb_config in self.config.checkboxes:
                checkbox = QCheckBox(cb_config.label)
                checkbox.setToolTip(cb_config.tooltip)
                checkbox.setChecked(cb_config.default)
                content_layout.addWidget(checkbox)
                self._checkboxes[cb_config.key] = checkbox

        # Plate selector
        if self.config.has_plate_selector:
            plate_row = QHBoxLayout()
            plate_row.setContentsMargins(0, 2, 0, 0)
            plate_row.setSpacing(4)

            self._plate_label = QLabel("Plate:")
            plate_row.addWidget(self._plate_label)

            self._plate_selector = QComboBox()
            self._plate_selector.setEnabled(False)
            self._plate_selector.setPlaceholderText("Select...")
            self._plate_selector.setMinimumWidth(80)
            plate_row.addWidget(self._plate_selector)
            plate_row.addStretch()

            content_layout.addLayout(plate_row)

        # Files sub-section (if configured)
        if self.config.has_files_section:
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
            content_layout.addWidget(self._dcc_file_table)

        # RV sequence sub-sections (Maya Playblasts and Nuke Renders)
        if self.config.name == "rv":
            self._dcc_sequence_table = DCCSequenceTable(
                dcc_name=self.config.name,
                settings_manager=self._settings_manager,
                parent=self,
            )
            _ = self._dcc_sequence_table.sequence_launch_requested.connect(
                self._on_sequence_launch_requested
            )
            content_layout.addWidget(self._dcc_sequence_table)

        container_layout.addWidget(self._content)
        layout.addWidget(self._container)

        # Apply dynamic styles
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply/refresh styles using current design system values."""
        # Expand/collapse button
        self._expand_btn.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
            }
            QToolButton:hover {
                background-color: #333;
                border-radius: 2px;
            }
        """)

        # DCC name label
        self._name_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: {design_system.typography.size_small}px;
                color: {self.config.color};
            }}
        """)

        # Version label
        self._version_label.setStyleSheet(f"""
            QLabel {{
                color: #888;
                font-size: {design_system.typography.size_small}px;
            }}
        """)

        # Launch button
        self._launch_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.config.color};
                color: #ecf0f1;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: {design_system.typography.size_tiny}px;
            }}
            QPushButton:hover {{
                background-color: {lighten_color(self.config.color)};
            }}
            QPushButton:pressed {{
                background-color: {darken_color(self.config.color)};
            }}
            QPushButton:disabled {{
                background-color: #2a2a2a;
                color: #666;
                border: 1px dashed #444;
            }}
        """)

        # Launch description label
        self._launch_description.setStyleSheet(f"""
            QLabel {{
                color: #888;
                font-size: {design_system.typography.size_tiny}px;
                margin-top: -4px;
            }}
        """)

        # Checkboxes
        for checkbox in self._checkboxes.values():
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: #aaa;
                    font-size: {design_system.typography.size_small}px;
                }}
                QCheckBox:hover {{
                    color: #ccc;
                }}
            """)

        # Plate label and selector
        if self._plate_label is not None:
            self._plate_label.setStyleSheet(
                f"QLabel {{ color: #888; font-size: {design_system.typography.size_small}px; }}"
            )

        if self._plate_selector is not None:
            self._plate_selector.setStyleSheet(f"""
                QComboBox {{
                    background-color: #2a2a2a;
                    color: #ecf0f1;
                    border: 1px solid #444;
                    border-radius: 3px;
                    padding: 2px 4px;
                    font-size: {design_system.typography.size_small}px;
                }}
                QComboBox:disabled {{
                    background-color: #1e1e1e;
                    color: #666;
                }}
                QComboBox::drop-down {{ border: none; }}
                QComboBox::down-arrow {{ image: none; }}
            """)

        # Delegate file table styling
        if self._dcc_file_table is not None:
            self._dcc_file_table.apply_styles()

    def _toggle_expanded(self) -> None:
        """Toggle the expanded state."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        """Set the expanded state.

        Args:
            expanded: True to expand, False to collapse

        """
        if self._expanded != expanded:
            self._expanded = expanded
            self._expand_btn.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
            self._content.setVisible(expanded)
            self.expanded_changed.emit(self.config.name, expanded)

    def is_expanded(self) -> bool:
        """Return whether the section is expanded."""
        return self._expanded


    def _on_launch_clicked(self) -> None:
        """Handle launch button click."""
        if self._launch_in_progress:
            return

        self._launch_in_progress = True
        self._original_button_text = self._launch_btn.text()
        self._launch_btn.setEnabled(False)
        self._launch_btn.setText(f"Launching {self.config.display_name}...")

        # Emit with options
        options = self.get_options()
        self.launch_requested.emit(self.config.name, options)

        # Reset after 3 seconds
        QTimer.singleShot(3000, self._safe_reset_button_state)

    def _safe_reset_button_state(self) -> None:
        """Safely reset button state."""
        try:
            if not self.isHidden() and hasattr(self, "_launch_btn"):
                self._reset_button_state()
        except (RuntimeError, AttributeError):
            pass

    def _reset_button_state(self) -> None:
        """Reset button to original state.

        Note: Will not reset if _search_pending is True (async file search in progress).
        """
        # Don't reset while async search is pending - wait for search to complete
        if self._search_pending:
            return

        self._launch_in_progress = False
        self._launch_btn.setText(self._original_button_text)
        self._launch_btn.setEnabled(self._should_be_enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the section.

        Args:
            enabled: True to enable launching

        """
        self._should_be_enabled = enabled
        if not self._launch_in_progress:
            self._launch_btn.setEnabled(enabled)

    def set_search_pending(self, pending: bool) -> None:
        """Set whether an async file search is in progress.

        When *pending* is ``True``, the launch button shows "Scanning…" text
        to indicate background work is happening.  When *pending* becomes
        ``False``, the button is reset to its normal state.

        No-op case: if ``_launch_in_progress`` is ``False`` at the time this
        method is called, neither branch takes effect.  This is intentional —
        the button state is only modified mid-launch so that normal idle state
        is not disrupted by stale search-complete notifications that arrive
        after the user has already cancelled or never started a launch.

        Args:
            pending: True if async search is in progress

        """
        self._search_pending = pending
        if pending:
            # Update button text to show search is in progress
            if self._launch_in_progress:
                self._launch_btn.setText("Scanning...")
        elif self._launch_in_progress:
            # Search complete - reset to normal state
            self._reset_button_state()

    def get_options(self) -> dict[str, bool | str | None]:
        """Get current launch options.

        Returns:
            Dict with checkbox states and selected plate

        """
        options: dict[str, bool | str | None] = {
            key: cb.isChecked() for key, cb in self._checkboxes.items()
        }
        options["selected_plate"] = self.get_selected_plate()
        return options

    def get_checkbox_states(self) -> dict[str, bool]:
        """Get the state of all checkboxes."""
        return {key: cb.isChecked() for key, cb in self._checkboxes.items()}

    def set_available_plates(self, plates: list[str]) -> None:
        """Update plate selector with available plates.

        Args:
            plates: List of plate names (e.g., ['FG01', 'BG01'])

        """
        if not self._plate_selector:
            return

        self._plate_selector.clear()
        if plates:
            self._plate_selector.addItems(plates)
            self._plate_selector.setCurrentIndex(0)  # Pre-select first plate
            self._plate_selector.setEnabled(True)
        else:
            self._plate_selector.setEnabled(False)
            self._plate_selector.setPlaceholderText("No plates available")

    def get_selected_plate(self) -> str | None:
        """Get currently selected plate name."""
        if not self._plate_selector or not self._plate_selector.isEnabled():
            return None
        text = self._plate_selector.currentText()
        return text or None

    def set_version_info(
        self, version: str | None, age: str | None = None
    ) -> None:
        """Set version info displayed in collapsed header.

        Args:
            version: Version string (e.g., "v005") or None
            age: Age string (e.g., "21m ago") or None

        """
        self._version_info = version
        self._age_info = age
        self._update_version_label()

    def _update_version_label(self) -> None:
        """Update the version label display."""
        if self._version_info:
            text = self._version_info
            if self._age_info:
                text += f" | {self._age_info}"
            self._version_label.setText(text)
            self._version_label.setVisible(True)
        else:
            self._version_label.setVisible(False)

    def set_launch_description(
        self, version: str | None, plate: str | None = None
    ) -> None:
        """Update the 'Opens:' description below launch button.

        Args:
            version: Version string (e.g., "v005") or None to hide
            plate: Plate name (e.g., "FG01") or None

        """
        if version:
            parts = [version]
            if plate:
                parts.append(plate)
            self._launch_description.setText(f"Opens: {' | '.join(parts)}")
            self._launch_description.setVisible(True)
        else:
            self._launch_description.setVisible(False)

    # ========== Embedded File Table Signal Handlers ==========

    def _on_embedded_file_selected(self, file: SceneFile) -> None:
        """Handle file_selected from embedded DCCFileTable.

        Updates the launch description and re-emits file_selected on DCCSection.

        Args:
            file: The selected SceneFile.

        """
        self._update_launch_button_from_file(file)
        self.file_selected.emit(file)

    def _on_embedded_file_launch_requested(self, file: SceneFile) -> None:
        """Handle launch_file_requested from embedded DCCFileTable.

        Updates the launch description and emits launch_requested on DCCSection.

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

    # ========== Embedded Sequence Table Signal Handlers ==========

    def _on_sequence_launch_requested(self, sequence: ImageSequence) -> None:
        """Handle sequence_launch_requested from embedded DCCSequenceTable.

        Emits launch_requested with sequence_path in options.

        Args:
            sequence: The ImageSequence to launch.

        """
        options = self.get_options()
        options["sequence_path"] = str(sequence.path)
        self.launch_requested.emit(self.config.name, options)

    # ========== Delegation to DCCFileTable ==========

    @property
    def _files_section(self) -> QWidget | None:  # pyright: ignore[reportUnusedFunction]
        """The files subsection widget (backward compat)."""
        return self._dcc_file_table

    @property
    def _file_table(self) -> QTableView | None:  # pyright: ignore[reportUnusedFunction]
        """The QTableView inside the file table (backward compat)."""
        if self._dcc_file_table is not None:
            return self._dcc_file_table.file_table
        return None

    @property
    def _file_model(self) -> FileTableModel | None:  # pyright: ignore[reportUnusedFunction]
        """The FileTableModel inside the file table (backward compat)."""
        if self._dcc_file_table is not None:
            return self._dcc_file_table.file_model
        return None

    @property
    def _files_header_btn(self) -> QPushButton | None:  # pyright: ignore[reportUnusedFunction]
        """The header button for the files subsection (backward compat)."""
        if self._dcc_file_table is not None:
            return self._dcc_file_table.files_header_btn
        return None

    @property
    def _current_selected_file(self) -> SceneFile | None:
        """Currently selected file (backward compat)."""
        if self._dcc_file_table is not None:
            return self._dcc_file_table.current_selected_file
        return None

    @_current_selected_file.setter
    def _current_selected_file(self, value: SceneFile | None) -> None:
        """Set currently selected file (backward compat)."""
        if self._dcc_file_table is not None:
            self._dcc_file_table.current_selected_file = value

    def set_files(self, files: list[SceneFile]) -> None:
        """Set files for the embedded files sub-section.

        Args:
            files: List of scene files to display.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.set_files(files)
            # Update launch description from auto-selected first file
            if files:
                self._update_launch_button_from_file(files[0])

    def get_selected_file(self) -> SceneFile | None:
        """Get the currently selected file from the embedded table.

        Returns:
            Selected SceneFile or None.

        """
        if self._dcc_file_table is not None:
            return self._dcc_file_table.get_selected_file()
        return None

    def set_default_file(self, file: SceneFile | None) -> None:
        """Mark a file as the default (shows arrow indicator).

        Args:
            file: The file to mark as default, or None to clear.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.set_default_file(file)
            if file is not None:
                self._update_launch_button_from_file(file)

    def set_files_expanded(self, expanded: bool) -> None:
        """Set the files sub-section expanded state.

        Args:
            expanded: True to expand, False to collapse.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.set_files_expanded(expanded)

    def is_files_expanded(self) -> bool:
        """Return files sub-section expanded state."""
        if self._dcc_file_table is not None:
            return self._dcc_file_table.is_files_expanded()
        return False

    def _on_file_double_clicked(self, index: QModelIndex) -> None:  # pyright: ignore[reportUnusedFunction]
        """Delegate double-click handling to file table (backward compat).

        Args:
            index: The double-clicked model index.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.on_file_double_clicked(index)

    def _show_file_context_menu(self, pos: QPoint) -> None:  # pyright: ignore[reportUnusedFunction]
        """Delegate context menu to file table (backward compat).

        Args:
            pos: Position where context menu was requested.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.show_file_context_menu(pos)

    def _launch_file(self, file: SceneFile) -> None:  # pyright: ignore[reportUnusedFunction]
        """Delegate file launch to file table (backward compat).

        Args:
            file: SceneFile to launch.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.launch_file(file)

    def _copy_file_path(self, file: SceneFile) -> None:  # pyright: ignore[reportUnusedFunction]
        """Delegate copy path to file table (backward compat).

        Args:
            file: SceneFile whose path to copy.

        """
        if self._dcc_file_table is not None:
            self._dcc_file_table.copy_file_path(file)

    # ========== Delegation to DCCSequenceTable ==========

    def set_playblast_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Maya playblast sequences for display.

        Args:
            sequences: List of ImageSequence objects.

        """
        if self._dcc_sequence_table is not None:
            self._dcc_sequence_table.set_playblast_sequences(sequences)

    def set_render_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Nuke render sequences for display.

        Args:
            sequences: List of ImageSequence objects.

        """
        if self._dcc_sequence_table is not None:
            self._dcc_sequence_table.set_render_sequences(sequences)

    def get_selected_sequence(self) -> ImageSequence | None:
        """Get currently selected sequence for RV launch.

        Returns:
            Selected ImageSequence or None.

        """
        if self._dcc_sequence_table is not None:
            return self._dcc_sequence_table.get_selected_sequence()
        return None
