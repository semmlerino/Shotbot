"""Comprehensive unit tests for LauncherWorker.

Testing QThread-based worker execution, command sanitization, stream handling,
and signal propagation. This is the final component of Priority 1 launcher testing.

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real Qt components with signal testing
- Mock subprocess calls to avoid launching actual apps
- Thread safety validation
- Proper resource cleanup
"""

from __future__ import annotations

import io
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtTest import QSignalSpy

from exceptions import SecurityError
from launcher.worker import LauncherWorker
from thread_safe_worker import WorkerState


if TYPE_CHECKING:
    from collections.abc import Generator

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

from process_pool_manager import ProcessPoolManager


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def reset_launcher_singletons() -> Generator[None, None, None]:
    """Reset launcher-related singletons between tests for isolation.

    Prevents singleton contamination when tests run in parallel with xdist.
    Resets ProcessPoolManager singleton state before and after each test.
    """
    # Reset before test using the new reset() method
    ProcessPoolManager.reset()
    yield
    # Reset after test
    ProcessPoolManager.reset()


@pytest.fixture
def worker_id() -> str:
    """Standard worker ID for testing."""
    return "test_worker_123"


@pytest.fixture
def mock_subprocess_popen():
    """Mock subprocess.Popen to avoid actually launching processes."""
    with patch("launcher.worker.subprocess.Popen") as mock_popen:
        # Create mock process without spec (avoid spec on already mocked object)
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Process is running
        mock_process.wait.return_value = 0  # Success exit code
        mock_process.returncode = 0

        # Mock stdout and stderr as file-like objects
        mock_process.stdout = io.BytesIO(b"test output\n")
        mock_process.stderr = io.BytesIO(b"test error\n")

        mock_popen.return_value = mock_process
        yield mock_popen, mock_process


@pytest.fixture
def mock_threading():
    """Mock threading.Thread to avoid actual thread creation."""
    with patch("launcher.worker.threading.Thread") as mock_thread:
        mock_thread_instance = Mock()
        mock_thread_instance.start.return_value = None
        mock_thread.return_value = mock_thread_instance
        yield mock_thread, mock_thread_instance


# ============================================================================
# Test Initialization
# ============================================================================


