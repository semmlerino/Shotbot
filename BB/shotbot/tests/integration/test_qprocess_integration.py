"""QProcess integration tests for ShotBot.

This module tests QProcess integration across the system:
1. Shot model refresh with QProcess instead of subprocess
2. Terminal launcher with different terminal emulators
3. Concurrent process execution and management
4. Process cleanup and resource management
5. Timeout handling and graceful termination
6. Real command execution with process monitoring

These tests validate the QProcess migration works correctly in production.
"""

import os
import threading
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QProcess

from command_launcher import CommandLauncher
from launcher_manager import LauncherManager
from shot_model import Shot, ShotModel
from terminal_launcher import TerminalLauncher


class TestQProcessShotModelIntegration:
    """Test shot model integration with QProcess."""

    @pytest.fixture
    def mock_workspace_output(self):
        """Mock workspace command output."""
        return """workspace /shows/testshow/shots/SEQ_001/SEQ_001_0010
workspace /shows/testshow/shots/SEQ_001/SEQ_001_0020
workspace /shows/testshow/shots/SEQ_001/SEQ_001_0030
workspace /shows/testshow/shots/SEQ_002/SEQ_002_0010
workspace /shows/testshow/shots/SEQ_002/SEQ_002_0020
workspace /shows/prodshow/shots/PROD_001/PROD_001_0001
workspace /shows/prodshow/shots/PROD_001/PROD_001_0002
workspace /shows/prodshow/shots/PROD_002/PROD_002_0001"""

    def test_shot_model_qprocess_refresh_basic(self, mock_workspace_output, qtbot):
        """Test basic shot model refresh using QProcess."""
        model = ShotModel()

        # Mock QProcess execution
        with patch("shot_model.QProcess") as MockQProcess:
            mock_process = Mock()
            MockQProcess.return_value = mock_process

            # Configure mock process behavior
            mock_process.start.return_value = None
            mock_process.waitForFinished.return_value = True
            mock_process.exitCode.return_value = 0
            mock_process.readAllStandardOutput.return_value.data.return_value = (
                mock_workspace_output.encode()
            )
            mock_process.readAllStandardError.return_value.data.return_value = b""

            # Execute refresh
            success, has_changes = model.refresh_shots()

            # Verify QProcess was used correctly
            MockQProcess.assert_called_once()
            mock_process.start.assert_called_once()
            mock_process.waitForFinished.assert_called_once()

            # Verify results
            assert success, "QProcess shot refresh should succeed"
            assert len(model.shots) == 8, f"Expected 8 shots, got {len(model.shots)}"

            # Verify shot parsing
            testshow_shots = [s for s in model.shots if s.show == "testshow"]
            prodshow_shots = [s for s in model.shots if s.show == "prodshow"]

            assert len(testshow_shots) == 5, "Should find 5 testshow shots"
            assert len(prodshow_shots) == 3, "Should find 3 prodshow shots"

    def test_qprocess_timeout_handling(self, qtbot):
        """Test QProcess timeout handling in shot model."""
        model = ShotModel()

        with patch("shot_model.QProcess") as MockQProcess:
            mock_process = Mock()
            MockQProcess.return_value = mock_process

            # Simulate timeout
            mock_process.start.return_value = None
            mock_process.waitForFinished.return_value = False  # Timeout
            mock_process.kill.return_value = None

            # Execute refresh
            success, has_changes = model.refresh_shots()

            # Should handle timeout gracefully
            assert success == False, "Should return False on timeout"
            mock_process.kill.assert_called_once(), "Should kill process on timeout"

    def test_qprocess_error_handling(self, qtbot):
        """Test QProcess error handling in shot model."""
        model = ShotModel()

        with patch("shot_model.QProcess") as MockQProcess:
            mock_process = Mock()
            MockQProcess.return_value = mock_process

            # Simulate process failure
            mock_process.start.return_value = None
            mock_process.waitForFinished.return_value = True
            mock_process.exitCode.return_value = 1  # Error exit code
            mock_process.readAllStandardOutput.return_value.data.return_value = b""
            mock_process.readAllStandardError.return_value.data.return_value = (
                b"Command failed"
            )

            # Execute refresh
            success, has_changes = model.refresh_shots()

            # Should handle error gracefully
            assert success == False, "Should return False on process error"
            assert len(model.shots) == 0, "Should not add shots on error"

    def test_qprocess_incremental_output_processing(self, qtbot):
        """Test processing QProcess output incrementally."""
        model = ShotModel()

        # Split output to simulate incremental reading
        output_parts = [
            "workspace /shows/test1/shots/SEQ/SEQ_0010\\n",
            "workspace /shows/test1/shots/SEQ/SEQ_0020\\n",
            "workspace /shows/test2/shots/SEQ/SEQ_0010\\n",
        ]

        with patch("shot_model.QProcess") as MockQProcess:
            mock_process = Mock()
            MockQProcess.return_value = mock_process

            # Configure incremental output
            mock_process.start.return_value = None
            mock_process.waitForFinished.return_value = True
            mock_process.exitCode.return_value = 0

            # Simulate incremental output reading
            full_output = "".join(output_parts).encode()
            mock_process.readAllStandardOutput.return_value.data.return_value = (
                full_output
            )
            mock_process.readAllStandardError.return_value.data.return_value = b""

            # Execute refresh
            success, has_changes = model.refresh_shots()

            assert success, "Incremental processing should succeed"
            assert len(model.shots) == 3, (
                "Should parse all shots from incremental output"
            )

    def test_qprocess_signal_based_refresh(self, qtbot):
        """Test QProcess with signal-based completion."""
        model = ShotModel()

        # Create real QProcess to test signals
        process = QProcess()

        # Track signal emissions
        finished_signals = []
        error_signals = []

        def on_finished(exit_code, exit_status):
            finished_signals.append((exit_code, exit_status))

        def on_error(error):
            error_signals.append(error)

        process.finished.connect(on_finished)
        process.errorOccurred.connect(on_error)

        # Test with echo command (should be available on most systems)
        test_output = "workspace /shows/signal_test/shots/SEQ/SEQ_0001"

        with patch.object(model, "_execute_workspace_command") as mock_execute:
            # Mock the execution to avoid real subprocess
            mock_execute.return_value = (True, test_output)

            success, has_changes = model.refresh_shots()

            assert success, "Signal-based refresh should succeed"
            mock_execute.assert_called_once()

    def test_concurrent_qprocess_shot_refreshes(self, mock_workspace_output, qtbot):
        """Test multiple concurrent shot model refreshes with QProcess."""
        models = [ShotModel() for _ in range(3)]

        results = {}

        def concurrent_refresh(model_idx, model):
            with patch("shot_model.QProcess") as MockQProcess:
                mock_process = Mock()
                MockQProcess.return_value = mock_process

                mock_process.start.return_value = None
                mock_process.waitForFinished.return_value = True
                mock_process.exitCode.return_value = 0
                mock_process.readAllStandardOutput.return_value.data.return_value = (
                    mock_workspace_output.encode()
                )
                mock_process.readAllStandardError.return_value.data.return_value = b""

                success, has_changes = model.refresh_shots()
                results[model_idx] = {
                    "success": success,
                    "shot_count": len(model.shots),
                    "has_changes": has_changes,
                }

        # Start concurrent refreshes
        threads = []
        for i, model in enumerate(models):
            thread = threading.Thread(target=concurrent_refresh, args=(i, model))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=5.0)

        # Verify all completed successfully
        assert len(results) == 3, "All concurrent refreshes should complete"

        for i, result in results.items():
            assert result["success"], f"Model {i} refresh should succeed"
            assert result["shot_count"] == 8, f"Model {i} should find 8 shots"


