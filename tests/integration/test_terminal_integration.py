"""Integration tests for terminal command flow from UI to execution."""

from __future__ import annotations

# Standard library imports
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

# Third-party imports
import pytest

# Local application imports
from command_launcher import CommandLauncher
from persistent_terminal_manager import PersistentTerminalManager


pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,  # CRITICAL: For parallel test safety
]

# Integration tests follow UNIFIED_TESTING_GUIDE principles:
# - Use real Qt components with qtbot
# - Mock only at system boundaries (subprocess)
# - Test complete workflows end-to-end


class TestTerminalIntegrationFlow:
    """Test complete terminal command flow from UI to execution."""

    @pytest.fixture
    def temp_environment(self, tmp_path):
        """Create a complete temporary environment for testing."""
        # Create FIFO path
        fifo_path = tmp_path / "test_commands.fifo"

        # Create dispatcher script
        dispatcher_path = tmp_path / "dispatcher.sh"
        dispatcher_path.write_text(
            "#!/bin/bash\n"
            "FIFO=$1\n"
            "while true; do\n"
            '  if read -r cmd < "$FIFO"; then\n'
            '    echo "Executing: $cmd"\n'
            "  fi\n"
            "done\n"
        )
        dispatcher_path.chmod(0o755)

        return {
            "fifo": str(fifo_path),
            "dispatcher": str(dispatcher_path),
            "tmp_path": tmp_path,
        }

    @pytest.fixture
    def integrated_launcher(self, qtbot, temp_environment):
        """Create fully integrated launcher with persistent terminal."""
        # Create persistent terminal manager
        with (
            patch("os.mkfifo"),
            patch("os.path.exists", return_value=True),
            patch("os.stat") as mock_stat,
        ):
            # Standard library imports
            import stat

            mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

            terminal_manager = PersistentTerminalManager(
                fifo_path=temp_environment["fifo"],
                dispatcher_path=temp_environment["dispatcher"],
            )
            # Note: PersistentTerminalManager is QObject, not QWidget - no qtbot.addWidget needed

            # Create launcher with terminal
            launcher = CommandLauncher()
            launcher.persistent_terminal = terminal_manager
            # Note: CommandLauncher is QObject, not QWidget - no qtbot.addWidget needed

            # Set up test shot
            launcher.current_shot = MagicMock(
                show="test_show",
                sequence="seq01",
                shot="0010",
                workspace_path="/test/workspace",
            )

            return launcher

    @pytest.mark.qt
    def test_end_to_end_command_flow_with_persistent_terminal(
        self, qtbot, integrated_launcher
    ) -> None:
        """Test complete flow: UI trigger → persistent terminal → command execution."""
        # Track all signals in the flow
        command_sent_signals = []
        command_executed_signals = []
        terminal_started_signals = []

        # Connect to signals
        integrated_launcher.persistent_terminal.command_sent.connect(
            command_sent_signals.append
        )
        integrated_launcher.command_executed.connect(
            lambda _ts, cmd: command_executed_signals.append(cmd)
        )
        integrated_launcher.persistent_terminal.terminal_started.connect(
            terminal_started_signals.append
        )

        # Mock subprocess for terminal launch
        with (
            patch("subprocess.Popen") as mock_popen,
            patch.object(
                integrated_launcher.persistent_terminal,
                "_is_terminal_alive",
                return_value=True,
            ),
            patch("os.open", return_value=42),
            patch("os.fdopen") as mock_fdopen,
            patch("config.Config.USE_PERSISTENT_TERMINAL", True),
            patch("config.Config.PERSISTENT_TERMINAL_ENABLED", True),
            patch("config.Config.APPS", {"3de": "3de4_r6"}),
            patch.object(
                integrated_launcher,
                "_validate_workspace_before_launch",
                return_value=True,
            ),
        ):
            # Set up mock process
            mock_process = MagicMock(pid=12345)
            mock_popen.return_value = mock_process

            # Set up mock FIFO write
            mock_file = MagicMock()
            mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
            mock_fdopen.return_value.__exit__ = Mock(return_value=False)

            # Manually set the terminal PID since we're mocking the launch
            integrated_launcher.persistent_terminal.terminal_pid = 12345
            integrated_launcher.persistent_terminal.terminal_process = mock_process

            # Simulate UI action: Launch 3DE
            with (
                patch.object(
                    integrated_launcher, "_is_rez_available", return_value=True
                ),
                patch.object(
                    integrated_launcher,
                    "_get_rez_packages_for_app",
                    return_value=["3de"],
                ),
            ):
                result = integrated_launcher.launch_app("3de")

            # Assert complete flow executed
            assert result is True

            # Verify terminal state
            assert integrated_launcher.persistent_terminal.terminal_pid == 12345

            # Verify command was sent through persistent terminal
            assert len(command_sent_signals) > 0
            sent_command = command_sent_signals[-1]
            assert "3de" in sent_command
            assert "ws /test/workspace" in sent_command

            # Verify UI was notified
            assert len(command_executed_signals) > 0

    @pytest.mark.qt
    def test_fallback_flow_when_persistent_terminal_fails(
        self, qtbot, integrated_launcher
    ) -> None:
        """Test fallback flow: persistent terminal fails → new terminal launched."""
        error_signals = []
        command_signals = []

        integrated_launcher.command_error.connect(
            lambda _ts, err: error_signals.append(err)
        )
        integrated_launcher.command_executed.connect(
            lambda _ts, cmd: command_signals.append(cmd)
        )

        # Make persistent terminal fail
        with (
            patch.object(
                integrated_launcher.persistent_terminal,
                "send_command",
                return_value=False,
            ),
            patch("subprocess.Popen") as mock_popen,
            patch.object(integrated_launcher, "_is_rez_available", return_value=True),
            patch.object(
                integrated_launcher, "_get_rez_packages_for_app", return_value=["nuke"]
            ),
            patch("config.Config.USE_PERSISTENT_TERMINAL", True),
            patch("config.Config.PERSISTENT_TERMINAL_ENABLED", True),
            patch("config.Config.APPS", {"nuke": "Nuke15.1v3"}),
            patch.object(
                integrated_launcher,
                "_validate_workspace_before_launch",
                return_value=True,
            ),
            patch.object(
                integrated_launcher, "_detect_available_terminal", return_value="gnome-terminal"
            ),
        ):
            mock_process = MagicMock()
            mock_popen.return_value = mock_process

            # Launch app - should fallback
            result = integrated_launcher.launch_app("nuke")

            # Assert fallback succeeded
            assert result is True

            # Verify new terminal was launched
            mock_popen.assert_called_once()
            popen_args = mock_popen.call_args[0][0]

            # CRITICAL: Verify no background operator in fallback
            command = popen_args[-1]
            assert not command.strip().endswith(" &")

            # Verify user was notified of fallback
            fallback_messages = [
                msg
                for msg in command_signals
                if "Persistent terminal not available" in msg or "Launching" in msg
            ]
            assert len(fallback_messages) > 0

    @pytest.mark.qt
    def test_auto_restart_on_terminal_death(self, qtbot, integrated_launcher) -> None:
        """Test terminal auto-restart when it dies unexpectedly."""
        restart_count = 0

        def mock_restart() -> bool:
            nonlocal restart_count
            restart_count += 1
            # After restart, dispatcher should be running
            # Update the mock to reflect this
            integrated_launcher.persistent_terminal._is_dispatcher_running = Mock(return_value=True)  # type: ignore[method-assign]
            return True

        # Simulate terminal dying and being restarted
        # Standard library imports

        with (
            patch("os.open") as mock_open,
            patch("os.kill"),  # Mock the force kill call
            patch.object(
                integrated_launcher.persistent_terminal,
                "restart_terminal",
                side_effect=mock_restart,
            ) as mock_restart_method,
            patch.object(
                integrated_launcher.persistent_terminal,
                "_is_terminal_alive",
                return_value=True,
            ),
            patch("os.path.exists", return_value=True),
            patch("os.fdopen") as mock_fdopen,
        ):
            # Set up dispatcher to be dead initially, then alive after restart
            dispatcher_states = [False, True]  # First call: dead, after restart: alive

            def dispatcher_running_side_effect() -> bool:
                return dispatcher_states.pop(0) if dispatcher_states else True

            integrated_launcher.persistent_terminal._is_dispatcher_running = Mock(  # type: ignore[method-assign]
                side_effect=dispatcher_running_side_effect
            )

            # Set terminal PID so force kill logic executes
            integrated_launcher.persistent_terminal.terminal_pid = 12345

            # os.open should succeed after restart
            mock_open.return_value = 42

            mock_file = MagicMock()
            mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
            mock_fdopen.return_value.__exit__ = Mock(return_value=False)

            # Send command - should trigger restart
            result = integrated_launcher.persistent_terminal.send_command(
                "test command", ensure_terminal=True
            )

            # Assert restart happened and command succeeded
            assert result is True
            mock_restart_method.assert_called_once()
            # Check that write was called with the command (as bytes or string)
            write_calls = [call[0][0] for call in mock_file.write.call_args_list]
            # Decode bytes if needed for comparison
            decoded_calls = [
                c.decode() if isinstance(c, bytes) else c for c in write_calls
            ]
            assert any("test command" in call for call in decoded_calls)

    @pytest.mark.qt
    def test_signal_flow_with_qt_event_loop(self, qtbot, integrated_launcher) -> None:
        """Test Qt signal propagation through the system."""
        # This tests that signals work correctly with Qt's event loop

        signals_received = {
            "terminal_started": [],
            "command_sent": [],
            "command_executed": [],
            "command_error": [],
        }

        # Connect all signals
        integrated_launcher.persistent_terminal.terminal_started.connect(
            lambda pid: signals_received["terminal_started"].append(pid)
        )
        integrated_launcher.persistent_terminal.command_sent.connect(
            lambda cmd: signals_received["command_sent"].append(cmd)
        )
        integrated_launcher.command_executed.connect(
            lambda ts, cmd: signals_received["command_executed"].append((ts, cmd))
        )
        integrated_launcher.command_error.connect(
            lambda ts, err: signals_received["command_error"].append((ts, err))
        )

        # Test terminal start signal
        with qtbot.waitSignal(
            integrated_launcher.persistent_terminal.terminal_started, timeout=100
        ):
            integrated_launcher.persistent_terminal.terminal_started.emit(99999)

        assert 99999 in signals_received["terminal_started"]

        # Test command flow signals
        test_command = "echo 'Qt signal test'"

        with qtbot.waitSignal(
            integrated_launcher.persistent_terminal.command_sent, timeout=100
        ):
            integrated_launcher.persistent_terminal.command_sent.emit(test_command)

        assert test_command in signals_received["command_sent"]

    @pytest.mark.qt
    def test_concurrent_command_handling(self, qtbot, integrated_launcher) -> None:
        """Test handling multiple rapid commands."""
        commands_sent = []

        # Mock FIFO operations to track commands
        with (
            patch("os.open", return_value=42),
            patch("os.fdopen") as mock_fdopen,
            patch("os.path.exists", return_value=True),
            patch.object(
                integrated_launcher.persistent_terminal,
                "_is_terminal_alive",
                return_value=True,
            ),
            patch.object(
                integrated_launcher.persistent_terminal,
                "_is_dispatcher_running",
                return_value=True,
            ),
        ):
            mock_file = MagicMock()

            def track_write(data) -> None:
                commands_sent.append(data.strip())

            mock_file.write = track_write
            mock_file.flush = Mock()
            mock_fdopen.return_value.__enter__ = Mock(return_value=mock_file)
            mock_fdopen.return_value.__exit__ = Mock(return_value=False)

            # Send multiple commands rapidly
            test_commands = [
                "echo 'Command 1'",
                "echo 'Command 2'",
                "echo 'Command 3'",
                "ls -la",
                "pwd",
            ]

            for cmd in test_commands:
                result = integrated_launcher.persistent_terminal.send_command(cmd)
                assert result is True

            # Verify all commands were sent in order (filter out empty separators)
            non_empty_commands = [cmd for cmd in commands_sent if cmd]
            # Decode bytes to strings if needed
            decoded_commands = [
                cmd.decode() if isinstance(cmd, bytes) else cmd
                for cmd in non_empty_commands
            ]
            assert len(decoded_commands) == len(test_commands)
            for sent, expected in zip(decoded_commands, test_commands, strict=False):
                assert sent == expected


