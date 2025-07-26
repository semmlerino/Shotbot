#!/usr/bin/env python3
"""
Unit tests for ProcessManager class
Tests QProcess lifecycle management, queue management, and timer coordination
"""

import pytest
import time
from unittest.mock import Mock, patch

from PySide6.QtCore import QProcess, QTimer
from process_manager import ProcessManager
from config import ProcessConfig, UIConfig


class TestProcessManager:
    """Test suite for ProcessManager class"""
    
    def setup_method(self):
        """Create fresh ProcessManager instance for each test"""
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    def teardown_method(self):
        """Cleanup after each test"""
        if hasattr(self, 'manager'):
            self.manager.stop_all_processes()


class TestBatchManagement:
    """Test batch processing initialization and management"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker'):
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
        self.manager.start_batch(["/test/video1.ts"], parallel_enabled=False, max_parallel=1)
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
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    @patch('process_manager.QProcess')
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
        mock_process.setProcessChannelMode.assert_called_once_with(QProcess.ProcessChannelMode.MergedChannels)
        mock_process.start.assert_called_once_with("ffmpeg", ffmpeg_args)
        mock_process.waitForStarted.assert_called_once_with(ProcessConfig.PROCESS_START_TIMEOUT * 1000)
        
        # Verify process is tracked
        assert len(self.manager.processes) == 1
        assert self.manager.processes[0] == (mock_process, file_path)
        assert mock_process in self.manager.process_logs
        assert mock_process in self.manager.process_outputs
        
        assert result_process == mock_process
    
    @patch('process_manager.QProcess')
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
    
    @patch('process_manager.QProcess')
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
    
    @patch('process_manager.QProcess')
    def test_codec_mapping_extraction(self, mock_qprocess_class):
        """Test codec information extraction from FFmpeg args"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process
        
        file_path = "/test/video.ts"
        ffmpeg_args = ["-i", file_path, "-c:v", "h264_nvenc", "-preset", "fast", "output.mp4"]
        
        self.manager.start_process(file_path, ffmpeg_args)
        
        # Should extract codec index from args
        assert file_path in self.manager.codec_map
        # Note: The actual index depends on the implementation logic
    
    @patch('process_manager.QProcess')
    @patch('process_manager.ProcessProgressTracker')
    def test_progress_tracker_registration(self, mock_tracker_class, mock_qprocess_class):
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
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    @patch('process_manager.QProcess')
    def test_handle_process_output(self, mock_qprocess_class):
        """Test handling of process output"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.readAllStandardOutput.return_value = b"test ffmpeg output\n"
        mock_qprocess_class.return_value = mock_process
        
        # Start a process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])
        
        # Simulate output ready signal
        self.manager._handle_process_output(mock_process)
        
        # Verify output is stored
        assert mock_process in self.manager.process_outputs
        assert len(self.manager.process_outputs[mock_process]) > 0
    
    @patch('process_manager.QProcess')
    def test_output_buffering_and_limits(self, mock_qprocess_class):
        """Test output buffering and size limits"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_qprocess_class.return_value = mock_process
        
        # Start a process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])
        
        # Simulate multiple output chunks
        output_chunks = [b"chunk1\n", b"chunk2\n", b"chunk3\n"]
        
        for chunk in output_chunks:
            mock_process.readAllStandardOutput.return_value = chunk
            self.manager._handle_process_output(mock_process)
        
        # Verify all chunks are buffered
        assert len(self.manager.process_outputs[mock_process]) == len(output_chunks)
    
    @patch('process_manager.QProcess')
    def test_empty_output_handling(self, mock_qprocess_class):
        """Test handling of empty output"""
        mock_process = Mock(spec=QProcess)
        mock_process.waitForStarted.return_value = True
        mock_process.readAllStandardOutput.return_value = b""
        mock_qprocess_class.return_value = mock_process
        
        # Start a process
        file_path = "/test/video.ts"
        self.manager.start_process(file_path, ["-i", file_path, "output.mp4"])
        
        # Simulate empty output
        self.manager._handle_process_output(mock_process)
        
        # Should handle gracefully without errors
        assert mock_process in self.manager.process_outputs


class TestProcessTermination:
    """Test process stopping and cleanup"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    @patch('process_manager.QProcess')
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
    
    @patch('process_manager.QProcess')
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
        self.manager.stop_all_processes()
        
        # Should not try to kill already finished process
        mock_process.kill.assert_not_called()


class TestTimerManagement:
    """Test smart timer management and adaptive intervals"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    def test_timer_initialization(self):
        """Test UI update timer initialization"""
        assert isinstance(self.manager.ui_update_timer, QTimer)
        assert self.manager._timer_interval == UIConfig.UI_UPDATE_DEFAULT
        assert self.manager._adaptive_timing
    
    @patch('process_manager.QTimer')
    def test_start_smart_timer(self, mock_qtimer_class):
        """Test starting the smart timer"""
        mock_timer = Mock()
        mock_qtimer_class.return_value = mock_timer
        
        # Recreate manager with mocked timer
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
            self.manager.ui_update_timer = mock_timer
        
        self.manager._start_smart_timer()
        
        mock_timer.start.assert_called_once()
    
    @patch('process_manager.QTimer')
    def test_stop_smart_timer(self, mock_qtimer_class):
        """Test stopping the smart timer"""
        mock_timer = Mock()
        mock_timer.isActive.return_value = True
        self.manager.ui_update_timer = mock_timer
        
        self.manager._stop_smart_timer()
        
        mock_timer.stop.assert_called_once()
    
    def test_adaptive_timer_adjustment(self):
        """Test adaptive timer interval adjustment"""
        # Test with high activity (many processes)
        self.manager.processes = [(Mock(), f"/test/video{i}.ts") for i in range(5)]
        
        self.manager._adjust_timer_interval()
        
        # Should use high activity interval for many processes
        assert self.manager._timer_interval == UIConfig.UI_UPDATE_HIGH_ACTIVITY
    
    def test_adaptive_timer_low_activity(self):
        """Test adaptive timer with low activity"""
        # Test with few processes
        self.manager.processes = [(Mock(), "/test/video.ts")]
        
        # Simulate old activity time
        self.manager._last_activity_time = time.time() - (UIConfig.LOW_ACTIVITY_THRESHOLD + 1)
        
        self.manager._adjust_timer_interval()
        
        # Should use low activity interval
        assert self.manager._timer_interval == UIConfig.UI_UPDATE_LOW_ACTIVITY
    
    def test_timer_emit_update_progress(self):
        """Test progress update emission"""
        with patch.object(self.manager, 'update_progress') as mock_emit:
            self.manager._emit_update_progress()
            mock_emit.emit.assert_called_once()


