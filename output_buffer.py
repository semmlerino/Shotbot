#!/usr/bin/env python3
"""
Optimized Output Buffer for FFmpeg Processing
Implements efficient batch processing and ring buffer for performance
"""

import re
import threading
import time
from collections import deque
from re import Pattern


class OutputBuffer:
    """High-performance output buffer with batch regex processing"""

    # Compiled regex patterns for better performance
    TIME_PATTERN: Pattern[str] = re.compile(
        r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", re.MULTILINE
    )
    FPS_PATTERN: Pattern[str] = re.compile(r"fps=\s*(\d+)", re.MULTILINE)
    FRAME_PATTERN: Pattern[str] = re.compile(r"frame=\s*(\d+)", re.MULTILINE)

    def __init__(self, max_size: int = 1000, batch_interval: float = 0.1):
        """
        Initialize output buffer

        Args:
            max_size: Maximum number of lines to keep in buffer
            batch_interval: Time interval for batch processing (seconds)
        """
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=max_size)
        self.pending_lines: list[str] = []
        self.batch_interval = batch_interval
        self.last_batch_time = time.time()
        self.lock = threading.Lock()

        # Cached results
        self.last_time_match: tuple[int, int, float] | None = None
        self.last_fps: int = 0
        self.last_frame: int = 0

    def add_output(self, chunk: str) -> None:
        """Add output chunk to pending buffer"""
        with self.lock:
            # Split chunk into lines and add to pending
            lines = chunk.split("\n")
            self.pending_lines.extend(line for line in lines if line.strip())

    def process_batch(self) -> dict[str, int | float | bool]:
        """
        Process pending lines in batch for better performance

        Returns:
            Dictionary with extracted progress data
        """
        current_time = time.time()

        # Check if it's time to process
        if current_time - self.last_batch_time < self.batch_interval:
            return self._get_cached_results()

        with self.lock:
            if not self.pending_lines:
                return self._get_cached_results()

            # Join lines for batch regex processing
            batch_text = "\n".join(self.pending_lines)

            # Clear pending lines and add to circular buffer
            self.buffer.extend(self.pending_lines)
            self.pending_lines.clear()

            # Batch regex matching - find all matches at once
            time_matches = list(self.TIME_PATTERN.finditer(batch_text))
            fps_matches = list(self.FPS_PATTERN.finditer(batch_text))
            frame_matches = list(self.FRAME_PATTERN.finditer(batch_text))

            # Update cached values with latest matches
            if time_matches:
                last_match = time_matches[-1]
                h, m, s = last_match.groups()
                self.last_time_match = (int(h), int(m), float(s))

            if fps_matches:
                self.last_fps = int(fps_matches[-1].group(1))

            if frame_matches:
                self.last_frame = int(frame_matches[-1].group(1))

            self.last_batch_time = current_time

        return self._get_cached_results()

    def force_process(self) -> dict[str, int | float | bool]:
        """Force immediate processing of pending data"""
        self.last_batch_time = 0  # Reset timer to force processing
        return self.process_batch()

    def _get_cached_results(self) -> dict[str, int | float | bool]:
        """Get cached results without processing"""
        if self.last_time_match:
            h, m, s = self.last_time_match
            elapsed_sec = h * 3600 + m * 60 + s
        else:
            elapsed_sec = 0

        return {
            "elapsed_sec": elapsed_sec,
            "fps": self.last_fps,
            "frame": self.last_frame,
            "has_data": self.last_time_match is not None,
        }

    def get_recent_lines(self, count: int = 50) -> list[str]:
        """Get recent output lines for display"""
        with self.lock:
            # Include both buffered and pending lines
            all_lines = list(self.buffer) + self.pending_lines
            return all_lines[-count:] if len(all_lines) > count else all_lines

    def clear(self) -> None:
        """Clear all buffers"""
        with self.lock:
            self.buffer.clear()
            self.pending_lines.clear()
            self.last_time_match = None
            self.last_fps = 0
            self.last_frame = 0


class ProcessOutputManager:
    """Manages output buffers for multiple processes"""

    def __init__(self, batch_interval: float = 0.1):
        super().__init__()
        self.buffers: dict[str, OutputBuffer] = {}
        self.base_batch_interval = batch_interval
        self.lock = threading.Lock()

    def get_buffer(self, process_id: str) -> OutputBuffer:
        """Get or create buffer for process"""
        with self.lock:
            if process_id not in self.buffers:
                # Adjust batch interval based on number of active processes
                active_count = len(self.buffers)
                if active_count >= 10:
                    # More processes = longer batch interval to reduce overhead
                    adjusted_interval = self.base_batch_interval * 2.0
                elif active_count >= 5:
                    adjusted_interval = self.base_batch_interval * 1.5
                else:
                    adjusted_interval = self.base_batch_interval

                self.buffers[process_id] = OutputBuffer(
                    batch_interval=adjusted_interval,
                    max_size=500
                    if active_count < 10
                    else 250,  # Reduce buffer size for many processes
                )
            return self.buffers[process_id]

    def remove_buffer(self, process_id: str) -> None:
        """Remove buffer for completed process"""
        with self.lock:
            _ = self.buffers.pop(process_id, None)

    def process_all_batches(self) -> dict[str, dict[str, int | float | bool]]:
        """Process all pending batches and return results"""
        results = {}
        with self.lock:
            for process_id, buffer in self.buffers.items():
                results[process_id] = buffer.process_batch()
        return results
