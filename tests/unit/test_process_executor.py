"""Tests for ProcessExecutor component.

This test suite provides comprehensive coverage of process execution:
- Persistent terminal routing
- New terminal window launching
- Process verification
- Signal emission and handling
- GUI app detection
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, Signal
from pytestqt.qtbot import QtBot

from config import Config
from launch.process_executor import ProcessExecutor


class MockPersistentTerminalManager(QObject):
    """Mock PersistentTerminalManager for testing."""

    # Signals (matching real PersistentTerminalManager)
    operation_progress = Signal(str, str)
    command_result = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.send_command_async_called = False
        self.last_command: str | None = None
        self._fallback_mode = False

    def send_command_async(self, command: str) -> None:
        """Mock async command sending."""
        self.send_command_async_called = True
        self.last_command = command


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config object."""
    config = MagicMock(spec=Config)
    config.PERSISTENT_TERMINAL_ENABLED = True
    config.USE_PERSISTENT_TERMINAL = True
    return config


@pytest.fixture
def mock_terminal() -> MockPersistentTerminalManager:
    """Create a mock persistent terminal manager."""
    return MockPersistentTerminalManager()


@pytest.fixture
def executor(
    mock_terminal: MockPersistentTerminalManager,
    mock_config: MagicMock,
) -> ProcessExecutor:
    """Create a ProcessExecutor with mocked dependencies."""
    return ProcessExecutor(mock_terminal, mock_config)


@pytest.fixture
def executor_no_terminal(mock_config: MagicMock) -> ProcessExecutor:
    """Create a ProcessExecutor without persistent terminal."""
    return ProcessExecutor(None, mock_config)


class TestGuiAppDetection:
    """Tests for GUI application detection."""

    def test_nuke_is_gui_app(self, executor: ProcessExecutor) -> None:
        """Test that Nuke is detected as GUI app."""
        assert executor.is_gui_app("nuke") is True

    def test_maya_is_gui_app(self, executor: ProcessExecutor) -> None:
        """Test that Maya is detected as GUI app."""
        assert executor.is_gui_app("maya") is True

    def test_3de_is_gui_app(self, executor: ProcessExecutor) -> None:
        """Test that 3DEqualizer is detected as GUI app."""
        assert executor.is_gui_app("3de") is True

    def test_rv_is_gui_app(self, executor: ProcessExecutor) -> None:
        """Test that RV is detected as GUI app."""
        assert executor.is_gui_app("rv") is True

    def test_case_insensitive(self, executor: ProcessExecutor) -> None:
        """Test that GUI app detection is case insensitive."""
        assert executor.is_gui_app("NUKE") is True
        assert executor.is_gui_app("Nuke") is True
        assert executor.is_gui_app("nuKE") is True

    def test_unknown_app_is_not_gui(self, executor: ProcessExecutor) -> None:
        """Test that unknown apps are not detected as GUI apps."""
        assert executor.is_gui_app("unknown") is False
        assert executor.is_gui_app("python") is False
        assert executor.is_gui_app("bash") is False


class TestPersistentTerminalAvailability:
    """Tests for persistent terminal availability checking."""

    def test_can_use_when_all_conditions_met(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
    ) -> None:
        """Test persistent terminal can be used when all conditions met."""
        mock_terminal._fallback_mode = False
        assert executor.can_use_persistent_terminal() is True

    def test_cannot_use_when_terminal_is_none(
        self, executor_no_terminal: ProcessExecutor
    ) -> None:
        """Test cannot use persistent terminal when it's None."""
        assert executor_no_terminal.can_use_persistent_terminal() is False

    def test_cannot_use_when_disabled_in_config(
        self,
        executor: ProcessExecutor,
        mock_config: MagicMock,
    ) -> None:
        """Test cannot use when PERSISTENT_TERMINAL_ENABLED is False."""
        mock_config.PERSISTENT_TERMINAL_ENABLED = False
        assert executor.can_use_persistent_terminal() is False

    def test_cannot_use_when_use_flag_false(
        self,
        executor: ProcessExecutor,
        mock_config: MagicMock,
    ) -> None:
        """Test cannot use when USE_PERSISTENT_TERMINAL is False."""
        mock_config.USE_PERSISTENT_TERMINAL = False
        assert executor.can_use_persistent_terminal() is False

    def test_cannot_use_when_fallback_mode(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
    ) -> None:
        """Test cannot use when terminal is in fallback mode."""
        mock_terminal._fallback_mode = True
        assert executor.can_use_persistent_terminal() is False