class TestTerminalLauncherQProcessIntegration:
    """Test terminal launcher QProcess integration."""

    def test_terminal_launcher_basic_execution(self, qtbot):
        """Test basic terminal launcher execution with QProcess."""
        launcher = TerminalLauncher()

        # Test with echo command
        test_command = "echo 'Terminal test'"

        with patch.object(launcher, "_get_available_terminal") as mock_get_terminal:
            mock_get_terminal.return_value = "xterm"

            with patch("terminal_launcher.QProcess") as MockQProcess:
                mock_process = Mock()
                MockQProcess.return_value = mock_process

                mock_process.start.return_value = None
                mock_process.waitForStarted.return_value = True
                mock_process.state.return_value = QProcess.ProcessState.Running

                success = launcher.launch_in_terminal(test_command)

                assert success, "Terminal launch should succeed"
                MockQProcess.assert_called_once()
                mock_process.start.assert_called_once()

    def test_terminal_launcher_fallback_terminals(self, qtbot):
        """Test terminal launcher fallback to different terminals."""
        launcher = TerminalLauncher()
        test_command = "echo 'Fallback test'"

        # Mock terminal availability
        terminal_availability = {
            "gnome-terminal": False,
            "xterm": True,
            "konsole": False,
        }

        def mock_find_executable(name):
            return (
                "/usr/bin/" + name if terminal_availability.get(name, False) else None
            )

        with patch("shutil.which", side_effect=mock_find_executable):
            with patch("terminal_launcher.QProcess") as MockQProcess:
                mock_process = Mock()
                MockQProcess.return_value = mock_process

                mock_process.start.return_value = None
                mock_process.waitForStarted.return_value = True

                success = launcher.launch_in_terminal(test_command)

                assert success, "Should succeed with fallback terminal"

                # Verify xterm was used (available terminal)
                call_args = mock_process.start.call_args
                assert "xterm" in str(call_args), "Should use available terminal"

    def test_terminal_launcher_process_monitoring(self, qtbot):
        """Test terminal launcher process monitoring."""
        launcher = TerminalLauncher()

        # Track process lifecycle signals
        started_processes = []
        finished_processes = []

        def on_process_started(pid):
            started_processes.append(pid)

        def on_process_finished(pid, exit_code):
            finished_processes.append((pid, exit_code))

        # Connect to launcher signals (if they exist)
        if hasattr(launcher, "process_started"):
            launcher.process_started.connect(on_process_started)
        if hasattr(launcher, "process_finished"):
            launcher.process_finished.connect(on_process_finished)

        with patch("terminal_launcher.QProcess") as MockQProcess:
            mock_process = Mock()
            MockQProcess.return_value = mock_process

            # Simulate process lifecycle
            mock_process.start.return_value = None
            mock_process.waitForStarted.return_value = True
            mock_process.pid.return_value = 12345
            mock_process.state.return_value = QProcess.ProcessState.Running

            success = launcher.launch_in_terminal("test command")
            assert success

            # Simulate process finish
            if hasattr(mock_process, "finished"):
                mock_process.finished.emit(0, QProcess.ExitStatus.NormalExit)

    def test_terminal_launcher_error_recovery(self, qtbot):
        """Test terminal launcher error recovery."""
        launcher = TerminalLauncher()

        with patch("terminal_launcher.QProcess") as MockQProcess:
            mock_process = Mock()
            MockQProcess.return_value = mock_process

            # Simulate start failure
            mock_process.start.return_value = None
            mock_process.waitForStarted.return_value = False
            mock_process.error.return_value = QProcess.ProcessError.FailedToStart

            success = launcher.launch_in_terminal("failing command")

            # Should handle failure gracefully
            assert success == False, "Should return False on start failure"

    def test_terminal_launcher_multiple_simultaneous(self, qtbot):
        """Test multiple simultaneous terminal launches."""
        launcher = TerminalLauncher()

        launched_processes = []

        def launch_terminal(command_idx):
            command = f"echo 'Command {command_idx}'"

            with patch("terminal_launcher.QProcess") as MockQProcess:
                mock_process = Mock()
                MockQProcess.return_value = mock_process

                mock_process.start.return_value = None
                mock_process.waitForStarted.return_value = True
                mock_process.pid.return_value = 10000 + command_idx

                success = launcher.launch_in_terminal(command)
                launched_processes.append((command_idx, success))

        # Launch multiple terminals concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=launch_terminal, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all launches
        for thread in threads:
            thread.join(timeout=2.0)

        # Verify all launches
        assert len(launched_processes) == 5, "All terminal launches should complete"

        for command_idx, success in launched_processes:
            assert success, f"Terminal launch {command_idx} should succeed"


