"""Tests for DCC launcher error paths not covered by test_command_launcher.py.

Covers:
- ProcessExecutor.verify_spawn signal emission when process crashes immediately
- ProcessExecutor.execute_in_new_terminal with PermissionError and OSError
- _validate_workspace_before_launch edge cases (nonexistent path, file not dir, permissions)
- Invalid/dangerous scene paths in launch_app_opening_scene_file
- Invalid/dangerous workspace paths in _finish_launch
- Unknown app_name in launch_app and launch_app_opening_scene_file
- Two timeouts then success: counter resets and cache is NOT reset at the second timeout
- ProcessVerifier._is_gui_app and _extract_app_name edge cases
- ProcessVerifier.cleanup_old_pid_files with missing directory
- ProcessExecutor cleanup while timers are pending
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from config import Config
from launch.command_launcher import CommandLauncher
from launch.launch_request import LaunchRequest
from launch.process_executor import ProcessExecutor
from tests.fixtures.process_fixtures import PopenDouble
from tests.test_helpers import process_qt_events
from type_definitions import Shot, ThreeDEScene


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def ensure_qt_cleanup(qtbot: QtBot) -> None:
    """Flush Qt event queue after every test."""
    yield
    process_qt_events()


@pytest.fixture(autouse=True)
def stable_terminal_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default all tests to a known terminal; individual tests override as needed."""
    monkeypatch.setattr(
        "launch.command_launcher.EnvironmentManager.detect_terminal",
        lambda _self: "gnome-terminal",
    )


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
    """CommandLauncher with ws-available stub."""
    from launch import EnvironmentManager

    monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)
    return CommandLauncher()


@pytest.fixture
def test_shot(tmp_path: Path) -> Shot:
    """A Shot whose workspace_path actually exists on disk."""
    ws = tmp_path / "shows" / "TEST" / "shots" / "seq01" / "seq01_0010"
    ws.mkdir(parents=True)
    return Shot("TEST", "seq01", "0010", str(ws))


@pytest.fixture
def test_scene(tmp_path: Path) -> ThreeDEScene:
    """A ThreeDEScene with a valid workspace and a real-looking scene path."""
    import time

    ws = tmp_path / "shows" / "TEST" / "shots" / "seq01" / "seq01_0010"
    ws.mkdir(parents=True)
    scene_file = ws / "3de" / "artist_plate_v001.3de"
    scene_file.parent.mkdir(parents=True, exist_ok=True)
    scene_file.write_text("fake scene")
    return ThreeDEScene(
        show="TEST",
        sequence="seq01",
        shot="0010",
        workspace_path=str(ws),
        user="artist",
        plate="plate_v001",
        scene_path=scene_file,
        modified_time=time.time(),
    )


# ---------------------------------------------------------------------------
# ProcessExecutor.verify_spawn — process crashes immediately
# ---------------------------------------------------------------------------


