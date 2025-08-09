"""QProcess-based process management system for ShotBot.

This module provides a unified, thread-safe process management system using
Qt's QProcess for better integration with the Qt event loop and improved
resource management. It replaces subprocess calls with QProcess throughout
the application.

Key Features:
    - Thread-safe process pool with configurable limits
    - Non-blocking execution with signal/slot communication
    - Automatic cleanup and resource management
    - Support for interactive bash commands (ws command)
    - Terminal emulator integration
    - Process lifecycle tracking with detailed monitoring
    - Graceful shutdown with timeout handling

Architecture:
    - QProcessManager: Central manager for all processes
    - ProcessWorker: QThread worker for non-blocking execution
    - ProcessInfo: Metadata tracking for each process
    - TerminalLauncher: Specialized terminal process handling
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QThread,
    QTimer,
    Signal,
    Slot,
)

logger = logging.getLogger(__name__)


class ProcessState(Enum):
    """Process lifecycle states."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    TERMINATED = "terminated"
    CRASHED = "crashed"


@dataclass
class ProcessConfig:
    """Configuration for process execution."""

    command: str
    arguments: List[str] = field(default_factory=list)
    working_directory: Optional[str] = None
    environment: Optional[Dict[str, str]] = None
    use_shell: bool = False
    interactive_bash: bool = False
    terminal: bool = False
    terminal_persist: bool = False
    timeout_ms: int = 30000  # 30 seconds default
    capture_output: bool = True
    merge_output: bool = False  # Merge stderr into stdout

    def to_shell_command(self) -> str:
        """Convert to shell command string."""
        if self.arguments:
            import shlex

            args = " ".join(shlex.quote(arg) for arg in self.arguments)
            return f"{self.command} {args}"
        return self.command


@dataclass
class ProcessInfo:
    """Metadata for a running process."""

    process_id: str
    config: ProcessConfig
    state: ProcessState
    pid: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    exit_status: Optional[QProcess.ExitStatus] = None
    error: Optional[str] = None
    output_buffer: List[str] = field(default_factory=list)
    error_buffer: List[str] = field(default_factory=list)

    @property
    def duration(self) -> Optional[float]:
        """Get process duration in seconds."""
        if self.start_time:
            end = self.end_time or time.time()
            return end - self.start_time
        return None

    @property
    def is_active(self) -> bool:
        """Check if process is still active."""
        return self.state in (
            ProcessState.PENDING,
            ProcessState.STARTING,
            ProcessState.RUNNING,
        )


