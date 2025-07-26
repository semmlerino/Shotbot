#!/usr/bin/env python3
"""
Unit tests for the logging system
Tests the structured logging, performance metrics, and user-friendly error messages
"""

import pytest
import tempfile
import os
import time
from unittest.mock import Mock, patch
from pathlib import Path

from logging_config import (
    PyFFMPEGLogger, 
    PerformanceMetrics, 
    UserFriendlyFormatter,
    get_logger,
    setup_logging,
    log_startup,
    log_shutdown
)


class TestPerformanceMetrics:
    """Test performance metrics tracking"""
    
    def setup_method(self):
        self.metrics = PerformanceMetrics()
    
    def test_conversion_time_tracking(self):
        """Test conversion time tracking"""
        file_path = "/test/video.ts"
        
        # Start tracking
        self.metrics.start_conversion(file_path)
        assert file_path in self.metrics.conversion_times
        
        # Finish tracking
        time.sleep(0.1)  # Small delay
        self.metrics.finish_conversion(file_path, 100.0)  # 100 MB file
        
        assert file_path not in self.metrics.conversion_times
        assert file_path in self.metrics.conversion_speeds
        assert self.metrics.conversion_speeds[file_path] > 0
    
    def test_error_recording(self):
        """Test error tracking"""
        self.metrics.record_error("ffmpeg_process")
        self.metrics.record_error("ffmpeg_process")
        self.metrics.record_error("timeout")
        
        assert self.metrics.error_counts["ffmpeg_process"] == 2
        assert self.metrics.error_counts["timeout"] == 1
    
    def test_average_speed_calculation(self):
        """Test average speed calculation"""
        # Add some conversion speeds
        self.metrics.conversion_speeds = {
            "/test/video1.ts": 50.0,  # 50 MB/s
            "/test/video2.ts": 100.0,  # 100 MB/s
            "/test/video3.ts": 75.0   # 75 MB/s
        }
        
        avg_speed = self.metrics.get_average_speed()
        assert abs(avg_speed - 75.0) < 0.1  # Should be 75 MB/s average
    
    def test_error_rate_calculation(self):
        """Test error rate calculation"""
        # 3 successful conversions, 1 error
        self.metrics.conversion_speeds = {
            "/test/video1.ts": 50.0,
            "/test/video2.ts": 60.0,
            "/test/video3.ts": 70.0
        }
        self.metrics.error_counts = {"ffmpeg_process": 1}
        
        error_rate = self.metrics.get_error_rate()
        assert abs(error_rate - 25.0) < 0.1  # 1 error out of 4 total = 25%
    
    def test_empty_metrics(self):
        """Test metrics when no data is available"""
        assert self.metrics.get_average_speed() == 0.0
        assert self.metrics.get_error_rate() == 0.0


class TestUserFriendlyFormatter:
    """Test the user-friendly log formatter"""
    
    def setup_method(self):
        self.formatter = UserFriendlyFormatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%H:%M:%S'
        )
    
    def test_info_formatting(self):
        """Test INFO level formatting"""
        import logging
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test message", args=(), exc_info=None
        )
        
        formatted = self.formatter.format(record)
        assert "ℹ️" in formatted or "INFO" in formatted
        assert "Test message" in formatted
    
    def test_error_with_suggestion(self):
        """Test ERROR formatting with suggestion"""
        import logging
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="Test error", args=(), exc_info=None
        )
        record.suggestion = "Try this fix"
        
        formatted = self.formatter.format(record)
        assert "Test error" in formatted
        assert "💡 Suggestion: Try this fix" in formatted
    
    def test_no_color_mode(self):
        """Test formatting without colors"""
        import logging
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="Test warning", args=(), exc_info=None
        )
        record.no_color = True
        
        formatted = self.formatter.format(record)
        assert "[WARNING]" in formatted
        assert "Test warning" in formatted