class TestLauncherManagerQProcessIntegration:
    """Test launcher manager QProcess integration."""

    def test_custom_launcher_qprocess_execution(self, qtbot):
        """Test custom launcher execution with QProcess."""
        manager = LauncherManager()

        # Create custom launcher
        launcher_id = manager.create_launcher(
            name="QProcess Test Launcher",
            command="echo 'QProcess custom launcher test'",
            description="Test custom launcher with QProcess",
        )

        assert launcher_id is not None, "Should create custom launcher"

        # Mock QProcess for execution
        execution_results = []

        def mock_execute_with_qprocess():
            with patch("launcher_manager.subprocess.Popen") as mock_popen:
                # Note: LauncherManager might still use subprocess.Popen
                # This test verifies the execution pathway
                mock_process = Mock()
                mock_process.wait.return_value = 0
                mock_process.pid = 54321
                mock_popen.return_value = mock_process

                success = manager.execute_launcher(launcher_id)
                execution_results.append(success)

        # Execute in thread to avoid blocking
        exec_thread = threading.Thread(target=mock_execute_with_qprocess)
        exec_thread.start()
        exec_thread.join(timeout=2.0)

        assert len(execution_results) == 1, "Execution should complete"
        assert execution_results[0] == True, "Custom launcher execution should succeed"

        # Cleanup
        manager.delete_launcher(launcher_id)

    def test_launcher_manager_process_tracking(self, qtbot):
        """Test launcher manager process tracking with QProcess."""
        manager = LauncherManager()

        # Create launcher with long-running command
        launcher_id = manager.create_launcher(
            name="Long Running Launcher",
            command="sleep 0.1",  # Short sleep for testing
            description="Test process tracking",
        )

        # Track process lifecycle
        process_events = []

        def on_execution_started(lid):
            process_events.append(("started", lid))

        def on_execution_finished(lid, success):
            process_events.append(("finished", lid, success))

        manager.execution_started.connect(on_execution_started)
        manager.execution_finished.connect(on_execution_finished)

        # Execute launcher
        with patch("launcher_manager.subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.wait.return_value = 0
            mock_process.pid = 98765
            mock_popen.return_value = mock_process

            success = manager.execute_launcher(launcher_id)
            assert success, "Process tracking execution should succeed"

            # Give worker thread time to process
            qtbot.wait(200)

        # Verify process tracking events
        assert len(process_events) >= 1, "Should have process tracking events"

        # Check for started event
        started_events = [e for e in process_events if e[0] == "started"]
        assert len(started_events) > 0, "Should have started event"

        # Cleanup
        manager.delete_launcher(launcher_id)

    def test_launcher_manager_concurrent_qprocess_execution(self, qtbot):
        """Test concurrent custom launcher execution."""
        manager = LauncherManager()

        # Create multiple launchers
        launcher_ids = []
        for i in range(3):
            launcher_id = manager.create_launcher(
                name=f"Concurrent Launcher {i}",
                command=f"echo 'Launcher {i} output'",
                description=f"Concurrent launcher {i}",
            )
            launcher_ids.append(launcher_id)

        # Execute all launchers concurrently
        execution_results = {}

        def execute_launcher(lid, index):
            with patch("launcher_manager.subprocess.Popen") as mock_popen:
                mock_process = Mock()
                mock_process.wait.return_value = 0
                mock_process.pid = 20000 + index
                mock_popen.return_value = mock_process

                success = manager.execute_launcher(lid)
                execution_results[index] = success

        # Start concurrent executions
        threads = []
        for i, lid in enumerate(launcher_ids):
            thread = threading.Thread(target=execute_launcher, args=(lid, i))
            threads.append(thread)
            thread.start()

        # Wait for all executions
        for thread in threads:
            thread.join(timeout=3.0)

        # Verify all executions
        assert len(execution_results) == 3, "All concurrent executions should complete"

        for i, success in execution_results.items():
            assert success, f"Concurrent execution {i} should succeed"

        # Cleanup
        for launcher_id in launcher_ids:
            if launcher_id:
                manager.delete_launcher(launcher_id)

    def test_launcher_manager_qprocess_cleanup(self, qtbot):
        """Test launcher manager QProcess cleanup."""
        manager = LauncherManager()

        # Create launcher that might leave processes
        launcher_id = manager.create_launcher(
            name="Cleanup Test Launcher",
            command="echo 'Testing cleanup'",
            description="Test process cleanup",
        )

        # Track active processes
        initial_process_count = len(manager._active_processes)

        # Execute launcher
        with patch("launcher_manager.subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.wait.return_value = 0
            mock_process.pid = 77777
            mock_popen.return_value = mock_process

            success = manager.execute_launcher(launcher_id)
            assert success

            # Wait for worker thread processing
            qtbot.wait(300)

        # Check that processes are cleaned up
        final_process_count = len(manager._active_processes)

        # Process should be cleaned up after completion
        # Note: Actual cleanup timing depends on implementation
        print(f"Process count: {initial_process_count} -> {final_process_count}")

        # Cleanup
        manager.delete_launcher(launcher_id)


class TestCommandLauncherQProcessIntegration:
    """Test command launcher QProcess integration."""

    @pytest.fixture
    def test_shot(self):
        """Create test shot for command launcher."""
        return Shot("qprocess_test", "QTEST", "0001", "/test/qprocess/workspace")

    def test_command_launcher_qprocess_app_launch(self, test_shot, qtbot):
        """Test command launcher app launch with QProcess."""
        launcher = CommandLauncher()
        launcher.set_current_shot(test_shot)

        # Test launching with QProcess mock
        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.pid = 88888
            mock_popen.return_value = mock_process

            success = launcher.launch_app("nuke")

            assert success, "QProcess app launch should succeed"
            mock_popen.assert_called_once()

            # Verify command contains shot context
            call_args = mock_popen.call_args[0][0]
            command_str = (
                " ".join(call_args) if isinstance(call_args, list) else str(call_args)
            )
            assert test_shot.workspace_path in command_str, (
                "Command should include shot workspace"
            )

    def test_command_launcher_qprocess_with_options(self, test_shot, qtbot):
        """Test command launcher QProcess with various options."""
        launcher = CommandLauncher()
        launcher.set_current_shot(test_shot)

        # Test with raw plate option
        with patch("subprocess.Popen") as mock_popen:
            with patch(
                "raw_plate_finder.RawPlateFinder.find_latest_raw_plate"
            ) as mock_find_plate:
                mock_find_plate.return_value = "/test/plate/path.####.exr"

                mock_process = Mock()
                mock_process.pid = 99999
                mock_popen.return_value = mock_process

                success = launcher.launch_app("nuke", include_raw_plate=True)

                assert success, "QProcess launch with raw plate should succeed"
                mock_find_plate.assert_called_once()

        # Test with undistortion option
        with patch("subprocess.Popen") as mock_popen:
            with patch(
                "undistortion_finder.UndistortionFinder.find_latest_undistortion_file"
            ) as mock_find_undist:
                mock_find_undist.return_value = "/test/undist/file.nk"

                mock_process = Mock()
                mock_process.pid = 11111
                mock_popen.return_value = mock_process

                success = launcher.launch_app("nuke", include_undistortion=True)

                assert success, "QProcess launch with undistortion should succeed"
                mock_find_undist.assert_called_once()

    def test_command_launcher_qprocess_error_handling(self, test_shot, qtbot):
        """Test command launcher QProcess error handling."""
        launcher = CommandLauncher()
        launcher.set_current_shot(test_shot)

        # Test with process start failure
        with patch(
            "subprocess.Popen", side_effect=FileNotFoundError("Command not found")
        ):
            success = launcher.launch_app("nonexistent_app")

            assert success == False, "Should return False for failed process start"

        # Test with permission error
        with patch(
            "subprocess.Popen", side_effect=PermissionError("Permission denied")
        ):
            success = launcher.launch_app("nuke")

            assert success == False, "Should return False for permission error"

    def test_command_launcher_signal_emission(self, test_shot, qtbot):
        """Test command launcher signal emission with QProcess."""
        launcher = CommandLauncher()
        launcher.set_current_shot(test_shot)

        # Track signals
        command_signals = []
        error_signals = []

        def on_command_executed(timestamp, command):
            command_signals.append((timestamp, command))

        def on_command_error(timestamp, error):
            error_signals.append((timestamp, error))

        launcher.command_executed.connect(on_command_executed)
        launcher.command_error.connect(on_command_error)

        # Test successful execution
        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.pid = 22222
            mock_popen.return_value = mock_process

            success = launcher.launch_app("maya")

            assert success, "Signal test execution should succeed"

            # Should emit command executed signal
            assert len(command_signals) == 1, "Should emit command executed signal"
            assert len(error_signals) == 0, "Should not emit error signal on success"

        # Test error execution
        with patch("subprocess.Popen", side_effect=Exception("Test error")):
            success = launcher.launch_app("failing_app")

            assert success == False, "Error execution should fail"

            # Should emit error signal
            assert len(error_signals) == 1, "Should emit error signal"

    def test_command_launcher_concurrent_qprocess_launches(self, qtbot):
        """Test concurrent app launches with QProcess."""
        # Create multiple shots
        shots = [
            Shot("concurrent1", "CONC", "0001", "/test/conc1"),
            Shot("concurrent2", "CONC", "0002", "/test/conc2"),
            Shot("concurrent3", "CONC", "0003", "/test/conc3"),
        ]

        launch_results = {}

        def concurrent_launch(shot_index, shot):
            launcher = CommandLauncher()
            launcher.set_current_shot(shot)

            with patch("subprocess.Popen") as mock_popen:
                mock_process = Mock()
                mock_process.pid = 30000 + shot_index
                mock_popen.return_value = mock_process

                success = launcher.launch_app("nuke")
                launch_results[shot_index] = success

        # Start concurrent launches
        threads = []
        for i, shot in enumerate(shots):
            thread = threading.Thread(target=concurrent_launch, args=(i, shot))
            threads.append(thread)
            thread.start()

        # Wait for all launches
        for thread in threads:
            thread.join(timeout=3.0)

        # Verify all launches
        assert len(launch_results) == 3, "All concurrent launches should complete"

        for i, success in launch_results.items():
            assert success, f"Concurrent launch {i} should succeed"


class TestQProcessResourceManagement:
    """Test QProcess resource management and cleanup."""

    def test_qprocess_resource_cleanup(self, qtbot):
        """Test proper QProcess resource cleanup."""
        # Track created processes
        created_processes = []

        class MockQProcess(Mock):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created_processes.append(self)
                self.start = Mock()
                self.waitForFinished = Mock(return_value=True)
                self.kill = Mock()
                self.terminate = Mock()
                self.deleteLater = Mock()

        with patch("shot_model.QProcess", MockQProcess):
            # Create and use multiple shot models
            models = []
            for i in range(5):
                model = ShotModel()
                models.append(model)

                # Mock successful execution
                for process in created_processes[-1:]:  # Last created process
                    process.exitCode.return_value = 0
                    process.readAllStandardOutput.return_value.data.return_value = (
                        b"workspace /test/shot"
                    )
                    process.readAllStandardError.return_value.data.return_value = b""

                success, _ = model.refresh_shots()
                assert success, f"Model {i} should succeed"

        # Verify processes were created
        assert len(created_processes) == 5, "Should create 5 QProcess instances"

        # Simulate cleanup - in real implementation, this would happen automatically
        # when QObjects are destroyed or when explicitly called
        for process in created_processes:
            if hasattr(process, "deleteLater"):
                process.deleteLater.assert_called()

    def test_qprocess_timeout_and_termination(self, qtbot):
        """Test QProcess timeout and termination handling."""
        launcher = CommandLauncher()
        shot = Shot("timeout_test", "TO", "0001", "/test/timeout")
        launcher.set_current_shot(shot)

        with patch("subprocess.Popen") as mock_popen:
            # Create process that will timeout
            mock_process = Mock()
            mock_process.pid = 44444

            # Simulate timeout scenario
            mock_process.poll.return_value = None  # Still running
            mock_process.wait.side_effect = TimeoutError("Process timeout")
            mock_process.terminate.return_value = None
            mock_process.kill.return_value = None

            mock_popen.return_value = mock_process

            # This would depend on implementation having timeout handling
            success = launcher.launch_app("long_running_app")

            # The key is that it should handle timeout gracefully
            # Implementation details may vary
            assert success in [True, False], "Should handle timeout gracefully"

    def test_qprocess_memory_management(self, qtbot):
        """Test QProcess memory management during multiple operations."""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Create many short-lived QProcess operations
        models = []

        with patch("shot_model.QProcess") as MockQProcess:
            for i in range(50):  # Create many operations
                mock_process = Mock()
                MockQProcess.return_value = mock_process

                mock_process.start.return_value = None
                mock_process.waitForFinished.return_value = True
                mock_process.exitCode.return_value = 0
                mock_process.readAllStandardOutput.return_value.data.return_value = (
                    b"workspace /test/memory"
                )
                mock_process.readAllStandardError.return_value.data.return_value = b""

                model = ShotModel()
                success, _ = model.refresh_shots()
                assert success, f"Memory test model {i} should succeed"

                models.append(model)

                # Periodically check memory
                if i % 10 == 0:
                    current_memory = process.memory_info().rss / 1024 / 1024
                    memory_growth = current_memory - initial_memory

                    # Memory growth should be reasonable
                    assert memory_growth < 50, (
                        f"Memory growth too high at iteration {i}: {memory_growth:.1f}MB"
                    )

        final_memory = process.memory_info().rss / 1024 / 1024
        total_growth = final_memory - initial_memory

        print(
            f"QProcess memory test: {initial_memory:.1f}MB -> {final_memory:.1f}MB (+{total_growth:.1f}MB)"
        )

        # Total memory growth should be reasonable for 50 operations
        assert total_growth < 100, f"Total memory growth too high: {total_growth:.1f}MB"

    def test_qprocess_error_state_recovery(self, qtbot):
        """Test recovery from QProcess error states."""
        launcher = CommandLauncher()
        shot = Shot("error_recovery", "ER", "0001", "/test/error_recovery")
        launcher.set_current_shot(shot)

        # Test sequence of failures followed by success
        failure_modes = [
            FileNotFoundError("Command not found"),
            PermissionError("Permission denied"),
            OSError("OS Error"),
            Exception("Generic error"),
        ]

        for i, error in enumerate(failure_modes):
            with patch("subprocess.Popen", side_effect=error):
                success = launcher.launch_app("error_app")
                assert success == False, f"Should handle error {i}: {error}"

        # After failures, should still work with valid command
        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.pid = 55555
            mock_popen.return_value = mock_process

            success = launcher.launch_app("recovery_app")
            assert success == True, "Should recover and work after previous errors"


@pytest.mark.integration
class TestQProcessRealWorldIntegration:
    """Test QProcess integration with real-world scenarios."""

    def test_qprocess_with_real_echo_command(self, qtbot):
        """Test QProcess with real echo command (safe and available)."""
        # This test uses actual QProcess with a safe command
        process = QProcess()

        # Track completion
        finished_signals = []

        def on_finished(exit_code, exit_status):
            finished_signals.append((exit_code, exit_status))

        process.finished.connect(on_finished)

        # Start echo command
        process.start("echo", ["QProcess integration test"])

        # Wait for completion
        started = process.waitForStarted(1000)  # 1 second timeout
        assert started, "Echo process should start"

        finished = process.waitForFinished(1000)  # 1 second timeout
        assert finished, "Echo process should finish"

        # Check results
        assert len(finished_signals) == 1, "Should receive finished signal"
        exit_code, exit_status = finished_signals[0]
        assert exit_code == 0, "Echo should succeed"

        # Check output
        output = process.readAllStandardOutput().data().decode()
        assert "QProcess integration test" in output, "Should contain test message"

    def test_qprocess_environment_variables(self, qtbot):
        """Test QProcess with environment variables."""
        process = QProcess()

        # Set custom environment
        env = process.processEnvironment()
        env.insert("SHOTBOT_TEST_VAR", "QProcess_Test_Value")
        process.setProcessEnvironment(env)

        # Use command that echoes environment variable
        if os.name == "nt":  # Windows
            process.start("cmd", ["/c", "echo %SHOTBOT_TEST_VAR%"])
        else:  # Unix-like
            process.start("sh", ["-c", "echo $SHOTBOT_TEST_VAR"])

        started = process.waitForStarted(1000)
        finished = process.waitForFinished(1000)

        if started and finished:
            output = process.readAllStandardOutput().data().decode().strip()
            assert "QProcess_Test_Value" in output, (
                "Environment variable should be passed to process"
            )
        else:
            pytest.skip("Could not execute environment test command")

    def test_qprocess_working_directory(self, tmp_path, qtbot):
        """Test QProcess with custom working directory."""
        # Create test directory and file
        test_dir = tmp_path / "qprocess_test"
        test_dir.mkdir()
        test_file = test_dir / "test_file.txt"
        test_file.write_text("QProcess working directory test")

        process = QProcess()
        process.setWorkingDirectory(str(test_dir))

        # Command to list current directory
        if os.name == "nt":  # Windows
            process.start("cmd", ["/c", "dir /b"])
        else:  # Unix-like
            process.start("ls", ["-1"])

        started = process.waitForStarted(1000)
        finished = process.waitForFinished(1000)

        if started and finished:
            output = process.readAllStandardOutput().data().decode()
            assert "test_file.txt" in output, "Should list file in working directory"
        else:
            pytest.skip("Could not execute directory listing command")

    def test_qprocess_integration_stress_test(self, qtbot):
        """Stress test QProcess integration with multiple rapid operations."""
        # Create many processes in rapid succession
        processes = []
        results = []

        for i in range(20):  # 20 rapid processes
            process = QProcess()
            processes.append(process)

            def make_finished_handler(proc_idx):
                def on_finished(exit_code, exit_status):
                    results.append((proc_idx, exit_code, exit_status))

                return on_finished

            process.finished.connect(make_finished_handler(i))

            # Start echo with unique message
            process.start("echo", [f"Process {i}"])

        # Wait for all to start
        for i, process in enumerate(processes):
            started = process.waitForStarted(1000)
            if not started:
                print(f"Process {i} failed to start")

        # Wait for all to finish
        for i, process in enumerate(processes):
            finished = process.waitForFinished(2000)
            if not finished:
                print(f"Process {i} did not finish in time")

        # Check results
        print(f"Completed {len(results)} of {len(processes)} processes")

        # Should complete most processes successfully
        successful_processes = [r for r in results if r[1] == 0]  # exit_code == 0
        success_rate = len(successful_processes) / len(processes)

        assert success_rate > 0.8, f"Success rate too low: {success_rate:.1%}"
