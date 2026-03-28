"""Settings tab panel widgets for SettingsDialog.

Each panel is a self-contained QWidget responsible for its own UI creation,
settings loading, and settings saving for one tab of the preferences dialog.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import Config
from ui.design_system import design_system


if TYPE_CHECKING:
    from managers.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class GeneralSettingsPanel(QWidget):
    """Panel for general UI and behaviour preferences."""

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_manager: SettingsManager = settings_manager

        # Widget attributes set in _setup_ui
        self.thumbnail_size_slider: QSlider
        self.thumbnail_size_label: QLabel
        self.ui_scale_slider: QSlider
        self.ui_scale_label: QLabel
        self.animations_check: QCheckBox
        self.refresh_interval_spin: QSpinBox
        self.background_refresh_check: QCheckBox
        self.double_click_combo: QComboBox
        self.terminal_edit: QLineEdit

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the General tab layout."""
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # UI Preferences Group
        ui_group = QGroupBox("User Interface")
        ui_layout = QFormLayout(ui_group)

        # Thumbnail size
        self.thumbnail_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_size_slider.setMinimum(Config.MIN_THUMBNAIL_SIZE)
        self.thumbnail_size_slider.setMaximum(Config.MAX_THUMBNAIL_SIZE)
        self.thumbnail_size_slider.setTickInterval(50)
        self.thumbnail_size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)

        self.thumbnail_size_label = QLabel()
        thumbnail_layout = QHBoxLayout()
        thumbnail_layout.addWidget(self.thumbnail_size_slider)
        thumbnail_layout.addWidget(self.thumbnail_size_label)
        ui_layout.addRow("Thumbnail Size:", thumbnail_layout)

        # UI Scale (font sizes)
        self.ui_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.ui_scale_slider.setMinimum(80)  # 80%
        self.ui_scale_slider.setMaximum(150)  # 150%
        self.ui_scale_slider.setTickInterval(10)
        self.ui_scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)

        self.ui_scale_label = QLabel()
        ui_scale_layout = QHBoxLayout()
        ui_scale_layout.addWidget(self.ui_scale_slider)
        ui_scale_layout.addWidget(self.ui_scale_label)
        ui_layout.addRow("UI Scale:", ui_scale_layout)

        # Animations
        self.animations_check = QCheckBox("Enable Animations")
        ui_layout.addRow(self.animations_check)

        scroll_layout.addWidget(ui_group)

        # Behavior Preferences Group
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QFormLayout(behavior_group)

        # Refresh interval
        self.refresh_interval_spin = QSpinBox()
        self.refresh_interval_spin.setMinimum(1)
        self.refresh_interval_spin.setMaximum(1440)  # 24 hours
        self.refresh_interval_spin.setSuffix(" minutes")
        behavior_layout.addRow("Auto Refresh Interval:", self.refresh_interval_spin)

        # Background refresh
        self.background_refresh_check = QCheckBox("Enable Background Refresh")
        behavior_layout.addRow(self.background_refresh_check)

        # Double click action
        self.double_click_combo = QComboBox()
        self.double_click_combo.addItems(
            ["Launch Default Application", "Show Shot Information", "Open Shot Folder"]
        )
        behavior_layout.addRow("Double Click Action:", self.double_click_combo)

        # Preferred terminal
        self.terminal_edit = QLineEdit()
        self.terminal_edit.setPlaceholderText("gnome-terminal")
        behavior_layout.addRow("Preferred Terminal:", self.terminal_edit)

        scroll_layout.addWidget(behavior_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Connect slider signals for live preview
        _ = self.thumbnail_size_slider.valueChanged.connect(
            self.update_thumbnail_preview  # pyright: ignore[reportAny]
        )
        _ = self.ui_scale_slider.valueChanged.connect(
            self.update_ui_scale_preview  # pyright: ignore[reportAny]
        )

    def load_settings(self) -> None:
        """Load general settings into controls."""
        self.thumbnail_size_slider.setValue(
            self.settings_manager.ui.get_thumbnail_size()
        )
        self.update_thumbnail_preview()  # pyright: ignore[reportAny]

        # UI Scale - convert from float (0.8-1.5) to percent (80-150)
        ui_scale = self.settings_manager.ui.get_ui_scale()
        self.ui_scale_slider.setValue(int(ui_scale * 100))
        self.update_ui_scale_preview()  # pyright: ignore[reportAny]

        self.animations_check.setChecked(
            self.settings_manager.ui.get_enable_animations()
        )

        self.refresh_interval_spin.setValue(
            self.settings_manager.refresh.get_refresh_interval()
        )
        self.background_refresh_check.setChecked(
            self.settings_manager.refresh.get_background_refresh()
        )

        # Map double click action to combo index
        action_map = {"launch_default": 0, "show_info": 1, "open_folder": 2}
        action = self.settings_manager.launch.get_double_click_action()
        self.double_click_combo.setCurrentIndex(action_map.get(action, 0))

        self.terminal_edit.setText(
            self.settings_manager.launch.get_preferred_terminal()
        )

    def save_settings(self) -> None:
        """Save general settings from controls."""
        self.settings_manager.ui.set_thumbnail_size(self.thumbnail_size_slider.value())

        # UI Scale - convert from percent (80-150) to float (0.8-1.5)
        ui_scale = self.ui_scale_slider.value() / 100.0
        self.settings_manager.ui.set_ui_scale(ui_scale)
        # Update design system with new scale
        design_system.set_ui_scale(ui_scale)

        self.settings_manager.ui.set_enable_animations(
            self.animations_check.isChecked()
        )

        self.settings_manager.refresh.set_refresh_interval(
            self.refresh_interval_spin.value()
        )
        self.settings_manager.refresh.set_background_refresh(
            self.background_refresh_check.isChecked()
        )

        # Map combo index to action
        action_map = {0: "launch_default", 1: "show_info", 2: "open_folder"}
        action = action_map.get(
            self.double_click_combo.currentIndex(), "launch_default"
        )
        self.settings_manager.launch.set_double_click_action(action)

        self.settings_manager.launch.set_preferred_terminal(self.terminal_edit.text())

    @Slot()  # pyright: ignore[reportAny]
    def update_thumbnail_preview(self) -> None:
        """Update thumbnail size preview label."""
        size = self.thumbnail_size_slider.value()
        self.thumbnail_size_label.setText(f"{size}px")

    @Slot()  # pyright: ignore[reportAny]
    def update_ui_scale_preview(self) -> None:
        """Update UI scale preview label and apply live preview."""
        scale_percent = self.ui_scale_slider.value()
        self.ui_scale_label.setText(f"{scale_percent}%")

        # Apply scale in real-time for live preview
        ui_scale = scale_percent / 100.0
        design_system.set_ui_scale(ui_scale)

        # Update the label's own font to demonstrate the scale effect
        font = self.ui_scale_label.font()
        font.setPixelSize(design_system.typography.size_body)
        self.ui_scale_label.setFont(font)


class PerformanceSettingsPanel(QWidget):
    """Panel for threading and memory performance settings."""

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_manager: SettingsManager = settings_manager

        # Widget attributes set in _setup_ui
        self.max_threads_spin: QSpinBox
        self.cache_memory_spin: QSpinBox
        self.cache_expiry_spin: QSpinBox

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the Performance tab layout."""
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Threading Group
        threading_group = QGroupBox("Threading")
        threading_layout = QFormLayout(threading_group)

        # Max thumbnail threads
        self.max_threads_spin = QSpinBox()
        self.max_threads_spin.setMinimum(1)
        self.max_threads_spin.setMaximum(16)
        threading_layout.addRow("Max Thumbnail Threads:", self.max_threads_spin)

        scroll_layout.addWidget(threading_group)

        # Memory Management Group
        memory_group = QGroupBox("Memory Management")
        memory_layout = QFormLayout(memory_group)

        # Max cache memory
        self.cache_memory_spin = QSpinBox()
        self.cache_memory_spin.setMinimum(10)
        self.cache_memory_spin.setMaximum(1024)
        self.cache_memory_spin.setSuffix(" MB")
        memory_layout.addRow("Max Cache Memory:", self.cache_memory_spin)

        # Cache expiry
        self.cache_expiry_spin = QSpinBox()
        self.cache_expiry_spin.setMinimum(5)
        self.cache_expiry_spin.setMaximum(10080)  # 1 week
        self.cache_expiry_spin.setSuffix(" minutes")
        memory_layout.addRow("Cache Expiry Time:", self.cache_expiry_spin)

        scroll_layout.addWidget(memory_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def load_settings(self) -> None:
        """Load performance settings into controls."""
        self.max_threads_spin.setValue(
            self.settings_manager.performance.get_max_thumbnail_threads()
        )
        self.cache_memory_spin.setValue(
            self.settings_manager.performance.get_max_cache_memory_mb()
        )
        self.cache_expiry_spin.setValue(
            self.settings_manager.performance.get_cache_expiry_minutes()
        )

    def save_settings(self) -> None:
        """Save performance settings from controls."""
        self.settings_manager.performance.set_max_thumbnail_threads(
            self.max_threads_spin.value()
        )
        self.settings_manager.performance.set_max_cache_memory_mb(
            self.cache_memory_spin.value()
        )
        self.settings_manager.performance.set_cache_expiry_minutes(
            self.cache_expiry_spin.value()
        )


class ApplicationsSettingsPanel(QWidget):
    """Panel for default application and custom launcher settings."""

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_manager: SettingsManager = settings_manager

        # Widget attributes set in _setup_ui
        self.default_app_combo: QComboBox
        self.background_gui_apps_check: QCheckBox
        self.association_combos: dict[str, QComboBox]
        self.associations_widget: QWidget
        self.launchers_edit: QTextEdit
        self.validate_launchers_btn: QPushButton

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the Applications tab layout."""
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Default Application Group
        default_group = QGroupBox("Default Application")
        default_layout = QFormLayout(default_group)

        # Default app selection
        self.default_app_combo = QComboBox()
        self.default_app_combo.addItems(list(Config.APPS.keys()))
        default_layout.addRow("Default App:", self.default_app_combo)

        # Background GUI apps (close terminal immediately)
        self.background_gui_apps_check = QCheckBox(
            "Close terminal after launching GUI apps"
        )
        self.background_gui_apps_check.setToolTip(
            "When enabled, launching 3DE, Nuke, Maya etc. will close the terminal\n"
            "window immediately, reducing desktop clutter.\n\n"
            "The application continues running in the background."
        )
        default_layout.addRow(self.background_gui_apps_check)

        scroll_layout.addWidget(default_group)

        # File Associations Group
        associations_group = QGroupBox("File Type Associations")
        associations_layout = QVBoxLayout(associations_group)

        # Create associations table
        self.associations_widget = self._create_associations_widget()
        associations_layout.addWidget(self.associations_widget)

        scroll_layout.addWidget(associations_group)

        # Custom Launchers Group
        launchers_group = QGroupBox("Custom Launchers")
        launchers_layout = QVBoxLayout(launchers_group)

        # Custom launchers list
        self.launchers_edit = QTextEdit()
        self.launchers_edit.setMaximumHeight(100)
        self.launchers_edit.setPlaceholderText(
            "Custom launcher definitions (JSON format)"
        )
        launchers_layout.addWidget(self.launchers_edit)

        # Launcher buttons
        launcher_buttons = QHBoxLayout()
        self.validate_launchers_btn = QPushButton("Validate")
        launcher_buttons.addWidget(self.validate_launchers_btn)
        launcher_buttons.addStretch()
        launchers_layout.addLayout(launcher_buttons)

        scroll_layout.addWidget(launchers_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Connect validation signal
        _ = self.validate_launchers_btn.clicked.connect(
            self.validate_custom_launchers  # pyright: ignore[reportAny]
        )

    def _create_associations_widget(self) -> QWidget:
        """Create file associations configuration widget."""
        widget = QWidget()
        layout = QGridLayout(widget)

        # Headers
        layout.addWidget(QLabel("File Type"), 0, 0)
        layout.addWidget(QLabel("Application"), 0, 1)

        # Initialize association controls
        self.association_combos = {}

        # Create rows for each file type
        row = 1
        for file_type in Config.APPS:
            # File type label
            layout.addWidget(QLabel(file_type.upper()), row, 0)

            # Application combo
            combo = QComboBox()
            combo.addItems(list(Config.APPS.values()))
            combo.setEditable(True)  # Allow custom applications
            self.association_combos[file_type] = combo
            layout.addWidget(combo, row, 1)

            row += 1

        return widget

    def load_settings(self) -> None:
        """Load application settings into controls."""
        self.default_app_combo.setCurrentText(
            self.settings_manager.launch.get_default_app()
        )
        self.background_gui_apps_check.setChecked(
            self.settings_manager.launch.get_background_gui_apps()
        )

        # Load file associations
        associations = self.settings_manager.launch.get_file_associations()
        for file_type, combo in self.association_combos.items():
            if file_type in associations:
                combo.setCurrentText(associations[file_type])

        # Load custom launchers
        launchers = self.settings_manager.launch.get_custom_launchers()
        self.launchers_edit.setPlainText(json.dumps(launchers, indent=2))

    def save_settings(self) -> None:
        """Save application settings from controls."""
        self.settings_manager.launch.set_default_app(
            self.default_app_combo.currentText()
        )
        self.settings_manager.launch.set_background_gui_apps(
            self.background_gui_apps_check.isChecked()
        )

        # File associations
        associations: dict[str, str] = {}
        for file_type, combo in self.association_combos.items():
            associations[file_type] = combo.currentText()
        self.settings_manager.launch.set_file_associations(associations)

        # Custom launchers
        try:
            text = self.launchers_edit.toPlainText().strip()
            if text:
                # Parse JSON - returns object but we validate types below
                parsed_data: object = json.loads(text)  # pyright: ignore[reportAny]
                # Handle both dict and list formats
                launchers: list[dict[str, object]] = []
                if isinstance(parsed_data, list):
                    # Type guard: ensure list contains dicts
                    # Cast to list[object] for proper type narrowing in loop
                    parsed_list = cast("list[object]", parsed_data)
                    for item in parsed_list:
                        if isinstance(item, dict):
                            # Type narrowing: item is now dict
                            # Cast to dict[str, object] to resolve unknown types
                            item_dict = cast("dict[str, object]", item)
                            launchers.append({str(k): v for k, v in item_dict.items()})
                        else:
                            # Skip invalid items with empty dict
                            launchers.append({})
                elif isinstance(parsed_data, dict):
                    # Convert dict to list format expected by settings manager
                    # Cast to dict[str, object] to resolve unknown types
                    parsed_dict = cast("dict[str, object]", parsed_data)
                    launchers = (
                        [{str(k): v for k, v in parsed_dict.items()}]
                        if parsed_dict
                        else []
                    )
                self.settings_manager.launch.set_custom_launchers(launchers)
        except json.JSONDecodeError:
            logger.warning("Invalid custom launchers JSON, keeping existing settings")

    @Slot()  # pyright: ignore[reportAny]
    def validate_custom_launchers(self) -> None:
        """Validate custom launchers JSON."""
        try:
            text = self.launchers_edit.toPlainText().strip()
            if text:
                json.loads(text)

            _ = QMessageBox.information(
                self, "Validation Success", "Custom launchers JSON is valid."
            )
        except json.JSONDecodeError as e:
            _ = QMessageBox.warning(
                self, "Validation Error", f"Invalid JSON format:\n{e}"
            )


class AdvancedSettingsPanel(QWidget):
    """Panel for debug and advanced settings."""

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_manager: SettingsManager = settings_manager

        # Widget attributes set in _setup_ui
        self.debug_mode_check: QCheckBox
        self.log_level_combo: QComboBox

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the Advanced tab layout."""
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Debug Group
        debug_group = QGroupBox("Debug Options")
        debug_layout = QFormLayout(debug_group)

        # Debug mode
        self.debug_mode_check = QCheckBox("Enable Debug Mode")
        debug_layout.addRow(self.debug_mode_check)

        # Log level
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        debug_layout.addRow("Log Level:", self.log_level_combo)

        scroll_layout.addWidget(debug_group)

        # System Information Group
        system_group = QGroupBox("System Information")
        system_layout = QVBoxLayout(system_group)

        # Settings file path
        settings_path_label = QLabel(
            f"Settings File: {self.settings_manager.get_settings_file_path()}"
        )
        settings_path_label.setWordWrap(True)
        settings_path_label.setStyleSheet(
            f"font-family: monospace; font-size: {design_system.typography.size_micro}px;"
        )
        system_layout.addWidget(settings_path_label)

        scroll_layout.addWidget(system_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def load_settings(self) -> None:
        """Load advanced settings into controls."""
        self.debug_mode_check.setChecked(self.settings_manager.debug.get_debug_mode())
        self.log_level_combo.setCurrentText(self.settings_manager.debug.get_log_level())

    def save_settings(self) -> None:
        """Save advanced settings from controls."""
        self.settings_manager.debug.set_debug_mode(self.debug_mode_check.isChecked())
        self.settings_manager.debug.set_log_level(self.log_level_combo.currentText())
