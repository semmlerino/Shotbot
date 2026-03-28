"""Settings controller for MainWindow refactoring.

This module provides the SettingsController class which handles all settings-related
functionality that was previously embedded in the MainWindow class. This is the first
step in the MainWindow refactoring plan, focusing on extracting the safest,
lowest-coupling functionality.

The SettingsController manages:
- Loading and saving application settings
- Applying UI and cache settings
- Managing preferences dialog
- Handling settings import/export
- Layout reset functionality

This controller uses dependency injection through the SettingsTarget protocol
to access the minimal required interface from MainWindow, enabling clean
separation of concerns and easier testing.
"""

from __future__ import annotations

import logging

# Standard library imports
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtWidgets import (  # QWidget used in cast()
    QFileDialog,
    QMessageBox,
    QWidget,
)

# Local application imports
from config import Config


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Local application imports
    from protocols import SettingsTarget


@final
class SettingsController:
    """Controller for managing all settings-related functionality.

    This controller encapsulates all settings operations that were previously
    part of MainWindow, providing a clean interface for settings management.
    It uses composition and dependency injection to minimize coupling with
    the MainWindow.

    Attributes:
        window: The target window that implements SettingsTarget protocol

    """

    def __init__(self, window: SettingsTarget) -> None:
        """Initialize the settings controller.

        Args:
            window: The window object that provides the SettingsTarget interface

        """
        super().__init__()
        self.window: SettingsTarget = window
        # MainWindow implements both SettingsTarget and QWidget protocols
        # Cast through object first to satisfy type checker
        self._window_widget: QWidget = cast("QWidget", cast("object", self.window))
        logger.debug("SettingsController initialized")

    def load_settings(self) -> None:
        """Load settings from settings manager."""
        # Geometry
        try:
            geometry = self.window.settings_manager.window.get_window_geometry()
            if not geometry.isEmpty():
                _ = self.window.restoreGeometry(geometry)
        except Exception:
            logger.exception("Error restoring window geometry")
            default_size = self.window.settings_manager.window.get_window_size()
            self.window.resize(default_size.width(), default_size.height())

        # Window state
        try:
            state = self.window.settings_manager.window.get_window_state()
            if not state.isEmpty():
                _ = self.window.restoreState(state)
        except Exception:
            logger.exception("Error restoring window state")

        # Splitter
        try:
            main_splitter_state = (
                self.window.settings_manager.window.get_splitter_state("main")
            )
            if not main_splitter_state.isEmpty():
                _ = self.window.restore_splitter_state(main_splitter_state)
        except Exception:
            logger.exception("Error restoring splitter state")

        # Maximized state
        try:
            if self.window.settings_manager.window.is_window_maximized():
                self.window.showMaximized()
        except Exception:
            logger.exception("Error restoring maximized state")

        # Tab index
        try:
            self.window.set_current_tab(
                self.window.settings_manager.window.get_current_tab()
            )
        except Exception:
            logger.exception("Error restoring tab index")

        # Thumbnail size
        try:
            thumbnail_size = self.window.settings_manager.ui.get_thumbnail_size()
            self.window.set_thumbnail_size(thumbnail_size)
        except Exception:
            logger.exception("Error restoring thumbnail size")

        # Cache settings
        try:
            self.apply_cache_settings()
        except Exception:
            logger.exception("Error applying cache settings")

        logger.info("Settings loaded")

    def save_settings(self) -> None:
        """Save settings to settings manager."""
        try:
            # Save window geometry and state
            self.window.settings_manager.window.set_window_geometry(
                self.window.saveGeometry()
            )
            self.window.settings_manager.window.set_window_state(
                self.window.saveState()
            )
            self.window.settings_manager.window.set_window_maximized(
                self.window.isMaximized()
            )

            # Save splitter states
            self.window.settings_manager.window.set_splitter_state(
                "main", self.window.get_splitter_state()
            )

            # Save current tab
            self.window.settings_manager.window.set_current_tab(
                self.window.get_current_tab()
            )

            # Save thumbnail size
            self.window.settings_manager.ui.set_thumbnail_size(
                self.window.get_thumbnail_size()
            )

            # Sync to disk
            self.window.settings_manager.sync()

            logger.info("Settings saved successfully")

        except Exception:
            logger.exception("Error saving settings")

    def apply_cache_settings(self) -> None:
        """Apply cache settings from settings manager."""
        try:
            # Apply cache expiry
            expiry_minutes = (
                self.window.settings_manager.performance.get_cache_expiry_minutes()
            )
            self.window.cache_coordinator.set_expiry_minutes(expiry_minutes)

            logger.debug("Cache settings applied")

        except Exception:
            logger.exception("Error applying cache settings")

    def show_preferences(self) -> None:
        """Show the preferences dialog."""
        # Lazy import to avoid circular dependencies - only needed when showing dialog
        from ui.settings_dialog import SettingsDialog

        if self.window.settings_dialog is None:
            self.window.settings_dialog = SettingsDialog(
                self.window.settings_manager,
                self._window_widget,
            )
            _ = self.window.settings_dialog.settings_applied.connect(
                self.on_settings_applied
            )

        self.window.settings_dialog.load_current_settings()
        self.window.settings_dialog.show()
        self.window.settings_dialog.raise_()
        self.window.settings_dialog.activateWindow()

    def on_settings_applied(self) -> None:
        """Handle settings being applied from preferences dialog."""
        # Reload and apply all settings
        self.apply_cache_settings()

        # Update thumbnail sizes in grids
        thumbnail_size = self.window.settings_manager.ui.get_thumbnail_size()
        self.window.set_thumbnail_size(thumbnail_size)

        logger.info("Settings applied successfully")

    def import_settings(self) -> None:
        """Import settings from file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self._window_widget,
            "Import Settings",
            "",
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            if self.window.settings_manager.import_settings(file_path):
                # Reload settings
                self.apply_cache_settings()
                _ = QMessageBox.information(
                    self._window_widget,
                    "Import Success",
                    "Settings imported successfully.",
                )
            else:
                _ = QMessageBox.warning(
                    self._window_widget,
                    "Import Error",
                    "Failed to import settings. Check the file format.",
                )

    def export_settings(self) -> None:
        """Export settings to file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self._window_widget,
            "Export Settings",
            "shotbot_settings.json",
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            if self.window.settings_manager.export_settings(file_path):
                _ = QMessageBox.information(
                    self._window_widget,
                    "Export Success",
                    f"Settings exported to:\n{file_path}",
                )
            else:
                _ = QMessageBox.warning(
                    self._window_widget,
                    "Export Error",
                    "Failed to export settings.",
                )

    def reset_layout(self) -> None:
        """Reset window layout to defaults."""
        reply = QMessageBox.question(
            self._window_widget,
            "Reset Layout",
            "Reset window layout to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Reset window size - call with both width and height
            self.window.resize(
                Config.DEFAULT_WINDOW_WIDTH, Config.DEFAULT_WINDOW_HEIGHT
            )

            # Reset splitter
            self.window.reset_splitter_sizes([840, 360])  # 70/30 split

            logger.info("Layout reset to defaults")
