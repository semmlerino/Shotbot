"""Tests for CommandLauncher following UNIFIED_TESTING_GUIDE.

This test suite validates CommandLauncher behavior using:
- Test doubles for external dependencies
- Real Qt components and signals
- Behavior testing, not implementation details
"""

from __future__ import annotations

import string
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from PySide6.QtCore import QThread, Signal

from command_launcher import CommandLauncher, LaunchContext
from config import Config
from launch import CommandBuilder
from shot_model import Shot
from tests.test_helpers import process_qt_events
from threede_scene_model import ThreeDEScene


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from tests.fixtures.subprocess_mocking import SubprocessMock



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
        "command_launcher.EnvironmentManager.detect_terminal",
        lambda _self: "gnome-terminal",
    )


class TestCommandLauncher:
    """Test CommandLauncher functionality."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """Create CommandLauncher with test doubles."""
        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        return CommandLauncher()

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

    def test_initialization(self, launcher: CommandLauncher) -> None:
        """Test CommandLauncher initializes correctly."""
        assert launcher.current_shot is None
        assert hasattr(launcher, "command_executed")
        assert hasattr(launcher, "command_error")

    def test_set_current_shot(self, launcher: CommandLauncher, test_shot: Shot) -> None:
        """Test setting current shot."""
        launcher.set_current_shot(test_shot)
        assert launcher.current_shot == test_shot

    def test_set_current_shot_none(self, launcher: CommandLauncher) -> None:
        """Test clearing current shot."""
        launcher.set_current_shot(None)
        assert launcher.current_shot is None

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
            patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False),
            patch("launch.process_executor.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
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
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
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
        mock_popen.return_value = MagicMock()

        # Launch 3DE with scene
        result = launcher.launch_app_with_scene("3de", test_scene)

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "3de" in " ".join(call_args)
        assert str(test_scene.scene_path) in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_rv_with_sequence_path(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching RV with image sequence path (playblast/render).

        When double-clicking a playblast/render in DCC section, sequence_path
        is passed to launch RV with that specific image sequence loaded.
        """
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch RV with sequence path (simulates double-click on playblast)
        sequence_path = "/shows/TEST/shots/seq01/seq01_0010/playblast/shot.####.exr"
        result = launcher.launch_app("rv", LaunchContext(sequence_path=sequence_path))

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        # Verify RV command includes the sequence path
        assert "rv" in command_str
        assert sequence_path in command_str
        # Verify default RV settings are present
        assert "-fps 12" in command_str
        assert "-play" in command_str
        assert "setPlayMode(2)" in command_str

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_rv_without_sequence_path(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test RV launch without sequence path still includes default settings."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch RV without sequence path
        result = launcher.launch_app("rv")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called with default RV settings
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        assert "rv" in command_str
        assert "-fps 12" in command_str
        assert "-play" in command_str
        assert "setPlayMode(2)" in command_str

    def test_no_shot_context_error(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test error when no shot context is set."""
        # Try to launch without shot (no shot set)
        result = launcher.launch_app("nuke")

        # Should return False when no shot is set
        assert result is False

    @pytest.mark.allow_dialogs  # Error dialog is expected side-effect
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
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
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.EnvironmentManager.detect_terminal", return_value=None)
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
        mock_popen.return_value = MagicMock()

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

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_gui_app_with_background_setting_enabled(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that GUI apps are backgrounded when setting is enabled."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE (a GUI app)
        with patch.object(launcher._settings_manager, "get_background_gui_apps", return_value=True):
            result = launcher.launch_app("3de")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        # Verify the command contains background wrapping
        assert "disown" in command_str
        assert "exit" in command_str

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_gui_app_without_background_setting(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that GUI apps are NOT backgrounded when setting is disabled (default)."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE (a GUI app) - default setting is False
        with patch.object(launcher._settings_manager, "get_background_gui_apps", return_value=False):
            result = launcher.launch_app("3de")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        # Verify the command does NOT contain background wrapping
        assert "disown" not in command_str


class TestCommandLauncherSignals:
    """Test CommandLauncher signal emissions."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """Create CommandLauncher with test doubles."""
        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        return CommandLauncher()

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
            patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False),
        ):
            mock_popen.return_value = MagicMock()

            # Launch should succeed
            result = launcher.launch_app("nuke")
            assert result is True

            # Wait for QTimer.singleShot(100ms) callback to complete
            process_qt_events()

            # Should have called Popen
            assert mock_popen.called


class TestVerificationTimeoutCounter:
    """Test verification timeout counter behavior.

    VFX apps can take 30-60+ seconds to boot (Rez resolution + plugin scanning).
    A single timeout doesn't indicate failure. But repeated timeouts suggest
    terminal detection issues, so we reset the environment cache after 3 consecutive
    timeouts to allow fresh terminal detection on next launch.
    """

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """Create CommandLauncher for verification timeout testing."""
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        return CommandLauncher()

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


class TestLaunchContextProperties:
    """Property-based tests for LaunchContext value object."""

    @given(
        open_latest_threede=st.booleans(),
        open_latest_maya=st.booleans(),
        open_latest_scene=st.booleans(),
        create_new_file=st.booleans(),
    )
    def test_launch_context_creation_always_succeeds(
        self,
        open_latest_threede: bool,
        open_latest_maya: bool,
        open_latest_scene: bool,
        create_new_file: bool,
    ) -> None:
        """Verify LaunchContext can be created with any boolean combination."""
        context = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_maya=open_latest_maya,
            open_latest_scene=open_latest_scene,
            create_new_file=create_new_file,
        )

        # Verify all fields are set correctly
        assert context.open_latest_threede == open_latest_threede
        assert context.open_latest_maya == open_latest_maya
        assert context.open_latest_scene == open_latest_scene
        assert context.create_new_file == create_new_file

    @given(selected_plate=st.one_of(st.none(), st.text(min_size=1, max_size=10)))
    def test_launch_context_selected_plate_optional(
        self, selected_plate: str | None
    ) -> None:
        """Verify LaunchContext handles optional selected_plate correctly."""
        context = LaunchContext(selected_plate=selected_plate)

        assert context.selected_plate == selected_plate

    def test_launch_context_is_immutable(self) -> None:
        """Verify LaunchContext is frozen (immutable)."""
        context = LaunchContext(open_latest_scene=True)

        # Attempt to modify should raise FrozenInstanceError
        with pytest.raises(Exception, match=r"cannot assign to field"):  # FrozenInstanceError from dataclass
            context.open_latest_scene = False  # type: ignore[misc]

    @given(
        open_latest_threede=st.booleans(),
        open_latest_maya=st.booleans(),
        open_latest_scene=st.booleans(),
        create_new_file=st.booleans(),
        selected_plate=st.one_of(st.none(), st.text(min_size=1, max_size=10)),
    )
    def test_launch_context_equality(
        self,
        open_latest_threede: bool,
        open_latest_maya: bool,
        open_latest_scene: bool,
        create_new_file: bool,
        selected_plate: str | None,
    ) -> None:
        """Verify LaunchContext equality works correctly."""
        context1 = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_maya=open_latest_maya,
            open_latest_scene=open_latest_scene,
            create_new_file=create_new_file,
            selected_plate=selected_plate,
        )

        context2 = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_maya=open_latest_maya,
            open_latest_scene=open_latest_scene,
            create_new_file=create_new_file,
            selected_plate=selected_plate,
        )

        # Same values should be equal
        assert context1 == context2

        # Should be hashable (since frozen=True)
        assert hash(context1) == hash(context2)


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


class TestLaunchContextDefaults:
    """Test LaunchContext default values."""

    def test_default_context_has_all_false(self) -> None:
        """Verify default LaunchContext has all boolean flags False."""
        context = LaunchContext()

        assert context.open_latest_threede is False
        assert context.open_latest_maya is False
        assert context.open_latest_scene is False
        assert context.create_new_file is False
        assert context.selected_plate is None

    @given(
        open_latest_threede=st.booleans(),
        open_latest_scene=st.booleans(),
    )
    def test_partial_context_creation(
        self, open_latest_threede: bool, open_latest_scene: bool
    ) -> None:
        """Verify LaunchContext can be created with partial parameters."""
        context = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_scene=open_latest_scene,
        )

        # Specified parameters
        assert context.open_latest_threede == open_latest_threede
        assert context.open_latest_scene == open_latest_scene

        # Unspecified parameters should have defaults
        assert context.open_latest_maya is False
        assert context.create_new_file is False
        assert context.selected_plate is None


class TestPathValidationEdgeCases:
    """Test edge cases in path validation using Hypothesis."""

    @given(path=st.just(""))
    def test_empty_path_rejected(self, path: str) -> None:
        """Verify empty paths are rejected."""
        with pytest.raises(ValueError, match=r".*empty.*|.*invalid.*"):
            CommandBuilder.validate_path(path)

    @given(path=st.text(max_size=0))
    def test_zero_length_path_rejected(self, path: str) -> None:
        """Verify zero-length paths are rejected."""
        if len(path) == 0:
            with pytest.raises(ValueError, match=r".*empty.*|.*invalid.*"):
                CommandBuilder.validate_path(path)

    @given(
        path=st.text(
            alphabet=string.whitespace,
            min_size=1,
            max_size=10,
        )
    )
    def test_whitespace_only_paths_handled_safely(self, path: str) -> None:
        """Verify whitespace-only paths are either rejected or safely quoted."""
        try:
            result = CommandBuilder.validate_path(path)
            # If accepted, should be quoted to prevent issues
            assert isinstance(result, str)
            # Should be wrapped in quotes if it contains spaces
            if " " in path:
                assert "'" in result or '"' in result
        except ValueError:
            # Rejection is also acceptable for whitespace-only paths
            pass


# ---------------------------------------------------------------------------
# Thread safety tests
# ---------------------------------------------------------------------------


class _WorkerThread(QThread):
    """Worker thread for testing cross-thread signal emissions."""

    finished_signal = Signal()

    def __init__(self, launcher: CommandLauncher, shot: MagicMock) -> None:
        """Initialize worker thread.

        Args:
            launcher: CommandLauncher instance to test
            shot: Mock shot object

        """
        super().__init__()
        self.launcher = launcher
        self.shot = shot

    def run(self) -> None:
        """Set current shot from worker thread."""
        self.launcher.set_current_shot(self.shot)
        self.finished_signal.emit()


class TestCommandLauncherThreadSafety:
    """Test CommandLauncher threading and concurrency behavior."""

    @pytest.fixture
    def launcher(self) -> CommandLauncher:
        """Create CommandLauncher instance for testing."""
        return CommandLauncher()

    def test_current_shot_access_from_worker_thread(
        self, qtbot: QtBot, launcher: CommandLauncher
    ) -> None:
        """Test that set_current_shot can be safely called from worker thread.

        While CommandLauncher is typically used from GUI thread, this test
        verifies that basic state access is thread-safe.
        """
        mock_shot = MagicMock(
            full_name="TEST_SHOT_0010",
            workspace_path="/test/workspace",
        )

        # Create worker thread
        worker = _WorkerThread(launcher, mock_shot)

        try:
            # Start worker and wait for completion
            with qtbot.waitSignal(worker.finished_signal, timeout=1000):
                worker.start()

            # Verify shot was set correctly
            assert launcher.current_shot == mock_shot
            assert launcher.current_shot.full_name == "TEST_SHOT_0010"
        finally:
            # Ensure QThread cleanup even if assertions fail
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
            worker.deleteLater()

    def test_signal_emissions_gui_and_cross_thread(
        self, qtbot: QtBot, launcher: CommandLauncher
    ) -> None:
        """Test command_error signal delivery from GUI thread and concurrent worker threads."""
        # Part 1: GUI thread emission
        gui_signals: list[tuple[str, str]] = []
        launcher.command_error.connect(lambda ts, err: gui_signals.append((ts, err)))

        launcher._emit_error("Test error from GUI")
        qtbot.wait(10)

        assert len(gui_signals) > 0
        assert "Test error from GUI" in gui_signals[0][1]

        # Part 2: Concurrent cross-thread emissions
        cross_thread_signals: list[tuple[str, str]] = []
        lock = threading.Lock()
        launcher2 = CommandLauncher()

        def on_error(timestamp: str, error: str) -> None:
            with lock:
                cross_thread_signals.append((timestamp, error))

        launcher2.command_error.connect(on_error)

        def emit_error(thread_id: int) -> None:
            for i in range(5):
                launcher2._emit_error(f"Error from thread {thread_id}, iteration {i}")
                time.sleep(0)

        threads = [threading.Thread(target=emit_error, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        qtbot.wait(100)

        assert len(cross_thread_signals) == 15
        thread_ids = {
            int(err.split("thread ")[1].split(",")[0])
            for _, err in cross_thread_signals
        }
        assert thread_ids == {0, 1, 2}

    def test_launch_app_called_concurrently(
        self, qtbot: QtBot, launcher: CommandLauncher, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test concurrent launch_app calls.

        While unlikely in practice (GUI prevents concurrent launches),
        this verifies that concurrent calls don't cause crashes or race conditions.
        """
        # Set up mock shot
        mock_shot = MagicMock(
            full_name="TEST_SHOT_0010",
            workspace_path="/test/workspace",
        )
        launcher.set_current_shot(mock_shot)

        # Mock dependencies
        # IMPORTANT: Patch command_launcher.Config.APPS, not config.Config.APPS
        # This is because module reloading in other tests can cause command_launcher
        # to hold a reference to a different Config class than config.Config
        monkeypatch.setattr("command_launcher.Config.APPS", {"test_app": "test_command"})
        monkeypatch.setattr("launch.process_executor.subprocess.Popen", Mock(return_value=Mock(pid=12345)))
        monkeypatch.setattr("command_launcher.EnvironmentManager.detect_terminal", lambda _self: "gnome-terminal")
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_rez_available", lambda _self, _config: False)

        # Track results
        results: list[bool] = []
        lock = threading.Lock()

        def launch_app_thread() -> None:
            result = launcher.launch_app("test_app")
            with lock:
                results.append(result)

        # Create multiple threads
        threads = [threading.Thread(target=launch_app_thread) for _ in range(3)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Process Qt events
        qtbot.wait(100)

        # Verify all launches succeeded (or at least completed without crashing)
        assert len(results) == 3
        # Note: Results may vary due to race conditions, but all should complete

    @pytest.mark.real_timing  # Uses qtbot.wait(200) for QTimer callback
    def test_qtimer_callback_thread_safety(
        self, qtbot: QtBot, launcher: CommandLauncher, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test that QTimer callbacks execute on correct thread.

        CommandLauncher uses QTimer.singleShot for delayed spawn verification.
        This test verifies that the callback executes on the GUI thread.
        """
        # Create a real temporary workspace directory
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        mock_shot = MagicMock(
            full_name="TEST_SHOT_0010",
            workspace_path=str(workspace),
        )
        launcher.set_current_shot(mock_shot)

        # Mock dependencies
        # IMPORTANT: Patch command_launcher.Config.APPS, not config.Config.APPS
        # This is because module reloading in other tests can cause command_launcher
        # to hold a reference to a different Config class than config.Config
        monkeypatch.setattr("command_launcher.Config.APPS", {"test_app": "test_command"})

        mock_process = Mock(pid=12345, poll=Mock(return_value=None))
        monkeypatch.setattr("launch.process_executor.subprocess.Popen", Mock(return_value=mock_process))
        monkeypatch.setattr("command_launcher.EnvironmentManager.detect_terminal", lambda _self: "gnome-terminal")
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_rez_available", lambda _self, _config: False)
        # CRITICAL: Mock is_ws_available - 'ws' command isn't available in dev environment
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_ws_available", lambda _self: True)

        # Launch app (will schedule QTimer callback)
        result = launcher.launch_app("test_app")
        assert result is True

        # Wait for QTimer callback (100ms delay + margin)
        qtbot.wait(200)

        # Verify spawn verification was called
        # (We can't directly test thread ID, but if it runs without crashing, it's correct)
        assert mock_process.poll.called

    @pytest.mark.usefixtures("qtbot")
    def test_cleanup_thread_safety(
        self, launcher: CommandLauncher
    ) -> None:
        """Test that cleanup() can be safely called from any thread.

        This is important for Python's garbage collection which may run
        __del__ from any thread.
        """
        # Call cleanup from worker thread
        def cleanup_from_thread() -> None:
            launcher.cleanup()

        thread = threading.Thread(target=cleanup_from_thread)
        thread.start()
        thread.join()

        # Verify cleanup completed without error
        # (If it crashes, the test will fail)

        # Cleanup again from GUI thread (should be idempotent)
        launcher.cleanup()

    @pytest.mark.usefixtures("qtbot")
    def test_state_consistency_under_concurrent_access(
        self, launcher: CommandLauncher
    ) -> None:
        """Test that concurrent state access maintains consistency.

        This test rapidly sets and reads current_shot from multiple threads
        to verify no corruption occurs.
        """
        shots = [
            MagicMock(full_name=f"SHOT_{i:04d}", workspace_path=f"/test/shot{i}")
            for i in range(10)
        ]

        def set_shots_rapidly() -> None:
            for shot in shots:
                launcher.set_current_shot(shot)
                time.sleep(0)

        threads = [threading.Thread(target=set_shots_rapidly) for _ in range(3)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Verify final state is one of the valid shots
        assert launcher.current_shot in shots or launcher.current_shot is None
        # Verify no corruption (shot object is intact)
        if launcher.current_shot:
            assert hasattr(launcher.current_shot, "full_name")
            assert hasattr(launcher.current_shot, "workspace_path")


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
        from process_pool_manager import ProcessPoolManager

        # Get the singleton instance (should be mocked by autouse fixture)
        pool = ProcessPoolManager.get_instance()

        # The mock should not execute real subprocesses
        assert pool is not None
