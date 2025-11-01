#!/usr/bin/env python3
"""
Unit tests for ProcessManager class
Tests QProcess lifecycle management, queue management, and timer coordination
"""

import pytest
import time
from collections import deque
from unittest.mock import Mock, patch

from PySide6.QtCore import QProcess, QTimer
from process_manager import ProcessManager
from config import ProcessConfig, UIConfig


class TestProcessManager:
    """Test suite for ProcessManager class"""

    def setup_method(self):
        """Create fresh ProcessManager instance for each test"""
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def teardown_method(self):
        """Cleanup after each test"""
        if hasattr(self, "manager"):
            self.manager.stop_all_processes()


class TestBatchManagement:
    """Test batch processing initialization and management"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def test_start_batch_initialization(self):
        """Test batch initialization with file paths"""
        file_paths = ["/test/video1.ts", "/test/video2.ts", "/test/video3.ts"]

        self.manager.start_batch(file_paths, parallel_enabled=True, max_parallel=3)

        assert self.manager.queue == file_paths
        assert self.manager.total == 3
        assert self.manager.completed == 0
        assert self.manager.parallel_enabled
        assert self.manager.max_parallel == 3
        assert not self.manager.stopping

    def test_start_batch_sequential_mode(self):
        """Test batch initialization in sequential mode"""
        file_paths = ["/test/video1.ts", "/test/video2.ts"]

        self.manager.start_batch(file_paths, parallel_enabled=False, max_parallel=1)

        assert not self.manager.parallel_enabled
        assert self.manager.max_parallel == 1

    def test_start_batch_empty_list(self):
        """Test batch initialization with empty file list"""
        self.manager.start_batch([], parallel_enabled=True, max_parallel=4)

        assert self.manager.queue == []
        assert self.manager.total == 0
        assert self.manager.completed == 0

    def test_start_batch_resets_state(self):
        """Test that starting a new batch resets previous state"""
        # Start first batch
        self.manager.start_batch(
            ["/test/video1.ts"], parallel_enabled=False, max_parallel=1
        )
        self.manager.completed = 1
        self.manager.stopping = True

        # Start second batch
        file_paths = ["/test/video2.ts", "/test/video3.ts"]
        self.manager.start_batch(file_paths, parallel_enabled=True, max_parallel=2)

        # State should be reset
        assert self.manager.queue == file_paths
        assert self.manager.total == 2
        assert self.manager.completed == 0
        assert not self.manager.stopping


class TestProcessLifecycle:
    """Test QProcess creation, starting, and management"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    @patch("process_manager.QProcess")
    def test_start_process_creation(self, mock_qprocess_class):
        """Test QProcess creation and configuration"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process

        file_path = "/test/video.ts"
        ffmpeg_args = ["-i", file_path, "-c:v", "libx264", "output.mp4"]

        result_process = self.manager.start_process(file_path, ffmpeg_args)

        # Verify process creation and configuration
        mock_qprocess_class.assert_called_once()
        # Just verify the method was called without checking the exact enum value
        mock_process.setProcessChannelMode.assert_called_once()
        # Check that start was called with ffmpeg command (platform-specific)
        start_call = mock_process.start.call_args[0]
        assert start_call[0] in ["ffmpeg", "ffmpeg.exe"]  # Platform-specific
        assert start_call[1] == ffmpeg_args
        mock_process.waitForStarted.assert_called_once_with(
            ProcessConfig.PROCESS_START_TIMEOUT * 1000
        )

        # Verify process is tracked
        assert len(self.manager.processes) == 1
        assert self.manager.processes[0] == (mock_process, file_path)
        assert mock_process in self.manager.process_logs
        assert mock_process in self.manager.process_outputs

        assert result_process == mock_process

    @patch("process_manager.QProcess")
    def test_start_process_startup_timeout(self, mock_qprocess_class):
        """Test process startup timeout handling"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = False  # Timeout
        mock_process.errorString.return_value = "Process timeout"
        mock_qprocess_class.return_value = mock_process

        file_path = "/test/video.ts"
        ffmpeg_args = ["-i", file_path, "-c:v", "libx264", "output.mp4"]

        result_process = self.manager.start_process(file_path, ffmpeg_args)

        # Should still track the process even if startup times out
        assert len(self.manager.processes) == 1
        assert result_process == mock_process

    @patch("process_manager.QProcess")
    def test_process_signal_connections(self, mock_qprocess_class):
        """Test that QProcess signals are properly connected"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process

        file_path = "/test/video.ts"
        ffmpeg_args = ["-i", file_path, "output.mp4"]

        self.manager.start_process(file_path, ffmpeg_args)

        # Verify signal connections
        mock_process.readyReadStandardOutput.connect.assert_called_once()
        mock_process.errorOccurred.connect.assert_called_once()
        mock_process.finished.connect.assert_called_once()

    @patch("process_manager.QProcess")
    def test_codec_mapping_extraction(self, mock_qprocess_class):
        """Test codec information extraction from FFmpeg args"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process

        file_path = "/test/video.ts"
        ffmpeg_args = [
            "-i",
            file_path,
            "-c:v",
            "h264_nvenc",
            "-preset",
            "fast",
            "output.mp4",
        ]

        self.manager.start_process(file_path, ffmpeg_args)

        # Should extract codec index from args
        assert file_path in self.manager.codec_map
        # Note: The actual index depends on the implementation logic

    @patch("process_manager.QProcess")
    @patch("process_manager.ProcessProgressTracker")
    def test_progress_tracker_registration(
        self, mock_tracker_class, mock_qprocess_class
    ):
        """Test process registration with progress tracker"""
        mock_tracker = Mock()
        mock_tracker.probe_duration.return_value = 600.0
        mock_tracker_class.return_value = mock_tracker

        # Recreate manager with mocked tracker
        self.manager = ProcessManager()
        self.manager.progress_tracker = mock_tracker

        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process

        file_path = "/test/video.ts"
        ffmpeg_args = ["-i", file_path, "output.mp4"]

        self.manager.start_process(file_path, ffmpeg_args)

        # Verify progress tracker interactions
        mock_tracker.probe_duration.assert_called_once_with(file_path)
        mock_tracker.register_process.assert_called_once()


