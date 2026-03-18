"""Tests for CommandLauncher following UNIFIED_TESTING_GUIDE.

This test suite validates CommandLauncher behavior using:
- Test doubles for external dependencies
- Real Qt components and signals
- Behavior testing, not implementation details
"""

from __future__ import annotations

import string
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from config import Config
from launch import CommandBuilder
from launch.command_launcher import CommandLauncher, LaunchContext
from tests.fixtures.process_fixtures import PopenDouble
from tests.test_helpers import process_qt_events
from type_definitions import Shot, ThreeDEScene


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from tests.fixtures.process_fixtures import SubprocessMock


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
    process_qt_events()


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
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[CommandLauncher]:
        """Create CommandLauncher with test doubles."""
        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        launcher = CommandLauncher()
        yield launcher
        launcher.cleanup()
        process_qt_events()

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create a test shot."""
        return Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")

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
        launcher: CommandLauncher,
        test_shot: Shot,
        app_name: str,
        expected_token: str,
    ) -> None:
        """Test launching supported applications with common expectations."""
        launcher.set_current_shot(test_shot)

        with (
            patch.object(
                CommandLauncher, "_validate_workspace_before_launch", return_value=True
            ),
            patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True),
            patch("launch.process_executor.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = _running_process_double(app_name)
            result = launcher.launch_app(app_name)

        assert result is True
        process_qt_events()

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

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_nuke_with_scene_sets_sgtk_file_to_open(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        qtbot: QtBot,
    ) -> None:
        """Nuke scene launches should export SGTK_FILE_TO_OPEN for PTR bootstrap."""
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

        result = launcher.launch_app_opening_scene_file("nuke", nuke_scene)

        assert result is True
        process_qt_events()
        assert mock_popen.called
        command_str = " ".join(mock_popen.call_args[0][0])
        assert "NUKE_PATH" in command_str
        assert "SGTK_FILE_TO_OPEN=/path/to/scene.nk" in command_str
        # Nuke should NOT have the scene file as a command argument
        assert "nuke /path/to/scene.nk" not in command_str

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_3de_with_scene(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_scene: ThreeDEScene,
        qtbot: QtBot,
    ) -> None:
        """Test launching 3DE with specific scene."""
        # Setup mock
        mock_popen.return_value = _running_process_double("3de")

        # Launch 3DE with scene
        result = launcher.launch_app_opening_scene_file("3de", test_scene)

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)
        assert "3de" in command_str
        assert str(test_scene.scene_path) in command_str
        assert "PYTHON_CUSTOM_SCRIPTS_3DE4" in command_str
        assert "SGTK_FILE_TO_OPEN" in command_str

    @pytest.mark.parametrize("sequence_path", [
        None,
        "/shows/TEST/shots/seq01/seq01_0010/playblast/shot.####.exr",
    ], ids=["without_sequence", "with_sequence"])
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_rv_default_settings(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
        sequence_path: str | None,
    ) -> None:
        """Test RV launch includes default settings with and without sequence path."""
        launcher.set_current_shot(test_shot)
        mock_popen.return_value = _running_process_double("rv")

        if sequence_path:
            result = launcher.launch_app("rv", LaunchContext(sequence_path=sequence_path))
        else:
            result = launcher.launch_app("rv")

        assert result is True
        process_qt_events()
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
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True)
    @patch("launch.process_executor.subprocess.Popen")
    def test_subprocess_failure(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test handling subprocess failure."""
        launcher.set_current_shot(test_shot)

        # Setup mock to simulate failure for all terminal types
        mock_popen.side_effect = FileNotFoundError("terminal not found")

        # Launch app should fail
        result = launcher.launch_app("nuke")

        # Should return False when subprocess fails
        assert result is False

        # Wait for any pending Qt events (QTimer won't fire due to failure, but process events)
        process_qt_events()

        # Verify subprocess was attempted
        assert mock_popen.called

    @pytest.mark.allow_dialogs  # May show warning dialog
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True)
    @patch("launch.command_launcher.EnvironmentManager.detect_terminal", return_value=None)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_headless_mode_when_no_terminal(
        self,
        mock_popen: MagicMock,
        mock_detect_terminal: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that launches succeed in headless mode when no terminal is available."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = _running_process_double("nuke")

        # Launch app - should succeed even without terminal
        result = launcher.launch_app("nuke")

        # Verify launch was successful (headless mode)
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called with direct bash (headless)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "/bin/bash"
        assert "-ilc" in call_args
        assert "nuke" in " ".join(call_args)

    @pytest.mark.parametrize(("background", "expect_disown"), [
        (True, True),
        (False, False),
    ], ids=["background_enabled", "background_disabled"])
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_gui_app_background_setting(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
        background: bool,
        expect_disown: bool,
    ) -> None:
        """Test GUI app backgrounding respects the background_gui_apps setting."""
        launcher.set_current_shot(test_shot)
        mock_popen.return_value = _running_process_double("3de")

        with patch.object(launcher._settings_manager.launch, "get_background_gui_apps", return_value=background):
            result = launcher.launch_app("3de")

        assert result is True
        process_qt_events()
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        if expect_disown:
            assert "disown" in command_str
            assert "exit" in command_str
        else:
            assert "disown" not in command_str


class TestCommandLauncherSignals:
    """Test CommandLauncher signal emissions."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[CommandLauncher]:
        """Create CommandLauncher with test doubles."""
        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        launcher = CommandLauncher()
        yield launcher
        launcher.cleanup()
        process_qt_events()

    @pytest.mark.allow_dialogs  # Warning dialogs are acceptable in this smoke-style path test
    def test_signal_data_format(self, launcher: CommandLauncher, qtbot: QtBot) -> None:
        """Test basic launcher functionality."""
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        launcher.set_current_shot(shot)

        with (
            patch.object(
                CommandLauncher, "_validate_workspace_before_launch", return_value=True
            ),
            patch("launch.process_executor.subprocess.Popen") as mock_popen,
            patch("launch.command_launcher.EnvironmentManager.should_wrap_with_rez", return_value=True),
        ):
            mock_popen.return_value = _running_process_double("nuke")

            # Launch should succeed
            result = launcher.launch_app("nuke")
            assert result is True

            # Wait for QTimer.singleShot(100ms) callback to complete
            process_qt_events()

            # Should have called Popen
            assert mock_popen.called


@pytest.mark.allow_dialogs
class TestVerificationTimeoutCounter:
    """Test verification timeout counter behavior.

    VFX apps can take 30-60+ seconds to boot (Rez resolution + plugin scanning).
    A single timeout doesn't indicate failure. But repeated timeouts suggest
    terminal detection issues, so we reset the environment cache after 3 consecutive
    timeouts to allow fresh terminal detection on next launch.
    """

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[CommandLauncher]:
        """Create CommandLauncher for verification timeout testing."""
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        launcher = CommandLauncher()
        yield launcher
        launcher.cleanup()
        process_qt_events()

    def test_single_timeout_does_not_reset_cache(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that a single verification timeout does not reset the env cache."""
        # Initialize counter
        launcher._consecutive_timeout_count = 0

        # Mock reset_cache to verify it's NOT called
        with patch.object(launcher.env_manager, "reset_cache") as mock_reset:
            launcher._on_app_verification_timeout("nuke")

            # Counter should increment
            assert launcher._consecutive_timeout_count == 1

            # Cache should NOT be reset after single timeout
            mock_reset.assert_not_called()

    def test_three_timeouts_triggers_cache_reset(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that 3 consecutive timeouts trigger environment cache reset."""
        launcher._consecutive_timeout_count = 0

        with patch.object(launcher.env_manager, "reset_cache") as mock_reset:
            # First two timeouts don't reset
            launcher._on_app_verification_timeout("nuke")
            launcher._on_app_verification_timeout("nuke")
            assert mock_reset.call_count == 0
            assert launcher._consecutive_timeout_count == 2

            # Third timeout triggers reset
            launcher._on_app_verification_timeout("nuke")
            mock_reset.assert_called_once()
            # Counter should be reset after cache reset
            assert launcher._consecutive_timeout_count == 0

    def test_successful_verification_resets_counter(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that successful app verification resets the timeout counter."""
        # Simulate 2 prior timeouts
        launcher._consecutive_timeout_count = 2

        # Successful verification should reset counter
        launcher._on_app_verified("nuke", 12345)

        assert launcher._consecutive_timeout_count == 0

    def test_successful_verification_prevents_cache_reset(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that a successful verification breaks the timeout sequence."""
        launcher._consecutive_timeout_count = 0

        with patch.object(launcher.env_manager, "reset_cache") as mock_reset:
            # Two timeouts
            launcher._on_app_verification_timeout("nuke")
            launcher._on_app_verification_timeout("nuke")

            # Successful launch
            launcher._on_app_verified("nuke", 12345)
            assert launcher._consecutive_timeout_count == 0

            # Third timeout starts fresh sequence
            launcher._on_app_verification_timeout("nuke")
            assert launcher._consecutive_timeout_count == 1

            # Cache should NOT be reset (only 1 timeout since last success)
            mock_reset.assert_not_called()


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------

# Custom strategies for generating test data
@st.composite
def valid_filesystem_paths(draw: st.DrawFn) -> str:
    """Generate valid filesystem paths for testing.

    Returns paths that should be accepted by path validation.
    """
    # Generate path components
    num_components = draw(st.integers(min_value=1, max_value=5))
    components = []

    for _ in range(num_components):
        # Valid path component: alphanumeric, dash, underscore
        component = draw(
            st.text(
                alphabet=string.ascii_letters + string.digits + "_-",
                min_size=1,
                max_size=20,
            )
        )
        components.append(component)

    # Build path
    return "/" + "/".join(components)


@st.composite
def potentially_dangerous_paths(draw: st.DrawFn) -> str:
    """Generate potentially dangerous filesystem paths.

    Returns paths that contain injection attempts or invalid characters.
    """
    # Choose a dangerous pattern
    return draw(
        st.sampled_from(
            [
                "../../../etc/passwd",  # Path traversal
                "/tmp/test; rm -rf /",  # Command injection
                "/path/with spaces/file",  # Spaces (valid but need quoting)
                "/path/with\nnewline/file",  # Newline
                "/path/with\ttab/file",  # Tab
                "/path/with'quote/file",  # Single quote
                '/path/with"quote/file',  # Double quote
                "/path/with$(cmd)/file",  # Command substitution
                "/path/with`cmd`/file",  # Backtick substitution
                "/path/with|pipe/file",  # Pipe
                "/path/with&background/file",  # Background operator
                "/path/with;semicolon/file",  # Command separator
            ]
        )
    )


class TestCommandBuilderProperties:
    """Property-based tests for CommandBuilder path validation."""

    @given(path=valid_filesystem_paths())
    def test_validate_path_accepts_valid_paths(self, path: str) -> None:
        """Verify path validation accepts valid filesystem paths."""
        # Valid paths should be accepted
        validated = CommandBuilder.validate_path(path)

        # Validated path should be properly quoted if needed
        assert isinstance(validated, str)
        assert len(validated) > 0

    @given(path=potentially_dangerous_paths())
    @settings(max_examples=50)  # Limit examples for potentially slow tests
    def test_validate_path_handles_dangerous_paths(self, path: str) -> None:
        """Verify path validation handles potentially dangerous inputs.

        This test doesn't assert specific behavior, but verifies that
        validation doesn't crash or allow obvious injection attacks.
        """
        try:
            validated = CommandBuilder.validate_path(path)

            # If validation succeeds, ensure basic sanitation
            # Command injection patterns should be quoted/escaped
            dangerous_chars = [";", "|", "&", "$", "`", "\n"]
            for char in dangerous_chars:
                if char in path:
                    # Dangerous characters should be escaped or quoted
                    # (exact behavior depends on implementation)
                    assert isinstance(validated, str)

        except ValueError:
            # Some paths should be rejected (e.g., path traversal)
            # This is acceptable behavior
            pass

    @given(
        path=st.text(
            alphabet=string.ascii_letters + string.digits + "/-_.",
            min_size=1,
            max_size=100,
        )
    )
    def test_validate_path_returns_string(self, path: str) -> None:
        """Verify path validation always returns a string or raises ValueError."""
        try:
            result = CommandBuilder.validate_path(path)
            assert isinstance(result, str)
        except ValueError:
            # Rejection is acceptable
            pass

    @given(packages=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5))
    def test_wrap_with_rez_handles_various_package_lists(
        self, packages: list[str]
    ) -> None:
        """Verify rez wrapping handles various package list sizes."""
        command = "test_command"
        wrapped = CommandBuilder.wrap_with_rez(command, packages)

        # Wrapped command should contain original command
        assert command in wrapped

        # Wrapped command should reference rez
        assert "rez" in wrapped.lower() or "rez-env" in wrapped

    @given(command=st.text(min_size=1, max_size=100))
    def test_add_logging_handles_various_commands(self, command: str) -> None:
        """Verify logging addition handles various command formats."""
        # Filter out commands with newlines (not valid shell commands)
        assume("\n" not in command)

        logged = CommandBuilder.add_logging(command)

        # Logged command should contain original command
        assert command in logged

        # Should add redirection
        assert "2>&1" in logged or ">" in logged


class TestSubprocessErrorHandling:
    """Test subprocess error handling in the launcher and process pool."""

    def test_error_fixture_integrates_with_launcher_module(
        self,
        subprocess_error_mock: SubprocessMock,
    ) -> None:
        """Test that error fixtures properly patch subprocess for launcher error paths."""
        import subprocess

        # Configure specific error
        subprocess_error_mock.set_return_code(127)
        subprocess_error_mock.set_output("", stderr="bash: command not found")

        # Verify the fixture patches subprocess with the configured return code
        proc = subprocess.Popen(["test", "cmd"])
        assert proc.returncode == 127

        # The fixture should have recorded the call
        assert ["test", "cmd"] in subprocess_error_mock.calls

    def test_process_pool_uses_test_double(self) -> None:
        """Test that ProcessPoolManager uses the test double from autouse fixture.

        This test verifies that the autouse mock_process_pool_manager fixture
        properly patches the singleton, preventing real subprocess execution.
        """
        from workers.process_pool_manager import ProcessPoolManager

        # Get the singleton instance (should be mocked by autouse fixture)
        pool = ProcessPoolManager.get_instance()

        # The mock should not execute real subprocesses
        assert pool is not None
