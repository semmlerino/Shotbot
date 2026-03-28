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
import logging
from typing import TYPE_CHECKING, ClassVar

# Third-party imports
from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import override

# Local application imports
from managers.notification_manager import NotificationManager
from timeout_config import TimeoutConfig
from ui.design_system import design_system
from ui.qt_widget_mixin import QtWidgetMixin
from ui.settings_panels import (
    AdvancedSettingsPanel,
    ApplicationsSettingsPanel,
    GeneralSettingsPanel,
    PerformanceSettingsPanel,
)


if TYPE_CHECKING:
    # Local application imports
    from managers.settings_manager import SettingsManager

# Set up logger for this module
logger = logging.getLogger(__name__)


class SettingsDialog(QDialog, QtWidgetMixin):
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

        # Store original values for cancel/restore
        self._original_ui_scale: float = design_system.get_ui_scale()

        # Dialog widgets (set in setup_ui)
        self.tab_widget: QTabWidget
        self.button_box: QDialogButtonBox
        self.import_btn: QPushButton
        self.export_btn: QPushButton
        self.reset_btn: QPushButton
        self.reset_category_btn: QPushButton

        # Tab panel instances (set in setup_ui)
        self.general_panel: GeneralSettingsPanel
        self.performance_panel: PerformanceSettingsPanel
        self.applications_panel: ApplicationsSettingsPanel
        self.advanced_panel: AdvancedSettingsPanel

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

        logger.debug("Settings dialog initialized")

    def setup_ui(self) -> None:
        """Setup the user interface."""
        layout = QVBoxLayout(self)

        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Create tab panels
        self.general_panel = GeneralSettingsPanel(self.settings_manager, parent=self)
        self.performance_panel = PerformanceSettingsPanel(
            self.settings_manager, parent=self
        )
        self.applications_panel = ApplicationsSettingsPanel(
            self.settings_manager, parent=self
        )
        self.advanced_panel = AdvancedSettingsPanel(self.settings_manager, parent=self)

        _ = self.tab_widget.addTab(self.general_panel, "General")
        _ = self.tab_widget.addTab(self.performance_panel, "Performance")
        _ = self.tab_widget.addTab(self.applications_panel, "Applications")
        _ = self.tab_widget.addTab(self.advanced_panel, "Advanced")

        # Create button box
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        layout.addWidget(self.button_box)

        # Add additional buttons
        self.create_additional_buttons()

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

    def set_initial_tab(self, tab_name: str) -> None:
        """Set the initial tab to display."""
        tab_indices = {"general": 0, "performance": 1, "applications": 2, "advanced": 3}

        if tab_name in tab_indices:
            self.tab_widget.setCurrentIndex(tab_indices[tab_name])

    def load_current_settings(self) -> None:
        """Load current settings into the dialog controls."""
        self.general_panel.load_settings()
        self.performance_panel.load_settings()
        self.applications_panel.load_settings()
        self.advanced_panel.load_settings()

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
                _ = QMessageBox.warning(
                    self, "Export Error", "Failed to export settings."
                )

    def reset_all_settings(self) -> None:
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset All Settings",
            (
                "Are you sure you want to reset all settings to defaults?\n"
                "This action cannot be undone."
            ),
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
                    self.general_panel.ui_scale_slider.setValue(100)
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
        self.general_panel.save_settings()
        self.performance_panel.save_settings()
        self.applications_panel.save_settings()
        self.advanced_panel.save_settings()

        # Sync settings to disk
        self.settings_manager.sync()

        logger.info("Settings saved successfully")
        NotificationManager.success(
            "Settings saved", timeout=TimeoutConfig.NOTIFICATION_SETTINGS_MS
        )

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
