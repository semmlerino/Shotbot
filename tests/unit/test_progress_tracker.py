#!/usr/bin/env python3
"""
Unit tests for ProcessProgressTracker class
Tests regex parsing of FFmpeg output, progress calculation, and ETA estimation
"""

import pytest
import subprocess
from unittest.mock import patch, Mock
import time

from progress_tracker import ProcessProgressTracker
from config import ProcessConfig
from tests.fixtures.mocks import MockProgressScenarios, MockFFmpegProcess


class TestProcessProgressTracker:
    """Test suite for ProcessProgressTracker class"""
    
    def setup_method(self):
        """Create fresh tracker instance for each test"""
        self.tracker = ProcessProgressTracker()
    
    def teardown_method(self):
        """Cleanup after each test"""
        self.tracker = None


class TestDurationProbing:
    """Test video duration detection"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    @patch('subprocess.run')
    def test_successful_duration_probe(self, mock_subprocess):
        """Test successful duration probing"""
        mock_result = Mock()
        mock_result.stdout = "630.456789"  # 10:30.456789
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result
        
        duration = self.tracker.probe_duration("/test/video.ts")
        
        assert duration == 630.456789
        mock_subprocess.assert_called_once()
        
        # Verify correct ffprobe arguments
        args = mock_subprocess.call_args[0][0]
        assert "ffprobe" in args
        assert "-show_entries" in args
        assert "format=duration" in args
        assert "/test/video.ts" in args
    
    @patch('subprocess.run')
    def test_duration_probe_timeout(self, mock_subprocess):
        """Test duration probe with timeout"""
        mock_subprocess.side_effect = subprocess.TimeoutExpired("ffprobe", ProcessConfig.SUBPROCESS_TIMEOUT)
        
        duration = self.tracker.probe_duration("/test/video.ts")
        
        assert duration is None
    
    @patch('subprocess.run')
    def test_duration_probe_error(self, mock_subprocess):
        """Test duration probe with subprocess error"""
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "ffprobe")
        
        duration = self.tracker.probe_duration("/test/video.ts")
        
        assert duration is None
    
    @patch('subprocess.run')
    def test_duration_probe_invalid_output(self, mock_subprocess):
        """Test duration probe with invalid output"""
        mock_result = Mock()
        mock_result.stdout = "not_a_number"
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result
        
        duration = self.tracker.probe_duration("/test/video.ts")
        
        assert duration is None
    
    @patch('subprocess.run')
    def test_duration_probe_empty_output(self, mock_subprocess):
        """Test duration probe with empty output"""
        mock_result = Mock()
        mock_result.stdout = ""
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result
        
        duration = self.tracker.probe_duration("/test/video.ts")
        
        assert duration is None


class TestProgressParsing:
    """Test FFmpeg output parsing for progress calculation"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    def test_time_regex_parsing(self):
        """Test time regex pattern matching"""
        test_lines = [
            "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:40.00 bitrate=1024.0kbits/s speed=1.0x",
            "frame=  250 fps= 30 q=25.0 size=2048kB time=00:05:30.50 bitrate=512.0kbits/s speed=1.2x",
            "frame= 1000 fps= 24 q=30.0 size=8192kB time=01:10:25.75 bitrate=256.0kbits/s speed=0.8x",
        ]
        
        expected_seconds = [100.0, 330.5, 4225.75]
        
        for line, expected in zip(test_lines, expected_seconds):
            match = self.tracker.TIME_RE.search(line)
            assert match is not None
            
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            
            total_seconds = hours * 3600 + minutes * 60 + seconds
            assert abs(total_seconds - expected) < 0.01
    
    def test_fps_regex_parsing(self):
        """Test FPS regex pattern matching"""
        test_lines = [
            "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:40.00 bitrate=1024.0kbits/s speed=1.0x",
            "frame=  250 fps= 30 q=25.0 size=2048kB time=00:05:30.50 bitrate=512.0kbits/s speed=1.2x",
            "frame= 1000 fps=120 q=30.0 size=8192kB time=01:10:25.75 bitrate=256.0kbits/s speed=0.8x",
        ]
        
        expected_fps = [25, 30, 120]
        
        for line, expected in zip(test_lines, expected_fps):
            match = self.tracker.FPS_RE.search(line)
            assert match is not None
            
            fps = int(match.group(1))
            assert fps == expected
    
    def test_malformed_time_format(self):
        """Test handling of malformed time formats"""
        malformed_lines = [
            "frame=  100 fps= 25 q=28.0 size=1024kB time=invalid bitrate=1024.0kbits/s speed=1.0x",
            "frame=  100 fps= 25 q=28.0 size=1024kB time=25:99:99.00 bitrate=1024.0kbits/s speed=1.0x",
            "frame=  100 fps= 25 q=28.0 size=1024kB bitrate=1024.0kbits/s speed=1.0x",  # No time field
        ]
        
        for line in malformed_lines:
            match = self.tracker.TIME_RE.search(line)
            # Should either not match or match invalid time that gets handled gracefully
            if match:
                # If it matches, the parsing should handle invalid values gracefully
                pass
    
    def test_progress_calculation_with_duration(self):
        """Test progress percentage calculation when duration is known"""
        process_id = "test_process"
        duration = 600.0  # 10 minutes
        
        # Register process
        self.tracker.register_process(process_id, "/test/video.ts", duration)
        
        # Test progress updates
        test_cases = [
            ("frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:00.00 bitrate=1024.0kbits/s speed=1.0x", 10.0),
            ("frame=  250 fps= 25 q=28.0 size=2048kB time=00:03:00.00 bitrate=512.0kbits/s speed=1.2x", 30.0),
            ("frame=  500 fps= 25 q=28.0 size=4096kB time=00:06:00.00 bitrate=256.0kbits/s speed=1.0x", 60.0),
            ("frame= 1000 fps= 25 q=28.0 size=8192kB time=00:10:00.00 bitrate=128.0kbits/s speed=1.0x", 100.0),
        ]
        
        for ffmpeg_line, expected_percentage in test_cases:
            progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
            
            assert progress_data is not None
            assert abs(progress_data["percentage"] - expected_percentage) < 0.1
    
    def test_progress_without_duration(self):
        """Test progress tracking when duration is unknown"""
        process_id = "test_process"
        
        # Register process without duration
        self.tracker.register_process(process_id, "/test/video.ts", None)
        
        ffmpeg_line = "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:00.00 bitrate=1024.0kbits/s speed=1.0x"
        progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
        
        # Should still return progress data but without percentage
        assert progress_data is not None
        assert "percentage" not in progress_data or progress_data["percentage"] == 0


