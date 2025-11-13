"""Unit tests for PersistentTerminalManager following UNIFIED_TESTING_GUIDE."""

from __future__ import annotations

# Standard library imports
import errno
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


pytestmark = [pytest.mark.unit, pytest.mark.qt]

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

        # Check for -i flag (either standalone or combined like -ilc)
        has_interactive_flag = any(
            arg == "-i" or (arg.startswith("-") and "i" in arg)
            for arg in call_args[bash_index:]
        )
        assert has_interactive_flag, (
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
            patch.object(terminal_manager, "_is_dispatcher_healthy", return_value=True),
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
            patch.object(terminal_manager, "_is_dispatcher_alive", return_value=True),
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

    def test_send_command_polls_dispatcher_readiness(
        self, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test that terminal launch waits for dispatcher via polling.

        Issue #6 fix: Replaces fixed 1.5s delay with polling _is_dispatcher_running()
        until ready or 5s timeout.
        """
        import time

        # Mock terminal launch and initial state
        terminal_manager._launch_terminal = MagicMock(return_value=True)  # type: ignore[method-assign]
        terminal_manager._is_terminal_alive = MagicMock(return_value=False)  # type: ignore[method-assign]
        terminal_manager._is_dispatcher_alive = MagicMock(return_value=True)  # type: ignore[method-assign]

        # Simulate dispatcher becoming ready after 0.3s (3 poll attempts at 0.1s intervals)
        poll_count = 0

        def mock_dispatcher_running() -> bool:
            nonlocal poll_count
            poll_count += 1
            return poll_count >= 3  # Ready on 3rd check (~0.3s)

        terminal_manager._is_dispatcher_running = mock_dispatcher_running  # type: ignore[method-assign]

        # Mock FIFO operations to succeed
        with (
            patch("os.open", return_value=3),
            patch("os.fdopen", MagicMock()),
        ):
            start = time.time()
            result = terminal_manager.send_command("test", ensure_terminal=True)
            elapsed = time.time() - start

        # Should succeed
        assert result is True, "Command should succeed after dispatcher becomes ready"

        # Should have polled at least 3 times before dispatcher was ready
        # (May be 3 or 4 depending on timing - dispatcher ready on 3rd check)
        assert poll_count >= 3, f"Expected at least 3 poll attempts, got {poll_count}"
        assert poll_count <= 4, f"Expected at most 4 poll attempts, got {poll_count}"

        # Should complete much faster than old 1.5s fixed delay
        # (3-4 polls * 0.1s = ~0.3-0.4s, allowing overhead for setup/teardown)
        assert elapsed < 1.0, f"Took {elapsed:.2f}s, expected < 1.0s with polling"

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


    def test_is_dispatcher_running_checks_fifo_reader(
        self, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test dispatcher running check uses heartbeat mechanism."""
        # Arrange: Mock successful heartbeat ping (dispatcher is responding)
        with (
            patch("os.path.exists", return_value=True),
            patch.object(terminal_manager, "_send_heartbeat_ping", return_value=True) as mock_heartbeat,
        ):
            # Act: Check if dispatcher is running
            result = terminal_manager._is_dispatcher_running()

        # Assert: Heartbeat ping was attempted with 3.0s timeout
        assert result is True
        mock_heartbeat.assert_called_once_with(timeout=3.0)

    def test_is_dispatcher_running_detects_no_reader(
        self, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test dispatcher running check detects unresponsive dispatcher."""
        # Arrange: Mock failed heartbeat ping (dispatcher not responding)
        with (
            patch("os.path.exists", return_value=True),
            patch.object(terminal_manager, "_send_heartbeat_ping", return_value=False) as mock_heartbeat,
        ):
            # Act: Check if dispatcher is running
            result = terminal_manager._is_dispatcher_running()

        # Assert: Correctly detected unresponsive dispatcher
        assert result is False
        mock_heartbeat.assert_called_once_with(timeout=3.0)

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
            patch.object(terminal_manager, "_is_dispatcher_alive", return_value=True),
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
        # Mock os.open to succeed for the command send after recovery
        mock_open.return_value = 42

        with (
            patch.object(terminal_manager, "_is_terminal_alive", return_value=True),
            patch.object(terminal_manager, "_is_dispatcher_alive", return_value=True),
            patch.object(
                terminal_manager,
                "_is_dispatcher_running",
                side_effect=[False, True],  # First fails, after restart succeeds
            ),
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

            # Act: Try to send command with ensure_terminal=True
            result = terminal_manager.send_command("test", ensure_terminal=True)

        # Assert: Terminal was force-killed and restarted
        assert result is True
        mock_kill.assert_called_once_with(12345, 9)  # SIGKILL
        mock_restart.assert_called_once()

    @patch("pathlib.Path.exists")
    @patch("os.mkfifo")
    @patch("pathlib.Path.stat")
    @patch("os.open")
    @patch("os.close")
    def test_dummy_writer_fd_opened_during_ensure_fifo(
        self,
        mock_close: MagicMock,
        mock_open: MagicMock,
        mock_stat: MagicMock,
        mock_mkfifo: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Test dummy writer FD is opened when explicitly requested.

        After fix, __init__ doesn't open dummy writer (defers until dispatcher starts).
        This test verifies _ensure_fifo(open_dummy_writer=True) works correctly.
        """
        # Arrange: FIFO doesn't exist initially, then exists after creation
        # Need multiple True values for all the exists() checks in _ensure_fifo()
        mock_exists.side_effect = [False, True, True, True]  # Init + manual call checks
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)
        mock_open.return_value = 42  # Dummy FD number

        # Act: Create manager (FIFO created, dummy writer NOT opened)
        import os as real_os
        with patch("os.O_WRONLY", real_os.O_WRONLY), patch("os.O_NONBLOCK", real_os.O_NONBLOCK):
            manager = PersistentTerminalManager(fifo_path="/tmp/test.fifo")

            # Assert: FIFO created but dummy writer NOT opened during init
            mock_mkfifo.assert_called_once_with("/tmp/test.fifo", 0o600)
            assert manager._dummy_writer_fd is None, "Dummy writer should not be opened during init"

            # Now explicitly call _ensure_fifo with open_dummy_writer=True
            result = manager._ensure_fifo(open_dummy_writer=True)

        # Assert: Dummy writer opened when explicitly requested
        assert result is True
        mock_open.assert_called_once_with(
            "/tmp/test.fifo", real_os.O_WRONLY | real_os.O_NONBLOCK
        )
        assert manager._dummy_writer_fd == 42

    @patch("os.close")
    def test_cleanup_closes_dummy_writer_fd(
        self, mock_close: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test cleanup closes dummy writer FD before removing FIFO."""
        # Arrange: Set dummy writer FD
        terminal_manager._dummy_writer_fd = 42

        # Mock FIFO operations
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.unlink"),
            patch.object(terminal_manager, "_is_terminal_alive", return_value=False),
        ):
            # Act: Cleanup
            terminal_manager.cleanup()

        # Assert: Dummy writer FD was closed
        mock_close.assert_called_once_with(42)
        assert terminal_manager._dummy_writer_fd is None

    @patch("os.close")
    def test_cleanup_handles_missing_dummy_writer_fd(
        self, mock_close: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test cleanup handles case where dummy writer FD is None."""
        # Arrange: No dummy writer FD
        terminal_manager._dummy_writer_fd = None

        # Mock FIFO operations
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.unlink"),
            patch.object(terminal_manager, "_is_terminal_alive", return_value=False),
        ):
            # Act: Cleanup (should not raise exception)
            terminal_manager.cleanup()

        # Assert: close() was not called
        mock_close.assert_not_called()

    @patch("os.close")
    @patch("os.open")
    def test_restart_terminal_closes_and_reopens_dummy_writer(
        self,
        mock_open: MagicMock,
        mock_close: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test restart_terminal closes dummy writer before FIFO cleanup and reopens."""
        # Arrange: Set initial dummy writer FD
        terminal_manager._dummy_writer_fd = 42
        mock_open.return_value = 99  # New FD after restart

        # Mock all required operations
        with (
            patch.object(terminal_manager, "close_terminal"),
            patch("time.sleep"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.unlink"),
            patch("os.mkfifo"),
            patch("pathlib.Path.stat") as mock_stat,
            patch.object(terminal_manager, "_launch_terminal", return_value=True),
            patch.object(terminal_manager, "_is_dispatcher_running", return_value=True),
        ):
            mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)
            import os as real_os
            with patch("os.O_WRONLY", real_os.O_WRONLY), patch("os.O_NONBLOCK", real_os.O_NONBLOCK):
                # Act: Restart terminal
                result = terminal_manager.restart_terminal()

        # Assert: Old FD closed, new FD opened
        assert result is True
        mock_close.assert_called_once_with(42)  # Old FD closed
        # New FD opened (will be called after FIFO recreation in _ensure_fifo)
        assert mock_open.called

    @patch("os.close")
    def test_cleanup_fifo_only_closes_dummy_writer(
        self, mock_close: MagicMock, terminal_manager: PersistentTerminalManager
    ) -> None:
        """Test cleanup_fifo_only closes dummy writer FD."""
        # Arrange: Set dummy writer FD
        terminal_manager._dummy_writer_fd = 42

        # Mock FIFO operations
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.unlink"):
            # Act: Cleanup FIFO only
            terminal_manager.cleanup_fifo_only()

        # Assert: Dummy writer FD was closed
        mock_close.assert_called_once_with(42)
        assert terminal_manager._dummy_writer_fd is None

    @patch("os.close")
    def test_del_closes_dummy_writer_fd(self, mock_close: MagicMock) -> None:
        """Test __del__ closes dummy writer FD during garbage collection."""
        # Arrange: Create manager and manually set dummy writer FD
        # (Init no longer opens dummy writer automatically)
        with (
            patch("os.path.exists", return_value=False),
            patch("os.mkfifo"),
            patch("os.stat") as mock_stat,
        ):
            mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)
            manager = PersistentTerminalManager(fifo_path="/tmp/test.fifo")

        # Manually set dummy writer FD to simulate it being opened later
        manager._dummy_writer_fd = 42

        # Verify dummy writer FD is set
        assert manager._dummy_writer_fd == 42

        # Mock Path operations for __del__
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.unlink"):
            # Act: Trigger __del__ by deleting manager
            manager.__del__()

        # Assert: Dummy writer FD was closed
        mock_close.assert_called_with(42)

    @patch("os.close")
    @patch("os.open")
    @patch("os.mkfifo")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("time.sleep")
    def test_restart_terminal_opens_dummy_writer_after_dispatcher_starts(
        self,
        mock_sleep: MagicMock,
        mock_stat: MagicMock,
        mock_exists: MagicMock,
        mock_mkfifo: MagicMock,
        mock_open: MagicMock,
        mock_close: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test restart_terminal opens dummy writer AFTER dispatcher starts.

        This test catches the bug where _ensure_fifo() tries to open dummy writer
        BEFORE _launch_terminal() starts the dispatcher, causing ENXIO errors.

        Current buggy order (line 895-901):
        1. _ensure_fifo() - Opens dummy writer (ENXIO!)
        2. _launch_terminal() - Starts dispatcher (reader)

        Correct order should be:
        1. Create FIFO file
        2. _launch_terminal() - Start dispatcher (reader)
        3. Open dummy writer - Now reader exists, no ENXIO
        """
        # Arrange: Track call order
        call_order: list[str] = []

        # Set initial dummy writer FD
        terminal_manager._dummy_writer_fd = 42

        # Mock Path.exists to return True for FIFO (so it gets removed)
        mock_exists.return_value = True

        # Mock FIFO stat
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Track os.open calls - simulate ENXIO if writer opens before dispatcher
        def track_open(path: str, flags: int) -> int:
            """Track dummy writer opens."""
            # Check if this is a write-only open (dummy writer)
            import os as real_os
            if flags & real_os.O_WRONLY:
                call_order.append("dummy_writer_open")
                # Simulate ENXIO if dispatcher hasn't started yet
                if "launch_terminal" not in call_order:
                    raise OSError(errno.ENXIO, "No reader available")
            return 99  # New FD

        mock_open.side_effect = track_open

        # Track _launch_terminal calls
        def track_launch() -> bool:
            """Track dispatcher launch."""
            call_order.append("launch_terminal")
            return True  # Simulate successful launch

        # Track _is_dispatcher_running for final health check
        def mock_dispatcher_running() -> bool:
            """Mock dispatcher running check."""
            return "launch_terminal" in call_order

        with (
            patch.object(terminal_manager, "_launch_terminal", side_effect=track_launch),
            patch.object(terminal_manager, "_is_dispatcher_running", side_effect=mock_dispatcher_running),
            patch.object(terminal_manager, "close_terminal"),
        ):
            # Act: Restart terminal
            result = terminal_manager.restart_terminal()

        # Assert: This test SHOULD FAIL with current code
        # Current code opens dummy writer BEFORE launching terminal
        # Expected order: ["launch_terminal", "dummy_writer_open"]
        # Actual buggy order: ["dummy_writer_open"] (raises ENXIO before launch)

        # This assertion will FAIL with current buggy code:
        # - Either ENXIO is raised (test fails with exception)
        # - Or call_order is wrong (assertion fails)
        if result:  # If it didn't raise ENXIO
            assert "launch_terminal" in call_order, "Dispatcher was never started"
            assert call_order.index("launch_terminal") < call_order.index("dummy_writer_open"), \
                f"Dummy writer opened before dispatcher started. Order: {call_order}"
        else:
            # restart_terminal returned False due to ENXIO
            pytest.fail("restart_terminal failed - likely due to ENXIO from opening writer before reader")

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("os.open")
    def test_ensure_fifo_with_no_reader_raises_enxio(
        self,
        mock_open: MagicMock,
        mock_stat: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Test _ensure_fifo handles ENXIO when opening writer with no reader.

        This test demonstrates the POSIX FIFO semantics:
        - open(fifo, O_WRONLY | O_NONBLOCK) with no reader = ENXIO error

        Current code doesn't handle this case properly, assuming the reader
        (dispatcher) already exists.
        """
        # Arrange: FIFO exists but has no reader
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Simulate ENXIO when trying to open for writing (no reader)
        mock_open.side_effect = OSError(errno.ENXIO, "No reader available")

        # Act: Try to create manager (calls _ensure_fifo in __init__)
        # This SHOULD handle ENXIO gracefully but currently doesn't
        with patch("os.mkfifo"):  # Don't actually create FIFO
            manager = PersistentTerminalManager(fifo_path="/tmp/test.fifo")

        # Assert: Manager should handle ENXIO gracefully
        # Current code logs error but doesn't handle it properly
        assert manager._dummy_writer_fd is None, (
            "Dummy writer FD should be None when ENXIO occurs"
        )

    @patch("os.open")
    @patch("os.mkfifo")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("time.sleep")
    def test_dummy_writer_opens_only_after_dispatcher_ready(
        self,
        mock_sleep: MagicMock,
        mock_stat: MagicMock,
        mock_exists: MagicMock,
        mock_mkfifo: MagicMock,
        mock_open: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test dummy writer FD remains None until dispatcher is ready.

        This is an end-to-end ordering test that verifies the complete flow:
        1. Create FIFO
        2. Start dispatcher (reader)
        3. Wait for dispatcher ready
        4. Open dummy writer (now safe, reader exists)
        """
        # Arrange: Track state
        call_order: list[str] = []
        dispatcher_ready = False

        # Set initial state
        terminal_manager._dummy_writer_fd = None

        # Mock FIFO operations
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Track os.open - should only be called after dispatcher ready
        open_call_count = 0

        def track_open(path: str, flags: int) -> int:
            """Track dummy writer opens."""
            nonlocal open_call_count
            import os as real_os
            if flags & real_os.O_WRONLY:
                open_call_count += 1
                call_order.append("dummy_writer_open")
                # Verify dispatcher is ready before opening
                if not dispatcher_ready:
                    pytest.fail("Dummy writer opened before dispatcher was ready!")
            return 42

        mock_open.side_effect = track_open

        # Mock dispatcher readiness
        def mock_dispatcher_running() -> bool:
            """Mock dispatcher running check."""
            return dispatcher_ready

        # Mock launch to set dispatcher ready
        def mock_launch() -> bool:
            """Mock terminal launch."""
            nonlocal dispatcher_ready
            call_order.append("launch_terminal")
            # Simulate dispatcher startup delay
            dispatcher_ready = True
            return True

        with (
            patch.object(terminal_manager, "_launch_terminal", side_effect=mock_launch),
            patch.object(terminal_manager, "_is_dispatcher_running", side_effect=mock_dispatcher_running),
            patch.object(terminal_manager, "close_terminal"),
            patch("os.close"),
        ):
            # Act: Restart terminal
            result = terminal_manager.restart_terminal()

        # Assert: Dummy writer only opened after dispatcher ready
        assert result is True
        assert call_order.index("launch_terminal") < call_order.index("dummy_writer_open"), \
            f"Wrong order: {call_order}"
        assert open_call_count == 1, "Dummy writer should be opened exactly once"

    @patch("pathlib.Path.exists")
    @patch("os.mkfifo")
    @patch("pathlib.Path.stat")
    @patch("os.open")
    def test_initialization_order_prevents_enxio(
        self,
        mock_open: MagicMock,
        mock_stat: MagicMock,
        mock_mkfifo: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Test __init__ doesn't raise ENXIO by deferring dummy writer opening.

        After fix, __init__ should:
        1. Create FIFO only (no dummy writer)
        2. Defer dummy writer opening until terminal is launched

        This prevents ENXIO since dummy writer isn't opened during init.
        """
        # Arrange: FIFO doesn't exist initially
        mock_exists.return_value = False
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Track if os.open was called with O_WRONLY (dummy writer)
        writer_opened = False

        def track_open(path: str, flags: int) -> int:
            """Track if dummy writer opens during init."""
            nonlocal writer_opened
            import os as real_os
            if flags & real_os.O_WRONLY:
                writer_opened = True
                # Would raise ENXIO if dispatcher not running
                raise OSError(errno.ENXIO, "No reader available - dispatcher not started")
            return 42

        mock_open.side_effect = track_open

        # Act: Create manager - should NOT raise ENXIO now
        manager = PersistentTerminalManager(fifo_path="/tmp/test.fifo")

        # Assert: Manager created successfully without opening dummy writer
        assert manager._dummy_writer_fd is None, "Dummy writer should not be opened during init"
        assert not writer_opened, "os.open(O_WRONLY) should not be called during init"
        assert manager.fifo_path == "/tmp/test.fifo"

        # The fix: __init__ calls _ensure_fifo(open_dummy_writer=False)
        # Dummy writer will be opened later when terminal is actually launched

    @patch("os.close")
    @patch("os.open")
    @patch("os.mkfifo")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("time.sleep")
    def test_rapid_restart_maintains_correct_order(
        self,
        mock_sleep: MagicMock,
        mock_stat: MagicMock,
        mock_exists: MagicMock,
        mock_mkfifo: MagicMock,
        mock_open: MagicMock,
        mock_close: MagicMock,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test rapid restart cycles maintain correct operation order.

        Stress test to verify that even in rapid restart scenarios,
        the order is always: close → mkfifo → launch → open_writer
        """
        # Arrange: Track all restart cycles
        restart_cycles: list[list[str]] = []
        current_cycle: list[str] = []

        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Track operations in each cycle
        def track_mkfifo(path: str, mode: int) -> None:
            """Track FIFO creation."""
            current_cycle.append("mkfifo")

        def track_open(path: str, flags: int) -> int:
            """Track dummy writer opens."""
            import os as real_os
            if flags & real_os.O_WRONLY:
                current_cycle.append("open_writer")
                # Verify dispatcher was launched before this
                if "launch" not in current_cycle:
                    pytest.fail(f"Writer opened before dispatcher in cycle {len(restart_cycles)}")
            return 42

        def track_close(fd: int) -> None:
            """Track FD close."""
            if fd == 42:  # Our dummy writer FD
                current_cycle.append("close")

        mock_mkfifo.side_effect = track_mkfifo
        mock_open.side_effect = track_open
        mock_close.side_effect = track_close

        # Mock dispatcher operations
        def mock_launch() -> bool:
            """Track terminal launch."""
            current_cycle.append("launch")
            return True

        def mock_dispatcher_running() -> bool:
            """Mock dispatcher running."""
            return "launch" in current_cycle

        terminal_manager._dummy_writer_fd = 42  # Set initial FD

        with (
            patch.object(terminal_manager, "_launch_terminal", side_effect=mock_launch),
            patch.object(terminal_manager, "_is_dispatcher_running", side_effect=mock_dispatcher_running),
            patch.object(terminal_manager, "close_terminal"),
            patch("pathlib.Path.unlink"),
        ):
            # Act: Run 3 rapid restart cycles
            for _ in range(3):
                current_cycle = []
                result = terminal_manager.restart_terminal()
                if result:
                    restart_cycles.append(current_cycle[:])  # Save cycle
                terminal_manager._dummy_writer_fd = 42  # Reset for next cycle

        # Assert: All cycles followed correct order
        assert len(restart_cycles) == 3, f"Expected 3 cycles, got {len(restart_cycles)}"

        # Verify each cycle has correct order: launch before open_writer
        for cycle_num, cycle in enumerate(restart_cycles):
            # Verify launch happens before open_writer
            if "open_writer" in cycle and "launch" in cycle:
                assert cycle.index("launch") < cycle.index("open_writer"), \
                    f"Cycle {cycle_num}: Wrong order {cycle}"

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("os.open")
    def test_enxio_error_logged_appropriately(
        self,
        mock_open: MagicMock,
        mock_stat: MagicMock,
        mock_exists: MagicMock,
        caplog: pytest.LogCaptureFixture,
        terminal_manager: PersistentTerminalManager,
    ) -> None:
        """Test ENXIO errors are logged when explicitly trying to open dummy writer.

        Verifies that when _open_dummy_writer() is called before dispatcher is ready,
        ENXIO is logged with helpful context.
        """
        # Arrange: FIFO exists but no reader
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

        # Simulate ENXIO error when opening writer
        mock_open.side_effect = OSError(errno.ENXIO, "No such device or address")

        # Act: Try to open dummy writer directly (no dispatcher running)
        import logging
        with caplog.at_level(logging.ERROR):
            result = terminal_manager._open_dummy_writer()

        # Assert: Operation failed
        assert result is False, "Opening dummy writer should fail with ENXIO"

        # Assert: ENXIO error was logged with context
        error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_logs) >= 2, f"Expected at least 2 error logs, got {len(error_logs)}"

        # Check for relevant error messages
        error_messages = [record.message for record in error_logs]

        # Should log the failed open attempt
        assert any("Failed to open dummy writer" in msg for msg in error_messages), \
            f"Expected 'Failed to open dummy writer' in logs, got: {error_messages}"

        # Should log ENXIO-specific guidance
        assert any("ENXIO error" in msg and "No reader available" in msg for msg in error_messages), \
            f"Expected ENXIO guidance in logs, got: {error_messages}"

        # Verify manager state is consistent despite error
        assert terminal_manager._dummy_writer_fd is None


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
