"""Comprehensive unit tests for LauncherProcessManager.

Testing the process lifecycle management, signal emissions, and resource cleanup.
Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real Qt components with signal testing
- Mock subprocess calls to avoid launching actual apps
- Thread safety validation
- Proper resource cleanup
"""

from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QMutex
from PySide6.QtTest import QSignalSpy

from launcher.models import ProcessInfo
from launcher.process_manager import LauncherProcessManager


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def process_manager(qapp: QApplication) -> LauncherProcessManager:
    """Create a LauncherProcessManager instance for testing."""
    manager = LauncherProcessManager()
    try:
        yield manager
    finally:
        # Cleanup
        manager.shutdown()
        manager.deleteLater()


@pytest.fixture
def mock_subprocess_popen():
    """Mock subprocess.Popen to avoid actually launching processes."""
    with patch("launcher.process_manager.subprocess.Popen") as mock_popen:
        # Create mock process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Process is running
        mock_process.wait.return_value = 0  # Success exit code
        mock_process.returncode = 0

        mock_popen.return_value = mock_process
        yield mock_popen, mock_process


@pytest.fixture
def mock_launcher_worker():
    """Mock LauncherWorker to avoid threading complexity."""
    with patch("launcher.process_manager.LauncherWorker") as mock_worker_class:
        mock_worker = Mock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = True

        mock_worker_class.return_value = mock_worker
        yield mock_worker_class, mock_worker


# ============================================================================
# Test Initialization
# ============================================================================


class TestInitialization:
    """Test LauncherProcessManager initialization."""

    def test_initialization_creates_empty_tracking(
        self, process_manager: LauncherProcessManager
    ) -> None:
        """Test manager initializes with empty process tracking."""
        assert len(process_manager._active_processes) == 0
        assert len(process_manager._active_workers) == 0
        assert process_manager.get_active_process_count() == 0

    def test_initialization_creates_timers(
        self, process_manager: LauncherProcessManager
    ) -> None:
        """Test manager creates cleanup timers."""
        assert process_manager._cleanup_timer is not None
        assert process_manager._cleanup_retry_timer is not None
        assert process_manager._cleanup_timer.isActive()  # Periodic timer should start

    def test_initialization_creates_mutexes(
        self, process_manager: LauncherProcessManager
    ) -> None:
        """Test manager creates thread-safe mutexes."""
        from PySide6.QtCore import (
            QRecursiveMutex,
        )
        # _process_lock is QRecursiveMutex, _cleanup_lock is QMutex
        assert isinstance(process_manager._process_lock, QRecursiveMutex)
        assert isinstance(process_manager._cleanup_lock, QMutex)

    def test_initialization_sets_cleanup_interval(
        self, process_manager: LauncherProcessManager
    ) -> None:
        """Test cleanup timer is configured correctly."""
        # Verify timer interval matches configuration
        assert process_manager._cleanup_timer.interval() == LauncherProcessManager.CLEANUP_INTERVAL_MS


# ============================================================================
# Test Subprocess Execution
# ============================================================================


