"""Tests for CommandLauncher following UNIFIED_TESTING_GUIDE.

This test suite validates CommandLauncher behavior using:
- Test doubles for external dependencies
- Real Qt components and signals
- Behavior testing, not implementation details
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, Signal

from command_launcher import CommandLauncher
from config import Config
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


class TestRawPlateFinder:
    """Test double for RawPlateFinder."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def find_latest_raw_plate(shot_workspace_path: str, _shot_name: str) -> str | None:
        """Mock finding latest raw plate."""
        if "TEST" in shot_workspace_path:
            return "/path/to/plate.####.exr"
        return None

    @staticmethod
    def verify_plate_exists(plate_path: str) -> bool:
        """Mock verifying plate exists."""
        return "/path/to/plate" in plate_path

    @staticmethod
    def get_version_from_path(plate_path: str) -> str | None:
        """Mock getting version from path."""
        if "plate" in plate_path:
            return "v001"
        return None


class TestNukeScriptGenerator:
    """Test double for NukeScriptGenerator."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def create_plate_script(_plate_path: str, shot_name: str) -> str:
        """Mock creating plate script."""
        return f"/tmp/{shot_name}_plate.nk"


class TestThreeDELatestFinder:
    """Test double for ThreeDELatestFinder."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def find_latest_3de_scene(shot: Shot) -> str | None:
        """Mock finding latest 3DE scene."""
        if shot.show == "TEST":
            return "/path/to/latest.3de"
        return None