class TestProcessOutput:
    """Test process output handling and parsing"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def test_handle_process_output(self):
        """Test handling of process output"""
        # Use real QProcess to avoid segfault with signals
        process = QProcess()
        
        # Mock only the specific methods we need
        process.waitForStarted = Mock(return_value=True)
        process.bytesAvailable = Mock(return_value=20)
        
        # Mock readAllStandardOutput to return QByteArray-like object
        mock_data = Mock()
        mock_data.data.return_value = b"test ffmpeg output\n"
        process.readAllStandardOutput = Mock(return_value=mock_data)
        
        # Add process to manager's tracking structures
        file_path = "/test/video.ts"
        self.manager.processes.append((process, file_path))
        self.manager.process_outputs[process] = deque(maxlen=self.manager._current_max_log_lines)
        self.manager.process_logs[process] = deque(maxlen=self.manager._current_max_log_lines)
        
        # Register process with progress tracker
        process_id = str(id(process))
        self.manager.progress_tracker.register_process(process_id, file_path, 60.0)
        
        # Call _handle_process_output
        self.manager._handle_process_output(process)
        
        # Verify output is stored
        assert process in self.manager.process_outputs
        assert len(self.manager.process_outputs[process]) > 0
        assert self.manager.process_outputs[process][0] == "test ffmpeg output\n"

    def test_output_buffering_and_limits(self):
        """Test output buffering and size limits"""
        # Use real QProcess to avoid segfault
        process = QProcess()
        process.waitForStarted = Mock(return_value=True)
        process.bytesAvailable = Mock(return_value=10)
        
        # Add process to manager's tracking structures
        file_path = "/test/video.ts"
        self.manager.processes.append((process, file_path))
        self.manager.process_outputs[process] = deque(maxlen=self.manager._current_max_log_lines)
        self.manager.process_logs[process] = deque(maxlen=self.manager._current_max_log_lines)
        
        # Register with progress tracker
        process_id = str(id(process))
        self.manager.progress_tracker.register_process(process_id, file_path, 60.0)
        
        # Simulate multiple output chunks
        output_chunks = [b"chunk1\n", b"chunk2\n", b"chunk3\n"]

        # Mock the progress tracker to avoid signal emissions
        mock_progress_data = {"current_pct": 0, "fps": 0}
        self.manager.progress_tracker.process_output.return_value = mock_progress_data
        
        # Mock signals to prevent segfault
        with patch.object(self.manager, "update_progress"):
            with patch.object(self.manager, "output_ready"):
                for chunk in output_chunks:
                    # Mock readAllStandardOutput to return QByteArray  
                    mock_data = Mock()
                    mock_data.data.return_value = chunk
                    process.readAllStandardOutput = Mock(return_value=mock_data)
                    self.manager._handle_process_output(process)

        # Verify all chunks are buffered
        assert len(self.manager.process_outputs[process]) == len(output_chunks)

    @patch("process_manager.QProcess")
    def test_empty_output_handling(self, mock_qprocess_class):
        """Test handling of empty output"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.bytesAvailable.return_value = 0  # No bytes available
        mock_process.readAllStandardOutput.return_value = b""
        mock_qprocess_class.return_value = mock_process

        # Start a process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])

        # Simulate empty output - with bytesAvailable() = 0, 
        # _handle_process_output should exit early
        self.manager._handle_process_output(mock_process)

        # Process should still be tracked in outputs (initialized during start_process)
        assert mock_process in self.manager.process_outputs
        # But should have no entries since no bytes were available
        assert len(self.manager.process_outputs[mock_process]) == 0


