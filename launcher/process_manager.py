"""Process management for launcher system.

This module handles subprocess and worker thread lifecycle management,
extracted from the original launcher_manager.py for better separation of concerns.
"""

from __future__ import annotations

# Standard library imports
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from typing import TextIO

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    QRecursiveMutex,
    Qt,
    QTimer,
    Signal,
)

# Local application imports
from config import ThreadingConfig
from launcher.models import ProcessInfo, ProcessInfoDict
from launcher.worker import LauncherWorker
from logging_mixin import LoggingMixin


@final
class LauncherProcessManager(LoggingMixin, QObject):
    """Manages launcher process lifecycle and worker threads."""

    # Qt signals
    process_started = Signal(str, str)  # launcher_id, command
    process_finished = Signal(str, bool, int)  # launcher_id, success, return_code
    process_error = Signal(str, str)  # launcher_id, error_message
    worker_created = Signal(str)  # worker_key
    worker_removed = Signal(str)  # worker_key

    # Cleanup configuration
    CLEANUP_INTERVAL_MS = 5000  # Check for finished processes every 5 seconds
    CLEANUP_RETRY_DELAY_MS = 2000  # Delay before retrying stuck cleanup
    PROCESS_STARTUP_TIMEOUT_MS = (
        ThreadingConfig.SUBPROCESS_TIMEOUT * 1000  # Convert seconds to ms
    )

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the process manager.

        Args:
            parent: Optional Qt parent object for proper lifecycle management
        """
        super().__init__(parent)

        # Thread-safe process tracking with detailed information
        self._active_processes: dict[str, ProcessInfo] = {}
        self._active_workers: dict[str, LauncherWorker] = {}  # Track worker threads
        # Use QRecursiveMutex for PySide6 compatibility
        self._process_lock = QRecursiveMutex()  # Qt recursive mutex for nested locking
        self._cleanup_lock = QMutex()  # Qt mutex for cleanup coordination
        self._cleanup_in_progress = False  # Track cleanup state with lock protection
        self._cleanup_scheduled = False  # Prevent cascading cleanup requests

        # Managed timer for cleanup retry (prevents cascading timers)
        self._cleanup_retry_timer = QTimer()
        _ = self._cleanup_retry_timer.timeout.connect(self._perform_cleanup_with_reset)
        self._cleanup_retry_timer.setSingleShot(True)

        # Periodic cleanup timer
        self._cleanup_timer = QTimer()
        _ = self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)

        # Shutdown flag for graceful cleanup
        self._shutting_down = False

        self.logger.info(
            f"LauncherProcessManager initialized with cleanup interval {self.CLEANUP_INTERVAL_MS}ms",
        )

    def execute_with_subprocess(
        self,
        launcher_id: str,
        launcher_name: str,
        command: list[str],
        working_dir: str | None = None,
    ) -> str | None:
        """Execute command directly as subprocess.

        Args:
            launcher_id: ID of the launcher
            launcher_name: Name of the launcher
            command: Command list to execute
            working_dir: Optional working directory

        Returns:
            Process key if successful, None otherwise

        Notes:
            Captures stderr to a log file for debugging launch failures.
            Log files are stored in ~/.shotbot/logs/launcher_{id}_{timestamp}.log
        """
        log_file: Path | None = None
        stderr_handle: TextIO | None = None

        try:
            # Create log file for stderr capture (helps debug launch failures)
            log_dir = Path.home() / ".shotbot" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"launcher_{launcher_id}_{int(time.time())}.log"

            # Open file for stderr capture - file stays open while process runs
            # The subprocess inherits the file descriptor and continues writing
            stderr_handle = log_file.open("w")

            # Start the process with stderr capture
            process = subprocess.Popen(
                command,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=stderr_handle,  # Capture stderr for debugging
                cwd=working_dir,
                start_new_session=True,
            )

            # Generate unique process key
            process_key = self._generate_process_key(launcher_id, process.pid)

            # Track the process (including log file path and handle for later cleanup)
            process_info = ProcessInfo(
                process=process,
                launcher_id=launcher_id,
                launcher_name=launcher_name,
                command=" ".join(command),
                timestamp=time.time(),
                log_file=log_file,
                stderr_handle=stderr_handle,  # Store handle to prevent GC and enable cleanup
            )

            with QMutexLocker(self._process_lock):
                self._active_processes[process_key] = process_info

            self.logger.info(
                f"Started subprocess for launcher '{launcher_name}' (PID: {process.pid})",
            )
            self.logger.debug(f"Subprocess stderr captured to: {log_file}")

            # Emit signal
            self.process_started.emit(launcher_id, " ".join(command))

            return process_key

        except Exception as e:
            # Close stderr handle if we opened it but failed to start process
            if stderr_handle is not None:
                try:
                    stderr_handle.close()
                except Exception:
                    pass
            self.logger.error(f"Failed to start subprocess: {e}")
            self.process_error.emit(launcher_id, str(e))
            return None

    def execute_with_worker(
        self,
        launcher_id: str,
        launcher_name: str,
        command: str,
        working_dir: str | None = None,
    ) -> bool:
        """Execute command using a worker thread.

        Args:
            launcher_id: ID of the launcher
            launcher_name: Name of the launcher
            command: Command to execute
            working_dir: Optional working directory

        Returns:
            True if worker started successfully, False otherwise
        """
        # Initialize worker_key before try block so it's always defined for cleanup
        worker_key: str | None = None
        try:
            # Create worker with proper Qt parent for ownership
            worker = LauncherWorker(launcher_id, command, working_dir, parent=self)

            # Generate unique worker key with UUID suffix (prevents race condition)
            # MUST be created BEFORE signal connections to avoid NameError in lambda
            worker_key = (
                f"{launcher_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            )

            # Connect worker signals with explicit connection types for thread safety
            # Type annotations for signal connections
            def on_started(lid: str, cmd: str) -> None:
                self.process_started.emit(lid, cmd)

            def on_error(lid: str, error: str) -> None:
                self.process_error.emit(lid, error)

            _ = worker.command_started.connect(
                on_started,
                Qt.ConnectionType.QueuedConnection,
            )

            # Closure captures immutable worker_key for immediate cleanup
            # Type annotations required for basedpyright
            def on_finished(lid: str, success: bool, rc: int) -> None:
                self._on_worker_finished(worker_key, lid, success, rc)

            _ = worker.command_finished.connect(
                on_finished,
                Qt.ConnectionType.QueuedConnection,
            )
            _ = worker.command_error.connect(
                on_error,
                Qt.ConnectionType.QueuedConnection,
            )

            # Add to tracking dictionary BEFORE starting to prevent race condition
            # where worker finishes before being tracked
            with QMutexLocker(self._process_lock):
                self._active_workers[worker_key] = worker

            # Now start the worker - it's already tracked
            worker.start()

            self.worker_created.emit(worker_key)
            self.logger.info(f"Started worker thread for launcher '{launcher_name}'")
            return True

        except Exception as e:
            # CRITICAL: Remove worker from tracking on failure to prevent memory leak
            # Worker was added at line 203 before start() was called
            # Only cleanup if worker_key was assigned (exception could occur before)
            if worker_key is not None:
                with QMutexLocker(self._process_lock):
                    _ = self._active_workers.pop(worker_key, None)
            self.logger.error(f"Failed to start worker thread: {e}")
            self.process_error.emit(launcher_id, str(e))
            return False

    def _on_worker_finished(
        self, worker_key: str, launcher_id: str, success: bool, return_code: int
    ) -> None:
        """Handle worker thread completion with immediate cleanup.

        Args:
            worker_key: Unique key for the worker thread
            launcher_id: ID of the launcher that finished
            success: Whether execution was successful
            return_code: Process return code
        """
        self.logger.info(
            f"Worker finished for launcher '{launcher_id}': success={success}",
        )

        # Clean up immediately (eliminates 0-5 second delay)
        # Store worker reference, remove from dict, THEN disconnect outside lock
        worker = None

        with QMutexLocker(self._process_lock):
            if worker_key in self._active_workers:
                worker = self._active_workers[worker_key]

                # Remove from tracking dict FIRST
                try:
                    del self._active_workers[worker_key]
                    self.worker_removed.emit(worker_key)
                except Exception as e:
                    # Log but don't propagate - periodic cleanup will handle it
                    self.logger.warning(
                        f"Error during worker cleanup for {worker_key}: {e}"
                    )

        # Disconnect signals OUTSIDE mutex (prevents deadlock if slot tries to acquire lock)
        if worker:
            try:
                _ = worker.command_started.disconnect()
                _ = worker.command_finished.disconnect()
                _ = worker.command_error.disconnect()
            except (RuntimeError, TypeError):
                pass  # Already disconnected

        # Emit completion signal
        self.process_finished.emit(launcher_id, success, return_code)

    def _generate_process_key(self, launcher_id: str, process_pid: int) -> str:
        """Generate unique key for process tracking.

        Args:
            launcher_id: ID of the launcher
            process_pid: Process ID

        Returns:
            Unique process key
        """
        timestamp = int(time.time() * 1000)  # Millisecond precision
        unique_suffix = str(uuid.uuid4())[:8]  # Short UUID suffix
        return f"{launcher_id}_{process_pid}_{timestamp}_{unique_suffix}"

    def get_active_processes_dict(self) -> dict[str, ProcessInfo]:
        """Get dictionary of active processes.

        Returns:
            Copy of the active processes dictionary for safe access
        """
        with QMutexLocker(self._process_lock):
            return dict(self._active_processes)

    def get_active_workers_dict(self) -> dict[str, LauncherWorker]:
        """Get dictionary of active workers.

        Returns:
            Copy of the active workers dictionary for safe access
        """
        with QMutexLocker(self._process_lock):
            return dict(self._active_workers)

    def get_active_process_count(self) -> int:
        """Get count of currently active processes.

        Returns:
            Number of active processes
        """
        # Thread-safe snapshot
        with QMutexLocker(self._process_lock):
            # Include both subprocess and worker counts
            return len(self._active_processes) + len(self._active_workers)

    def get_active_process_info(self) -> list[ProcessInfoDict]:
        """Get information about all active processes.

        Returns:
            List of process information dictionaries
        """
        info_list: list[ProcessInfoDict] = []

        # Get snapshot of processes
        with QMutexLocker(self._process_lock):
            processes_snapshot = list(self._active_processes.items())
            workers_snapshot = list(self._active_workers.items())

        # Add subprocess info
        for process_key, process_info in processes_snapshot:
            try:
                info_list.append(
                    {
                        "type": "subprocess",
                        "key": process_key,
                        "launcher_id": process_info.launcher_id,
                        "launcher_name": process_info.launcher_name,
                        "command": process_info.command,
                        "pid": process_info.process.pid,
                        "running": process_info.process.poll() is None,
                        "start_time": process_info.timestamp,
                    }
                )
            except Exception as e:
                self.logger.debug(f"Error getting process info for {process_key}: {e}")

        # Add worker info (normalize to match ProcessInfoDict structure)
        for worker_key, worker in workers_snapshot:
            try:
                info_list.append(
                    {
                        "type": "worker",
                        "key": worker_key,
                        "launcher_id": worker.launcher_id,
                        "launcher_name": getattr(worker, "launcher_name", "Unknown"),
                        "command": worker.command,
                        "pid": 0,  # Workers don't have PIDs, use 0 as placeholder
                        "running": worker.isRunning(),
                        "start_time": getattr(worker, "timestamp", 0.0),
                    }
                )
            except Exception as e:
                self.logger.debug(f"Error getting worker info for {worker_key}: {e}")

        return info_list

    # Non-blocking termination constants
    TERMINATION_POLL_INTERVAL_MS = 100  # Poll every 100ms
    TERMINATION_MAX_ATTEMPTS = 50  # 50 * 100ms = 5 seconds

    def _check_process_terminated(
        self,
        process: subprocess.Popen[bytes],
        process_key: str,
        force: bool,
        attempt: int = 0,
    ) -> None:
        """Non-blocking check if process terminated.

        Uses QTimer.singleShot polling instead of blocking wait() to keep UI responsive.
        Calls itself recursively via QTimer until process terminates or max attempts reached.

        Args:
            process: The subprocess to check
            process_key: Key identifying the process
            force: Whether force-kill was used
            attempt: Current attempt number (0-indexed)
        """
        # Guard against signal emission after object deletion
        if self._shutting_down:
            return

        # Check if process has terminated
        return_code = process.poll()
        if return_code is not None:
            self.logger.info(f"Process {process_key} terminated with code {return_code}")
            self.process_finished.emit(process_key, return_code == 0, return_code)
            return

        # Max attempts reached - force kill if not already forced
        if attempt >= self.TERMINATION_MAX_ATTEMPTS:
            if not force:
                process.kill()
                self.logger.warning(f"Force-killed process {process_key} after timeout")
                # Schedule one more check to get final status
                QTimer.singleShot(
                    self.TERMINATION_POLL_INTERVAL_MS,
                    lambda: self._finalize_killed_process(process, process_key),
                )
            else:
                # Already force-killed, report failure
                self.logger.warning(f"Process {process_key} kill timeout reached")
                self.process_finished.emit(process_key, False, -9)
            return

        # Schedule next check (non-blocking)
        QTimer.singleShot(
            self.TERMINATION_POLL_INTERVAL_MS,
            lambda: self._check_process_terminated(process, process_key, force, attempt + 1),
        )

    def _finalize_killed_process(
        self, process: subprocess.Popen[bytes], process_key: str
    ) -> None:
        """Check final status after force-kill.

        Args:
            process: The subprocess that was killed
            process_key: Key identifying the process
        """
        # Guard against signal emission after object deletion
        if self._shutting_down:
            return

        return_code = process.poll()
        if return_code is not None:
            self.process_finished.emit(process_key, False, return_code)
        else:
            # Still running after kill - give up
            self.logger.error(f"Process {process_key} still running after kill")
            self.process_finished.emit(process_key, False, -9)

    def terminate_process(self, process_key: str, force: bool = False) -> bool:
        """Terminate a specific process (non-blocking).

        Args:
            process_key: Key of the process to terminate
            force: If True, force kill the process

        Returns:
            True if termination was initiated, False if process not found.
            Actual termination result is signaled via process_finished signal.

        Note:
            This method is non-blocking. Instead of waiting for process termination,
            it initiates termination and returns immediately. The process_finished
            signal is emitted when termination completes.
        """
        # Get process/worker reference under lock, then release before operations
        process_info = None
        worker = None

        with QMutexLocker(self._process_lock):
            if process_key in self._active_processes:
                process_info = self._active_processes[process_key]
                # Remove from tracking immediately to prevent double-termination
                del self._active_processes[process_key]
            elif process_key in self._active_workers:
                worker = self._active_workers[process_key]
                # Remove from tracking immediately
                del self._active_workers[process_key]

        # Handle process termination (non-blocking)
        if process_info is not None:
            try:
                # Close stderr handle (subprocess has its own copy of the fd)
                if process_info.stderr_handle is not None:
                    try:
                        process_info.stderr_handle.close()
                    except Exception:
                        pass

                if force:
                    process_info.process.kill()
                else:
                    process_info.process.terminate()

                # Start non-blocking termination check instead of blocking wait()
                self._check_process_terminated(process_info.process, process_key, force)
                return True

            except Exception as e:
                self.logger.error(f"Failed to terminate process {process_key}: {e}")
                self.process_finished.emit(process_key, False, -1)
                return False

        # Handle worker termination (workers have their own async mechanism)
        if worker is not None:
            try:
                _ = worker.request_stop()
                # Start async worker check instead of blocking wait()
                self._check_worker_stopped(worker, process_key)
                return True
            except Exception as e:
                self.logger.error(f"Failed to stop worker {process_key}: {e}")
                return False

        self.logger.warning(f"Process/worker {process_key} not found")
        return False

    def _check_worker_stopped(
        self, worker: LauncherWorker, worker_key: str, attempt: int = 0
    ) -> None:
        """Non-blocking check if worker has stopped.

        Args:
            worker: The worker thread to check
            worker_key: Key identifying the worker
            attempt: Current attempt number
        """
        # Guard against signal emission after object deletion
        if self._shutting_down:
            return

        if not worker.isRunning():
            # Worker stopped - clean up signals
            try:
                _ = worker.command_started.disconnect()
                _ = worker.command_finished.disconnect()
                _ = worker.command_error.disconnect()
            except (RuntimeError, TypeError):
                # Signals may already be disconnected
                pass
            self.worker_removed.emit(worker_key)
            return

        if attempt >= self.TERMINATION_MAX_ATTEMPTS:
            self.logger.warning(f"Worker {worker_key} did not stop gracefully")
            # Clean up signals anyway
            try:
                _ = worker.command_started.disconnect()
                _ = worker.command_finished.disconnect()
                _ = worker.command_error.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.worker_removed.emit(worker_key)
            return

        # Schedule next check
        QTimer.singleShot(
            self.TERMINATION_POLL_INTERVAL_MS,
            lambda: self._check_worker_stopped(worker, worker_key, attempt + 1),
        )

    def _cleanup_finished_processes(self) -> None:
        """Clean up finished processes from tracking (thread-safe)."""
        if self._shutting_down:
            return

        finished_keys: list[str] = []

        with QMutexLocker(self._process_lock):
            # Create a snapshot to avoid iteration issues
            processes_snapshot = list(self._active_processes.items())

        # Check processes outside lock to prevent blocking
        for process_key, process_info in processes_snapshot:
            try:
                # Check if process has finished
                if process_info.process.poll() is not None:
                    finished_keys.append(process_key)
            except (OSError, AttributeError) as e:
                # Process may have been cleaned up already
                self.logger.debug(f"Error checking process {process_key}: {e}")
                finished_keys.append(process_key)

        # Remove finished processes with lock held
        if finished_keys:
            with QMutexLocker(self._process_lock):
                for key in finished_keys:
                    if key in self._active_processes:
                        process_info = self._active_processes[key]
                        self.logger.debug(
                            (
                                f"Cleaning up finished process: {process_info.launcher_name} "
                                f"(PID: {process_info.process.pid}, Key: {key})"
                            ),
                        )
                        # Close stderr handle to prevent fd leak
                        if process_info.stderr_handle is not None:
                            try:
                                process_info.stderr_handle.close()
                                self.logger.debug(f"Closed stderr handle for process {key}")
                            except Exception as e:
                                self.logger.debug(f"Error closing stderr handle: {e}")
                        del self._active_processes[key]
                self.logger.debug(f"Cleaned up {len(finished_keys)} finished processes")

    def _cleanup_finished_workers(self) -> None:
        """Clean up finished worker threads."""
        if self._shutting_down:
            return

        finished_keys: list[str] = []

        with QMutexLocker(self._process_lock):
            # Snapshot for safe iteration
            workers_snapshot = list(self._active_workers.items())

        # Check workers outside the lock
        for worker_key, worker in workers_snapshot:
            try:
                # Check worker state
                if not worker.isRunning():
                    finished_keys.append(worker_key)
                    self.logger.debug(f"Worker {worker_key} has finished")
            except Exception as e:
                self.logger.debug(f"Error checking worker {worker_key}: {e}")
                finished_keys.append(worker_key)

        # Clean up finished workers
        if finished_keys:
            with QMutexLocker(self._process_lock):
                for key in finished_keys:
                    if key in self._active_workers:
                        worker = self._active_workers[key]

                        # Disconnect signals to prevent warnings
                        try:
                            _ = worker.command_started.disconnect()
                            _ = worker.command_finished.disconnect()
                            _ = worker.command_error.disconnect()
                        except (RuntimeError, TypeError):
                            # Signals may already be disconnected
                            pass

                        self.logger.debug(f"Removing finished worker {key}")
                        del self._active_workers[key]
                        self.worker_removed.emit(key)

    def _periodic_cleanup(self) -> None:
        """Periodic cleanup of finished processes and old entries."""
        if self._shutting_down:
            return

        try:
            # Clean up processes and workers
            self._cleanup_finished_processes()
            self._cleanup_finished_workers()

        except Exception as e:
            self.logger.error(f"Error during periodic cleanup: {e}")

    def _perform_cleanup_with_reset(self) -> None:
        """Perform cleanup and reset the scheduled flag."""
        with QMutexLocker(self._cleanup_lock):
            self._cleanup_scheduled = False
        self._periodic_cleanup()

    # Shutdown configuration
    SHUTDOWN_TIMEOUT_MS = 15000  # 15 second total shutdown timeout
    MIN_WORKER_WAIT_MS = 100  # Minimum wait per worker to check status

    def stop_all_workers(self, timeout_ms: int | None = None) -> None:
        """Stop all active workers and processes gracefully with shared deadline.

        Args:
            timeout_ms: Total timeout in milliseconds for all workers/processes.
                       Defaults to SHUTDOWN_TIMEOUT_MS (15 seconds).

        Note:
            Uses a shared deadline so that stuck workers don't accumulate
            wait times. If deadline is reached, remaining workers are
            abandoned to allow app shutdown to proceed.
        """
        if timeout_ms is None:
            timeout_ms = self.SHUTDOWN_TIMEOUT_MS

        self._shutting_down = True
        deadline = time.monotonic() + (timeout_ms / 1000.0)

        # Stop timers
        self._cleanup_timer.stop()
        self._cleanup_retry_timer.stop()

        # Get snapshot of active processes and workers
        with QMutexLocker(self._process_lock):
            processes = list(self._active_processes.keys())
            workers_snapshot = dict(self._active_workers)

        # Request stop on ALL workers first (parallel initiation)
        for worker in workers_snapshot.values():
            try:
                _ = worker.request_stop()
            except Exception as e:
                self.logger.debug(f"Error requesting worker stop: {e}")

        # Terminate all processes (non-blocking - just initiates termination)
        for process_key in processes:
            _ = self.terminate_process(process_key, force=False)

        # Wait for workers with SHARED deadline (not per-worker timeout)
        for worker_key, worker in workers_snapshot.items():
            remaining_sec = deadline - time.monotonic()
            if remaining_sec <= 0:
                self.logger.warning(
                    "Shutdown timeout reached, skipping remaining workers"
                )
                break

            # Calculate wait time: remaining time, but at least MIN_WORKER_WAIT_MS
            remaining_ms = int(remaining_sec * 1000)
            wait_ms = max(remaining_ms, self.MIN_WORKER_WAIT_MS)

            try:
                if not worker.wait(wait_ms):
                    self.logger.warning(
                        f"Worker {worker_key} did not stop within timeout"
                    )

                # Disconnect signals to prevent warnings
                try:
                    _ = worker.command_started.disconnect()
                    _ = worker.command_finished.disconnect()
                    _ = worker.command_error.disconnect()
                except (RuntimeError, TypeError):
                    # Signals may already be disconnected
                    pass

            except Exception as e:
                self.logger.error(f"Error stopping worker {worker_key}: {e}")

        # Clear all tracking
        with QMutexLocker(self._process_lock):
            self._active_workers.clear()
            self._active_processes.clear()

        elapsed_ms = int((time.monotonic() - (deadline - timeout_ms / 1000.0)) * 1000)
        self.logger.info(f"All workers and processes stopped in {elapsed_ms}ms")

    def shutdown(self) -> None:
        """Shutdown the process manager and clean up resources."""
        self.stop_all_workers()
