"""DCC section widget for individual DCC application launching.

Extracted and improved from AppLauncherSection. Provides a collapsible
section with launch button, options checkboxes, and plate selector.
Shows version info in collapsed header for quick reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qt_widget_mixin import QtWidgetMixin


if TYPE_CHECKING:
    pass


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
            CheckboxConfig(
                label="Include raw plate",
                tooltip="Automatically create a Read node for the raw plate",
                key="include_raw_plate",
                default=False,
            ),
        ],
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
    ),
    DCCConfig(
        name="rv",
        display_name="RV",
        color="#2b5d4d",
        shortcut="R",
        tooltip="Launch RV for playback and review",
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
    """

    launch_requested = Signal(str, dict)  # app_name, options
    expanded_changed = Signal(str, bool)  # app_name, is_expanded

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

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the section UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Container with left accent border
        self._container = QWidget()
        self._container.setStyleSheet(f"""
            QWidget#dccContainer {{
                background-color: #252525;
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
                font-size: 12px;
                color: {self.config.color};
            }}
        """)
        header_layout.addWidget(self._name_label)

        # Version info (shown when available)
        self._version_label = QLabel()
        self._version_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 10px;
            }
        """)
        self._version_label.setVisible(False)
        header_layout.addWidget(self._version_label)

        header_layout.addStretch()

        container_layout.addWidget(header)

        # Make header clickable
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda e: self._toggle_expanded()  # type: ignore[method-assign, assignment]

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
                font-size: 11px;
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
        self._launch_description.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 11px;
                margin-top: -4px;
            }
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
                checkbox.setStyleSheet("""
                    QCheckBox {
                        color: #aaa;
                        font-size: 10px;
                    }
                    QCheckBox:hover {
                        color: #ccc;
                    }
                """)
                content_layout.addWidget(checkbox)
                self._checkboxes[cb_config.key] = checkbox

        # Plate selector
        if self.config.has_plate_selector:
            plate_row = QHBoxLayout()
            plate_row.setContentsMargins(0, 2, 0, 0)
            plate_row.setSpacing(4)

            plate_label = QLabel("Plate:")
            plate_label.setStyleSheet("QLabel { color: #888; font-size: 10px; }")
            plate_row.addWidget(plate_label)

            self._plate_selector = QComboBox()
            self._plate_selector.setEnabled(False)
            self._plate_selector.setPlaceholderText("Select...")
            self._plate_selector.setMinimumWidth(80)
            self._plate_selector.setStyleSheet("""
                QComboBox {
                    background-color: #2a2a2a;
                    color: #ecf0f1;
                    border: 1px solid #444;
                    border-radius: 3px;
                    padding: 2px 4px;
                    font-size: 10px;
                }
                QComboBox:disabled {
                    background-color: #1e1e1e;
                    color: #666;
                }
                QComboBox::drop-down { border: none; }
                QComboBox::down-arrow { image: none; }
            """)
            plate_row.addWidget(self._plate_selector)
            plate_row.addStretch()

            content_layout.addLayout(plate_row)

        container_layout.addWidget(self._content)
        layout.addWidget(self._container)

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
            self._plate_selector.setEnabled(True)
            self._plate_selector.setPlaceholderText("Select plate...")
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
