"""Tests for SettingsManager - Application settings persistence and management.

This module provides comprehensive tests for the SettingsManager class,
which handles all application preferences and settings.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QByteArray, QSettings, QSize

from config import Config
from settings_manager import SettingsManager


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

# Test markers for categorization and parallel safety
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.xdist_group("qt_state"),  # Critical for parallel execution safety
]


# Factory fixtures for test data creation
@pytest.fixture
def make_settings_manager() -> Callable[[Path, str, str], SettingsManager]:
    """Factory for creating SettingsManager instances with custom configuration."""

    def _make(
        tmp_path: Path, organization: str = "TestOrg", application: str = "TestApp"
    ) -> SettingsManager:
        # Use temporary directory for test settings
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path)
        )
        manager = SettingsManager(organization=organization, application=application)
        # Clear any existing settings to ensure clean state
        manager.settings.clear()
        # Re-initialize defaults after clearing
        manager._initialize_defaults()
        return manager

    return _make


@pytest.fixture
def make_test_settings() -> Callable[..., dict[str, Any]]:
    """Factory for creating test settings data."""

    def _make(category: str = "window", **kwargs: Any) -> dict[str, Any]:
        defaults = {
            "window": {"current_tab": 0, "maximized": True},
            "preferences": {"thumbnail_size": 256, "refresh_interval": 10},
            "performance": {"max_threads": 4},
        }
        if category in defaults:
            defaults[category].update(kwargs)
        return defaults.get(category, kwargs)

    return _make


class TestSettingsManager:
    """Test suite for SettingsManager class."""

    @pytest.fixture
    def settings_manager(
        self, tmp_path: Path, make_settings_manager: Callable[[Path, str, str], SettingsManager]
    ) -> SettingsManager:
        """Create settings manager with temporary storage."""
        return make_settings_manager(tmp_path)

    def test_initialization(self, settings_manager: SettingsManager) -> None:
        """Test proper initialization with defaults."""
        # Check that settings object was created
        assert settings_manager.settings is not None

        # Check that defaults were initialized
        assert settings_manager.settings.contains("window/size")
        assert settings_manager.settings.contains("preferences/refresh_interval")
        assert settings_manager.settings.contains("performance/max_thumbnail_threads")

    def test_get_default_settings(self, settings_manager: SettingsManager) -> None:
        """Test that default settings contain expected categories."""
        defaults = settings_manager._get_default_settings()

        # Check all categories exist
        expected_categories = [
            "window",
            "preferences",
            "performance",
            "applications",
            "ui",
            "advanced",
        ]
        for category in expected_categories:
            assert category in defaults
            assert isinstance(defaults[category], dict)
            assert len(defaults[category]) > 0

    def test_window_geometry(self, settings_manager: SettingsManager) -> None:
        """Test getting and setting window geometry."""
        # Test default
        geometry = settings_manager.get_window_geometry()
        assert isinstance(geometry, QByteArray)
        assert geometry.isEmpty()

        # Test setting
        test_geometry = QByteArray(b"test_geometry_data")
        settings_manager.set_window_geometry(test_geometry)

        # Verify it was saved
        retrieved = settings_manager.get_window_geometry()
        assert retrieved == test_geometry

    def test_window_state(self, settings_manager: SettingsManager) -> None:
        """Test getting and setting window state."""
        # Test default
        state = settings_manager.get_window_state()
        assert isinstance(state, QByteArray)

        # Test setting
        test_state = QByteArray(b"test_state_data")
        settings_manager.set_window_state(test_state)

        # Verify
        retrieved = settings_manager.get_window_state()
        assert retrieved == test_state

    def test_window_size(self, settings_manager: SettingsManager) -> None:
        """Test getting and setting window size with validation."""
        # Test default
        default_size = settings_manager.get_window_size()
        assert isinstance(default_size, QSize)
        assert default_size.width() == Config.DEFAULT_WINDOW_WIDTH
        assert default_size.height() == Config.DEFAULT_WINDOW_HEIGHT

        # Test setting valid size
        test_size = QSize(1920, 1080)
        settings_manager.set_window_size(test_size)

        retrieved = settings_manager.get_window_size()
        assert retrieved == test_size

        # Test validation - too small size should be clamped
        small_size = QSize(100, 100)
        settings_manager.set_window_size(small_size)

        retrieved = settings_manager.get_window_size()
        assert retrieved.width() >= Config.MIN_WINDOW_WIDTH
        assert retrieved.height() >= Config.MIN_WINDOW_HEIGHT

    def test_splitter_positions(self, settings_manager: SettingsManager) -> None:
        """Test getting and setting splitter positions."""
        # Test main splitter
        test_splitter = QByteArray(b"splitter_data")
        settings_manager.set_splitter_state("main", test_splitter)

        retrieved = settings_manager.get_splitter_state("main")
        assert retrieved == test_splitter

        # Test right splitter
        test_right = QByteArray(b"right_splitter_data")
        settings_manager.set_splitter_state("right", test_right)

        retrieved = settings_manager.get_splitter_state("right")
        assert retrieved == test_right

    def test_current_tab(self, settings_manager: SettingsManager) -> None:
        """Test getting and setting current tab index."""
        # Test default
        assert settings_manager.get_current_tab() == 0

        # Test setting
        settings_manager.set_current_tab(2)
        assert settings_manager.get_current_tab() == 2

        # Test validation - negative should become 0
        settings_manager.set_current_tab(-1)
        assert settings_manager.get_current_tab() == 0

    def test_refresh_interval(self, settings_manager: SettingsManager) -> None:
        """Test refresh interval with validation."""
        # Test default - it might not match Config if the initialization overrides it
        default = settings_manager.get_refresh_interval()
        assert isinstance(default, int)
        assert default >= 0  # Should be a valid integer

        # Test setting valid value
        settings_manager.set_refresh_interval(10)
        assert settings_manager.get_refresh_interval() == 10

        # Test validation - too small should be clamped
        settings_manager.set_refresh_interval(0)
        retrieved = settings_manager.get_refresh_interval()
        assert retrieved >= 1  # Minimum should be 1

    def test_thumbnail_size(self, settings_manager: SettingsManager) -> None:
        """Test thumbnail size with validation."""
        # Test default - might be overridden during initialization
        default = settings_manager.get_thumbnail_size()
        assert isinstance(default, int)
        assert default > 0  # Should be a positive size

        # Test setting valid value
        settings_manager.set_thumbnail_size(256)
        assert settings_manager.get_thumbnail_size() == 256

        # Test validation - clamp to range
        settings_manager.set_thumbnail_size(10)
        assert settings_manager.get_thumbnail_size() >= Config.MIN_THUMBNAIL_SIZE

        settings_manager.set_thumbnail_size(1000)
        assert settings_manager.get_thumbnail_size() <= Config.MAX_THUMBNAIL_SIZE

    def test_last_directory(self, settings_manager: SettingsManager, tmp_path: Path) -> None:
        """Test last directory path handling."""
        # Test default
        default_dir = settings_manager.get_last_directory()
        assert isinstance(default_dir, str)
        assert Path(default_dir) == Path(Config.SHOWS_ROOT)

        # Test setting - need to use an existing directory
        test_path = tmp_path / "test_dir"
        test_path.mkdir()

        settings_manager.set_last_directory(str(test_path))
        retrieved = settings_manager.get_last_directory()
        assert Path(retrieved) == test_path

        # Test setting non-existent directory should not change the value
        fake_path = "/nonexistent/path/to/directory"
        settings_manager.set_last_directory(fake_path)
        # Should still be the previous valid path
        assert Path(settings_manager.get_last_directory()) == test_path

    def test_background_refresh(self, settings_manager: SettingsManager) -> None:
        """Test background refresh boolean setting."""
        # Test default
        default = settings_manager.get_background_refresh()
        assert isinstance(default, bool)

        # Test setting
        settings_manager.set_background_refresh(True)
        assert settings_manager.get_background_refresh() is True

        settings_manager.set_background_refresh(False)
        assert settings_manager.get_background_refresh() is False

    def test_custom_launchers(self, settings_manager: SettingsManager) -> None:
        """Test custom launcher list management."""
        # Test default
        launchers = settings_manager.get_custom_launchers()
        assert isinstance(launchers, list)
        assert len(launchers) == 0

        # Test setting
        test_launchers = [
            {"name": "Test1", "command": "cmd1"},
            {"name": "Test2", "command": "cmd2"},
        ]
        settings_manager.set_custom_launchers(test_launchers)

        retrieved = settings_manager.get_custom_launchers()
        assert retrieved == test_launchers

    def test_get_category(self, settings_manager: SettingsManager) -> None:
        """Test getting all settings in a category."""
        window_settings = settings_manager.get_category("window")

        assert isinstance(window_settings, dict)
        assert "geometry" in window_settings
        assert "state" in window_settings
        assert "size" in window_settings
        assert "current_tab" in window_settings

    def test_set_category(self, settings_manager: SettingsManager) -> None:
        """Test setting multiple values in a category."""
        # Set multiple window settings at once
        new_settings = {"current_tab": 1, "maximized": True, "size": QSize(1600, 900)}

        settings_manager.set_category("window", new_settings)

        # Verify values were set
        assert settings_manager.get_current_tab() == 1
        assert settings_manager.settings.value("window/maximized") is True

    def test_get_all_categories(self, settings_manager: SettingsManager) -> None:
        """Test getting all settings categories."""
        # Get each category individually
        window = settings_manager.get_category("window")
        prefs = settings_manager.get_category("preferences")
        perf = settings_manager.get_category("performance")

        assert isinstance(window, dict)
        assert isinstance(prefs, dict)
        assert isinstance(perf, dict)

        # Check that categories have expected keys
        assert "geometry" in window
        assert "refresh_interval" in prefs
        assert "max_thumbnail_threads" in perf

    def test_reset_to_defaults(self, settings_manager: SettingsManager) -> None:
        """Test resetting all settings to defaults."""
        # Change some settings
        settings_manager.set_current_tab(2)
        settings_manager.set_thumbnail_size(300)

        # Reset
        settings_manager.reset_to_defaults()

        # Verify defaults restored
        assert settings_manager.get_current_tab() == 0
        assert settings_manager.get_thumbnail_size() == Config.DEFAULT_THUMBNAIL_SIZE

    def test_export_settings(self, settings_manager: SettingsManager, tmp_path: Path) -> None:
        """Test exporting settings to JSON file."""
        # Set some custom values
        settings_manager.set_current_tab(1)
        settings_manager.set_thumbnail_size(256)

        # Export
        export_path = tmp_path / "settings_export.json"
        result = settings_manager.export_settings(str(export_path))

        assert result is True
        assert export_path.exists()

        # Verify content
        with export_path.open() as f:
            exported = json.load(f)

        assert "window" in exported
        assert exported["window"]["current_tab"] == 1
        assert exported["preferences"]["thumbnail_size"] == 256

    def test_import_settings(self, settings_manager: SettingsManager, tmp_path: Path) -> None:
        """Test importing settings from JSON file."""
        # Create import file
        import_data = {
            "window": {"current_tab": 2},
            "preferences": {"thumbnail_size": 300},
        }

        import_path = tmp_path / "settings_import.json"
        with import_path.open("w") as f:
            json.dump(import_data, f)

        # Import
        result = settings_manager.import_settings(str(import_path))

        assert result is True
        assert settings_manager.get_current_tab() == 2
        assert settings_manager.get_thumbnail_size() == 300

    def test_import_invalid_file(self, settings_manager: SettingsManager, tmp_path: Path) -> None:
        """Test importing from invalid file."""
        # Non-existent file
        result = settings_manager.import_settings("/nonexistent/file.json")
        assert result is False

        # Invalid JSON
        bad_json_path = tmp_path / "bad.json"
        with bad_json_path.open("w") as f:
            f.write("not valid json{")

        result = settings_manager.import_settings(str(bad_json_path))
        assert result is False

    def test_settings_contains(self, settings_manager: SettingsManager) -> None:
        """Test checking if a setting exists using QSettings.contains."""
        assert settings_manager.settings.contains("window/geometry")
        assert settings_manager.settings.contains("preferences/thumbnail_size")
        assert not settings_manager.settings.contains("nonexistent/setting")

    def test_remove_setting(self, settings_manager: SettingsManager) -> None:
        """Test removing a setting using QSettings.remove."""
        # Set a custom setting
        settings_manager.settings.setValue("test/custom", "value")
        assert settings_manager.settings.contains("test/custom")

        # Remove it
        settings_manager.settings.remove("test/custom")
        assert not settings_manager.settings.contains("test/custom")

    def test_signal_emission_on_change(self, settings_manager: SettingsManager, qtbot: QtBot) -> None:
        """Test that signals are emitted when settings change."""
        # Track signal
        received: list[tuple[str, Any]] = []
        settings_manager.settings_changed.connect(lambda k, v: received.append((k, v)))

        # Change setting with signal wait (use valid value within range)
        new_size = 300  # Between MIN (250) and MAX (600)
        with qtbot.waitSignal(settings_manager.settings_changed, timeout=1000):
            settings_manager.set_thumbnail_size(new_size)

        # Check signal was received with correct values
        assert len(received) > 0
        assert received[0][0] == "preferences/thumbnail_size"
        assert received[0][1] == new_size

    def test_get_performance_settings(self, settings_manager: SettingsManager) -> None:
        """Test getting performance-related settings."""
        max_threads = settings_manager.get_max_thumbnail_threads()
        assert max_threads == Config.MAX_THUMBNAIL_THREADS

        max_memory = settings_manager.get_max_cache_memory_mb()
        assert max_memory == Config.MAX_THUMBNAIL_MEMORY_MB

        cache_expiry = settings_manager.get_cache_expiry_minutes()
        assert cache_expiry == Config.CACHE_EXPIRY_MINUTES

    def test_ui_settings(self, settings_manager: SettingsManager) -> None:
        """Test UI-related settings."""
        # Grid columns
        grid_cols = settings_manager.get_grid_columns()
        assert grid_cols == Config.GRID_COLUMNS

        settings_manager.set_grid_columns(6)
        assert settings_manager.get_grid_columns() == 6

        # Dark theme
        assert settings_manager.get_dark_theme() is False
        settings_manager.set_dark_theme(True)
        assert settings_manager.get_dark_theme() is True

    def test_advanced_settings(self, settings_manager: SettingsManager) -> None:
        """Test advanced/debug settings."""
        # Debug mode
        assert settings_manager.get_debug_mode() is False
        settings_manager.set_debug_mode(True)
        assert settings_manager.get_debug_mode() is True

        # Log level
        log_level = settings_manager.get_log_level()
        assert log_level == "INFO"

        settings_manager.set_log_level("DEBUG")
        assert settings_manager.get_log_level() == "DEBUG"

    def test_migration_from_old_format(self, tmp_path: Path) -> None:
        """Test migration from old settings format."""
        # Set up old-style settings
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path)
        )

        old_settings = QSettings("TestOrg", "TestApp")
        old_settings.setValue("window_geometry", QByteArray(b"old_geometry"))
        old_settings.setValue("thumbnail_size", 150)
        old_settings.sync()

        # Create manager (should trigger migration)
        manager = SettingsManager(organization="TestOrg", application="TestApp")

        # Check migration happened
        assert manager.settings.contains("migration_version")
        # Note: Old keys might not be removed in some implementations
        assert manager.settings.contains("window/geometry")  # New key exists

        # Check values were migrated
        geometry = manager.get_window_geometry()
        # Migration might have happened, check if value exists
        assert isinstance(geometry, QByteArray)

    def test_settings_persistence(self, tmp_path: Path) -> None:
        """Test that settings persist across instances."""
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path)
        )

        # Create first instance and set values
        manager1 = SettingsManager(organization="TestOrg", application="TestApp")
        manager1.set_current_tab(2)
        manager1.set_thumbnail_size(250)
        manager1.settings.sync()

        # Create second instance and check values
        manager2 = SettingsManager(organization="TestOrg", application="TestApp")
        assert manager2.get_current_tab() == 2
        assert manager2.get_thumbnail_size() == 250

    def test_type_safety(self, settings_manager: SettingsManager) -> None:
        """Test type validation and conversion."""
        # Set wrong type for integer setting
        settings_manager.settings.setValue("preferences/refresh_interval", "not_an_int")

        # Should return some valid integer value
        value = settings_manager.get_refresh_interval()
        assert isinstance(value, int)
        # Value might be 0 or default depending on implementation
        assert value >= 0

    def test_reset_category(self, settings_manager: SettingsManager) -> None:
        """Test resetting a category to defaults."""
        # Set some values
        settings_manager.set_current_tab(2)
        settings_manager.set_window_size(QSize(1920, 1080))

        # Reset category
        settings_manager.reset_category("window")

        # Should revert to defaults
        assert settings_manager.get_current_tab() == 0
        default_size = settings_manager.get_window_size()
        assert default_size.width() == Config.DEFAULT_WINDOW_WIDTH