class ProcessWorker(QThread):
    """Worker thread for QProcess execution.

    Executes QProcess in a separate thread to prevent blocking the main GUI thread.
    Handles all process lifecycle events and emits appropriate signals.
    """

    # Signals
    started = Signal(str)  # process_id
    output_ready = Signal(str, str)  # process_id, output_line
    error_ready = Signal(str, str)  # process_id, error_line
    finished = Signal(str, int, QProcess.ExitStatus)  # process_id, exit_code, status
    failed = Signal(str, str)  # process_id, error_message
    state_changed = Signal(str, ProcessState)  # process_id, new_state

    def __init__(
        self, process_id: str, config: ProcessConfig, parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.process_id = process_id
        self.config = config
        self._process: Optional[QProcess] = None
        self._should_stop = threading.Event()
        self._info = ProcessInfo(
            process_id=process_id, config=config, state=ProcessState.PENDING
        )

    def run(self):
        """Execute the process in this thread."""
        try:
            self._emit_state(ProcessState.STARTING)

            # Create QProcess
            self._process = QProcess()

            # Set up environment
            if self.config.environment:
                env = QProcessEnvironment.systemEnvironment()
                for key, value in self.config.environment.items():
                    env.insert(key, value)
                self._process.setProcessEnvironment(env)

            # Set working directory
            if self.config.working_directory:
                self._process.setWorkingDirectory(self.config.working_directory)

            # Connect signals for output handling
            if self.config.capture_output:
                self._process.readyReadStandardOutput.connect(self._handle_stdout)
                self._process.readyReadStandardError.connect(self._handle_stderr)

            # Connect lifecycle signals
            self._process.started.connect(self._on_started)
            self._process.finished.connect(self._on_finished)
            self._process.errorOccurred.connect(self._on_error)

            # Configure output channels
            if self.config.merge_output:
                self._process.setProcessChannelMode(QProcess.MergedChannels)
            elif not self.config.capture_output:
                # Redirect to null device for GUI apps
                self._process.setStandardOutputFile(QProcess.nullDevice())
                self._process.setStandardErrorFile(QProcess.nullDevice())

            # Build command
            if self.config.interactive_bash:
                # For interactive bash (ws command)
                program = "/bin/bash"
                arguments = ["-i", "-c", self.config.to_shell_command()]
            elif self.config.use_shell:
                # General shell execution
                program = "/bin/sh"
                arguments = ["-c", self.config.to_shell_command()]
            else:
                # Direct execution
                program = self.config.command
                arguments = self.config.arguments

            # Start the process
            self._info.start_time = time.time()
            self._process.start(program, arguments)

            # Wait for process to start or timeout
            if not self._process.waitForStarted(5000):  # 5 second startup timeout
                error = self._process.errorString()
                self._emit_error(f"Process failed to start: {error}")
                return

            # Monitor process with timeout
            start_time = time.time()
            while not self._should_stop.is_set():
                # Check timeout
                if self.config.timeout_ms > 0:
                    elapsed = (time.time() - start_time) * 1000
                    if elapsed > self.config.timeout_ms:
                        self._terminate_process("Timeout exceeded")
                        break

                # Check if process finished
                if self._process.state() == QProcess.NotRunning:
                    break

                # Process events and sleep briefly
                self._process.waitForFinished(100)  # Check every 100ms

            # Ensure we read any remaining output
            if self.config.capture_output:
                self._process.waitForReadyRead(100)
                self._handle_stdout()
                self._handle_stderr()

        except Exception as e:
            self._emit_error(f"Worker exception: {str(e)}")
        finally:
            self._cleanup()

    def stop(self):
        """Request the worker to stop."""
        self._should_stop.set()
        if self._process and self._process.state() != QProcess.NotRunning:
            self._terminate_process("Worker stop requested")

    def _terminate_process(self, reason: str):
        """Terminate the process gracefully."""
        if not self._process:
            return

        logger.info(f"Terminating process {self.process_id}: {reason}")

        # Try graceful termination first
        self._process.terminate()
        if self._process.waitForFinished(2000):  # 2 second grace period
            self._emit_state(ProcessState.TERMINATED)
        else:
            # Force kill if necessary
            logger.warning(f"Force killing process {self.process_id}")
            self._process.kill()
            self._process.waitForFinished(1000)
            self._emit_state(ProcessState.TERMINATED)

    @Slot()
    def _on_started(self):
        """Handle process started event."""
        if self._process:
            self._info.pid = self._process.processId()
            self._emit_state(ProcessState.RUNNING)
            self.started.emit(self.process_id)
            logger.debug(f"Process {self.process_id} started with PID {self._info.pid}")

    @Slot(int, QProcess.ExitStatus)
    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        """Handle process finished event."""
        self._info.end_time = time.time()
        self._info.exit_code = exit_code
        self._info.exit_status = exit_status

        if exit_status == QProcess.CrashExit:
            self._emit_state(ProcessState.CRASHED)
        elif exit_code == 0:
            self._emit_state(ProcessState.FINISHED)
        else:
            self._emit_state(ProcessState.FAILED)

        self.finished.emit(self.process_id, exit_code, exit_status)
        logger.debug(
            f"Process {self.process_id} finished with code {exit_code} "
            f"(status: {exit_status.name})"
        )

    @Slot(QProcess.ProcessError)
    def _on_error(self, error: QProcess.ProcessError):
        """Handle process error event."""
        error_string = self._process.errorString() if self._process else str(error)
        self._info.error = error_string
        self._emit_error(f"Process error: {error_string}")

    @Slot()
    def _handle_stdout(self):
        """Read and emit standard output."""
        if not self._process:
            return

        data = self._process.readAllStandardOutput()
        if data:
            text = data.data().decode("utf-8", errors="replace")
            for line in text.splitlines():
                if line:
                    self._info.output_buffer.append(line)
                    self.output_ready.emit(self.process_id, line)

    @Slot()
    def _handle_stderr(self):
        """Read and emit standard error."""
        if not self._process:
            return

        data = self._process.readAllStandardError()
        if data:
            text = data.data().decode("utf-8", errors="replace")
            for line in text.splitlines():
                if line:
                    self._info.error_buffer.append(line)
                    self.error_ready.emit(self.process_id, line)

    def _emit_state(self, state: ProcessState):
        """Update and emit state change."""
        self._info.state = state
        self.state_changed.emit(self.process_id, state)

    def _emit_error(self, error_message: str):
        """Emit error and update state."""
        logger.error(f"Process {self.process_id}: {error_message}")
        self._info.error = error_message
        self._emit_state(ProcessState.FAILED)
        self.failed.emit(self.process_id, error_message)

    def _cleanup(self):
        """Clean up resources."""
        if self._process:
            # Disconnect all signals to prevent memory leaks
            try:
                self._process.started.disconnect()
                self._process.finished.disconnect()
                self._process.errorOccurred.disconnect()
                if self.config.capture_output:
                    self._process.readyReadStandardOutput.disconnect()
                    self._process.readyReadStandardError.disconnect()
            except (RuntimeError, TypeError):
                pass  # Signals might already be disconnected

            # Ensure process is terminated
            if self._process.state() != QProcess.NotRunning:
                self._process.kill()
                self._process.waitForFinished(1000)

            self._process.deleteLater()
            self._process = None

    def get_info(self) -> ProcessInfo:
        """Get current process information."""
        return self._info


class TerminalLauncher(QObject):
    """Specialized launcher for terminal-based processes."""

    # Terminal emulator configurations
    TERMINAL_CONFIGS = [
        {
            "name": "gnome-terminal",
            "check": ["gnome-terminal", "--version"],
            "command": ["gnome-terminal", "--"],
            "args_prefix": ["bash", "-i", "-c"],
        },
        {
            "name": "konsole",
            "check": ["konsole", "--version"],
            "command": ["konsole", "-e"],
            "args_prefix": ["bash", "-i", "-c"],
        },
        {
            "name": "xterm",
            "check": ["xterm", "-version"],
            "command": ["xterm", "-e"],
            "args_prefix": ["bash", "-i", "-c"],
        },
        {
            "name": "xfce4-terminal",
            "check": ["xfce4-terminal", "--version"],
            "command": ["xfce4-terminal", "-e"],
            "args_prefix": ["bash", "-i", "-c"],
        },
    ]

    def __init__(self):
        super().__init__()
        self._available_terminals: List[Dict[str, Any]] = []
        self._detect_terminals()

    def _detect_terminals(self):
        """Detect available terminal emulators."""
        for config in self.TERMINAL_CONFIGS:
            try:
                # Test if terminal is available
                test_process = QProcess()
                test_process.start(config["check"][0], config["check"][1:])
                if test_process.waitForFinished(1000):
                    self._available_terminals.append(config)
                    logger.debug(f"Found terminal: {config['name']}")
            except Exception:
                continue

        if not self._available_terminals:
            logger.warning("No terminal emulators found")

    def launch_in_terminal(
        self,
        command: str,
        working_directory: Optional[str] = None,
        persist: bool = False,
    ) -> Optional[QProcess]:
        """Launch a command in a terminal window.

        Args:
            command: Command to execute
            working_directory: Optional working directory
            persist: Keep terminal open after command finishes

        Returns:
            QProcess instance if successful, None otherwise
        """
        if not self._available_terminals:
            logger.error("No terminal emulators available")
            return None

        # Add persistence suffix if requested
        if persist:
            command = f"{command}; echo 'Press Enter to close...'; read"

        # Try each available terminal
        for terminal_config in self._available_terminals:
            try:
                process = QProcess()

                if working_directory:
                    process.setWorkingDirectory(working_directory)

                # Build full command
                full_args = list(terminal_config["command"][1:])
                full_args.extend(terminal_config["args_prefix"])
                full_args.append(command)

                # Start process
                process.startDetached(terminal_config["command"][0], full_args)

                logger.info(f"Launched in {terminal_config['name']}: {command[:50]}...")
                return process

            except Exception as e:
                logger.debug(f"Failed to launch in {terminal_config['name']}: {e}")
                continue

        logger.error("Failed to launch in any terminal")
        return None


class QProcessManager(QObject):
    """Central manager for all QProcess instances.

    Provides a unified interface for process management with:
    - Thread-safe process pool
    - Automatic cleanup
    - Resource limits
    - Lifecycle tracking
    """

    # Signals
    process_started = Signal(str, ProcessInfo)  # process_id, info
    process_finished = Signal(str, ProcessInfo)  # process_id, info
    process_output = Signal(str, str)  # process_id, line
    process_error = Signal(str, str)  # process_id, line
    process_state_changed = Signal(str, ProcessState)  # process_id, state

    # Configuration
    MAX_CONCURRENT_PROCESSES = 100
    CLEANUP_INTERVAL_MS = 30000  # 30 seconds
    DEFAULT_TIMEOUT_MS = 30000  # 30 seconds

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # Thread-safe process tracking
        self._processes: Dict[str, ProcessInfo] = {}
        self._workers: Dict[str, ProcessWorker] = {}
        self._lock = threading.RLock()

        # Terminal launcher
        self._terminal_launcher = TerminalLauncher()

        # Cleanup timer
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)

        # Shutdown flag
        self._shutting_down = False

        logger.info("QProcessManager initialized")

    def execute(
        self,
        command: str,
        arguments: Optional[List[str]] = None,
        working_directory: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        interactive_bash: bool = False,
        terminal: bool = False,
        terminal_persist: bool = False,
        capture_output: bool = True,
        timeout_ms: Optional[int] = None,
        process_id: Optional[str] = None,
    ) -> Optional[str]:
        """Execute a process with the given configuration.

        Args:
            command: Command to execute
            arguments: Optional command arguments
            working_directory: Optional working directory
            environment: Optional environment variables
            interactive_bash: Use interactive bash shell
            terminal: Launch in terminal window
            terminal_persist: Keep terminal open after completion
            capture_output: Capture process output
            timeout_ms: Timeout in milliseconds
            process_id: Optional process ID (auto-generated if not provided)

        Returns:
            Process ID if successful, None otherwise
        """
        # Check limits
        with self._lock:
            if len(self._processes) >= self.MAX_CONCURRENT_PROCESSES:
                logger.error(f"Process limit reached ({self.MAX_CONCURRENT_PROCESSES})")
                return None

        # Generate process ID if not provided
        if not process_id:
            process_id = f"proc_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        # Create configuration
        config = ProcessConfig(
            command=command,
            arguments=arguments or [],
            working_directory=working_directory,
            environment=environment,
            use_shell=False,
            interactive_bash=interactive_bash,
            terminal=terminal,
            terminal_persist=terminal_persist,
            timeout_ms=timeout_ms or self.DEFAULT_TIMEOUT_MS,
            capture_output=capture_output and not terminal,
            merge_output=False,
        )

        # Handle terminal launch
        if terminal:
            return self._launch_terminal(process_id, config)

        # Create and start worker
        return self._launch_worker(process_id, config)

    def execute_shell(
        self,
        command: str,
        working_directory: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        capture_output: bool = True,
        timeout_ms: Optional[int] = None,
        process_id: Optional[str] = None,
    ) -> Optional[str]:
        """Execute a shell command.

        Args:
            command: Shell command to execute
            working_directory: Optional working directory
            environment: Optional environment variables
            capture_output: Capture process output
            timeout_ms: Timeout in milliseconds
            process_id: Optional process ID

        Returns:
            Process ID if successful, None otherwise
        """
        if not process_id:
            process_id = f"shell_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        config = ProcessConfig(
            command=command,
            working_directory=working_directory,
            environment=environment,
            use_shell=True,
            capture_output=capture_output,
            timeout_ms=timeout_ms or self.DEFAULT_TIMEOUT_MS,
        )

        return self._launch_worker(process_id, config)

    def execute_ws_command(
        self,
        workspace_path: str,
        command: str,
        terminal: bool = False,
        capture_output: bool = True,
        timeout_ms: Optional[int] = None,
        process_id: Optional[str] = None,
    ) -> Optional[str]:
        """Execute a command with workspace setup.

        Args:
            workspace_path: Workspace path for ws command
            command: Command to execute after workspace setup
            terminal: Launch in terminal window
            capture_output: Capture process output
            timeout_ms: Timeout in milliseconds
            process_id: Optional process ID

        Returns:
            Process ID if successful, None otherwise
        """
        # Build full command with ws
        full_command = f"ws {workspace_path} && {command}"

        return self.execute(
            command=full_command,
            interactive_bash=True,  # ws requires interactive bash
            terminal=terminal,
            capture_output=capture_output,
            timeout_ms=timeout_ms,
            process_id=process_id,
        )

    def terminate_process(self, process_id: str, force: bool = False) -> bool:
        """Terminate a process.

        Args:
            process_id: Process ID to terminate
            force: Force kill if True

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if process_id not in self._workers:
                logger.warning(f"Process {process_id} not found")
                return False

            worker = self._workers[process_id]

        # Stop the worker
        worker.stop()

        # Wait for graceful shutdown
        if not worker.wait(3000):  # 3 second timeout
            worker.terminate()
            worker.wait(1000)

        logger.info(f"Terminated process {process_id}")
        return True

    def get_process_info(self, process_id: str) -> Optional[ProcessInfo]:
        """Get information about a process.

        Args:
            process_id: Process ID

        Returns:
            ProcessInfo if found, None otherwise
        """
        with self._lock:
            return self._processes.get(process_id)

    def get_active_processes(self) -> List[ProcessInfo]:
        """Get list of active processes.

        Returns:
            List of ProcessInfo for active processes
        """
        with self._lock:
            return [info for info in self._processes.values() if info.is_active]

    def get_process_count(self) -> Tuple[int, int]:
        """Get process counts.

        Returns:
            Tuple of (active_count, total_count)
        """
        with self._lock:
            total = len(self._processes)
            active = sum(1 for info in self._processes.values() if info.is_active)
            return active, total

    def wait_for_process(
        self, process_id: str, timeout_ms: int = 30000
    ) -> Optional[ProcessInfo]:
        """Wait for a process to complete.

        Args:
            process_id: Process ID to wait for
            timeout_ms: Maximum wait time in milliseconds

        Returns:
            ProcessInfo when complete, None if timeout
        """
        start_time = time.time()

        while (time.time() - start_time) * 1000 < timeout_ms:
            with self._lock:
                info = self._processes.get(process_id)
                if info and not info.is_active:
                    return info

            # Sleep briefly before checking again
            self.thread().msleep(100)

        logger.warning(f"Timeout waiting for process {process_id}")
        return None

    def _launch_worker(self, process_id: str, config: ProcessConfig) -> str:
        """Launch a worker thread for process execution."""
        # Create worker
        worker = ProcessWorker(process_id, config)

        # Connect signals
        worker.started.connect(
            lambda pid: self._on_process_started(pid, worker.get_info())
        )
        worker.finished.connect(self._on_process_finished)
        worker.failed.connect(self._on_process_failed)
        worker.state_changed.connect(self._on_state_changed)

        if config.capture_output:
            worker.output_ready.connect(self.process_output.emit)
            worker.error_ready.connect(self.process_error.emit)

        # Store references
        with self._lock:
            self._processes[process_id] = worker.get_info()
            self._workers[process_id] = worker

        # Start worker
        worker.start()

        logger.debug(f"Started worker for process {process_id}")
        return process_id

    def _launch_terminal(self, process_id: str, config: ProcessConfig) -> Optional[str]:
        """Launch a process in a terminal window."""
        # Build command
        if config.interactive_bash:
            command = f"bash -i -c '{config.to_shell_command()}'"
        else:
            command = config.to_shell_command()

        # Launch in terminal
        process = self._terminal_launcher.launch_in_terminal(
            command=command,
            working_directory=config.working_directory,
            persist=config.terminal_persist,
        )

        if process:
            # Create info for tracking
            info = ProcessInfo(
                process_id=process_id,
                config=config,
                state=ProcessState.RUNNING,
                start_time=time.time(),
            )

            with self._lock:
                self._processes[process_id] = info

            self.process_started.emit(process_id, info)
            logger.info(f"Launched terminal process {process_id}")
            return process_id

        return None

    @Slot(str, ProcessInfo)
    def _on_process_started(self, process_id: str, info: ProcessInfo):
        """Handle process started event."""
        with self._lock:
            self._processes[process_id] = info
        self.process_started.emit(process_id, info)

    @Slot(str, int, QProcess.ExitStatus)
    def _on_process_finished(
        self, process_id: str, exit_code: int, exit_status: QProcess.ExitStatus
    ):
        """Handle process finished event."""
        with self._lock:
            if process_id in self._processes:
                info = self._processes[process_id]
                info.exit_code = exit_code
                info.exit_status = exit_status
                info.end_time = time.time()

                if exit_status == QProcess.CrashExit:
                    info.state = ProcessState.CRASHED
                elif exit_code == 0:
                    info.state = ProcessState.FINISHED
                else:
                    info.state = ProcessState.FAILED

                self.process_finished.emit(process_id, info)

        # Schedule cleanup
        QTimer.singleShot(5000, lambda: self._cleanup_worker(process_id))

    @Slot(str, str)
    def _on_process_failed(self, process_id: str, error: str):
        """Handle process failure."""
        with self._lock:
            if process_id in self._processes:
                info = self._processes[process_id]
                info.error = error
                info.state = ProcessState.FAILED
                info.end_time = time.time()
                self.process_finished.emit(process_id, info)

    @Slot(str, ProcessState)
    def _on_state_changed(self, process_id: str, state: ProcessState):
        """Handle process state change."""
        with self._lock:
            if process_id in self._processes:
                self._processes[process_id].state = state
        self.process_state_changed.emit(process_id, state)

    def _cleanup_worker(self, process_id: str):
        """Clean up a finished worker."""
        with self._lock:
            if process_id in self._workers:
                worker = self._workers[process_id]
                if worker.isFinished():
                    # Disconnect signals
                    try:
                        worker.started.disconnect()
                        worker.finished.disconnect()
                        worker.failed.disconnect()
                        worker.state_changed.disconnect()
                        worker.output_ready.disconnect()
                        worker.error_ready.disconnect()
                    except (RuntimeError, TypeError):
                        pass

                    # Clean up worker
                    worker.deleteLater()
                    del self._workers[process_id]

                    logger.debug(f"Cleaned up worker for process {process_id}")

    @Slot()
    def _periodic_cleanup(self):
        """Periodic cleanup of finished processes."""
        if self._shutting_down:
            return

        current_time = time.time()
        old_threshold = current_time - 3600  # 1 hour

        with self._lock:
            # Find old finished processes
            to_remove = []
            for process_id, info in self._processes.items():
                if not info.is_active and info.end_time:
                    if info.end_time < old_threshold:
                        to_remove.append(process_id)

            # Remove old entries
            for process_id in to_remove:
                del self._processes[process_id]
                logger.debug(f"Removed old process entry: {process_id}")

            # Clean up finished workers
            finished_workers = []
            for process_id, worker in self._workers.items():
                if worker.isFinished():
                    finished_workers.append(process_id)

            for process_id in finished_workers:
                self._cleanup_worker(process_id)

            # Log statistics
            active_count, total_count = self.get_process_count()
            if active_count > 0:
                logger.debug(
                    f"Process manager: {active_count} active, "
                    f"{total_count} total, {len(to_remove)} cleaned"
                )

    def shutdown(self):
        """Shutdown the process manager."""
        logger.info("Shutting down QProcessManager...")
        self._shutting_down = True

        # Stop cleanup timer
        self._cleanup_timer.stop()

        # Terminate all active processes
        with self._lock:
            active_workers = list(self._workers.keys())

        for process_id in active_workers:
            self.terminate_process(process_id)

        # Wait for workers to finish
        with self._lock:
            remaining = len(self._workers)

        if remaining > 0:
            logger.warning(f"Shutdown with {remaining} workers still active")

        logger.info("QProcessManager shutdown complete")
