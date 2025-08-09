"""Unit tests for QProcess migration components.

This test suite validates the QProcess-based process management system,
ensuring thread safety, proper resource management, and backward compatibility.
"""

import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QProcess

from command_launcher_qprocess import CommandLauncherQProcess, CommandLauncherWorker
from qprocess_manager import (
    ProcessConfig,
    ProcessInfo,
    ProcessState,
    ProcessWorker,
    QProcessManager,
    TerminalLauncher,
)
from shot_model_qprocess import ShotModelQProcess, ShotRefreshWorker


class TestProcessConfig:
    """Test ProcessConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ProcessConfig(command="echo")

        assert config.command == "echo"
        assert config.arguments == []
        assert config.working_directory is None
        assert config.environment is None
        assert config.use_shell is False
        assert config.interactive_bash is False
        assert config.terminal is False
        assert config.terminal_persist is False
        assert config.timeout_ms == 30000
        assert config.capture_output is True
        assert config.merge_output is False

    def test_to_shell_command(self):
        """Test shell command generation."""
        # Simple command
        config = ProcessConfig(command="ls")
        assert config.to_shell_command() == "ls"

        # Command with arguments
        config = ProcessConfig(command="echo", arguments=["hello", "world"])
        assert config.to_shell_command() == "echo hello world"

        # Command with special characters
        config = ProcessConfig(command="echo", arguments=["hello world", "test&file"])
        assert config.to_shell_command() == "echo 'hello world' 'test&file'"


class TestProcessInfo:
    """Test ProcessInfo dataclass."""

    def test_duration_calculation(self):
        """Test process duration calculation."""
        config = ProcessConfig(command="test")
        info = ProcessInfo(
            process_id="test_123", config=config, state=ProcessState.RUNNING
        )

        # No start time
        assert info.duration is None

        # With start time, no end time
        info.start_time = time.time() - 5
        assert 4.9 < info.duration < 5.1

        # With both start and end time
        info.end_time = info.start_time + 10
        assert 9.9 < info.duration < 10.1

    def test_is_active_states(self):
        """Test is_active property for different states."""
        config = ProcessConfig(command="test")
        info = ProcessInfo(
            process_id="test_123", config=config, state=ProcessState.PENDING
        )

        # Active states
        for state in [
            ProcessState.PENDING,
            ProcessState.STARTING,
            ProcessState.RUNNING,
        ]:
            info.state = state
            assert info.is_active

        # Inactive states
        for state in [
            ProcessState.FINISHED,
            ProcessState.FAILED,
            ProcessState.TERMINATED,
            ProcessState.CRASHED,
        ]:
            info.state = state
            assert not info.is_active


class TestProcessWorker:
    """Test ProcessWorker thread."""

    @pytest.fixture
    def worker(self):
        """Create a test worker."""
        config = ProcessConfig(command="echo", arguments=["test"], capture_output=True)
        return ProcessWorker("test_worker", config)

    def test_worker_initialization(self, worker):
        """Test worker initialization."""
        assert worker.process_id == "test_worker"
        assert worker.config.command == "echo"
        assert worker._process is None
        assert not worker._should_stop.is_set()

    def test_worker_signals(self, qtbot, worker):
        """Test worker signal emissions."""
        # Connect signal spies
        with qtbot.waitSignal(worker.started, timeout=1000) as start_spy:
            with qtbot.waitSignal(worker.finished, timeout=1000) as finish_spy:
                worker.start()
                worker.wait()

        # Check signal data
        assert start_spy.args[0] == "test_worker"
        assert finish_spy.args[0] == "test_worker"
        assert isinstance(finish_spy.args[1], int)  # exit code
        assert isinstance(finish_spy.args[2], QProcess.ExitStatus)

    def test_worker_stop(self, worker):
        """Test worker stop functionality."""
        worker._should_stop.set()
        assert worker._should_stop.is_set()

        # Mock process for termination test
        mock_process = Mock(spec=QProcess)
        mock_process.state.return_value = QProcess.Running
        worker._process = mock_process

        worker.stop()
        mock_process.terminate.assert_called_once()

    def test_worker_timeout(self, qtbot):
        """Test worker timeout handling."""
        config = ProcessConfig(
            command="sleep",
            arguments=["10"],
            timeout_ms=100,  # 100ms timeout
        )
        worker = ProcessWorker("timeout_test", config)

        # Should timeout and emit failed signal
        with qtbot.waitSignal(worker.failed, timeout=1000):
            worker.start()
            worker.wait()

        info = worker.get_info()
        assert info.state == ProcessState.TERMINATED


class TestTerminalLauncher:
    """Test TerminalLauncher functionality."""

    def test_terminal_detection(self):
        """Test terminal emulator detection."""
        launcher = TerminalLauncher()

        # Skip test if no terminals available (e.g., headless environment)
        if len(launcher._available_terminals) == 0:
            pytest.skip("No terminal emulators available in this environment")
        
        # Should detect at least one terminal on Linux
        if sys.platform.startswith("linux"):
            assert len(launcher._available_terminals) > 0

    @patch("qprocess_manager.QProcess")
    def test_launch_in_terminal(self, mock_qprocess_class):
        """Test launching command in terminal."""
        mock_process = Mock(spec=QProcess)
        mock_qprocess_class.return_value = mock_process
        mock_process.startDetached.return_value = True

        launcher = TerminalLauncher()
        launcher._available_terminals = [
            {
                "name": "test-terminal",
                "command": ["test-terminal", "--"],
                "args_prefix": ["bash", "-c"],
            }
        ]

        result = launcher.launch_in_terminal(
            "echo test", working_directory="/tmp", persist=False
        )

        assert result is not None
        mock_process.setWorkingDirectory.assert_called_with("/tmp")
        mock_process.startDetached.assert_called_once()

    def test_no_terminals_available(self):
        """Test handling when no terminals are available."""
        launcher = TerminalLauncher()
        launcher._available_terminals = []

        result = launcher.launch_in_terminal("echo test")
        assert result is None


class TestQProcessManager:
    """Test QProcessManager central management."""

    @pytest.fixture
    def manager(self, qtbot):
        """Create a test manager."""
        manager = QProcessManager()
        # QProcessManager is a QObject, not a QWidget, so we don't add it to qtbot
        yield manager
        manager.shutdown()

    def test_manager_initialization(self, manager):
        """Test manager initialization."""
        assert len(manager._processes) == 0
        assert len(manager._workers) == 0
        assert not manager._shutting_down
        assert manager._cleanup_timer.isActive()

    def test_execute_simple_command(self, manager, qtbot):
        """Test executing a simple command."""
        process_id = manager.execute(
            command="echo", arguments=["hello"], capture_output=True
        )

        assert process_id is not None
        assert process_id in manager._processes

        # Wait for completion
        info = manager.wait_for_process(process_id, timeout_ms=2000)
        assert info is not None
        assert info.exit_code == 0
        assert info.state == ProcessState.FINISHED

    def test_execute_shell_command(self, manager):
        """Test executing a shell command."""
        process_id = manager.execute_shell(command="echo $HOME", capture_output=True)

        assert process_id is not None
        assert process_id.startswith("shell_")

        # Wait for completion
        info = manager.wait_for_process(process_id, timeout_ms=2000)
        assert info is not None
        assert info.exit_code == 0

    def test_execute_ws_command(self, manager):
        """Test executing a workspace command."""
        with patch.object(manager, "execute") as mock_execute:
            mock_execute.return_value = "ws_test_123"

            process_id = manager.execute_ws_command(
                workspace_path="/shows/test/shots/seq/shot",
                command="nuke",
                terminal=False,
            )

            assert process_id == "ws_test_123"
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args[1]
            assert call_args["interactive_bash"] is True
            assert "ws /shows/test/shots/seq/shot && nuke" in call_args["command"]

    def test_process_limit(self, manager):
        """Test process limit enforcement."""
        # Fill up to limit
        manager._processes = {
            f"proc_{i}": ProcessInfo(
                process_id=f"proc_{i}",
                config=ProcessConfig(command="test"),
                state=ProcessState.RUNNING,
            )
            for i in range(manager.MAX_CONCURRENT_PROCESSES)
        }

        # Try to execute one more
        process_id = manager.execute("echo", ["test"])
        assert process_id is None

    def test_terminate_process(self, manager, qtbot):
        """Test process termination."""
        # Start a long-running process
        process_id = manager.execute(
            command="sleep", arguments=["10"], capture_output=False
        )

        assert process_id is not None

        # Give it time to start
        qtbot.wait(100)

        # Terminate it
        success = manager.terminate_process(process_id)
        assert success

        # Wait for termination
        info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert info is not None
        assert info.state in [ProcessState.TERMINATED, ProcessState.FAILED]

    def test_get_active_processes(self, manager):
        """Test getting active processes."""
        # Start multiple processes
        process_ids = []
        for i in range(3):
            pid = manager.execute("echo", [f"test_{i}"])
            if pid:
                process_ids.append(pid)

        # Check active processes
        active = manager.get_active_processes()
        assert len(active) <= 3  # Some may have finished already

        # Wait for all to complete
        for pid in process_ids:
            manager.wait_for_process(pid, timeout_ms=2000)

        # Should have no active processes
        active = manager.get_active_processes()
        assert len(active) == 0

    def test_periodic_cleanup(self, manager, qtbot):
        """Test periodic cleanup of old processes."""
        # Create old finished process
        old_info = ProcessInfo(
            process_id="old_proc",
            config=ProcessConfig(command="test"),
            state=ProcessState.FINISHED,
            end_time=time.time() - 7200,  # 2 hours ago
        )

        manager._processes["old_proc"] = old_info

        # Trigger cleanup
        manager._periodic_cleanup()

        # Old process should be removed
        assert "old_proc" not in manager._processes

    def test_shutdown(self, manager):
        """Test manager shutdown."""
        # Start a process
        process_id = manager.execute("sleep", ["1"])

        # Shutdown
        manager.shutdown()

        assert manager._shutting_down
        assert not manager._cleanup_timer.isActive()


class TestShotModelQProcess:
    """Test QProcess-based ShotModel."""

    @pytest.fixture
    def model(self, qtbot):
        """Create a test model."""
        model = ShotModelQProcess(load_cache=False)
        # ShotModelQProcess is a QObject, not a QWidget, so we don't add it to qtbot
        yield model
        model.cleanup()

    def test_model_initialization(self, model):
        """Test model initialization."""
        assert len(model.shots) == 0
        assert not model._is_refreshing
        assert model._refresh_worker is None

    @patch.object(QProcessManager, "execute")
    @patch.object(QProcessManager, "wait_for_process")
    def test_refresh_shots_blocking(self, mock_wait, mock_execute, model):
        """Test blocking shot refresh."""
        # Mock process execution
        mock_execute.return_value = "ws_test_123"
        mock_wait.return_value = ProcessInfo(
            process_id="ws_test_123",
            config=ProcessConfig(command="ws -sg"),
            state=ProcessState.FINISHED,
            exit_code=0,
            output_buffer=[
                "workspace /shows/test/shots/seq/shot_001",
                "workspace /shows/test/shots/seq/shot_002",
            ],
        )

        # Perform blocking refresh
        result = model.refresh_shots(blocking=True)

        assert result.success
        assert result.has_changes
        assert len(model.shots) == 2
        assert model.shots[0].shot == "shot_001"
        assert model.shots[1].shot == "shot_002"

    def test_refresh_shots_async(self, model, qtbot):
        """Test asynchronous shot refresh."""
        with patch.object(model, "_start_refresh_worker") as mock_start:
            # Start async refresh
            result = model.refresh_shots(blocking=False)

            assert result.success
            assert not result.has_changes  # Returns immediately
            mock_start.assert_called_once()

    def test_refresh_already_running(self, model):
        """Test preventing concurrent refreshes."""
        model._is_refreshing = True

        result = model.refresh_shots()

        assert not result.success
        assert not result.has_changes

    def test_cancel_refresh(self, model):
        """Test canceling refresh operation."""
        # Create mock worker
        mock_worker = Mock(spec=ShotRefreshWorker)
        mock_worker.isRunning.return_value = True
        model._refresh_worker = mock_worker
        model._is_refreshing = True

        model.cancel_refresh()

        mock_worker.stop.assert_called_once()
        assert not model._is_refreshing

    def test_refresh_worker_signals(self, qtbot):
        """Test refresh worker signal handling."""
        manager = QProcessManager()
        worker = ShotRefreshWorker(manager, [])

        # Connect signal spy
        with qtbot.waitSignal(worker.refresh_started, timeout=100):
            worker.refresh_started.emit()

        with qtbot.waitSignal(worker.refresh_error, timeout=100) as spy:
            worker.refresh_error.emit("Test error")

        assert spy.args[0] == "Test error"


class TestCommandLauncherQProcess:
    """Test QProcess-based CommandLauncher."""

    @pytest.fixture
    def launcher(self, qtbot):
        """Create a test launcher."""
        launcher = CommandLauncherQProcess()
        # CommandLauncherQProcess is a QObject, not a QWidget, so we don't add it to qtbot
        yield launcher
        launcher.cleanup()

    def test_launcher_initialization(self, launcher):
        """Test launcher initialization."""
        assert launcher.current_shot is None
        assert len(launcher._active_workers) == 0

    @patch.object(QProcessManager, "execute_ws_command")
    def test_launch_app_blocking(self, mock_execute, launcher):
        """Test blocking app launch."""
        from shot_model import Shot

        # Set current shot
        shot = Shot(
            show="test",
            sequence="seq",
            shot="001",
            workspace_path="/shows/test/shots/seq/001",
        )
        launcher.set_current_shot(shot)

        # Mock execution
        mock_execute.return_value = "app_test_123"

        # Launch app
        success = launcher.launch_app("nuke", blocking=True)

        assert success
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args[1]
        assert call_kwargs["workspace_path"] == shot.workspace_path
        assert "nuke" in call_kwargs["command"]

    def test_launch_app_no_shot(self, launcher, qtbot):
        """Test launching without shot context."""
        with qtbot.waitSignal(launcher.command_error, timeout=100):
            success = launcher.launch_app("nuke")

        assert not success

    def test_launch_app_unknown(self, launcher, qtbot):
        """Test launching unknown application."""
        from shot_model import Shot

        shot = Shot(
            show="test",
            sequence="seq",
            shot="001",
            workspace_path="/shows/test/shots/seq/001",
        )
        launcher.set_current_shot(shot)

        with qtbot.waitSignal(launcher.command_error, timeout=100):
            success = launcher.launch_app("unknown_app")

        assert not success

    @patch("command_launcher_qprocess.RawPlateFinder")
    @patch("command_launcher_qprocess.UndistortionFinder")
    @patch.object(QProcessManager, "execute_ws_command")
    def test_launch_with_plates_and_undistortion(
        self, mock_execute, mock_undist_finder, mock_plate_finder, launcher
    ):
        """Test launching with raw plates and undistortion."""
        from shot_model import Shot

        # Set current shot
        shot = Shot(
            show="test",
            sequence="seq",
            shot="001",
            workspace_path="/shows/test/shots/seq/001",
        )
        launcher.set_current_shot(shot)

        # Mock finders
        mock_plate_finder.find_latest_raw_plate.return_value = "/path/to/plate.####.exr"
        mock_plate_finder.verify_plate_exists.return_value = True
        mock_plate_finder.get_version_from_path.return_value = "v001"

        mock_undist_finder.find_latest_undistortion.return_value = Path(
            "/path/to/undist.nk"
        )
        mock_undist_finder.get_version_from_path.return_value = "v002"

        mock_execute.return_value = "nuke_test_123"

        # Launch with plates and undistortion
        success = launcher.launch_app(
            "nuke", include_raw_plate=True, include_undistortion=True, blocking=True
        )

        assert success
        call_kwargs = mock_execute.call_args[1]
        assert "/path/to/plate.####.exr" in call_kwargs["command"]
        assert "/path/to/undist.nk" in call_kwargs["command"]

    def test_launch_async_worker(self, launcher, qtbot):
        """Test asynchronous launch with worker."""
        from shot_model import Shot

        shot = Shot(
            show="test",
            sequence="seq",
            shot="001",
            workspace_path="/shows/test/shots/seq/001",
        )
        launcher.set_current_shot(shot)

        with patch.object(launcher, "_launch_async") as mock_launch:
            launcher.launch_app("nuke", blocking=False)
            mock_launch.assert_called_once()

    def test_cleanup_finished_workers(self, launcher):
        """Test cleaning up finished workers."""
        # Create mock finished worker
        mock_worker = Mock(spec=CommandLauncherWorker)
        mock_worker.isFinished.return_value = True
        launcher._active_workers = [mock_worker]

        launcher._cleanup_finished_workers()

        assert len(launcher._active_workers) == 0
        mock_worker.deleteLater.assert_called_once()


class TestThreadSafety:
    """Test thread safety of process management."""

    def test_concurrent_process_creation(self, qtbot):
        """Test creating multiple processes concurrently."""
        manager = QProcessManager()
        # QProcessManager is a QObject, not a QWidget

        process_ids = []

        def create_process(index):
            pid = manager.execute("echo", [f"test_{index}"])
            if pid:
                process_ids.append(pid)

        # Create processes from multiple threads
        import threading

        threads = []
        for i in range(10):
            t = threading.Thread(target=create_process, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # All should have been created
        assert len(process_ids) == 10
        assert len(set(process_ids)) == 10  # All unique

        manager.shutdown()

    def test_concurrent_termination(self, qtbot):
        """Test terminating processes from multiple threads."""
        manager = QProcessManager()
        # QProcessManager is a QObject, not a QWidget

        # Create processes
        process_ids = []
        for i in range(5):
            pid = manager.execute("sleep", ["10"])
            if pid:
                process_ids.append(pid)

        # Terminate from multiple threads
        import threading

        def terminate_process(pid):
            manager.terminate_process(pid)

        threads = []
        for pid in process_ids:
            t = threading.Thread(target=terminate_process, args=(pid,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # All should be terminated
        qtbot.wait(1000)
        active = manager.get_active_processes()
        assert len(active) == 0

        manager.shutdown()


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_shot_model_api_compatibility(self):
        """Test ShotModel maintains API compatibility."""
        from shot_model import ShotModel
        from shot_model_qprocess import ShotModelQProcess

        # Check that QProcess version has all required methods
        original_methods = [m for m in dir(ShotModel) if not m.startswith("_")]
        qprocess_methods = [m for m in dir(ShotModelQProcess) if not m.startswith("_")]

        for method in original_methods:
            if method not in ["cache_manager", "shots"]:  # Skip properties
                assert method in qprocess_methods, f"Missing method: {method}"

    def test_command_launcher_api_compatibility(self):
        """Test CommandLauncher maintains API compatibility."""
        from command_launcher import CommandLauncher
        from command_launcher_qprocess import CommandLauncherQProcess

        # Check that QProcess version has all required methods
        original_methods = [m for m in dir(CommandLauncher) if not m.startswith("_")]
        qprocess_methods = [
            m for m in dir(CommandLauncherQProcess) if not m.startswith("_")
        ]

        for method in original_methods:
            if method not in ["current_shot"]:  # Skip properties
                assert method in qprocess_methods, f"Missing method: {method}"

    def test_signal_compatibility(self):
        """Test that signals remain compatible."""
        from command_launcher import CommandLauncher
        from command_launcher_qprocess import CommandLauncherQProcess

        original = CommandLauncher()
        qprocess = CommandLauncherQProcess()

        # Check signals exist
        assert hasattr(qprocess, "command_executed")
        assert hasattr(qprocess, "command_error")

        # Check signals are compatible (both are Signal instances)
        # In PySide6, signals don't have a .signal attribute
        # We just verify they exist and are signals
        from PySide6.QtCore import SignalInstance
        assert isinstance(qprocess.command_executed, SignalInstance)
        assert isinstance(qprocess.command_error, SignalInstance)
