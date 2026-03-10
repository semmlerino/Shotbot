"""Unit tests for controllers/settings_controller.py.

Tests for SettingsController which manages settings-related functionality
extracted from MainWindow.

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior using protocol-based test doubles
- Cover load/save, apply settings, and reset layout
- Mock Qt dialogs for import/export tests
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtCore import QByteArray, QSize

from controllers.settings_controller import SettingsController


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ============================================================================
# Test Doubles
# ============================================================================


class SizeSliderDouble:
    """Test double for grid size slider."""

    __test__ = False

    def __init__(self) -> None:
        self._value = 100

    def setValue(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class GridWidgetDouble:
    """Test double for GridWidget with size_slider attribute."""

    __test__ = False

    def __init__(self) -> None:
        self.size_slider = SizeSliderDouble()


class SplitterDouble:
    """Test double for QSplitter."""

    __test__ = False

    def __init__(self) -> None:
        self._state = QByteArray(b"splitter_state")
        self._sizes: list[int] = [700, 300]

    def saveState(self) -> QByteArray:
        return self._state

    def restoreState(self, state: QByteArray) -> bool:
        self._state = state
        return True

    def setSizes(self, sizes: list[int]) -> None:
        self._sizes = sizes


class TabWidgetDouble:
    """Test double for QTabWidget."""

    __test__ = False

    def __init__(self) -> None:
        self._current_index = 0

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index


class SettingsManagerDouble:
    """Test double for SettingsManager."""

    __test__ = False

    def __init__(self) -> None:
        self._geometry = QByteArray(b"geometry")
        self._state = QByteArray(b"state")
        self._splitter_states: dict[str, QByteArray] = {}
        self._maximized = False
        self._current_tab = 0
        self._thumbnail_size = 150
        self._max_cache_memory_mb = 512
        self._cache_expiry_minutes = 60
        self._sync_called = False
        self._window_size = QSize(1200, 800)

    def get_window_geometry(self) -> QByteArray:
        return self._geometry

    def set_window_geometry(self, geometry: QByteArray) -> None:
        self._geometry = geometry

    def get_window_state(self) -> QByteArray:
        return self._state

    def set_window_state(self, state: QByteArray) -> None:
        self._state = state

    def get_splitter_state(self, name: str) -> QByteArray:
        return self._splitter_states.get(name, QByteArray())

    def set_splitter_state(self, name: str, state: QByteArray) -> None:
        self._splitter_states[name] = state

    def is_window_maximized(self) -> bool:
        return self._maximized

    def set_window_maximized(self, maximized: bool) -> None:
        self._maximized = maximized

    def get_current_tab(self) -> int:
        return self._current_tab

    def set_current_tab(self, index: int) -> None:
        self._current_tab = index

    def get_thumbnail_size(self) -> int:
        return self._thumbnail_size

    def set_thumbnail_size(self, size: int) -> None:
        self._thumbnail_size = size

    def get_max_cache_memory_mb(self) -> int:
        return self._max_cache_memory_mb

    def get_cache_expiry_minutes(self) -> int:
        return self._cache_expiry_minutes

    def get_window_size(self) -> QSize:
        return self._window_size

    def sync(self) -> None:
        self._sync_called = True

    def import_settings(self, path: str) -> bool:
        return True

    def export_settings(self, path: str) -> bool:
        return True


class CacheCoordinatorDouble:
    """Test double for CacheCoordinator."""

    __test__ = False

    def __init__(self) -> None:
        self._expiry_minutes: int | None = None

    def set_expiry_minutes(self, minutes: int) -> None:
        self._expiry_minutes = minutes


class SettingsTargetDouble:
    """Test double implementing SettingsTarget protocol.

    Provides all required attributes and methods for testing SettingsController.
    """

    __test__ = False

    def __init__(self) -> None:
        # Window state
        self._geometry = QByteArray(b"window_geometry")
        self._state = QByteArray(b"window_state")
        self._maximized = False
        self._size = QSize(1200, 800)
        self._show_maximized_called = False

        # Widget references
        self.settings_manager = SettingsManagerDouble()
        self.cache_coordinator = CacheCoordinatorDouble()
        self.splitter = SplitterDouble()
        self.tab_widget = TabWidgetDouble()
        self.shot_grid = GridWidgetDouble()
        self.threede_shot_grid = GridWidgetDouble()
        self.previous_shots_grid = GridWidgetDouble()
        self._settings_dialog = None

    def restoreGeometry(self, geometry: QByteArray) -> bool:
        self._geometry = geometry
        return True

    def saveGeometry(self) -> QByteArray:
        return self._geometry

    def restoreState(self, state: QByteArray) -> bool:
        self._state = state
        return True

    def saveState(self) -> QByteArray:
        return self._state

    def isMaximized(self) -> bool:
        return self._maximized

    def showMaximized(self) -> None:
        self._maximized = True
        self._show_maximized_called = True

    def resize(self, w: int, h: int) -> None:
        self._size = QSize(w, h)

    def get_window_size(self) -> QSize:
        return self._size

    def set_thumbnail_size(self, size: int) -> None:
        self.shot_grid.size_slider.setValue(size)
        self.threede_shot_grid.size_slider.setValue(size)
        self.previous_shots_grid.size_slider.setValue(size)

    def get_thumbnail_size(self) -> int:
        return self.shot_grid.size_slider.value()

    def get_splitter_state(self) -> QByteArray:
        return self.splitter.saveState()

    def restore_splitter_state(self, state: QByteArray) -> bool:
        return self.splitter.restoreState(state)

    def get_current_tab(self) -> int:
        return self.tab_widget.currentIndex()

    def set_current_tab(self, index: int) -> None:
        self.tab_widget.setCurrentIndex(index)

    def reset_splitter_sizes(self, sizes: list[int]) -> None:
        self.splitter.setSizes(sizes)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def window_double() -> SettingsTargetDouble:
    """Create a SettingsTarget test double."""
    return SettingsTargetDouble()


@pytest.fixture
def controller(window_double: SettingsTargetDouble) -> SettingsController:
    """Create a SettingsController with test double."""
    return SettingsController(window_double)  # type: ignore[arg-type]


# ============================================================================
# Test Initialization
# ============================================================================


class TestSettingsControllerInitialization:
    """Test SettingsController initialization."""

    def test_init_stores_window_reference(
        self, window_double: SettingsTargetDouble
    ) -> None:
        """Test that init stores window reference."""
        controller = SettingsController(window_double)  # type: ignore[arg-type]
        assert controller.window is window_double


# ============================================================================
# Test Load Settings
# ============================================================================


class TestLoadSettings:
    """Test loading settings functionality."""

    def test_load_settings_restores_all_fields(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that load_settings restores all managed fields from settings manager."""
        # Set up all managed fields in settings manager
        window_double.settings_manager._geometry = QByteArray(b"saved_geometry")
        window_double.settings_manager._state = QByteArray(b"saved_state")
        window_double.settings_manager._splitter_states["main"] = QByteArray(b"main_splitter")
        window_double.settings_manager._maximized = True
        window_double.settings_manager._current_tab = 2
        window_double.settings_manager._thumbnail_size = 200

        controller.load_settings()

        assert window_double._geometry == QByteArray(b"saved_geometry")
        assert window_double._state == QByteArray(b"saved_state")
        assert window_double.splitter._state == QByteArray(b"main_splitter")
        assert window_double._show_maximized_called is True
        assert window_double.tab_widget._current_index == 2
        assert window_double.shot_grid.size_slider._value == 200
        assert window_double.threede_shot_grid.size_slider._value == 200
        assert window_double.previous_shots_grid.size_slider._value == 200

    def test_load_settings_handles_empty_geometry(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that load_settings handles empty geometry gracefully."""
        window_double.settings_manager._geometry = QByteArray()  # Empty

        # Should not raise
        controller.load_settings()


# ============================================================================
# Test Save Settings
# ============================================================================


class TestSaveSettings:
    """Test saving settings functionality."""

    def test_save_settings_persists_all_fields(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that save_settings persists all managed fields to settings manager."""
        # Set up all managed fields on window double
        window_double._geometry = QByteArray(b"current_geometry")
        window_double._state = QByteArray(b"current_state")
        window_double.splitter._state = QByteArray(b"splitter_state")
        window_double._maximized = True
        window_double.tab_widget._current_index = 1
        window_double.shot_grid.size_slider._value = 175

        controller.save_settings()

        assert window_double.settings_manager._geometry == QByteArray(b"current_geometry")
        assert window_double.settings_manager._state == QByteArray(b"current_state")
        assert "main" in window_double.settings_manager._splitter_states
        assert window_double.settings_manager._maximized is True
        assert window_double.settings_manager._current_tab == 1
        assert window_double.settings_manager._thumbnail_size == 175

    def test_save_settings_calls_sync(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that save_settings calls sync on settings manager."""
        controller.save_settings()

        assert window_double.settings_manager._sync_called is True


# ============================================================================
# Test Apply Settings
# ============================================================================


class TestApplySettings:
    """Test applying settings functionality."""

    def test_apply_cache_settings_sets_expiry(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that apply_cache_settings sets expiry minutes."""
        window_double.settings_manager._cache_expiry_minutes = 120

        controller.apply_cache_settings()

        assert window_double.cache_coordinator._expiry_minutes == 120

    def test_on_settings_applied_updates_thumbnail_size(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that on_settings_applied updates thumbnail sizes."""
        window_double.settings_manager._thumbnail_size = 250

        controller.on_settings_applied()

        assert window_double.shot_grid.size_slider._value == 250
        assert window_double.threede_shot_grid.size_slider._value == 250
        assert window_double.previous_shots_grid.size_slider._value == 250


# ============================================================================
# Test Reset Layout
# ============================================================================


class TestResetLayout:
    """Test reset layout functionality."""

    def test_reset_layout_resets_window_size_on_confirmation(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that reset_layout resets window size when user confirms."""
        # Mock QMessageBox to return Yes
        with patch(
            "controllers.settings_controller.QMessageBox.question"
        ) as mock_question:
            from PySide6.QtWidgets import QMessageBox

            mock_question.return_value = QMessageBox.StandardButton.Yes

            controller.reset_layout()

            # Should have resized to defaults
            # Config.DEFAULT_WINDOW_WIDTH = 1200, Config.DEFAULT_WINDOW_HEIGHT = 800
            assert window_double._size.width() == 1200
            assert window_double._size.height() == 800

    def test_reset_layout_resets_splitter_on_confirmation(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that reset_layout resets splitter when user confirms."""
        with patch(
            "controllers.settings_controller.QMessageBox.question"
        ) as mock_question:
            from PySide6.QtWidgets import QMessageBox

            mock_question.return_value = QMessageBox.StandardButton.Yes

            controller.reset_layout()

            # Should have reset splitter sizes
            assert window_double.splitter._sizes == [840, 360]

    def test_reset_layout_does_nothing_on_cancel(
        self, controller: SettingsController, window_double: SettingsTargetDouble
    ) -> None:
        """Test that reset_layout does nothing when user cancels."""
        original_size = window_double._size

        with patch(
            "controllers.settings_controller.QMessageBox.question"
        ) as mock_question:
            from PySide6.QtWidgets import QMessageBox

            mock_question.return_value = QMessageBox.StandardButton.No

            controller.reset_layout()

            # Size should not have changed
            assert window_double._size == original_size


# ============================================================================
# Test Round Trip
# ============================================================================


class TestRoundTrip:
    """Test save and load round-trip."""

    def test_save_then_load_restores_state(
        self, window_double: SettingsTargetDouble
    ) -> None:
        """Test that save followed by load restores the same state."""
        controller = SettingsController(window_double)  # type: ignore[arg-type]

        # Set up initial state
        window_double.tab_widget._current_index = 2
        window_double.shot_grid.size_slider._value = 180
        window_double._maximized = True

        # Save
        controller.save_settings()

        # Reset window state
        window_double.tab_widget._current_index = 0
        window_double.shot_grid.size_slider._value = 100
        window_double._maximized = False

        # Load
        controller.load_settings()

        # Verify restored
        assert window_double.tab_widget._current_index == 2
        assert window_double.shot_grid.size_slider._value == 180
        assert window_double._show_maximized_called is True
