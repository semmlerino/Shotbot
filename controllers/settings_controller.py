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
    from PySide6.QtWidgets import QSlider, QSplitter, QTabWidget

    # Local application imports
    from cache_manager import CacheManager
    from settings_dialog import SettingsDialog
    from settings_manager import SettingsManager


class GridWidget(Protocol):
    """Protocol for grid widgets that have size sliders.

    This protocol defines the minimal interface required from grid view widgets
    for settings management. All grid views inherit from BaseGridView which
    provides the size_slider attribute.
    """

    size_slider: QSlider  # QSlider for thumbnail size control


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
    settings_manager: SettingsManager
    cache_manager: CacheManager
    splitter: QSplitter
    tab_widget: QTabWidget
    shot_grid: GridWidget  # Grid widgets with size_slider attribute
    threede_shot_grid: GridWidget
    previous_shots_grid: GridWidget

    # Settings dialog reference
    _settings_dialog: SettingsDialog | None


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
            if hasattr(self.window.shot_grid, "size_slider"):
                self.window.shot_grid.size_slider.setValue(thumbnail_size)
            if hasattr(self.window.threede_shot_grid, "size_slider"):
                self.window.threede_shot_grid.size_slider.setValue(thumbnail_size)
            if hasattr(self.window.previous_shots_grid, "size_slider"):
                self.window.previous_shots_grid.size_slider.setValue(thumbnail_size)

            # Apply UI preferences
            self.apply_ui_settings()

            # Apply cache settings
            self.apply_cache_settings()

            self.logger.info("Settings loaded successfully")

        except Exception as e:
            self.logger.error(f"Error loading settings: {e}")
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
            if hasattr(self.window.shot_grid, "size_slider"):
                self.window.settings_manager.set_thumbnail_size(
                    self.window.shot_grid.size_slider.value()
                )

            # Sync to disk
            self.window.settings_manager.sync()

            self.logger.info("Settings saved successfully")

        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")

    def apply_ui_settings(self) -> None:
        """Apply UI settings from settings manager."""
        try:
            # Dead settings removed: grid_columns, show_tooltips, dark_theme
            # These were never implemented and just confused users
            self.logger.debug("UI settings applied")

        except Exception as e:
            self.logger.error(f"Error applying UI settings: {e}")

    def apply_cache_settings(self) -> None:
        """Apply cache settings from settings manager."""
        try:
            # Apply cache memory limit
            max_memory = self.window.settings_manager.get_max_cache_memory_mb()
            if hasattr(self.window.cache_manager, "set_memory_limit"):
                self.window.cache_manager.set_memory_limit(max_memory)

            # Apply cache expiry
            expiry_minutes = self.window.settings_manager.get_cache_expiry_minutes()
            if hasattr(self.window.cache_manager, "set_expiry_minutes"):
                self.window.cache_manager.set_expiry_minutes(expiry_minutes)

            self.logger.debug("Cache settings applied")

        except Exception as e:
            self.logger.error(f"Error applying cache settings: {e}")

    def show_preferences(self) -> None:
        """Show the preferences dialog."""
        # Lazy import to avoid circular dependencies - only needed when showing dialog
        from settings_dialog import SettingsDialog

        if self.window._settings_dialog is None:  # pyright: ignore[reportPrivateUsage]
            # MainWindow implements both SettingsTarget and QWidget protocols
            # Cast through object first to satisfy type checker
            parent_widget = cast("QWidget", cast("object", self.window))
            self.window._settings_dialog = SettingsDialog(  # pyright: ignore[reportPrivateUsage]
                self.window.settings_manager,
                parent_widget,
            )
            _ = self.window._settings_dialog.settings_applied.connect(  # pyright: ignore[reportPrivateUsage]
                self.on_settings_applied
            )

        if self.window._settings_dialog is not None:  # pyright: ignore[reportPrivateUsage,reportUnnecessaryComparison]
            self.window._settings_dialog.load_current_settings()  # pyright: ignore[reportPrivateUsage]
            self.window._settings_dialog.show()  # pyright: ignore[reportPrivateUsage]
            self.window._settings_dialog.raise_()  # pyright: ignore[reportPrivateUsage]
            self.window._settings_dialog.activateWindow()  # pyright: ignore[reportPrivateUsage]

    def on_settings_applied(self) -> None:
        """Handle settings being applied from preferences dialog."""
        # Reload and apply all settings
        self.apply_ui_settings()
        self.apply_cache_settings()

        # Update thumbnail sizes in grids
        thumbnail_size = self.window.settings_manager.get_thumbnail_size()
        # GridWidget protocol guarantees size_slider exists
        if hasattr(self.window.shot_grid, "size_slider"):
            self.window.shot_grid.size_slider.setValue(thumbnail_size)
        if hasattr(self.window.threede_shot_grid, "size_slider"):
            self.window.threede_shot_grid.size_slider.setValue(thumbnail_size)
        if hasattr(self.window.previous_shots_grid, "size_slider"):
            self.window.previous_shots_grid.size_slider.setValue(thumbnail_size)

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
                self.apply_ui_settings()
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