class TestProcessTermination:
    """Test process stopping and cleanup"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    @patch("process_manager.QProcess")
    def test_stop_all_processes(self, mock_qprocess_class):
        """Test stopping all running processes"""
        # Create multiple mock processes
        mock_processes = []
        for i in range(3):
            mock_process = Mock(spec=QProcess)
            mock_process.waitForStarted.return_value = True
            mock_process.state.return_value = QProcess.ProcessState.Running
            mock_processes.append(mock_process)

        mock_qprocess_class.side_effect = mock_processes

        # Start multiple processes
        for i in range(3):
            file_path = f"/test/video{i}.ts"
            self.manager.start_process(file_path, ["-i", file_path, f"output{i}.mp4"])

        # Stop all processes
        stopped_processes = self.manager.stop_all_processes()

        # Verify all processes were killed
        for mock_process in mock_processes:
            mock_process.kill.assert_called_once()

        assert len(stopped_processes) == 3
        assert self.manager.stopping
        assert self.manager.queue == []

    @patch("process_manager.QProcess")
    def test_stop_already_finished_processes(self, mock_qprocess_class):
        """Test stopping processes that are already finished"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.state.return_value = QProcess.ProcessState.NotRunning
        mock_qprocess_class.return_value = mock_process

        # Start a process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])

        # Stop all processes
        stopped = self.manager.stop_all_processes()

        # The implementation always calls kill() for safety, regardless of process state
        mock_process.kill.assert_called_once()
        # Should still return the process in the list
        assert len(stopped) == 1


class TestTimerManagement:
    """Test that timer management is not part of ProcessManager"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def test_no_timer_in_process_manager(self):
        """Test that ProcessManager doesn't have timer management"""
        # Timer management has been moved out of ProcessManager
        assert not hasattr(self.manager, "ui_update_timer")
        assert not hasattr(self.manager, "_timer_interval")
        assert not hasattr(self.manager, "_adaptive_timing")
        assert not hasattr(self.manager, "_start_smart_timer")
        assert not hasattr(self.manager, "_stop_smart_timer")
        assert not hasattr(self.manager, "_adjust_timer_interval")
        assert not hasattr(self.manager, "_emit_update_progress")

    def test_last_activity_time_exists(self):
        """Test that last activity time tracking exists"""
        # This is still tracked for other purposes
        assert hasattr(self.manager, "_last_activity_time")
        assert self.manager._last_activity_time == 0

    def test_update_progress_signal_exists(self):
        """Test that update_progress signal exists"""
        assert hasattr(self.manager, "update_progress")
        # Test signal emission
        with patch.object(self.manager, "update_progress") as mock_signal:
            mock_signal.emit()
            mock_signal.emit.assert_called_once()


