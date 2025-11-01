#!/usr/bin/env python3
"""
Process Manager Module for PyMPEG
Handles the creation, management, and monitoring of FFmpeg processes
"""

import os
import subprocess
from collections import deque
from typing import Dict, List, Tuple, Any, Optional

from PySide6.QtCore import QProcess, QObject, Signal

from progress_tracker import ProcessProgressTracker
from config import ProcessConfig
from logging_config import get_logger


class ProcessManager(QObject):
    """Manages FFmpeg processes for video conversion"""

    # Signal emitted when process output is available
    output_ready = Signal(QProcess, str)

    # Signal emitted when process has finished
    process_finished = Signal(QProcess, int, str)

    # Signal emitted when overall progress should be updated
    update_progress = Signal()

    # Class-level cache for FFmpeg path
    _ffmpeg_command_cache: Optional[str] = None
    _ffmpeg_available_cache: Optional[bool] = None

    # Process ID counter to avoid collisions
    _process_id_counter = 0

    def __init__(self, parent=None):
        super().__init__(parent)

        # Initialize logger
        self.logger = get_logger()

        # Initialize process tracking
        self.processes: List[Tuple[QProcess, str]] = []
        self.process_widgets: Dict[QProcess, Dict] = {}

        # Use deque for memory-efficient circular buffers
        self.process_logs: Dict[QProcess, deque] = {}  # Circular buffer for logs
        self.process_outputs: Dict[QProcess, deque] = {}  # Circular buffer for outputs
        self._base_max_log_lines = 500  # Base maximum lines per process log
        self._current_max_log_lines = (
            500  # Dynamically adjusted based on active processes
        )

        # Map QProcess to unique IDs
        self.process_ids: Dict[QProcess, str] = {}

        # Track signal connections for proper cleanup
        self.process_connections: Dict[QProcess, List[Any]] = {}

        # Queue management
        self.queue: List[str] = []
        self.total = 0
        self.completed = 0

        # Progress tracking
        self.progress_tracker = ProcessProgressTracker()
        self.codec_map: Dict[str, int] = {}  # Maps file paths to codec indices

        # Timer management (simplified with UI update manager)
        self._last_activity_time = 0

        # Conversion state
        self.stopping = False
        self.parallel_enabled = False
        self.max_parallel = 1

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

    def _get_process_id(self, process: QProcess) -> str:
        """Get or create a unique ID for a process"""
        if process not in self.process_ids:
            ProcessManager._process_id_counter += 1
            self.process_ids[process] = f"process_{ProcessManager._process_id_counter}"
        return self.process_ids[process]

    def _adjust_buffer_sizes(self):
        """Dynamically adjust buffer sizes based on number of active processes"""
        active_count = len(self.processes)

        if active_count >= 10:
            # Many processes - reduce buffer to conserve memory
            self._current_max_log_lines = 100
        elif active_count >= 5:
            # Moderate processes
            self._current_max_log_lines = 250
        else:
            # Few processes - use full buffer
            self._current_max_log_lines = self._base_max_log_lines

        # Resize existing buffers if needed
        for process in list(self.process_logs.keys()):
            if (
                process in self.process_logs
                and self.process_logs[process].maxlen != self._current_max_log_lines
            ):
                # Create new deque with adjusted size and copy last N items
                old_data = list(self.process_logs[process])[
                    -self._current_max_log_lines :
                ]
                self.process_logs[process] = deque(
                    old_data, maxlen=self._current_max_log_lines
                )

        for process in list(self.process_outputs.keys()):
            if (
                process in self.process_outputs
                and self.process_outputs[process].maxlen != self._current_max_log_lines
            ):
                # Create new deque with adjusted size and copy last N items
                old_data = list(self.process_outputs[process])[
                    -self._current_max_log_lines :
                ]
                self.process_outputs[process] = deque(
                    old_data, maxlen=self._current_max_log_lines
                )

    def start_process(self, path: str, ffmpeg_args: List[str]) -> QProcess:
        """
        Start a new FFmpeg process for the given file
        Returns the created process object
        """
        # Create process
        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        # Set up signals and track connections for cleanup
        connections = []

        # Output handling connection
        def output_handler(p=process):
            return self._handle_process_output(p)

        process.readyReadStandardOutput.connect(output_handler)
        connections.append(("readyReadStandardOutput", output_handler))

        # Error handling connection
        def error_handler(error, p=process, path=path):
            return self._handle_process_error(error, p, path)

        process.errorOccurred.connect(error_handler)
        connections.append(("errorOccurred", error_handler))

        # Finished handling connection - this is critical for marking completion
        def finished_handler(exit_code, exit_status, p=process, process_path=path):
            return self.mark_process_finished(p, process_path)

        process.finished.connect(finished_handler)
        connections.append(("finished", finished_handler))

        # Store connections for cleanup
        self.process_connections[process] = connections

        # Start the process with error checking
        self.logger.log_ffmpeg_start(path, ffmpeg_args)

        # Use cached FFmpeg command
        ffmpeg_cmd = self._get_ffmpeg_command()
        if not ffmpeg_cmd:
            self.logger.error(
                "FFmpeg not found in system PATH",
                suggestion="Install FFmpeg and ensure it's in your system PATH. Visit https://ffmpeg.org/download.html",
            )
            return process

        # Log the actual arguments being passed
        self.logger.debug(f"Starting {ffmpeg_cmd} with args: {ffmpeg_args}")

        # Start process without manual quoting - Qt handles this automatically
        process.start(ffmpeg_cmd, ffmpeg_args)

        # Wait for process to actually start (up to 5 seconds)
        if not process.waitForStarted(ProcessConfig.PROCESS_START_TIMEOUT * 1000):
            self.logger.log_process_timeout(
                f"FFmpeg process for {os.path.basename(path)}",
                ProcessConfig.PROCESS_START_TIMEOUT,
            )
            # Still continue with tracking so we can handle the error properly

        # Add to tracking structures
        self.processes.append((process, path))

        # Adjust buffer sizes for current process count
        self._adjust_buffer_sizes()

        # Initialize circular buffers for this process with adjusted size
        self.process_logs[process] = deque(maxlen=self._current_max_log_lines)
        self.process_outputs[process] = deque(maxlen=self._current_max_log_lines)

        # Register with progress tracker
        duration = self.progress_tracker.probe_duration(path)
        if duration:
            process_id = self._get_process_id(process)
            self.progress_tracker.register_process(process_id, path, duration)

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
                process_id = self._get_process_id(process)
                progress_data = self.progress_tracker.process_output(process_id, chunk)

                # Signal that we have progress
                if progress_data:
                    # The update_progress signal will be handled by main window
                    self.update_progress.emit()

            # Emit signal for UI handling
            self.output_ready.emit(process, chunk)

    def _using_windows_ffmpeg(self) -> bool:
        """Check if we're using Windows FFmpeg executable"""
        ffmpeg_cmd = self._get_ffmpeg_command()
        if not ffmpeg_cmd:
            return False
        # Check if it's an exe or contains Windows/Program Files paths
        return (
            ffmpeg_cmd.endswith(".exe")
            or "Windows" in ffmpeg_cmd
            or "Program Files" in ffmpeg_cmd
            or ffmpeg_cmd.startswith("C:\\")
        )

    def _get_ffmpeg_command(self) -> Optional[str]:
        """Get cached FFmpeg command or detect it"""
        # Return cached value if available
        if ProcessManager._ffmpeg_command_cache is not None:
            return ProcessManager._ffmpeg_command_cache

        # Try different FFmpeg locations (Windows-focused)
        ffmpeg_commands = [
            "ffmpeg",
            "ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        ]

        for cmd in ffmpeg_commands:
            try:
                result = subprocess.run(
                    [cmd, "-version"],
                    capture_output=True,
                    timeout=2,  # Reduced timeout
                )
                if result.returncode == 0:
                    ProcessManager._ffmpeg_command_cache = cmd
                    ProcessManager._ffmpeg_available_cache = True
                    self.logger.info(f"Found FFmpeg at: {cmd}")
                    return cmd
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue

        ProcessManager._ffmpeg_available_cache = False
        return None

    def _handle_process_error(self, error, process: QProcess, path: str) -> None:
        """Enhanced error handling for process errors"""
        error_names = {
            QProcess.ProcessError.FailedToStart: "FailedToStart",
            QProcess.ProcessError.Crashed: "Crashed",
            QProcess.ProcessError.Timedout: "Timedout",
            QProcess.ProcessError.WriteError: "WriteError",
            QProcess.ProcessError.ReadError: "ReadError",
            QProcess.ProcessError.UnknownError: "UnknownError",
        }

        error_name = error_names.get(error, f"Unknown({error})")
        error_string = process.errorString()

        # Get more context
        program = process.program()
        arguments = process.arguments()

        # Log full command for debugging
        full_command = f"{program} {' '.join(arguments)}"

        self.logger.error(
            f"QProcess error occurred: ProcessError.{error_name} - {error_string}",
            extra_info={
                "file": os.path.basename(path),
                "program": program,
                "arguments": " ".join(arguments[:5]) + "..."
                if len(arguments) > 5
                else " ".join(arguments),
                "error_code": error,
                "process_state": process.state(),
                "full_command": full_command
                if len(full_command) < 500
                else full_command[:500] + "...",
            },
            suggestion="Check if FFmpeg is properly installed and accessible. Try running 'ffmpeg -version' in terminal.",
        )

        # If process crashed, try to get exit code
        if error == QProcess.ProcessError.Crashed:
            exit_code = process.exitCode() if hasattr(process, "exitCode") else -1
            exit_status = process.exitStatus() if hasattr(process, "exitStatus") else -1
            self.logger.error(
                f"Process crashed with exit code: {exit_code}, exit status: {exit_status}"
            )

            # Try to run the command directly to get better error info
            if arguments and len(arguments) < 50:  # Only for reasonable sized commands
                try:
                    ffmpeg_cmd = self._get_ffmpeg_command()
                    if ffmpeg_cmd:
                        test_result = subprocess.run(
                            [ffmpeg_cmd]
                            + arguments[:5],  # Test with just first few args
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        if test_result.stderr:
                            self.logger.error(
                                f"FFmpeg stderr: {test_result.stderr[:500]}"
                            )
                except Exception as e:
                    self.logger.error(f"Failed to test FFmpeg command: {e}")

    def get_overall_progress(self) -> Dict[str, Any]:
        """Get overall progress information"""
        return self.progress_tracker.get_overall_progress()

    def get_codec_distribution(self) -> Dict[str, int]:
        """Get distribution of active encoders by type"""
        return self.progress_tracker.get_codec_distribution(self.codec_map)

    def get_process_progress(self, process: QProcess) -> Optional[Dict[str, Any]]:
        """Get progress information for a specific process"""
        process_id = self._get_process_id(process)
        return self.progress_tracker.get_process_progress(process_id)

    def mark_process_finished(self, process: QProcess, process_path: str) -> None:
        """Mark process as finished, update tracker, and emit finished signal."""
        exit_code = process.exitCode() if hasattr(process, "exitCode") else -1
        process_id = self._get_process_id(process)

        # For successful completion, force progress to 100% and emit update before cleanup
        if exit_code == 0:
            self.progress_tracker.force_progress_to_100(process_id)
            # Emit progress update to show 100% completion in UI
            self.update_progress.emit()

        # Guaranteed cleanup for this process
        self._cleanup_process_resources(process)

        # Mark as completed in progress tracker
        self.progress_tracker.complete_process(process_id, success=(exit_code == 0))
        # Emit process finished signal
        self.process_finished.emit(process, exit_code, process_path)

    def _cleanup_process_resources(self, process: QProcess) -> None:
        """Guaranteed cleanup of all resources associated with a process"""
        # Find process path before removing from list
        process_path = None
        for p, path in self.processes:
            if p == process:
                process_path = path
                break

        # Disconnect all signals for this process to prevent memory leaks
        if process in self.process_connections:
            try:
                for signal_name, handler in self.process_connections[process]:
                    if signal_name == "readyReadStandardOutput":
                        process.readyReadStandardOutput.disconnect(handler)
                    elif signal_name == "errorOccurred":
                        process.errorOccurred.disconnect(handler)
                    elif signal_name == "finished":
                        process.finished.disconnect(handler)
            except Exception as e:
                self.logger.warning(f"Error disconnecting signals: {e}")
            finally:
                del self.process_connections[process]

        # Remove from tracking list
        self.processes = [(p, path) for (p, path) in self.processes if p != process]

        # Adjust buffer sizes after removing process
        self._adjust_buffer_sizes()

        # Clean up logs and outputs (deques automatically handle memory)
        if process in self.process_logs:
            self.process_logs.pop(process)  # Deque is already size-limited

        if process in self.process_outputs:
            self.process_outputs.pop(process)  # Deque is already size-limited

        # Remove from codec mapping
        if process_path and process_path in self.codec_map:
            del self.codec_map[process_path]

        # Remove process ID mapping
        if process in self.process_ids:
            del self.process_ids[process]

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
        self.process_ids.clear()
        self.process_connections.clear()

    def get_available_vram(self) -> int:
        """Get available GPU VRAM in MB. Returns 0 if unable to detect."""
        return 0  # Simplified - VRAM monitoring disabled

    def can_start_gpu_encode(self) -> bool:
        """Check if there's enough VRAM to start a new GPU encode."""
        return True  # Always allow GPU encode - no VRAM monitoring

    def set_process_priority(self, process: QProcess, priority: str) -> None:
        """Set process priority. Priority can be 'high', 'normal', or 'low'."""
        try:
            if os.name == "nt":  # Windows
                priority_classes = {
                    "high": subprocess.HIGH_PRIORITY_CLASS,
                    "normal": subprocess.NORMAL_PRIORITY_CLASS,
                    "low": subprocess.IDLE_PRIORITY_CLASS,
                }
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(
                    0x0200, False, process.processId()
                )
                if handle:
                    ctypes.windll.kernel32.SetPriorityClass(
                        handle,
                        priority_classes.get(
                            priority, subprocess.NORMAL_PRIORITY_CLASS
                        ),
                    )
                    ctypes.windll.kernel32.CloseHandle(handle)
            else:  # Linux/Unix
                nice_values = {"high": -10, "normal": 0, "low": 10}
                os.nice(nice_values.get(priority, 0))
        except Exception as e:
            self.logger.warning(f"Failed to set process priority: {e}")
