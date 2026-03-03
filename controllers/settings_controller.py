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

# Standard library imports
from typing import TYPE_CHECKING, Protocol, cast

# Third-party imports
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

# Local application imports
from config import Config
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtCore import QByteArray, QSize
    from PySide6.QtWidgets import QSplitter, QTabWidget

    # Local application imports
    from cache import CacheCoordinator
    from settings_dialog import SettingsDialog
    from settings_manager import SettingsManager


class SettingsTarget(Protocol):
    """Protocol defining the interface required by SettingsController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the SettingsController for proper operation. It includes window geometry
    methods, widget references, and layout management capabilities.
    """

    # Window geometry and state methods
    def restoreGeometry(self, geometry: QByteArray) -> bool: ...
    def saveGeometry(self) -> QByteArray: ...
    def restoreState(self, state: QByteArray) -> bool: ...
    def saveState(self) -> QByteArray: ...
    def isMaximized(self) -> bool: ...
    def showMaximized(self) -> None: ...

    # Overloaded resize signatures from QMainWindow
    def resize(self, w: int, h: int) -> None: ...
    def get_window_size(
        self,
    ) -> QSize | tuple[int, int]: ...  # Flexible return type for QSize or tuple

    # Widget references needed for settings
    settings_manager: SettingsManager  # skylos: ignore
    cache_coordinator: CacheCoordinator  # skylos: ignore
    splitter: QSplitter  # skylos: ignore
    tab_widget: QTabWidget  # skylos: ignore

    # Thumbnail size access methods
    def set_thumbnail_size(self, size: int) -> None: ...
    def get_thumbnail_size(self) -> int: ...

    # Settings dialog reference
    settings_dialog: SettingsDialog | None  # skylos: ignore


