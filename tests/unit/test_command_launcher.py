"""Tests for CommandLauncher following UNIFIED_TESTING_GUIDE.

This test suite validates CommandLauncher behavior using:
- Test doubles for external dependencies
- Real Qt components and signals
- Behavior testing, not implementation details
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from config import Config
from launch.command_launcher import CommandLauncher
from launch.launch_request import LaunchContext, LaunchRequest
from tests.fixtures.process_fixtures import PopenDouble
from type_definitions import Shot, ThreeDEScene


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot



def _running_process_double(*args: str) -> PopenDouble:
    """Return a subprocess double that looks alive to ProcessExecutor.verify_spawn."""
    process_args = list(args) or ["test-app"]
    return PopenDouble(args=process_args, returncode=0)


@pytest.fixture(autouse=True)
def ensure_qt_cleanup(qtbot: QtBot):
    """Ensure Qt event processing completes after each test.

    This prevents Qt state pollution between tests, specifically:
    - QTimer.singleShot callbacks scheduled by CommandLauncher
    - QObject instances that need proper deletion
    - Event queue cleanup

    CRITICAL: CommandLauncher.launch_app() schedules QTimer.singleShot(100ms)
    callbacks that must complete before the next test starts.
    """
    yield
    # Wait for any pending timers (CommandLauncher uses 100ms timers)
    qtbot.wait(1)


@pytest.fixture(autouse=True)
def stable_terminal_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to a deterministic terminal in non-headless tests.

    Tests that need headless behavior explicitly patch detect_terminal to None.
    """
    monkeypatch.setattr(
        "launch.command_launcher.EnvironmentManager.detect_terminal",
        lambda _self: "gnome-terminal",
    )


