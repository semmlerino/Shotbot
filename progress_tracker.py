#!/usr/bin/env python3
"""
Progress Tracker Module for PyMPEG
Handles parsing ffmpeg output and calculating progress metrics and ETAs
"""

import time
import threading
from typing import Dict, Any, Optional, List

from config import UIConfig, ProcessConfig
from logging_config import get_logger
from output_buffer import ProcessOutputManager


class ProcessProgressTracker:
    """Tracks progress for ffmpeg encoding processes"""

    def __init__(self):
        """Initialize the progress tracker"""
        self.logger = get_logger()
        self.processes: Dict[str, Dict[str, Any]] = {}
        self.batch_start_time: Optional[float] = None
        self.completed_count = 0
        self.total_count = 0
        self._lock = threading.RLock()  # Reentrant lock for thread safety

        # For ETA smoothing
        self.prev_eta_values: List[float] = []
        self.eta_window_size = (
            3  # Use last 3 ETAs for smoothing (reduced for more responsiveness)
        )
        self.last_progress_time = 0
        self.last_progress_value = 0
        self.force_eta_update_interval = (
            UIConfig.FORCE_UPDATE_INTERVAL
        )  # Force ETA update every N seconds even with small progress

        # Track processes that need special ffmpeg flags
        self.needs_genpts: Dict[str, bool] = {}  # Process IDs that need -fflags +genpts

        # Initialize output buffer manager for optimized processing
        self.output_manager = ProcessOutputManager(batch_interval=0.1)

    def start_batch(self, total_files: int):
        """Start tracking a batch of processes"""
        self.batch_start_time = time.time()
        self.completed_count = 0
        self.total_count = total_files

    def register_process(self, process_id: str, path: str, duration: float):
        """Register a new process to track"""
        with self._lock:
            self.processes[process_id] = {
                "path": path,
                "duration": duration,
                "start_time": time.time(),
                "current_pct": 0,
                "fps": 0,
                "last_frame": 0,
                "last_fps_time": time.time(),
                "elapsed_sec": 0,
                "prev_eta_values": [],  # For ETA smoothing per process
                "last_progress_time": 0,
                "last_progress_value": 0,
            }
            return self.processes[process_id]

    def mark_needs_genpts(self, process_id: str) -> None:
        """Mark a process as needing the genpts ffmpeg flag"""
        self.needs_genpts[process_id] = True

    def needs_genpts_flag(self, process_id: str) -> bool:
        """Check if a process needs the genpts ffmpeg flag"""
        return self.needs_genpts.get(process_id, False)

    def force_progress_to_100(self, process_id: str):
        """Force a process progress to 100% for final display"""
        with self._lock:
            if process_id in self.processes:
                self.processes[process_id]["current_pct"] = 100

    def complete_process(self, process_id: str, success: bool = True):
        """Mark a process as completed"""
        with self._lock:
            if process_id in self.processes:
                if success:
                    # Force progress to 100% for successful completion
                    self.processes[process_id]["current_pct"] = 100
                    self.completed_count += 1
                del self.processes[process_id]

                # Clean up genpts tracking
                self.needs_genpts.pop(process_id, None)

                # Clean up output buffer
                self.output_manager.remove_buffer(process_id)

    def process_output(self, process_id: str, chunk: str) -> Dict[str, Any]:
        """
        Process ffmpeg output chunk and update progress information
        Returns updated progress data if successful, empty dict otherwise
        """
        if process_id not in self.processes:
            return {}

        # Add chunk to buffer for batch processing
        buffer = self.output_manager.get_buffer(process_id)
        buffer.add_output(chunk)

        # Get batch-processed results
        results = buffer.process_batch()

        if not results["has_data"]:
            return {}

        process = self.processes[process_id]

        # Update process data from batch results
        elapsed_sec = results["elapsed_sec"]
        process["elapsed_sec"] = elapsed_sec
        process["fps"] = results["fps"]

        # Calculate percentage based on duration
        duration = process["duration"]
        if not duration:
            return {}

        # Update progress percentage
        pct = min(100, round(elapsed_sec / duration * 100))
        process["current_pct"] = pct

        # Calculate remaining time with more precision
        elapsed = time.time() - process["start_time"]
        if pct > 0:
            remain = (elapsed / pct) * (100 - pct)  # More precise calculation
        else:
            remain = 0

        # Prepare result with formatted times and progress data
        return {
            "process_id": process_id,
            "current_pct": pct,
            "elapsed_sec": elapsed_sec,
            "duration": duration,
            "fps": process["fps"],
            "elapsed": elapsed,
            "elapsed_str": self._format_time(elapsed),
            "remain": remain,
            "remain_str": self._format_time(remain),
            "path": process["path"],
        }

    def force_batch_process_all(self) -> None:
        """Force immediate batch processing for all active processes"""
        with self._lock:
            # Create a list copy to avoid modification during iteration
            process_ids = list(self.processes.keys())
            for process_id in process_ids:
                if process_id in self.processes:  # Check if still exists
                    buffer = self.output_manager.get_buffer(process_id)
                    buffer.force_process()

    def get_overall_progress(self) -> Dict[str, Any]:
        """
        Calculate overall progress metrics for all active processes
        Returns a dictionary with overall stats
        """
        if not self.batch_start_time:
            return {}

        # Use lock to ensure thread safety for cache operations
        with self._lock:
            # Check if we need to recalculate (cache for performance)
            current_time = time.time()
            if hasattr(self, "_last_overall_calc_time") and hasattr(
                self, "_last_overall_result"
            ):
                if current_time - self._last_overall_calc_time < 0.1:  # 100ms cache
                    return self._last_overall_result

        # Batch process all outputs for accurate data
        self.output_manager.process_all_batches()

        # Calculate overall progress percentage
        process_progress_sum = sum(p["current_pct"] for p in self.processes.values())
        active_count = len(self.processes)

        # Calculate weighted progress (completed files count as 100%)
        if self.total_count > 0:  # Avoid division by zero
            weighted_pct = (
                process_progress_sum + (self.completed_count * 100)
            ) / self.total_count
        else:
            weighted_pct = 0

        # Get current time for calculations
        elapsed_total = current_time - self.batch_start_time

        # Calculate time-based progress rate rather than percentage-based
        # This makes the ETA calculation more stable
        current_progress_rate = 0
        if weighted_pct > 0:  # Avoid division by zero
            # Calculate instantaneous rate
            if self.last_progress_value > 0 and current_time > self.last_progress_time:
                time_diff = current_time - self.last_progress_time
                progress_diff = weighted_pct - self.last_progress_value

                # Update ETA in two cases:
                # 1. When we've made meaningful progress
                # 2. When it's been a while since our last update
                should_update = (
                    progress_diff > 0.05 and time_diff > 0.5
                ) or time_diff > self.force_eta_update_interval

                if should_update:
                    # Calculate progress rate (%/second)
                    current_progress_rate = progress_diff / time_diff

                    # Always ensure some minimum rate to prevent infinite ETA
                    min_rate = 0.001  # Minimum progress rate of 0.001% per second
                    current_progress_rate = max(current_progress_rate, min_rate)

                    # Calculate raw ETA based on current rate
                    raw_eta = (100 - weighted_pct) / current_progress_rate

                    # Cap the raw ETA at a reasonable maximum
                    max_possible_eta = 3600 * 24  # 24 hours max
                    raw_eta = min(raw_eta, max_possible_eta)

                    # Add to the list of recent ETAs
                    self.prev_eta_values.append(raw_eta)
                    # Keep only the most recent values
                    if len(self.prev_eta_values) > self.eta_window_size:
                        self.prev_eta_values.pop(0)

            # Use fallback calculation if we don't have enough data yet
            if not self.prev_eta_values:
                total_eta = (elapsed_total / weighted_pct) * (100 - weighted_pct)
                self.prev_eta_values.append(total_eta)

            # Calculate smoothed ETA using weighted moving average
            # Give more weight to recent values
            weights = [i + 1 for i in range(len(self.prev_eta_values))]
            total_weight = sum(weights)
            smoothed_eta = sum(
                eta * (w / total_weight)
                for eta, w in zip(self.prev_eta_values, weights)
            )

            # Apply sanity limits to ETA
            # If progress is >90%, ETA shouldn't be more than 10 minutes
            if weighted_pct > 90 and smoothed_eta > 600:
                smoothed_eta = min(smoothed_eta, 600)

            # Store values for next calculation
            self.last_progress_time = current_time
            self.last_progress_value = weighted_pct
        else:
            smoothed_eta = 0

        result = {
            "weighted_pct": weighted_pct,
            "elapsed_total": elapsed_total,
            "elapsed_str": self._format_time(elapsed_total),
            "total_eta": smoothed_eta,
            "eta_str": self._format_time(smoothed_eta),
            "active_count": active_count,
            "completed_count": self.completed_count,
            "total_count": self.total_count,
        }

        # Cache the result with thread safety
        with self._lock:
            self._last_overall_calc_time = current_time
            self._last_overall_result = result

        return result

    def get_codec_distribution(self, codec_map: Dict[str, int]) -> Dict[str, int]:
        """Calculate distribution of active encoders by type (GPU/CPU)"""
        codec_counts = {"GPU": 0, "CPU": 0}

        for process_id, data in self.processes.items():
            path = data["path"]
            if path in codec_map:
                codec_idx = codec_map[path]
                # Assuming codec indices 0-2 are GPU encoders, the rest are CPU
                codec_type = "GPU" if codec_idx in [0, 1, 2] else "CPU"
                codec_counts[codec_type] += 1

        return codec_counts

    def get_process_progress(self, process_id: str) -> Optional[Dict[str, Any]]:
        """Get progress information for a specific process"""
        with self._lock:
            if process_id not in self.processes:
                return None

            process = self.processes[process_id]

            # Check cache first
            if "last_result" in process and "last_result_time" in process:
                if time.time() - process["last_result_time"] < 0.05:  # 50ms cache
                    return process["last_result"]

        # Get current time and progress data
        current_time = time.time()
        elapsed = current_time - process["start_time"]
        pct = process["current_pct"]

        # Apply the same smoothing algorithm used in overall progress
        if pct > 0:
            # Calculate instantaneous rate if we have previous data
            if (
                process["last_progress_value"] > 0
                and current_time > process["last_progress_time"]
            ):
                time_diff = current_time - process["last_progress_time"]
                progress_diff = pct - process["last_progress_value"]

                # Update more aggressively for individual files
                should_update = (progress_diff > 0.01) or (time_diff > 2.0)

                if should_update:
                    # Calculate progress rate (%/second) with minimum threshold
                    current_rate = max(
                        progress_diff / time_diff, 0.0005
                    )  # Ensure some movement

                    # Calculate raw ETA based on current rate
                    raw_eta = (100 - pct) / current_rate

                    # Cap at reasonable maximum
                    raw_eta = min(
                        raw_eta, 3600 * 12
                    )  # Max 12 hours for individual file

                    # Add to the list of recent ETAs for this process
                    process["prev_eta_values"].append(raw_eta)
                    # Keep very small window for individual processes to be more responsive
                    if len(process["prev_eta_values"]) > 2:
                        process["prev_eta_values"].pop(0)

            # Use fallback calculation if we don't have enough data yet
            if not process["prev_eta_values"]:
                basic_eta = (elapsed / pct) * (100 - pct)
                process["prev_eta_values"].append(basic_eta)

            # Calculate smoothed ETA using weighted moving average
            weights = [
                i + 1 for i in range(len(process["prev_eta_values"]))
            ]  # More weight to recent values
            total_weight = sum(weights)
            smoothed_eta = sum(
                eta * (w / total_weight)
                for eta, w in zip(process["prev_eta_values"], weights)
            )

            # Apply sanity check - ETA shouldn't increase significantly when progress is high
            if pct > 80 and len(process["prev_eta_values"]) > 1:
                # Don't let ETA increase by more than 20% when we're near the end
                previous_eta = process["prev_eta_values"][-2]
                if smoothed_eta > previous_eta * 1.2:
                    smoothed_eta = previous_eta * 1.2

            # Store current values for next calculation
            process["last_progress_time"] = current_time
            process["last_progress_value"] = pct

            remain = smoothed_eta
        else:
            remain = 0

        # Return a copy of the process data with additional calculated fields
        result = {
            "process_id": process_id,
            "current_pct": pct,
            "elapsed_sec": process.get("elapsed_sec", 0),
            "duration": process["duration"],
            "fps": process["fps"],
            "elapsed": elapsed,
            "elapsed_str": self._format_time(elapsed),
            "remain": remain,
            "remain_str": self._format_time(remain),
            "path": process["path"],
        }

        # Cache the result with thread safety
        with self._lock:
            # Recheck if process still exists before caching
            if process_id in self.processes:
                self.processes[process_id]["last_result"] = result
                self.processes[process_id]["last_result_time"] = current_time

        return result

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as HH:MM:SS"""
        return time.strftime("%H:%M:%S", time.gmtime(seconds))

    @staticmethod
    def probe_duration(path: str) -> Optional[float]:
        """
        Probe a media file for its duration using ffprobe
        Returns duration in seconds or None if it can't be determined
        """
        logger = get_logger()  # Get logger instance for static method
        try:
            import subprocess

            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=ProcessConfig.SUBPROCESS_TIMEOUT,
            )

            if result.stdout.strip():
                return float(result.stdout.strip())
        except subprocess.TimeoutExpired:
            logger.log_process_timeout(
                f"ffprobe for {path}", ProcessConfig.SUBPROCESS_TIMEOUT
            )
        except (subprocess.CalledProcessError, ValueError, OSError):
            logger.warning(
                f"Failed to probe duration for {path}",
                suggestion="Check if the file is a valid video file",
            )

        return None
