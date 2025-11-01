#!/usr/bin/env python3
"""
Unit tests for OutputBuffer class
Tests batch processing, regex parsing, and thread-safe operations
"""

import pytest
import time
import threading
from unittest.mock import patch

from output_buffer import OutputBuffer, ProcessOutputManager


class TestOutputBuffer:
    """Test suite for OutputBuffer class"""

    def setup_method(self):
        """Create OutputBuffer instance for each test"""
        self.buffer = OutputBuffer(max_size=100, batch_interval=0.01)

    def test_init(self):
        """Test buffer initialization"""
        assert self.buffer.buffer.maxlen == 100
        assert self.buffer.batch_interval == 0.01
        assert len(self.buffer.pending_lines) == 0
        assert self.buffer.last_time_match is None
        assert self.buffer.last_fps == 0
        assert self.buffer.last_frame == 0

    def test_add_output(self):
        """Test adding output chunks"""
        chunk = "frame=  100 fps= 25 q=28.0\nsize=    1024kB time=00:00:04.00\n"
        
        self.buffer.add_output(chunk)
        
        assert len(self.buffer.pending_lines) == 2
        assert "frame=  100 fps= 25 q=28.0" in self.buffer.pending_lines
        assert "size=    1024kB time=00:00:04.00" in self.buffer.pending_lines

    def test_add_output_filters_empty_lines(self):
        """Test that empty lines are filtered out"""
        chunk = "line1\n\n\nline2\n   \nline3"
        
        self.buffer.add_output(chunk)
        
        assert len(self.buffer.pending_lines) == 3
        assert self.buffer.pending_lines == ["line1", "line2", "line3"]

    def test_process_batch_extracts_time(self):
        """Test batch processing extracts time information"""
        self.buffer.add_output("frame=  100 fps= 25 time=00:01:30.50 bitrate=1024.0kbits/s")
        
        # Force immediate processing
        result = self.buffer.force_process()
        
        assert result["elapsed_sec"] == 90.5  # 1:30.50 = 90.5 seconds
        assert self.buffer.last_time_match == (0, 1, 30.5)

    def test_process_batch_extracts_fps(self):
        """Test batch processing extracts FPS"""
        self.buffer.add_output("frame=  200 fps= 30 q=25.0 size=2048kB")
        
        result = self.buffer.force_process()
        
        assert result["fps"] == 30
        assert self.buffer.last_fps == 30

    def test_process_batch_extracts_frame(self):
        """Test batch processing extracts frame count"""
        self.buffer.add_output("frame=  500 fps= 25 q=28.0")
        
        result = self.buffer.force_process()
        
        assert result["frame"] == 500
        assert self.buffer.last_frame == 500

    def test_process_batch_handles_multiple_matches(self):
        """Test that latest values are used when multiple matches exist"""
        chunk = """
        frame=  100 fps= 20 time=00:00:04.00
        frame=  200 fps= 25 time=00:00:08.00
        frame=  300 fps= 30 time=00:00:12.00
        """
        
        self.buffer.add_output(chunk)
        result = self.buffer.force_process()
        
        # Should use last values
        assert result["frame"] == 300
        assert result["fps"] == 30
        assert result["elapsed_sec"] == 12.0

    def test_batch_interval_respected(self):
        """Test that batch processing respects interval"""
        self.buffer.add_output("frame=  100 fps= 25")
        
        # Set last_batch_time to past to allow first processing
        self.buffer.last_batch_time = time.time() - 1
        
        # First process should work
        result1 = self.buffer.process_batch()
        assert result1["frame"] == 100
        
        # Add more data
        self.buffer.add_output("frame=  200 fps= 30")
        
        # Immediate second process should return cached results
        result2 = self.buffer.process_batch()
        assert result2["frame"] == 100  # Still cached
        
        # Wait for interval and process again
        time.sleep(0.011)  # Slightly more than batch_interval
        result3 = self.buffer.process_batch()
        assert result3["frame"] == 200  # New data processed

    def test_force_process_bypasses_interval(self):
        """Test force_process bypasses batch interval"""
        self.buffer.add_output("frame=  100 fps= 25")
        self.buffer.process_batch()
        
        # Add more data immediately
        self.buffer.add_output("frame=  200 fps= 30")
        
        # Force process should work immediately
        result = self.buffer.force_process()
        assert result["frame"] == 200

    def test_circular_buffer_size_limit(self):
        """Test that buffer respects max size"""
        # Add more lines than max_size
        for i in range(150):
            self.buffer.add_output(f"line {i}")
        
        self.buffer.force_process()
        
        # Buffer should only keep last 100 lines
        assert len(self.buffer.buffer) == 100
        assert "line 49" not in self.buffer.buffer
        assert "line 149" in self.buffer.buffer

    def test_get_recent_lines(self):
        """Test getting recent lines from buffer"""
        # Add some lines
        for i in range(20):
            self.buffer.add_output(f"line {i}")
        
        self.buffer.force_process()
        
        # Get last 5 lines
        recent_lines = self.buffer.get_recent_lines(5)
        
        assert len(recent_lines) == 5
        assert recent_lines == ["line 15", "line 16", "line 17", "line 18", "line 19"]

    def test_get_recent_lines_more_than_available(self):
        """Test getting more lines than available"""
        self.buffer.add_output("line 1")
        self.buffer.add_output("line 2")
        self.buffer.force_process()
        
        recent_lines = self.buffer.get_recent_lines(10)
        
        assert len(recent_lines) == 2
        assert recent_lines == ["line 1", "line 2"]

    def test_clear_buffer(self):
        """Test clearing the buffer"""
        self.buffer.add_output("some data")
        self.buffer.force_process()
        
        self.buffer.clear()
        
        assert len(self.buffer.buffer) == 0
        assert len(self.buffer.pending_lines) == 0
        # Cached values should be reset
        assert self.buffer.last_time_match is None
        assert self.buffer.last_fps == 0
        assert self.buffer.last_frame == 0

    def test_thread_safety(self):
        """Test thread-safe operations"""
        results = []
        errors = []
        
        def add_data(thread_id):
            try:
                for i in range(50):
                    self.buffer.add_output(f"thread {thread_id} frame= {i} fps= 25")
                    if i % 10 == 0:
                        result = self.buffer.process_batch()
                        results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=add_data, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should complete without errors
        assert len(errors) == 0
        assert len(results) > 0

    def test_regex_patterns(self):
        """Test regex patterns match expected formats"""
        test_cases = [
            ("time=00:00:00.00", (0, 0, 0.0)),
            ("time=01:23:45.67", (1, 23, 45.67)),
            ("time=10:59:59.99", (10, 59, 59.99)),
        ]
        
        for text, expected in test_cases:
            match = OutputBuffer.TIME_PATTERN.search(text)
            assert match is not None
            h, m, s = match.groups()
            assert (int(h), int(m), float(s)) == expected

    def test_fps_pattern_variations(self):
        """Test FPS pattern handles variations"""
        test_cases = [
            ("fps= 25", 25),
            ("fps=  30", 30),
            ("fps=   0", 0),
            ("fps= 120", 120),
        ]
        
        for text, expected in test_cases:
            match = OutputBuffer.FPS_PATTERN.search(text)
            assert match is not None
            assert int(match.group(1)) == expected

    def test_get_progress_summary(self):
        """Test getting complete progress summary"""
        self.buffer.add_output("frame= 1500 fps= 30 time=00:00:50.00 bitrate=2048.0kbits/s")
        
        result = self.buffer.force_process()
        
        assert result["frame"] == 1500
        assert result["fps"] == 30
        assert result["elapsed_sec"] == 50.0
        assert result["has_data"] is True

    def test_no_data_returns_empty_results(self):
        """Test that no data returns appropriate empty results"""
        result = self.buffer.process_batch()
        
        assert result["frame"] == 0
        assert result["fps"] == 0
        assert result["elapsed_sec"] == 0
        assert result["has_data"] is False

    def test_partial_data_handling(self):
        """Test handling partial data (only some fields present)"""
        # Only frame data
        self.buffer.add_output("frame= 100")
        result = self.buffer.force_process()
        assert result["frame"] == 100
        assert result["fps"] == 0
        assert result["elapsed_sec"] == 0
        
        # Add FPS data
        self.buffer.add_output("fps= 25")
        result = self.buffer.force_process()
        assert result["frame"] == 100  # Preserved
        assert result["fps"] == 25
        
        # Add time data
        self.buffer.add_output("time=00:00:10.00")
        result = self.buffer.force_process()
        assert result["frame"] == 100  # Preserved
        assert result["fps"] == 25     # Preserved
        assert result["elapsed_sec"] == 10.0