class TestPyFFMPEGLogger:
    """Test the main logger class"""
    
    def setup_method(self):
        # Use a temporary logger to avoid interfering with global state
        self.logger = PyFFMPEGLogger("TestLogger")
    
    def teardown_method(self):
        # Clean up handlers
        self.logger.logger.handlers.clear()
    
    def test_logger_initialization(self):
        """Test logger initialization"""
        assert self.logger.name == "TestLogger"
        assert self.logger.metrics is not None
        assert len(self.logger.logger.handlers) > 0  # Should have handlers
    
    def test_log_levels(self):
        """Test different log levels"""
        with patch.object(self.logger, 'log_message') as mock_signal:
            self.logger.debug("Debug message")
            self.logger.info("Info message")
            self.logger.warning("Warning message")
            self.logger.error("Error message")
            self.logger.critical("Critical message")
            
            # Should have emitted signals for each message
            assert mock_signal.emit.call_count == 5
    
    def test_error_with_suggestion(self):
        """Test error logging with suggestions"""
        with patch.object(self.logger, 'error_occurred') as mock_signal:
            self.logger.error("Test error", suggestion="Fix this way")
            
            mock_signal.emit.assert_called_once_with("Test error", "Fix this way")
    
    def test_performance_logging(self):
        """Test performance logging"""
        with patch.object(self.logger, 'performance_update') as mock_signal:
            self.logger.log_performance("test_operation", 1.5, {"param": "value"})
            
            mock_signal.emit.assert_called_once()
            args = mock_signal.emit.call_args[0][0]
            assert args['operation'] == "test_operation"
            assert args['duration'] == 1.5
            assert args['param'] == "value"
    
    def test_ffmpeg_logging_methods(self):
        """Test FFmpeg-specific logging methods"""
        file_path = "/test/video.ts"
        
        # Test start logging
        self.logger.log_ffmpeg_start(file_path, ["-i", file_path, "output.mp4"])
        assert file_path in self.logger.metrics.conversion_times
        
        # Test error logging
        with patch.object(self.logger, 'error_occurred') as mock_signal:
            self.logger.log_ffmpeg_error(file_path, 1, "Invalid file")
            mock_signal.emit.assert_called_once()
        
        # Test success logging
        self.logger.log_ffmpeg_success(file_path, 100.0)
        # Should have finished tracking
        assert file_path not in self.logger.metrics.conversion_times
    
    def test_hardware_detection_logging(self):
        """Test hardware detection logging"""
        gpu_info = "GPU 0: NVIDIA GeForce RTX 4090"
        encoders = ["h264_nvenc", "hevc_nvenc", "libx264"]
        
        with patch.object(self.logger, 'log_message') as mock_signal:
            self.logger.log_hardware_detection(gpu_info, encoders)
            
            # Should have logged GPU detection
            assert mock_signal.emit.call_count >= 1
    
    def test_process_timeout_logging(self):
        """Test process timeout logging"""
        with patch.object(self.logger, 'error_occurred') as mock_signal:
            self.logger.log_process_timeout("test_process", 30)
            
            mock_signal.emit.assert_called_once()
            args = mock_signal.emit.call_args[0]
            assert "test_process" in args[0]
            assert "30 seconds" in args[0]
    
    def test_metrics_summary(self):
        """Test metrics summary generation"""
        # Add some test data
        self.logger.metrics.conversion_speeds["/test/video.ts"] = 50.0
        self.logger.metrics.record_error("test_error")
        
        summary = self.logger.get_metrics_summary()
        
        assert 'average_speed_mbps' in summary
        assert 'error_rate_percent' in summary
        assert 'total_conversions' in summary
        assert 'total_errors' in summary
        assert 'error_breakdown' in summary
        
        assert summary['total_conversions'] == 1
        assert summary['total_errors'] == 1