class TestPersistentTerminalExecution:
    """Tests for persistent terminal execution."""

    def test_successful_execution(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
    ) -> None:
        """Test successful command execution in persistent terminal."""
        result = executor.execute_in_persistent_terminal("nuke", "nuke")

        assert result is True
        assert mock_terminal.send_command_async_called is True
        assert mock_terminal.last_command == "nuke"

    def test_returns_false_when_terminal_unavailable(
        self, executor_no_terminal: ProcessExecutor
    ) -> None:
        """Test returns False when persistent terminal unavailable."""
        result = executor_no_terminal.execute_in_persistent_terminal("nuke", "nuke")

        assert result is False

    def test_returns_false_when_fallback_mode(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
    ) -> None:
        """Test returns False when terminal in fallback mode."""
        mock_terminal._fallback_mode = True

        result = executor.execute_in_persistent_terminal("nuke", "nuke")

        assert result is False
        assert mock_terminal.send_command_async_called is False


class TestNewTerminalExecution:
    """Tests for new terminal window execution."""

    @patch("subprocess.Popen")
    @patch("PySide6.QtCore.QTimer.singleShot")
    def test_gnome_terminal_execution(
        self,
        mock_single_shot: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test execution in gnome-terminal."""
        mock_process = MagicMock()  # No spec needed when Popen is already mocked
        mock_popen.return_value = mock_process

        result = executor.execute_in_new_terminal("nuke", "nuke", "gnome-terminal")

        assert result is True
        mock_popen.assert_called_once_with(
            ["gnome-terminal", "--", "bash", "-ilc", "nuke"]
        )
        # Verify process verification was scheduled
        mock_single_shot.assert_called_once()
        assert mock_single_shot.call_args[0][0] == 100  # 100ms delay

    @patch("subprocess.Popen")
    @patch("PySide6.QtCore.QTimer.singleShot")
    def test_konsole_execution(
        self,
        mock_single_shot: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test execution in konsole."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        result = executor.execute_in_new_terminal("maya", "maya", "konsole")

        assert result is True
        mock_popen.assert_called_once_with(["konsole", "-e", "bash", "-ilc", "maya"])

    @patch("subprocess.Popen")
    @patch("PySide6.QtCore.QTimer.singleShot")
    def test_xterm_execution(
        self,
        mock_single_shot: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test execution in xterm."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        result = executor.execute_in_new_terminal("3de", "3de", "xterm")

        assert result is True
        mock_popen.assert_called_once_with(["xterm", "-e", "bash", "-ilc", "3de"])

    @patch("subprocess.Popen")
    @patch("PySide6.QtCore.QTimer.singleShot")
    def test_fallback_execution(
        self,
        mock_single_shot: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test fallback to direct bash execution."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        result = executor.execute_in_new_terminal("unknown", "unknown", "unknown-term")

        assert result is True
        mock_popen.assert_called_once_with(["/bin/bash", "-ilc", "unknown"])


class TestProcessVerification:
    """Tests for process spawn verification."""

    @patch("launch.process_executor.NotificationManager.error")
    def test_process_crashed_immediately(
        self,
        mock_notification: MagicMock,
        executor: ProcessExecutor,
        qtbot: QtBot,
    ) -> None:
        """Test detection of immediate process crash."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 1  # Non-None = process exited

        # Use wait_signal instead of signal_blocker
        with (
            qtbot.waitSignal(executor.execution_error, timeout=1000),
            qtbot.waitSignal(executor.execution_completed, timeout=1000),
        ):
            # Call verification
            executor._verify_spawn(mock_process, "nuke")

        # Verify notification was shown
        mock_notification.assert_called_once()

    def test_process_spawned_successfully(
        self, executor: ProcessExecutor, qtbot: QtBot
    ) -> None:
        """Test successful process spawn detection."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # None = process still running
        mock_process.pid = 12345

        # Use wait_signal instead of signal_blocker
        with qtbot.waitSignal(executor.execution_progress, timeout=1000):
            # Call verification
            executor._verify_spawn(mock_process, "nuke")


class TestSignalHandling:
    """Tests for signal handling and forwarding."""

    def test_terminal_progress_forwarding(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
        qtbot: QtBot,
    ) -> None:
        """Test that terminal progress signals are forwarded."""
        # Use wait_signal to verify signal emission
        with qtbot.waitSignal(executor.execution_progress, timeout=1000):
            # Emit signal from mock terminal
            mock_terminal.operation_progress.emit("send_command", "Sending...")

    def test_terminal_success_result(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
        qtbot: QtBot,
    ) -> None:
        """Test handling of successful terminal command result."""
        # Use wait_signal to verify signal emission
        with qtbot.waitSignal(executor.execution_completed, timeout=1000):
            # Emit success result
            mock_terminal.command_result.emit(True, "")

    def test_terminal_failure_result(
        self,
        executor: ProcessExecutor,
        mock_terminal: MockPersistentTerminalManager,
        qtbot: QtBot,
    ) -> None:
        """Test handling of failed terminal command result."""
        # Use wait_signal for both signals
        with (
            qtbot.waitSignal(executor.execution_completed, timeout=1000),
            qtbot.waitSignal(executor.execution_error, timeout=1000),
        ):
            # Emit failure result
            mock_terminal.command_result.emit(False, "Command failed")