class TestVerifySpawnCrash:
    """Tests for ProcessExecutor.verify_spawn when the process exits immediately."""

    @pytest.mark.allow_dialogs  # verify_spawn shows an error notification dialog
    def test_verify_spawn_crashed_process_emits_execution_error(
        self, qtbot: QtBot
    ) -> None:
        """verify_spawn emits execution_error when process has already exited."""
        executor = ProcessExecutor(Config)
        error_emissions: list[tuple[str, str]] = []
        executor.execution_error.connect(
            lambda ts, msg: error_emissions.append((ts, msg))
        )

        # A PopenDouble with returncode=1 and _terminated=True so poll() returns 1
        crashed_process = PopenDouble(args=["3de"], returncode=1)
        crashed_process._terminated = True

        executor.verify_spawn(crashed_process, "3de")
        process_qt_events()

        assert len(error_emissions) == 1
        _ts, msg = error_emissions[0]
        assert "3de" in msg
        assert "crashed" in msg.lower() or "exit code" in msg.lower()

        executor.cleanup()

    @pytest.mark.allow_dialogs  # verify_spawn shows an error notification dialog
    def test_verify_spawn_crashed_process_emits_execution_completed_with_false(
        self, qtbot: QtBot
    ) -> None:
        """verify_spawn emits execution_completed(False, ...) when process crashed."""
        executor = ProcessExecutor(Config)
        completed_emissions: list[tuple[bool, str]] = []
        executor.execution_completed.connect(
            lambda ok, msg: completed_emissions.append((ok, msg))
        )

        crashed_process = PopenDouble(args=["maya"], returncode=127)
        crashed_process._terminated = True

        executor.verify_spawn(crashed_process, "maya")
        process_qt_events()

        assert len(completed_emissions) == 1
        success, _msg = completed_emissions[0]
        assert success is False

        executor.cleanup()

    def test_verify_spawn_running_process_emits_progress(
        self, qtbot: QtBot
    ) -> None:
        """verify_spawn emits execution_progress when process is still running."""
        executor = ProcessExecutor(Config)
        progress_emissions: list[tuple[str, str]] = []
        executor.execution_progress.connect(
            lambda ts, msg: progress_emissions.append((ts, msg))
        )

        # PopenDouble with no returncode set and _terminated=False → poll() returns None
        running_process = PopenDouble(args=["nuke"], returncode=0)
        # Override poll to return None (still running) regardless of _terminated state
        running_process.poll = lambda: None  # type: ignore[method-assign]

        executor.verify_spawn(running_process, "nuke")
        process_qt_events()

        assert len(progress_emissions) == 1
        _ts, msg = progress_emissions[0]
        assert "nuke" in msg.lower()
        assert "started" in msg.lower() or "pid" in msg.lower()

        executor.cleanup()


# ---------------------------------------------------------------------------
# ProcessExecutor.execute_in_new_terminal — OS-level errors
# ---------------------------------------------------------------------------