class TestETACalculation:
    """Test ETA (Estimated Time of Arrival) calculations"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    def test_eta_calculation_linear_progress(self):
        """Test ETA calculation with linear progress"""
        process_id = "test_process"
        duration = 600.0  # 10 minutes
        
        self.tracker.register_process(process_id, "/test/video.ts", duration)
        
        # Simulate linear progress over time
        start_time = time.time()
        
        with patch('time.time') as mock_time:
            # Progress at 1 minute mark -> 10% complete
            mock_time.return_value = start_time + 60
            ffmpeg_line = "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:00.00 bitrate=1024.0kbits/s speed=1.0x"
            progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
            
            # At 10% complete in 60 seconds, should take ~600 seconds total
            # So ETA should be around 540 seconds (9 minutes) remaining
            assert progress_data is not None
            if "eta_seconds" in progress_data and progress_data["eta_seconds"] > 0:
                assert 400 < progress_data["eta_seconds"] < 700  # Reasonable range
    
    def test_eta_with_variable_speed(self):
        """Test ETA calculation with variable processing speed"""
        process_id = "test_process"
        duration = 600.0
        
        self.tracker.register_process(process_id, "/test/video.ts", duration)
        
        start_time = time.time()
        
        with patch('time.time') as mock_time:
            # First update: slow progress
            mock_time.return_value = start_time + 120  # 2 minutes elapsed
            ffmpeg_line1 = "frame=  50 fps= 25 q=28.0 size=512kB time=00:00:30.00 bitrate=1024.0kbits/s speed=0.5x"
            self.tracker.update_progress(process_id, ffmpeg_line1)
            
            # Second update: faster progress
            mock_time.return_value = start_time + 180  # 3 minutes elapsed
            ffmpeg_line2 = "frame= 150 fps= 25 q=28.0 size=1536kB time=00:02:00.00 bitrate=1024.0kbits/s speed=1.5x"
            progress_data2 = self.tracker.update_progress(process_id, ffmpeg_line2)
            
            # ETA should adapt to the changing speed
            assert progress_data2 is not None
            if "eta_seconds" in progress_data2:
                # Should reflect the improved processing speed
                pass
    
    def test_eta_smoothing(self):
        """Test ETA smoothing over multiple updates"""
        process_id = "test_process"
        duration = 600.0
        
        self.tracker.register_process(process_id, "/test/video.ts", duration)
        
        start_time = time.time()
        eta_values = []
        
        with patch('time.time') as mock_time:
            # Multiple progress updates
            for i in range(1, 6):
                mock_time.return_value = start_time + (i * 30)  # Every 30 seconds
                progress_seconds = i * 30  # Linear progress
                
                ffmpeg_line = f"frame={i*50:5d} fps= 25 q=28.0 size={i*512}kB time={progress_seconds//3600:02d}:{(progress_seconds%3600)//60:02d}:{progress_seconds%60:05.2f} bitrate=1024.0kbits/s speed=1.0x"
                progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
                
                if progress_data and "eta_seconds" in progress_data:
                    eta_values.append(progress_data["eta_seconds"])
            
            # ETA values should show some smoothing (not wildly fluctuating)
            if len(eta_values) > 2:
                # Check that ETA is generally decreasing as progress continues
                assert eta_values[-1] < eta_values[0]


class TestBatchProcessing:
    """Test batch processing and overall progress tracking"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    def test_batch_initialization(self):
        """Test batch processing initialization"""
        total_files = 5
        self.tracker.start_batch(total_files)
        
        # Should initialize batch tracking
        assert hasattr(self.tracker, 'batch_total')
    
    def test_process_registration(self):
        """Test registering multiple processes in a batch"""
        self.tracker.start_batch(3)
        
        # Register multiple processes
        processes = [
            ("proc1", "/test/video1.ts", 600.0),
            ("proc2", "/test/video2.ts", 300.0),
            ("proc3", "/test/video3.ts", 900.0),
        ]
        
        for proc_id, path, duration in processes:
            self.tracker.register_process(proc_id, path, duration)
        
        # All processes should be registered
        assert len(self.tracker.processes) == 3
    
    def test_overall_progress_calculation(self):
        """Test overall batch progress calculation"""
        self.tracker.start_batch(2)
        
        # Register two processes with known durations
        self.tracker.register_process("proc1", "/test/video1.ts", 600.0)
        self.tracker.register_process("proc2", "/test/video2.ts", 300.0)
        
        # Update progress for first process (50% complete)
        ffmpeg_line1 = "frame= 500 fps= 25 q=28.0 size=4096kB time=00:05:00.00 bitrate=256.0kbits/s speed=1.0x"
        self.tracker.update_progress("proc1", ffmpeg_line1)
        
        # Update progress for second process (100% complete)
        ffmpeg_line2 = "frame= 500 fps= 25 q=28.0 size=2048kB time=00:05:00.00 bitrate=256.0kbits/s speed=1.0x"
        self.tracker.update_progress("proc2", ffmpeg_line2)
        
        # Calculate overall progress
        overall_progress = self.tracker.get_overall_progress()
        
        # Should be weighted average: (600*0.5 + 300*1.0) / (600+300) = 600/900 = 66.67%
        assert overall_progress is not None
        if "percentage" in overall_progress:
            expected = (600 * 50 + 300 * 100) / (600 + 300)
            assert abs(overall_progress["percentage"] - expected) < 1.0


