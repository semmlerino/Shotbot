"""Settings management for ShotBot application.

This module provides a comprehensive settings management system with persistent storage,
type safety, validation, and migration support. The SettingsManager centralizes all
application preferences and provides a clean API for getting and setting values.

Key Features:
    - Type-safe getter/setter methods with validation
    - Automatic migration from old settings format
    - Default values for all settings with fallbacks
    - QSettings integration for cross-platform persistence
    - Settings organization into logical categories
    - Import/export functionality for settings backup

Architecture:
    The SettingsManager acts as a facade over QSettings, providing a strongly-typed
    interface while maintaining backward compatibility. Settings are organized into
    categories (window, preferences, performance, etc.) with validation and defaults.

Settings Categories:
    - Window: Geometry, splitter positions, tab selection, dock states
    - Preferences: Refresh intervals, UI behavior, file handling
    - Performance: Threading, cache limits, concurrent operations
    - Applications: Default apps, custom launchers, file associations
    - Advanced: Debug options, experimental features

Examples:
    Basic usage:
        >>> settings = SettingsManager()
        >>> settings.set_window_geometry(window.saveGeometry())
        >>> geometry = settings.get_window_geometry()
        >>> window.restoreGeometry(geometry)

    Type-safe access:
        >>> refresh_interval = settings.get_refresh_interval()  # Returns int
        >>> settings.set_refresh_interval(120)  # Validates range
        >>> settings.set_thumbnail_size(300)  # Validates against min/max

    Category access:
        >>> window_settings = settings.get_category("window")
        >>> settings.export_settings("/path/to/backup.json")
        >>> settings.import_settings("/path/to/backup.json")

Type Safety:
    All methods include comprehensive type annotations and runtime validation.
    Invalid values are rejected with clear error messages and safe fallbacks.
"""

from __future__ import annotations

# Standard library imports
import json
import os
import tempfile
from pathlib import Path
from typing import cast, final

# Third-party imports
from PySide6.QtCore import QByteArray, QObject, QSettings, QSize, Signal

# Local application imports
from config import Config
from logging_mixin import LoggingMixin


# Set up logger for this module