class TestLoggerSingleton:
    """Test global logger functionality"""
    
    def test_get_logger_singleton(self):
        """Test that get_logger returns the same instance"""
        logger1 = get_logger()
        logger2 = get_logger()
        
        assert logger1 is logger2  # Should be the same instance
    
    def test_setup_logging(self):
        """Test logging setup"""
        logger = setup_logging(debug_mode=True)
        
        assert logger is not None
        assert isinstance(logger, PyFFMPEGLogger)
    
    def test_startup_shutdown_logging(self):
        """Test startup and shutdown logging"""
        with patch('logging_config.get_logger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            
            log_startup()
            mock_logger.info.assert_called()
            
            # Add some metrics for shutdown test
            mock_logger.get_metrics_summary.return_value = {
                'total_conversions': 5,
                'average_speed_mbps': 75.0,
                'error_rate_percent': 10.0
            }
            
            log_shutdown()
            mock_logger.info.assert_called()
            mock_logger.log_performance.assert_called()


class TestLogFileCreation:
    """Test log file creation and rotation"""
    
    def test_log_file_creation(self):
        """Test that log files are created"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Change working directory temporarily
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                
                # Create logger which should create log files
                logger = PyFFMPEGLogger("TestFileLogger")
                logger.info("Test message")
                
                # Check if log directory was created
                log_dir = Path(temp_dir) / "logs"
                assert log_dir.exists()
                
                # Check if log files were created
                log_files = list(log_dir.glob("*.log"))
                assert len(log_files) > 0
                
                # Clean up
                logger.logger.handlers.clear()
                
            finally:
                os.chdir(original_cwd)
    
    def test_log_rotation_configuration(self):
        """Test that log rotation is properly configured"""
        import logging.handlers
        
        logger = PyFFMPEGLogger("TestRotationLogger")
        
        # Check that handlers are RotatingFileHandler
        file_handlers = [h for h in logger.logger.handlers 
                        if isinstance(h, logging.handlers.RotatingFileHandler)]
        
        assert len(file_handlers) > 0  # Should have rotating file handlers
        
        # Check rotation settings
        for handler in file_handlers:
            assert handler.maxBytes > 0
            assert handler.backupCount > 0
        
        # Clean up
        logger.logger.handlers.clear()


class TestIntegrationWithExistingModules:
    """Test integration with existing PyFFMPEG modules"""
    
    def test_process_manager_logging(self):
        """Test that ProcessManager uses logging correctly"""
        from process_manager import ProcessManager
        
        pm = ProcessManager()
        assert hasattr(pm, 'logger')
        assert pm.logger is not None
    
    def test_conversion_controller_logging(self):
        """Test that ConversionController uses logging correctly"""
        from conversion_controller import ConversionController
        from process_manager import ProcessManager
        
        pm = ProcessManager()
        cc = ConversionController(pm)
        assert hasattr(cc, 'logger')
        assert cc.logger is not None
    
    def test_progress_tracker_logging(self):
        """Test that ProgressTracker uses logging correctly"""
        from progress_tracker import ProcessProgressTracker
        
        pt = ProcessProgressTracker()
        assert hasattr(pt, 'logger')
        assert pt.logger is not None
    
    @patch('subprocess.run')
    def test_progress_tracker_timeout_logging(self, mock_subprocess):
        """Test that ProgressTracker logs timeout correctly"""
        import subprocess
        from progress_tracker import ProcessProgressTracker
        
        mock_subprocess.side_effect = subprocess.TimeoutExpired("ffprobe", 30)
        
        pt = ProcessProgressTracker()
        
        with patch.object(pt.logger, 'log_process_timeout') as mock_log:
            result = pt.probe_duration("/test/video.ts")
            
            assert result is None
            mock_log.assert_called_once()


@pytest.mark.integration
class TestLoggingSystemIntegration:
    """Integration tests for the complete logging system"""
    
    def test_full_logging_workflow(self):
        """Test a complete logging workflow"""
        logger = get_logger()
        
        # Test startup
        logger.info("🚀 Starting test workflow")
        
        # Test performance tracking
        start_time = time.time()
        time.sleep(0.1)  # Simulate work
        duration = time.time() - start_time
        
        logger.log_performance("test_operation", duration, {"test_param": "value"})
        
        # Test error with suggestion
        logger.error("Test error occurred", suggestion="Try restarting the application")
        
        # Test hardware detection
        logger.log_hardware_detection("GPU 0: Test GPU", ["test_encoder"])
        
        # Test metrics
        metrics = logger.get_metrics_summary()
        assert isinstance(metrics, dict)
        
        # Test shutdown
        logger.info("🛑 Ending test workflow")
    
    def test_concurrent_logging(self):
        """Test logging from multiple sources"""
        import threading
        
        logger = get_logger()
        results = []
        
        def log_worker(worker_id):
            try:
                logger.info(f"Worker {worker_id} starting")
                time.sleep(0.05)
                logger.debug(f"Worker {worker_id} processing")
                logger.info(f"Worker {worker_id} finished")
                results.append(worker_id)
            except Exception as e:
                results.append(f"Error in worker {worker_id}: {e}")
        
        # Start multiple logging threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=log_worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check that all workers completed
        assert len(results) == 5
        assert all(isinstance(r, int) for r in results)  # No errors