class TestInitialization:
    """Test LauncherWorker initialization."""

    def test_initialization_sets_basic_attributes(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test worker initializes with basic attributes."""
        worker = LauncherWorker(worker_id, "nuke script.nk")
        try:
            assert worker.launcher_id == worker_id
            assert worker.command == "nuke script.nk"
            assert worker.working_dir is None
            assert worker._process is None
            assert worker.get_state() == WorkerState.CREATED
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_initialization_with_working_dir(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test worker initializes with optional working directory."""
        worker = LauncherWorker(worker_id, "maya scene.ma", working_dir="/tmp")
        try:
            assert worker.working_dir == "/tmp"
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_initialization_inherits_from_thread_safe_worker(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test worker has all ThreadSafeWorker lifecycle signals."""
        worker = LauncherWorker(worker_id, "nuke")
        try:
            # Verify base class signals exist
            assert hasattr(worker, "worker_started")
            assert hasattr(worker, "worker_stopping")
            assert hasattr(worker, "worker_stopped")
            assert hasattr(worker, "worker_error")

            # Verify launcher-specific signals
            assert hasattr(worker, "command_started")
            assert hasattr(worker, "command_finished")
            assert hasattr(worker, "command_error")
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop


# ============================================================================
# Test Command Sanitization
# ============================================================================


class TestCommandSanitization:
    """Test _sanitize_command method for command parsing.

    Note: Security validation (whitelisting, pattern checking) was removed per
    CLAUDE.md security posture for single-user trusted tool.
    """

    def test_sanitize_command_simple(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test parsing of simple command."""
        worker = LauncherWorker(worker_id, "nuke")
        try:
            cmd_list, use_shell = worker._sanitize_command("nuke script.nk")
            assert cmd_list == ["nuke", "script.nk"]
            assert use_shell is False
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_sanitize_command_with_path(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test parsing of command with full path."""
        worker = LauncherWorker(worker_id, "nuke")
        try:
            cmd_list, use_shell = worker._sanitize_command(
                "/usr/local/bin/nuke script.nk"
            )
            assert "nuke" in cmd_list[0]
            assert cmd_list[1] == "script.nk"
            assert use_shell is False
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_sanitize_command_3de(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test parsing of 3DE command."""
        worker = LauncherWorker(worker_id, "3de")
        try:
            cmd_list, use_shell = worker._sanitize_command("3de scene.3de")
            assert cmd_list == ["3de", "scene.3de"]
            assert use_shell is False
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_sanitize_command_maya(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test parsing of Maya command."""
        worker = LauncherWorker(worker_id, "maya")
        try:
            cmd_list, use_shell = worker._sanitize_command("maya -file scene.ma")
            assert cmd_list == ["maya", "-file", "scene.ma"]
            assert use_shell is False
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_sanitize_rejects_malformed_command(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test sanitization rejects malformed command that shlex cannot parse."""
        worker = LauncherWorker(worker_id, "nuke")
        try:
            with pytest.raises(SecurityError, match="could not be parsed"):
                worker._sanitize_command('nuke "unclosed quote')
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_sanitize_never_uses_shell(
        self, qtbot: QtBot, qapp: QApplication, worker_id: str
    ) -> None:
        """Test sanitization always returns use_shell=False for security."""
        worker = LauncherWorker(worker_id, "nuke")
        try:
            # Try multiple commands
            for command in ["nuke script.nk", "maya -file scene.ma", "3de scene.3de"]:
                _cmd_list, use_shell = worker._sanitize_command(command)
                assert use_shell is False, f"use_shell should always be False, got True for: {command}"
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop


# ============================================================================
# Test Worker Execution
# ============================================================================


class TestWorkerExecution:
    """Test worker thread execution and lifecycle."""

    def test_do_work_emits_command_started_signal(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work emits command_started signal."""
        _mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            spy = QSignalSpy(worker.command_started)

            # Simulate process finishing quickly
            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            assert spy.count() == 1
            assert spy.at(0)[0] == worker_id
            assert spy.at(0)[1] == "nuke script.nk"
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_calls_subprocess_popen(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work creates subprocess with correct arguments."""
        mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            # Simulate process finishing quickly
            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            mock_popen.assert_called_once()
            call_args = mock_popen.call_args

            # Verify command
            assert call_args[0][0] == ["nuke", "script.nk"]

            # Verify kwargs
            assert call_args[1]["shell"] is False
            assert call_args[1]["stdout"] == subprocess.PIPE
            assert call_args[1]["stderr"] == subprocess.PIPE
            assert call_args[1]["cwd"] is None
            assert call_args[1]["start_new_session"] is True
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_uses_working_directory(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work passes working directory to subprocess."""
        mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk", working_dir="/tmp")

        try:
            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            call_args = mock_popen.call_args
            assert call_args[1]["cwd"] == "/tmp"
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_creates_stream_drain_threads(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work creates threads to drain stdout and stderr."""
        _mock_popen, mock_process = mock_subprocess_popen
        mock_thread_cls, mock_thread = mock_threading
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            # Should create two threads (stdout and stderr drains)
            assert mock_thread_cls.call_count == 2

            # Verify both threads were started
            assert mock_thread.start.call_count == 2

            # Verify daemon flag (changed to False to prevent thread leaks)
            for call_args in mock_thread_cls.call_args_list:
                assert call_args[1]["daemon"] is False

            # Verify threads have names for debugging
            thread_names = [call_args[1].get("name", "") for call_args in mock_thread_cls.call_args_list]
            assert len(thread_names) == 2
            assert any("stdout-drain" in name for name in thread_names)
            assert any("stderr-drain" in name for name in thread_names)
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_emits_command_finished_on_success(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work emits command_finished with success on exit code 0."""
        _mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            spy = QSignalSpy(worker.command_finished)

            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            assert spy.count() == 1
            assert spy.at(0)[0] == worker_id
            assert spy.at(0)[1] is True  # success
            assert spy.at(0)[2] == 0  # return code
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_emits_command_finished_on_failure(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work emits command_finished with failure on non-zero exit."""
        _mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            spy = QSignalSpy(worker.command_finished)

            mock_process.wait.return_value = 1
            mock_process.poll.return_value = 1

            worker.do_work()

            assert spy.count() == 1
            assert spy.at(0)[0] == worker_id
            assert spy.at(0)[1] is False  # failure
            assert spy.at(0)[2] == 1  # return code
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_handles_stop_request_during_execution(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test do_work respects stop request during process execution."""
        _mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            spy_finished = QSignalSpy(worker.command_finished)

            # Simulate long-running process that doesn't finish
            call_count = [0]  # Use mutable to track calls
            def wait_timeout(*args, **kwargs):
                call_count[0] += 1
                # Request stop on second call (after first timeout)
                if call_count[0] == 2:
                    worker.request_stop()
                # Always timeout to simulate running process
                raise subprocess.TimeoutExpired("cmd", 1.0)

            mock_process.wait.side_effect = wait_timeout
            mock_process.poll.return_value = None

            worker.do_work()

            # Should emit finished with failure code -2 (stopped)
            assert spy_finished.count() == 1
            assert spy_finished.at(0)[1] is False
            assert spy_finished.at(0)[2] == -2
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_do_work_emits_error_on_exception(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test do_work emits command_error on exception."""
        worker = LauncherWorker(worker_id, "invalid command")

        try:
            spy_error = QSignalSpy(worker.command_error)
            spy_finished = QSignalSpy(worker.command_finished)

            # This will raise SecurityError due to invalid command
            worker.do_work()

            # Should emit error signal
            assert spy_error.count() == 1
            assert worker_id in spy_error.at(0)[0]

            # Should also emit finished with failure
            assert spy_finished.count() == 1
            assert spy_finished.at(0)[1] is False
            assert spy_finished.at(0)[2] == -1  # error code
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop


# ============================================================================
# Test Process Termination
# ============================================================================


class TestProcessTermination:
    """Test process termination and cleanup."""

    def test_terminate_process_calls_terminate(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _terminate_process calls process.terminate()."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = None
            mock_process.wait.return_value = 0
            worker._process = mock_process

            worker._terminate_process()

            mock_process.terminate.assert_called_once()
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_terminate_process_waits_for_graceful_exit(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _terminate_process waits for graceful termination."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = None
            mock_process.wait.return_value = 0
            worker._process = mock_process

            worker._terminate_process()

            # Should wait with 10s timeout
            mock_process.wait.assert_called()
            assert mock_process.wait.call_args[1]["timeout"] == 10
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_terminate_process_kills_if_timeout(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _terminate_process kills process if graceful timeout."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = None
            mock_process.wait.side_effect = [
                subprocess.TimeoutExpired("cmd", 10),  # First wait times out
                0,  # Second wait succeeds after kill
            ]
            worker._process = mock_process

            worker._terminate_process()

            # Should call kill after timeout
            mock_process.kill.assert_called_once()

            # Should wait again after kill
            assert mock_process.wait.call_count == 2
            assert mock_process.wait.call_args_list[1][1]["timeout"] == 5
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_terminate_process_handles_none_process(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _terminate_process handles None process gracefully."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            worker._process = None

            # Should not raise exception
            worker._terminate_process()
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_cleanup_process_terminates_running_process(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _cleanup_process terminates running process."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = None  # Still running
            mock_process.wait.return_value = 0
            worker._process = mock_process

            worker._cleanup_process()

            # Should call terminate
            mock_process.terminate.assert_called()
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_cleanup_process_sets_process_to_none(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _cleanup_process sets _process to None after cleanup."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = 0  # Already terminated
            worker._process = mock_process

            worker._cleanup_process()

            assert worker._process is None
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_cleanup_process_logs_orphaned_process(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _cleanup_process with force kill fallback."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.pid = 99999
            mock_process.poll.return_value = None  # Still running

            # Mock _terminate_process to succeed without issue
            with patch.object(worker, "_terminate_process"):
                # wait() in _cleanup_process times out, then kill+wait succeeds
                mock_process.wait.side_effect = [
                    subprocess.TimeoutExpired("cmd", 2),  # Graceful timeout in _cleanup
                    None,  # Kill succeeds
                ]
                worker._process = mock_process

                # Should log error but force kill and succeed
                worker._cleanup_process()

                # Verify force kill was attempted
                mock_process.kill.assert_called_once()

                # Process should be set to None after successful force kill
                assert worker._process is None
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_request_stop_terminates_subprocess(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test request_stop terminates subprocess before calling parent."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = None
            mock_process.wait.return_value = 0
            worker._process = mock_process

            # Set to RUNNING state so request_stop works
            worker.set_state(WorkerState.STARTING)
            worker.set_state(WorkerState.RUNNING)

            worker.request_stop()

            # Should terminate subprocess
            mock_process.terminate.assert_called()
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop


# ============================================================================
# Test Signal Propagation
# ============================================================================


class TestSignalPropagation:
    """Test signal emission from worker thread."""

    def test_signals_emitted_across_thread_boundaries(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test signals are properly emitted from worker thread."""
        _mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            # Create spies for all signals
            spy_started = QSignalSpy(worker.command_started)
            spy_finished = QSignalSpy(worker.command_finished)
            spy_error = QSignalSpy(worker.command_error)

            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            # All signals should be emitted
            assert spy_started.count() == 1
            assert spy_finished.count() == 1
            assert spy_error.count() == 0  # No error
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_multiple_workers_emit_independent_signals(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test multiple workers emit independent signals."""
        _mock_popen, mock_process = mock_subprocess_popen

        worker1 = LauncherWorker("worker1", "nuke script1.nk")
        worker2 = LauncherWorker("worker2", "maya scene.ma")

        try:
            spy1 = QSignalSpy(worker1.command_started)
            spy2 = QSignalSpy(worker2.command_started)

            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker1.do_work()
            worker2.do_work()

            # Each worker should emit its own signal
            assert spy1.count() == 1
            assert spy1.at(0)[0] == "worker1"

            assert spy2.count() == 1
            assert spy2.at(0)[0] == "worker2"
        finally:
            worker1.safe_stop()
            worker2.safe_stop()
            worker1.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop
            worker2.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop


# ============================================================================
# Test Thread Safety
# ============================================================================


class TestThreadSafety:
    """Test thread-safe operations and concurrent access."""

    def test_process_attribute_access_is_safe(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test _process attribute can be safely accessed."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            # Should not raise even with no process
            worker._cleanup_process()
            worker._terminate_process()
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_concurrent_request_stop_is_safe(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test multiple request_stop calls are safe."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            worker.set_state(WorkerState.STARTING)
            worker.set_state(WorkerState.RUNNING)

            # Multiple calls should be safe
            result1 = worker.request_stop()
            result2 = worker.request_stop()

            assert result1 is True  # First should succeed
            assert result2 is False  # Second should indicate already stopping
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop


# ============================================================================
# Test Resource Cleanup
# ============================================================================


class TestResourceCleanup:
    """Test proper resource cleanup and memory management."""

    def test_worker_cleans_up_after_normal_execution(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test worker cleans up resources after normal execution."""
        _mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, "nuke script.nk")

        try:
            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            # Process should be cleaned up
            # Note: _process is set to None in cleanup
            assert worker._process is None or worker._process.poll() is not None
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_worker_cleans_up_after_exception(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test worker cleans up resources even after exception."""
        worker = LauncherWorker(worker_id, "invalid command")

        try:
            # This will raise SecurityError
            worker.do_work()

            # Should still clean up (no process created in this case)
            assert worker._process is None
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    # NOTE: Removed - causes segfault with Qt event loop in tests
    # def test_worker_can_be_safely_deleted(
    #     self,
    #     qapp: QApplication,
    #     worker_id: str,
    # ) -> None:
    #     """Test worker can be safely deleted without leaks."""
    #     worker = LauncherWorker(worker_id, "nuke")
    #
    #     # Should not raise on deletion
    #     worker.safe_stop()
    #     worker.deleteLater()
    #
    #     # Process Qt events to ensure cleanup
    #     QTimer.singleShot(10, qapp.quit)
    #     qapp.exec()


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_worker_with_empty_command(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test worker handles empty command."""
        worker = LauncherWorker(worker_id, "")

        try:
            spy_error = QSignalSpy(worker.command_error)

            worker.do_work()

            # Should emit error (empty command not in whitelist)
            assert spy_error.count() == 1
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_worker_with_whitespace_command(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test worker handles whitespace-only command."""
        worker = LauncherWorker(worker_id, "   ")

        try:
            spy_error = QSignalSpy(worker.command_error)

            worker.do_work()

            # Should emit error
            assert spy_error.count() == 1
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_worker_handles_command_with_quotes(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
        mock_subprocess_popen,
        mock_threading,
    ) -> None:
        """Test worker correctly parses command with quoted arguments."""
        mock_popen, mock_process = mock_subprocess_popen
        worker = LauncherWorker(worker_id, 'nuke "file with spaces.nk"')

        try:
            mock_process.wait.return_value = 0
            mock_process.poll.return_value = 0

            worker.do_work()

            call_args = mock_popen.call_args
            # shlex should properly handle the quoted filename
            assert len(call_args[0][0]) == 2
            assert call_args[0][0][0] == "nuke"
            assert "spaces" in call_args[0][0][1]
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_worker_handles_process_already_terminated(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test cleanup handles process that already terminated."""
        worker = LauncherWorker(worker_id, "nuke")

        try:
            mock_process = Mock()
            mock_process.poll.return_value = 0  # Already dead
            worker._process = mock_process

            # Should handle gracefully
            worker._cleanup_process()
            assert worker._process is None
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop

    def test_worker_handles_all_allowed_commands(
        self,
        qtbot: QtBot,
        qapp: QApplication,
        worker_id: str,
    ) -> None:
        """Test worker accepts all whitelisted commands."""
        allowed_commands = [
            "3de", "3de4", "3dequalizer",
            "nuke", "nuke_i", "nukex",
            "maya", "mayapy",
            "rv", "rvpkg",
            "houdini", "hython",
            "katana", "mari",
            "publish", "publish_standalone",
            "python", "python3",
        ]

        worker = LauncherWorker(worker_id, "test")
        try:
            for cmd in allowed_commands:
                # Should not raise SecurityError
                cmd_list, use_shell = worker._sanitize_command(f"{cmd} test.file")
                assert cmd_list[0] == cmd
                assert use_shell is False
        finally:
            worker.safe_stop()
            worker.deleteLater()
            qtbot.wait(1)  # Flush Qt event loop
