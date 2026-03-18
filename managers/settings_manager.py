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
from typing import ClassVar, NamedTuple, cast, final

# Third-party imports
from PySide6.QtCore import QByteArray, QObject, QSettings, QSize

# Local application imports
from config import Config
from logging_mixin import LoggingMixin


# Set up logger for this module


class _SettingDef(NamedTuple):
    qsettings_key: str
    type_: type
    default: object


@final
class SettingsManager(LoggingMixin, QObject):
    """Manages application settings with type safety and persistence.

    Provides a comprehensive settings management system with automatic
    migration, validation, and organized access to application preferences.
    """

    _REGISTRY: ClassVar[dict[str, _SettingDef]] = {
        "window_geometry":       _SettingDef("window/geometry",                   QByteArray, QByteArray()),
        "window_state":          _SettingDef("window/state",                      QByteArray, QByteArray()),
        "window_maximized":      _SettingDef("window/maximized",                  bool,       False),
        "current_tab":           _SettingDef("window/current_tab",                int,        0),
        "refresh_interval":      _SettingDef("preferences/refresh_interval",      int,        Config.CACHE_REFRESH_INTERVAL_MINUTES),
        "background_refresh":    _SettingDef("preferences/background_refresh",    bool,       Config.ENABLE_BACKGROUND_REFRESH),
        "thumbnail_size":        _SettingDef("preferences/thumbnail_size",        int,        Config.DEFAULT_THUMBNAIL_SIZE),
        "last_directory":        _SettingDef("preferences/last_directory",        str,        str(Config.SHOWS_ROOT)),
        "preferred_terminal":    _SettingDef("preferences/preferred_terminal",    str,        "gnome-terminal"),
        "double_click_action":   _SettingDef("preferences/double_click_action",   str,        "launch_default"),
        "max_thumbnail_threads": _SettingDef("performance/max_thumbnail_threads", int,        Config.MAX_THUMBNAIL_THREADS),
        "max_cache_memory_mb":   _SettingDef("performance/max_cache_memory_mb",   int,        Config.MAX_THUMBNAIL_MEMORY_MB),
        "cache_expiry_minutes":  _SettingDef("performance/cache_expiry_minutes",  int,        Config.CACHE_EXPIRY_MINUTES),
        "enable_animations":     _SettingDef("performance/enable_animations",     bool,       True),
        "default_app":           _SettingDef("applications/default_app",          str,        Config.DEFAULT_APP),
        "background_gui_apps":   _SettingDef("applications/background_gui_apps",  bool,       False),
        "ui_scale":              _SettingDef("ui/ui_scale",                       float,      1.0),
        "debug_mode":            _SettingDef("advanced/debug_mode",               bool,       False),
        "log_level":             _SettingDef("advanced/log_level",                str,        "INFO"),
    }

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

        self.logger.debug(f"SettingsManager initialized: {self.settings.fileName()}")

    def _get(self, key: str) -> object:
        defn = self._REGISTRY[key]
        return self.settings.value(defn.qsettings_key, defn.default, type=defn.type_)

    def _set(self, key: str, value: object) -> None:
        self.settings.setValue(self._REGISTRY[key].qsettings_key, value)

    def _initialize_defaults(self) -> None:
        """Initialize default values for all registry settings if they don't exist."""
        for defn in self._REGISTRY.values():
            if not self.settings.contains(defn.qsettings_key):
                self.settings.setValue(defn.qsettings_key, defn.default)
                self.logger.debug(
                    f"Initialized default setting: {defn.qsettings_key} = {defn.default}"
                )

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
        value = self._get("window_geometry")
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_window_geometry(self, geometry: QByteArray) -> None:
        """Set window geometry."""
        self._set("window_geometry", geometry)

    def get_window_state(self) -> QByteArray:
        """Get window state (dock widgets, toolbars)."""
        value = self._get("window_state")
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_window_state(self, state: QByteArray) -> None:
        """Set window state."""
        self._set("window_state", state)

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

    def get_splitter_state(self, splitter_name: str) -> QByteArray:
        """Get splitter state by name."""
        key = f"window/splitter_{splitter_name}"
        value = self.settings.value(key, QByteArray(), type=QByteArray)
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_splitter_state(self, splitter_name: str, state: QByteArray) -> None:
        """Set splitter state by name."""
        key = f"window/splitter_{splitter_name}"
        self.settings.setValue(key, state)

    def get_current_tab(self) -> int:
        """Get current tab index."""
        value = self._get("current_tab")
        return value if isinstance(value, int) else 0

    def set_current_tab(self, index: int) -> None:
        """Set current tab index."""
        self._set("current_tab", max(0, index))

    def is_window_maximized(self) -> bool:
        """Check if window was maximized."""
        value = self._get("window_maximized")
        return value if isinstance(value, bool) else False

    def set_window_maximized(self, maximized: bool) -> None:
        """Set window maximized state."""
        self._set("window_maximized", maximized)

    # Preference Settings
    def get_refresh_interval(self) -> int:
        """Get refresh interval in minutes."""
        value = self._get("refresh_interval")
        return value if isinstance(value, int) else Config.CACHE_REFRESH_INTERVAL_MINUTES

    def set_refresh_interval(self, minutes: int) -> None:
        """Set refresh interval in minutes."""
        self._set("refresh_interval", max(1, min(minutes, 1440)))

    def get_background_refresh(self) -> bool:
        """Get background refresh enabled state."""
        value = self._get("background_refresh")
        return value if isinstance(value, bool) else Config.ENABLE_BACKGROUND_REFRESH

    def set_background_refresh(self, enabled: bool) -> None:
        """Set background refresh enabled state."""
        self._set("background_refresh", enabled)

    def get_thumbnail_size(self) -> int:
        """Get thumbnail size."""
        value = self._get("thumbnail_size")
        return value if isinstance(value, int) else Config.DEFAULT_THUMBNAIL_SIZE

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size with validation."""
        self._set("thumbnail_size", max(Config.MIN_THUMBNAIL_SIZE, min(size, Config.MAX_THUMBNAIL_SIZE)))

    def get_last_directory(self) -> str:
        """Get last used directory."""
        value = self._get("last_directory")
        return value if isinstance(value, str) else str(Config.SHOWS_ROOT)

    def set_last_directory(self, directory: str) -> None:
        """Set last used directory."""
        # Validate directory exists
        if Path(directory).is_dir():
            self._set("last_directory", directory)

    def get_preferred_terminal(self) -> str:
        """Get preferred terminal emulator."""
        value = self._get("preferred_terminal")
        return value if isinstance(value, str) else "gnome-terminal"

    def set_preferred_terminal(self, terminal: str) -> None:
        """Set preferred terminal emulator."""
        self._set("preferred_terminal", terminal)

    def get_double_click_action(self) -> str:
        """Get double click action."""
        value = self._get("double_click_action")
        return value if isinstance(value, str) else "launch_default"

    def set_double_click_action(self, action: str) -> None:
        """Set double click action."""
        valid_actions = ["launch_default", "show_info", "open_folder"]
        if action in valid_actions:
            self._set("double_click_action", action)

    # Performance Settings
    def get_max_thumbnail_threads(self) -> int:
        """Get maximum thumbnail loading threads."""
        value = self._get("max_thumbnail_threads")
        return value if isinstance(value, int) else Config.MAX_THUMBNAIL_THREADS

    def set_max_thumbnail_threads(self, threads: int) -> None:
        """Set maximum thumbnail loading threads."""
        self._set("max_thumbnail_threads", max(1, min(threads, 16)))

    def get_max_cache_memory_mb(self) -> int:
        """Get maximum cache memory in MB."""
        value = self._get("max_cache_memory_mb")
        return value if isinstance(value, int) else Config.MAX_THUMBNAIL_MEMORY_MB

    def set_max_cache_memory_mb(self, memory_mb: int) -> None:
        """Set maximum cache memory in MB."""
        self._set("max_cache_memory_mb", max(10, min(memory_mb, 1024)))

    def get_cache_expiry_minutes(self) -> int:
        """Get cache expiry time in minutes."""
        value = self._get("cache_expiry_minutes")
        return value if isinstance(value, int) else Config.CACHE_EXPIRY_MINUTES

    def set_cache_expiry_minutes(self, minutes: int) -> None:
        """Set cache expiry time in minutes."""
        self._set("cache_expiry_minutes", max(5, min(minutes, 10080)))

    def get_enable_animations(self) -> bool:
        """Get animation enabled state."""
        value = self._get("enable_animations")
        return value if isinstance(value, bool) else True

    def set_enable_animations(self, enabled: bool) -> None:
        """Set animation enabled state."""
        self._set("enable_animations", enabled)

    # Application Settings
    def get_default_app(self) -> str:
        """Get default application."""
        value = self._get("default_app")
        return value if isinstance(value, str) else Config.DEFAULT_APP

    def set_default_app(self, app: str) -> None:
        """Set default application."""
        # Validate app exists in available apps
        available_apps = list(Config.APPS.keys())
        if app in available_apps:
            self._set("default_app", app)

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

    def get_background_gui_apps(self) -> bool:
        """Get whether to run GUI apps in background (close terminal immediately).

        When True, launching 3DE, Nuke, Maya etc. will background the process
        and close the terminal window immediately, reducing desktop clutter.
        """
        value = self._get("background_gui_apps")
        return bool(value)

    def set_background_gui_apps(self, enabled: bool) -> None:
        """Set whether to run GUI apps in background."""
        self._set("background_gui_apps", enabled)

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

    # UI Settings
    # Dead settings removed: grid_columns, show_tooltips, dark_theme
    # These were never applied by settings_controller.py
    # Dark theme is always enabled unconditionally in shotbot.py

    def get_ui_scale(self) -> float:
        """Get UI scale factor.

        Returns:
            Scale factor (0.8 to 1.5, default 1.0 = 100%)

        """
        value = self._get("ui_scale")
        if isinstance(value, (int, float)):
            # Clamp to valid range
            return max(0.8, min(float(value), 1.5))
        return 1.0

    def set_ui_scale(self, scale: float) -> None:
        """Set UI scale factor.

        Args:
            scale: Scale factor (0.8 to 1.5)

        """
        self._set("ui_scale", max(0.8, min(scale, 1.5)))

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

    # Sort Order Settings (per-tab)
    def get_sort_order(self, tab_id: str) -> str:
        """Get sort order for a tab.

        Args:
            tab_id: Tab identifier ("my_shots", "threede_scenes", "previous_shots")

        Returns:
            Sort order string ("name" or "date")

        """
        # Default sort orders: name for my_shots, date for others
        defaults = {"my_shots": "name", "threede_scenes": "date", "previous_shots": "date"}
        stored = self.settings.value(f"ui/sort_order_{tab_id}", defaults.get(tab_id, "name"))
        # Validate stored value
        if stored in ("name", "date"):
            return str(stored)
        return defaults.get(tab_id, "name")

    def set_sort_order(self, tab_id: str, order: str) -> None:
        """Set sort order for a tab.

        Args:
            tab_id: Tab identifier ("my_shots", "threede_scenes", "previous_shots")
            order: Sort order ("name" or "date")

        """
        if order not in ("name", "date"):
            self.logger.warning(f"Invalid sort order '{order}', ignoring")
            return
        self.settings.setValue(f"ui/sort_order_{tab_id}", order)

    # Advanced Settings
    def get_debug_mode(self) -> bool:
        """Get debug mode state."""
        value = self._get("debug_mode")
        return value if isinstance(value, bool) else False

    def set_debug_mode(self, enabled: bool) -> None:
        """Set debug mode state."""
        self._set("debug_mode", enabled)

    def get_log_level(self) -> str:
        """Get logging level."""
        value = self._get("log_level")
        return value if isinstance(value, str) else "INFO"

    def set_log_level(self, level: str) -> None:
        """Set logging level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level in valid_levels:
            self._set("log_level", level)

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

        except Exception:
            self.logger.exception("Failed to export settings")
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
                loaded_data: object = json.load(f)  # pyright: ignore[reportAny]

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

        except Exception:
            self.logger.exception("Failed to import settings")
            return False

    def reset_to_defaults(self) -> None:
        """Reset all settings to default values."""
        # Clear all existing settings
        self.settings.clear()

        # Reinitialize with defaults
        self._initialize_defaults()

        self.logger.info("All settings reset to defaults")

    def reset_category(self, category: str) -> None:
        """Reset a specific category to defaults.

        Removes all stored keys under the category so QSettings falls back to
        in-code defaults, then re-writes the registry-defined defaults for the
        category so they are persisted explicitly.
        """
        # Clear all stored keys under this category group
        self.settings.beginGroup(category)
        self.settings.remove("")  # removes all keys in the current group
        self.settings.endGroup()

        # Re-write registry defaults for this category
        prefix = f"{category}/"
        for defn in self._REGISTRY.values():
            if defn.qsettings_key.startswith(prefix):
                self.settings.setValue(defn.qsettings_key, defn.default)

        self.logger.info(f"Category '{category}' reset to defaults")

    def sync(self) -> None:
        """Synchronize settings to disk."""
        self.settings.sync()

    def get_settings_file_path(self) -> str:
        """Get the path to the settings file."""
        return self.settings.fileName()


def get_stored_height(settings: QSettings, key: str, default: int) -> int:
    """Read an integer height value from QSettings with a safe fallback.

    Args:
        settings: The QSettings instance to read from.
        key: The settings key to look up.
        default: Value to return when the key is absent or the stored value
            is not an integer.

    Returns:
        The stored integer height, or *default* if not found or wrong type.

    """
    value = settings.value(key, default, type=int)
    return value if isinstance(value, int) else default
