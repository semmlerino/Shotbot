"""Domain setting groups for SettingsManager.

Each class groups related settings methods and delegates storage to the
``_get``/``_set`` callables (and raw ``QSettings`` for keys not in the
registry) provided at construction time.  SettingsManager instantiates one of
each and exposes them as sub-objects while keeping the existing flat methods as
thin one-line delegates for backward compatibility.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast, final

from PySide6.QtCore import QByteArray, QSettings, QSize

from config import Config


# ---------------------------------------------------------------------------
# Type aliases for the callable signatures expected by every domain class.
# ---------------------------------------------------------------------------
_GetFn = Callable[[str], object]
_SetFn = Callable[[str, object], None]


@final
class WindowStateSettings:
    """Window geometry, splitter, tab, and maximized-state persistence."""

    def __init__(self, get: _GetFn, set_fn: _SetFn, settings: QSettings) -> None:
        self._get = get
        self._set = set_fn
        self._settings = settings

    # -- geometry / state --------------------------------------------------

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
        value = self._settings.value("window/size", default_size, type=QSize)
        return value if isinstance(value, QSize) else default_size

    def set_window_size(self, size: QSize) -> None:
        """Set window size."""
        min_width = max(size.width(), Config.MIN_WINDOW_WIDTH)
        min_height = max(size.height(), Config.MIN_WINDOW_HEIGHT)
        validated_size = QSize(min_width, min_height)
        self._settings.setValue("window/size", validated_size)

    # -- splitter -----------------------------------------------------------

    def get_splitter_state(self, splitter_name: str) -> QByteArray:
        """Get splitter state by name."""
        key = f"window/splitter_{splitter_name}"
        value = self._settings.value(key, QByteArray(), type=QByteArray)
        return value if isinstance(value, QByteArray) else QByteArray()

    def set_splitter_state(self, splitter_name: str, state: QByteArray) -> None:
        """Set splitter state by name."""
        key = f"window/splitter_{splitter_name}"
        self._settings.setValue(key, state)

    # -- tab ----------------------------------------------------------------

    def get_current_tab(self) -> int:
        """Get current tab index."""
        value = self._get("current_tab")
        return value if isinstance(value, int) else 0

    def set_current_tab(self, index: int) -> None:
        """Set current tab index."""
        self._set("current_tab", max(0, index))

    # -- maximized ----------------------------------------------------------

    def is_window_maximized(self) -> bool:
        """Check if window was maximized."""
        value = self._get("window_maximized")
        return value if isinstance(value, bool) else False

    def set_window_maximized(self, maximized: bool) -> None:
        """Set window maximized state."""
        self._set("window_maximized", maximized)


@final
class RefreshSettings:
    """Refresh interval and background-refresh toggle."""

    def __init__(self, get: _GetFn, set_fn: _SetFn) -> None:
        self._get = get
        self._set = set_fn

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


@final
class UIAppearanceSettings:
    """Thumbnail size, UI scale, animations, expanded sections, and sort order."""

    def __init__(self, get: _GetFn, set_fn: _SetFn, settings: QSettings) -> None:
        self._get = get
        self._set = set_fn
        self._settings = settings

    def get_thumbnail_size(self) -> int:
        """Get thumbnail size."""
        value = self._get("thumbnail_size")
        return value if isinstance(value, int) else Config.DEFAULT_THUMBNAIL_SIZE

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size with validation."""
        self._set(
            "thumbnail_size",
            max(Config.MIN_THUMBNAIL_SIZE, min(size, Config.MAX_THUMBNAIL_SIZE)),
        )

    def get_ui_scale(self) -> float:
        """Get UI scale factor.

        Returns:
            Scale factor (0.8 to 1.5, default 1.0 = 100%)

        """
        value = self._get("ui_scale")
        if isinstance(value, (int, float)):
            return max(0.8, min(float(value), 1.5))
        return 1.0

    def set_ui_scale(self, scale: float) -> None:
        """Set UI scale factor.

        Args:
            scale: Scale factor (0.8 to 1.5)

        """
        self._set("ui_scale", max(0.8, min(scale, 1.5)))

    def get_enable_animations(self) -> bool:
        """Get animation enabled state."""
        value = self._get("enable_animations")
        return value if isinstance(value, bool) else True

    def set_enable_animations(self, enabled: bool) -> None:
        """Set animation enabled state."""
        self._set("enable_animations", enabled)

    def get_expanded_sections(self) -> dict[str, bool]:
        """Get expanded state for all sections."""
        default_sections = {
            "files": False,
            "3de": True,
            "nuke": True,
            "maya": True,
            "rv": True,
        }
        stored_value = self._settings.value("ui/expanded_sections", default_sections)
        if isinstance(stored_value, dict):
            typed_dict = cast("dict[object, object]", stored_value)
            return {str(k): bool(v) for k, v in typed_dict.items()}
        return default_sections

    def set_section_expanded(self, section_id: str, expanded: bool) -> None:
        """Set expanded state for a single section."""
        sections = self.get_expanded_sections()
        sections[section_id] = expanded
        self._settings.setValue("ui/expanded_sections", sections)

    def is_section_expanded(self, section_id: str) -> bool:
        """Check if a section is expanded.

        Args:
            section_id: Section identifier (e.g., "files", "3de", "nuke")

        Returns:
            True if section is expanded, False otherwise

        """
        sections = self.get_expanded_sections()
        return sections.get(section_id, False)

    def get_sort_order(self, tab_id: str) -> str:
        """Get sort order for a tab.

        Args:
            tab_id: Tab identifier ("my_shots", "threede_scenes", "previous_shots")

        Returns:
            Sort order string ("name" or "date")

        """
        defaults = {"my_shots": "name", "threede_scenes": "date", "previous_shots": "date"}
        stored = self._settings.value(
            f"ui/sort_order_{tab_id}", defaults.get(tab_id, "name")
        )
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
            return
        self._settings.setValue(f"ui/sort_order_{tab_id}", order)