class TestSubprocessExecution:
    """Test execute_with_subprocess functionality."""

    def test_execute_subprocess_success(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test successful subprocess execution."""
        mock_popen, mock_process = mock_subprocess_popen

        spy = QSignalSpy(process_manager.process_started)

        process_key = process_manager.execute_with_subprocess(
            launcher_id="test_launcher",
            launcher_name="Test Launcher",
            command=["echo", "hello"],
            working_dir="/tmp"
        )

        # Verify process was created
        assert process_key is not None
        assert "test_launcher" in process_key
        assert str(mock_process.pid) in process_key

        # Verify Popen was called correctly
        # Note: stderr is now captured to a log file instead of DEVNULL
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs["shell"] is False
        assert call_kwargs["stdout"] == subprocess.DEVNULL
        # stderr is now a file handle for log capture (not DEVNULL)
        assert hasattr(call_kwargs["stderr"], "write")  # File-like object
        assert call_kwargs["cwd"] == "/tmp"
        assert call_kwargs["start_new_session"] is True

        # Verify signal emitted
        assert spy.count() == 1
        signal_args = spy.at(0)
        assert signal_args[0] == "test_launcher"
        assert signal_args[1] == "echo hello"

    def test_execute_subprocess_tracks_process(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test subprocess is tracked in active processes."""
        _mock_popen, mock_process = mock_subprocess_popen

        process_key = process_manager.execute_with_subprocess(
            launcher_id="test_launcher",
            launcher_name="Test Launcher",
            command=["echo", "hello"]
        )

        # Verify process is tracked
        assert process_key in process_manager._active_processes
        assert process_manager.get_active_process_count() == 1

        # Verify ProcessInfo is correct
        process_info = process_manager._active_processes[process_key]
        assert isinstance(process_info, ProcessInfo)
        assert process_info.launcher_id == "test_launcher"
        assert process_info.launcher_name == "Test Launcher"
        assert process_info.command == "echo hello"
        assert process_info.process is mock_process

    def test_execute_subprocess_failure(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test subprocess execution failure handling."""
        spy_error = QSignalSpy(process_manager.process_error)

        with patch("launcher.process_manager.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = OSError("Command not found")

            process_key = process_manager.execute_with_subprocess(
                launcher_id="test_launcher",
                launcher_name="Test Launcher",
                command=["nonexistent_command"]
            )

        # Verify failure
        assert process_key is None
        assert spy_error.count() == 1
        signal_args = spy_error.at(0)
        assert signal_args[0] == "test_launcher"
        assert "Command not found" in signal_args[1]

    def test_execute_subprocess_without_working_dir(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test subprocess execution with no working directory."""
        mock_popen, _ = mock_subprocess_popen

        process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["echo", "test"],
            working_dir=None
        )

        # Verify cwd is None
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["cwd"] is None


# ============================================================================
# Test Worker Thread Execution
# ============================================================================


class TestWorkerExecution:
    """Test execute_with_worker functionality."""

    def test_execute_worker_success(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test successful worker thread execution."""
        mock_worker_class, mock_worker = mock_launcher_worker

        spy = QSignalSpy(process_manager.worker_created)

        result = process_manager.execute_with_worker(
            launcher_id="test_launcher",
            launcher_name="Test Launcher",
            command="echo hello",
            working_dir="/tmp"
        )

        # Verify worker was created (with parent for Qt ownership)
        assert result is True
        mock_worker_class.assert_called_once_with("test_launcher", "echo hello", "/tmp", parent=process_manager)

        # Verify worker was started
        mock_worker.start.assert_called_once()

        # Verify signal emitted
        assert spy.count() == 1

    def test_execute_worker_tracks_worker(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test worker is tracked in active workers."""
        _mock_worker_class, mock_worker = mock_launcher_worker

        process_manager.execute_with_worker(
            launcher_id="test_launcher",
            launcher_name="Test Launcher",
            command="echo hello"
        )

        # Verify worker is tracked
        assert process_manager.get_active_process_count() == 1
        workers = process_manager.get_active_workers_dict()
        assert len(workers) == 1

        # Verify worker is in the dict
        worker_key = next(iter(workers.keys()))
        assert "test_launcher" in worker_key
        assert workers[worker_key] is mock_worker

    def test_execute_worker_connects_signals(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test worker signals are connected properly."""
        _mock_worker_class, mock_worker = mock_launcher_worker

        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Verify signals were connected
        assert mock_worker.command_started.connect.called
        assert mock_worker.command_finished.connect.called
        assert mock_worker.command_error.connect.called

    def test_execute_worker_failure(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test worker creation failure handling."""
        spy_error = QSignalSpy(process_manager.process_error)

        with patch("launcher.process_manager.LauncherWorker") as mock_worker_class:
            mock_worker_class.side_effect = Exception("Worker creation failed")

            result = process_manager.execute_with_worker(
                launcher_id="test",
                launcher_name="Test",
                command="echo test"
            )

        # Verify failure
        assert result is False
        assert spy_error.count() == 1


# ============================================================================
# Test Process Lifecycle
# ============================================================================


class TestProcessLifecycle:
    """Test process lifecycle management."""

    def test_worker_finished_signal_cleanup(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test worker cleanup on finished signal."""
        _mock_worker_class, _mock_worker = mock_launcher_worker
        spy_removed = QSignalSpy(process_manager.worker_removed)
        spy_finished = QSignalSpy(process_manager.process_finished)

        # Create and track a worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Get the worker key
        workers = process_manager.get_active_workers_dict()
        worker_key = next(iter(workers.keys()))

        # Simulate worker finished by calling the handler directly
        process_manager._on_worker_finished(worker_key, "test", True, 0)

        # Verify cleanup
        assert spy_removed.count() == 1
        assert spy_finished.count() == 1

        # Worker should be removed
        workers = process_manager.get_active_workers_dict()
        assert worker_key not in workers

    def test_cleanup_finished_processes(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test cleanup removes finished processes."""
        _mock_popen, mock_process = mock_subprocess_popen

        # Create a process
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["echo", "test"]
        )

        # Mark process as finished
        mock_process.poll.return_value = 0  # Finished with exit code 0

        # Trigger cleanup
        process_manager._cleanup_finished_processes()

        # Verify process was removed
        assert process_key not in process_manager._active_processes

    def test_cleanup_finished_workers(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test cleanup removes finished workers."""
        _mock_worker_class, mock_worker = mock_launcher_worker
        spy_removed = QSignalSpy(process_manager.worker_removed)

        # Create a worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Mark worker as finished
        mock_worker.isRunning.return_value = False

        # Trigger cleanup
        process_manager._cleanup_finished_workers()

        # Verify worker was removed
        assert spy_removed.count() == 1
        assert len(process_manager.get_active_workers_dict()) == 0

    def test_periodic_cleanup_runs(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test periodic cleanup is triggered automatically."""
        _mock_popen, mock_process = mock_subprocess_popen

        # Create a process
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["echo", "test"]
        )

        # Initially process is running
        assert process_key in process_manager._active_processes

        # Mark process as finished
        mock_process.poll.return_value = 0

        # Manually trigger cleanup instead of waiting 6 seconds
        process_manager._periodic_cleanup()

        # Process should be cleaned up
        assert process_key not in process_manager._active_processes


# ============================================================================
# Test Signal Emissions
# ============================================================================


class TestSignalEmissions:
    """Test Qt signal emissions."""

    def test_process_started_signal(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test process_started signal emission."""
        spy = QSignalSpy(process_manager.process_started)

        process_manager.execute_with_subprocess(
            launcher_id="nuke",
            launcher_name="Nuke",
            command=["nuke", "--safe"]
        )

        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == "nuke"
        assert args[1] == "nuke --safe"

    def test_process_error_signal(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test process_error signal emission."""
        spy = QSignalSpy(process_manager.process_error)

        with patch("launcher.process_manager.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("nuke not found")

            process_manager.execute_with_subprocess(
                launcher_id="nuke",
                launcher_name="Nuke",
                command=["nuke"]
            )

        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == "nuke"
        assert "nuke not found" in args[1]

    def test_worker_created_signal(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test worker_created signal emission."""
        spy = QSignalSpy(process_manager.worker_created)

        process_manager.execute_with_worker(
            launcher_id="maya",
            launcher_name="Maya",
            command="maya -batch"
        )

        assert spy.count() == 1

    def test_worker_removed_signal(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test worker_removed signal emission."""
        _mock_worker_class, mock_worker = mock_launcher_worker
        spy = QSignalSpy(process_manager.worker_removed)

        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Mark as finished and cleanup
        mock_worker.isRunning.return_value = False
        process_manager._cleanup_finished_workers()

        assert spy.count() == 1

    def test_process_finished_signal(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test process_finished signal emission."""
        spy = QSignalSpy(process_manager.process_finished)

        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Get worker key
        workers = process_manager.get_active_workers_dict()
        worker_key = next(iter(workers.keys()))

        # Trigger finish
        process_manager._on_worker_finished(worker_key, "test", True, 0)

        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == "test"
        assert args[1] is True
        assert args[2] == 0


# ============================================================================
# Test Process Termination
# ============================================================================


class TestProcessTermination:
    """Test process termination functionality."""

    def test_terminate_subprocess_graceful(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test graceful subprocess termination."""
        _mock_popen, mock_process = mock_subprocess_popen

        # Create process
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["sleep", "100"]
        )

        # Terminate gracefully (non-blocking)
        result = process_manager.terminate_process(process_key, force=False)

        assert result is True
        mock_process.terminate.assert_called_once()
        # Note: terminate_process uses non-blocking poll() instead of wait()
        # The actual termination check happens via QTimer callbacks
        mock_process.poll.assert_called()

    def test_terminate_subprocess_force_kill(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test force kill of subprocess."""
        _mock_popen, mock_process = mock_subprocess_popen

        # Create process
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["sleep", "100"]
        )

        # Force kill
        result = process_manager.terminate_process(process_key, force=True)

        assert result is True
        mock_process.kill.assert_called_once()

    def test_terminate_worker(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test worker termination."""
        _mock_worker_class, mock_worker = mock_launcher_worker
        spy = QSignalSpy(process_manager.worker_removed)

        # Make worker appear stopped
        mock_worker.isRunning.return_value = False

        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Get worker key
        workers = process_manager.get_active_workers_dict()
        worker_key = next(iter(workers.keys()))

        # Terminate (non-blocking)
        result = process_manager.terminate_process(worker_key, force=False)

        assert result is True
        mock_worker.request_stop.assert_called_once()
        # Signal emission happens via QTimer callback - wait for it
        qtbot.waitUntil(lambda: spy.count() == 1, timeout=2000)

    def test_terminate_nonexistent_process(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test terminating non-existent process."""
        result = process_manager.terminate_process("nonexistent_key", force=False)

        assert result is False

    def test_terminate_subprocess_timeout_fallback(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test force kill fallback when graceful termination times out.

        Note: The current implementation uses non-blocking poll() checks via
        QTimer callbacks. This test verifies the basic flow is initiated.
        The actual timeout and kill behavior happens asynchronously.
        """
        _mock_popen, mock_process = mock_subprocess_popen
        spy = QSignalSpy(process_manager.process_finished)

        # Make poll() return None (process still running) initially,
        # then return 0 (terminated) after enough iterations
        poll_call_count = [0]

        def poll_side_effect():
            poll_call_count[0] += 1
            # Return None for first several calls (process still running)
            # Then return exit code to indicate termination
            if poll_call_count[0] > 3:
                return 0  # Process terminated
            return None  # Still running

        mock_process.poll.side_effect = poll_side_effect

        # Create process
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["sleep", "100"]
        )

        # Terminate (non-blocking - starts async polling)
        result = process_manager.terminate_process(process_key, force=False)

        assert result is True
        mock_process.terminate.assert_called_once()
        # Non-blocking implementation uses poll() via QTimer callbacks
        # Wait for signal emission (indicating termination completed)
        qtbot.waitUntil(lambda: spy.count() >= 1, timeout=5000)


# ============================================================================
# Test Process Information
# ============================================================================


class TestProcessInformation:
    """Test process information retrieval."""

    def test_get_active_process_count(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test counting active processes and workers."""
        # Create subprocess
        process_manager.execute_with_subprocess(
            launcher_id="test1",
            launcher_name="Test 1",
            command=["echo", "test1"]
        )

        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test2",
            launcher_name="Test 2",
            command="echo test2"
        )

        # Should count both
        assert process_manager.get_active_process_count() == 2

    def test_get_active_process_info_subprocess(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test getting subprocess information."""
        _mock_popen, _mock_process = mock_subprocess_popen

        process_manager.execute_with_subprocess(
            launcher_id="nuke",
            launcher_name="Nuke",
            command=["nuke", "--safe"]
        )

        info_list = process_manager.get_active_process_info()

        assert len(info_list) == 1
        info = info_list[0]
        assert info["type"] == "subprocess"
        assert info["launcher_id"] == "nuke"
        assert info["launcher_name"] == "Nuke"
        assert info["command"] == "nuke --safe"
        assert info["pid"] == 12345
        assert info["running"] is True

    def test_get_active_process_info_worker(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test getting worker information."""
        _mock_worker_class, mock_worker = mock_launcher_worker

        # Set launcher_id on mock worker (it's accessed via getattr in get_active_process_info)
        mock_worker.launcher_id = "maya"
        mock_worker.command = "maya -batch"

        process_manager.execute_with_worker(
            launcher_id="maya",
            launcher_name="Maya",
            command="maya -batch"
        )

        info_list = process_manager.get_active_process_info()

        assert len(info_list) == 1
        info = info_list[0]
        assert info["type"] == "worker"
        assert info["launcher_id"] == "maya"
        assert info["command"] == "maya -batch"
        assert info["running"] is True

    def test_get_active_processes_dict(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test getting dict of active processes."""
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["echo", "test"]
        )

        processes = process_manager.get_active_processes_dict()

        assert len(processes) == 1
        assert process_key in processes
        assert isinstance(processes[process_key], ProcessInfo)

    def test_get_active_workers_dict(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test getting dict of active workers."""
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        workers = process_manager.get_active_workers_dict()

        assert len(workers) == 1


# ============================================================================
# Test Thread Safety
# ============================================================================


class TestThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_process_creation(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test creating multiple processes concurrently."""
        # Create multiple processes rapidly
        keys = []
        for i in range(5):
            key = process_manager.execute_with_subprocess(
                launcher_id=f"test{i}",
                launcher_name=f"Test {i}",
                command=["echo", f"test{i}"]
            )
            keys.append(key)

        # All should be tracked
        assert process_manager.get_active_process_count() == 5

        # All keys should be unique
        assert len(set(keys)) == 5

    def test_process_access_thread_safe(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test thread-safe access to process information."""
        process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["echo", "test"]
        )

        # Getting dicts should be thread-safe (returns copy)
        processes1 = process_manager.get_active_processes_dict()
        processes2 = process_manager.get_active_processes_dict()

        # Should be equal but not the same object
        assert processes1 == processes2
        assert processes1 is not processes2

    def test_cleanup_during_process_creation(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test cleanup doesn't interfere with process creation."""
        _mock_popen, _mock_process = mock_subprocess_popen

        # Create process
        process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["echo", "test"]
        )

        # Trigger cleanup while process is running
        process_manager._periodic_cleanup()

        # Process should still be tracked (not finished)
        assert process_manager.get_active_process_count() == 1


# ============================================================================
# Test Resource Cleanup
# ============================================================================


class TestResourceCleanup:
    """Test resource cleanup and shutdown."""

    def test_stop_all_workers_stops_timers(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test stopping all workers stops timers."""
        assert process_manager._cleanup_timer.isActive()

        process_manager.stop_all_workers()

        assert not process_manager._cleanup_timer.isActive()
        assert not process_manager._cleanup_retry_timer.isActive()

    def test_stop_all_workers_terminates_processes(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test stopping all workers terminates subprocesses."""
        _mock_popen, mock_process = mock_subprocess_popen

        # Create process
        process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["sleep", "100"]
        )

        process_manager.stop_all_workers()

        # Process should be terminated
        mock_process.terminate.assert_called()

    def test_stop_all_workers_stops_workers(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test stopping all workers stops worker threads."""
        _mock_worker_class, mock_worker = mock_launcher_worker

        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        process_manager.stop_all_workers()

        # Worker should be stopped
        mock_worker.request_stop.assert_called()
        mock_worker.wait.assert_called()

    def test_shutdown_calls_stop_all_workers(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test shutdown calls stop_all_workers."""
        with patch.object(process_manager, "stop_all_workers") as mock_stop:
            process_manager.shutdown()

            mock_stop.assert_called_once()

    def test_cleanup_clears_tracking_dicts(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test stop_all_workers clears tracking dictionaries."""
        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        process_manager.stop_all_workers()

        # Workers should be cleared
        assert len(process_manager._active_workers) == 0


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_execute_empty_command_list(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test executing with empty command list."""
        spy_error = QSignalSpy(process_manager.process_error)

        with patch("launcher.process_manager.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = ValueError("Empty command")

            result = process_manager.execute_with_subprocess(
                launcher_id="test",
                launcher_name="Test",
                command=[]
            )

        assert result is None
        assert spy_error.count() == 1

    def test_cleanup_with_no_processes(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test cleanup when no processes are running."""
        # Should not crash
        process_manager._cleanup_finished_processes()
        process_manager._cleanup_finished_workers()
        process_manager._periodic_cleanup()

    def test_terminate_during_shutdown(
        self,
        process_manager: LauncherProcessManager,
        mock_subprocess_popen,
        qtbot: QtBot
    ) -> None:
        """Test cleanup during shutdown doesn't execute."""
        _mock_popen, _mock_process = mock_subprocess_popen

        # Create process
        process_key = process_manager.execute_with_subprocess(
            launcher_id="test",
            launcher_name="Test",
            command=["sleep", "100"]
        )

        # Mark as shutting down
        process_manager._shutting_down = True

        # Cleanup should not run
        process_manager._cleanup_finished_processes()

        # Process should still be tracked (cleanup skipped)
        assert process_key in process_manager._active_processes

    def test_worker_finished_after_removal(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test handling worker finished signal after worker already removed."""
        # Call finish handler with non-existent key
        # Should not crash
        process_manager._on_worker_finished("nonexistent_key", "test", True, 0)

    def test_generate_process_key_uniqueness(
        self,
        process_manager: LauncherProcessManager,
        qtbot: QtBot
    ) -> None:
        """Test process key generation creates unique keys."""
        keys = set()
        for i in range(100):
            key = process_manager._generate_process_key("launcher", 12345 + i)
            keys.add(key)

        # All keys should be unique
        assert len(keys) == 100

    def test_multiple_signals_disconnection(
        self,
        process_manager: LauncherProcessManager,
        mock_launcher_worker,
        qtbot: QtBot
    ) -> None:
        """Test signal disconnection handles already disconnected signals."""
        _mock_worker_class, mock_worker = mock_launcher_worker

        # Make disconnect raise RuntimeError (already disconnected)
        mock_worker.command_started.disconnect.side_effect = RuntimeError("Not connected")
        mock_worker.command_finished.disconnect.side_effect = RuntimeError("Not connected")
        mock_worker.command_error.disconnect.side_effect = RuntimeError("Not connected")

        # Create worker
        process_manager.execute_with_worker(
            launcher_id="test",
            launcher_name="Test",
            command="echo test"
        )

        # Mark as finished - should handle disconnection errors
        mock_worker.isRunning.return_value = False
        process_manager._cleanup_finished_workers()

        # Should complete without crashing
        assert len(process_manager._active_workers) == 0


# ============================================================================
# Test ProcessInfo
# ============================================================================


class TestProcessInfo:
    """Test ProcessInfo dataclass."""

    def test_process_info_creation(self) -> None:
        """Test creating ProcessInfo instance."""
        mock_process = Mock()
        mock_process.pid = 12345

        info = ProcessInfo(
            process=mock_process,
            launcher_id="test_launcher",
            launcher_name="Test Launcher",
            command="echo hello",
            timestamp=time.time()
        )

        assert info.process is mock_process
        assert info.launcher_id == "test_launcher"
        assert info.launcher_name == "Test Launcher"
        assert info.command == "echo hello"
        assert info.validated is False

    def test_process_info_validation_flag(self) -> None:
        """Test validation flag in ProcessInfo."""
        mock_process = Mock()

        info = ProcessInfo(
            process=mock_process,
            launcher_id="test",
            launcher_name="Test",
            command="echo test",
            timestamp=time.time()
        )

        # Initially not validated
        assert info.validated is False

        # Can be set
        info.validated = True
        assert info.validated is True
