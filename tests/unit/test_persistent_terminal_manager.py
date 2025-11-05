"""Unit tests for PersistentTerminalManager following UNIFIED_TESTING_GUIDE."""

from __future__ import annotations

# Standard library imports
import errno
import os
import stat
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock, patch

# Third-party imports
import pytest


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

# Local application imports
from persistent_terminal_manager import PersistentTerminalManager


pytestmark = [pytest.mark.unit, pytest.mark.qt, pytest.mark.xdist_group("qt_state")]

# Following UNIFIED_TESTING_GUIDE principles:
# - Test behavior, not implementation
# - Mock only at system boundaries (os, subprocess)
# - Use real Qt components with qtbot


class TestPersistentTerminalManager:
    """Test persistent terminal manager functionality."""

    @pytest.fixture
    def temp_fifo(self, tmp_path: Path) -> str:
        """Create a temporary FIFO path for testing."""
        fifo_path = tmp_path / "test_commands.fifo"
        return str(fifo_path)

    @pytest.fixture
    def temp_dispatcher(self, tmp_path: Path) -> str:
        """Create a temporary dispatcher script."""
        dispatcher = tmp_path / "test_dispatcher.sh"
        dispatcher.write_text("#!/bin/bash\necho 'Test dispatcher'")
        dispatcher.chmod(0o755)
        return str(dispatcher)

    @pytest.fixture
    def terminal_manager(
        self, temp_fifo: str, temp_dispatcher: str
    ) -> Generator[PersistentTerminalManager, None, None]:
        """Create terminal manager with test paths."""
        # Mock only system boundaries
        # Use a more nuanced exists check: False for FIFO, True for dispatcher
        def mock_exists(path: str) -> bool:
            """Mock exists to return False for FIFO, True for dispatcher."""
            if path == temp_fifo:
                return False  # FIFO doesn't exist yet
            return path == temp_dispatcher  # Dispatcher exists (created by fixture)

        with (
            patch("os.path.exists", side_effect=mock_exists),
            patch("os.mkfifo") as mock_mkfifo,
            patch("os.stat") as mock_stat,
        ):
            # Simulate successful FIFO creation
            mock_mkfifo.return_value = None
            mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

            manager = PersistentTerminalManager(
                fifo_path=temp_fifo, dispatcher_path=temp_dispatcher
            )
            # Note: PersistentTerminalManager is QObject, not QWidget - no qtbot.addWidget needed

            yield manager

    def test_initialization(
        self,
        terminal_manager: PersistentTerminalManager,
        temp_fifo: str,
        temp_dispatcher: str,
    ) -> None:
        """Test manager initializes with correct paths."""
        # Test BEHAVIOR: manager sets up correct paths
        assert terminal_manager.fifo_path == temp_fifo
        assert terminal_manager.dispatcher_path == temp_dispatcher
        assert terminal_manager.terminal_pid is None
        assert terminal_manager.terminal_process is None

    @patch("pathlib.Path.exists")
    @patch("os.mkfifo")
    @patch("pathlib.Path.stat")
    def test_ensure_fifo_creates_when_missing(
        self, mock_stat: MagicMock, mock_mkfifo: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test FIFO creation when it doesn't exist."""
        # Arrange: FIFO doesn't exist initially, then exists after creation
        mock_exists.side_effect = [False, True]  # Not exists, then exists
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Act: Create manager (which ensures FIFO)
        _ = PersistentTerminalManager(fifo_path="/tmp/test.fifo")

        # Assert: FIFO was created with correct permissions
        mock_mkfifo.assert_called_once_with("/tmp/test.fifo", 0o600)

    @patch("os.path.exists", return_value=True)
    @patch("os.stat")
    def test_ensure_fifo_validates_existing_fifo(
        self, mock_stat: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test FIFO validation for existing path."""
        # Arrange: Path exists but is not a FIFO
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFREG | 0o600)  # Regular file

        # Act: Create manager
        manager = PersistentTerminalManager(fifo_path="/tmp/not_a_fifo")

        # Assert: Manager detected invalid FIFO (check internal state)
        # This tests BEHAVIOR - the manager should handle invalid FIFOs gracefully
        assert manager.fifo_path == "/tmp/not_a_fifo"  # Still initialized

    def test_is_terminal_alive_with_no_pid(
        self, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test terminal alive check when no PID set."""
        # Test BEHAVIOR: no terminal running when PID is None
        assert terminal_manager._is_terminal_alive() is False

    @patch("os.kill")
    def test_is_terminal_alive_with_valid_pid(
        self, mock_kill: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test terminal alive check with valid process."""
        # Arrange: Set a PID
        terminal_manager.terminal_pid = 12345
        mock_kill.return_value = None  # Process exists

        # Act: Check if alive
        result = terminal_manager._is_terminal_alive()

        # Assert: Process check was performed correctly
        assert result is True
        mock_kill.assert_called_once_with(12345, 0)  # Signal 0 = check existence

    @patch("os.kill")
    def test_is_terminal_alive_with_dead_pid(
        self, mock_kill: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test terminal alive check with dead process."""
        # Arrange: Set a PID that doesn't exist
        terminal_manager.terminal_pid = 99999
        mock_kill.side_effect = ProcessLookupError()

        # Act: Check if alive
        result = terminal_manager._is_terminal_alive()

        # Assert: Dead process detected and cleaned up
        assert result is False
        assert terminal_manager.terminal_pid is None
        assert terminal_manager.terminal_process is None

    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_launch_terminal_success(
        self,
        mock_sleep: MagicMock,
        mock_popen: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test successful terminal launch."""
        # Arrange: Mock successful process launch
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        # Mock terminal alive check
        with patch.object(terminal_manager, "_is_terminal_alive", return_value=True):
            # Act: Launch terminal
            result = terminal_manager._launch_terminal()

        # Assert: Terminal launched successfully
        assert result is True
        assert terminal_manager.terminal_pid == 12345
        assert terminal_manager.terminal_process == mock_process

    @patch("subprocess.Popen")
    def test_launch_terminal_tries_multiple_emulators(
        self, mock_popen: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test fallback to different terminal emulators."""
        # Arrange: First two emulators fail, third succeeds
        mock_popen.side_effect = [
            FileNotFoundError(),  # gnome-terminal not found
            FileNotFoundError(),  # konsole not found
            MagicMock(pid=54321),  # xterm works
        ]

        with patch.object(terminal_manager, "_is_terminal_alive", return_value=True):
            # Act: Launch terminal
            result = terminal_manager._launch_terminal()

        # Assert: Terminal launched with fallback
        assert result is True
        assert terminal_manager.terminal_pid == 54321
        assert mock_popen.call_count == 3  # Tried 3 emulators

    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_launch_terminal_uses_interactive_bash(
        self,
        mock_sleep: MagicMock,
        mock_popen: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test that terminal launches bash in interactive mode for shell functions."""
        # Arrange: Mock successful process launch
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        with patch.object(terminal_manager, "_is_terminal_alive", return_value=True):
            # Act: Launch terminal
            result = terminal_manager._launch_terminal()

        # Assert: Terminal launched successfully
        assert result is True

        # Verify bash was invoked with -i flag for interactive mode
        # This ensures shell functions (like 'ws') are loaded from .bashrc
        call_args = mock_popen.call_args[0][0]  # Get first call's args

        # Find bash and -i in the command list
        bash_index = None
        for i, arg in enumerate(call_args):
            if arg == "bash":
                bash_index = i
                break

        assert bash_index is not None, "bash not found in command"
        assert "-i" in call_args[bash_index:], (
            "bash -i flag missing for interactive mode"
        )

    @patch("os.open")
    @patch("os.fdopen")
    def test_send_command_success(
        self,
        mock_fdopen: MagicMock,
        mock_open: MagicMock,
        terminal_manager: PersistentTerminalManager,
        qtbot: QtBot,
    ) -> None:
        """Test successful command sending."""
        # Arrange: Mock FIFO operations
        mock_fd = 42
        mock_open.return_value = mock_fd
        mock_file = MagicMock()
        mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
        mock_fdopen.return_value.__exit__ = Mock(return_value=False)

        # Track signal emission
        signal_spy: list[str] = []
        terminal_manager.command_sent.connect(signal_spy.append)

        with (
            patch.object(terminal_manager, "_is_terminal_alive", return_value=True),
            patch("os.path.exists", return_value=True),
        ):
            # Act: Send command
            result = terminal_manager.send_command("echo test")

        # Assert: Command sent successfully
        assert result is True
        # Implementation now uses binary mode with two write calls (command + newline)
        assert mock_file.write.call_count == 2
        mock_file.write.assert_any_call(b"echo test")
        mock_file.write.assert_any_call(b"\n")
        # No flush in unbuffered mode
        assert len(signal_spy) == 1
        assert signal_spy[0] == "echo test"

    @patch("os.open")
    @patch("time.sleep")
    @patch("os.path.exists", return_value=True)
    def test_send_command_with_auto_restart(
        self,
        mock_exists: MagicMock,
        mock_sleep: MagicMock,
        mock_open: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test command sending with terminal auto-restart."""

        # Arrange: Mock open to succeed
        mock_open.return_value = 42

        # Mock dispatcher state: False initially (triggers restart), True after restart
        dispatcher_calls = [False, True]

        def dispatcher_side_effect() -> bool:
            if dispatcher_calls:
                return dispatcher_calls.pop(0)
            return True

        # Mock restart succeeding
        with (
            patch.object(
                terminal_manager, "restart_terminal", return_value=True
            ) as mock_restart,
            patch.object(terminal_manager, "_is_terminal_alive", return_value=True),
            patch.object(
                terminal_manager,
                "_is_dispatcher_running",
                side_effect=dispatcher_side_effect,
            ),
            patch("os.fdopen") as mock_fdopen,
        ):
            mock_file = MagicMock()
            mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
            mock_fdopen.return_value.__exit__ = Mock(return_value=False)

            # Act: Send command with ensure_terminal=True
            # New behavior: Detects dispatcher dead before write, restarts preemptively
            result = terminal_manager.send_command("test command", ensure_terminal=True)

        # Assert: Terminal was restarted and command sent
        assert result is True
        mock_restart.assert_called_once()
        # Implementation now uses binary mode with two write calls
        assert mock_file.write.call_count == 2
        mock_file.write.assert_any_call(b"test command")
        mock_file.write.assert_any_call(b"\n")

    @patch("os.open")
    def test_send_command_handles_missing_fifo(
        self, mock_open: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test command sending when FIFO disappears."""
        # Arrange: FIFO doesn't exist
        mock_open.side_effect = OSError(errno.ENOENT, "File not found")

        with (
            patch("os.path.exists", return_value=False),
            patch.object(
                terminal_manager, "_ensure_fifo", return_value=True
            ) as mock_ensure,
        ):
            # Act: Send command
            _ = terminal_manager.send_command("test", ensure_terminal=False)

        # Assert: Tried to recreate FIFO
        mock_ensure.assert_called()

    def test_clear_terminal(self, terminal_manager: PersistentTerminalManager) -> None:
        """Test terminal clearing command."""
        with patch.object(terminal_manager, "send_command") as mock_send:
            # Act: Clear terminal
            _ = terminal_manager.clear_terminal()

        # Assert: Clear command sent
        mock_send.assert_called_once_with("CLEAR_TERMINAL", ensure_terminal=False)

    @patch("os.kill")
    @patch("time.sleep")
    def test_close_terminal(
        self,
        mock_sleep: MagicMock,
        mock_kill: MagicMock,
        terminal_manager: PersistentTerminalManager,
        qtbot: QtBot,
    ) -> None:
        """Test terminal closing."""
        # Arrange: Terminal is running
        terminal_manager.terminal_pid = 12345

        # Track signal emission
        signal_spy: list[bool] = []
        terminal_manager.terminal_closed.connect(lambda: signal_spy.append(True))

        with (
            patch.object(
                terminal_manager, "_is_terminal_alive", side_effect=[True, False]
            ),
            patch.object(terminal_manager, "send_command"),
        ):
            # Act: Close terminal
            result = terminal_manager.close_terminal()

        # Assert: Terminal terminated
        assert result is True
        assert terminal_manager.terminal_pid is None
        assert terminal_manager.terminal_process is None
        mock_kill.assert_called_with(12345, 15)  # SIGTERM = 15
        assert len(signal_spy) == 1  # terminal_closed signal emitted

    @patch("time.sleep")
    def test_restart_terminal(
        self, mock_sleep: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test terminal restart with FIFO cleanup."""
        with (
            patch.object(terminal_manager, "close_terminal") as mock_close,
            patch.object(
                terminal_manager, "_launch_terminal", return_value=True
            ) as mock_launch,
            patch.object(
                terminal_manager, "_ensure_fifo", return_value=True
            ) as mock_ensure_fifo,
            patch.object(
                terminal_manager, "_is_dispatcher_running", return_value=True
            ),
            patch("os.path.exists", return_value=True),
            patch("os.unlink") as mock_unlink,
        ):
            # Act: Restart terminal
            result = terminal_manager.restart_terminal()

        # Assert: Terminal closed and relaunched with FIFO cleanup
        assert result is True
        mock_close.assert_called_once()
        mock_unlink.assert_called_once()  # FIFO should be cleaned up
        mock_ensure_fifo.assert_called_once()  # FIFO should be recreated
        mock_launch.assert_called_once()

    @patch("os.path.exists", return_value=True)
    @patch("os.unlink")
    def test_cleanup_removes_fifo_and_closes_terminal(
        self,
        mock_unlink: MagicMock,
        mock_exists: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test full cleanup."""
        with (
            patch.object(terminal_manager, "_is_terminal_alive", return_value=True),
            patch.object(terminal_manager, "close_terminal") as mock_close,
        ):
            # Act: Cleanup
            terminal_manager.cleanup()

        # Assert: Terminal closed and FIFO removed
        mock_close.assert_called_once()
        # Path.unlink() passes Path object to os.unlink (not string)
        mock_unlink.assert_called_once()
        assert str(mock_unlink.call_args[0][0]) == str(terminal_manager.fifo_path)

    @patch("os.path.exists", return_value=True)
    @patch("os.unlink")
    def test_cleanup_fifo_only(
        self,
        mock_unlink: MagicMock,
        mock_exists: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test FIFO-only cleanup (keeps terminal open)."""
        with patch.object(terminal_manager, "close_terminal") as mock_close:
            # Act: Cleanup FIFO only
            terminal_manager.cleanup_fifo_only()

        # Assert: FIFO removed but terminal NOT closed
        # Path.unlink() passes Path object to os.unlink (not string)
        mock_unlink.assert_called_once()
        assert str(mock_unlink.call_args[0][0]) == str(terminal_manager.fifo_path)
        mock_close.assert_not_called()


    @patch("os.open")
    def test_is_dispatcher_running_checks_fifo_reader(
        self, mock_open: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test dispatcher running check uses non-blocking FIFO open."""
        # Arrange: Mock successful non-blocking open (reader is present)
        mock_fd = 42
        mock_open.return_value = mock_fd

        with (
            patch("os.path.exists", return_value=True),
            patch("os.close") as mock_close,
        ):
            # Act: Check if dispatcher is running
            result = terminal_manager._is_dispatcher_running()

        # Assert: Non-blocking FIFO open was attempted
        assert result is True
        mock_open.assert_called_once()
        call_args = mock_open.call_args
        assert call_args[0][0] == terminal_manager.fifo_path
        # Verify O_WRONLY | O_NONBLOCK flags were used
        assert call_args[0][1] & os.O_WRONLY
        assert call_args[0][1] & os.O_NONBLOCK
        mock_close.assert_called_once_with(mock_fd)

    @patch("os.open")
    def test_is_dispatcher_running_detects_no_reader(
        self, mock_open: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test dispatcher running check detects missing reader (ENXIO)."""
        # Arrange: Mock ENXIO error (no reader on FIFO)
        mock_open.side_effect = OSError(errno.ENXIO, "No such device or address")

        with patch("os.path.exists", return_value=True):
            # Act: Check if dispatcher is running
            result = terminal_manager._is_dispatcher_running()

        # Assert: Correctly detected no reader
        assert result is False

    @patch("os.open")
    @patch("os.fdopen")
    @patch("time.sleep")
    def test_rapid_successive_commands_no_restart(
        self,
        mock_sleep: MagicMock,
        mock_fdopen: MagicMock,
        mock_open: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test rapid successive commands don't trigger terminal restart.

        This tests the fix for the race condition where the dispatcher hasn't
        reopened the FIFO between loop iterations, causing _is_dispatcher_running()
        to fail and trigger an unnecessary restart.

        With persistent file descriptor (exec 3< "$FIFO"), the dispatcher always
        has a reader open, eliminating the race window.
        """
        # Arrange: Mock FIFO operations to succeed
        mock_fd = 42
        mock_open.return_value = mock_fd
        mock_file = MagicMock()
        mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
        mock_fdopen.return_value.__exit__ = Mock(return_value=False)

        # Track restart calls - should NOT be called
        restart_count = 0

        def mock_restart() -> bool:
            nonlocal restart_count
            restart_count += 1
            return True

        with (
            patch.object(terminal_manager, "_is_terminal_alive", return_value=True),
            patch.object(terminal_manager, "_is_dispatcher_running", return_value=True),
            patch.object(terminal_manager, "restart_terminal", side_effect=mock_restart),
            patch("os.path.exists", return_value=True),
        ):
            # Act: Send two commands in rapid succession (simulating button double-click)
            result1 = terminal_manager.send_command("command1", ensure_terminal=True)
            result2 = terminal_manager.send_command("command2", ensure_terminal=True)

        # Assert: Both commands succeeded without restart
        assert result1 is True
        assert result2 is True
        assert restart_count == 0, (
            "Terminal should not restart on rapid successive commands "
            "(persistent FD eliminates race window)"
        )
        # Verify both commands were written
        assert mock_file.write.call_count == 4  # 2 commands x 2 writes each (cmd + newline)

    @patch("os.open")
    @patch("time.sleep")
    def test_dispatcher_dead_terminal_alive_triggers_restart(
        self,
        mock_sleep: MagicMock,
        mock_open: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test that dead dispatcher with alive terminal triggers force restart.

        This should NOT happen with persistent FD fix, but we test the fallback
        behavior in case the dispatcher crashes for other reasons.
        """
        # Arrange: Terminal is alive but dispatcher is not running
        mock_open.side_effect = OSError(errno.ENXIO, "No reader")

        with (
            patch.object(terminal_manager, "_is_terminal_alive", return_value=True),
            patch("os.path.exists", return_value=True),
            patch.object(
                terminal_manager, "restart_terminal", return_value=True
            ) as mock_restart,
            patch("os.kill") as mock_kill,
            patch("os.fdopen") as mock_fdopen,
        ):
            terminal_manager.terminal_pid = 12345

            # Setup mock for successful command send after restart
            mock_file = MagicMock()
            mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
            mock_fdopen.return_value.__exit__ = Mock(return_value=False)

            # Reset mock_open for second attempt after restart
            mock_open.side_effect = [
                OSError(errno.ENXIO, "No reader"),  # First check fails
                42,  # After restart, FIFO open succeeds
            ]

            # Act: Try to send command with ensure_terminal=True
            result = terminal_manager.send_command("test", ensure_terminal=True)

        # Assert: Terminal was force-killed and restarted
        assert result is True
        mock_kill.assert_called_once_with(12345, 9)  # SIGKILL
        mock_restart.assert_called_once()


class TestPersistentTerminalIntegration:
    """Integration tests for persistent terminal with Qt event loop."""

    @pytest.mark.qt
    def test_terminal_signals_with_qt_event_loop(self, qtbot: QtBot) -> None:
        """Test Qt signals work correctly with event loop."""
        # Create real manager with temp paths
        with tempfile.TemporaryDirectory() as tmpdir:
            fifo_path = Path(tmpdir) / "test.fifo"
            dispatcher_path = Path(tmpdir) / "dispatcher.sh"
            dispatcher_path.write_text("#!/bin/bash\necho test")
            dispatcher_path.chmod(0o755)

            # Don't actually create FIFO to avoid system calls
            with (
                patch("os.mkfifo"),
                patch("os.path.exists", return_value=True),
                patch("os.stat") as mock_stat,
            ):
                mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)
                manager = PersistentTerminalManager(
                    fifo_path=str(fifo_path), dispatcher_path=str(dispatcher_path)
                )
                # Note: PersistentTerminalManager is QObject, not QWidget - no qtbot.addWidget needed

                # Test signal emission with Qt event loop
                with patch.object(manager, "_launch_terminal", return_value=True):
                    manager.terminal_pid = 12345

                    # Use qtbot to wait for signal
                    with qtbot.waitSignal(manager.terminal_started, timeout=100):
                        manager.terminal_started.emit(12345)

                    # Test command_sent signal
                    with qtbot.waitSignal(manager.command_sent, timeout=100) as blocker:
                        manager.command_sent.emit("test command")

                    assert blocker.args[0] == "test command"