@final
class LaunchPreferenceSettings:
    """Terminal, double-click action, default app, file associations, custom launchers."""

    def __init__(self, get: _GetFn, set_fn: _SetFn, settings: QSettings) -> None:
        self._get = get
        self._set = set_fn
        self._settings = settings

    def get_last_directory(self) -> str:
        """Get last used directory."""
        value = self._get("last_directory")
        return value if isinstance(value, str) else str(Config.SHOWS_ROOT)

    def set_last_directory(self, directory: str) -> None:
        """Set last used directory."""
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

    def get_default_app(self) -> str:
        """Get default application."""
        value = self._get("default_app")
        return value if isinstance(value, str) else Config.DEFAULT_APP

    def set_default_app(self, app: str) -> None:
        """Set default application."""
        available_apps = list(Config.APPS.keys())
        if app in available_apps:
            self._set("default_app", app)

    def get_file_associations(self) -> dict[str, str]:
        """Get file type associations."""
        default_associations = dict(Config.APPS)
        stored_value = self._settings.value(
            "applications/file_associations", default_associations
        )
        if isinstance(stored_value, dict):
            typed_dict = cast("dict[object, object]", stored_value)
            return {str(k): str(v) for k, v in typed_dict.items()}
        return default_associations

    def set_file_associations(self, associations: dict[str, str]) -> None:
        """Set file type associations."""
        self._settings.setValue("applications/file_associations", associations)

    def get_background_gui_apps(self) -> bool:
        """Get whether to run GUI apps in background (close terminal immediately).

        When True, launching 3DE, Nuke, Maya etc. will background the process
        and close the terminal window immediately, reducing desktop clutter.
        """
        value = self._get("background_gui_apps")
        return value if isinstance(value, bool) else False

    def set_background_gui_apps(self, enabled: bool) -> None:
        """Set whether to run GUI apps in background."""
        self._set("background_gui_apps", enabled)

    def get_custom_launchers(self) -> list[dict[str, object]]:
        """Get custom launcher definitions."""
        stored_value = self._settings.value(
            "applications/custom_launchers", [], type=list
        )
        if isinstance(stored_value, list):
            typed_list = cast("list[object]", stored_value)
            return [
                cast("dict[str, object]", item)
                for item in typed_list
                if isinstance(item, dict)
            ]
        return []

    def set_custom_launchers(self, launchers: list[dict[str, object]]) -> None:
        """Set custom launcher definitions."""
        self._settings.setValue("applications/custom_launchers", launchers)


@final
class PerformanceSettings:
    """Max thumbnail threads, cache memory, and cache expiry."""

    def __init__(self, get: _GetFn, set_fn: _SetFn) -> None:
        self._get = get
        self._set = set_fn

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


@final
class DebugSettings:
    """Debug mode and log level."""

    def __init__(self, get: _GetFn, set_fn: _SetFn) -> None:
        self._get = get
        self._set = set_fn

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
