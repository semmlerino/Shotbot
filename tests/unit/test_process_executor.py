"""Tests for ProcessExecutor component.

This test suite provides comprehensive coverage of process execution:
- New terminal window launching
- Process verification
- Signal emission and handling
- GUI app detection
"""

import pytest
from pytestqt.qtbot import QtBot


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from config import Config
from launch.process_executor import ProcessExecutor


@pytest.fixture
def mock_config(mocker):
    """Create a mock Config object."""
    return mocker.MagicMock(spec=Config)


@pytest.fixture
def executor(mock_config) -> ProcessExecutor:
    """Create a ProcessExecutor with mocked dependencies."""
    return ProcessExecutor(mock_config)


class TestGuiAppDetection:
    """Tests for GUI application detection."""

    @pytest.mark.parametrize("app_name", ["nuke", "maya", "3de", "rv"])
    def test_known_gui_apps(self, executor: ProcessExecutor, app_name: str) -> None:
        """Test that known DCC apps are detected as GUI apps."""
        assert executor.is_gui_app(app_name) is True

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
            (
                "x-terminal-emulator",
                ["x-terminal-emulator", "-e", "/bin/bash", "-ilc", "cmd"],
            ),
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

    @pytest.mark.parametrize(
        ("terminal", "app_name", "cmd", "expected_popen_args"),
        [
            (
                "gnome-terminal",
                "nuke",
                "nuke",
                ["gnome-terminal", "--", "/bin/bash", "-ilc", "nuke"],
            ),
            (
                "konsole",
                "maya",
                "maya",
                ["konsole", "-e", "/bin/bash", "-ilc", "maya"],
            ),
            (
                "xterm",
                "3de",
                "3de",
                ["xterm", "-e", "/bin/bash", "-ilc", "3de"],
            ),
        ],
    )
    def test_terminal_execution(
        self,
        fp,
        mocker,
        executor: ProcessExecutor,
        terminal: str,
        app_name: str,
        cmd: str,
        expected_popen_args: list[str],
    ) -> None:
        """Test execution in supported terminal emulators."""
        mock_timer_class = mocker.patch("launch.process_executor.QTimer")
        mock_timer = mocker.MagicMock()
        mock_timer_class.return_value = mock_timer
        fp.register(expected_popen_args)

        result = executor.execute_in_new_terminal(cmd, app_name, terminal)

        assert result is not None  # Result is FakePopen from pytest-subprocess
        assert list(fp.calls[0]) == expected_popen_args

    def test_timer_setup_on_success(
        self,
        fp,
        mocker,
        executor: ProcessExecutor,
    ) -> None:
        """Test that process verification timer is created and started on success."""
        mock_timer_class = mocker.patch("launch.process_executor.QTimer")
        mock_timer = mocker.MagicMock()
        mock_timer_class.return_value = mock_timer
        fp.register(["gnome-terminal", "--", "/bin/bash", "-ilc", "nuke"])

        executor.execute_in_new_terminal("nuke", "nuke", "gnome-terminal")

        mock_timer.setSingleShot.assert_called_once_with(True)
        mock_timer.setInterval.assert_called_once_with(100)
        mock_timer.start.assert_called_once()

    @pytest.mark.allow_dialogs  # May show warning dialog
    @pytest.mark.usefixtures("suppress_qmessagebox")
    def test_headless_execution_when_terminal_is_none(
        self,
        fp,
        mocker,
        executor: ProcessExecutor,
    ) -> None:
        """Test headless mode when terminal is None (no terminal available)."""
        mock_timer_class = mocker.patch("launch.process_executor.QTimer")
        mock_timer = mocker.MagicMock()
        mock_timer_class.return_value = mock_timer
        fp.register(["/bin/bash", "-ilc", "echo test"])

        # Pass None for terminal to trigger headless mode
        result = executor.execute_in_new_terminal("echo test", "test_app", None)

        assert result is not None  # Result is FakePopen from pytest-subprocess
        assert list(fp.calls[0]) == ["/bin/bash", "-ilc", "echo test"]

    def test_fallback_execution_for_unknown_terminal(
        self,
        fp,
        mocker,
        executor: ProcessExecutor,
    ) -> None:
        """Test fallback to direct bash execution for unknown terminal."""
        mock_timer_class = mocker.patch("launch.process_executor.QTimer")
        mock_timer = mocker.MagicMock()
        mock_timer_class.return_value = mock_timer
        fp.register(["/bin/bash", "-ilc", "unknown"])

        result = executor.execute_in_new_terminal("unknown", "unknown", "unknown-term")

        assert result is not None  # Result is FakePopen from pytest-subprocess
        assert list(fp.calls[0]) == ["/bin/bash", "-ilc", "unknown"]

    @pytest.mark.parametrize(
        ("exc_type", "exc_msg"),
        [
            (FileNotFoundError, "gnome-terminal not found"),
            (PermissionError, "Permission denied"),
            (OSError, "OS error"),
        ],
    )
    def test_returns_none_on_popen_error(
        self,
        mocker,
        executor: ProcessExecutor,
        exc_type: type[Exception],
        exc_msg: str,
    ) -> None:
        """Test that FileNotFoundError, PermissionError, and OSError all return None."""
        mock_popen = mocker.patch("subprocess.Popen")
        mock_popen.side_effect = exc_type(exc_msg)

        result = executor.execute_in_new_terminal("cmd", "app", "gnome-terminal")

        assert result is None


class TestProcessVerification:
    """Tests for process spawn verification."""

    def test_process_crashed_immediately(
        self,
        executor: ProcessExecutor,
        qtbot: QtBot,
        mocker,
    ) -> None:
        """Test detection of immediate process crash."""
        mock_process = mocker.MagicMock()
        mock_process.poll.return_value = 1  # Non-None = process exited

        # Use wait_signal instead of signal_blocker
        with (
            qtbot.waitSignal(executor.execution_error, timeout=1000),
            qtbot.waitSignal(executor.execution_completed, timeout=1000),
            qtbot.waitSignal(executor.launch_crash_detected, timeout=1000),
        ):
            # Call verification
            executor.verify_spawn(mock_process, "nuke")

    def test_process_spawned_successfully(
        self, executor: ProcessExecutor, qtbot: QtBot, mocker
    ) -> None:
        """Test successful process spawn detection."""
        mock_process = mocker.MagicMock()
        mock_process.poll.return_value = None  # None = process still running
        mock_process.pid = 12345

        # Use wait_signal instead of signal_blocker
        with qtbot.waitSignal(executor.execution_progress, timeout=1000) as blocker:
            # Call verification
            executor.verify_spawn(mock_process, "nuke")

        # Verify signal was emitted successfully
        assert blocker.signal_triggered, "execution_progress signal should be emitted"
        # Signal was emitted, indicating verify_spawn completed without error
        assert blocker.args is not None, (
            "Signal should have been emitted with arguments"
        )