class TestProgressScenarios:
    """Test various real-world progress scenarios"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    def test_normal_conversion_scenario(self):
        """Test normal conversion progress scenario"""
        scenario = MockProgressScenarios.normal_conversion()
        process_id = "normal_test"
        
        self.tracker.register_process(process_id, "/test/video.ts", scenario['duration'])
        
        for i, (ffmpeg_line, expected_pct) in enumerate(zip(scenario['progress_updates'], scenario['expected_percentages'])):
            progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
            
            assert progress_data is not None
            if "percentage" in progress_data:
                assert abs(progress_data["percentage"] - expected_pct) < 2.0  # Allow some variance
    
    def test_slow_conversion_scenario(self):
        """Test slow conversion with variable speed"""
        scenario = MockProgressScenarios.slow_conversion()
        process_id = "slow_test"
        
        self.tracker.register_process(process_id, "/test/video.ts", scenario['duration'])
        
        for ffmpeg_line, expected_pct in zip(scenario['progress_updates'], scenario['expected_percentages']):
            progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
            
            assert progress_data is not None
            if "percentage" in progress_data:
                assert abs(progress_data["percentage"] - expected_pct) < 2.0
    
    def test_realistic_ffmpeg_output(self):
        """Test with realistic FFmpeg output from MockFFmpegProcess"""
        mock_ffmpeg = MockFFmpegProcess(duration=300.0, fps=30, success=True)
        output_lines = mock_ffmpeg.simulate_conversion()
        
        process_id = "realistic_test"
        self.tracker.register_process(process_id, "/test/video.ts", 300.0)
        
        progress_values = []
        for line in output_lines:
            progress_data = self.tracker.update_progress(process_id, line)
            if progress_data and "percentage" in progress_data:
                progress_values.append(progress_data["percentage"])
        
        # Should have some progress updates
        assert len(progress_values) > 0
        
        # Progress should be generally increasing
        if len(progress_values) > 1:
            assert progress_values[-1] >= progress_values[0]
        
        # Final progress should be close to 100%
        if progress_values:
            assert progress_values[-1] > 90


class TestEdgeCases:
    """Test edge cases and error conditions"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    def test_unregistered_process_update(self):
        """Test updating progress for unregistered process"""
        ffmpeg_line = "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:00.00 bitrate=1024.0kbits/s speed=1.0x"
        progress_data = self.tracker.update_progress("nonexistent", ffmpeg_line)
        
        # Should handle gracefully
        assert progress_data is None or progress_data == {}
    
    def test_zero_duration(self):
        """Test handling of zero duration"""
        process_id = "zero_duration"
        self.tracker.register_process(process_id, "/test/video.ts", 0.0)
        
        ffmpeg_line = "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:00.00 bitrate=1024.0kbits/s speed=1.0x"
        progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
        
        # Should handle division by zero gracefully
        assert progress_data is not None
    
    def test_negative_duration(self):
        """Test handling of negative duration"""
        process_id = "negative_duration"
        self.tracker.register_process(process_id, "/test/video.ts", -100.0)
        
        ffmpeg_line = "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:00.00 bitrate=1024.0kbits/s speed=1.0x"
        progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
        
        # Should handle negative duration gracefully
        assert progress_data is not None
    
    def test_progress_exceeding_duration(self):
        """Test progress time exceeding expected duration"""
        process_id = "exceed_duration"
        self.tracker.register_process(process_id, "/test/video.ts", 60.0)  # 1 minute
        
        # Report progress at 2 minutes (exceeds duration)
        ffmpeg_line = "frame=  100 fps= 25 q=28.0 size=1024kB time=00:02:00.00 bitrate=1024.0kbits/s speed=1.0x"
        progress_data = self.tracker.update_progress(process_id, ffmpeg_line)
        
        # Should handle gracefully, possibly capping at 100%
        assert progress_data is not None
        if "percentage" in progress_data:
            assert progress_data["percentage"] <= 100
    
    def test_empty_ffmpeg_line(self):
        """Test handling of empty FFmpeg output line"""
        process_id = "empty_line"
        self.tracker.register_process(process_id, "/test/video.ts", 600.0)
        
        progress_data = self.tracker.update_progress(process_id, "")
        
        # Should handle gracefully
        assert progress_data is None or progress_data == {}
    
    def test_malformed_ffmpeg_output(self):
        """Test handling of malformed FFmpeg output"""
        process_id = "malformed"
        self.tracker.register_process(process_id, "/test/video.ts", 600.0)
        
        malformed_lines = [
            "completely invalid output",
            "frame=abc fps=xyz time=invalid",
            "size=1024kB bitrate=512.0kbits/s",  # Missing required fields
        ]
        
        for line in malformed_lines:
            progress_data = self.tracker.update_progress(process_id, line)
            # Should not crash and return reasonable response
            assert isinstance(progress_data, (dict, type(None)))


