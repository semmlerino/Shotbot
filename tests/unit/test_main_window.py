"""Tests for MainWindow - critical UI integration.

Following UNIFIED_TESTING_GUIDE principles:
- Use real components where possible
- Use test doubles at system boundaries (subprocess)
- Test behavior not implementation
- Use qtbot for proper Qt testing
"""

# Standard library imports
from datetime import UTC
from pathlib import Path
from typing import Protocol
from unittest.mock import MagicMock

# Third-party imports
import pytest
from pytestqt.qtbot import QtBot

# Local application imports
# Lazy imports to avoid Qt initialization at module level
# from cache_manager import CacheManager
# from main_window import MainWindow
# from shot_model import Shot
from config import Config


class TestProcessPoolType(Protocol):
    """Protocol for process pool test doubles."""

    __test__ = False

    should_fail: bool
    call_count: int
    commands: list[str]

    def set_outputs(self, output: str) -> None: ...
    def set_errors(self, error: str) -> None: ...
    def execute_workspace_command(
        self, command: str, cache_ttl: int | None = None
    ) -> str: ...
    def reset(self) -> None: ...


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.permissive_process_pool,  # MainWindow tests check UI, not subprocess output
    pytest.mark.allow_dialogs,  # MainWindow init triggers error dialogs in test env
    pytest.mark.usefixtures("suppress_qmessagebox"),
]


# Module-level fixture to handle lazy imports
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow, Shot, ThreeDEScene, SceneFile, FileType  # noqa: PLW0603
    # Local application imports
    from dcc.scene_file import (
        FileType,
        SceneFile,
    )
    from main_window import (
        MainWindow,
    )
    from shots.shot_model import (
        Shot,
    )
    from threede.scene_model import (
        ThreeDEScene,
    )


@pytest.fixture(autouse=True)
def stable_main_window_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable background startup work unrelated to these UI behavior tests."""
    from type_definitions import RefreshResult

    def _skip_async_init(_self: object) -> RefreshResult:
        return RefreshResult(success=True, has_changes=False)

    monkeypatch.setenv("SHOTBOT_NO_INITIAL_LOAD", "1")
    monkeypatch.setattr("shots.shot_model.ShotModel.initialize_async", _skip_async_init)
    monkeypatch.setattr(
        "launch.environment_manager.EnvironmentManager.warm_cache_async",
        lambda _self: None,
    )


class TestMainWindowInitialization:
    """Test MainWindow initialization and component setup."""

    def test_main_window_creates_all_components(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that MainWindow initializes all required components and uses provided cache manager."""
        # Use real cache directory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(exist_ok=True)

        # Create main window with real components
        main_window = MainWindow(cache_dir=cache_dir)
        qtbot.addWidget(main_window)

        # Verify cache coordinator is initialized (CacheManager is no longer stored as-is)
        assert main_window.cache_coordinator is not None

        # Verify all critical components exist
        assert main_window.shot_model is not None
        assert main_window.threede_scene_model is not None
        assert main_window.previous_shots_model is not None
        assert main_window.command_launcher is not None

        # Verify UI components
        assert main_window.tab_widget is not None
        assert main_window.shot_grid is not None
        assert main_window.threede_shot_grid is not None
        assert main_window.previous_shots_grid is not None
        assert main_window.right_panel is not None

    def test_main_window_creates_default_cache_manager(self, qtbot: QtBot) -> None:
        """Test MainWindow creates default cache manager if none provided."""
        main_window = MainWindow()
        qtbot.addWidget(main_window)

        # Verify default cache coordinator exists
        assert main_window.cache_coordinator is not None