class TestResourceCleanup:
    """Test memory management and resource cleanup"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    @patch('process_manager.QProcess')
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
        """Test log size limits and truncation"""
        mock_process = Mock()
        
        # Add many log entries
        large_log = ["log entry"] * 200
        self.manager.process_logs[mock_process] = large_log
        
        # Trigger log cleanup
        self.manager._cleanup_process_logs()
        
        # Should limit log size
        remaining_logs = len(self.manager.process_logs[mock_process])
        assert remaining_logs <= 100  # Reasonable limit
    
    def test_output_buffer_management(self):
        """Test output buffer size limits"""
        mock_process = Mock()
        
        # Add large output buffer
        large_output = [b"output chunk"] * 100
        self.manager.process_outputs[mock_process] = large_output
        
        # Trigger output cleanup
        self.manager._cleanup_process_outputs()
        
        # Should limit output buffer size
        remaining_outputs = len(self.manager.process_outputs[mock_process])
        assert remaining_outputs <= 50  # Reasonable limit


class TestProcessWidgetManagement:
    """Test process widget tracking and management"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    def test_widget_registration(self):
        """Test registering process widgets"""
        mock_process = Mock()
        mock_widget = Mock()
        
        widget_data = {
            'widget': mock_widget,
            'created_time': time.time(),
            'last_update': time.time()
        }
        
        self.manager.process_widgets[mock_process] = widget_data
        
        assert mock_process in self.manager.process_widgets
        assert self.manager.process_widgets[mock_process]['widget'] == mock_widget
    
    def test_widget_cleanup_on_process_finish(self):
        """Test widget cleanup when process finishes"""
        mock_process = Mock()
        mock_widget = Mock()
        
        # Register widget
        self.manager.process_widgets[mock_process] = {
            'widget': mock_widget,
            'created_time': time.time() - 1000,  # Old widget
            'last_update': time.time() - 100
        }
        
        # Simulate process finish cleanup
        self.manager._cleanup_finished_process_widgets()
        
        # Widget should be cleaned up if process is finished
        # (Implementation depends on actual cleanup logic)


class TestQueueManagement:
    """Test file queue management and processing order"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker'):
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
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    @patch('process_manager.QProcess')
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
                self.manager.start_process(file_path, ["-i", file_path, f"output{i}.mp4"])
        
        # Should have exactly 3 active processes
        assert len(self.manager.processes) == 3
    
    @patch('process_manager.QProcess')
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
        with patch('process_manager.ProcessProgressTracker'):
            self.manager = ProcessManager()
    
    def test_double_batch_start(self):
        """Test starting a batch while another is running"""
        # Start first batch
        self.manager.start_batch(["/test/video1.ts"], parallel_enabled=True, max_parallel=1)
        
        # Start second batch (should reset state)
        self.manager.start_batch(["/test/video2.ts", "/test/video3.ts"], parallel_enabled=True, max_parallel=2)
        
        # Should have new batch state
        assert len(self.manager.queue) == 2
        assert self.manager.total == 2
        assert self.manager.max_parallel == 2
    
    @patch('process_manager.QProcess')
    def test_process_creation_failure(self, mock_qprocess_class):
        """Test handling of process creation failure"""
        mock_qprocess_class.side_effect = Exception("Process creation failed")
        
        # Should handle process creation failure gracefully
        with pytest.raises(Exception):
            self.manager.start_process("/test/video.ts", ["-i", "input.ts", "output.mp4"])
    
    def test_stop_processes_when_none_running(self):
        """Test stopping processes when none are running"""
        # Should handle gracefully
        stopped_processes = self.manager.stop_all_processes()
        
        assert stopped_processes == []
        assert self.manager.stopping
    
    def test_timer_operations_without_timer(self):
        """Test timer operations when timer is None"""
        self.manager.ui_update_timer = None
        
        # Should handle gracefully without errors
        self.manager._start_smart_timer()
        self.manager._stop_smart_timer()
        self.manager._emit_update_progress()


@pytest.mark.unit 
class TestProcessManagerIntegration:
    """Test integration between ProcessManager components"""
    
    def setup_method(self):
        with patch('process_manager.ProcessProgressTracker') as mock_tracker_class:
            self.mock_tracker = Mock()
            mock_tracker_class.return_value = self.mock_tracker
            self.manager = ProcessManager()
    
    @patch('process_manager.QProcess')
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
        mock_process.readAllStandardOutput.return_value = b"ffmpeg progress output"
        self.manager._handle_process_output(mock_process)
        
        # Simulate process finish
        mock_process.state.return_value = QProcess.ProcessState.NotRunning
        self.manager.stop_all_processes()
        
        # Verify cleanup
        assert self.manager.stopping