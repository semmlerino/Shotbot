"""Settings persistence and edge-case tests.

Tests covering gaps not addressed by test_settings_controller.py:
- Full field roundtrip via the real SettingsManager (QSettings + INI file)
- Behavior under empty/corrupted QSettings
- Export/import roundtrip
- Boundary and type-edge values
- Concurrent access from multiple controllers
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QSettings, QSize

from config import Config
from controllers.settings_controller import SettingsController
from managers.settings_manager import SettingsManager
from tests.unit.test_settings_controller import (
    CacheCoordinatorDouble,
    GridWidgetDouble,
    SplitterDouble,
    TabWidgetDouble,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ============================================================================
# Helpers: real SettingsManager backed by a temp INI file
# ============================================================================


def make_real_manager(tmp_path: Path, name: str = "test") -> SettingsManager:
    """Create a SettingsManager backed by a per-test INI file.

    Using IniFormat + explicit file path keeps tests hermetic: each call
    produces an isolated file that is never shared with the system registry
    or other tests.
    """
    ini_path = str(tmp_path / f"{name}.ini")
    manager = SettingsManager.__new__(SettingsManager)
    # Bypass the default QSettings(org, app) constructor; inject an INI file
    # QObject.__init__ is called explicitly so signals work.
    from PySide6.QtCore import QObject

    QObject.__init__(manager)
    manager.settings = QSettings(ini_path, QSettings.Format.IniFormat)
    manager._initialize_defaults()
    manager._migrate_old_settings()
    return manager


# ============================================================================
# Test doubles — reused from test_settings_controller pattern
# ============================================================================


class _WindowDouble:
    """SettingsTarget test double that holds a real SettingsManager."""

    __test__ = False

    def __init__(self, real_manager: SettingsManager) -> None:
        self._geometry = QByteArray(b"window_geometry")
        self._state = QByteArray(b"window_state")
        self._maximized = False
        self._size = QSize(1200, 800)
        self._show_maximized_called = False

        self.settings_manager = real_manager
        self.cache_coordinator = CacheCoordinatorDouble()
        self.splitter = SplitterDouble()
        self.tab_widget = TabWidgetDouble()
        self.shot_grid = GridWidgetDouble()
        self.threede_shot_grid = GridWidgetDouble()
        self.previous_shots_grid = GridWidgetDouble()
        self.settings_dialog = None

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
def real_manager(tmp_path: Path) -> SettingsManager:
    """Real SettingsManager backed by a temp INI file."""
    return make_real_manager(tmp_path)


@pytest.fixture
def window(real_manager: SettingsManager) -> _WindowDouble:
    """Window double wired to a real SettingsManager."""
    return _WindowDouble(real_manager)


@pytest.fixture
def controller(window: _WindowDouble) -> SettingsController:
    return SettingsController(window)  # type: ignore[arg-type]


# ============================================================================
# 1. Full-field roundtrip via real SettingsManager
# ============================================================================


class TestFullRoundtrip:
    """Every field saved by save_settings() must survive a load_settings() cycle."""

    def test_all_fields_survive_roundtrip(self, tmp_path: Path) -> None:
        """save_settings → clear live state → load_settings restores all fields."""
        manager = make_real_manager(tmp_path)
        window = _WindowDouble(manager)
        ctrl = SettingsController(window)  # type: ignore[arg-type]

        # Set distinctive values for every field the controller manages
        window._geometry = QByteArray(b"custom_geometry_data")
        window._state = QByteArray(b"custom_state_data")
        window.splitter._state = QByteArray(b"custom_splitter_data")
        window._maximized = False
        window.tab_widget._current_index = 2
        window.shot_grid.size_slider._value = 600

        ctrl.save_settings()

        # Wipe all live state
        window._geometry = QByteArray()
        window._state = QByteArray()
        window.splitter._state = QByteArray()
        window._maximized = False
        window._show_maximized_called = False
        window.tab_widget._current_index = 0
        window.shot_grid.size_slider._value = 100

        ctrl.load_settings()

        assert window._geometry == QByteArray(b"custom_geometry_data")
        assert window._state == QByteArray(b"custom_state_data")
        assert window.splitter._state == QByteArray(b"custom_splitter_data")
        assert window.tab_widget._current_index == 2
        assert window.shot_grid.size_slider._value == 600

    def test_geometry_bytes_survive_disk_flush(self, tmp_path: Path) -> None:
        """Geometry bytes written with sync() are intact after a fresh SettingsManager."""
        manager1 = make_real_manager(tmp_path, name="flush_test")
        manager1.window.set_window_geometry(QByteArray(b"\x00\xff\xab\xcd"))
        manager1.sync()

        # Simulate a restart: new SettingsManager reads the same file
        manager2 = make_real_manager(tmp_path, name="flush_test")
        assert manager2.window.get_window_geometry() == QByteArray(b"\x00\xff\xab\xcd")


# ============================================================================
# 2. Persistence after simulated crash (incomplete save)
# ============================================================================


class TestSimulatedCrash:
    """Settings manager must handle corrupted or partially-written state gracefully."""

    def test_empty_qsettings_produces_defaults(self, tmp_path: Path) -> None:
        """A completely empty INI file yields default values, not exceptions."""
        ini_path = str(tmp_path / "empty.ini")
        # Write a blank file (simulates a crash before any write completed)
        Path(ini_path).write_bytes(b"")

        manager = SettingsManager.__new__(SettingsManager)
        from PySide6.QtCore import QObject

        QObject.__init__(manager)
        manager.settings = QSettings(ini_path, QSettings.Format.IniFormat)
        manager._initialize_defaults()
        manager._migrate_old_settings()

        # Must return defaults without raising
        assert manager.ui.get_thumbnail_size() == Config.Thumbnail.DEFAULT_SIZE
        assert manager.window.get_current_tab() == 0
        assert manager.window.get_window_geometry().isEmpty()
        assert manager.window.is_window_maximized() is False

    def test_corrupted_binary_splitter_state_falls_back_gracefully(
        self, tmp_path: Path
    ) -> None:
        """A QByteArray with garbage bytes is passed through without a crash.

        The SettingsManager stores whatever bytes are given; QSplitter.restoreState()
        is the consumer that decides whether the bytes are valid.  The controller
        must not crash before handing the value to the splitter.
        """
        manager = make_real_manager(tmp_path)
        garbage = QByteArray(b"\xde\xad\xbe\xef" * 64)
        manager.window.set_splitter_state("main", garbage)

        window = _WindowDouble(manager)
        ctrl = SettingsController(window)  # type: ignore[arg-type]

        # load_settings must not raise even with invalid splitter bytes
        ctrl.load_settings()

        # The garbage bytes were handed to the splitter as-is
        assert window.splitter._state == garbage

    def test_load_settings_after_missing_all_window_keys(self, tmp_path: Path) -> None:
        """load_settings does not raise when the entire window/ category is absent."""
        ini_path = str(tmp_path / "no_window.ini")
        # Write only non-window settings
        Path(ini_path).write_text("[preferences]\nthumbnail_size = 500\n")

        manager = SettingsManager.__new__(SettingsManager)
        from PySide6.QtCore import QObject

        QObject.__init__(manager)
        manager.settings = QSettings(ini_path, QSettings.Format.IniFormat)
        manager._initialize_defaults()
        manager._migrate_old_settings()

        window = _WindowDouble(manager)
        ctrl = SettingsController(window)  # type: ignore[arg-type]

        # Must not raise
        ctrl.load_settings()

        # Should have fallen back to empty geometry (no geometry key present after
        # _initialize_defaults seeds an empty QByteArray, which isEmpty() → True)
        assert window._geometry == QByteArray(b"window_geometry")  # unchanged default

    def test_controller_catches_exception_from_broken_settings_manager(
        self, tmp_path: Path
    ) -> None:
        """load_settings swallows the exception and falls back to a default resize."""

        class _BrokenManager:
            __test__ = False

            def __init__(self) -> None:
                self.window = self  # type: ignore[assignment]
                self.ui = self  # type: ignore[assignment]
                self.performance = self  # type: ignore[assignment]

            def get_window_geometry(self) -> QByteArray:
                raise RuntimeError("disk read failed")

            def get_window_size(self) -> QSize:
                return QSize(1200, 800)

            def get_cache_expiry_minutes(self) -> int:
                return 60

        class _BrokenWindow:
            __test__ = False
            settings_manager = _BrokenManager()
            cache_coordinator = CacheCoordinatorDouble()
            splitter = SplitterDouble()
            tab_widget = TabWidgetDouble()
            settings_dialog = None
            _size = QSize(0, 0)

            def restoreGeometry(self, g: QByteArray) -> bool:
                return True

            def saveGeometry(self) -> QByteArray:
                return QByteArray()

            def restoreState(self, s: QByteArray) -> bool:
                return True

            def saveState(self) -> QByteArray:
                return QByteArray()

            def isMaximized(self) -> bool:
                return False

            def showMaximized(self) -> None:
                pass

            def resize(self, w: int, h: int) -> None:
                self._size = QSize(w, h)

            def get_window_size(self) -> QSize:
                return self._size

            def set_thumbnail_size(self, size: int) -> None:
                pass

            def get_thumbnail_size(self) -> int:
                return 150

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

        broken_window = _BrokenWindow()
        ctrl = SettingsController(broken_window)  # type: ignore[arg-type]

        # Must not raise — controller catches the exception internally
        ctrl.load_settings()

        # Fallback resize should have been called with QSize from get_window_size()
        assert broken_window._size == QSize(1200, 800)


# ============================================================================
# 3. Import/export roundtrip
# ============================================================================


class TestImportExportRoundtrip:
    """export_settings → modify in memory → import_settings restores originals."""

    def test_export_then_import_restores_cache_expiry(self, tmp_path: Path) -> None:
        """Exported cache expiry is restored after import."""
        manager = make_real_manager(tmp_path)
        manager.performance.set_cache_expiry_minutes(120)
        manager.sync()

        export_path = str(tmp_path / "cache_settings.json")
        assert manager.export_settings(export_path) is True

        manager.performance.set_cache_expiry_minutes(Config.Cache.EXPIRY_MINUTES)

        assert manager.import_settings(export_path) is True
        assert manager.performance.get_cache_expiry_minutes() == 120

    def test_import_with_extra_unknown_keys_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """Importing a file with extra keys is tolerated without exception."""
        export_path = str(tmp_path / "extra_keys.json")
        data = {
            "preferences": {"thumbnail_size": 500, "unknown_future_key": "ignored"},
            "new_unknown_category": {"key": "value"},
        }
        with Path(export_path).open("w") as f:
            json.dump(data, f)

        manager = make_real_manager(tmp_path)
        # Must return True (or at worst False) — never raise
        result = manager.import_settings(export_path)
        assert isinstance(result, bool)

    def test_import_non_dict_json_returns_false(self, tmp_path: Path) -> None:
        """A JSON file whose root is a list (not dict) returns False."""
        list_path = str(tmp_path / "list.json")
        with Path(list_path).open("w") as f:
            json.dump([1, 2, 3], f)

        manager = make_real_manager(tmp_path)
        assert manager.import_settings(list_path) is False


# ============================================================================
# 4. Edge cases — validation clamping
# ============================================================================


class TestEdgeCases:
    """Boundary values, type mismatches, and validation clamping."""

    @pytest.mark.parametrize(
        ("domain", "setter", "input_value", "getter", "expected"),
        [
            (
                "ui",
                "set_thumbnail_size",
                0,
                "get_thumbnail_size",
                Config.Thumbnail.MIN_SIZE,
            ),
            (
                "performance",
                "set_cache_expiry_minutes",
                0,
                "get_cache_expiry_minutes",
                5,
            ),
            (
                "performance",
                "set_cache_expiry_minutes",
                999_999,
                "get_cache_expiry_minutes",
                10080,
            ),
            ("refresh", "set_refresh_interval", 0, "get_refresh_interval", 1),
            ("refresh", "set_refresh_interval", 99_999, "get_refresh_interval", 1440),
        ],
        ids=[
            "thumbnail_zero_clamped",
            "cache_expiry_below_min",
            "cache_expiry_above_max",
            "refresh_below_min",
            "refresh_above_max",
        ],
    )
    def test_value_clamped_to_valid_range(
        self,
        real_manager: SettingsManager,
        domain: str,
        setter: str,
        input_value: int,
        getter: str,
        expected: int,
    ) -> None:
        """Out-of-range values are clamped to valid boundaries."""
        domain_obj = getattr(real_manager, domain)
        getattr(domain_obj, setter)(input_value)
        assert getattr(domain_obj, getter)() == expected

    def test_empty_geometry_does_not_trigger_restore(
        self, window: _WindowDouble, controller: SettingsController
    ) -> None:
        """load_settings skips restoreGeometry when the stored value is empty."""
        original_geometry = window._geometry
        window.settings_manager.window.set_window_geometry(QByteArray())  # empty

        controller.load_settings()

        # Window geometry should be unchanged because isEmpty() guard was respected
        assert window._geometry == original_geometry


# ============================================================================
# 5. Concurrent access — multiple controllers, shared manager
# ============================================================================


class TestConcurrentAccess:
    """Two SettingsController instances sharing a single SettingsManager.

    In real use this does not happen at runtime, but verifies that the last
    writer wins and that neither controller corrupts the shared state.
    """

    def test_second_save_overwrites_first(self, tmp_path: Path) -> None:
        """The last controller to call save_settings() determines what is persisted."""
        manager = make_real_manager(tmp_path)

        window_a = _WindowDouble(manager)
        window_a.tab_widget._current_index = 1
        window_a.shot_grid.size_slider._value = 500

        window_b = _WindowDouble(manager)
        window_b.tab_widget._current_index = 3
        window_b.shot_grid.size_slider._value = 700

        ctrl_a = SettingsController(window_a)  # type: ignore[arg-type]
        ctrl_b = SettingsController(window_b)  # type: ignore[arg-type]

        ctrl_a.save_settings()
        ctrl_b.save_settings()  # Overwrites ctrl_a's values

        # Verify persisted state matches ctrl_b (last writer)
        assert manager.window.get_current_tab() == 3
        assert manager.ui.get_thumbnail_size() == 700

    def test_first_load_does_not_affect_second_controllers_window(
        self, tmp_path: Path
    ) -> None:
        """Loading settings into one window does not mutate a sibling window."""
        manager = make_real_manager(tmp_path)
        manager.window.set_current_tab(2)
        manager.ui.set_thumbnail_size(800)

        window_a = _WindowDouble(manager)
        window_b = _WindowDouble(manager)

        ctrl_a = SettingsController(window_a)  # type: ignore[arg-type]
        ctrl_a.load_settings()

        # window_b was never loaded — its tab index must remain at its initial value
        assert window_b.tab_widget._current_index == 0