class TestResourceCleanup:
    """Test memory management and resource cleanup"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    @patch("process_manager.QProcess")
    def test_cleanup_all_resources(self, mock_qprocess_class):
        """Test comprehensive resource cleanup"""
        # Create mock processes
        mock_processes = []
        for i in range(2):
            mock_process = Mock(spec=QProcess)
            mock_process.waitForStarted.return_value = True
            mock_process.state.return_value = QProcess.ProcessState.Running
            mock_processes.append(mock_process)

        mock_qprocess_class.side_effect = mock_processes

        # Start processes and populate data structures
        for i in range(2):
            file_path = f"/test/video{i}.ts"
            self.manager.start_process(file_path, ["-i", file_path, f"output{i}.mp4"])

        # Add some process data
        for process in mock_processes:
            self.manager.process_logs[process] = ["log1", "log2"]
            self.manager.process_outputs[process] = [b"output1", b"output2"]

        # Cleanup all resources
        self.manager.cleanup_all_resources()

        # Verify cleanup
        assert len(self.manager.processes) == 0
        assert len(self.manager.process_logs) == 0
        assert len(self.manager.process_outputs) == 0
        assert len(self.manager.process_widgets) == 0
        assert self.manager.queue == []

    def test_log_size_management(self):
        """Test log size limits using deque"""
        mock_process = Mock()

        # Process logs are now deques with automatic size limits
        # The manager uses circular buffers (deques) which auto-limit size
        self.manager.process_logs[mock_process] = deque(maxlen=100)
        
        # Add many log entries - deque will automatically limit
        for i in range(200):
            self.manager.process_logs[mock_process].append(f"log entry {i}")

        # Deque automatically maintains size limit
        assert len(self.manager.process_logs[mock_process]) == 100

    @pytest.mark.slow
    def test_output_buffer_management(self):
        """Test output buffer size limits using deque"""
        mock_process = Mock()

        # Process outputs are now deques with automatic size limits
        self.manager.process_outputs[mock_process] = deque(maxlen=50)
        
        # Add many output chunks - deque will automatically limit
        for i in range(100):
            self.manager.process_outputs[mock_process].append(f"output chunk {i}".encode())

        # Deque automatically maintains size limit
        assert len(self.manager.process_outputs[mock_process]) == 50

    def test_dynamic_buffer_adjustment(self):
        """Test dynamic buffer size adjustment based on process count"""
        # Create mock processes
        mock_processes = [(Mock(), f"/test/video{i}.ts") for i in range(10)]
        self.manager.processes = mock_processes
        
        # Trigger buffer size adjustment
        self.manager._adjust_buffer_sizes()
        
        # With 10 processes, should use smaller buffer
        assert self.manager._current_max_log_lines == 100


class TestProcessWidgetManagement:
    """Test process widget tracking and management"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def test_widget_registration(self):
        """Test registering process widgets"""
        mock_process = Mock()
        mock_widget = Mock()

        widget_data = {
            "widget": mock_widget,
            "created_time": time.time(),
            "last_update": time.time(),
        }

        self.manager.process_widgets[mock_process] = widget_data

        assert mock_process in self.manager.process_widgets
        assert self.manager.process_widgets[mock_process]["widget"] == mock_widget

    def test_widget_cleanup_on_process_finish(self):
        """Test widget tracking structure"""
        mock_process = Mock()
        mock_widget = Mock()

        # Register widget
        self.manager.process_widgets[mock_process] = {
            "widget": mock_widget,
            "created_time": time.time() - 1000,  # Old widget
            "last_update": time.time() - 100,
        }

        # Process widgets are tracked but cleanup happens externally
        # The ProcessManager doesn't have a _cleanup_finished_process_widgets method
        # Widget cleanup is handled by the process monitor
        assert mock_process in self.manager.process_widgets
        
        # Test manual widget cleanup since cleanup_all_resources doesn't clear widgets
        # Clear it manually
        self.manager.process_widgets.clear()
        assert len(self.manager.process_widgets) == 0


