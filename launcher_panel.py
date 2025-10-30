"""Improved launcher panel with clear hierarchy and app-specific sections."""

from __future__ import annotations

# Standard library imports
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from qt_widget_mixin import QtWidgetMixin

if TYPE_CHECKING:
    # Local application imports
    from shot_model import Shot


@dataclass
class AppConfig:
    """Configuration for an application launcher section."""

    name: str
    command: str
    icon: str = ""  # Unicode emoji or icon path
    color: str = "#2b3e50"  # Default color
    tooltip: str = ""
    shortcut: str = ""
    checkboxes: list[CheckboxConfig] | None = None


@dataclass
class CheckboxConfig:
    """Configuration for app-specific checkboxes."""

    label: str
    tooltip: str
    key: str  # Settings key
    default: bool = False


class AppLauncherSection(QtWidgetMixin, QWidget):
    """Individual app launcher section with grouped options."""

    # Signals
    launch_requested = Signal(str)  # app_name

    def __init__(
        self,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.is_expanded = True
        self.checkboxes: dict[str, QCheckBox] = {}
        self.plate_selector: QComboBox | None = None  # Plate selection dropdown
        self._launch_in_progress = False
        self._original_button_text = ""
        self._should_be_enabled = False  # Track parent's desired enabled state
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the section UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(5)

        # Header with expand/collapse button and app name
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Expand/collapse button
        self.expand_button = QToolButton()
        self.expand_button.setArrowType(
            Qt.ArrowType.DownArrow if self.is_expanded else Qt.ArrowType.RightArrow
        )
        self.expand_button.clicked.connect(self._toggle_expanded)
        self.expand_button.setMaximumSize(20, 20)
        header_layout.addWidget(self.expand_button)

        # App icon and name
        name_label = QLabel(f"{self.config.icon} {self.config.name.upper()}")
        name_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: 12px;
                color: {self.config.color};
            }}
        """)
        header_layout.addWidget(name_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Content container (button and checkboxes)
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(25, 5, 0, 0)  # Indent content
        content_layout.setSpacing(5)

        # Launch button
        self.launch_button = QPushButton(f"Launch {self.config.name}")
        self.launch_button.setObjectName(f"launch_{self.config.name}")
        self.launch_button.clicked.connect(self._on_launch_clicked)
        self.launch_button.setEnabled(False)  # Disabled until shot selected

        # Apply button styling with app color
        self.launch_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.config.color};
                color: #ecf0f1;
                border: 1px solid #34495e;
                border-radius: 4px;
                padding: 8px;
                font-weight: bold;
                text-align: left;
                padding-left: 12px;
            }}
            QPushButton:hover {{
                background-color: {self._lighten_color(self.config.color)};
                border-color: #4e6d8c;
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(self.config.color)};
            }}
            QPushButton:disabled {{
                background-color: #1e2a35;
                color: #666;
                border-color: #1e2a35;
            }}
        """)

        # Set tooltip with shortcut
        tooltip = self.config.tooltip or f"Launch {self.config.name}"
        if self.config.shortcut:
            tooltip += f" (Shortcut: {self.config.shortcut})"
        self.launch_button.setToolTip(tooltip)

        content_layout.addWidget(self.launch_button)

        # Add checkboxes if configured
        if self.config.checkboxes:
            for checkbox_config in self.config.checkboxes:
                checkbox = QCheckBox(checkbox_config.label)
                checkbox.setToolTip(checkbox_config.tooltip)
                checkbox.setChecked(checkbox_config.default)
                checkbox.setStyleSheet("""
                    QCheckBox {
                        margin-left: 10px;
                        color: #aaa;
                    }
                    QCheckBox:hover {
                        color: #ccc;
                    }
                """)
                content_layout.addWidget(checkbox)
                self.checkboxes[checkbox_config.key] = checkbox

        # Add plate selector for apps that work with plates
        if self.config.name in ["nuke", "maya", "3de", "rv"]:
            # Create plate selector with label
            plate_layout = QHBoxLayout()
            plate_layout.setContentsMargins(10, 5, 0, 0)

            plate_label = QLabel("Plate:")
            plate_label.setStyleSheet("QLabel { color: #aaa; font-size: 11px; }")
            plate_layout.addWidget(plate_label)

            self.plate_selector = QComboBox()
            self.plate_selector.setEnabled(False)
            self.plate_selector.setPlaceholderText("Select plate space...")
            self.plate_selector.setMinimumWidth(120)
            self.plate_selector.setStyleSheet(f"""
                QComboBox {{
                    background-color: #2a2a2a;
                    color: #ecf0f1;
                    border: 1px solid {self.config.color};
                    border-radius: 3px;
                    padding: 4px 8px;
                    font-size: 11px;
                }}
                QComboBox:disabled {{
                    background-color: #1e1e1e;
                    color: #666;
                    border-color: #333;
                }}
                QComboBox::drop-down {{
                    border: none;
                }}
                QComboBox::down-arrow {{
                    image: none;
                    border: none;
                }}
            """)
            plate_layout.addWidget(self.plate_selector)
            plate_layout.addStretch()

            content_layout.addLayout(plate_layout)

        layout.addWidget(self.content_widget)

        # Add separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("QFrame { color: #333; margin: 5px 0; }")
        layout.addWidget(separator)

    def _toggle_expanded(self) -> None:
        """Toggle expanded/collapsed state."""
        self.is_expanded = not self.is_expanded
        self.expand_button.setArrowType(
            Qt.ArrowType.DownArrow if self.is_expanded else Qt.ArrowType.RightArrow
        )
        self.content_widget.setVisible(self.is_expanded)

    def _lighten_color(self, color: str) -> str:
        """Lighten a hex color for hover effect."""
        # Simple color lightening - could be improved
        if color.startswith("#"):
            # Convert to RGB, lighten, convert back
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)

            # Lighten by 20%
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

            # Darken by 20%
            r = int(r * 0.8)
            g = int(g * 0.8)
            b = int(b * 0.8)

            return f"#{r:02x}{g:02x}{b:02x}"
        return color

    def _on_launch_clicked(self) -> None:
        """Handle launch button click with progress indication."""
        # Prevent double-clicks
        if self._launch_in_progress:
            return

        # Save original state and update UI
        self._launch_in_progress = True
        self._original_button_text = self.launch_button.text()
        self.launch_button.setEnabled(False)
        self.launch_button.setText(f"Launching {self.config.name}...")

        # Emit launch request
        self.launch_requested.emit(self.config.name)

        # Reset button after 3 seconds (with safe widget lifecycle check)
        QTimer.singleShot(3000, self._safe_reset_button_state)

    def _safe_reset_button_state(self) -> None:
        """Safely reset button state with widget lifecycle checks.

        Protects against widget destruction during the timer window by catching
        RuntimeError (C++ object deleted) and checking widget validity.
        """
        try:
            if not self.isHidden() and hasattr(self, "launch_button"):
                self._reset_button_state()
        except (RuntimeError, AttributeError):
            # Widget was destroyed, silently ignore
            pass

    def _reset_button_state(self) -> None:
        """Reset button to original state after launch.

        Restores the enabled state that was set via set_enabled(), which may
        have changed during the 3-second launch window (e.g., shot deselection).
        """
        self._launch_in_progress = False
        self.launch_button.setText(self._original_button_text)
        self.launch_button.setEnabled(self._should_be_enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the launch button.

        Tracks the desired enabled state and applies it immediately unless
        a launch is in progress. When launch completes, the tracked state
        will be restored, respecting any changes made during the launch window.
        """
        self._should_be_enabled = enabled
        if not self._launch_in_progress:
            self.launch_button.setEnabled(enabled)

    def get_checkbox_states(self) -> dict[str, bool]:
        """Get the state of all checkboxes."""
        return {key: cb.isChecked() for key, cb in self.checkboxes.items()}

    def set_available_plates(self, plates: list[str]) -> None:
        """Update plate selector with available plates.

        Args:
            plates: List of plate names (e.g., ['FG01', 'BG01'])
        """
        if not self.plate_selector:
            return

        self.plate_selector.clear()
        if plates:
            self.plate_selector.addItems(plates)
            self.plate_selector.setEnabled(True)
            self.plate_selector.setPlaceholderText("Select plate space...")
        else:
            self.plate_selector.setEnabled(False)
            self.plate_selector.setPlaceholderText("No plates available")

    def get_selected_plate(self) -> str | None:
        """Get currently selected plate name.

        Returns:
            Plate name (e.g., 'FG01') or None if no plate selected
        """
        if not self.plate_selector or not self.plate_selector.isEnabled():
            return None

        current_text = self.plate_selector.currentText()
        return current_text if current_text else None


class LauncherPanel(QtWidgetMixin, QWidget):
    """Improved launcher panel with organized app sections."""

    # Signals
    app_launch_requested = Signal(str)  # app_name
    custom_launcher_requested = Signal(str)  # launcher_id

    def __init__(self, parent: QWidget | None = None) -> None:
        # Declare widgets created in template methods
        self.custom_launcher_container: QVBoxLayout
        super().__init__(parent)
        self.app_sections: dict[str, AppLauncherSection] = {}
        self.custom_launcher_buttons: dict[str, QPushButton] = {}
        self._current_shot: Shot | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the launcher panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main group box
        self.group_box = QGroupBox("Launch Applications")
        self.group_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #ddd;
            }
        """)

        group_layout = QVBoxLayout(self.group_box)
        group_layout.setSpacing(0)

        # Info label
        self.info_label = QLabel("Select a shot to enable app launching")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(
            "QLabel { color: #888; font-style: italic; padding: 5px 10px; font-size: 11px; }"
        )
        group_layout.addWidget(self.info_label)

        # App configurations
        app_configs = [
            AppConfig(
                name="3de",
                command="3de",
                icon="🎬",
                color="#2b4d6f",  # Blue
                tooltip="Launch 3DE for matchmove/tracking",
                shortcut="3",
                checkboxes=[
                    CheckboxConfig(
                        label="Open latest 3DE scene (when available)",
                        tooltip="Automatically open the latest scene file from the workspace",
                        key="open_latest_threede",
                        default=True,
                    )
                ],
            ),
            AppConfig(
                name="nuke",
                command="nuke",
                icon="🎨",
                color="#5d4d2b",  # Orange/brown
                tooltip="Launch Nuke for compositing",
                shortcut="N",
                checkboxes=[
                    CheckboxConfig(
                        label="Open latest scene",
                        tooltip="Open the most recent Nuke script from workspace (creates v001 if none exist)",
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
                        label="Include undistortion nodes",
                        tooltip="Automatically include the latest undistortion .nk file",
                        key="include_undistortion",
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
            AppConfig(
                name="maya",
                command="maya",
                icon="🎭",
                color="#4d2b5d",  # Purple
                tooltip="Launch Maya for 3D work",
                shortcut="M",
                checkboxes=[
                    CheckboxConfig(
                        label="Open latest Maya scene (when available)",
                        tooltip="Automatically open the latest scene file from the workspace",
                        key="open_latest_maya",
                        default=True,
                    )
                ],
            ),
            AppConfig(
                name="rv",
                command="rv",
                icon="📽️",
                color="#2b5d4d",  # Teal
                tooltip="Launch RV for playback and review",
                shortcut="R",
            ),
            AppConfig(
                name="publish",
                command="publish_standalone",
                icon="📦",
                color="#5d2b2b",  # Red
                tooltip="Launch publish tool",
                shortcut="P",
            ),
        ]

        # Create app sections
        for config in app_configs:
            section = AppLauncherSection(config)
            section.launch_requested.connect(self._on_app_launch)
            group_layout.addWidget(section)
            self.app_sections[config.name] = section

        # Custom launchers section
        self._add_custom_launchers_section(group_layout)

        # Add stretch to push everything to the top
        group_layout.addStretch()

        layout.addWidget(self.group_box)

    def _add_custom_launchers_section(self, parent_layout: QVBoxLayout) -> None:
        """Add custom launchers section."""
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("QFrame { color: #555; margin: 10px 0; }")
        parent_layout.addWidget(separator)

        # Add custom launchers label
        custom_label = QLabel("Custom Launchers")
        custom_label.setObjectName("customLaunchersLabel")
        custom_label.setStyleSheet("""
            QLabel#customLaunchersLabel {
                color: #aaa;
                font-size: 11px;
                font-weight: bold;
                padding: 5px 0 2px 10px;
            }
        """)
        parent_layout.addWidget(custom_label)

        # Container for custom launcher buttons
        self.custom_launcher_container = QVBoxLayout()
        self.custom_launcher_container.setSpacing(5)
        self.custom_launcher_container.setContentsMargins(25, 5, 10, 0)
        parent_layout.addLayout(self.custom_launcher_container)

    def _on_app_launch(self, app_name: str) -> None:
        """Handle app launch request from section."""
        self.app_launch_requested.emit(app_name)

    def set_shot(self, shot: Shot | None) -> None:
        """Update the panel for the selected shot."""
        self._current_shot = shot

        # Update info label
        if shot:
            self.info_label.setText(f"Shot: {shot.show}/{shot.sequence}/{shot.shot}")
            self.info_label.setStyleSheet(
                "QLabel { color: #9c9; font-style: normal; padding: 5px 10px; font-size: 11px; font-weight: bold; }"
            )
        else:
            self.info_label.setText("Select a shot to enable app launching")
            self.info_label.setStyleSheet(
                "QLabel { color: #888; font-style: italic; padding: 5px 10px; font-size: 11px; }"
            )

        # Enable/disable all app sections
        for section in self.app_sections.values():
            section.set_enabled(shot is not None)

        # Enable/disable custom launcher buttons
        for button in self.custom_launcher_buttons.values():
            button.setEnabled(shot is not None)

    def get_checkbox_state(self, app: str, key: str) -> bool:
        """Get the state of a specific checkbox."""
        if app in self.app_sections:
            states = self.app_sections[app].get_checkbox_states()
            return states.get(key, False)
        return False

    def add_custom_launcher(self, launcher_id: str, name: str) -> None:
        """Add a custom launcher button."""
        if launcher_id not in self.custom_launcher_buttons:
            button = QPushButton(name)
            button.setObjectName(f"customLauncher_{launcher_id}")
            button.clicked.connect(
                lambda: self.custom_launcher_requested.emit(launcher_id)
            )
            button.setEnabled(self._current_shot is not None)
            button.setStyleSheet("""
                QPushButton {
                    background-color: #3d3d3d;
                    color: #ecf0f1;
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 6px;
                    text-align: left;
                    padding-left: 12px;
                }
                QPushButton:hover {
                    background-color: #4d4d4d;
                    border-color: #666;
                }
                QPushButton:pressed {
                    background-color: #2d2d2d;
                }
                QPushButton:disabled {
                    background-color: #2d2d2d;
                    color: #666;
                    border-color: #333;
                }
            """)
            self.custom_launcher_container.addWidget(button)
            self.custom_launcher_buttons[launcher_id] = button

    def remove_custom_launcher(self, launcher_id: str) -> None:
        """Remove a custom launcher button."""
        if launcher_id in self.custom_launcher_buttons:
            button = self.custom_launcher_buttons.pop(launcher_id)
            self.custom_launcher_container.removeWidget(button)
            button.deleteLater()

    def update_custom_launchers(self, launchers: list[tuple[str, str]]) -> None:
        """Update all custom launcher buttons."""
        # Remove old buttons
        for button in list(self.custom_launcher_buttons.values()):
            self.custom_launcher_container.removeWidget(button)
            button.deleteLater()
        self.custom_launcher_buttons.clear()

        # Add new buttons
        for launcher_id, name in launchers:
            self.add_custom_launcher(launcher_id, name)