class TestTerminalCleanup:
    """Test proper cleanup of terminal resources."""

    def setup_method(self) -> None:
        """Track Qt objects for cleanup."""
        self.qt_objects: list[Any] = []

    def teardown_method(self) -> None:
        """Clean up Qt objects."""
        for obj in self.qt_objects:
            try:
                if hasattr(obj, "deleteLater"):
                    obj.deleteLater()
            except Exception:
                pass
        self.qt_objects.clear()

    @pytest.mark.qt
    def test_cleanup_on_application_exit(self, qtbot) -> None:
        """Test terminal cleanup when application exits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fifo_path = Path(tmpdir) / "test.fifo"

            # Create manager
            with (
                patch("os.mkfifo"),
                patch("os.path.exists", return_value=True),
                patch("os.stat") as mock_stat,
                patch("os.unlink") as mock_unlink,
            ):
                # Standard library imports
                import stat

                mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

                manager = PersistentTerminalManager(fifo_path=str(fifo_path))
                self.qt_objects.append(manager)  # Track for cleanup
                # Note: PersistentTerminalManager is QObject, not QWidget - no qtbot.addWidget needed

                # Set terminal as running
                manager.terminal_pid = 12345

                with (
                    patch.object(manager, "_is_terminal_alive", return_value=True),
                    patch.object(manager, "close_terminal") as mock_close,
                ):
                    # Cleanup
                    manager.cleanup()

                    # Assert proper cleanup
                    mock_close.assert_called_once()
                    # Accept either str or Path - implementation may use either
                    actual_call = mock_unlink.call_args[0][0]
                    assert str(actual_call) == str(fifo_path)

    @pytest.mark.qt
    def test_cleanup_fifo_only_keeps_terminal(self, qtbot) -> None:
        """Test FIFO-only cleanup keeps terminal running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fifo_path = Path(tmpdir) / "test.fifo"

            with (
                patch("os.mkfifo"),
                patch("os.path.exists", return_value=True),
                patch("os.stat") as mock_stat,
                patch("os.unlink") as mock_unlink,
            ):
                # Standard library imports
                import stat

                mock_stat.return_value = MagicMock(st_mode=stat.S_IFIFO | 0o600)

                manager = PersistentTerminalManager(fifo_path=str(fifo_path))
                self.qt_objects.append(manager)  # Track for cleanup
                # Note: PersistentTerminalManager is QObject, not QWidget - no qtbot.addWidget needed

                manager.terminal_pid = 12345

                with patch.object(manager, "close_terminal") as mock_close:
                    # Cleanup FIFO only
                    manager.cleanup_fifo_only()

                    # Assert terminal NOT closed
                    mock_close.assert_not_called()
                    # But FIFO was removed - accept either str or Path
                    actual_call = mock_unlink.call_args[0][0]
                    assert str(actual_call) == str(fifo_path)