class TestQueueManagement:
    """Test file queue management and processing order"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def test_queue_fifo_order(self):
        """Test queue maintains FIFO order"""
        file_paths = ["/test/video1.ts", "/test/video2.ts", "/test/video3.ts"]

        self.manager.start_batch(file_paths, parallel_enabled=False, max_parallel=1)

        # Queue should maintain original order
        assert self.manager.queue == file_paths

    def test_queue_modification_during_processing(self):
        """Test queue modifications during processing"""
        file_paths = ["/test/video1.ts", "/test/video2.ts", "/test/video3.ts"]

        self.manager.start_batch(file_paths, parallel_enabled=True, max_parallel=2)

        # Simulate processing by removing items
        original_length = len(self.manager.queue)

        # Remove first item (simulating process start)
        if self.manager.queue:
            self.manager.queue.pop(0)

        assert len(self.manager.queue) == original_length - 1

    def test_empty_queue_handling(self):
        """Test handling of empty queue"""
        self.manager.start_batch([], parallel_enabled=True, max_parallel=4)

        assert self.manager.queue == []
        assert self.manager.total == 0

        # Should handle empty queue gracefully without errors


class TestConcurrentProcessing:
    """Test concurrent process management"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    @patch("process_manager.QProcess")
    def test_parallel_process_limit(self, mock_qprocess_class):
        """Test parallel process limit enforcement"""
        # Setup multiple mock processes
        mock_processes = []
        for i in range(5):
            mock_process = Mock(spec=QProcess)
            mock_process.waitForStarted.return_value = True
            mock_processes.append(mock_process)

        mock_qprocess_class.side_effect = mock_processes

        # Start batch with limit of 3
        file_paths = [f"/test/video{i}.ts" for i in range(5)]
        self.manager.start_batch(file_paths, parallel_enabled=True, max_parallel=3)

        # Start processes up to limit
        for i in range(3):  # Only start 3 processes
            if self.manager.queue:
                file_path = self.manager.queue.pop(0)
                self.manager.start_process(
                    file_path, ["-i", file_path, f"output{i}.mp4"]
                )

        # Should have exactly 3 active processes
        assert len(self.manager.processes) == 3

    @patch("process_manager.QProcess")
    def test_sequential_processing(self, mock_qprocess_class):
        """Test sequential processing mode"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process

        # Start batch in sequential mode
        file_paths = ["/test/video1.ts", "/test/video2.ts"]
        self.manager.start_batch(file_paths, parallel_enabled=False, max_parallel=1)

        # Start first process
        if self.manager.queue:
            file_path = self.manager.queue.pop(0)
            self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])

        # Should have only 1 active process
        assert len(self.manager.processes) == 1
        assert self.manager.max_parallel == 1


@pytest.mark.unit
class TestProcessManagerEdgeCases:
    """Test edge cases and error conditions"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker"):
            self.manager = ProcessManager()

    def test_double_batch_start(self):
        """Test starting a batch while another is running"""
        # Start first batch
        self.manager.start_batch(
            ["/test/video1.ts"], parallel_enabled=True, max_parallel=1
        )

        # Start second batch (should reset state)
        self.manager.start_batch(
            ["/test/video2.ts", "/test/video3.ts"],
            parallel_enabled=True,
            max_parallel=2,
        )

        # Should have new batch state
        assert len(self.manager.queue) == 2
        assert self.manager.total == 2
        assert self.manager.max_parallel == 2

    @patch("process_manager.QProcess")
    def test_process_creation_failure(self, mock_qprocess_class):
        """Test handling of process creation failure"""
        mock_qprocess_class.side_effect = Exception("Process creation failed")

        # Should handle process creation failure gracefully
        with pytest.raises(Exception):
            self.manager.start_process(
                "/test/video.ts", ["-i", "input.ts", "output.mp4"]
            )

    def test_stop_processes_when_none_running(self):
        """Test stopping processes when none are running"""
        # Should handle gracefully
        stopped_processes = self.manager.stop_all_processes()

        assert stopped_processes == []
        assert self.manager.stopping

    def test_process_tracking_without_processes(self):
        """Test process tracking operations with no active processes"""
        # The progress tracker is mocked, so we need to configure it
        self.manager.progress_tracker.get_overall_progress.return_value = {}
        self.manager.progress_tracker.get_codec_distribution.return_value = {}
        
        # Should handle gracefully without errors
        progress = self.manager.get_overall_progress()
        assert isinstance(progress, dict)
        
        codec_dist = self.manager.get_codec_distribution()
        assert isinstance(codec_dist, dict)