class TestTabSwitching:
    """Test tab switching functionality."""

    def test_switch_between_tabs(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test switching between different tabs."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Reset to first tab (settings may have restored a different tab from persistent storage)
        main_window.tab_widget.setCurrentIndex(0)

        # Verify we're on the first tab (My Shots)
        assert main_window.tab_widget.currentIndex() == 0
        assert main_window.tab_widget.currentWidget() == main_window.shot_grid

        # Switch to second tab (Other 3DE Scenes)
        main_window.tab_widget.setCurrentIndex(1)
        assert main_window.tab_widget.currentIndex() == 1
        assert main_window.tab_widget.currentWidget() == main_window.threede_shot_grid

        # Switch to third tab
        main_window.tab_widget.setCurrentIndex(2)
        assert main_window.tab_widget.currentIndex() == 2
        assert main_window.tab_widget.currentWidget() == main_window.previous_shots_grid


class TestShotSelection:
    """Test shot selection and application launching."""

    def test_shot_selection_enables_app_buttons(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that selecting a shot enables application launcher buttons."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Initially DCC section launch buttons should be disabled
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert not section._launch_btn.isEnabled()

        # Create a test shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")

        # Simulate shot selection
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Now DCC section launch buttons should be enabled
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

        # Right panel should be updated with the shot
        assert main_window.right_panel is not None

    def test_shot_deselection_disables_app_buttons(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that deselecting a shot disables application launcher buttons."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Select a shot first
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify DCC section launch buttons are enabled
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

        # Deselect shot
        main_window.shot_selection_controller.on_shot_selected(None)

        # DCC section launch buttons should be disabled again
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert not section._launch_btn.isEnabled()


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestShotRefresh:
    """Test shot refresh functionality."""

    def test_refresh_shots_updates_display(self, qtbot: QtBot, tmp_path: Path, mocker) -> None:
        """Test that MainWindow refresh delegates to the refresh orchestrator."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        mock_refresh_tab = mocker.patch.object(
            main_window.refresh_coordinator, "refresh_tab"
        )
        main_window._refresh_shots()

        mock_refresh_tab.assert_called_once_with(0)

    def test_refresh_shot_display_respects_hide_filter(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Hidden shots must not appear in the proxy after refresh_shot_display()."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        shot_visible = Shot("show1", "seq01", "shot0010", "/shows/show1/seq01/shot0010")
        shot_hidden = Shot("show1", "seq01", "shot0020", "/shows/show1/seq01/shot0020")

        # Populate model directly (bypasses async loading)
        main_window.shot_model.shots = [shot_visible, shot_hidden]
        main_window.hide_manager.hide_shot(shot_hidden)

        # Simulate a data-refresh event (e.g. shots_loaded / F5)
        main_window.refresh_coordinator.refresh_shot_display()

        # Item model holds all shots; proxy applies hide filter
        all_shots = main_window.shot_item_model.shots
        assert shot_visible in all_shots
        assert shot_hidden in all_shots  # Item model has all shots

        # Proxy filters out hidden shots
        proxy = main_window.shot_proxy
        visible_rows = proxy.rowCount()
        visible_shots = [
            proxy.sourceModel().get_item_at_index(proxy.mapToSource(proxy.index(r, 0)))
            for r in range(visible_rows)
        ]
        assert shot_visible in visible_shots
        assert shot_hidden not in visible_shots


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestApplicationLaunching:
    """Test application launching functionality."""

    def test_launch_app_without_selection_shows_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test that launching an app without a shot shows an error."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Mock the workspace directory creation to avoid permission errors
        def mock_mkdir(self, *args, **kwargs) -> None:
            pass  # Don't actually create directories

        monkeypatch.setattr("pathlib.Path.mkdir", mock_mkdir)

        # Try to launch app without selecting a shot (should not raise)
        main_window.launch_app("nuke")

        # No shot selected; underlying launcher returns False but MainWindow.launch_app -> None
        assert main_window.command_launcher.current_shot is None


class TestStatusBar:
    """Test status bar functionality."""

    def test_background_load_started_shows_message(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that background load started signal shows status message."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Emit the signal (inlined handler is a lambda in _connect_signals)
        main_window.shot_model.background_load_started.emit()

        # Verify status bar shows fetching message
        assert "Fetching fresh data" in main_window.status_bar.currentMessage()

    def test_show_filter_updates_status_bar(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that applying show filter updates status bar with count."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Add some test shots
        test_shots = [
            Shot(
                show="TestShow",
                sequence="sq010",
                shot="sh0010",
                workspace_path="/test/path",
            ),
            Shot(
                show="OtherShow",
                sequence="sq020",
                shot="sh0020",
                workspace_path="/other/path",
            ),
        ]
        main_window.shot_model.shots = test_shots
        main_window.shot_item_model.set_shots(test_shots)

        # Apply filter via the filter coordinator (new proxy-based interface)
        main_window.filter_coordinator.apply_show_filter(
            main_window.shot_proxy, "My Shots", "TestShow"
        )

        # Verify status bar shows filter result
        message = main_window.status_bar.currentMessage()
        assert "TestShow" in message


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestMainWindowIntegration:
    """Integration tests for MainWindow end-to-end workflows."""

    def test_complete_shot_workflow(self, qtbot: QtBot, tmp_path: Path, mocker) -> None:
        """Test complete workflow: set a shot, select it, and launch an app."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        shows_root = Config.SHOWS_ROOT
        shot = Shot(
            "test_show",
            "seq01",
            "0010",
            f"{shows_root}/test/shots/seq01/seq01_0010",
        )
        main_window.shot_model.shots = [shot]
        main_window.shot_item_model.set_shots([shot])

        # Select the shot
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify DCC section launch buttons enabled (test behavior)
        assert "nuke" in main_window.right_panel._dcc_accordion._sections
        assert main_window.right_panel._dcc_accordion._sections[
            "nuke"
        ]._launch_btn.isEnabled()

        mock_launch = mocker.patch.object(
            main_window.command_launcher, "launch", return_value=True
        )
        main_window.launch_app("nuke")

        mock_launch.assert_called_once()
        request = mock_launch.call_args.args[0]
        assert request.app_name == "nuke"


class TestCrashRecovery:
    """Test 3DE crash recovery functionality."""

    @pytest.mark.parametrize("context_type", ["shot", "scene"])
    def test_crash_recovery_with_selection(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, context_type: str, mocker
    ) -> None:
        """Test crash recovery uses workspace_path from the active selection.

        'shot' — shot selected from My Shots tab; scene is None.
        'scene' — 3DE scene selected from Other 3DE Scenes tab; shot is None.
        """
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        shows_root = Config.SHOWS_ROOT

        if context_type == "shot":
            shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
            main_window.shot_selection_controller.on_shot_selected(shot)
            assert main_window.command_launcher.current_shot == shot
            assert main_window.threede_shot_grid.selected_scene is None
            expected_workspace = shot.workspace_path
        else:
            scene = ThreeDEScene(
                show="test_show",
                sequence="seq01",
                shot="0010",
                workspace_path=f"{shows_root}/test/seq01/0010",
                user="test_user",
                plate="FG01",
                scene_path=Path(f"{shows_root}/test/seq01/0010/test.3de"),
            )
            main_window.threede_shot_grid._selected_scene = scene
            assert main_window.threede_shot_grid.selected_scene == scene
            assert main_window.command_launcher.current_shot is None
            expected_workspace = scene.workspace_path

        mock_crash_info = MagicMock()
        mock_crash_info.crash_path.name = "test_scene.3de.crash"

        mock_manager_class = mocker.patch("threede.recovery.ThreeDERecoveryManager")
        mock_manager = mock_manager_class.return_value
        mock_manager.find_crash_files.return_value = [mock_crash_info]

        mock_dialog_class = mocker.patch(
            "threede.recovery_dialog.ThreeDERecoveryDialog"
        )
        mock_dialog = mock_dialog_class.return_value
        mock_dialog.exec.return_value = 0

        main_window.shot_selection_controller.on_recover_crashes_requested()

        mock_manager.find_crash_files.assert_called_once_with(
            expected_workspace, recursive=True
        )
        mock_dialog_class.assert_called_once()

    def test_crash_recovery_no_shot_selected(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, expect_dialog
    ) -> None:
        """Test crash recovery shows warning when no shot is selected."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Don't select any shot or scene
        assert main_window.command_launcher.current_shot is None
        assert main_window.threede_shot_grid.selected_scene is None

        # Trigger crash recovery
        main_window.shot_selection_controller.on_recover_crashes_requested()

        # Verify a warning dialog was shown (QMessageBox.warning intercepted by fixture)
        expect_dialog.assert_shown("warning", "No Shot Selected")

    def test_crash_recovery_no_crash_files_found(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, mocker
    ) -> None:
        """Test crash recovery shows info message when no crash files found."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Create and select a shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Mock recovery manager to return no crash files
        mock_manager_class = mocker.patch("threede.recovery.ThreeDERecoveryManager")
        mock_manager = mock_manager_class.return_value
        mock_manager.find_crash_files.return_value = []  # No crash files

        # Trigger crash recovery
        main_window.shot_selection_controller.on_recover_crashes_requested()

        # Verify info message was shown in the status bar
        message = main_window.status_bar.currentMessage()
        assert "No 3DE crash files found" in message
        assert shot.full_name in message

    def test_crash_recovery_with_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, expect_dialog, mocker
    ) -> None:
        """Test crash recovery handles errors gracefully."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Create and select a shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Mock recovery manager to raise an error
        mock_manager_class = mocker.patch("threede.recovery.ThreeDERecoveryManager")
        mock_manager = mock_manager_class.return_value
        mock_manager.find_crash_files.side_effect = Exception("Test error")

        # Trigger crash recovery
        main_window.shot_selection_controller.on_recover_crashes_requested()

        # Verify an error notification was shown
        expect_dialog.assert_shown("critical", "Scan Error")


class TestRightPanelFileLaunch:
    """Test file launch from right panel DCC section.

    When a user selects a file in the DCC panel (e.g., Maya file from
    'Other 3DE scenes' tab) and clicks Launch, the selected file should
    be opened in the application.
    """

    def test_launch_with_selected_file_from_shot_context(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, mocker
    ) -> None:
        """Test launching a selected file when shot is selected (My Shots tab)."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Select a shot (provides workspace context)
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Create a SceneFile to simulate file selection in DCC panel
        from datetime import datetime

        maya_file = SceneFile(
            path=Path(f"{shows_root}/test/seq01/0010/scenes/test_scene.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(tz=UTC),
            user="other_user",
        )

        # Mock launch to verify it's called correctly
        mock_launch = mocker.patch.object(
            main_window.command_launcher, "launch", return_value=True
        )
        # Simulate right panel launch with selected file
        options = {"selected_file": maya_file}
        main_window._on_right_panel_launch("maya", options)

        # Verify launch was called with correct LaunchRequest
        mock_launch.assert_called_once()
        request = mock_launch.call_args.args[0]
        assert request.app_name == "maya"
        assert request.file_path == maya_file.path
        assert request.workspace_path == shot.workspace_path

    def test_launch_with_selected_file_from_scene_context(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, mocker
    ) -> None:
        """Test launching a selected file when 3DE scene is selected."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Select a 3DE scene (provides workspace context via selected_scene)
        shows_root = Config.SHOWS_ROOT
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{shows_root}/test/seq01/0010",
            user="scene_user",
            plate="FG01",
            scene_path=Path(f"{shows_root}/test/seq01/0010/scenes/track.3de"),
        )
        # Set scene directly (simulates user selection in Other 3DE Scenes tab)
        main_window.threede_shot_grid._selected_scene = scene
        # Ensure no shot is selected (Other 3DE Scenes tab behavior)
        main_window.command_launcher.set_current_shot(None)

        # Create a Maya file to launch
        from datetime import datetime

        maya_file = SceneFile(
            path=Path(f"{shows_root}/test/seq01/0010/scenes/finalize.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(tz=UTC),
            user="another_user",
        )

        # Mock launch
        mock_launch = mocker.patch.object(
            main_window.command_launcher, "launch", return_value=True
        )
        options = {"selected_file": maya_file}
        main_window._on_right_panel_launch("maya", options)

        # Verify launch was called with scene's workspace
        mock_launch.assert_called_once()
        request = mock_launch.call_args.args[0]
        assert request.app_name == "maya"
        assert request.file_path == maya_file.path
        assert request.workspace_path == scene.workspace_path

    def test_launch_with_selected_file_no_context_shows_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, expect_dialog
    ) -> None:
        """Test that launching without context shows an error."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Ensure no shot or scene is selected
        main_window.command_launcher.set_current_shot(None)
        main_window.threede_shot_grid._selected_scene = None

        # Create a file to launch
        from datetime import datetime

        nuke_file = SceneFile(
            path=Path("/shows/test/scenes/comp.nk"),
            file_type=FileType.NUKE,
            modified_time=datetime.now(tz=UTC),
            user="user",
        )

        options = {"selected_file": nuke_file}
        main_window._on_right_panel_launch("nuke", options)

        # Verify a critical error dialog was shown with correct message
        expect_dialog.assert_shown("critical", "Cannot Launch File")
        expect_dialog.assert_shown("critical", "No shot or scene context available")

    def test_launch_without_selected_file_uses_launch_app(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, mocker
    ) -> None:
        """Test that launch without selected_file uses standard launch_app."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        # Select a shot for context
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Mock launch
        mock_launch = mocker.patch.object(
            main_window.command_launcher, "launch", return_value=True
        )
        # Launch without selected_file
        options = {"open_latest_maya": True}
        main_window._on_right_panel_launch("maya", options)

        # Verify launch was called with no file_path (standard launch)
        mock_launch.assert_called_once()
        request = mock_launch.call_args.args[0]
        assert request.app_name == "maya"
        assert request.file_path is None
        assert request.scene is None


class TestGetCurrentWorkspacePath:
    """Test the _get_current_workspace_path helper method."""

    @pytest.mark.parametrize(
        ("context", "expected_source"),
        [
            ("shot", "shot"),
            ("scene", "scene"),
            ("none", None),
        ],
    )
    def test_workspace_path_resolution(
        self, qtbot: QtBot, tmp_path: Path, context: str, expected_source: str | None
    ) -> None:
        """Test workspace path resolution for each selection context.

        'shot' — shot selected; result comes from shot.workspace_path.
        'scene' — 3DE scene selected, no shot; result comes from scene.workspace_path.
        'none' — nothing selected; result is None.
        """
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        shows_root = Config.SHOWS_ROOT

        if context == "shot":
            shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
            main_window.shot_selection_controller.on_shot_selected(shot)
            expected = shot.workspace_path
        elif context == "scene":
            scene = ThreeDEScene(
                show="test_show",
                sequence="seq01",
                shot="0010",
                workspace_path=f"{shows_root}/test/seq01/0010",
                user="user",
                plate="FG01",
                scene_path=Path(f"{shows_root}/test/seq01/0010/track.3de"),
            )
            main_window.threede_shot_grid._selected_scene = scene
            main_window.command_launcher.set_current_shot(None)
            expected = scene.workspace_path
        else:
            main_window.command_launcher.set_current_shot(None)
            main_window.threede_shot_grid._selected_scene = None
            expected = None

        result = main_window._get_current_workspace_path()
        assert result == expected

    def test_prefers_shot_over_scene(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that shot workspace is preferred when both are available."""
        main_window = MainWindow(cache_dir=tmp_path / "cache")
        qtbot.addWidget(main_window)

        shows_root = Config.SHOWS_ROOT

        # Set both shot and scene with different workspaces
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/shot/workspace")
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{shows_root}/scene/workspace",
            user="user",
            plate="FG01",
            scene_path=Path(f"{shows_root}/scene/workspace/track.3de"),
        )
        main_window.shot_selection_controller.on_shot_selected(shot)
        main_window.threede_shot_grid._selected_scene = scene

        # Verify shot workspace is preferred
        result = main_window._get_current_workspace_path()
        assert result == shot.workspace_path
        assert result != scene.workspace_path
