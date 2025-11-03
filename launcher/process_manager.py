"""Process management for launcher system.

This module handles subprocess and worker thread lifecycle management,
extracted from the original launcher_manager.py for better separation of concerns.
"""

from __future__ import annotations

# Standard library imports
import subprocess
import time
import uuid

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

    def __init__(self) -> None:
        """Initialize the process manager."""
        super().__init__()

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
        """
        try:
            # Start the process
            process = subprocess.Popen(
                command,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=working_dir,
                start_new_session=True,
            )

            # Generate unique process key
            process_key = self._generate_process_key(launcher_id, process.pid)

            # Track the process
            process_info = ProcessInfo(
                process=process,
                launcher_id=launcher_id,
                launcher_name=launcher_name,
                command=" ".join(command),
                timestamp=time.time(),
            )

            with QMutexLocker(self._process_lock):
                self._active_processes[process_key] = process_info

            self.logger.info(
                f"Started subprocess for launcher '{launcher_name}' (PID: {process.pid})",
            )

            # Emit signal
            self.process_started.emit(launcher_id, " ".join(command))

            return process_key

        except Exception as e:
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
        try:
            # Create worker
            worker = LauncherWorker(launcher_id, command, working_dir)

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
        with QMutexLocker(self._process_lock):
            if worker_key in self._active_workers:
                worker = self._active_workers[worker_key]

                # Disconnect signals to prevent warnings
                try:
                    worker.command_started.disconnect()
                    worker.command_finished.disconnect()
                    worker.command_error.disconnect()
                except (RuntimeError, TypeError):
                    pass  # Already disconnected

                # Ensure cleanup happens even if emit fails
                try:
                    del self._active_workers[worker_key]
                    self.worker_removed.emit(worker_key)
                except Exception as e:
                    # Log but don't propagate - periodic cleanup will handle it
                    self.logger.warning(
                        f"Error during worker cleanup for {worker_key}: {e}"
                    )

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

    def terminate_process(self, process_key: str, force: bool = False) -> bool:
        """Terminate a specific process.

        Args:
            process_key: Key of the process to terminate
            force: If True, force kill the process

        Returns:
            True if process was terminated, False otherwise
        """
        # Check if it's a subprocess
        with QMutexLocker(self._process_lock):
            if process_key in self._active_processes:
                process_info = self._active_processes[process_key]
                try:
                    if force:
                        process_info.process.kill()
                    else:
                        process_info.process.terminate()

                    # Wait briefly for termination
                    try:
                        process_info.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if not force:
                            # Try force kill as fallback
                            process_info.process.kill()
                            process_info.process.wait(timeout=2)

                    # Remove from tracking
                    del self._active_processes[process_key]
                    self.logger.info(f"Terminated process {process_key}")
                    return True

                except Exception as e:
                    self.logger.error(f"Failed to terminate process {process_key}: {e}")
                    return False

            # Check if it's a worker thread
            elif process_key in self._active_workers:
                worker = self._active_workers[process_key]
                try:
                    worker.request_stop()
                    if not worker.wait(5000):  # Wait 5 seconds
                        self.logger.warning(
                            f"Worker {process_key} did not stop gracefully"
                        )

                    # Disconnect signals to prevent warnings
                    try:
                        worker.command_started.disconnect()
                        worker.command_finished.disconnect()
                        worker.command_error.disconnect()
                    except (RuntimeError, TypeError):
                        # Signals may already be disconnected
                        pass

                    del self._active_workers[process_key]
                    self.worker_removed.emit(process_key)
                    return True
                except Exception as e:
                    self.logger.error(f"Failed to stop worker {process_key}: {e}")
                    return False

        self.logger.warning(f"Process/worker {process_key} not found")
        return False

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
                            worker.command_started.disconnect()
                            worker.command_finished.disconnect()
                            worker.command_error.disconnect()
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

    def stop_all_workers(self) -> None:
        """Stop all active workers and processes gracefully."""
        self._shutting_down = True

        # Stop timers
        self._cleanup_timer.stop()
        self._cleanup_retry_timer.stop()

        # Get snapshot of active processes and workers
        with QMutexLocker(self._process_lock):
            processes = list(self._active_processes.keys())
            workers_snapshot = dict(self._active_workers)

        # Terminate all processes
        for process_key in processes:
            self.terminate_process(process_key, force=False)

        # Stop all workers with signal disconnection
        for worker_key, worker in workers_snapshot.items():
            try:
                worker.request_stop()
                worker.wait(5000)  # Wait 5 seconds

                # Disconnect signals to prevent warnings
                try:
                    worker.command_started.disconnect()
                    worker.command_finished.disconnect()
                    worker.command_error.disconnect()
                except (RuntimeError, TypeError):
                    # Signals may already be disconnected
                    pass

            except Exception as e:
                self.logger.error(f"Error stopping worker {worker_key}: {e}")

        # Clear all tracking
        with QMutexLocker(self._process_lock):
            self._active_workers.clear()

        self.logger.info("All workers and processes stopped")

    def shutdown(self) -> None:
        """Shutdown the process manager and clean up resources."""
        self.stop_all_workers()
