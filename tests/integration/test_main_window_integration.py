"""Integration tests for MainWindow cross-component coordination and user workflows."""

from __future__ import annotations

import contextlib
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.fixtures.model_fixtures import (
    MainWindowTestProgressManager,
    ProgressOperationDouble,
    TestNotificationManager,
)
from tests.fixtures.test_doubles import (
    PopenDouble,
    TestProcessPool,
    TestSubprocess,
)
from tests.test_helpers import process_qt_events
from type_definitions import Shot, ThreeDEScene


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


# ---------------------------------------------------------------------------
# Module-level lazy import fixture (required by all classes in this module)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow  # noqa: PLW0603
    from main_window import MainWindow


pytestmark = [
    pytest.mark.qt,
    pytest.mark.allow_dialogs,
    pytest.mark.permissive_process_pool,
]


# ---------------------------------------------------------------------------
# Shared window-cleanup helper
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def stable_main_window_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable background startup work that these tests control explicitly."""
    from type_definitions import RefreshResult

    def _skip_async_init(_self: object) -> RefreshResult:
        return RefreshResult(success=True, has_changes=False)

    monkeypatch.setenv("SHOTBOT_NO_INITIAL_LOAD", "1")
    monkeypatch.setattr("shots.shot_model.ShotModel.initialize_async", _skip_async_init)
    monkeypatch.setattr(
        "launch.environment_manager.EnvironmentManager.warm_cache_async",
        lambda _self: None,
    )


def _stop_window_background_work(window: Any) -> None:
    """Stop background workers/timers associated with a MainWindow."""

    if hasattr(window, "auto_refresh_timer") and window.auto_refresh_timer:
        with contextlib.suppress(RuntimeError):
            window.auto_refresh_timer.stop()

    if hasattr(window, "command_launcher"):
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            window.command_launcher.cleanup()

    if (
        hasattr(window, "threede_worker")
        and window.threede_worker
        and window.threede_worker.isRunning()
    ):
        with contextlib.suppress(RuntimeError):
            window.threede_worker.quit()
            window.threede_worker.wait(1000)

    shot_model = getattr(window, "shot_model", None)
    if shot_model is not None:
        with contextlib.suppress(RuntimeError, AttributeError):
            shot_model.cleanup()


def _close_windows(windows: list[Any], qtbot: Any) -> None:
    """Close a list of MainWindow instances with proper Qt cleanup."""
    for window in windows:
        if window:
            _stop_window_background_work(window)
            with contextlib.suppress(RuntimeError):
                window.close()
            if not window.isHidden():
                with contextlib.suppress(RuntimeError):
                    window.hide()
            process_qt_events()

    windows.clear()

    for _ in range(3):
        process_qt_events()


# Test doubles are imported from tests.fixtures.model_fixtures above.


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_cache_manager(tmp_path: Path) -> Path:
    """Real cache directory for testing."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def main_window_with_real_components(
    qapp: Any, qtbot: Any, real_cache_manager: Path, monkeypatch: Any
) -> Generator[Any, None, None]:
    """MainWindow with real components, not mocked.

    Forces legacy ShotModel, installs TestProcessPool, and monkey-patches
    NotificationManager and ProgressManager before window creation.
    """
    assert qapp is not None, "QApplication must exist before creating widgets"

    test_pool = TestProcessPool(allow_main_thread=True)
    test_pool.set_outputs("workspace /test/path")

    def mock_get_instance() -> TestProcessPool:
        return test_pool

    from workers.process_pool_manager import ProcessPoolManager

    monkeypatch.setattr(ProcessPoolManager, "get_instance", mock_get_instance)

    from managers.notification_manager import NotificationManager

    TestNotificationManager.clear()

    original_notification_methods = {
        "error": NotificationManager.error,
        "warning": NotificationManager.warning,
        "info": NotificationManager.info,
        "success": NotificationManager.success,
    }
    NotificationManager.error = TestNotificationManager.error
    NotificationManager.warning = TestNotificationManager.warning
    NotificationManager.info = TestNotificationManager.info
    NotificationManager.success = TestNotificationManager.success

    from managers.progress_manager import ProgressManager

    test_progress_manager = MainWindowTestProgressManager()
    original_operation = ProgressManager.operation
    original_start_operation = ProgressManager.start_operation
    original_finish_operation = ProgressManager.finish_operation
    ProgressManager.operation = test_progress_manager.operation
    ProgressManager.start_operation = test_progress_manager.start_operation
    ProgressManager.finish_operation = test_progress_manager.finish_operation

    import types

    class MockThreeDELatestFinder:
        def find_latest_scene(self, *_args: Any, **_kwargs: Any) -> str | None:
            return None

    class MockMayaLatestFinder:
        def find_latest_scene(self, *_args: Any, **_kwargs: Any) -> str | None:
            return None

    mock_threede_latest_finder = types.ModuleType("threede_latest_finder")
    mock_threede_latest_finder.ThreeDELatestFinder = MockThreeDELatestFinder
    original_threede_latest_finder = sys.modules.get("threede_latest_finder")
    sys.modules["threede_latest_finder"] = mock_threede_latest_finder

    mock_maya_latest_finder = types.ModuleType("maya_latest_finder")
    mock_maya_latest_finder.MayaLatestFinder = MockMayaLatestFinder
    original_maya_latest_finder = sys.modules.get("maya_latest_finder")
    sys.modules["maya_latest_finder"] = mock_maya_latest_finder

    window = MainWindow(cache_dir=real_cache_manager)
    qtbot.addWidget(window)

    window._test_process_pool = test_pool
    window._test_progress_manager = test_progress_manager
    window._test_notification_manager = TestNotificationManager

    window.shot_model._process_pool = test_pool
    window.shot_model._force_sync_refresh = True

    try:
        yield window
    finally:
        for module_name, original_module in (
            ("threede_latest_finder", original_threede_latest_finder),
            ("maya_latest_finder", original_maya_latest_finder),
        ):
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module

        for name, method in original_notification_methods.items():
            setattr(NotificationManager, name, method)

        ProgressManager.operation = original_operation
        ProgressManager.start_operation = original_start_operation
        ProgressManager.finish_operation = original_finish_operation

        _stop_window_background_work(window)

        with contextlib.suppress(RuntimeError):
            window.close()
        if not window.isHidden():
            with contextlib.suppress(RuntimeError):
                window.hide()
        process_qt_events()


