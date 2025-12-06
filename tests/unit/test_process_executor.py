"""Tests for ProcessExecutor component.

This test suite provides comprehensive coverage of process execution:
- New terminal window launching
- Process verification
- Signal emission and handling
- GUI app detection
"""

from unittest.mock import MagicMock, patch

import pytest
from pytestqt.qtbot import QtBot


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from config import Config
from launch.process_executor import ProcessExecutor


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config object."""
    return MagicMock(spec=Config)


@pytest.fixture
def executor(mock_config: MagicMock) -> ProcessExecutor:
    """Create a ProcessExecutor with mocked dependencies."""
    return ProcessExecutor(mock_config)


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


class TestBuildTerminalCommand:
    """Tests for _build_terminal_command helper method."""

    @pytest.mark.parametrize(
        ("terminal", "expected_cmd"),
        [
            # Now uses /bin/bash for explicit path
            ("gnome-terminal", ["gnome-terminal", "--", "/bin/bash", "-ilc", "cmd"]),
            ("konsole", ["konsole", "-e", "/bin/bash", "-ilc", "cmd"]),
            ("kitty", ["kitty", "/bin/bash", "-ilc", "cmd"]),
            ("xterm", ["xterm", "-e", "/bin/bash", "-ilc", "cmd"]),
            ("x-terminal-emulator", ["x-terminal-emulator", "-e", "/bin/bash", "-ilc", "cmd"]),
            ("xfce4-terminal", ["xfce4-terminal", "-e", "/bin/bash", "-ilc", "cmd"]),
            ("mate-terminal", ["mate-terminal", "-e", "/bin/bash", "-ilc", "cmd"]),
            ("alacritty", ["alacritty", "-e", "/bin/bash", "-ilc", "cmd"]),
            ("terminology", ["terminology", "-e", "/bin/bash", "-ilc", "cmd"]),
            (None, ["/bin/bash", "-ilc", "cmd"]),  # Headless fallback
            ("unknown-terminal", ["/bin/bash", "-ilc", "cmd"]),  # Unknown fallback
        ],
    )
    def test_build_terminal_command(
        self, executor: ProcessExecutor, terminal: str | None, expected_cmd: list[str]
    ) -> None:
        """Test that terminal commands are built correctly for all supported terminals."""
        result = executor._build_terminal_command(terminal, "cmd")
        assert result == expected_cmd


class TestNewTerminalExecution:
    """Tests for new terminal window execution."""

    @patch("subprocess.Popen")
    @patch("launch.process_executor.QTimer")
    def test_gnome_terminal_execution(
        self,
        mock_timer_class: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test execution in gnome-terminal."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_timer = MagicMock()
        mock_timer_class.return_value = mock_timer

        result = executor.execute_in_new_terminal("nuke", "nuke", "gnome-terminal")

        assert result is mock_process  # Returns Popen object on success
        mock_popen.assert_called_once_with(
            ["gnome-terminal", "--", "/bin/bash", "-ilc", "nuke"]
        )
        # Verify process verification timer was created and started
        mock_timer.setSingleShot.assert_called_once_with(True)
        mock_timer.setInterval.assert_called_once_with(100)
        mock_timer.start.assert_called_once()

    @patch("subprocess.Popen")
    @patch("launch.process_executor.QTimer")
    def test_konsole_execution(
        self,
        mock_timer_class: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test execution in konsole."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_timer = MagicMock()
        mock_timer_class.return_value = mock_timer

        result = executor.execute_in_new_terminal("maya", "maya", "konsole")

        assert result is mock_process
        mock_popen.assert_called_once_with(["konsole", "-e", "/bin/bash", "-ilc", "maya"])

    @patch("subprocess.Popen")
    @patch("launch.process_executor.QTimer")
    def test_xterm_execution(
        self,
        mock_timer_class: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test execution in xterm."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_timer = MagicMock()
        mock_timer_class.return_value = mock_timer

        result = executor.execute_in_new_terminal("3de", "3de", "xterm")

        assert result is mock_process
        mock_popen.assert_called_once_with(["xterm", "-e", "/bin/bash", "-ilc", "3de"])

    @pytest.mark.allow_dialogs  # May show warning dialog
    @patch("subprocess.Popen")
    @patch("launch.process_executor.QTimer")
    def test_headless_execution_when_terminal_is_none(
        self,
        mock_timer_class: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test headless mode when terminal is None (no terminal available)."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_timer = MagicMock()
        mock_timer_class.return_value = mock_timer

        # Pass None for terminal to trigger headless mode
        result = executor.execute_in_new_terminal("echo test", "test_app", None)

        assert result is mock_process
        mock_popen.assert_called_once_with(["/bin/bash", "-ilc", "echo test"])

    @patch("subprocess.Popen")
    @patch("launch.process_executor.QTimer")
    def test_fallback_execution_for_unknown_terminal(
        self,
        mock_timer_class: MagicMock,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test fallback to direct bash execution for unknown terminal."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_timer = MagicMock()
        mock_timer_class.return_value = mock_timer

        result = executor.execute_in_new_terminal("unknown", "unknown", "unknown-term")

        assert result is mock_process
        mock_popen.assert_called_once_with(["/bin/bash", "-ilc", "unknown"])

    @patch("subprocess.Popen")
    def test_returns_none_on_file_not_found(
        self,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test that FileNotFoundError returns None."""
        mock_popen.side_effect = FileNotFoundError("gnome-terminal not found")

        result = executor.execute_in_new_terminal("cmd", "app", "gnome-terminal")

        assert result is None

    @patch("subprocess.Popen")
    def test_returns_none_on_permission_error(
        self,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test that PermissionError returns None."""
        mock_popen.side_effect = PermissionError("Permission denied")

        result = executor.execute_in_new_terminal("cmd", "app", "gnome-terminal")

        assert result is None

    @patch("subprocess.Popen")
    def test_returns_none_on_os_error(
        self,
        mock_popen: MagicMock,
        executor: ProcessExecutor,
    ) -> None:
        """Test that OSError returns None."""
        mock_popen.side_effect = OSError("OS error")

        result = executor.execute_in_new_terminal("cmd", "app", "gnome-terminal")

        assert result is None


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
            executor.verify_spawn(mock_process, "nuke")

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
        with qtbot.waitSignal(executor.execution_progress, timeout=1000) as blocker:
            # Call verification
            executor.verify_spawn(mock_process, "nuke")

        # Verify signal was emitted successfully
        assert blocker.signal_triggered, "execution_progress signal should be emitted"
        # Signal was emitted, indicating verify_spawn completed without error
        assert blocker.args is not None, "Signal should have been emitted with arguments"

