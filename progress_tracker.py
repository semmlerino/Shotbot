#!/usr/bin/env python3
"""
Progress Tracker Module for PyMPEG
Handles parsing ffmpeg output and calculating progress metrics and ETAs
"""

import re
import time
from typing import Dict, Any, Optional, List

from config import UIConfig, ProcessConfig
from logging_config import get_logger


class ProcessProgressTracker:
    """Tracks progress for ffmpeg encoding processes"""

    # Regex patterns for parsing ffmpeg output
    TIME_RE = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
    FPS_RE = re.compile(r"fps=\s*(\d+)")
    FRAME_RE = re.compile(r"frame=\s*(\d+)")

    def __init__(self):
        """Initialize the progress tracker"""
        self.logger = get_logger()
        self.processes: Dict[str, Dict[str, Any]] = {}
        self.batch_start_time: Optional[float] = None
        self.completed_count = 0
        self.total_count = 0

        # For ETA smoothing
        self.prev_eta_values: List[float] = []
        self.eta_window_size = 3  # Use last 3 ETAs for smoothing (reduced for more responsiveness)
        self.last_progress_time = 0
        self.last_progress_value = 0
        self.force_eta_update_interval = UIConfig.FORCE_UPDATE_INTERVAL  # Force ETA update every N seconds even with small progress

        # Track processes that need special ffmpeg flags
        self.needs_genpts: Dict[str, bool] = {}  # Process IDs that need -fflags +genpts

    def start_batch(self, total_files: int):
        """Start tracking a batch of processes"""
        self.batch_start_time = time.time()
        self.completed_count = 0
        self.total_count = total_files

    def register_process(self, process_id: str, path: str, duration: float):
        """Register a new process to track"""
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

    def complete_process(self, process_id: str, success: bool = True):
        """Mark a process as completed"""
        if process_id in self.processes:
            if success:
                self.completed_count += 1
            del self.processes[process_id]

            # Clean up genpts tracking
            self.needs_genpts.pop(process_id, None)

    def process_output(self, process_id: str, chunk: str) -> Dict[str, Any]:
        """
        Process ffmpeg output chunk and update progress information
        Returns updated progress data if successful, empty dict otherwise
        """
        if process_id not in self.processes:
            return {}

        process = self.processes[process_id]

        # Extract FPS information if present
        fps_match = self.FPS_RE.search(chunk)
        if fps_match:
            current_fps = int(fps_match.group(1))
            process["fps"] = current_fps

        # Look for time progress in ffmpeg output
        time_match = self.TIME_RE.search(chunk)
        if not time_match:
            return {}

        # Parse time and calculate progress
        h, m, s = time_match.groups()
        elapsed_sec = int(h) * 3600 + int(m) * 60 + float(s)
        process["elapsed_sec"] = elapsed_sec

        # Calculate percentage based on duration
        duration = process["duration"]
        if not duration:
            return {}

        # Update progress percentage
        pct = min(100, int(elapsed_sec / duration * 100))
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

    def get_overall_progress(self) -> Dict[str, Any]:
        """
        Calculate overall progress metrics for all active processes
        Returns a dictionary with overall stats
        """
        if not self.batch_start_time:
            return {}

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
        current_time = time.time()
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

        return {
            "weighted_pct": weighted_pct,
            "elapsed_total": elapsed_total,
            "elapsed_str": self._format_time(elapsed_total),
            "total_eta": smoothed_eta,
            "eta_str": self._format_time(smoothed_eta),
            "active_count": active_count,
            "completed_count": self.completed_count,
            "total_count": self.total_count,
        }

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
        if process_id in self.processes:
            process = self.processes[process_id]

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
            return {
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

        return None

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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=ProcessConfig.SUBPROCESS_TIMEOUT)

            if result.stdout.strip():
                return float(result.stdout.strip())
        except subprocess.TimeoutExpired:
            logger.log_process_timeout(f"ffprobe for {path}", ProcessConfig.SUBPROCESS_TIMEOUT)
        except (subprocess.CalledProcessError, ValueError, OSError):
            logger.warning(f"Failed to probe duration for {path}", suggestion="Check if the file is a valid video file")

        return None