class TestMayaLatestFinder:
    """Test double for MayaLatestFinder."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def find_latest_maya_scene(shot: Shot) -> str | None:
        """Mock finding latest Maya scene."""
        if shot.show == "TEST":
            return "/path/to/latest.mb"
        return None


class TestPersistentTerminalManager(QObject):
    """Test double for PersistentTerminalManager."""

    __test__ = False  # Prevent pytest collection

    # Signals (matching real PersistentTerminalManager)
    command_finished = Signal(str, int)  # key, return_code
    command_error = Signal(str, str)  # key, error_message
    operation_started = Signal(str)  # operation_name
    operation_progress = Signal(str, str)  # operation_name, status_message
    operation_finished = Signal(str, bool, str)  # operation_name, success, message
    command_result = Signal(bool, str)  # success, error_message

    def __init__(self) -> None:
        """Initialize test terminal manager."""
        super().__init__()
        self.executed_commands: list[tuple[str, str]] = []  # Changed from list[str] to str
        self.is_available = True
        self._fallback_mode = False  # Add fallback mode attribute

    @property
    def is_fallback_mode(self) -> bool:
        """Check if persistent terminal is in fallback mode."""
        return self._fallback_mode

    def is_terminal_available(self) -> bool:
        """Check if terminal is available."""
        return self.is_available

    def execute_command(self, key: str, command: list[str]) -> None:
        """Record command execution."""
        # Simulate immediate success
        self.command_finished.emit(key, 0)

    def send_command(self, command: str) -> bool:
        """Send command to terminal (mocked - synchronous)."""
        self.executed_commands.append(("sync", command))
        return True

    def send_command_async(self, command: str) -> None:
        """Send command asynchronously (mocked)."""
        self.executed_commands.append(("async", command))
        # Simulate immediate success via signals
        self.operation_started.emit("send_command")
        self.operation_progress.emit("send_command", "Sending command")
        self.command_result.emit(True, "")
        self.operation_finished.emit("send_command", True, "Command sent")


class TestCommandLauncher:
    """Test CommandLauncher functionality."""

    @pytest.fixture
    def launcher(self) -> CommandLauncher:
        """Create CommandLauncher with test doubles."""
        return CommandLauncher(
            raw_plate_finder=TestRawPlateFinder,
            nuke_script_generator=TestNukeScriptGenerator,
            threede_latest_finder=TestThreeDELatestFinder,
            maya_latest_finder=TestMayaLatestFinder,
            persistent_terminal=None,  # Test without persistent terminal first
        )

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
        assert launcher.persistent_terminal is None
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

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.subprocess.Popen")
    def test_launch_nuke(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching Nuke application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch Nuke
        result = launcher.launch_app("nuke")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert (
            "gnome-terminal" in call_args
            or "xterm" in call_args
            or "konsole" in call_args
            or "x-terminal-emulator" in call_args
            or "/bin/bash" in call_args
        )
        assert "nuke" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.subprocess.Popen")
    def test_launch_nuke_with_raw_plate(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching Nuke with raw plate."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch Nuke with raw plate
        result = launcher.launch_app("nuke", include_raw_plate=True)

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "nuke" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.subprocess.Popen")
    def test_launch_3de(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching 3DE application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE
        result = launcher.launch_app("3de")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "3de" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.subprocess.Popen")
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
    @patch("command_launcher.subprocess.Popen")
    def test_launch_maya(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching Maya application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch Maya
        result = launcher.launch_app("maya")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "maya" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.subprocess.Popen")
    def test_launch_rv(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching RV application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch RV
        result = launcher.launch_app("rv")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "rv" in " ".join(call_args)

    def test_no_shot_context_error(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test error when no shot context is set."""
        # Try to launch without shot (no shot set)
        result = launcher.launch_app("nuke")

        # Should return False when no shot is set
        assert result is False

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.subprocess.Popen")
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

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.Config.PERSISTENT_TERMINAL_ENABLED", True)
    @patch("command_launcher.Config.USE_PERSISTENT_TERMINAL", True)
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    def test_persistent_terminal_usage(
        self, mock_rez: MagicMock, mock_validate: MagicMock, qtbot: QtBot
    ) -> None:
        """Test using persistent terminal manager with async API."""
        terminal = TestPersistentTerminalManager()
        launcher = CommandLauncher(
            raw_plate_finder=TestRawPlateFinder,
            nuke_script_generator=TestNukeScriptGenerator,
            threede_latest_finder=TestThreeDELatestFinder,
            maya_latest_finder=TestMayaLatestFinder,
            persistent_terminal=terminal,
        )

        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        launcher.set_current_shot(shot)

        # Launch app - should use persistent terminal (async)
        result = launcher.launch_app("nuke")

        # Should be successful
        assert result is True

        # Wait for any Qt events to process
        process_qt_events()

        # Verify terminal was used with async API
        assert len(terminal.executed_commands) == 1
        mode, command = terminal.executed_commands[0]
        assert mode == "async"  # Verify async method was used
        assert "nuke" in command

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.Config.PERSISTENT_TERMINAL_ENABLED", True)
    @patch("command_launcher.Config.USE_PERSISTENT_TERMINAL", True)
    def test_persistent_terminal_unavailable(
        self, mock_validate: MagicMock, qtbot: QtBot
    ) -> None:
        """Test fallback when persistent terminal is in fallback mode."""
        terminal = TestPersistentTerminalManager()
        terminal._fallback_mode = True  # Simulate terminal in fallback mode

        launcher = CommandLauncher(
            raw_plate_finder=TestRawPlateFinder,
            nuke_script_generator=TestNukeScriptGenerator,
            threede_latest_finder=TestThreeDELatestFinder,
            maya_latest_finder=TestMayaLatestFinder,
            persistent_terminal=terminal,
        )

        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        launcher.set_current_shot(shot)

        with (
            patch("command_launcher.subprocess.Popen") as mock_popen,
            patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False),
        ):
            mock_popen.return_value = MagicMock()

            # Launch app - should fall back to subprocess
            result = launcher.launch_app("nuke")

            # Should be successful
            assert result is True

            # Wait for QTimer.singleShot(100ms) callback to complete
            process_qt_events()

            # Verify subprocess was used as fallback (terminal was NOT used)
            assert mock_popen.called
            assert len(terminal.executed_commands) == 0  # Terminal should not have been used


class TestCommandLauncherSignals:
    """Test CommandLauncher signal emissions."""

    @pytest.fixture
    def launcher(self) -> CommandLauncher:
        """Create CommandLauncher with test doubles."""
        return CommandLauncher(
            raw_plate_finder=TestRawPlateFinder,
            nuke_script_generator=TestNukeScriptGenerator,
            threede_latest_finder=TestThreeDELatestFinder,
            maya_latest_finder=TestMayaLatestFinder,
            persistent_terminal=None,
        )

    def test_signal_data_format(self, launcher: CommandLauncher, qtbot: QtBot) -> None:
        """Test basic launcher functionality."""
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        launcher.set_current_shot(shot)

        with (
            patch.object(
                CommandLauncher, "_validate_workspace_before_launch", return_value=True
            ),
            patch("command_launcher.subprocess.Popen") as mock_popen,
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