@final
class SettingsManager(LoggingMixin, QObject):
    """Manages application settings with type safety and persistence.

    Provides a comprehensive settings management system with automatic
    migration, validation, and organized access to application preferences.
    """

    # Signals for settings changes
    settings_changed = Signal(str, object)  # Setting key, new value
    category_changed = Signal(str)  # Category name
    settings_reset = Signal()  # All settings reset to defaults

    def __init__(
        self, organization: str = "ShotBot", application: str = "ShotBot"
    ) -> None:
        """Initialize settings manager.

        Args:
            organization: Organization name for QSettings
            application: Application name for QSettings
        """
        super().__init__()
        self.settings = QSettings(organization, application)

        # Initialize settings with defaults if first run
        self._initialize_defaults()

        # Migrate old settings if needed
        self._migrate_old_settings()

        self.logger.info(f"Settings manager initialized: {self.settings.fileName()}")

    def _initialize_defaults(self) -> None:
        """Initialize default values for all settings if they don't exist."""
        defaults = self._get_default_settings()

        for category, settings_dict in defaults.items():
            for key, setting_value in settings_dict.items():
                full_key = f"{category}/{key}"
                if not self.settings.contains(full_key):
                    self.settings.setValue(full_key, setting_value)
                    self.logger.debug(
                        f"Initialized default setting: {full_key} = {setting_value}"
                    )

    def _get_default_settings(self) -> dict[str, dict[str, object]]:
        """Get default settings organized by category."""
        return {
            "window": {
                "geometry": QByteArray(),
                "state": QByteArray(),
                "splitter_main": QByteArray(),
                "splitter_right": QByteArray(),
                "current_tab": 0,
                "maximized": False,
                "size": QSize(
                    Config.DEFAULT_WINDOW_WIDTH, Config.DEFAULT_WINDOW_HEIGHT
                ),
            },
            "preferences": {
                "refresh_interval": Config.CACHE_REFRESH_INTERVAL_MINUTES,
                "background_refresh": Config.ENABLE_BACKGROUND_REFRESH,
                "thumbnail_size": Config.DEFAULT_THUMBNAIL_SIZE,
                "show_status_tips": True,
                "auto_refresh_on_focus": True,
                "confirm_delete": True,
                "remember_last_directory": True,
                "last_directory": str(Config.SHOWS_ROOT),
                "show_hidden_files": False,
                "auto_launch_delay": 0,  # Seconds before auto-launching application
                "preferred_terminal": "gnome-terminal",  # Default terminal emulator
                "double_click_action": "launch_default",  # or "show_info"
            },
            "performance": {
                "max_thumbnail_threads": Config.MAX_THUMBNAIL_THREADS,
                "max_cache_memory_mb": Config.MAX_THUMBNAIL_MEMORY_MB,
                "cache_expiry_minutes": Config.CACHE_EXPIRY_MINUTES,
                "max_concurrent_operations": 4,
                "enable_animations": True,
                "lazy_loading": True,
                "preload_thumbnails": True,
                "background_priority": "low",  # Thread priority for background operations
                "cache_compression": True,
                "progressive_loading": True,
            },
            "applications": {
                "default_app": Config.DEFAULT_APP,
                "custom_launchers": [],  # List of custom launcher definitions
                "file_associations": dict(Config.APPS),  # Copy default apps
                "launch_in_terminal": False,
                "terminal_command": "gnome-terminal",
                "environment_variables": {},  # Additional env vars for launches
                "working_directory": "",  # Default working directory
                "background_gui_apps": False,  # Close terminal after launching GUI apps
            },
            "ui": {
                "grid_columns": Config.GRID_COLUMNS,
                "show_grid_lines": False,
                "show_tooltips": True,
                "icon_text_visible": True,
                "status_bar_visible": True,
                "toolbar_visible": True,
                "compact_mode": False,
                "dark_theme": False,
                "font_size": 9,
                "ui_scale": 1.0,  # UI scale factor (0.8 to 1.5, default 1.0 = 100%)
                "thumbnail_spacing": Config.THUMBNAIL_SPACING,
                "selection_highlight": True,
                "hover_effects": True,
                "expanded_sections": {
                    "files": False,  # Files section default collapsed
                    "3de": True,  # DCC sections default expanded
                    "nuke": True,
                    "maya": True,
                    "rv": True,
                },
            },
            "advanced": {
                "debug_mode": False,
                "log_level": "INFO",
                "enable_profiling": False,
                "crash_reporting": True,
                "beta_features": False,
                "cache_debug": False,
                "threading_debug": False,
                "memory_monitoring": False,
                "performance_overlay": False,
                "experimental_caching": False,
            },
        }

    def _migrate_old_settings(self) -> None:
        """Migrate settings from old format to new organized format."""
        # Check if migration is needed
        if self.settings.contains("migration_version"):
            return

        self.logger.info("Migrating settings to new format...")

        # Migrate any existing loose settings to organized structure
        old_keys = [
            ("window_geometry", "window/geometry"),
            ("window_state", "window/state"),
            ("thumbnail_size", "preferences/thumbnail_size"),
            ("refresh_interval", "preferences/refresh_interval"),
            ("last_directory", "preferences/last_directory"),
        ]

        for old_key, new_key in old_keys:
            if self.settings.contains(old_key):
                value = cast("object", self.settings.value(old_key))
                self.settings.setValue(new_key, value)
                self.settings.remove(old_key)
                self.logger.debug(f"Migrated setting: {old_key} -> {new_key}")

        # Mark migration as complete
        self.settings.setValue("migration_version", 1)
        self.logger.info("Settings migration completed")

    # Window Settings
    def get_window_geometry(self) -> QByteArray:
        """Get window geometry."""
        value = self.settings.value("window/geometry", QByteArray(), type=QByteArray)
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_window_geometry(self, geometry: QByteArray) -> None:
        """Set window geometry."""
        self.settings.setValue("window/geometry", geometry)
        self.settings_changed.emit("window/geometry", geometry)

    def get_window_state(self) -> QByteArray:
        """Get window state (dock widgets, toolbars)."""
        value = self.settings.value("window/state", QByteArray(), type=QByteArray)
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_window_state(self, state: QByteArray) -> None:
        """Set window state."""
        self.settings.setValue("window/state", state)
        self.settings_changed.emit("window/state", state)

    def get_window_size(self) -> QSize:
        """Get window size."""
        default_size = QSize(Config.DEFAULT_WINDOW_WIDTH, Config.DEFAULT_WINDOW_HEIGHT)
        value = self.settings.value("window/size", default_size, type=QSize)
        return value if isinstance(value, QSize) else default_size

    def set_window_size(self, size: QSize) -> None:
        """Set window size."""
        # Validate minimum size
        min_width = max(size.width(), Config.MIN_WINDOW_WIDTH)
        min_height = max(size.height(), Config.MIN_WINDOW_HEIGHT)
        validated_size = QSize(min_width, min_height)

        self.settings.setValue("window/size", validated_size)
        self.settings_changed.emit("window/size", validated_size)

    def get_splitter_state(self, splitter_name: str) -> QByteArray:
        """Get splitter state by name."""
        key = f"window/splitter_{splitter_name}"
        value = self.settings.value(key, QByteArray(), type=QByteArray)
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_splitter_state(self, splitter_name: str, state: QByteArray) -> None:
        """Set splitter state by name."""
        key = f"window/splitter_{splitter_name}"
        self.settings.setValue(key, state)
        self.settings_changed.emit(key, state)

    def get_current_tab(self) -> int:
        """Get current tab index."""
        value = self.settings.value("window/current_tab", 0, type=int)
        return value if isinstance(value, int) else 0

    def set_current_tab(self, index: int) -> None:
        """Set current tab index."""
        validated_index = max(0, index)  # Ensure non-negative
        self.settings.setValue("window/current_tab", validated_index)
        self.settings_changed.emit("window/current_tab", validated_index)

    def is_window_maximized(self) -> bool:
        """Check if window was maximized."""
        value = self.settings.value("window/maximized", False, type=bool)
        return value if isinstance(value, bool) else False

    def set_window_maximized(self, maximized: bool) -> None:
        """Set window maximized state."""
        self.settings.setValue("window/maximized", maximized)
        self.settings_changed.emit("window/maximized", maximized)

    # Preference Settings
    def get_refresh_interval(self) -> int:
        """Get refresh interval in minutes."""
        value = self.settings.value(
            "preferences/refresh_interval",
            Config.CACHE_REFRESH_INTERVAL_MINUTES,
            type=int,
        )
        return (
            value if isinstance(value, int) else Config.CACHE_REFRESH_INTERVAL_MINUTES
        )

    def set_refresh_interval(self, minutes: int) -> None:
        """Set refresh interval in minutes."""
        # Validate range (1 minute to 24 hours)
        validated_minutes = max(1, min(minutes, 1440))
        self.settings.setValue("preferences/refresh_interval", validated_minutes)
        self.settings_changed.emit("preferences/refresh_interval", validated_minutes)

    def get_background_refresh(self) -> bool:
        """Get background refresh enabled state."""
        value = self.settings.value(
            "preferences/background_refresh",
            Config.ENABLE_BACKGROUND_REFRESH,
            type=bool,
        )
        return value if isinstance(value, bool) else Config.ENABLE_BACKGROUND_REFRESH

    def set_background_refresh(self, enabled: bool) -> None:
        """Set background refresh enabled state."""
        self.settings.setValue("preferences/background_refresh", enabled)
        self.settings_changed.emit("preferences/background_refresh", enabled)

    def get_thumbnail_size(self) -> int:
        """Get thumbnail size."""
        value = self.settings.value(
            "preferences/thumbnail_size", Config.DEFAULT_THUMBNAIL_SIZE, type=int
        )
        return value if isinstance(value, int) else Config.DEFAULT_THUMBNAIL_SIZE

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size with validation."""
        # Validate against min/max bounds
        validated_size = max(
            Config.MIN_THUMBNAIL_SIZE, min(size, Config.MAX_THUMBNAIL_SIZE)
        )
        self.settings.setValue("preferences/thumbnail_size", validated_size)
        self.settings_changed.emit("preferences/thumbnail_size", validated_size)

    def get_last_directory(self) -> str:
        """Get last used directory."""
        value = self.settings.value(
            "preferences/last_directory", str(Config.SHOWS_ROOT), type=str
        )
        return value if isinstance(value, str) else str(Config.SHOWS_ROOT)

    def set_last_directory(self, directory: str) -> None:
        """Set last used directory."""
        # Validate directory exists
        if Path(directory).is_dir():
            self.settings.setValue("preferences/last_directory", directory)
            self.settings_changed.emit("preferences/last_directory", directory)

    def get_preferred_terminal(self) -> str:
        """Get preferred terminal emulator."""
        value = self.settings.value(
            "preferences/preferred_terminal", "gnome-terminal", type=str
        )
        return value if isinstance(value, str) else "gnome-terminal"

    def set_preferred_terminal(self, terminal: str) -> None:
        """Set preferred terminal emulator."""
        self.settings.setValue("preferences/preferred_terminal", terminal)
        self.settings_changed.emit("preferences/preferred_terminal", terminal)

    def get_double_click_action(self) -> str:
        """Get double click action."""
        value = self.settings.value(
            "preferences/double_click_action", "launch_default", type=str
        )
        return value if isinstance(value, str) else "launch_default"

    def set_double_click_action(self, action: str) -> None:
        """Set double click action."""
        valid_actions = ["launch_default", "show_info", "open_folder"]
        if action in valid_actions:
            self.settings.setValue("preferences/double_click_action", action)
            self.settings_changed.emit("preferences/double_click_action", action)

    # Performance Settings
    def get_max_thumbnail_threads(self) -> int:
        """Get maximum thumbnail loading threads."""
        value = self.settings.value(
            "performance/max_thumbnail_threads", Config.MAX_THUMBNAIL_THREADS, type=int
        )
        return value if isinstance(value, int) else Config.MAX_THUMBNAIL_THREADS

    def set_max_thumbnail_threads(self, threads: int) -> None:
        """Set maximum thumbnail loading threads."""
        # Validate range (1-16 threads)
        validated_threads = max(1, min(threads, 16))
        self.settings.setValue("performance/max_thumbnail_threads", validated_threads)
        self.settings_changed.emit(
            "performance/max_thumbnail_threads", validated_threads
        )

    def get_max_cache_memory_mb(self) -> int:
        """Get maximum cache memory in MB."""
        value = self.settings.value(
            "performance/max_cache_memory_mb", Config.MAX_THUMBNAIL_MEMORY_MB, type=int
        )
        return value if isinstance(value, int) else Config.MAX_THUMBNAIL_MEMORY_MB

    def set_max_cache_memory_mb(self, memory_mb: int) -> None:
        """Set maximum cache memory in MB."""
        # Validate range (10MB to 1GB)
        validated_memory = max(10, min(memory_mb, 1024))
        self.settings.setValue("performance/max_cache_memory_mb", validated_memory)
        self.settings_changed.emit("performance/max_cache_memory_mb", validated_memory)

    def get_cache_expiry_minutes(self) -> int:
        """Get cache expiry time in minutes."""
        value = self.settings.value(
            "performance/cache_expiry_minutes", Config.CACHE_EXPIRY_MINUTES, type=int
        )
        return value if isinstance(value, int) else Config.CACHE_EXPIRY_MINUTES

    def set_cache_expiry_minutes(self, minutes: int) -> None:
        """Set cache expiry time in minutes."""
        # Validate range (5 minutes to 1 week)
        validated_minutes = max(5, min(minutes, 10080))
        self.settings.setValue("performance/cache_expiry_minutes", validated_minutes)
        self.settings_changed.emit(
            "performance/cache_expiry_minutes", validated_minutes
        )

    def get_enable_animations(self) -> bool:
        """Get animation enabled state."""
        value = self.settings.value("performance/enable_animations", True, type=bool)
        return value if isinstance(value, bool) else True

    def set_enable_animations(self, enabled: bool) -> None:
        """Set animation enabled state."""
        self.settings.setValue("performance/enable_animations", enabled)
        self.settings_changed.emit("performance/enable_animations", enabled)

    # Application Settings
    def get_default_app(self) -> str:
        """Get default application."""
        value = self.settings.value(
            "applications/default_app", Config.DEFAULT_APP, type=str
        )
        return value if isinstance(value, str) else Config.DEFAULT_APP

    def set_default_app(self, app: str) -> None:
        """Set default application."""
        # Validate app exists in available apps
        available_apps = list(Config.APPS.keys())
        if app in available_apps:
            self.settings.setValue("applications/default_app", app)
            self.settings_changed.emit("applications/default_app", app)

    def get_file_associations(self) -> dict[str, str]:
        """Get file type associations."""
        default_associations = dict(Config.APPS)
        stored_value = self.settings.value(
            "applications/file_associations", default_associations
        )
        # Type guard: QSettings.value can return various types depending on stored data
        if isinstance(stored_value, dict):
            # Ensure all keys and values are strings
            # Cast to help type checker understand the dict iteration
            typed_dict = cast("dict[object, object]", stored_value)
            return {str(k): str(v) for k, v in typed_dict.items()}
        return default_associations

    def set_file_associations(self, associations: dict[str, str]) -> None:
        """Set file type associations."""
        self.settings.setValue("applications/file_associations", associations)
        self.settings_changed.emit("applications/file_associations", associations)

    def get_background_gui_apps(self) -> bool:
        """Get whether to run GUI apps in background (close terminal immediately).

        When True, launching 3DE, Nuke, Maya etc. will background the process
        and close the terminal window immediately, reducing desktop clutter.
        """
        value = self.settings.value("applications/background_gui_apps", False, type=bool)
        return bool(value)

    def set_background_gui_apps(self, enabled: bool) -> None:
        """Set whether to run GUI apps in background."""
        self.settings.setValue("applications/background_gui_apps", enabled)
        self.settings_changed.emit("applications/background_gui_apps", enabled)

    def get_custom_launchers(self) -> list[dict[str, object]]:
        """Get custom launcher definitions."""
        stored_value = self.settings.value(
            "applications/custom_launchers", [], type=list
        )
        # Type guard: QSettings.value can return various types
        if isinstance(stored_value, list):
            # Ensure each item is a dict and cast for type safety
            typed_list = cast("list[object]", stored_value)
            return [
                cast("dict[str, object]", item)
                for item in typed_list
                if isinstance(item, dict)
            ]
        return []

    def set_custom_launchers(self, launchers: list[dict[str, object]]) -> None:
        """Set custom launcher definitions."""
        self.settings.setValue("applications/custom_launchers", launchers)
        self.settings_changed.emit("applications/custom_launchers", launchers)

    # UI Settings
    # Dead settings removed: grid_columns, show_tooltips
    # These were never applied by settings_controller.py

    def get_dark_theme(self) -> bool:
        """Get dark theme setting."""
        value = self.settings.value("ui/dark_theme", False, type=bool)
        return bool(value) if isinstance(value, bool) else False

    def set_dark_theme(self, enabled: bool) -> None:
        """Set dark theme setting."""
        self.settings.setValue("ui/dark_theme", enabled)
        self.settings_changed.emit("ui/dark_theme", enabled)

    def get_ui_scale(self) -> float:
        """Get UI scale factor.

        Returns:
            Scale factor (0.8 to 1.5, default 1.0 = 100%)
        """
        value = self.settings.value("ui/ui_scale", 1.0, type=float)
        if isinstance(value, (int, float)):
            # Clamp to valid range
            return max(0.8, min(float(value), 1.5))
        return 1.0

    def set_ui_scale(self, scale: float) -> None:
        """Set UI scale factor.

        Args:
            scale: Scale factor (0.8 to 1.5)
        """
        # Validate and clamp range
        validated_scale = max(0.8, min(scale, 1.5))
        self.settings.setValue("ui/ui_scale", validated_scale)
        self.settings_changed.emit("ui/ui_scale", validated_scale)

    def get_expanded_sections(self) -> dict[str, bool]:
        """Get expanded state for all sections."""
        default_sections = {
            "files": False,
            "3de": True,
            "nuke": True,
            "maya": True,
            "rv": True,
        }
        stored_value = self.settings.value("ui/expanded_sections", default_sections)
        if isinstance(stored_value, dict):
            typed_dict = cast("dict[object, object]", stored_value)
            return {str(k): bool(v) for k, v in typed_dict.items()}
        return default_sections

    def set_section_expanded(self, section_id: str, expanded: bool) -> None:
        """Set expanded state for a single section."""
        sections = self.get_expanded_sections()
        sections[section_id] = expanded
        self.settings.setValue("ui/expanded_sections", sections)
        self.settings_changed.emit("ui/expanded_sections", sections)

    def is_section_expanded(self, section_id: str) -> bool:
        """Check if a section is expanded.

        Args:
            section_id: Section identifier (e.g., "files", "3de", "nuke")

        Returns:
            True if section is expanded, False otherwise
        """
        sections = self.get_expanded_sections()
        # Default to False for unknown sections
        return sections.get(section_id, False)

    # Advanced Settings
    def get_debug_mode(self) -> bool:
        """Get debug mode state."""
        value = self.settings.value("advanced/debug_mode", False, type=bool)
        return value if isinstance(value, bool) else False

    def set_debug_mode(self, enabled: bool) -> None:
        """Set debug mode state."""
        self.settings.setValue("advanced/debug_mode", enabled)
        self.settings_changed.emit("advanced/debug_mode", enabled)

    def get_log_level(self) -> str:
        """Get logging level."""
        value = self.settings.value("advanced/log_level", "INFO", type=str)
        return value if isinstance(value, str) else "INFO"

    def set_log_level(self, level: str) -> None:
        """Set logging level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level in valid_levels:
            self.settings.setValue("advanced/log_level", level)
            self.settings_changed.emit("advanced/log_level", level)

    # Category Access
    def get_category(self, category: str) -> dict[str, object]:
        """Get all settings for a category."""
        category_settings: dict[str, object] = {}

        # Start a group for the category
        self.settings.beginGroup(category)

        try:
            # Get all keys in this category
            for key in self.settings.childKeys():
                setting_value = cast("object", self.settings.value(key))
                category_settings[key] = setting_value
        finally:
            self.settings.endGroup()

        return category_settings

    def set_category(self, category: str, settings_dict: dict[str, object]) -> None:
        """Set all settings for a category."""
        self.settings.beginGroup(category)

        try:
            for key, setting_value in settings_dict.items():
                self.settings.setValue(key, setting_value)
        finally:
            self.settings.endGroup()

        self.category_changed.emit(category)

    # Bulk Operations
    def export_settings(self, file_path: str) -> bool:
        """Export all settings to JSON file.

        Uses atomic write pattern (temp file + rename) to prevent file
        corruption if disk becomes full or write is interrupted.
        """
        temp_fd = None
        temp_path = None
        try:
            all_settings: dict[str, dict[str, object]] = {}

            # Get all categories
            categories = [
                "window",
                "preferences",
                "performance",
                "applications",
                "ui",
                "advanced",
            ]

            for category in categories:
                all_settings[category] = self.get_category(category)

            # Atomic write: write to temp file in same directory, then rename
            target_path = Path(file_path)
            target_dir = target_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)

            # Create temp file in same directory (ensures same filesystem for rename)
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=f".{target_path.name}.",
                dir=str(target_dir),
            )

            # Write to temp file
            with os.fdopen(temp_fd, "w") as f:
                temp_fd = None  # fdopen takes ownership
                json.dump(all_settings, f, indent=2, default=str)

            # Atomic rename (POSIX guarantees this is atomic on same filesystem)
            _ = Path(temp_path).replace(file_path)
            temp_path = None  # Successfully moved

            self.logger.info(f"Settings exported to: {file_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to export settings: {e}")
            # Clean up temp file on error
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
            if temp_path is not None:
                try:
                    Path(temp_path).unlink()
                except OSError:
                    pass
            return False

    def import_settings(self, file_path: str) -> bool:
        """Import settings from JSON file."""
        try:
            with Path(file_path).open() as f:
                # json.load() is typed as returning Any in type stubs since JSON structure
                # is dynamic. We annotate as object and immediately narrow with type guard.
                loaded_data: object = json.load(f)

            # Type guard: ensure we have a dict at the top level
            if not isinstance(loaded_data, dict):
                self.logger.error("Invalid settings file: not a dictionary")
                return False

            # Cast after type guard to help type checker
            settings_data = cast("dict[str, object]", loaded_data)

            # Import each category
            for category_name, category_data in settings_data.items():
                if isinstance(category_data, dict):
                    # Type-safe conversion: ensure all values are valid
                    category_dict = cast("dict[str, object]", category_data)
                    settings_dict: dict[str, object] = {
                        str(k): v for k, v in category_dict.items()
                    }
                    self.set_category(str(category_name), settings_dict)

            self.logger.info(f"Settings imported from: {file_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to import settings: {e}")
            return False

    def reset_to_defaults(self) -> None:
        """Reset all settings to default values."""
        # Clear all existing settings
        self.settings.clear()

        # Reinitialize with defaults
        self._initialize_defaults()

        self.logger.info("All settings reset to defaults")
        self.settings_reset.emit()

    def reset_category(self, category: str) -> None:
        """Reset a specific category to defaults."""
        defaults = self._get_default_settings()

        if category in defaults:
            self.set_category(category, defaults[category])
            self.logger.info(f"Category '{category}' reset to defaults")
            self.category_changed.emit(category)

    def sync(self) -> None:
        """Synchronize settings to disk."""
        self.settings.sync()

    def get_settings_file_path(self) -> str:
        """Get the path to the settings file."""
        return self.settings.fileName()