class SettingsController(LoggingMixin):
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
        self.logger.debug("SettingsController initialized")

    def load_settings(self) -> None:
        """Load settings from settings manager."""
        try:
            # Restore window geometry and state
            geometry = self.window.settings_manager.get_window_geometry()
            if not geometry.isEmpty():
                _ = self.window.restoreGeometry(geometry)

            state = self.window.settings_manager.get_window_state()
            if not state.isEmpty():
                _ = self.window.restoreState(state)

            # Restore splitter states
            main_splitter_state = self.window.settings_manager.get_splitter_state(
                "main"
            )
            if not main_splitter_state.isEmpty():
                _ = self.window.splitter.restoreState(main_splitter_state)

            # Apply window maximized state
            if self.window.settings_manager.is_window_maximized():
                self.window.showMaximized()

            # Restore current tab
            self.window.tab_widget.setCurrentIndex(
                self.window.settings_manager.get_current_tab()
            )

            # Apply thumbnail size
            thumbnail_size = self.window.settings_manager.get_thumbnail_size()
            self.window.set_thumbnail_size(thumbnail_size)

            # Apply cache settings
            self.apply_cache_settings()

            self.logger.info("Settings loaded successfully")

        except Exception:
            self.logger.exception("Error loading settings")
            # Fallback to default window size
            default_size = self.window.settings_manager.get_window_size()
            # get_window_size() returns QSize or tuple[int, int] per protocol
            # In practice, SettingsManager returns QSize, but handle both for robustness
            try:
                # Try QSize first (most likely)
                width = default_size.width()
                height = default_size.height()
                self.window.resize(width, height)
            except AttributeError:
                # Fallback to tuple handling or config defaults
                if isinstance(default_size, tuple) and len(default_size) == 2:
                    # Type checker can't narrow union type properly here, use cast
                    size_tuple = cast("tuple[int, int]", default_size)
                    width = int(size_tuple[0])
                    height = int(size_tuple[1])
                    self.window.resize(width, height)
                else:
                    # Final fallback to config defaults
                    width = int(Config.DEFAULT_WINDOW_WIDTH)
                    height = int(Config.DEFAULT_WINDOW_HEIGHT)
                    self.window.resize(width, height)

    def save_settings(self) -> None:
        """Save settings to settings manager."""
        try:
            # Save window geometry and state
            self.window.settings_manager.set_window_geometry(self.window.saveGeometry())
            self.window.settings_manager.set_window_state(self.window.saveState())
            self.window.settings_manager.set_window_maximized(self.window.isMaximized())

            # Save splitter states
            self.window.settings_manager.set_splitter_state(
                "main", self.window.splitter.saveState()
            )

            # Save current tab
            self.window.settings_manager.set_current_tab(
                self.window.tab_widget.currentIndex()
            )

            # Save thumbnail size
            self.window.settings_manager.set_thumbnail_size(
                self.window.get_thumbnail_size()
            )

            # Sync to disk
            self.window.settings_manager.sync()

            self.logger.info("Settings saved successfully")

        except Exception:
            self.logger.exception("Error saving settings")

    def apply_cache_settings(self) -> None:
        """Apply cache settings from settings manager."""
        try:
            # Apply cache expiry
            expiry_minutes = self.window.settings_manager.get_cache_expiry_minutes()
            if hasattr(self.window.cache_coordinator, "set_expiry_minutes"):
                self.window.cache_coordinator.set_expiry_minutes(expiry_minutes)

            self.logger.debug("Cache settings applied")

        except Exception:
            self.logger.exception("Error applying cache settings")

    def show_preferences(self) -> None:
        """Show the preferences dialog."""
        # Lazy import to avoid circular dependencies - only needed when showing dialog
        from settings_dialog import SettingsDialog

        if self.window.settings_dialog is None:
            # MainWindow implements both SettingsTarget and QWidget protocols
            # Cast through object first to satisfy type checker
            parent_widget = cast("QWidget", cast("object", self.window))
            self.window.settings_dialog = SettingsDialog(
                self.window.settings_manager,
                parent_widget,
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
        thumbnail_size = self.window.settings_manager.get_thumbnail_size()
        self.window.set_thumbnail_size(thumbnail_size)

        self.logger.info("Settings applied successfully")

    def import_settings(self) -> None:
        """Import settings from file."""
        # Cast to QWidget for dialog parent - MainWindow implements both protocols
        # Cast through object first to satisfy type checker
        parent_widget = cast("QWidget", cast("object", self.window))

        file_path, _ = QFileDialog.getOpenFileName(
            parent_widget,
            "Import Settings",
            "",
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            if self.window.settings_manager.import_settings(file_path):
                # Reload settings
                self.apply_cache_settings()
                _ = QMessageBox.information(
                    parent_widget,
                    "Import Success",
                    "Settings imported successfully.",
                )
            else:
                _ = QMessageBox.warning(
                    parent_widget,
                    "Import Error",
                    "Failed to import settings. Check the file format.",
                )

    def export_settings(self) -> None:
        """Export settings to file."""
        # Cast to QWidget for dialog parent - MainWindow implements both protocols
        # Cast through object first to satisfy type checker
        parent_widget = cast("QWidget", cast("object", self.window))

        file_path, _ = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Settings",
            "shotbot_settings.json",
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            if self.window.settings_manager.export_settings(file_path):
                _ = QMessageBox.information(
                    parent_widget,
                    "Export Success",
                    f"Settings exported to:\n{file_path}",
                )
            else:
                _ = QMessageBox.warning(
                    parent_widget,
                    "Export Error",
                    "Failed to export settings.",
                )

    def reset_layout(self) -> None:
        """Reset window layout to defaults."""
        # Cast to QWidget for dialog parent - MainWindow implements both protocols
        # Cast through object first to satisfy type checker
        parent_widget = cast("QWidget", cast("object", self.window))

        reply = QMessageBox.question(
            parent_widget,
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
            self.window.splitter.setSizes([840, 360])  # 70/30 split

            self.logger.info("Layout reset to defaults")
