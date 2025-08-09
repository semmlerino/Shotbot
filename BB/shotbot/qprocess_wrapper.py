"""QProcess wrapper architecture for command execution with enhanced signal management.

This module provides a production-ready QProcess wrapper that replaces subprocess
with Qt's native process management, offering superior integration with the Qt event loop,
proper signal handling, and resource cleanup.
"""

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, TypedDict, Union

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    Signal,
)

# Set up logger for this module
logger = logging.getLogger(__name__)


# Type definitions using TypedDict for structured data
class ProcessConfig(TypedDict, total=False):
    """Type-safe configuration for process execution."""

    command: str
    arguments: List[str]
    working_directory: Optional[str]
    environment: Optional[Dict[str, str]]
    timeout_ms: Optional[int]
    merge_output: bool
    detached: bool
    forward_signals: bool


class ProcessOutput(TypedDict):
    """Structured output from process execution."""

    stdout: str
    stderr: str
    exit_code: int
    exit_status: str
    duration_ms: float
    timed_out: bool


# Protocol for process observers
class ProcessObserver(Protocol):
    """Protocol for objects that observe process execution."""

    def on_started(self, process_id: str) -> None:
        """Called when process starts."""
        ...

    def on_output(self, process_id: str, output: str, is_error: bool) -> None:
        """Called when process produces output."""
        ...

    def on_finished(
        self, process_id: str, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        """Called when process finishes."""
        ...

    def on_error(self, process_id: str, error: QProcess.ProcessError) -> None:
        """Called when process encounters an error."""
        ...


@dataclass
class ProcessInfo:
    """Information about a running or completed process."""

    process_id: str
    command: str
    arguments: List[str]
    working_directory: Optional[str]
    start_time: float
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    exit_status: Optional[QProcess.ExitStatus] = None
    stdout_lines: List[str] = field(default_factory=list)
    stderr_lines: List[str] = field(default_factory=list)
    error: Optional[QProcess.ProcessError] = None
    timed_out: bool = False


class ProcessState(enum.Enum):
    """Enhanced process state enumeration."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    FINISHING = "finishing"
    FINISHED = "finished"
    CRASHED = "crashed"
    TIMED_OUT = "timed_out"
    ERROR = "error"


class QProcessWrapper(QObject):
    """Production-ready QProcess wrapper with enhanced signal management.

    This wrapper provides:
    - Proper signal-based process management
    - Automatic resource cleanup
    - Timeout handling with graceful termination
    - Structured output capture and parsing
    - Observer pattern for extensibility
    - Thread-safe operation within Qt event loop

    Example:
        >>> wrapper = QProcessWrapper()
        >>> wrapper.output_received.connect(lambda text, is_err: print(text))
        >>> wrapper.finished.connect(lambda code, status: print(f"Finished: {code}"))
        >>> config = ProcessConfig(
        ...     command="ls", arguments=["-la", "/tmp"], timeout_ms=5000
        ... )
        >>> wrapper.start_process(config)
    """

    # Signals
    started = Signal(str)  # process_id
    output_received = Signal(str, bool)  # text, is_error
    error_occurred = Signal(str, str)  # process_id, error_message
    finished = Signal(str, int, QProcess.ExitStatus)  # process_id, exit_code, status
    state_changed = Signal(str, ProcessState)  # process_id, new_state
    timeout_warning = Signal(str, int)  # process_id, remaining_ms

    def __init__(
        self,
        process_id: Optional[str] = None,
        auto_cleanup: bool = True,
        parent: Optional[QObject] = None,
    ):
        """Initialize QProcess wrapper.

        Args:
            process_id: Unique identifier for this process
            auto_cleanup: Automatically cleanup resources on deletion
            parent: Parent QObject for proper Qt hierarchy
        """
        super().__init__(parent)

        self.process_id = process_id or f"process_{id(self)}"
        self.auto_cleanup = auto_cleanup
        self._process: Optional[QProcess] = None
        self._info: Optional[ProcessInfo] = None
        self._state = ProcessState.NOT_STARTED
        self._observers: List[ProcessObserver] = []
        self._timeout_timer: Optional[QTimer] = None
        self._warning_timer: Optional[QTimer] = None
        self._config: Optional[ProcessConfig] = None

        # Output buffers
        self._stdout_buffer = QByteArray()
        self._stderr_buffer = QByteArray()

    def add_observer(self, observer: ProcessObserver) -> None:
        """Add an observer for process events.

        Args:
            observer: Object implementing ProcessObserver protocol
        """
        if observer not in self._observers:
            self._observers.append(observer)

    def remove_observer(self, observer: ProcessObserver) -> None:
        """Remove an observer.

        Args:
            observer: Observer to remove
        """
        if observer in self._observers:
            self._observers.remove(observer)

    def start_process(self, config: ProcessConfig) -> bool:
        """Start a process with the given configuration.

        Args:
            config: Process configuration

        Returns:
            True if process started successfully, False otherwise
        """
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            logger.warning(f"Process {self.process_id} is already running")
            return False

        self._config = config
        self._setup_process()

        # Parse command and arguments
        command = config["command"]
        arguments = config.get("arguments", [])

        # Set working directory if specified
        if working_dir := config.get("working_directory"):
            self._process.setWorkingDirectory(working_dir)

        # Set environment if specified
        if env_vars := config.get("environment"):
            env = QProcessEnvironment.systemEnvironment()
            for key, value in env_vars.items():
                env.insert(key, value)
            self._process.setProcessEnvironment(env)

        # Setup timeout if specified
        if timeout_ms := config.get("timeout_ms"):
            self._setup_timeout(timeout_ms)

        # Initialize process info
        self._info = ProcessInfo(
            process_id=self.process_id,
            command=command,
            arguments=arguments,
            working_directory=config.get("working_directory"),
            start_time=time.time(),
        )

        # Start the process
        self._set_state(ProcessState.STARTING)

        if config.get("detached", False):
            # Start detached process
            success = self._process.startDetached(command, arguments)
            if success:
                self._set_state(ProcessState.RUNNING)
                self._notify_started()
            else:
                self._set_state(ProcessState.ERROR)
            return success
        else:
            # Start attached process
            self._process.start(command, arguments)

            # Wait for process to start
            if self._process.waitForStarted(1000):
                self._set_state(ProcessState.RUNNING)
                self._notify_started()
                return True
            else:
                error = self._process.error()
                self._handle_error(error)
                return False

    def _setup_process(self) -> None:
        """Setup QProcess instance and connect signals."""
        if self._process:
            self._cleanup_process()

        self._process = QProcess(self)

        # Connect signals
        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._on_stdout_ready)
        self._process.readyReadStandardError.connect(self._on_stderr_ready)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error_occurred)
        self._process.stateChanged.connect(self._on_state_changed)

        # Setup channel mode
        if self._config and self._config.get("merge_output", False):
            self._process.setProcessChannelMode(
                QProcess.ProcessChannelMode.MergedChannels
            )

    def _setup_timeout(self, timeout_ms: int) -> None:
        """Setup timeout handling for the process.

        Args:
            timeout_ms: Timeout in milliseconds
        """
        # Main timeout timer
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(timeout_ms)

        # Warning timer (emit warning at 90% of timeout)
        warning_ms = int(timeout_ms * 0.9)
        self._warning_timer = QTimer(self)
        self._warning_timer.setSingleShot(True)
        self._warning_timer.timeout.connect(
            lambda: self.timeout_warning.emit(self.process_id, timeout_ms - warning_ms)
        )
        self._warning_timer.start(warning_ms)

    def _on_started(self) -> None:
        """Handle process started event."""
        logger.debug(f"Process {self.process_id} started")
        self.started.emit(self.process_id)

    def _on_stdout_ready(self) -> None:
        """Handle stdout data available."""
        if not self._process:
            return

        data = self._process.readAllStandardOutput()
        text = data.data().decode("utf-8", errors="replace")

        if self._info:
            self._info.stdout_lines.extend(text.splitlines())

        self.output_received.emit(text, False)
        self._notify_output(text, False)

    def _on_stderr_ready(self) -> None:
        """Handle stderr data available."""
        if not self._process:
            return

        data = self._process.readAllStandardError()
        text = data.data().decode("utf-8", errors="replace")

        if self._info:
            self._info.stderr_lines.extend(text.splitlines())

        self.output_received.emit(text, True)
        self._notify_output(text, True)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """Handle process finished event.

        Args:
            exit_code: Process exit code
            exit_status: Process exit status
        """
        logger.debug(
            f"Process {self.process_id} finished with code {exit_code}, status {exit_status}"
        )

        # Cancel timeout timers
        if self._timeout_timer:
            self._timeout_timer.stop()
            self._timeout_timer = None
        if self._warning_timer:
            self._warning_timer.stop()
            self._warning_timer = None

        # Update process info
        if self._info:
            self._info.end_time = time.time()
            self._info.exit_code = exit_code
            self._info.exit_status = exit_status

        # Update state
        if exit_status == QProcess.ExitStatus.CrashExit:
            self._set_state(ProcessState.CRASHED)
        else:
            self._set_state(ProcessState.FINISHED)

        # Emit signal
        self.finished.emit(self.process_id, exit_code, exit_status)
        self._notify_finished(exit_code, exit_status)

    def _on_error_occurred(self, error: QProcess.ProcessError) -> None:
        """Handle process error.

        Args:
            error: Process error type
        """
        self._handle_error(error)

    def _handle_error(self, error: QProcess.ProcessError) -> None:
        """Handle process error with appropriate logging and signaling.

        Args:
            error: Process error type
        """
        error_messages = {
            QProcess.ProcessError.FailedToStart: "Failed to start process",
            QProcess.ProcessError.Crashed: "Process crashed",
            QProcess.ProcessError.Timedout: "Process operation timed out",
            QProcess.ProcessError.WriteError: "Error writing to process",
            QProcess.ProcessError.ReadError: "Error reading from process",
            QProcess.ProcessError.UnknownError: "Unknown process error",
        }

        error_msg = error_messages.get(error, f"Process error: {error}")
        logger.error(f"Process {self.process_id}: {error_msg}")

        if self._info:
            self._info.error = error

        self._set_state(ProcessState.ERROR)
        self.error_occurred.emit(self.process_id, error_msg)
        self._notify_error(error)

    def _on_state_changed(self, new_state: QProcess.ProcessState) -> None:
        """Handle QProcess state change.

        Args:
            new_state: New QProcess state
        """
        # Map QProcess state to our ProcessState
        state_map = {
            QProcess.ProcessState.NotRunning: ProcessState.NOT_STARTED,
            QProcess.ProcessState.Starting: ProcessState.STARTING,
            QProcess.ProcessState.Running: ProcessState.RUNNING,
        }

        if mapped_state := state_map.get(new_state):
            if mapped_state != self._state:
                logger.debug(
                    f"Process {self.process_id} state: {self._state} -> {mapped_state}"
                )

    def _on_timeout(self) -> None:
        """Handle process timeout."""
        logger.warning(f"Process {self.process_id} timed out")

        if self._info:
            self._info.timed_out = True

        self._set_state(ProcessState.TIMED_OUT)

        # Try graceful termination first
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()

            # Give it 2 seconds to terminate gracefully
            if not self._process.waitForFinished(2000):
                # Force kill if necessary
                logger.warning(f"Force killing process {self.process_id}")
                self._process.kill()
                self._process.waitForFinished(1000)

    def _set_state(self, state: ProcessState) -> None:
        """Set process state and emit signal if changed.

        Args:
            state: New process state
        """
        if state != self._state:
            old_state = self._state
            self._state = state
            logger.debug(f"Process {self.process_id}: {old_state} -> {state}")
            self.state_changed.emit(self.process_id, state)

    def _notify_started(self) -> None:
        """Notify observers that process started."""
        for observer in self._observers:
            try:
                observer.on_started(self.process_id)
            except Exception as e:
                logger.error(f"Observer error in on_started: {e}")

    def _notify_output(self, output: str, is_error: bool) -> None:
        """Notify observers of process output.

        Args:
            output: Output text
            is_error: Whether this is error output
        """
        for observer in self._observers:
            try:
                observer.on_output(self.process_id, output, is_error)
            except Exception as e:
                logger.error(f"Observer error in on_output: {e}")

    def _notify_finished(
        self, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        """Notify observers that process finished.

        Args:
            exit_code: Process exit code
            exit_status: Process exit status
        """
        for observer in self._observers:
            try:
                observer.on_finished(self.process_id, exit_code, exit_status)
            except Exception as e:
                logger.error(f"Observer error in on_finished: {e}")

    def _notify_error(self, error: QProcess.ProcessError) -> None:
        """Notify observers of process error.

        Args:
            error: Process error type
        """
        for observer in self._observers:
            try:
                observer.on_error(self.process_id, error)
            except Exception as e:
                logger.error(f"Observer error in on_error: {e}")

    def terminate(self, timeout_ms: int = 5000) -> bool:
        """Gracefully terminate the process.

        Args:
            timeout_ms: Maximum time to wait for termination

        Returns:
            True if process terminated successfully
        """
        if not self._process:
            return True

        if self._process.state() == QProcess.ProcessState.NotRunning:
            return True

        logger.info(f"Terminating process {self.process_id}")
        self._process.terminate()

        if self._process.waitForFinished(timeout_ms):
            return True

        # Force kill if graceful termination failed
        logger.warning(f"Force killing process {self.process_id}")
        self._process.kill()
        return self._process.waitForFinished(1000)

    def kill(self) -> None:
        """Forcefully kill the process."""
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            logger.warning(f"Killing process {self.process_id}")
            self._process.kill()

    def write_input(self, data: Union[str, bytes]) -> bool:
        """Write data to process stdin.

        Args:
            data: Data to write (string or bytes)

        Returns:
            True if write was successful
        """
        if not self._process or self._process.state() != QProcess.ProcessState.Running:
            logger.warning(f"Cannot write to process {self.process_id}: not running")
            return False

        if isinstance(data, str):
            data = data.encode("utf-8")

        bytes_written = self._process.write(data)
        return bytes_written == len(data)

    def get_output(self) -> ProcessOutput:
        """Get structured output from the process.

        Returns:
            ProcessOutput with stdout, stderr, and metadata
        """
        if not self._info:
            return ProcessOutput(
                stdout="",
                stderr="",
                exit_code=-1,
                exit_status="not_started",
                duration_ms=0.0,
                timed_out=False,
            )

        duration_ms = (
            (self._info.end_time - self._info.start_time) * 1000
            if self._info.end_time
            else (time.time() - self._info.start_time) * 1000
        )

        exit_status = "unknown"
        if self._info.exit_status is not None:
            exit_status = (
                "normal"
                if self._info.exit_status == QProcess.ExitStatus.NormalExit
                else "crash"
            )

        return ProcessOutput(
            stdout="\n".join(self._info.stdout_lines),
            stderr="\n".join(self._info.stderr_lines),
            exit_code=self._info.exit_code or -1,
            exit_status=exit_status,
            duration_ms=duration_ms,
            timed_out=self._info.timed_out,
        )

    def is_running(self) -> bool:
        """Check if process is currently running.

        Returns:
            True if process is running
        """
        return (
            self._process is not None
            and self._process.state() == QProcess.ProcessState.Running
        )

    def get_state(self) -> ProcessState:
        """Get current process state.

        Returns:
            Current ProcessState
        """
        return self._state

    def get_info(self) -> Optional[ProcessInfo]:
        """Get process information.

        Returns:
            ProcessInfo if available, None otherwise
        """
        return self._info

    def _cleanup_process(self) -> None:
        """Cleanup process resources."""
        if self._process:
            if self._process.state() != QProcess.ProcessState.NotRunning:
                self._process.terminate()
                if not self._process.waitForFinished(2000):
                    self._process.kill()
                    self._process.waitForFinished(1000)

            self._process.deleteLater()
            self._process = None

        if self._timeout_timer:
            self._timeout_timer.stop()
            self._timeout_timer.deleteLater()
            self._timeout_timer = None

        if self._warning_timer:
            self._warning_timer.stop()
            self._warning_timer.deleteLater()
            self._warning_timer = None

    def __del__(self):
        """Cleanup on deletion."""
        if self.auto_cleanup:
            self._cleanup_process()
