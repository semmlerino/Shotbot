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
    interface with automatic persistence. Settings are organized into
    categories (window, preferences, performance, etc.) with validation and defaults.
    Domain sub-objects (``self.window``, ``self.refresh``, etc.) group related settings methods
    by logical category.

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
import logging
import os
import tempfile
from pathlib import Path
from typing import ClassVar, NamedTuple, cast, final

# Third-party imports
from PySide6.QtCore import QByteArray, QObject, QSettings

# Local application imports
from config import Config
from managers.settings_domains import (
    DebugSettings,
    LaunchPreferenceSettings,
    PerformanceSettings,
    RefreshSettings,
    UIAppearanceSettings,
    WindowStateSettings,
)


logger = logging.getLogger(__name__)


class _SettingDef(NamedTuple):
    qsettings_key: str
    type_: type
    default: object


@final
class SettingsManager(QObject):
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
        "window_geometry": _SettingDef("window/geometry", QByteArray, QByteArray()),
        "window_state": _SettingDef("window/state", QByteArray, QByteArray()),
        "window_maximized": _SettingDef("window/maximized", bool, False),
        "current_tab": _SettingDef("window/current_tab", int, 0),
        "refresh_interval": _SettingDef(
            "preferences/refresh_interval", int, Config.CACHE_REFRESH_INTERVAL_MINUTES
        ),
        "background_refresh": _SettingDef(
            "preferences/background_refresh", bool, Config.ENABLE_BACKGROUND_REFRESH
        ),
        "thumbnail_size": _SettingDef(
            "preferences/thumbnail_size", int, Config.DEFAULT_THUMBNAIL_SIZE
        ),
        "last_directory": _SettingDef(
            "preferences/last_directory", str, str(Config.SHOWS_ROOT)
        ),
        "preferred_terminal": _SettingDef(
            "preferences/preferred_terminal", str, "gnome-terminal"
        ),
        "double_click_action": _SettingDef(
            "preferences/double_click_action", str, "launch_default"
        ),
        "max_thumbnail_threads": _SettingDef(
            "performance/max_thumbnail_threads", int, Config.MAX_THUMBNAIL_THREADS
        ),
        "max_cache_memory_mb": _SettingDef(
            "performance/max_cache_memory_mb", int, Config.MAX_THUMBNAIL_MEMORY_MB
        ),
        "cache_expiry_minutes": _SettingDef(
            "performance/cache_expiry_minutes", int, Config.CACHE_EXPIRY_MINUTES
        ),
        "enable_animations": _SettingDef("performance/enable_animations", bool, True),
        "default_app": _SettingDef("applications/default_app", str, Config.DEFAULT_APP),
        "background_gui_apps": _SettingDef(
            "applications/background_gui_apps", bool, False
        ),
        "ui_scale": _SettingDef("ui/ui_scale", float, 1.0),
        "debug_mode": _SettingDef("advanced/debug_mode", bool, False),
        "log_level": _SettingDef("advanced/log_level", str, "INFO"),
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

        logger.debug(f"SettingsManager initialized: {self.settings.fileName()}")

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
                logger.debug(
                    f"Initialized default setting: {defn.qsettings_key} = {defn.default}"
                )

    def _migrate_old_settings(self) -> None:
        """Migrate settings from old format to new organized format."""
        # Check if migration is needed
        if self.settings.contains("migration_version"):
            return

        logger.info("Migrating settings to new format...")

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
                logger.debug(f"Migrated setting: {old_key} -> {new_key}")

        # Mark migration as complete
        self.settings.setValue("migration_version", 1)
        logger.info("Settings migration completed")

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

            logger.info(f"Settings exported to: {file_path}")
            return True

        except Exception:
            logger.exception("Failed to export settings")
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
                logger.error("Invalid settings file: not a dictionary")
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

            logger.info(f"Settings imported from: {file_path}")
            return True

        except Exception:
            logger.exception("Failed to import settings")
            return False

    def reset_to_defaults(self) -> None:
        """Reset all settings to default values."""
        # Clear all existing settings
        self.settings.clear()

        # Reinitialize with defaults
        self._initialize_defaults()

        logger.info("All settings reset to defaults")

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

        logger.info(f"Category '{category}' reset to defaults")

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
