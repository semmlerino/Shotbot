#!/usr/bin/env python3
"""
Process Manager Module for PyMPEG
Handles the creation, management, and monitoring of FFmpeg processes
"""

import os
import subprocess
import time
from typing import Dict, List, Tuple, Any, Optional

from PySide6.QtCore import QProcess, QTimer, QObject, Signal

from progress_tracker import ProcessProgressTracker
from config import ProcessConfig, UIConfig
from logging_config import get_logger


class ProcessManager(QObject):
    """Manages FFmpeg processes for video conversion"""

    # Signal emitted when process output is available
    output_ready = Signal(QProcess, str)

    # Signal emitted when process has finished
    process_finished = Signal(QProcess, int, str)

    # Signal emitted when overall progress should be updated
    update_progress = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Initialize logger
        self.logger = get_logger()

        # Initialize process tracking
        self.processes: List[Tuple[QProcess, str]] = []
        self.process_widgets: Dict[QProcess, Dict] = {}
        self.process_logs: Dict[QProcess, List[str]] = {}
        self.process_outputs: Dict[QProcess, List[str]] = {}

        # Queue management
        self.queue: List[str] = []
        self.total = 0
        self.completed = 0

        # Progress tracking
        self.progress_tracker = ProcessProgressTracker()
        self.codec_map: Dict[str, int] = {}  # Maps file paths to codec indices

        # Smart UI update timer with adaptive intervals
        self.ui_update_timer = QTimer()
        self.ui_update_timer.timeout.connect(self._emit_update_progress)
        self.ui_update_timer.setSingleShot(False)
        
        # Timer management
        self._timer_interval = UIConfig.UI_UPDATE_DEFAULT  # Default interval in ms
        self._last_activity_time = 0
        self._adaptive_timing = True

        # Conversion state
        self.stopping = False
        self.parallel_enabled = False
        self.max_parallel = 1
        
        # GPU memory monitoring
        self._last_vram_check = 0
        self._vram_check_interval = 5  # Check every 5 seconds
        self._min_vram_mb = 2048  # Minimum 2GB VRAM per encode

    def start_batch(
        self,
        file_paths: List[str],
        parallel_enabled: bool = False,
        max_parallel: int = 1,
    ):
        """Start a new batch conversion process"""
        self.queue = list(file_paths)
        self.total = len(self.queue)
        self.completed = 0
        self.stopping = False
        self.parallel_enabled = parallel_enabled
        self.max_parallel = max_parallel

        # Initialize progress tracker
        self.progress_tracker.start_batch(self.total)

        # Start smart UI update timer
        self._start_smart_timer()

    def start_process(self, path: str, ffmpeg_args: List[str]) -> QProcess:
        """
        Start a new FFmpeg process for the given file
        Returns the created process object
        """
        # Create process
        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        # Set up signals
        process.readyReadStandardOutput.connect(
            lambda p=process: self._handle_process_output(p)
        )

        # Set up error handling
        process.errorOccurred.connect(
            lambda error, p=process: self.logger.error(
                f"QProcess error occurred: {error} - {p.errorString()}",
                suggestion="Check if FFmpeg is properly installed and accessible"
            )
        )

        # Start the process with error checking
        self.logger.log_ffmpeg_start(path, ffmpeg_args)
        process.start("ffmpeg", ffmpeg_args)

        # Wait for process to actually start (up to 5 seconds)
        if not process.waitForStarted(ProcessConfig.PROCESS_START_TIMEOUT * 1000):
            self.logger.log_process_timeout(
                f"FFmpeg process for {os.path.basename(path)}", 
                ProcessConfig.PROCESS_START_TIMEOUT
            )
            # Still continue with tracking so we can handle the error properly

        # Add to tracking structures
        self.processes.append((process, path))
        self.process_logs[process] = []
        self.process_outputs[process] = []

        # Register with progress tracker
        duration = self.progress_tracker.probe_duration(path)
        if duration:
            self.progress_tracker.register_process(str(id(process)), path, duration)

        # Store codec information for this file
        codec_idx = ffmpeg_args.index("-c:v") + 1 if "-c:v" in ffmpeg_args else -1
        if codec_idx >= 0 and codec_idx < len(ffmpeg_args):
            self.codec_map[path] = codec_idx

        return process

    def stop_all_processes(self):
        """Stop all running processes"""
        self.stopping = True

        # Kill any running QProcess
        for process, _ in self.processes:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()

        # Stop the smart timer
        self._stop_smart_timer()

        # Reset the progress tracker
        self.progress_tracker.start_batch(0)

        # Clear the queue
        self.queue = []

        return self.processes.copy()

    # Duplicate process_finished removed to resolve mypy no-redef error.

    def _handle_process_output(self, process: QProcess):
        """Process output from an FFmpeg process"""
        if process.bytesAvailable() > 0:
            data = process.readAllStandardOutput()
            # Ensure data.data() is bytes before decoding to satisfy mypy
            buf = data.data()
            if isinstance(buf, memoryview):
                chunk = buf.tobytes().decode("utf-8", errors="replace")
            else:
                chunk = buf.decode("utf-8", errors="replace")

            # Check for MPEGTS timing errors
            if (
                "start time for stream" in chunk
                and "is not set in estimate_timings_from_pts" in chunk
            ):
                # Log this warning for UI display
                self.process_logs[process].append(
                    "⚠️ MPEGTS timing warning detected. Adding -fflags +genpts to improve timestamps."
                )

                # Store this detection for future process restarts if needed
                path = next((p for proc, p in self.processes if proc == process), None)
                if path:
                    # Mark this file as needing genpts flag for potential restart
                    self.progress_tracker.mark_needs_genpts(str(id(process)))

            # Store the output
            self.process_outputs[process].append(chunk)
            self.process_logs[process].append(chunk)

            # Process the output with the progress tracker
            path = next((p for proc, p in self.processes if proc == process), None)
            if path:
                self.progress_tracker.process_output(str(id(process)), chunk)

            # Emit signal for UI handling
            self.output_ready.emit(process, chunk)

    def _emit_update_progress(self):
        """Emit signal to update UI with progress and manage timer efficiency"""
        # Only emit if we have active processes
        if self.processes:
            self.update_progress.emit()
            self._last_activity_time = time.time()
            
            # Adjust timer interval based on activity
            if self._adaptive_timing:
                self._adjust_timer_interval()
        else:
            # No active processes, stop the timer
            self._stop_smart_timer()
    
    def _start_smart_timer(self):
        """Start the timer only when needed"""
        if not self.ui_update_timer.isActive() and (self.processes or self.queue):
            self._timer_interval = UIConfig.UI_UPDATE_DEFAULT  # Reset to default
            self.ui_update_timer.start(self._timer_interval)
            self._last_activity_time = time.time()
    
    def _stop_smart_timer(self):
        """Stop the timer when not needed"""
        if self.ui_update_timer.isActive():
            self.ui_update_timer.stop()
    
    def _adjust_timer_interval(self):
        """Dynamically adjust timer interval based on activity level"""
        if not self._adaptive_timing:
            return
            
        current_time = time.time()
        time_since_activity = current_time - self._last_activity_time
        
        # Adaptive intervals based on process count and activity
        if len(self.processes) >= 4:
            # High activity - faster updates
            new_interval = UIConfig.UI_UPDATE_HIGH_ACTIVITY
        elif len(self.processes) >= 2:
            # Medium activity
            new_interval = UIConfig.UI_UPDATE_DEFAULT
        elif time_since_activity > UIConfig.LOW_ACTIVITY_THRESHOLD:
            # Low activity for a while - slower updates
            new_interval = UIConfig.UI_UPDATE_LOW_ACTIVITY
        else:
            # Single process or recent activity
            new_interval = UIConfig.UI_UPDATE_DEFAULT
        
        # Only update if interval changed significantly
        if abs(new_interval - self._timer_interval) > 100:
            self._timer_interval = new_interval
            if self.ui_update_timer.isActive():
                self.ui_update_timer.setInterval(new_interval)

    def get_overall_progress(self) -> Dict[str, Any]:
        """Get overall progress information"""
        return self.progress_tracker.get_overall_progress()

    def get_codec_distribution(self) -> Dict[str, int]:
        """Get distribution of active encoders by type"""
        return self.progress_tracker.get_codec_distribution(self.codec_map)

    def get_process_progress(self, process: QProcess) -> Optional[Dict[str, Any]]:
        """Get progress information for a specific process"""
        return self.progress_tracker.get_process_progress(str(id(process)))

    def mark_process_finished(self, process: QProcess, process_path: str) -> None:
        """Mark process as finished, update tracker, and emit finished signal."""
        exit_code = process.exitCode() if hasattr(process, "exitCode") else -1
        
        # Guaranteed cleanup for this process
        self._cleanup_process_resources(process)
        
        # Mark as completed in progress tracker
        self.progress_tracker.complete_process(
            str(id(process)), success=(exit_code == 0)
        )
        # Emit process finished signal
        self.process_finished.emit(process, exit_code, process_path)
    
    def _cleanup_process_resources(self, process: QProcess) -> None:
        """Guaranteed cleanup of all resources associated with a process"""
        # Remove from tracking list
        self.processes = [(p, path) for (p, path) in self.processes if p != process]
        
        # Clean up logs and outputs with bounds checking
        if process in self.process_logs:
            logs = self.process_logs.pop(process)
            # Limit log history to prevent memory leaks
            if len(logs) > 1000:
                logs = logs[-500:]  # Keep only last 500 entries
                
        if process in self.process_outputs:
            outputs = self.process_outputs.pop(process)
            # Clear large output buffers
            outputs.clear()
            del self.process_outputs[process]
        
        # Remove from codec mapping
        process_path = None
        for p, path in self.processes:
            if p == process:
                process_path = path
                break
        if process_path and process_path in self.codec_map:
            del self.codec_map[process_path]
    
    def cleanup_all_resources(self) -> None:
        """Emergency cleanup of all resources - called on shutdown"""
        # Kill any remaining processes
        for process, _ in self.processes:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(3000)  # Wait up to 3 seconds
        
        # Clear all tracking structures
        self.processes.clear()
        self.process_logs.clear()
        self.process_outputs.clear()
        self.codec_map.clear()
        
        # Stop smart timer
        self._stop_smart_timer()
    
    def get_available_vram(self) -> int:
        """Get available GPU VRAM in MB. Returns 0 if unable to detect."""
        current_time = time.time()
        
        # Check if we need to update VRAM info
        if current_time - self._last_vram_check < self._vram_check_interval:
            return getattr(self, '_cached_vram', 0)
        
        try:
            import subprocess
            # Query GPU memory info
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                # Parse available memory (first GPU)
                vram_mb = int(result.stdout.strip().split('\n')[0])
                self._cached_vram = vram_mb
                self._last_vram_check = current_time
                return vram_mb
                
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError, OSError):
            pass
        
        self._cached_vram = 0
        return 0
    
    def can_start_gpu_encode(self) -> bool:
        """Check if there's enough VRAM to start a new GPU encode."""
        available_vram = self.get_available_vram()
        
        # Estimate VRAM needed for new encode
        estimated_vram_per_encode = self._min_vram_mb
        
        # Check if we have enough VRAM
        return available_vram >= estimated_vram_per_encode
    
    def set_process_priority(self, process: QProcess, priority: str) -> None:
        """Set process priority. Priority can be 'high', 'normal', or 'low'."""
        try:
            if os.name == 'nt':  # Windows
                priority_classes = {
                    'high': subprocess.HIGH_PRIORITY_CLASS,
                    'normal': subprocess.NORMAL_PRIORITY_CLASS,
                    'low': subprocess.IDLE_PRIORITY_CLASS
                }
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, process.processId())
                if handle:
                    ctypes.windll.kernel32.SetPriorityClass(handle, priority_classes.get(priority, subprocess.NORMAL_PRIORITY_CLASS))
                    ctypes.windll.kernel32.CloseHandle(handle)
            else:  # Linux/Unix
                nice_values = {
                    'high': -10,
                    'normal': 0,
                    'low': 10
                }
                os.nice(nice_values.get(priority, 0))
        except Exception as e:
            self.logger.warning(f"Failed to set process priority: {e}")