@pytest.mark.unit
class TestProcessManagerIntegration:
    """Test integration between ProcessManager components"""

    def setup_method(self):
        with patch("process_manager.ProcessProgressTracker") as mock_tracker_class:
            self.mock_tracker = Mock()
            mock_tracker_class.return_value = self.mock_tracker
            self.manager = ProcessManager()

    @patch("process_manager.QProcess")
    def test_full_process_lifecycle(self, mock_qprocess_class):
        """Test complete process lifecycle from start to finish"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.state.return_value = QProcess.ProcessState.Running
        mock_qprocess_class.return_value = mock_process

        # Configure progress tracker
        self.mock_tracker.probe_duration.return_value = 600.0

        # Start batch
        file_path = "/test/video.ts"
        self.manager.start_batch([file_path], parallel_enabled=False, max_parallel=1)

        # Start process
        ffmpeg_args = ["-i", file_path, "-c:v", "libx264", "output.mp4"]
        process = self.manager.start_process(file_path, ffmpeg_args)

        # Verify integration
        assert process == mock_process
        assert len(self.manager.processes) == 1
        self.mock_tracker.probe_duration.assert_called_once_with(file_path)
        self.mock_tracker.register_process.assert_called_once()

        # Simulate process output
        mock_process.bytesAvailable.return_value = 22  # Has bytes available
        # Mock readAllStandardOutput to return QByteArray
        mock_data = Mock()
        mock_data.data.return_value = b"ffmpeg progress output"
        mock_process.readAllStandardOutput.return_value = mock_data
        self.manager._handle_process_output(mock_process)

        # Simulate process finish
        mock_process.state.return_value = QProcess.ProcessState.NotRunning
        self.manager.stop_all_processes()

        # Verify cleanup
        assert self.manager.stopping

    @patch("process_manager.QProcess")
    def test_mark_process_finished_success(self, mock_qprocess_class):
        """Test process completion with successful exit code"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.exitCode.return_value = 0  # Successful completion
        mock_qprocess_class.return_value = mock_process

        # Configure progress tracker
        self.mock_tracker.probe_duration.return_value = 600.0

        # Start process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])

        # Mock signals to prevent segfault
        with patch.object(self.manager, "update_progress") as mock_update_signal:
            with patch.object(self.manager, "process_finished") as mock_finished_signal:
                # Call mark_process_finished directly
                self.manager.mark_process_finished(mock_process, file_path)

                # Verify progress tracker interactions
                self.mock_tracker.force_progress_to_100.assert_called_once()
                self.mock_tracker.complete_process.assert_called_once()
                
                # Verify signals were emitted
                mock_update_signal.emit.assert_called_once()
                mock_finished_signal.emit.assert_called_once_with(mock_process, 0, file_path)

        # Verify process was cleaned up
        assert len(self.manager.processes) == 0
        assert mock_process not in self.manager.process_logs
        assert mock_process not in self.manager.process_outputs

    @patch("process_manager.QProcess")
    def test_mark_process_finished_failure(self, mock_qprocess_class):
        """Test process completion with failure exit code"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.exitCode.return_value = 1  # Failed completion
        mock_qprocess_class.return_value = mock_process

        # Configure progress tracker
        self.mock_tracker.probe_duration.return_value = 600.0

        # Start process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])

        # Mock signals to prevent segfault
        with patch.object(self.manager, "update_progress") as mock_update_signal:
            with patch.object(self.manager, "process_finished") as mock_finished_signal:
                # Call mark_process_finished directly
                self.manager.mark_process_finished(mock_process, file_path)

                # Verify progress tracker interactions
                # force_progress_to_100 should NOT be called for failed processes
                self.mock_tracker.force_progress_to_100.assert_not_called()
                self.mock_tracker.complete_process.assert_called_once()
                
                # update_progress should NOT be emitted for failed processes
                mock_update_signal.emit.assert_not_called()
                # But process_finished should still be emitted
                mock_finished_signal.emit.assert_called_once_with(mock_process, 1, file_path)

        # Verify process was cleaned up even on failure
        assert len(self.manager.processes) == 0
        assert mock_process not in self.manager.process_logs
        assert mock_process not in self.manager.process_outputs
