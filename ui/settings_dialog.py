"""Settings dialog for ShotBot application preferences.

This module provides a comprehensive preferences dialog with tabbed interface
for configuring all application settings. The dialog includes live preview,
validation, import/export functionality, and organized settings categories.

Key Features:
    - Tabbed interface for different setting categories
    - Live preview for visual settings (thumbnail size, themes)
    - Input validation with error messages
    - Apply/Cancel/OK buttons with proper handling
    - Reset to defaults for individual categories or all settings
    - Import/export settings functionality
    - Keyboard shortcuts and accessibility support

Categories:
    - General: Basic preferences and UI behavior
    - Performance: Threading, caching, and optimization
    - Applications: Default apps and custom launchers
    - Advanced: Debug options and experimental features

Architecture:
    The dialog uses a tab-based layout with dedicated widgets for each category.
    Settings are applied immediately to a temporary copy and only committed
    when the user clicks OK or Apply. This allows for proper cancellation.

Examples:
    Basic usage:
        >>> from settings_dialog import SettingsDialog
        >>> from settings_manager import SettingsManager
        >>> settings = SettingsManager()
        >>> dialog = SettingsDialog(settings, parent=main_window)
        >>> if dialog.exec() == QDialog.Accepted:
        ...     # Settings were applied
        ...     pass

    With specific tab:
        >>> dialog = SettingsDialog(settings, initial_tab="performance")
        >>> dialog.show()

Type Safety:
    All UI controls include proper type annotations and validation.
    Settings values are validated before application with clear error messages.

"""

from __future__ import annotations

# Standard library imports
import json
import logging
from typing import TYPE_CHECKING, ClassVar, cast

# Third-party imports
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from config import Config
from logging_mixin import LoggingMixin
from managers.notification_manager import NotificationManager
from timeout_config import TimeoutConfig
from typing_compat import override
from ui.design_system import design_system
from ui.qt_widget_mixin import QtWidgetMixin


if TYPE_CHECKING:
    # Local application imports
    from managers.settings_manager import SettingsManager

# Set up logger for this module
logger = logging.getLogger(__name__)