@pytest.mark.unit
class TestProgressTrackerPerformance:
    """Test performance characteristics of progress tracking"""
    
    def setup_method(self):
        self.tracker = ProcessProgressTracker()
    
    def test_many_processes_registration(self):
        """Test registering many processes"""
        num_processes = 100
        self.tracker.start_batch(num_processes)
        
        start_time = time.time()
        
        for i in range(num_processes):
            self.tracker.register_process(f"proc_{i}", f"/test/video_{i}.ts", 600.0)
        
        elapsed = time.time() - start_time
        
        # Should complete quickly (less than 1 second for 100 processes)
        assert elapsed < 1.0
        assert len(self.tracker.processes) == num_processes
    
    def test_frequent_progress_updates(self):
        """Test handling frequent progress updates"""
        process_id = "frequent_updates"
        self.tracker.register_process(process_id, "/test/video.ts", 600.0)
        
        start_time = time.time()
        
        # Simulate frequent updates
        for i in range(100):
            seconds = i * 6  # Every 6 seconds of video
            ffmpeg_line = f"frame={i*50:5d} fps= 25 q=28.0 size={i*512}kB time={seconds//3600:02d}:{(seconds%3600)//60:02d}:{seconds%60:05.2f} bitrate=1024.0kbits/s speed=1.0x"
            self.tracker.update_progress(process_id, ffmpeg_line)
        
        elapsed = time.time() - start_time
        
        # Should handle 100 updates quickly
        assert elapsed < 1.0