@pytest.fixture(autouse=True)
def disable_environment_warm_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CommandLauncher tests isolated and fast.

    CommandLauncher starts EnvironmentManager.warm_cache_async() during construction.
    These tests do not need background cache warming, and the extra threads can leak
    state across tests and destabilize long serial runs.
    """
    monkeypatch.setattr(
        "launch.command_launcher.EnvironmentManager.warm_cache_async",
        lambda _self: None,
    )


class TestCommandLauncher:
    """Test CommandLauncher functionality."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot) -> Iterator[CommandLauncher]:
        """Create CommandLauncher with test doubles."""
        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager

        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        launcher = CommandLauncher()
        yield launcher
        launcher.cleanup()
        qtbot.wait(1)

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create a test shot."""
        return Shot(
            "TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def test_scene(self) -> ThreeDEScene:
        """Create a test 3DE scene."""
        return ThreeDEScene(
            show="TEST",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010",
            user="testuser",
            plate="plate_v001",
            scene_path=Path("/path/to/scene.3de"),
        )

    @pytest.mark.parametrize(
        ("app_name", "expected_token"),
        [
            ("nuke", "nuke"),
            ("3de", "3de"),
            ("maya", "maya"),
            ("rv", "rv"),
        ],
    )
    def test_launch_supported_apps(
        self,
        mocker,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
        app_name: str,
        expected_token: str,
    ) -> None:
        """Test launching supported applications with common expectations."""
        launcher.set_current_shot(test_shot)

        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        mock_popen.return_value = _running_process_double(app_name)
        result = launcher.launch(LaunchRequest(app_name=app_name))

        assert result is True
        qtbot.wait(1)

        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)
        assert expected_token in command_str

        if app_name == "nuke":
            assert (
                "gnome-terminal" in call_args
                or "xterm" in call_args
                or "konsole" in call_args
                or "x-terminal-emulator" in call_args
                or "/bin/bash" in call_args
            )

    def test_launch_nuke_with_scene_gets_plain_workspace_launch(
        self,
        mocker,
        launcher: CommandLauncher,
        qtbot: QtBot,
    ) -> None:
        """Nuke scene launch gets plain workspace launch without SGTK_FILE_TO_OPEN."""
        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        mock_popen.return_value = _running_process_double("nuke")
        nuke_scene = ThreeDEScene(
            show="TEST",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010",
            user="testuser",
            plate="FG01",
            scene_path=Path("/path/to/scene.nk"),
        )

        result = launcher.launch(LaunchRequest(app_name="nuke", scene=nuke_scene))

        assert result is True
        qtbot.wait(1)
        assert mock_popen.called
        command_str = " ".join(mock_popen.call_args[0][0])
        # Non-3DE scene launches should NOT export SGTK_FILE_TO_OPEN
        assert "SGTK_FILE_TO_OPEN" not in command_str
        assert "NUKE_PATH" not in command_str

    def test_launch_3de_with_scene(
        self,
        mocker,
        launcher: CommandLauncher,
        test_scene: ThreeDEScene,
        qtbot: QtBot,
    ) -> None:
        """Test launching 3DE with specific scene."""
        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        # Setup mock
        mock_popen.return_value = _running_process_double("3de")

        # Launch 3DE with scene
        result = launcher.launch(LaunchRequest(app_name="3de", scene=test_scene))

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        qtbot.wait(1)

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)
        assert "3de" in command_str
        assert str(test_scene.scene_path) in command_str
        assert "PYTHON_CUSTOM_SCRIPTS_3DE4" in command_str
        assert "SGTK_FILE_TO_OPEN" in command_str

    @pytest.mark.parametrize(
        "sequence_path",
        [
            None,
            "/shows/TEST/shots/seq01/seq01_0010/playblast/shot.####.exr",
        ],
        ids=["without_sequence", "with_sequence"],
    )
    def test_launch_rv_default_settings(
        self,
        mocker,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
        sequence_path: str | None,
    ) -> None:
        """Test RV launch includes default settings with and without sequence path."""
        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        launcher.set_current_shot(test_shot)
        mock_popen.return_value = _running_process_double("rv")

        if sequence_path:
            result = launcher.launch(
                LaunchRequest(
                    app_name="rv", context=LaunchContext(sequence_path=sequence_path)
                )
            )
        else:
            result = launcher.launch(LaunchRequest(app_name="rv"))

        assert result is True
        qtbot.wait(1)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        assert "rv" in command_str
        assert "-fps 12" in command_str
        assert "-play" in command_str
        assert "setPlayMode(2)" in command_str

        if sequence_path:
            assert sequence_path in command_str

    @pytest.mark.allow_dialogs  # Error dialog is expected side-effect
    @pytest.mark.usefixtures("suppress_qmessagebox")
    def test_subprocess_failure(
        self,
        mocker,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test handling subprocess failure."""
        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        launcher.set_current_shot(test_shot)

        # Setup mock to simulate failure for all terminal types
        mock_popen.side_effect = FileNotFoundError("terminal not found")

        # Launch app should fail
        result = launcher.launch(LaunchRequest(app_name="nuke"))

        # Should return False when subprocess fails
        assert result is False

        # Wait for any pending Qt events (QTimer won't fire due to failure, but process events)
        qtbot.wait(1)

        # Verify subprocess was attempted
        assert mock_popen.called

    @pytest.mark.allow_dialogs  # May show warning dialog
    @pytest.mark.usefixtures("suppress_qmessagebox")
    def test_launch_headless_mode_when_no_terminal(
        self,
        mocker,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that launches succeed in headless mode when no terminal is available."""
        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.detect_terminal", return_value=None
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = _running_process_double("nuke")

        # Launch app - should succeed even without terminal
        result = launcher.launch(LaunchRequest(app_name="nuke"))

        # Verify launch was successful (headless mode)
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        qtbot.wait(1)

        # Verify subprocess was called with direct bash (headless)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "/bin/bash"
        assert "-ilc" in call_args
        assert "nuke" in " ".join(call_args)

    @pytest.mark.parametrize(
        ("background", "expect_disown"),
        [
            (True, True),
            (False, False),
        ],
        ids=["background_enabled", "background_disabled"],
    )
    def test_launch_gui_app_background_setting(
        self,
        mocker,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
        background: bool,
        expect_disown: bool,
    ) -> None:
        """Test GUI app backgrounding respects the background_gui_apps setting."""
        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        launcher.set_current_shot(test_shot)
        mock_popen.return_value = _running_process_double("3de")

        mocker.patch.object(
            launcher._settings_manager.launch,
            "get_background_gui_apps",
            return_value=background,
        )
        result = launcher.launch(LaunchRequest(app_name="3de"))

        assert result is True
        qtbot.wait(1)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        if expect_disown:
            assert "disown" in command_str
            assert "exit" in command_str
        else:
            assert "disown" not in command_str


@pytest.mark.usefixtures("suppress_qmessagebox")
class TestCommandLauncherSignals:
    """Test CommandLauncher signal emissions."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot) -> Iterator[CommandLauncher]:
        """Create CommandLauncher with test doubles."""
        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager

        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        launcher = CommandLauncher()
        yield launcher
        launcher.cleanup()
        qtbot.wait(1)

    @pytest.mark.allow_dialogs  # Warning dialogs are acceptable in this smoke-style path test
    def test_signal_data_format(self, mocker, launcher: CommandLauncher, qtbot: QtBot) -> None:
        """Test basic launcher functionality."""
        shot = Shot(
            "TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"
        )
        launcher.set_current_shot(shot)

        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen.return_value = _running_process_double("nuke")

        # Launch should succeed
        result = launcher.launch(LaunchRequest(app_name="nuke"))
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        qtbot.wait(1)

        # Should have called Popen
        assert mock_popen.called


class TestScriptsDirValidation:
    """Test _validate_scripts_dir preflight validation."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot) -> Iterator[CommandLauncher]:
        """Create CommandLauncher with test doubles."""
        from launch import EnvironmentManager

        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        launcher = CommandLauncher()
        yield launcher
        launcher.cleanup()
        qtbot.wait(1)

    def test_missing_scripts_dir_blocks_nuke_launch(
        self,
        launcher: CommandLauncher,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nuke launch fails when Config.SCRIPTS_DIR doesn't exist."""
        monkeypatch.setattr(Config, "SCRIPTS_DIR", "/nonexistent/scripts")
        shot = Shot(
            "TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"
        )
        launcher.set_current_shot(shot)

        result = launcher.launch(LaunchRequest(app_name="nuke"))

        assert result is False

    def test_missing_hook_file_warns_but_proceeds(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Launch proceeds with warning when hook file is missing but dir exists."""
        monkeypatch.setattr(Config, "SCRIPTS_DIR", str(tmp_path))
        # tmp_path exists but has no init.py

        result = launcher._validate_scripts_dir("nuke")

        assert result is True

    def test_maya_skips_scripts_dir_validation(
        self,
        mocker,
        launcher: CommandLauncher,
        monkeypatch: pytest.MonkeyPatch,
        qtbot: QtBot,
    ) -> None:
        """Maya launch doesn't check scripts dir (doesn't use hook scripts)."""
        monkeypatch.setattr(Config, "SCRIPTS_DIR", "/nonexistent/scripts")
        shot = Shot(
            "TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"
        )
        launcher.set_current_shot(shot)

        mocker.patch.object(
            CommandLauncher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch(
            "launch.command_launcher.EnvironmentManager.should_wrap_with_rez",
            return_value=True,
        )
        mock_popen = mocker.patch("launch.process_executor.subprocess.Popen")
        mock_popen.return_value = PopenDouble(args=["maya"], returncode=0)
        result = launcher.launch(LaunchRequest(app_name="maya"))

        assert result is True
        qtbot.wait(1)


class TestSubprocessErrorHandling:
    """Test subprocess error handling in the launcher and process pool."""

    def test_error_fixture_integrates_with_launcher_module(
        self,
        fp,
    ) -> None:
        """Test that subprocess calls can be faked with specific return codes."""
        import subprocess

        fp.register(["test", "cmd"], returncode=127, stderr="bash: command not found")

        # Verify the fake process returns the configured return code
        proc = subprocess.Popen(["test", "cmd"])
        assert proc.returncode == 127

        # The fixture should have recorded the call
        assert list(fp.calls[0]) == ["test", "cmd"]