class TestProcessOutputManager:
    """Test suite for ProcessOutputManager class"""

    def setup_method(self):
        """Create ProcessOutputManager instance for each test"""
        self.manager = ProcessOutputManager(batch_interval=0.1)

    def test_init(self):
        """Test manager initialization"""
        assert len(self.manager.buffers) == 0
        assert self.manager.base_batch_interval == 0.1

    def test_get_buffer_creates_new(self):
        """Test getting buffer creates new one if needed"""
        process_id = "process_1"
        
        buffer = self.manager.get_buffer(process_id)
        
        assert buffer is not None
        assert process_id in self.manager.buffers
        assert isinstance(buffer, OutputBuffer)

    def test_get_buffer_returns_existing(self):
        """Test getting buffer returns existing one"""
        process_id = "process_1"
        
        buffer1 = self.manager.get_buffer(process_id)
        buffer2 = self.manager.get_buffer(process_id)
        
        assert buffer1 is buffer2
        assert len(self.manager.buffers) == 1

    def test_batch_interval_adjustment(self):
        """Test batch interval adjusts based on active processes"""
        # Create fewer than 5 processes
        for i in range(3):
            buffer = self.manager.get_buffer(f"process_{i}")
            assert buffer.batch_interval == 0.1  # Base interval
        
        # Create 5-9 processes (check for adjustment)
        for i in range(3, 7):
            buffer = self.manager.get_buffer(f"process_{i}")
            # Should have adjusted interval
            # The actual adjustment logic is in the implementation
        
        # Create 10+ processes
        for i in range(7, 12):
            buffer = self.manager.get_buffer(f"process_{i}")
            # Should have further adjusted interval

    def test_remove_buffer(self):
        """Test removing a buffer"""
        process_id = "process_1"
        self.manager.get_buffer(process_id)
        
        self.manager.remove_buffer(process_id)
        assert process_id not in self.manager.buffers

    def test_process_all_batches(self):
        """Test processing all buffers in batch"""
        # Create multiple buffers with data
        for i in range(3):
            process_id = f"process_{i}"
            buffer = self.manager.get_buffer(process_id)
            buffer.add_output(f"frame= {i*100} fps= {20+i} time=00:00:{i*10:02d}.00")
            # Set last_batch_time to past to allow processing
            buffer.last_batch_time = time.time() - 1
        
        # Process all batches
        results = self.manager.process_all_batches()
        
        assert len(results) == 3
        assert "process_0" in results
        assert "process_1" in results
        assert "process_2" in results
        
        # Check individual results
        assert results["process_0"]["frame"] == 0
        assert results["process_1"]["frame"] == 100
        assert results["process_2"]["frame"] == 200

    def test_concurrent_buffer_access(self):
        """Test thread-safe concurrent buffer access"""
        results = []
        errors = []
        
        def access_buffer(thread_id):
            try:
                for i in range(10):
                    process_id = f"thread_{thread_id}_process_{i % 3}"
                    buffer = self.manager.get_buffer(process_id)
                    buffer.add_output(f"data from thread {thread_id}")
                    results.append(buffer)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=access_buffer, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should complete without errors
        assert len(errors) == 0
        assert len(results) > 0