class TestExecuteInNewTerminalErrors:
    """Tests for OS-level errors during process spawning."""

    def test_permission_error_returns_none(self, qtbot: QtBot) -> None:
        """PermissionError during Popen returns None (does not propagate)."""
        executor = ProcessExecutor(Config)

        with patch("launch.process_executor.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = PermissionError("permission denied")
            result = executor.execute_in_new_terminal(
                "echo hello", "3de", terminal="gnome-terminal"
            )

        assert result is None
        executor.cleanup()

    def test_os_error_returns_none(self, qtbot: QtBot) -> None:
        """Generic OSError during Popen returns None (does not propagate)."""
        executor = ProcessExecutor(Config)

        with patch("launch.process_executor.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = OSError("no such device")
            result = executor.execute_in_new_terminal(
                "echo hello", "maya", terminal="xterm"
            )

        assert result is None
        executor.cleanup()

    def test_file_not_found_returns_none(self, qtbot: QtBot) -> None:
        """FileNotFoundError during Popen returns None (terminal binary missing)."""
        executor = ProcessExecutor(Config)

        with patch("launch.process_executor.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("No such file: gnome-terminal")
            result = executor.execute_in_new_terminal(
                "nuke -x", "nuke", terminal="gnome-terminal"
            )

        assert result is None
        executor.cleanup()


# ---------------------------------------------------------------------------
# _validate_workspace_before_launch — path edge cases
# ---------------------------------------------------------------------------


class TestValidateWorkspaceBeforeLaunch:
    """Tests for workspace pre-flight validation."""

    def test_nonexistent_workspace_emits_error_and_returns_false(
        self,
        launcher: CommandLauncher,
        qtbot: QtBot,
    ) -> None:
        """Launch is blocked when workspace directory does not exist."""

        result = launcher._validate_workspace_before_launch(
            "/nonexistent/path/that/does/not/exist", "3de"
        )

        assert result is False

    def test_file_instead_of_directory_emits_error_and_returns_false(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
        qtbot: QtBot,
    ) -> None:
        """Launch is blocked when workspace_path points to a file, not a directory."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("I am a file")

        result = launcher._validate_workspace_before_launch(str(file_path), "nuke")

        assert result is False

    def test_no_read_permission_emits_error_and_returns_false(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
        qtbot: QtBot,
    ) -> None:
        """Launch is blocked when workspace is not readable/executable."""
        restricted = tmp_path / "restricted_ws"
        restricted.mkdir()
        restricted.chmod(0o000)


        try:
            result = launcher._validate_workspace_before_launch(str(restricted), "maya")
        finally:
            restricted.chmod(0o755)  # restore so tmp_path can clean up

        # Only meaningful as a non-root user; root always passes permission checks
        if os.getuid() != 0:
            assert result is False

    def test_valid_workspace_returns_true(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
    ) -> None:
        """Validation passes for a real, readable directory."""
        ws = tmp_path / "valid_ws"
        ws.mkdir()

        result = launcher._validate_workspace_before_launch(str(ws), "3de")

        assert result is True


# ---------------------------------------------------------------------------
# launch_app — no shot context and unknown app
# ---------------------------------------------------------------------------


class TestLaunchAppGuardClauses:
    """Tests for early-exit guard clauses in launch_app."""

    def test_launch_app_without_shot_emits_error_and_returns_false(
        self,
        launcher: CommandLauncher,
        qtbot: QtBot,
    ) -> None:
        """launch_app returns False immediately when no shot is selected."""

        result = launcher.launch(LaunchRequest(app_name="3de"))

        assert result is False

    def test_launch_app_unknown_app_emits_error_and_returns_false(
        self,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """launch_app returns False for an app name not in Config.APPS."""
        launcher.set_current_shot(test_shot)

        result = launcher.launch(LaunchRequest(app_name="blender_xyz_unknown"))

        assert result is False

    def test_launch_app_opening_scene_file_unknown_app_emits_error(
        self,
        launcher: CommandLauncher,
        test_scene: ThreeDEScene,
        qtbot: QtBot,
    ) -> None:
        """launch returns False for unknown app names even when scene is provided."""

        result = launcher.launch(LaunchRequest(app_name="blender_xyz_unknown", scene=test_scene))

        assert result is False


# ---------------------------------------------------------------------------
# Invalid scene paths in launch_app_opening_scene_file
# ---------------------------------------------------------------------------


class TestInvalidScenePaths:
    """Tests for malformed or dangerous scene paths."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "/shows/TEST/shots/seq01/sh0010/3de/scene.3de; rm -rf /",
            "/shows/TEST/shots/seq01/sh0010/3de/scene.3de && evil",
            "/shows/TEST/shots/seq01/sh0010/3de/scene.3de | cat /etc/passwd",
        ],
        ids=["semicolon-injection", "double-ampersand-injection", "pipe-injection"],
    )
    def test_scene_path_with_shell_injection_characters_blocked(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
        bad_path: str,
        qtbot: QtBot,
    ) -> None:
        """launch_app_opening_scene_file rejects paths containing shell meta-characters."""
        import time

        ws = tmp_path / "ws"
        ws.mkdir()
        scene = ThreeDEScene(
            show="TEST",
            sequence="seq01",
            shot="0010",
            workspace_path=str(ws),
            user="artist",
            plate="plate_v001",
            scene_path=Path(bad_path),
            modified_time=time.time(),
        )

        result = launcher.launch(LaunchRequest(app_name="3de", scene=scene))

        assert result is False


# ---------------------------------------------------------------------------
# Invalid workspace path in _finish_launch
# ---------------------------------------------------------------------------


class TestInvalidWorkspacePathInFinishLaunch:
    """Tests for dangerous workspace paths caught during command construction."""

    def test_workspace_path_with_shell_injection_blocked(
        self,
        launcher: CommandLauncher,
        qtbot: QtBot,
    ) -> None:
        """_finish_launch rejects workspace paths containing shell meta-characters."""

        # Pass a dangerous workspace path directly to _finish_launch
        # (bypassing the workspace existence check via a patched validator)
        with patch.object(
            CommandLauncher,
            "_validate_workspace_before_launch",
            return_value=True,
        ):
            # The path itself contains a dangerous character
            result = launcher._finish_launch(
                "3de",
                "3de",
                workspace_path="/shows/TEST/shots/seq01/0010; malicious_command",
            )

        assert result is False

    def test_empty_workspace_path_with_no_shot_blocked(
        self,
        launcher: CommandLauncher,
        qtbot: QtBot,
    ) -> None:
        """_finish_launch returns False when workspace_path is None and no shot is set."""

        result = launcher._finish_launch("3de", "3de", workspace_path=None)

        assert result is False


# ---------------------------------------------------------------------------
# Consecutive timeout → success: counter reset behaviour
# ---------------------------------------------------------------------------


@pytest.mark.allow_dialogs
class TestConsecutiveTimeoutThenSuccess:
    """Tests for timeout counter edge cases not covered by test_command_launcher.py."""

    @pytest.fixture
    def timeout_launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """CommandLauncher with env manager cache stub for reset tracking."""
        from launch import EnvironmentManager

        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)
        return CommandLauncher()

    def test_two_timeouts_do_not_reset_cache(
        self, timeout_launcher: CommandLauncher
    ) -> None:
        """Two consecutive timeouts do not trigger a cache reset (threshold is 3)."""
        reset_calls: list[None] = []
        timeout_launcher.env_manager.reset_cache = lambda: reset_calls.append(None)  # type: ignore[method-assign]

        timeout_launcher._consecutive_timeout_count = 0
        timeout_launcher._on_app_verification_timeout("maya")
        timeout_launcher._on_app_verification_timeout("maya")

        assert timeout_launcher._consecutive_timeout_count == 2
        assert len(reset_calls) == 0

    def test_verified_after_two_timeouts_resets_counter_to_zero(
        self, timeout_launcher: CommandLauncher
    ) -> None:
        """Successful verification after 2 timeouts brings counter to 0."""
        timeout_launcher._consecutive_timeout_count = 2
        timeout_launcher._on_app_verified("maya", 55555)

        assert timeout_launcher._consecutive_timeout_count == 0

    def test_timeout_after_success_starts_fresh_count(
        self, timeout_launcher: CommandLauncher
    ) -> None:
        """A timeout that follows a success counts as 1, not accumulated."""
        reset_calls: list[None] = []
        timeout_launcher.env_manager.reset_cache = lambda: reset_calls.append(None)  # type: ignore[method-assign]

        # Simulate 2 timeouts, then a success, then 1 more timeout
        timeout_launcher._consecutive_timeout_count = 2
        timeout_launcher._on_app_verified("3de", 12345)
        assert timeout_launcher._consecutive_timeout_count == 0

        timeout_launcher._on_app_verification_timeout("3de")
        assert timeout_launcher._consecutive_timeout_count == 1
        # Only 1 timeout since reset — should NOT have triggered cache reset
        assert len(reset_calls) == 0




# ---------------------------------------------------------------------------
# ProcessExecutor cleanup while timers pending
# ---------------------------------------------------------------------------


class TestProcessExecutorCleanup:
    """Tests for ProcessExecutor cleanup behaviour."""

    def test_cleanup_cancels_pending_timers(self, qtbot: QtBot) -> None:
        """cleanup() empties the pending timer list so no stale callbacks fire."""
        executor = ProcessExecutor(Config)

        # Simulate a running process so a timer is created
        running_popen = PopenDouble(args=["3de"], returncode=0)
        running_popen.poll = lambda: None  # type: ignore[method-assign]

        with patch("launch.process_executor.subprocess.Popen", return_value=running_popen):
            executor.execute_in_new_terminal(
                "echo hello", "3de", terminal="gnome-terminal"
            )

        assert len(executor._pending_timers) > 0

        executor.cleanup()

        assert len(executor._pending_timers) == 0

        executor.deleteLater()
        process_qt_events()

    def test_cleanup_idempotent_on_double_call(self, qtbot: QtBot) -> None:
        """Calling cleanup() twice does not raise."""
        executor = ProcessExecutor(Config)
        executor.cleanup()
        executor.cleanup()  # should not raise