class SettingsDialog(QDialog, QtWidgetMixin, LoggingMixin):
    """Comprehensive settings dialog with tabbed interface."""

    # Signals
    settings_applied: ClassVar[Signal] = Signal()  # Emitted when settings are applied

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: QWidget | None = None,
        initial_tab: str = "general",
    ) -> None:
        """Initialize settings dialog.

        Args:
            settings_manager: SettingsManager instance
            parent: Parent widget
            initial_tab: Initial tab to show ("general", "performance", "applications", "advanced")

        """
        super().__init__(parent)
        self.settings_manager: SettingsManager = settings_manager

        # Temporary settings copy for preview/cancel functionality
        self.temp_settings: dict[str, object] = {}

        # Store original values for cancel/restore
        self._original_ui_scale: float = design_system.get_ui_scale()

        # Initialize all widget attributes that will be set in setup_ui()
        # General tab widgets
        self.thumbnail_size_slider: QSlider
        self.thumbnail_size_label: QLabel
        self.ui_scale_slider: QSlider
        self.ui_scale_label: QLabel
        self.animations_check: QCheckBox
        self.refresh_interval_spin: QSpinBox
        self.background_refresh_check: QCheckBox
        self.double_click_combo: QComboBox
        self.terminal_edit: QLineEdit

        # Performance tab widgets
        self.max_threads_spin: QSpinBox
        self.cache_memory_spin: QSpinBox
        self.cache_expiry_spin: QSpinBox

        # Applications tab widgets
        self.default_app_combo: QComboBox
        self.background_gui_apps_check: QCheckBox
        self.association_combos: dict[
            str, QComboBox
        ]  # Populated in create_associations_widget
        self.associations_widget: QWidget
        self.launchers_edit: QTextEdit
        self.validate_launchers_btn: QPushButton

        # Advanced tab widgets
        self.debug_mode_check: QCheckBox
        self.log_level_combo: QComboBox

        # Dialog widgets
        self.tab_widget: QTabWidget
        self.button_box: QDialogButtonBox
        self.import_btn: QPushButton
        self.export_btn: QPushButton
        self.reset_btn: QPushButton
        self.reset_category_btn: QPushButton

        self.setWindowTitle("ShotBot Preferences")
        self.setWindowIcon(QIcon())  # TODO: Add proper icon
        self.setModal(True)

        # Use QtWidgetMixin for window geometry
        # Third-party imports
        from PySide6.QtCore import QSize

        self.setup_window_geometry("settings_dialog", QSize(700, 600))

        # Setup UI
        self.setup_ui()

        # Load current settings
        self.load_current_settings()

        # Set initial tab
        self.set_initial_tab(initial_tab)

        # Connect signals
        self.connect_signals()

        self.logger.debug("Settings dialog initialized")

    def setup_ui(self) -> None:
        """Setup the user interface."""
        layout = QVBoxLayout(self)

        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Create tabs
        self.create_general_tab()
        self.create_performance_tab()
        self.create_applications_tab()
        self.create_advanced_tab()

        # Create button box
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        layout.addWidget(self.button_box)

        # Add additional buttons
        self.create_additional_buttons()

    def create_general_tab(self) -> None:
        """Create the general preferences tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Create scroll area for better organization
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

        _ = self.tab_widget.addTab(tab, "General")

    def create_performance_tab(self) -> None:
        """Create the performance settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

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

        _ = self.tab_widget.addTab(tab, "Performance")

    def create_applications_tab(self) -> None:
        """Create the applications settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

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
        self.associations_widget = self.create_associations_widget()
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

        _ = self.tab_widget.addTab(tab, "Applications")

    def create_associations_widget(self) -> QWidget:
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

    def create_advanced_tab(self) -> None:
        """Create the advanced settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

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
        settings_path_label.setStyleSheet(f"font-family: monospace; font-size: {design_system.typography.size_micro}px;")
        system_layout.addWidget(settings_path_label)

        scroll_layout.addWidget(system_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        _ = self.tab_widget.addTab(tab, "Advanced")

    def create_additional_buttons(self) -> None:
        """Create additional buttons for import/export and reset."""
        # Add custom buttons to button box
        self.import_btn = self.button_box.addButton(
            "Import...", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.export_btn = self.button_box.addButton(
            "Export...", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.reset_btn = self.button_box.addButton(
            "Reset to Defaults", QDialogButtonBox.ButtonRole.ResetRole
        )
        self.reset_category_btn = self.button_box.addButton(
            "Reset Current Tab", QDialogButtonBox.ButtonRole.ResetRole
        )

    def connect_signals(self) -> None:
        """Connect all signals and slots."""
        # Button box signals
        _ = self.button_box.accepted.connect(self.accept_changes)
        _ = self.button_box.rejected.connect(self.reject_changes)
        _ = self.button_box.clicked.connect(self.handle_button_click)

        # Setting change signals for live preview
        _ = self.thumbnail_size_slider.valueChanged.connect(
            self.update_thumbnail_preview  # pyright: ignore[reportAny]
        )
        _ = self.ui_scale_slider.valueChanged.connect(
            self.update_ui_scale_preview  # pyright: ignore[reportAny]
        )

        # Validation signals
        _ = self.validate_launchers_btn.clicked.connect(
            self.validate_custom_launchers  # pyright: ignore[reportAny]
        )

    def set_initial_tab(self, tab_name: str) -> None:
        """Set the initial tab to display."""
        tab_indices = {"general": 0, "performance": 1, "applications": 2, "advanced": 3}

        if tab_name in tab_indices:
            self.tab_widget.setCurrentIndex(tab_indices[tab_name])

    def load_current_settings(self) -> None:
        """Load current settings into the dialog controls."""
        # General tab
        self.thumbnail_size_slider.setValue(self.settings_manager.ui.get_thumbnail_size())
        self.update_thumbnail_preview()  # pyright: ignore[reportAny]

        # UI Scale - convert from float (0.8-1.5) to percent (80-150)
        ui_scale = self.settings_manager.ui.get_ui_scale()
        self.ui_scale_slider.setValue(int(ui_scale * 100))
        self.update_ui_scale_preview()  # pyright: ignore[reportAny]

        self.animations_check.setChecked(self.settings_manager.ui.get_enable_animations())

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

        self.terminal_edit.setText(self.settings_manager.launch.get_preferred_terminal())

        # Performance tab
        self.max_threads_spin.setValue(
            self.settings_manager.performance.get_max_thumbnail_threads()
        )
        self.cache_memory_spin.setValue(self.settings_manager.performance.get_max_cache_memory_mb())
        self.cache_expiry_spin.setValue(
            self.settings_manager.performance.get_cache_expiry_minutes()
        )

        # Applications tab
        self.default_app_combo.setCurrentText(self.settings_manager.launch.get_default_app())
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

        # Advanced tab
        self.debug_mode_check.setChecked(self.settings_manager.debug.get_debug_mode())
        self.log_level_combo.setCurrentText(self.settings_manager.debug.get_log_level())

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
            _ = QMessageBox.warning(self, "Validation Error", f"Invalid JSON format:\n{e}")

    def handle_button_click(self, button: QAbstractButton) -> None:
        """Handle custom button clicks."""
        if button == self.import_btn:
            self.import_settings()
        elif button == self.export_btn:
            self.export_settings()
        elif button == self.reset_btn:
            self.reset_all_settings()
        elif button == self.reset_category_btn:
            self.reset_current_category()
        elif button == self.button_box.button(QDialogButtonBox.StandardButton.Apply):
            self.apply_settings()

    def import_settings(self) -> None:
        """Import settings from file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Settings", "", "JSON Files (*.json);;All Files (*)"
        )

        if file_path:
            if self.settings_manager.import_settings(file_path):
                self.load_current_settings()
                _ = QMessageBox.information(
                    self, "Import Success", "Settings imported successfully."
                )
            else:
                _ = QMessageBox.warning(
                    self,
                    "Import Error",
                    "Failed to import settings. Check the file format.",
                )

    def export_settings(self) -> None:
        """Export settings to file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            "shotbot_settings.json",
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            if self.settings_manager.export_settings(file_path):
                _ = QMessageBox.information(
                    self, "Export Success", f"Settings exported to:\n{file_path}"
                )
            else:
                _ = QMessageBox.warning(self, "Export Error", "Failed to export settings.")

    def reset_all_settings(self) -> None:
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset All Settings",
            ("Are you sure you want to reset all settings to defaults?\n"
            "This action cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.settings_manager.reset_to_defaults()
            self.load_current_settings()
            _ = QMessageBox.information(
                self, "Reset Complete", "All settings have been reset to defaults."
            )

    def reset_current_category(self) -> None:
        """Reset current tab's settings to defaults."""
        tab_categories = {
            0: "preferences",  # General
            1: "performance",
            2: "applications",
            3: "advanced",
        }

        current_index = self.tab_widget.currentIndex()
        category = tab_categories.get(current_index)

        if category:
            reply = QMessageBox.question(
                self,
                "Reset Category",
                f"Reset all {category} settings to defaults?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.settings_manager.reset_category(category)
                if current_index == 0:
                    # General tab: also reset ui_scale (stored under "ui/" prefix,
                    # not "preferences/", so reset_category("preferences") misses it)
                    self.settings_manager.ui.set_ui_scale(1.0)
                    self.ui_scale_slider.setValue(100)
                    design_system.set_ui_scale(1.0)
                self.load_current_settings()
                _ = QMessageBox.information(
                    self,
                    "Reset Complete",
                    f"{category.title()} settings reset to defaults.",
                )

    def apply_settings(self) -> None:
        """Apply current settings without closing dialog."""
        self.save_settings()
        self.settings_applied.emit()
        _ = QMessageBox.information(
            self, "Settings Applied", "Settings have been applied successfully."
        )

    def accept_changes(self) -> None:
        """Accept and apply all changes."""
        self.save_settings()
        self.settings_applied.emit()
        self.accept()

    def reject_changes(self) -> None:
        """Reject all changes and close dialog."""
        # Restore original UI scale (revert live preview)
        design_system.set_ui_scale(self._original_ui_scale)
        self.reject()

    def save_settings(self) -> None:
        """Save all settings from dialog controls."""
        # General settings
        self.settings_manager.ui.set_thumbnail_size(self.thumbnail_size_slider.value())

        # UI Scale - convert from percent (80-150) to float (0.8-1.5)
        ui_scale = self.ui_scale_slider.value() / 100.0
        self.settings_manager.ui.set_ui_scale(ui_scale)
        # Update design system with new scale
        design_system.set_ui_scale(ui_scale)

        self.settings_manager.ui.set_enable_animations(self.animations_check.isChecked())

        self.settings_manager.refresh.set_refresh_interval(self.refresh_interval_spin.value())
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

        # Performance settings
        self.settings_manager.performance.set_max_thumbnail_threads(self.max_threads_spin.value())
        self.settings_manager.performance.set_max_cache_memory_mb(self.cache_memory_spin.value())
        self.settings_manager.performance.set_cache_expiry_minutes(self.cache_expiry_spin.value())

        # Application settings
        self.settings_manager.launch.set_default_app(self.default_app_combo.currentText())
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
            self.logger.warning(
                "Invalid custom launchers JSON, keeping existing settings"
            )

        # Advanced settings
        self.settings_manager.debug.set_debug_mode(self.debug_mode_check.isChecked())
        self.settings_manager.debug.set_log_level(self.log_level_combo.currentText())

        # Sync settings to disk
        self.settings_manager.sync()

        self.logger.info("Settings saved successfully")
        NotificationManager.success("Settings saved", timeout=TimeoutConfig.NOTIFICATION_SETTINGS_MS)

    # Override mixin event handlers with proper keyword parameter signatures
    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle close event with cleanup."""
        # Call parent implementation from QtWidgetMixin
        super().closeEvent(event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events with standard shortcuts."""
        # Call parent implementation from QtWidgetMixin
        super().keyPressEvent(event)
