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
    Domain sub-objects (``self.window``, ``self.refresh``, etc.) group related methods;
    the existing flat methods delegate to them for full backward compatibility.

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

    Domain sub-object access:
        >>> settings.window.get_window_geometry()
        >>> settings.refresh.get_refresh_interval()
        >>> settings.ui.get_thumbnail_size()
        >>> settings.launch.get_preferred_terminal()
        >>> settings.performance.get_max_thumbnail_threads()
        >>> settings.debug.get_debug_mode()

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
from managers.settings_domains import (
    DebugSettings,
    LaunchPreferenceSettings,
    PerformanceSettings,
    RefreshSettings,
    UIAppearanceSettings,
    WindowStateSettings,
)


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

    Domain sub-objects expose the same methods grouped by concern:

    Attributes:
        window: Window geometry, splitter, tab, and maximized-state settings.
        refresh: Refresh interval and background-refresh toggle.
        ui: Thumbnail size, UI scale, animations, sections, and sort order.
        launch: Terminal, double-click action, app, file associations, launchers.
        performance: Thread limits, cache memory, and cache expiry.
        debug: Debug mode and log level.
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

        # Domain sub-objects — group related methods by concern.
        self._init_domain_objects()

        self.logger.debug(f"SettingsManager initialized: {self.settings.fileName()}")

    _DOMAIN_ATTRS: ClassVar[frozenset[str]] = frozenset(
        {"window", "refresh", "ui", "launch", "performance", "debug"}
    )

    def __getattr__(self, name: str) -> object:
        """Lazily initialize domain sub-objects on first access.

        This handles the case where ``__new__`` is used to bypass ``__init__``
        (e.g. in test helpers) and ``_init_domain_objects`` has not yet been
        called.  It is only invoked when the normal attribute lookup fails, so
        it does not interfere with regular attribute access.
        """
        if name in self._DOMAIN_ATTRS and "settings" in self.__dict__:
            self._init_domain_objects()
            return object.__getattribute__(self, name)  # pyright: ignore[reportAny] - dynamic attr lookup
        msg = f"'{type(self).__name__}' object has no attribute '{name}'"
        raise AttributeError(msg)

    def _init_domain_objects(self) -> None:
        """Create domain sub-objects that group related settings methods.

        Called by ``__init__`` and, lazily, by ``__getattr__`` when a domain
        attribute is accessed before ``__init__`` has run (e.g. in tests that
        bypass ``__init__`` via ``__new__``).
        """
        self.window = WindowStateSettings(self._get, self._set, self.settings)
        self.refresh = RefreshSettings(self._get, self._set)
        self.ui = UIAppearanceSettings(self._get, self._set, self.settings)
        self.launch = LaunchPreferenceSettings(self._get, self._set, self.settings)
        self.performance = PerformanceSettings(self._get, self._set)
        self.debug = DebugSettings(self._get, self._set)

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

    # -----------------------------------------------------------------------
    # Window Settings — delegate to self.window
    # -----------------------------------------------------------------------

    def get_window_geometry(self) -> QByteArray:
        """Get window geometry."""
        return self.window.get_window_geometry()

    def set_window_geometry(self, geometry: QByteArray) -> None:
        """Set window geometry."""
        self.window.set_window_geometry(geometry)

    def get_window_state(self) -> QByteArray:
        """Get window state (dock widgets, toolbars)."""
        return self.window.get_window_state()

    def set_window_state(self, state: QByteArray) -> None:
        """Set window state."""
        self.window.set_window_state(state)

    def get_window_size(self) -> QSize:
        """Get window size."""
        return self.window.get_window_size()

    def set_window_size(self, size: QSize) -> None:
        """Set window size."""
        self.window.set_window_size(size)

    def get_splitter_state(self, splitter_name: str) -> QByteArray:
        """Get splitter state by name."""
        return self.window.get_splitter_state(splitter_name)

    def set_splitter_state(self, splitter_name: str, state: QByteArray) -> None:
        """Set splitter state by name."""
        self.window.set_splitter_state(splitter_name, state)

    def get_current_tab(self) -> int:
        """Get current tab index."""
        return self.window.get_current_tab()

    def set_current_tab(self, index: int) -> None:
        """Set current tab index."""
        self.window.set_current_tab(index)

    def is_window_maximized(self) -> bool:
        """Check if window was maximized."""
        return self.window.is_window_maximized()

    def set_window_maximized(self, maximized: bool) -> None:
        """Set window maximized state."""
        self.window.set_window_maximized(maximized)

    # -----------------------------------------------------------------------
    # Preference Settings — delegate to self.refresh / self.launch / self.ui
    # -----------------------------------------------------------------------

    def get_refresh_interval(self) -> int:
        """Get refresh interval in minutes."""
        return self.refresh.get_refresh_interval()

    def set_refresh_interval(self, minutes: int) -> None:
        """Set refresh interval in minutes."""
        self.refresh.set_refresh_interval(minutes)

    def get_background_refresh(self) -> bool:
        """Get background refresh enabled state."""
        return self.refresh.get_background_refresh()

    def set_background_refresh(self, enabled: bool) -> None:
        """Set background refresh enabled state."""
        self.refresh.set_background_refresh(enabled)

    def get_thumbnail_size(self) -> int:
        """Get thumbnail size."""
        return self.ui.get_thumbnail_size()

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size with validation."""
        self.ui.set_thumbnail_size(size)

    def get_last_directory(self) -> str:
        """Get last used directory."""
        return self.launch.get_last_directory()

    def set_last_directory(self, directory: str) -> None:
        """Set last used directory."""
        self.launch.set_last_directory(directory)

    def get_preferred_terminal(self) -> str:
        """Get preferred terminal emulator."""
        return self.launch.get_preferred_terminal()

    def set_preferred_terminal(self, terminal: str) -> None:
        """Set preferred terminal emulator."""
        self.launch.set_preferred_terminal(terminal)

    def get_double_click_action(self) -> str:
        """Get double click action."""
        return self.launch.get_double_click_action()

    def set_double_click_action(self, action: str) -> None:
        """Set double click action."""
        self.launch.set_double_click_action(action)

    # -----------------------------------------------------------------------
    # Performance Settings — delegate to self.performance / self.ui
    # -----------------------------------------------------------------------

    def get_max_thumbnail_threads(self) -> int:
        """Get maximum thumbnail loading threads."""
        return self.performance.get_max_thumbnail_threads()

    def set_max_thumbnail_threads(self, threads: int) -> None:
        """Set maximum thumbnail loading threads."""
        self.performance.set_max_thumbnail_threads(threads)

    def get_max_cache_memory_mb(self) -> int:
        """Get maximum cache memory in MB."""
        return self.performance.get_max_cache_memory_mb()

    def set_max_cache_memory_mb(self, memory_mb: int) -> None:
        """Set maximum cache memory in MB."""
        self.performance.set_max_cache_memory_mb(memory_mb)

    def get_cache_expiry_minutes(self) -> int:
        """Get cache expiry time in minutes."""
        return self.performance.get_cache_expiry_minutes()

    def set_cache_expiry_minutes(self, minutes: int) -> None:
        """Set cache expiry time in minutes."""
        self.performance.set_cache_expiry_minutes(minutes)

    def get_enable_animations(self) -> bool:
        """Get animation enabled state."""
        return self.ui.get_enable_animations()

    def set_enable_animations(self, enabled: bool) -> None:
        """Set animation enabled state."""
        self.ui.set_enable_animations(enabled)

    # -----------------------------------------------------------------------
    # Application Settings — delegate to self.launch
    # -----------------------------------------------------------------------

    def get_default_app(self) -> str:
        """Get default application."""
        return self.launch.get_default_app()

    def set_default_app(self, app: str) -> None:
        """Set default application."""
        self.launch.set_default_app(app)

    def get_file_associations(self) -> dict[str, str]:
        """Get file type associations."""
        return self.launch.get_file_associations()

    def set_file_associations(self, associations: dict[str, str]) -> None:
        """Set file type associations."""
        self.launch.set_file_associations(associations)

    def get_background_gui_apps(self) -> bool:
        """Get whether to run GUI apps in background (close terminal immediately).

        When True, launching 3DE, Nuke, Maya etc. will background the process
        and close the terminal window immediately, reducing desktop clutter.
        """
        return self.launch.get_background_gui_apps()

    def set_background_gui_apps(self, enabled: bool) -> None:
        """Set whether to run GUI apps in background."""
        self.launch.set_background_gui_apps(enabled)

    def get_custom_launchers(self) -> list[dict[str, object]]:
        """Get custom launcher definitions."""
        return self.launch.get_custom_launchers()

    def set_custom_launchers(self, launchers: list[dict[str, object]]) -> None:
        """Set custom launcher definitions."""
        self.launch.set_custom_launchers(launchers)

    # -----------------------------------------------------------------------
    # UI Settings — delegate to self.ui
    # Dead settings removed: grid_columns, show_tooltips, dark_theme
    # These were never applied by settings_controller.py
    # Dark theme is always enabled unconditionally in shotbot.py
    # -----------------------------------------------------------------------

    def get_ui_scale(self) -> float:
        """Get UI scale factor.

        Returns:
            Scale factor (0.8 to 1.5, default 1.0 = 100%)

        """
        return self.ui.get_ui_scale()

    def set_ui_scale(self, scale: float) -> None:
        """Set UI scale factor.

        Args:
            scale: Scale factor (0.8 to 1.5)

        """
        self.ui.set_ui_scale(scale)

    def get_expanded_sections(self) -> dict[str, bool]:
        """Get expanded state for all sections."""
        return self.ui.get_expanded_sections()

    def set_section_expanded(self, section_id: str, expanded: bool) -> None:
        """Set expanded state for a single section."""
        self.ui.set_section_expanded(section_id, expanded)

    def is_section_expanded(self, section_id: str) -> bool:
        """Check if a section is expanded.

        Args:
            section_id: Section identifier (e.g., "files", "3de", "nuke")

        Returns:
            True if section is expanded, False otherwise

        """
        return self.ui.is_section_expanded(section_id)

    # Sort Order Settings (per-tab)
    def get_sort_order(self, tab_id: str) -> str:
        """Get sort order for a tab.

        Args:
            tab_id: Tab identifier ("my_shots", "threede_scenes", "previous_shots")

        Returns:
            Sort order string ("name" or "date")

        """
        return self.ui.get_sort_order(tab_id)

    def set_sort_order(self, tab_id: str, order: str) -> None:
        """Set sort order for a tab.

        Args:
            tab_id: Tab identifier ("my_shots", "threede_scenes", "previous_shots")
            order: Sort order ("name" or "date")

        """
        if order not in ("name", "date"):
            self.logger.warning(f"Invalid sort order '{order}', ignoring")
            return
        self.ui.set_sort_order(tab_id, order)

    # -----------------------------------------------------------------------
    # Advanced Settings — delegate to self.debug
    # -----------------------------------------------------------------------

    def get_debug_mode(self) -> bool:
        """Get debug mode state."""
        return self.debug.get_debug_mode()

    def set_debug_mode(self, enabled: bool) -> None:
        """Set debug mode state."""
        self.debug.set_debug_mode(enabled)

    def get_log_level(self) -> str:
        """Get logging level."""
        return self.debug.get_log_level()

    def set_log_level(self, level: str) -> None:
        """Set logging level."""
        self.debug.set_log_level(level)

    # -----------------------------------------------------------------------
    # Category Access
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Bulk Operations
    # -----------------------------------------------------------------------

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
