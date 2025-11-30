"""DCC section widget for individual DCC application launching.

Extracted and improved from AppLauncherSection. Provides a collapsible
section with launch button, options checkboxes, and plate selector.
Shows version info in collapsed header for quick reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, final


if TYPE_CHECKING:
    from files_tab_widget import FileTableModel

from PySide6.QtCore import QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from design_system import design_system
from qt_widget_mixin import QtWidgetMixin
from scene_file import FileType, ImageSequence, SceneFile
from thumbnail_widget_base import FolderOpenerWorker


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


def get_default_config(name: str) -> DCCConfig | None:
    """Get default config for a DCC by name."""
    for config in DEFAULT_DCC_CONFIGS:
        if config.name == name:
            return config
    return None


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
        launch_requested: Signal(str, dict) - app_name, options dict
        expanded_changed: Signal(str, bool) - app_name, is_expanded
        file_selected: Signal(object) - emits SceneFile when user clicks a file
    """

    launch_requested = Signal(str, dict)  # app_name, options
    expanded_changed = Signal(str, bool)  # app_name, is_expanded
    file_selected = Signal(object)  # SceneFile

    def __init__(
        self,
        config: DCCConfig,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the DCC section.

        Args:
            config: Configuration for this DCC
            parent: Optional parent widget
        """
        super().__init__(parent)
        self.config = config
        self._expanded = False
        self._version_info: str | None = None
        self._age_info: str | None = None
        self._launch_in_progress = False
        self._should_be_enabled = False
        self._original_button_text = ""

        # UI components
        self._checkboxes: dict[str, QCheckBox] = {}
        self._plate_selector: QComboBox | None = None

        # Files sub-section components (only if has_files_section)
        self._files_section: QWidget | None = None
        self._files_content: QWidget | None = None
        self._file_table: QTableView | None = None
        self._file_model: FileTableModel | None = None
        self._files_header_btn: QPushButton | None = None
        self._files_expanded = False
        self._files_count = 0
        self._current_selected_file: SceneFile | None = None

        # RV sequence sub-section components (only for RV)
        self._playblasts_section: dict[str, Any] | None = None
        self._renders_section: dict[str, Any] | None = None
        self._selected_sequence: ImageSequence | None = None

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
                background-color: {self._get_tinted_background()};
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
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Expand/collapse button
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._expand_btn.setMaximumSize(18, 18)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ = self._expand_btn.clicked.connect(self._toggle_expanded)
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
        header_layout.addWidget(self._expand_btn)

        # DCC name
        self._name_label = QLabel(self.config.display_name)
        self._name_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: {design_system.typography.size_small}px;
                color: {self.config.color};
            }}
        """)
        header_layout.addWidget(self._name_label)

        # Version info (shown when available)
        self._version_label = QLabel()
        self._version_label.setStyleSheet(f"""
            QLabel {{
                color: #888;
                font-size: {design_system.typography.size_small}px;
            }}
        """)
        self._version_label.setVisible(False)
        header_layout.addWidget(self._version_label)

        header_layout.addStretch()

        container_layout.addWidget(header)

        # Make header clickable
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda _e: self._toggle_expanded()  # type: ignore[method-assign, assignment]

        # Content widget (hidden when collapsed)
        self._content = QWidget()
        self._content.setVisible(False)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(26, 4, 0, 4)  # Indent under expand arrow
        content_layout.setSpacing(4)

        # Launch button
        self._launch_btn = QPushButton("Launch")
        self._launch_btn.setEnabled(False)
        _ = self._launch_btn.clicked.connect(self._on_launch_clicked)
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
                background-color: {self._lighten_color(self.config.color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(self.config.color)};
            }}
            QPushButton:disabled {{
                background-color: #2a2a2a;
                color: #666;
                border: 1px dashed #444;
            }}
        """)

        tooltip = self.config.tooltip or f"Launch {self.config.display_name}"
        tooltip += f" (Shortcut: {self.config.shortcut.upper()})"
        self._launch_btn.setToolTip(tooltip)
        content_layout.addWidget(self._launch_btn)

        # Launch description label (shows what will be opened)
        self._launch_description = QLabel()
        self._launch_description.setStyleSheet(f"""
            QLabel {{
                color: #888;
                font-size: {design_system.typography.size_tiny}px;
                margin-top: 12px;
            }}
        """)
        self._launch_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._launch_description.setVisible(False)
        content_layout.addWidget(self._launch_description)

        # Checkboxes
        if self.config.checkboxes:
            for cb_config in self.config.checkboxes:
                checkbox = QCheckBox(cb_config.label)
                checkbox.setToolTip(cb_config.tooltip)
                checkbox.setChecked(cb_config.default)
                checkbox.setStyleSheet(f"""
                    QCheckBox {{
                        color: #aaa;
                        font-size: {design_system.typography.size_small}px;
                    }}
                    QCheckBox:hover {{
                        color: #ccc;
                    }}
                """)
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
            plate_row.addWidget(self._plate_selector)
            plate_row.addStretch()

            content_layout.addLayout(plate_row)

        # Files sub-section (if configured)
        if self.config.has_files_section:
            self._setup_files_subsection(content_layout)

        # RV sequence sub-sections (Maya Playblasts and Nuke Renders)
        if self.config.name == "rv":
            self._setup_rv_sequence_subsections(content_layout)

        container_layout.addWidget(self._content)
        layout.addWidget(self._container)

        # Apply dynamic styles
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply/refresh styles using current design system values."""
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
                background-color: {self._lighten_color(self.config.color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(self.config.color)};
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

        # Files header button
        if self._files_header_btn is not None:
            self._files_header_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    text-align: left;
                    padding: 4px 0px;
                    font-size: {design_system.typography.size_tiny}px;
                    font-weight: bold;
                    color: #888;
                }}
                QPushButton:hover {{
                    color: #aaa;
                }}
            """)

        # Files table
        if self._file_table is not None:
            color = self.config.color
            self._file_table.setStyleSheet(f"""
                QTableView {{
                    background-color: #1e1e1e;
                    alternate-background-color: #232323;
                    color: #ecf0f1;
                    border: 1px solid #333;
                    border-radius: 3px;
                    selection-background-color: {color}40;
                    selection-color: #ecf0f1;
                }}
                QTableView::item {{
                    padding: 2px 6px;
                    font-size: {design_system.typography.size_small}px;
                }}
                QTableView::item:selected {{
                    background-color: {color}60;
                }}
                QHeaderView::section {{
                    background-color: #252525;
                    color: #888;
                    padding: 3px 6px;
                    border: none;
                    border-bottom: 1px solid #333;
                    font-weight: bold;
                    font-size: {design_system.typography.size_tiny}px;
                }}
            """)

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

    def _lighten_color(self, color: str) -> str:
        """Lighten a hex color for hover effect."""
        if color.startswith("#"):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            r = min(255, int(r * 1.2))
            g = min(255, int(g * 1.2))
            b = min(255, int(b * 1.2))
            return f"#{r:02x}{g:02x}{b:02x}"
        return color

    def _get_tinted_background(self, base: str = "#252525", blend: float = 0.12) -> str:
        """Generate a subtle tint of the DCC color blended with base background.

        Args:
            base: Base background color (dark gray).
            blend: Blend factor (0.0 = base only, 1.0 = full DCC color).

        Returns:
            Hex color string with subtle DCC color tint.
        """
        color = self.config.color
        if not color.startswith("#") or not base.startswith("#"):
            return base

        # Parse colors
        br, bg, bb = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)
        cr, cg, cb = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

        # Blend: result = base * (1 - blend) + color * blend
        r = int(br * (1 - blend) + cr * blend)
        g = int(bg * (1 - blend) + cg * blend)
        b = int(bb * (1 - blend) + cb * blend)

        return f"#{r:02x}{g:02x}{b:02x}"

    def _darken_color(self, color: str) -> str:
        """Darken a hex color for pressed effect."""
        if color.startswith("#"):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            r = int(r * 0.8)
            g = int(g * 0.8)
            b = int(b * 0.8)
            return f"#{r:02x}{g:02x}{b:02x}"
        return color

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
        """Reset button to original state."""
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
        return text if text else None

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

    # ========== Files Sub-Section Methods ==========

    def _setup_files_subsection(self, content_layout: QVBoxLayout) -> None:
        """Set up the collapsible files sub-section.

        Args:
            content_layout: The layout to add the files section to
        """
        # Local import to avoid circular dependency
        from files_tab_widget import FileTableModel

        # Container for files sub-section
        self._files_section = QWidget()
        files_layout = QVBoxLayout(self._files_section)
        files_layout.setContentsMargins(0, 8, 0, 0)
        files_layout.setSpacing(0)

        # Files header button (collapsible)
        self._files_header_btn = QPushButton("▶  Files (0)")
        self._files_header_btn.setFlat(True)
        self._files_header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ = self._files_header_btn.clicked.connect(self._toggle_files_expanded)
        self._files_header_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 4px 0px;
                font-size: {design_system.typography.size_tiny}px;
                font-weight: bold;
                color: #888;
            }}
            QPushButton:hover {{
                color: #aaa;
            }}
        """)
        files_layout.addWidget(self._files_header_btn)

        # Files table container (hidden by default)
        self._files_content = QWidget()
        self._files_content.setVisible(False)
        files_content_layout = QVBoxLayout(self._files_content)
        files_content_layout.setContentsMargins(0, 4, 0, 0)
        files_content_layout.setSpacing(0)

        # Create table model and view
        self._file_model = FileTableModel(parent=self)
        self._file_table = QTableView()
        self._file_table.setModel(self._file_model)
        self._file_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._file_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._file_table.setAlternatingRowColors(True)
        self._file_table.setSortingEnabled(False)
        self._file_table.setShowGrid(False)
        self._file_table.verticalHeader().setVisible(False)
        self._file_table.setMaximumHeight(120)

        # Configure header
        header = self._file_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        # Styling with DCC accent color
        color = self.config.color
        self._file_table.setStyleSheet(f"""
            QTableView {{
                background-color: #1e1e1e;
                alternate-background-color: #232323;
                color: #ecf0f1;
                border: 1px solid #333;
                border-radius: 3px;
                selection-background-color: {color}40;
                selection-color: #ecf0f1;
            }}
            QTableView::item {{
                padding: 2px 6px;
                font-size: {design_system.typography.size_small}px;
            }}
            QTableView::item:selected {{
                background-color: {color}60;
            }}
            QHeaderView::section {{
                background-color: #252525;
                color: #888;
                padding: 3px 6px;
                border: none;
                border-bottom: 1px solid #333;
                font-weight: bold;
                font-size: {design_system.typography.size_tiny}px;
            }}
        """)

        # Connect signals
        _ = self._file_table.clicked.connect(self._on_file_clicked)

        # Enable context menu on right-click
        self._file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        _ = self._file_table.customContextMenuRequested.connect(
            self._show_file_context_menu
        )

        # Connect double-click for quick launch
        _ = self._file_table.doubleClicked.connect(self._on_file_double_clicked)

        files_content_layout.addWidget(self._file_table)
        files_layout.addWidget(self._files_content)

        content_layout.addWidget(self._files_section)

    def _toggle_files_expanded(self) -> None:
        """Toggle the files sub-section expanded state."""
        self._files_expanded = not self._files_expanded
        if self._files_content is not None:
            self._files_content.setVisible(self._files_expanded)
        self._update_files_header()

    def _update_files_header(self) -> None:
        """Update files header text with indicator and count."""
        if self._files_header_btn is not None:
            indicator = "▼" if self._files_expanded else "▶"
            self._files_header_btn.setText(f"{indicator}  Files ({self._files_count})")

    def _on_file_clicked(self, index: QModelIndex) -> None:
        """Handle file row click.

        Args:
            index: The clicked model index
        """
        if self._file_model is not None:
            file = self._file_model.get_file(index.row())
            if file is not None:
                # Track selected file
                self._current_selected_file = file
                # Update launch description
                self._update_launch_button_from_file(file)
                # Mark this file as current default
                self._file_model.set_current_default(file)
                # Emit signal
                self.file_selected.emit(file)

    def _on_file_double_clicked(self, index: QModelIndex) -> None:
        """Handle file row double-click - launch immediately.

        Double-clicking a file row launches the DCC app with that file selected.

        Args:
            index: The double-clicked model index
        """
        if self._file_model is None:
            return

        file = self._file_model.get_file(index.row())
        if file is None:
            return

        # Update selection state (same as single click)
        self._current_selected_file = file
        self._file_model.set_current_default(file)
        self.file_selected.emit(file)

        # Emit launch signal - parent retrieves file via get_selected_file()
        options = self.get_options()
        self.launch_requested.emit(self.config.name, options)

    def _show_file_context_menu(self, pos: QPoint) -> None:
        """Show context menu for file table.

        Args:
            pos: Position where context menu was requested
        """
        if self._file_table is None or self._file_model is None:
            return

        index = self._file_table.indexAt(pos)
        if not index.isValid():
            return

        file = self._file_model.get_file(index.row())
        if file is None:
            return

        menu = QMenu(self)

        # "Open in [App Name]" action
        app_display_name = self.config.display_name
        open_action = menu.addAction(f"Open in {app_display_name}")
        _ = open_action.triggered.connect(lambda: self._launch_file(file))

        # "Open Containing Folder" action
        open_folder_action = menu.addAction("Open Containing Folder")
        _ = open_folder_action.triggered.connect(lambda: self._open_file_folder(file))

        # Separator
        _ = menu.addSeparator()

        # "Copy Path" action
        copy_path_action = menu.addAction("Copy Path")
        _ = copy_path_action.triggered.connect(lambda: self._copy_file_path(file))

        # Show menu at global position
        _ = menu.exec(self._file_table.mapToGlobal(pos))

    def _launch_file(self, file: SceneFile) -> None:
        """Launch the DCC app with the specified file.

        Args:
            file: SceneFile to launch
        """
        # Update selection state
        self._current_selected_file = file
        if self._file_model is not None:
            self._file_model.set_current_default(file)
        self.file_selected.emit(file)

        # Emit launch signal - parent retrieves file via get_selected_file()
        options = self.get_options()
        self.launch_requested.emit(self.config.name, options)

    def _open_file_folder(self, file: SceneFile) -> None:
        """Open the containing folder for a file.

        Args:
            file: SceneFile whose parent folder to open
        """
        from pathlib import Path

        from PySide6.QtCore import QThreadPool

        file_path = Path(file.path)
        if file_path.exists():
            folder_path = str(file_path.parent)
            worker = FolderOpenerWorker(folder_path)
            QThreadPool.globalInstance().start(worker)

    def _copy_file_path(self, file: SceneFile) -> None:
        """Copy file path to clipboard.

        Args:
            file: SceneFile whose path to copy
        """
        clipboard = QApplication.clipboard()
        clipboard.setText(str(file.path))

    def _update_launch_button_from_file(self, file: SceneFile) -> None:
        """Update launch button description from selected file.

        Args:
            file: The selected scene file
        """
        if file.version is not None:
            version_str = f"v{file.version:03d}"
            plate = self.get_selected_plate()
            self.set_launch_description(version_str, plate)

    def set_files(self, files: list[SceneFile]) -> None:
        """Set files for the embedded files sub-section.

        Args:
            files: List of scene files to display
        """
        if self._file_model is not None:
            self._file_model.set_files(files)
            self._files_count = len(files)
            self._update_files_header()

            # Auto-select first file if available
            if files:
                self._current_selected_file = files[0]
                self._file_model.set_current_default(files[0])
                self._update_launch_button_from_file(files[0])
            else:
                self._current_selected_file = None

    def get_selected_file(self) -> SceneFile | None:
        """Get the currently selected file from the embedded table.

        Returns:
            Selected SceneFile or None
        """
        # Return the tracked current selected file
        return self._current_selected_file

    def set_default_file(self, file: SceneFile | None) -> None:
        """Mark a file as the default (shows arrow indicator).

        Args:
            file: The file to mark as default, or None to clear
        """
        self._current_selected_file = file
        if self._file_model is not None:
            self._file_model.set_current_default(file)
            if file is not None:
                self._update_launch_button_from_file(file)

    def set_files_expanded(self, expanded: bool) -> None:
        """Set the files sub-section expanded state.

        Args:
            expanded: True to expand, False to collapse
        """
        if self._files_expanded != expanded:
            self._files_expanded = expanded
            if self._files_content is not None:
                self._files_content.setVisible(expanded)
            self._update_files_header()

    def is_files_expanded(self) -> bool:
        """Return files sub-section expanded state."""
        return self._files_expanded

    # =========================================================================
    # RV Sequence Subsections (Maya Playblasts and Nuke Renders)
    # =========================================================================

    def _setup_rv_sequence_subsections(self, content_layout: QVBoxLayout) -> None:
        """Set up Maya Playblasts and Nuke Renders subsections for RV section.

        Args:
            content_layout: The layout to add the sequence sections to
        """
        # Colors matching DCC themes
        playblast_color = "#6b4d8a"  # Purple (Maya-like)
        render_color = "#8a6b2b"  # Gold (distinctive)

        # Create Maya Playblasts subsection
        self._playblasts_section = self._create_sequence_subsection(
            title="Maya Playblasts",
            color=playblast_color,
            content_layout=content_layout,
        )

        # Create Nuke Renders subsection
        self._renders_section = self._create_sequence_subsection(
            title="Nuke Renders",
            color=render_color,
            content_layout=content_layout,
        )

    def _create_sequence_subsection(
        self,
        title: str,
        color: str,
        content_layout: QVBoxLayout,
    ) -> dict[str, Any]:
        """Create a collapsible sequence subsection.

        Args:
            title: Section title (e.g., "Maya Playblasts")
            color: Accent color hex
            content_layout: Parent layout to add section to

        Returns:
            Dict containing section state and UI elements
        """
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        # Header button (collapsible, colored left border)
        header_btn = QPushButton(f"▶  {title} (0)")
        header_btn.setFlat(True)
        header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-left: 3px solid {color};
                text-align: left;
                padding: 4px 8px;
                font-size: {design_system.typography.size_tiny}px;
                font-weight: bold;
                color: {color};
            }}
            QPushButton:hover {{
                background-color: #2a2a2a;
            }}
        """)
        layout.addWidget(header_btn)

        # Content container (hidden by default)
        content = QWidget()
        content.setVisible(False)
        content_inner_layout = QVBoxLayout(content)
        content_inner_layout.setContentsMargins(8, 4, 0, 0)
        content_inner_layout.setSpacing(4)

        # List widget for sequences
        list_widget = QListWidget()
        list_widget.setMaximumHeight(120)
        list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 3px;
                color: #ecf0f1;
                font-size: {design_system.typography.size_small}px;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid #2a2a2a;
            }}
            QListWidget::item:selected {{
                background-color: {color}40;
            }}
            QListWidget::item:hover {{
                background-color: #2a2a2a;
            }}
        """)
        content_inner_layout.addWidget(list_widget)

        layout.addWidget(content)
        content_layout.addWidget(section)

        # Store state in dict
        result: dict[str, Any] = {
            "section": section,
            "header_btn": header_btn,
            "content": content,
            "list_widget": list_widget,
            "expanded": False,
            "color": color,
            "title": title,
        }

        # Connect toggle
        _ = header_btn.clicked.connect(lambda: self._toggle_sequence_section(result))

        # Connect double-click to launch RV with sequence
        _ = list_widget.itemDoubleClicked.connect(self._on_sequence_double_clicked)

        return result

    def _toggle_sequence_section(self, section_data: dict[str, Any]) -> None:
        """Toggle sequence subsection expanded state.

        Args:
            section_data: Dict containing section state and UI elements
        """
        section_data["expanded"] = not section_data["expanded"]
        section_data["content"].setVisible(section_data["expanded"])
        indicator = "▼" if section_data["expanded"] else "▶"
        count = section_data["list_widget"].count()
        section_data["header_btn"].setText(
            f"{indicator}  {section_data['title']} ({count})"
        )

    def _on_sequence_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle sequence item double-click - launch RV with sequence.

        Args:
            item: The double-clicked list item
        """
        sequence = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(sequence, ImageSequence):
            self._selected_sequence = sequence
            # Emit launch signal with sequence_path in options
            options = self.get_options()
            options["sequence_path"] = str(sequence.path)
            self.launch_requested.emit(self.config.name, options)

    def set_playblast_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Maya playblast sequences for display.

        Args:
            sequences: List of ImageSequence objects
        """
        if self._playblasts_section:
            self._update_sequence_list(self._playblasts_section, sequences)

    def set_render_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Nuke render sequences for display.

        Args:
            sequences: List of ImageSequence objects
        """
        if self._renders_section:
            self._update_sequence_list(self._renders_section, sequences)

    def _update_sequence_list(
        self, section_data: dict[str, Any], sequences: list[ImageSequence]
    ) -> None:
        """Update a sequence list widget with new data.

        Args:
            section_data: Dict containing section state and UI elements
            sequences: List of ImageSequence objects to display
        """
        list_widget: QListWidget = section_data["list_widget"]
        list_widget.clear()

        for i, seq in enumerate(sequences):
            # Format: "▶  {render_type}  |  v{version}  |  {frame_range}  |  {age}  |  LATEST"
            version_str = f"v{seq.version:03d}" if seq.version else "—"
            latest_badge = "  LATEST" if i == 0 else ""
            item_text = (
                f"▶  {seq.render_type}  |  {version_str}  |  "
                f"{seq.frame_range_str}  |  {seq.relative_age}{latest_badge}"
            )

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, seq)
            list_widget.addItem(item)

        # Update header count
        indicator = "▼" if section_data["expanded"] else "▶"
        section_data["header_btn"].setText(
            f"{indicator}  {section_data['title']} ({len(sequences)})"
        )

    def get_selected_sequence(self) -> ImageSequence | None:
        """Get currently selected sequence for RV launch.

        Returns:
            Selected ImageSequence or None
        """
        return self._selected_sequence