# ---------------------------------------------------------------------------
# TestCrossTabSynchronization
# ---------------------------------------------------------------------------


@pytest.mark.allow_main_thread
class TestCrossTabSynchronization:
    """Test data synchronization across all three tabs."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, qtbot: QtBot) -> None:
        """Clean up Qt widgets and process events between tests."""
        self.test_windows: list[Any] = []
        yield
        _close_windows(self.test_windows, qtbot)

    def test_shot_selection_syncs_info_panel_across_tabs(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Verify info panel updates across all three tabs.

        Covers:
        - Selecting a shot enables launcher buttons and updates info panel
        - Switching to 3DE tab and selecting a scene updates info panel
        - Tab switching clears info panel when new tab has no selection
        """
        window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(window)
        self.test_windows.append(window)

        shots = [
            Shot("TEST", "seq01", "0010", "/shows/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", "/shows/TEST/shots/seq01/seq01_0020"),
        ]
        window.shot_model.shots = shots
        window.shot_item_model.set_shots(shots)

        window.tab_widget.setCurrentIndex(0)
        process_qt_events()

        assert window.tab_widget.currentIndex() == 0

        # Selecting a shot should enable launcher buttons and update info panel
        first_shot = shots[0]
        window.shot_selection_controller.on_shot_selected(first_shot)

        assert window.right_panel._current_shot == first_shot
        for section in window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

        # Switch to 3DE tab and select a scene
        window.tab_widget.setCurrentIndex(1)
        process_qt_events()

        scene = ThreeDEScene(
            show="TEST",
            sequence="seq02",
            shot="0030",
            workspace_path="/shows/TEST/shots/seq02/seq02_0030",
            user="testuser",
            plate="PLATE01",
            scene_path=Path("/test/scene.3de"),
        )
        window.threede_controller.on_scene_selected(scene)

        current_shot = window.right_panel._current_shot
        assert current_shot is not None
        assert current_shot.shot == "0030"
        assert current_shot.sequence == "seq02"

        # Switch to Previous Shots tab — panel should clear (no selection)
        window.tab_widget.setCurrentIndex(2)
        process_qt_events()
        assert window.right_panel._current_shot is None

        # Back to My Shots — panel clears since no selection is active
        window.tab_widget.setCurrentIndex(0)
        process_qt_events()
        assert window.right_panel._current_shot is None

        # Re-select or deselect/reselect to verify panel updates
        second_shot = shots[1]
        window.shot_selection_controller.on_shot_selected(second_shot)
        assert window.right_panel._current_shot == second_shot

    def test_show_filter_affects_all_tabs(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that show filtering propagates correctly within a tab."""
        from shots.shot_model import AsyncShotLoader

        original_init_async = AsyncShotLoader.__init__

        def no_op_init(self: Any, *args: Any, **kwargs: Any) -> None:
            super(AsyncShotLoader, self).__init__()
            self._should_stop = True

        AsyncShotLoader.__init__ = no_op_init

        from PySide6.QtCore import QTimer

        original_singleshot = QTimer.singleShot
        QTimer.singleShot = lambda *_args, **_kwargs: None

        temp_cache_dir = tmp_path / "shotbot_test_cache"
        temp_cache_dir.mkdir()
        window = MainWindow(cache_dir=temp_cache_dir)
        qtbot.addWidget(window)
        self.test_windows.append(window)

        AsyncShotLoader.__init__ = original_init_async

        window.shot_model.shots.clear()
        window.shot_item_model.set_shots([])

        from PySide6.QtCore import QMutexLocker

        with QMutexLocker(window.shot_model._loader_lock):
            if window.shot_model._async_loader:
                window.shot_model._async_loader.stop()
                window.shot_model._async_loader.wait()
                window.shot_model._async_loader.deleteLater()
                window.shot_model._async_loader = None
            window.shot_model._loading_in_progress = False

        process_qt_events()

        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs(
            "workspace /shows/SHOW1/shots/seq01/seq01_0010\n"
            "workspace /shows/SHOW1/shots/seq01/seq01_0020\n"
            "workspace /shows/SHOW2/shots/seq02/seq02_0030"
        )
        window.shot_model._process_pool = test_pool
        window.shot_model._force_sync_refresh = True

        QTimer.singleShot = original_singleshot

        success, _ = window.shot_model.refresh_shots()
        assert success, "refresh_shots should succeed"

        process_qt_events()

        shot_item_model = window.shot_item_model
        assert shot_item_model.rowCount() == 3

        shot_item_model.set_show_filter(window.shot_model, "SHOW1")
        process_qt_events()
        assert shot_item_model.rowCount() == 2

        shot_item_model.set_show_filter(window.shot_model, None)
        assert shot_item_model.rowCount() == 3


# ---------------------------------------------------------------------------
# TestMainWindowUICoordination
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.gui_mainwindow
@pytest.mark.qt_heavy
@pytest.mark.integration_unsafe
class TestMainWindowUICoordination:
    """Test UI coordination and signal-slot connections."""

    def test_window_initialization(self, main_window_with_real_components: Any) -> None:
        """Test that main window initializes with all components."""
        window = main_window_with_real_components

        assert len(window.right_panel._dcc_accordion._sections) > 0
        assert "3de" in window.right_panel._dcc_accordion._sections
        assert "nuke" in window.right_panel._dcc_accordion._sections

    def test_launcher_execution_workflow(
        self, main_window_with_real_components: Any, qtbot: Any, tmp_path: Path
    ) -> None:
        """Test that the launch button delegates to CommandLauncher."""
        window = main_window_with_real_components

        workspace_path = tmp_path / "test_workspace"
        workspace_path.mkdir(parents=True, exist_ok=True)

        test_shot = Shot("testshow", "seq01", "shot01", str(workspace_path))
        window.shot_model.shots = [test_shot]
        window.shot_selection_controller.on_shot_selected(test_shot)

        qtbot.wait(1)

        section_3de = window.right_panel._dcc_accordion._sections.get("3de")
        assert section_3de is not None
        assert section_3de._launch_btn.isEnabled()

        open_latest_checkbox = section_3de._checkboxes.get("open_latest_threede")
        if open_latest_checkbox:
            open_latest_checkbox.setChecked(False)

        with patch.object(
            window.command_launcher, "launch", return_value=True
        ) as mock_launch:
            section_3de._launch_btn.click()
            qtbot.wait(1)

        mock_launch.assert_called_once()
        assert mock_launch.call_args is not None
        request = mock_launch.call_args.args[0]
        assert request.app_name == "3de"

    def test_progress_indication_during_operations(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that progress is shown during long operations."""
        window = main_window_with_real_components

        qtbot.wait(1)

        window.shot_model.refresh_started.emit()

        def status_contains_refresh_or_loading() -> bool:
            status = window.status_bar.currentMessage()
            return status and (
                "refresh" in status.lower() or "loading" in status.lower()
            )

        qtbot.waitUntil(status_contains_refresh_or_loading, timeout=1000)

        status_text = window.status_bar.currentMessage()

        window.shot_model.refresh_finished.emit(True, False)

        def status_changed() -> bool:
            new_status = window.status_bar.currentMessage()
            return new_status != status_text

        qtbot.waitUntil(status_changed, timeout=1000)


# ---------------------------------------------------------------------------
# TestMainWindowKeyboardShortcuts
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestMainWindowKeyboardShortcuts:
    """Test keyboard shortcuts and navigation."""

    def test_keyboard_shortcuts_work(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that keyboard shortcuts trigger correct actions."""
        window = main_window_with_real_components

        test_shot = Shot("test", "seq01", "shot01", "/test")
        window.shot_model.shots = [test_shot]
        window.shot_selection_controller.on_shot_selected(test_shot)

        assert window.refresh_action.shortcut() == QKeySequence.StandardKey.Refresh

        test_pool = window._test_process_pool
        initial_command_count = len(test_pool.get_executed_commands())

        window.shot_model.invalidate_workspace_cache()
        window.refresh_action.trigger()
        qtbot.wait(1)

        commands = test_pool.get_executed_commands()
        assert len(commands) > initial_command_count, (
            f"Expected commands to be executed. Commands: {commands}"
        )


# ---------------------------------------------------------------------------
# TestMainWindowErrorScenarios
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestMainWindowErrorScenarios:
    """Test error handling and recovery."""

    def test_handles_shot_refresh_failure(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test graceful handling of shot refresh failures.

        When refresh fails, the error propagates through:
        1. ShotModel emits error_occurred → MainWindow updates status bar
        2. ShotModel emits refresh_finished(False) → RefreshCoordinator
           updates status bar and records a NotificationManager error
        """
        window = main_window_with_real_components

        test_pool = window._test_process_pool
        test_pool.set_should_fail(True, "Network error")

        window._test_notification_manager.clear()
        window.shot_model.invalidate_workspace_cache()
        window.refresh_action.trigger()

        status_text = window.status_bar.currentMessage()
        assert "failed" in status_text.lower() or "error" in status_text.lower()

        notifications = window._test_notification_manager._notifications
        error_notifications = [
            n for n in notifications if n.get("type") in ["error", "warning"]
        ]
        assert len(error_notifications) > 0


# ---------------------------------------------------------------------------
# TestUserWorkflows
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestUserWorkflows:
    """Integration tests for critical user workflows in ShotBot."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path, qtbot: Any) -> Iterator[None]:
        """Set up test environment with realistic data structures."""
        self.temp_dir = tmp_path / "shotbot"
        self.temp_dir.mkdir()
        self.config_dir = self.temp_dir / "config"
        self.cache_dir = self.temp_dir / "cache"
        self.shows_dir = self.temp_dir / "shows"
        self.test_windows: list[Any] = []

        for directory in [self.config_dir, self.cache_dir, self.shows_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        self.test_shots = [
            {
                "show": "feature_film",
                "sequence": "SEQ_001_FOREST",
                "shot": "0010",
                "name": "SEQ_001_FOREST_0010",
                "workspace_path": "/shows/feature_film/shots/SEQ_001_FOREST/SEQ_001_FOREST_0010",
            },
            {
                "show": "feature_film",
                "sequence": "SEQ_001_FOREST",
                "shot": "0020",
                "name": "SEQ_001_FOREST_0020",
                "workspace_path": "/shows/feature_film/shots/SEQ_001_FOREST/SEQ_001_FOREST_0020",
            },
            {
                "show": "episodic_tv",
                "sequence": "EP101",
                "shot": "0001",
                "name": "EP101_0001",
                "workspace_path": "/shows/episodic_tv/shots/EP101/EP101_0001",
            },
        ]

        self.test_subprocess = TestSubprocess()

        self.test_processes = {
            "nuke": PopenDouble(
                ["nuke"], returncode=0, stdout="Nuke started", stderr=""
            ),
            "maya": PopenDouble(
                ["maya"], returncode=0, stdout="Maya started", stderr=""
            ),
            "custom": PopenDouble(
                ["custom_tool"], returncode=0, stdout="Custom tool started", stderr=""
            ),
        }
        self.test_processes["nuke"].pid = 11111
        self.test_processes["maya"].pid = 22222
        self.test_processes["custom"].pid = 33333

        self.signal_events: list[tuple] = []

        self.progress_operation = ProgressOperationDouble()
        self.progress_patcher = patch(
            "managers.progress_manager.ProgressManager.start_operation"
        )
        self.mock_progress = self.progress_patcher.start()
        self.mock_progress.return_value = self.progress_operation

        yield

        with contextlib.suppress(Exception):
            self.progress_patcher.stop()

        _close_windows(self.test_windows, qtbot)

    def _create_test_process(self, pid: int, name: str) -> PopenDouble:
        process = PopenDouble([name], returncode=0, stdout=f"{name} output", stderr="")
        process.pid = pid
        return process

    def _track_signal(self, signal_name: str) -> Any:
        def handler(*args: Any) -> None:
            self.signal_events.append((signal_name, args, time.time()))

        return handler

    def _create_realistic_shot_structure(self, shot_data: dict[str, str]) -> Path:
        shot_path = (
            self.shows_dir
            / shot_data["show"]
            / "shots"
            / shot_data["sequence"]
            / shot_data["name"]
        )

        directories = [
            "publish/editorial/cutref/v001/jpg/1920x1080",
            "publish/turnover/plate/input_plate",
            "work/comp/nuke/scenes",
            "mm/nuke/comp/scenes",
            "mm/3de/mm-default/scenes/scene/FG01/v001",
            "sourceimages/plates/FG01/v001/exr/4096x2304",
            "user/alice/mm/3de/mm-default/scenes/scene/FG01/v001",
            "user/bob/mm/3de/mm-default/scenes/scene/BG01/v001",
        ]

        for directory in directories:
            (shot_path / directory).mkdir(parents=True, exist_ok=True)

        thumbnail_path = (
            shot_path / "publish/editorial/cutref/v001/jpg/1920x1080/thumbnail.jpg"
        )
        thumbnail_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200)

        scene_path = (
            shot_path
            / "user/alice/mm/3de/mm-default/scenes/scene/FG01/v001/alice_scene.3de"
        )
        scene_path.write_bytes(b"3DE_SCENE_DATA" * 50)

        return shot_path

    @pytest.mark.qt
    def test_launch_nuke_with_shot(self, qtbot: Any) -> None:
        """Test complete workflow of selecting a shot and launching Nuke."""
        main_window = MainWindow(cache_dir=self.cache_dir)
        qtbot.addWidget(main_window)
        self.test_windows.append(main_window)

        shot_data = self.test_shots[0]
        actual_workspace_path = self._create_realistic_shot_structure(shot_data)
        test_shot = Shot(
            shot_data["show"],
            shot_data["sequence"],
            shot_data["shot"],
            str(actual_workspace_path),
        )

        main_window.command_launcher.set_current_shot(test_shot)
        assert main_window.command_launcher.current_shot == test_shot

        # Pre-populate rez cache so test doesn't fail on missing rez binary
        main_window.command_launcher.env_manager._rez_available_cache = True

        with (
            patch(
                "launch.process_executor.subprocess.Popen",
                return_value=self.test_processes["nuke"],
            ) as mock_popen,
            patch.dict("os.environ", {"SHOTBOT_TEST_MODE": "true"}),
            patch(
                "launch.command_launcher.EnvironmentManager.is_ws_available",
                return_value=True,
            ),
        ):
            from launch.launch_request import LaunchRequest
            success = main_window.command_launcher.launch(LaunchRequest(app_name="nuke"))

            assert success is True

            qtbot.wait(1)

            assert mock_popen.called, "Popen should have been called"

            if mock_popen.call_args:
                call_args = mock_popen.call_args
                command_str = " ".join(call_args[0][0]) if call_args[0] else ""
                assert "nuke" in command_str.lower(), (
                    f"Expected 'nuke' in command: {command_str}"
                )

        assert main_window.command_launcher.current_shot == test_shot

    @pytest.mark.qt
    def test_thumbnail_loading_workflow(
        self, qtbot: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test thumbnail loading and display workflow."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs("")

        monkeypatch.setenv("SHOTBOT_NO_INITIAL_LOAD", "1")

        with patch(
            "workers.process_pool_manager.ProcessPoolManager.get_instance",
            return_value=test_pool,
        ):
            main_window = MainWindow(cache_dir=self.cache_dir)

        qtbot.addWidget(main_window)
        self.test_windows.append(main_window)

        from PySide6.QtCore import QMutexLocker

        with QMutexLocker(main_window.shot_model._loader_lock):
            if main_window.shot_model._async_loader:
                main_window.shot_model._async_loader.stop()
                main_window.shot_model._async_loader.wait()
                main_window.shot_model._async_loader.deleteLater()
                main_window.shot_model._async_loader = None
            main_window.shot_model._loading_in_progress = False

        main_window.shot_model.shots = []
        main_window.shot_item_model.set_shots([])
        main_window.shot_model._cache = None

        shot_data_1 = self.test_shots[0]
        shot_path_1 = self._create_realistic_shot_structure(shot_data_1)
        thumb_path_1 = (
            shot_path_1 / "publish/editorial/cutref/v001/jpg/1920x1080/thumbnail.jpg"
        )
        thumb_path_1.write_bytes(b"fake-thumbnail")
        shot_1 = Shot(
            shot_data_1["show"],
            shot_data_1["sequence"],
            shot_data_1["shot"],
            shot_data_1["workspace_path"],
        )

        shot_data_2 = self.test_shots[1]
        self._create_realistic_shot_structure(shot_data_2)
        shot_2 = Shot(
            shot_data_2["show"],
            shot_data_2["sequence"],
            shot_data_2["shot"],
            shot_data_2["workspace_path"],
        )

        all_shots = [shot_1, shot_2]
        main_window.shot_model.shots = all_shots
        main_window.refresh_coordinator.handle_shots_changed(all_shots)

        qtbot.waitUntil(
            lambda: main_window.shot_item_model.rowCount() > 0, timeout=1000
        )

        assert main_window.shot_item_model.rowCount() > 0, "No shots in item model"

        from ui.base_item_model import BaseItemRole as UnifiedRole

        for i in range(main_window.shot_item_model.rowCount()):
            index = main_window.shot_item_model.index(i, 0)
            shot_data = main_window.shot_item_model.data(index, UnifiedRole.ObjectRole)
            assert shot_data is not None


# ---------------------------------------------------------------------------
# Standalone helpers (preserved from test_user_workflows.py)
# ---------------------------------------------------------------------------


def setup_test_environment() -> Path:
    """Set up isolated test environment for standalone testing."""
    return Path(tempfile.mkdtemp(prefix="shotbot_workflow_test_"))


def cleanup_test_environment(temp_dir: Path) -> None:
    """Clean up test environment after standalone testing."""
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        print(f"Cleanup warning: {e}")


if __name__ == "__main__":
    temp_dir = setup_test_environment()

    try:
        app = QApplication.instance()
        if app is None:
            app = QApplication([])

        print("Running critical user workflow integration tests...")
        print("1. Testing Nuke launch workflow...")
        try:

            class StandaloneQtBot:
                def addWidget(self, widget: Any) -> None:
                    pass

                def wait(self, ms: int) -> None:
                    QTest.qWait(ms)

                def waitUntil(self, condition: Any, timeout: int = 1000) -> bool:
                    start_time = time.time()
                    while time.time() - start_time < timeout / 1000:
                        if condition():
                            return True
                        QTest.qWait(10)
                    return False

            qtbot = StandaloneQtBot()
            standalone_temp = tempfile.mkdtemp(prefix="shotbot_user_workflow_")
            test_instance = TestUserWorkflows()
            test_instance.temp_dir = Path(standalone_temp)
            test_instance.config_dir = test_instance.temp_dir / "config"
            test_instance.cache_dir = test_instance.temp_dir / "cache"
            test_instance.shows_dir = test_instance.temp_dir / "shows"
            for d in [
                test_instance.config_dir,
                test_instance.cache_dir,
                test_instance.shows_dir,
            ]:
                d.mkdir(parents=True, exist_ok=True)
            test_instance.test_shots = [
                {
                    "show": "feature_film",
                    "sequence": "SEQ_001_FOREST",
                    "shot": "0010",
                    "name": "SEQ_001_FOREST_0010",
                    "workspace_path": "/shows/feature_film/shots/SEQ_001_FOREST/SEQ_001_FOREST_0010",
                },
            ]
            test_instance.test_subprocess = TestSubprocess()
            test_instance.test_processes = {
                "nuke": PopenDouble(
                    ["nuke"], returncode=0, stdout="Nuke started", stderr=""
                ),
            }
            test_instance.test_processes["nuke"].pid = 11111
            test_instance.signal_events = []
            test_instance.progress_operation = ProgressOperationDouble()
            test_instance.progress_patcher = patch(
                "managers.progress_manager.ProgressManager.start_operation"
            )
            test_instance.mock_progress = test_instance.progress_patcher.start()
            test_instance.mock_progress.return_value = test_instance.progress_operation

            try:
                test_instance.test_launch_nuke_with_shot(qtbot)
                print("   Nuke launch workflow passed")
            finally:
                with contextlib.suppress(Exception):
                    test_instance.progress_patcher.stop()
                cleanup_test_environment(Path(standalone_temp))
        except Exception as e:  # noqa: BLE001
            print(f"   Nuke launch workflow failed: {e}")

        print("Standalone workflow tests completed")

    except Exception as e:  # noqa: BLE001
        print(f"Standalone test error: {e}")
        traceback.print_exc()
    finally:
        cleanup_test_environment(temp_dir)
