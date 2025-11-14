"""Persistent Terminal Manager for ShotBot.

This module manages a single persistent terminal window that handles all commands,
eliminating the need to spawn new terminals for each command.

PRIMARY LAUNCHER: This is the production launcher system for Shotbot.
Provides FIFO-based communication with persistent terminal sessions.
"""

from __future__ import annotations

import contextlib

# Standard library imports
import errno
import os
import signal
import stat
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar, final

# Third-party imports
import psutil
from PySide6.QtCore import QObject, QThread, Signal

# Local application imports
from config import Config
from launch.process_verifier import ProcessVerifier
from logging_mixin import LoggingMixin


# Module-level constants
_TERMINAL_RESTART_DELAY_SECONDS = 0.5  # Delay before restarting terminal
_FIFO_READY_TIMEOUT_SECONDS = 2.0  # Timeout for FIFO readiness check
_DISPATCHER_HEALTH_CHECK_TIMEOUT_SECONDS = 3.0  # Timeout for dispatcher health checks
_DISPATCHER_STARTUP_TIMEOUT_SECONDS = 5.0  # Timeout for dispatcher startup/restart
_HEARTBEAT_SEND_TIMEOUT_SECONDS = 3.0  # Timeout for sending heartbeat pings
_WORKER_POLL_INTERVAL_SECONDS = 0.1  # Polling interval for worker threads
_CLEANUP_POLL_INTERVAL_SECONDS = 0.2  # Polling interval for cleanup operations


class TerminalOperationWorker(QThread):
    """Worker thread for running blocking terminal operations asynchronously.

    This worker runs blocking operations (health checks, terminal restart)
    in a background thread to prevent GUI freezes.
    """

    # Signals
    progress: Signal = Signal(str)  # Status message
    operation_finished: Signal = Signal(bool, str)  # success, message

    def __init__(
        self,
        manager: PersistentTerminalManager,
        operation: str,
        parent: QObject | None = None,
    ) -> None:
        """Initialize worker.

        Args:
            manager: The terminal manager instance
            operation: Operation name ('health_check' or 'send_command')
            parent: Optional parent QObject for proper Qt ownership
        """
        super().__init__(parent)
        self.manager: PersistentTerminalManager = manager
        self.operation: str = operation
        self.command: str = ""  # For send_command operation

    def run(self) -> None:  # type: ignore[override]
        """Execute the operation in background thread."""
        try:
            if self.operation == "health_check":
                self._run_health_check()
            elif self.operation == "send_command":
                self._run_send_command()
        except Exception as e:
            self.operation_finished.emit(False, f"Operation failed: {e!s}")

    def _run_health_check(self) -> None:
        """Run health check operation.

        Thread-Safety Note:
            This method runs in a worker thread and calls manager methods that access
            shared state. This is SAFE because:
            - _is_dispatcher_healthy() and _ensure_dispatcher_healthy() use internal
              locks (_write_lock, _state_lock) to protect all shared state access
            - These methods are designed to be thread-safe and callable from workers
        """
        self.progress.emit("Checking terminal health...")

        if self.manager._is_dispatcher_healthy():  # pyright: ignore[reportPrivateUsage]
            self.operation_finished.emit(True, "Terminal healthy")
            return

        self.progress.emit("Terminal unhealthy, attempting recovery...")

        if self.manager._ensure_dispatcher_healthy():  # pyright: ignore[reportPrivateUsage]
            self.operation_finished.emit(True, "Terminal recovered")
        else:
            self.operation_finished.emit(False, "Terminal recovery failed")

    def _run_send_command(self) -> None:
        """Run send command operation.

        Thread-Safety Note:
            This method runs in a worker thread and calls manager methods that access
            shared state. This is SAFE because:
            - _ensure_dispatcher_healthy() and _send_command_direct() use internal
              locks (_write_lock, _state_lock) to protect all shared state access
            - These methods are designed to be thread-safe and callable from workers
        """
        self.progress.emit(f"Sending command: {self.command[:50]}...")

        # Ensure terminal is healthy first
        if not self.manager._ensure_dispatcher_healthy():  # pyright: ignore[reportPrivateUsage]
            self.operation_finished.emit(False, "Terminal not healthy")
            return

        # Emit executing signal (Phase 1)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.manager.command_executing.emit(timestamp)

        # Send command to FIFO
        if not self.manager._send_command_direct(self.command):  # pyright: ignore[reportPrivateUsage]
            self.operation_finished.emit(False, "Failed to send command")
            return

        # Command sent successfully - now verify process started (Phase 2)
        self.manager.logger.debug("Command sent, starting verification...")  # pyright: ignore[reportAttributeAccessIssue]

        # Wait for process to start (with timeout)
        success, message = self.manager._process_verifier.wait_for_process(  # pyright: ignore[reportPrivateUsage]
            self.command
        )

        if success:
            # Emit verified signal
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.manager.command_verified.emit(timestamp, message)
            self.operation_finished.emit(True, f"Verified: {message}")
        else:
            # Verification failed - emit error signal
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.manager.command_error.emit(timestamp, f"Verification failed: {message}")  # pyright: ignore[reportAttributeAccessIssue]
            self.operation_finished.emit(False, f"Verification failed: {message}")


@final
class PersistentTerminalManager(LoggingMixin, QObject):
    """Manages a single persistent terminal for all commands."""

    # Class-level tracking for test cleanup
    _test_instances: ClassVar[list[PersistentTerminalManager]] = []
    _test_instances_lock: ClassVar[threading.Lock] = threading.Lock()

    # Signals
    terminal_started = Signal(int)  # PID of terminal
    terminal_closed = Signal()
    command_sent = Signal(str)  # Command that was sent

    # Progress signals for non-blocking operations
    operation_started = Signal(str)  # operation_name
    operation_progress = Signal(str, str)  # operation_name, status_message
    operation_finished = Signal(str, bool, str)  # operation_name, success, message
    command_result = Signal(bool, str)  # success, error_message (empty if success)

    # New async execution lifecycle signals (Phase 1 & 2)
    command_queued = Signal(str, str)  # timestamp, command - emitted when queued
    command_executing = Signal(str)  # timestamp - emitted when execution starts
    command_verified = Signal(str, str)  # timestamp, message - emitted when verified (Phase 2)
    command_error = Signal(str, str)  # timestamp, error - emitted on verification failure (Phase 2)
    # Keep command_result for backward compatibility

    def __init__(
        self,
        fifo_path: str | None = None,
        dispatcher_path: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the persistent terminal manager.

        Args:
            fifo_path: Path to the FIFO for command communication
            dispatcher_path: Path to the terminal dispatcher script
            parent: Optional parent QObject for proper Qt ownership
        """
        super().__init__(parent)

        # Set up paths
        self.fifo_path = fifo_path or Config.FIFO_PATH
        self.heartbeat_path = Config.HEARTBEAT_PATH
        self.dispatcher_log_path = str(Path.home() / ".shotbot/logs/dispatcher_debug.log")

        # Find dispatcher script relative to this module
        if dispatcher_path:
            self.dispatcher_path = dispatcher_path
        else:
            module_dir = Path(__file__).parent
            self.dispatcher_path = str(module_dir / "terminal_dispatcher.sh")

        # Terminal state
        self.terminal_pid: int | None = None
        self.terminal_process: subprocess.Popen[bytes] | None = None
        self.dispatcher_pid: int | None = None  # Track dispatcher bash script PID
        self._dummy_writer_fd: int | None = None  # Keeps FIFO alive to prevent EOF
        self._fd_closed: bool = False  # Track if FD has been closed

        # Health monitoring
        self._last_heartbeat_time: float = 0.0
        self._heartbeat_timeout: float = Config.HEARTBEAT_TIMEOUT
        self._heartbeat_check_interval: float = Config.HEARTBEAT_CHECK_INTERVAL

        # Auto-recovery state
        self._restart_attempts: int = 0
        self._max_restart_attempts: int = Config.MAX_TERMINAL_RESTART_ATTEMPTS
        self._fallback_mode: bool = False  # Use fallback when persistent terminal fails

        # Thread safety: Lock for serializing FIFO writes
        # This prevents byte-level corruption when multiple threads
        # call send_command() concurrently
        self._write_lock = threading.Lock()
        # Protects all shared state accessed from worker threads:
        # terminal_pid, terminal_process, dispatcher_pid, _restart_attempts,
        # _fallback_mode, _last_heartbeat_time, _dummy_writer_fd, _fd_closed
        self._state_lock = threading.Lock()

        # Active workers for async operations (prevents garbage collection)
        self._active_workers: list[TerminalOperationWorker] = []
        self._workers_lock = threading.Lock()  # Thread-safe worker list access

        # Process verification for launched applications (Phase 2)
        self._process_verifier = ProcessVerifier(self.logger)

        # Ensure FIFO exists (but don't open dummy writer yet - no dispatcher running)
        if not self._ensure_fifo(open_dummy_writer=False):
            self.logger.warning(
                f"Failed to create FIFO at {self.fifo_path}, persistent terminal may not work properly"
            )

        self.logger.info(
            f"PersistentTerminalManager initialized with FIFO: {self.fifo_path}"
        )

        # Clean up old PID files on startup (Phase 2)
        ProcessVerifier.cleanup_old_pid_files(max_age_hours=24)

        # Track instance for test cleanup
        with self.__class__._test_instances_lock:
            self.__class__._test_instances.append(self)

    def _ensure_fifo(self, open_dummy_writer: bool = True) -> bool:
        """Ensure the FIFO exists for command communication.

        Args:
            open_dummy_writer: If True, open dummy writer FD to prevent EOF.
                               If False, only create FIFO without opening writer.
                               Set to False when dispatcher is not yet running.

        Returns:
            True if FIFO exists or was created successfully, False otherwise
        """
        if not Path(self.fifo_path).exists():
            try:
                # Remove any existing file first (in case it's not a FIFO)
                with contextlib.suppress(FileNotFoundError):
                    Path(self.fifo_path).unlink()

                os.mkfifo(self.fifo_path, 0o600)  # Only user can read/write
                self.logger.debug(f"Created FIFO at {self.fifo_path}")
            except OSError as e:
                self.logger.error(f"Could not create FIFO at {self.fifo_path}: {e}")
                return False

        # Verify it's actually a FIFO
        if not Path(self.fifo_path).exists():
            self.logger.error(
                f"FIFO does not exist after creation attempt: {self.fifo_path}"
            )
            return False

        # Check if path is a FIFO using cross-platform compatible method
        try:
            file_stat = Path(self.fifo_path).stat()
            if not stat.S_ISFIFO(file_stat.st_mode):
                self.logger.error(f"Path exists but is not a FIFO: {self.fifo_path}")
                return False
        except OSError as e:
            self.logger.error(f"Could not stat FIFO path {self.fifo_path}: {e}")
            return False

        # Open dummy writer to keep FIFO alive and prevent EOF
        # This prevents the bash reader from receiving EOF when command writers close
        # Only open if requested AND if not already open
        if open_dummy_writer:
            with self._state_lock:
                if self._dummy_writer_fd is None:
                    try:
                        self._dummy_writer_fd = os.open(
                            self.fifo_path, os.O_WRONLY | os.O_NONBLOCK
                        )
                        self._fd_closed = False  # Mark as open
                        self.logger.debug(
                            f"Opened dummy writer (FD {self._dummy_writer_fd}) to keep FIFO alive"
                        )
                    except OSError as e:
                        self.logger.error(f"Failed to open dummy writer: {e}")
                        # Log warning but don't fail - dispatcher might not be running yet
                        # Caller should open dummy writer after dispatcher is ready
                        self.logger.warning(
                            "Dummy writer could not be opened - dispatcher may not be running yet. "
                            "Call _open_dummy_writer() after dispatcher is ready."
                        )
                        return False

        return True

    def _open_dummy_writer(self) -> bool:
        """Open dummy writer FD to keep FIFO alive.

        This should be called AFTER the dispatcher (reader) has started,
        to avoid ENXIO errors from opening write-only FIFO with no reader.

        Returns:
            True if dummy writer opened successfully or already open, False on error
        """
        with self._state_lock:
            # Already open - nothing to do
            if self._dummy_writer_fd is not None:
                self.logger.debug(f"Dummy writer already open (FD {self._dummy_writer_fd})")
                return True

            # Verify FIFO exists
            if not Path(self.fifo_path).exists():
                self.logger.error(f"Cannot open dummy writer - FIFO doesn't exist: {self.fifo_path}")
                return False

            # Open dummy writer (requires reader to be present)
            try:
                self._dummy_writer_fd = os.open(
                    self.fifo_path, os.O_WRONLY | os.O_NONBLOCK
                )
                self._fd_closed = False  # Mark as open
                self.logger.debug(
                    f"Opened dummy writer (FD {self._dummy_writer_fd}) to keep FIFO alive"
                )
                return True
            except OSError as e:
                self.logger.error(f"Failed to open dummy writer: {e}")
                if e.errno == errno.ENXIO:
                    self.logger.error(
                        "ENXIO error: No reader available. "
                        "Ensure dispatcher is running before opening dummy writer."
                    )
                return False

    def _close_dummy_writer_fd(self) -> None:
        """Close dummy writer FD (idempotent).

        This method is safe to call multiple times.
        """
        with self._state_lock:
            if self._fd_closed or self._dummy_writer_fd is None:
                return

            try:
                os.close(self._dummy_writer_fd)
                self._fd_closed = True
                self.logger.debug(f"Closed dummy writer FD {self._dummy_writer_fd}")
            except OSError as e:
                if e.errno != errno.EBADF:  # Not already closed
                    self.logger.warning(f"Error closing dummy writer: {e}")
            finally:
                self._dummy_writer_fd = None

    def _is_dispatcher_running(self) -> bool:
        """Check if the terminal dispatcher is running and ready to read from FIFO.

        Uses heartbeat mechanism instead of open/close to avoid EOF race condition.
        This sends actual data (__HEARTBEAT__) which bash reads and responds to,
        eliminating the race where open/close could send EOF to blocked reads.

        Returns:
            True if dispatcher appears to be running and responsive, False otherwise
        """
        if not Path(self.fifo_path).exists():
            return False

        # Use longer timeout to avoid false negatives when bash is executing commands
        # This tests the full round-trip: write → bash reads → bash responds
        return self._send_heartbeat_ping(timeout=_HEARTBEAT_SEND_TIMEOUT_SECONDS)

    def _is_terminal_alive(self) -> bool:
        """Check if the terminal process is still running.

        Thread-Safe: Uses _state_lock to protect terminal_pid and terminal_process.
        """
        with self._state_lock:
            if self.terminal_pid is None:
                return False

            try:
                # Check if process exists (doesn't actually kill it)
                os.kill(self.terminal_pid, 0)
                return True
            except ProcessLookupError:
                self.logger.debug(f"Terminal process {self.terminal_pid} no longer exists")
                self.terminal_pid = None
                self.terminal_process = None
                return False
            except PermissionError:
                # Process exists but we can't access it
                return True

    def _find_dispatcher_pid(self) -> int | None:
        """Find the PID of the dispatcher bash script.

        Thread-Safe: Uses _state_lock to read terminal_pid.

        Returns:
            PID of dispatcher script if found, None otherwise
        """
        # Snapshot terminal_pid under lock
        with self._state_lock:
            terminal_pid = self.terminal_pid

        if terminal_pid is None:
            return None

        try:
            # Get the terminal process
            terminal_proc = psutil.Process(terminal_pid)

            # Get the dispatcher script basename for matching
            dispatcher_name = Path(self.dispatcher_path).name

            # Look for bash child process running our dispatcher script
            for child in terminal_proc.children(recursive=True):
                try:
                    # Check if this is a bash process
                    if "bash" not in child.name().lower():
                        continue

                    # Check if it's running our dispatcher script
                    # Match against the full path or just the basename
                    cmdline = child.cmdline()
                    if any(self.dispatcher_path in arg or dispatcher_name in arg for arg in cmdline):
                        self.logger.debug(
                            f"Found dispatcher process: PID {child.pid}, cmdline: {cmdline}"
                        )
                        return child.pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            self.logger.debug(
                f"No dispatcher script found under terminal PID {terminal_pid}"
            )
            return None

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.debug(f"Error finding dispatcher PID: {e}")
            return None

    def _is_dispatcher_alive(self) -> bool:
        """Check if the dispatcher bash script is running.

        Thread-Safe: Uses _state_lock to protect dispatcher_pid.

        Returns:
            True if dispatcher process is running, False otherwise
        """
        with self._state_lock:
            if self.dispatcher_pid is None:
                # Try to find it
                self.dispatcher_pid = self._find_dispatcher_pid()
                if self.dispatcher_pid is None:
                    return False

            dispatcher_pid = self.dispatcher_pid

        try:
            # Check if dispatcher process still exists
            proc = psutil.Process(dispatcher_pid)
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                return True
            self.logger.debug(
                f"Dispatcher process {dispatcher_pid} is not running or is zombie"
            )
            with self._state_lock:
                self.dispatcher_pid = None
            return False
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self.logger.debug(f"Dispatcher process {dispatcher_pid} no longer exists")
            with self._state_lock:
                self.dispatcher_pid = None
            return False

    def _check_heartbeat(self) -> bool:
        """Check if a recent heartbeat exists.

        Thread-Safe: Uses _state_lock to protect _last_heartbeat_time.

        Returns:
            True if recent heartbeat found, False otherwise
        """
        try:
            heartbeat_file = Path(self.heartbeat_path)
            if not heartbeat_file.exists():
                return False

            # Read heartbeat timestamp
            content = heartbeat_file.read_text().strip()
            if not content or content != "PONG":
                return False

            # Check file modification time
            mtime = heartbeat_file.stat().st_mtime
            age = time.time() - mtime

            if age < self._heartbeat_timeout:
                with self._state_lock:
                    self._last_heartbeat_time = mtime
                self.logger.debug(f"Heartbeat OK (age: {age:.1f}s)")
                return True
            self.logger.debug(f"Heartbeat stale (age: {age:.1f}s)")
            return False

        except Exception as e:
            self.logger.debug(f"Error checking heartbeat: {e}")
            return False

    def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
        """Send a heartbeat ping and wait for response.

        Args:
            timeout: Maximum time to wait for response (seconds)

        Returns:
            True if PONG received within timeout, False otherwise
        """
        try:
            # Remove old heartbeat file
            heartbeat_file = Path(self.heartbeat_path)
            if heartbeat_file.exists():
                heartbeat_file.unlink()

            # Send PING command
            if not self._send_command_direct("__HEARTBEAT__"):
                return False

            # Poll for PONG response
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if self._check_heartbeat():
                    return True
                time.sleep(_WORKER_POLL_INTERVAL_SECONDS)

            self.logger.debug(f"No heartbeat response after {timeout}s")
            return False

        except Exception as e:
            self.logger.debug(f"Error sending heartbeat ping: {e}")
            return False

    def _is_dispatcher_healthy(self) -> bool:
        """Comprehensive health check for dispatcher.

        Uses multiple checks:
        1. Dispatcher process exists and is running
        2. FIFO has a reader (existing check)
        3. Heartbeat response (if enabled)

        Thread-Safe:
            Can be called from worker threads. Uses internal locks to protect
            shared state access (_write_lock for FIFO operations).

        Returns:
            True if dispatcher appears healthy, False otherwise
        """
        # Check 1: Dispatcher process exists
        if not self._is_dispatcher_alive():
            self.logger.debug("Health check failed: Dispatcher process not running")
            return False

        # Check 2: FIFO has reader
        if not self._is_dispatcher_running():
            self.logger.debug("Health check failed: FIFO has no reader")
            return False

        # Check 3: Recent heartbeat (optional - only if we've received one before)
        # This prevents false negatives on first run
        with self._state_lock:
            last_heartbeat_time = self._last_heartbeat_time

        if last_heartbeat_time > 0:
            age = time.time() - last_heartbeat_time
            if age > self._heartbeat_timeout:
                self.logger.debug(
                    f"Health check failed: No recent heartbeat (last: {age:.1f}s ago)"
                )
                # Try sending a ping to verify
                if not self._send_heartbeat_ping():
                    return False

        self.logger.debug("Health check passed: Dispatcher is healthy")
        return True

    def _send_command_direct(self, command: str) -> bool:
        """Send command to FIFO without health checks (internal use only).

        This method sends a command directly to the FIFO without performing
        health checks or terminal existence validation. It should only be
        called from methods that have already validated terminal state.

        Args:
            command: Command string to send (newline will be appended)

        Returns:
            True if sent successfully, False otherwise

        Thread Safety:
            Thread-safe through _write_lock. Multiple threads can call
            this concurrently.

        Resource Management:
            - Opens file descriptor with O_WRONLY | O_NONBLOCK
            - Wraps fd in fdopen for automatic cleanup
            - Ensures fd is closed even if fdopen fails
            - No file descriptor leaks in any error path

        Error Handling:
            - ENXIO: No reader available (dispatcher not running)
            - EAGAIN: Write would block (buffer full)
            - Other OSError: Logged with full error details
        """
        if not Path(self.fifo_path).exists():
            self.logger.debug(f"FIFO does not exist: {self.fifo_path}")
            return False

        fd = None  # Track FD for cleanup in case of errors
        try:
            with self._write_lock:
                fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
                # Now wrap in fdopen (which takes ownership of fd)
                with os.fdopen(fd, "wb", buffering=0) as fifo:
                    fd = None  # fdopen took ownership, clear reference
                    _ = fifo.write(command.encode("utf-8"))
                    _ = fifo.write(b"\n")
            return True
        except OSError as e:
            # ✅ Clean up fd if fdopen() never took ownership
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass  # Already closed or invalid

            # Log specific error types for debugging
            if e.errno == errno.ENXIO:
                self.logger.debug("No reader on FIFO (ENXIO) - dispatcher may not be running")
            elif e.errno == errno.EAGAIN:
                self.logger.warning("FIFO write would block (buffer full?) - command may be delayed")
            else:
                self.logger.error(f"Failed to write to FIFO {self.fifo_path}: {e}")
            return False

    def _launch_terminal(self) -> bool:
        """Launch the persistent terminal with dispatcher script.

        Returns:
            True if terminal launched successfully, False otherwise

        Resource Management:
            - Creates subprocess.Popen for terminal emulator
            - Tracks process via self.terminal_process
            - On failure, process is NOT cleaned up (will terminate naturally)

        Error Handling:
            - FileNotFoundError: Terminal emulator not found (try next)
            - Other exceptions: Logged and continue to next emulator
        """
        if not Path(self.dispatcher_path).exists():
            self.logger.error(
                f"Dispatcher script not found: {self.dispatcher_path}. "
                f"Cannot launch persistent terminal without dispatcher."
            )
            return False

        # Try different terminal emulators
        # Note: Use -il (not -ilc) when executing a script file
        # -i = interactive, -l = login shell (loads .bash_profile for ws function)
        # -c = command string (only use for inline commands, not script files)
        terminal_commands = [
            # gnome-terminal with title
            [
                "gnome-terminal",
                "--title=ShotBot Terminal",
                "--",
                "bash",
                "-il",
                self.dispatcher_path,
                self.fifo_path,
            ],
            # konsole
            [
                "konsole",
                "--title",
                "ShotBot Terminal",
                "-e",
                "bash",
                "-il",
                self.dispatcher_path,
                self.fifo_path,
            ],
            # xterm
            [
                "xterm",
                "-title",
                "ShotBot Terminal",
                "-e",
                "bash",
                "-il",
                self.dispatcher_path,
                self.fifo_path,
            ],
            # fallback to any available terminal
            [
                "x-terminal-emulator",
                "-e",
                "bash",
                "-il",
                self.dispatcher_path,
                self.fifo_path,
            ],
        ]

        for cmd in terminal_commands:
            try:
                self.logger.debug(f"Trying to launch terminal with: {cmd[0]}")
                proc = subprocess.Popen(cmd, start_new_session=True)
                pid = proc.pid

                # Store under lock
                with self._state_lock:
                    self.terminal_process = proc
                    self.terminal_pid = pid

                # Give terminal time to start
                time.sleep(_TERMINAL_RESTART_DELAY_SECONDS)

                if self._is_terminal_alive():
                    self.logger.info(
                        f"Terminal emulator launched with PID: {pid}"
                    )

                    # Wait for dispatcher script to start
                    timeout = _DISPATCHER_STARTUP_TIMEOUT_SECONDS
                    poll_interval = _CLEANUP_POLL_INTERVAL_SECONDS
                    elapsed = 0.0

                    while elapsed < timeout:
                        found_pid = self._find_dispatcher_pid()
                        if found_pid is not None:
                            with self._state_lock:
                                self.dispatcher_pid = found_pid
                            self.logger.info(
                                f"Dispatcher script started with PID: {found_pid}"
                            )
                            break
                        time.sleep(poll_interval)
                        elapsed += poll_interval
                    else:
                        self.logger.warning(
                            "Dispatcher PID not found after terminal launch - may not have started yet"
                        )

                    self.terminal_started.emit(pid)
                    return True

            except FileNotFoundError:
                self.logger.debug(f"Terminal emulator not found: {cmd[0]}")
                continue
            except Exception as e:
                self.logger.error(f"Error launching terminal with {cmd[0]}: {e}")
                continue

        self.logger.error("Failed to launch terminal with any available emulator")
        return False

    def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
        """Send a command to the persistent terminal.

        Args:
            command: The command to execute
            ensure_terminal: Whether to launch terminal if not running

        Returns:
            True if command was sent successfully, False otherwise
        """
        # Check if we're in fallback mode
        with self._state_lock:
            fallback_mode = self._fallback_mode

        if fallback_mode:
            self.logger.warning(
                "Persistent terminal in fallback mode - cannot send command"
            )
            return False

        # Validate command before proceeding
        if not command or not command.strip():
            self.logger.error("Attempted to send empty command")
            return False

        # Check for printable ASCII characters (basic sanity check)
        try:
            _ = command.encode("ascii")
        except UnicodeEncodeError:
            self.logger.warning(f"Command contains non-ASCII characters: {command!r}")

        # Perform comprehensive health check if requested
        if ensure_terminal:
            # Log if terminal not running (informational only - health check will handle it)
            if not self._is_dispatcher_running():
                self.logger.warning("Terminal not running, health check will attempt recovery")
            if not self._ensure_dispatcher_healthy():
                # Health check failed and recovery attempts exhausted
                with self._state_lock:
                    fallback_mode = self._fallback_mode

                if fallback_mode:
                    self.logger.error(
                        "Persistent terminal unavailable - fallback mode activated"
                    )
                    return False
                self.logger.error(
                    "Failed to ensure dispatcher is healthy"
                )
                return False

        # Debug logging - snapshot PIDs under lock
        with self._state_lock:
            terminal_pid = self.terminal_pid
            dispatcher_pid = self.dispatcher_pid

        self.logger.debug(
            f"Sending command to FIFO:\n"
            f"  Command: {command!r}\n"
            f"  Length: {len(command)} chars\n"
            f"  FIFO: {self.fifo_path}\n"
            f"  Terminal PID: {terminal_pid}\n"
            f"  Dispatcher PID: {dispatcher_pid}"
        )

        # Acquire lock to serialize FIFO writes
        with self._write_lock:
            # Send command to FIFO using non-blocking I/O
            fifo_fd = None
            max_retries = 2

            for attempt in range(max_retries):
                try:
                    # Open FIFO in non-blocking mode
                    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)

                    # Use binary mode with unbuffered I/O
                    with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
                        fifo_fd = None  # File object now owns the descriptor
                        _ = fifo.write(command.encode("utf-8"))
                        _ = fifo.write(b"\n")

                    self.logger.info(f"Successfully sent command to terminal: {command}")
                    self.command_sent.emit(command)
                    return True

                except OSError as e:
                    if e.errno == errno.ENOENT:
                        # FIFO doesn't exist
                        if attempt < max_retries - 1:
                            self.logger.warning(
                                f"FIFO disappeared, recreating (attempt {attempt + 1}/{max_retries})"
                            )
                            if self._ensure_fifo():
                                time.sleep(_CLEANUP_POLL_INTERVAL_SECONDS)
                                continue
                        self.logger.error(f"Failed to send command to FIFO: {e}")
                    elif e.errno == errno.ENXIO:
                        # No reader available
                        self.logger.error(
                            "No reader available for FIFO - dispatcher may have crashed"
                        )
                        # Mark for health check on next command
                        with self._state_lock:
                            self.dispatcher_pid = None
                    elif e.errno == errno.EAGAIN:
                        self.logger.warning("FIFO write would block (buffer full?)")
                    else:
                        self.logger.error(f"Failed to send command to FIFO: {e}")
                    return False
                finally:
                    # Clean up file descriptor if it wasn't converted to file object
                    if fifo_fd is not None:
                        with contextlib.suppress(OSError):
                            os.close(fifo_fd)

            # If we get here, all attempts failed
            return False

    def send_command_async(self, command: str, ensure_terminal: bool = True) -> None:
        """Send a command to the persistent terminal asynchronously (non-blocking).

        This method returns immediately and performs all blocking operations
        (health checks, terminal restart) in a background thread. Progress
        and completion are reported via signals.

        Signals emitted (Phase 1 lifecycle):
            - command_queued(str, str): When command is queued (timestamp, command)
            - command_executing(str): When execution starts (timestamp)
            - command_verified(str, str): When execution verified (timestamp, message)
            - command_result(bool, str): Final result (success, error_message) - backward compat
            - operation_started(str): When operation begins
            - operation_progress(str, str): Progress updates

        Args:
            command: The command to execute
            ensure_terminal: Whether to launch terminal if not running

        Note:
            For tests and CLI usage, use send_command() (blocking) instead.
            This async method is designed for GUI applications to prevent freezing.
        """
        # Validate command before proceeding
        if not command or not command.strip():
            self.logger.error("Attempted to send empty command")
            self.command_result.emit(False, "Empty command")
            return

        # Check if we're in fallback mode
        with self._state_lock:
            fallback_mode = self._fallback_mode

        if fallback_mode:
            self.logger.warning("Persistent terminal in fallback mode - cannot send command")
            self.command_result.emit(False, "Terminal in fallback mode")
            return

        # Emit queued signal immediately (Phase 1)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_queued.emit(timestamp, command)
        self.logger.debug(f"[{timestamp}] Command queued: {command[:100]}...")

        # Create worker for background operation
        worker = TerminalOperationWorker(self, "send_command", parent=self)
        worker.command = command

        # Connect signals
        def on_progress(msg: str) -> None:
            self.operation_progress.emit("send_command", msg)

        _ = worker.progress.connect(on_progress)
        _ = worker.operation_finished.connect(self._on_async_command_finished)

        # Store worker reference to prevent garbage collection (thread-safe)
        with self._workers_lock:
            self._active_workers.append(worker)

        # Clean up worker when finished
        def cleanup_worker() -> None:
            with self._workers_lock:
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
            worker.deleteLater()

        _ = worker.operation_finished.connect(cleanup_worker)

        # Emit operation started signal
        self.operation_started.emit("send_command")

        # Start background operation
        worker.start()

    def _on_async_command_finished(self, success: bool, message: str) -> None:
        """Handle async command completion.

        Args:
            success: Whether the command was sent successfully
            message: Status message
        """
        if success:
            self.logger.info(f"Async command completed: {message}")
            self.command_result.emit(True, "")
        else:
            self.logger.error(f"Async command failed: {message}")
            self.command_result.emit(False, message)

        # Emit operation finished signal
        self.operation_finished.emit("send_command", success, message)

    def _ensure_dispatcher_healthy(self) -> bool:
        """Ensure dispatcher is healthy, attempting recovery if needed.

        Thread-Safe:
            Can be called from worker threads. Uses internal locks to protect
            shared state access and recovery operations.

        Returns:
            True if dispatcher is healthy, False if recovery failed
        """
        # Check if dispatcher is healthy
        if self._is_dispatcher_healthy():
            self.logger.debug("Dispatcher health check passed")
            return True

        # Snapshot PIDs for logging under lock
        with self._state_lock:
            terminal_pid = self.terminal_pid
            dispatcher_pid = self.dispatcher_pid

        self.logger.warning(
            "Dispatcher health check failed - attempting recovery. "
            f"Terminal PID: {terminal_pid}, Dispatcher PID: {dispatcher_pid}"
        )

        # Check if we've exceeded restart attempts
        with self._state_lock:
            if self._restart_attempts >= self._max_restart_attempts:
                self.logger.error(
                    f"Exceeded maximum restart attempts ({self._max_restart_attempts}) - "
                    f"entering fallback mode. Terminal will not auto-recover."
                )
                self._fallback_mode = True
                return False

            # Attempt to restart terminal
            self._restart_attempts += 1
            restart_attempt = self._restart_attempts

        self.logger.info(
            f"Attempting terminal restart ({restart_attempt}/{self._max_restart_attempts}) "
            f"- reason: health check failure"
        )

        # Force kill existing terminal if needed
        if self._is_terminal_alive():
            with self._state_lock:
                pid_to_kill = self.terminal_pid

            if pid_to_kill:
                try:
                    os.kill(pid_to_kill, signal.SIGKILL)
                    self.logger.info(f"Force killed terminal process {pid_to_kill}")
                    time.sleep(_TERMINAL_RESTART_DELAY_SECONDS)
                except (ProcessLookupError, PermissionError) as e:
                    self.logger.debug(f"Could not kill terminal: {e}")

            with self._state_lock:
                self.terminal_pid = None
                self.terminal_process = None
                self.dispatcher_pid = None

        # Restart terminal
        if not self.restart_terminal():
            self.logger.error("Failed to restart terminal")
            return False

        # Wait for dispatcher to become healthy
        timeout = _DISPATCHER_STARTUP_TIMEOUT_SECONDS
        poll_interval = _CLEANUP_POLL_INTERVAL_SECONDS
        elapsed = 0.0

        while elapsed < timeout:
            if self._is_dispatcher_healthy():
                self.logger.info(
                    f"Dispatcher recovered successfully after {elapsed:.2f}s"
                )
                # Reset restart counter on successful recovery
                with self._state_lock:
                    self._restart_attempts = 0
                return True
            time.sleep(poll_interval)
            elapsed += poll_interval

        self.logger.error(f"Dispatcher did not become healthy after {timeout}s")
        return False

    @property
    def is_fallback_mode(self) -> bool:
        """Check if persistent terminal is in fallback mode.

        Thread-Safe: Uses _state_lock to protect _fallback_mode.

        Returns:
            True if in fallback mode (persistent terminal unavailable)
        """
        with self._state_lock:
            return self._fallback_mode

    def reset_fallback_mode(self) -> None:
        """Reset fallback mode and restart attempts.

        Thread-Safe: Uses _state_lock to protect _fallback_mode and _restart_attempts.

        This allows retrying the persistent terminal after it has been
        disabled due to too many failures.
        """
        with self._state_lock:
            self._fallback_mode = False
            self._restart_attempts = 0
        self.logger.info("Fallback mode reset - persistent terminal re-enabled")

    def clear_terminal(self) -> bool:
        """Clear the terminal screen.

        Returns:
            True if clear command was sent successfully
        """
        return self.send_command("CLEAR_TERMINAL", ensure_terminal=False)

    def close_terminal(self) -> bool:
        """Close the persistent terminal.

        Returns:
            True if terminal was closed successfully
        """
        # Only try graceful exit if dispatcher is running
        # If dispatcher is dead, sending EXIT_TERMINAL will hang/fail
        if self._is_dispatcher_running():
            self.logger.debug("Dispatcher running, sending EXIT_TERMINAL for graceful exit")
            _ = self.send_command("EXIT_TERMINAL", ensure_terminal=False)
            # Give it time to exit gracefully
            time.sleep(_TERMINAL_RESTART_DELAY_SECONDS)
        else:
            self.logger.debug("Dispatcher not running, skipping graceful exit")

        # Force kill if still running
        if self._is_terminal_alive():
            with self._state_lock:
                pid_to_kill = self.terminal_pid

            if pid_to_kill:
                try:
                    self.logger.debug(f"Force killing terminal process {pid_to_kill}")
                    os.kill(pid_to_kill, signal.SIGTERM)
                    time.sleep(_TERMINAL_RESTART_DELAY_SECONDS)
                    if self._is_terminal_alive():
                        os.kill(pid_to_kill, signal.SIGKILL)
                    self.logger.info(f"Force killed terminal process {pid_to_kill}")
                except ProcessLookupError:
                    pass
                except Exception as e:
                    self.logger.error(f"Error killing terminal process: {e}")

        with self._state_lock:
            self.terminal_pid = None
            self.terminal_process = None

        self.terminal_closed.emit()
        return True

    def restart_terminal(self) -> bool:
        """Restart the persistent terminal with atomic FIFO recreation.

        Uses atomic FIFO replacement to prevent race conditions between
        FIFO cleanup and dispatcher startup.

        Returns:
            True if terminal was restarted successfully

        Thread Safety:
            Not thread-safe - should only be called from main thread or
            with external synchronization.

        TODO: Add tests for:
          - TerminalOperationWorker Qt lifecycle with parent parameter
          - Atomic FIFO recreation under race conditions
          - FD leak prevention in _send_command_direct()
        """
        self.logger.info("Restarting terminal (reason: health check failure or manual restart)")

        # Close existing terminal
        _ = self.close_terminal()
        time.sleep(_TERMINAL_RESTART_DELAY_SECONDS)

        # Close dummy writer FD before cleaning up FIFO
        self._close_dummy_writer_fd()

        # ATOMIC FIFO REPLACEMENT to avoid race condition
        # Use unique temp path, then atomic rename
        temp_fifo = f"{self.fifo_path}.{os.getpid()}.tmp"

        # Ensure parent directory exists
        parent_dir = Path(self.fifo_path).parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        # Clean up old FIFO
        if Path(self.fifo_path).exists():
            try:
                Path(self.fifo_path).unlink()
                # CRITICAL: fsync parent directory to ensure unlink is committed
                parent_fd = os.open(str(parent_dir), os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                self.logger.debug(f"Removed stale FIFO at {self.fifo_path}")
            except OSError as e:
                self.logger.warning(f"Could not remove stale FIFO: {e}")

        # Create temp FIFO and atomically rename
        try:
            os.mkfifo(temp_fifo, 0o600)
            # Use os.rename() for guaranteed atomic operation (not Path.rename())
            os.rename(temp_fifo, self.fifo_path)  # noqa: PTH104
            self.logger.debug(f"Atomically created FIFO at {self.fifo_path}")
        except OSError as e:
            self.logger.error(f"Failed to create FIFO atomically: {e}")
            # ✅ CLEANUP: Ensure temp file removed on error (only if it exists)
            if Path(temp_fifo).exists():
                try:
                    Path(temp_fifo).unlink()
                    self.logger.debug(f"Cleaned up temp FIFO: {temp_fifo}")
                except OSError as cleanup_error:
                    self.logger.warning(f"Failed to clean up temp FIFO: {cleanup_error}")
            return False

        # Launch new terminal (starts dispatcher/reader)
        # FIFO is now guaranteed to exist and be valid - no race condition
        if self._launch_terminal():
            # Wait for dispatcher to be ready with timeout (replaces fixed delay)
            self.logger.debug("Waiting for dispatcher to be ready...")
            timeout = _DISPATCHER_STARTUP_TIMEOUT_SECONDS
            poll_interval = _WORKER_POLL_INTERVAL_SECONDS
            elapsed = 0.0

            while elapsed < timeout:
                if self._is_dispatcher_running():
                    self.logger.info(f"Dispatcher ready after {elapsed:.2f}s")

                    # Now that dispatcher is running, open dummy writer to prevent EOF
                    if not self._open_dummy_writer():
                        self.logger.warning("Failed to open dummy writer after dispatcher started")
                        # Continue anyway - terminal is working, just no dummy writer protection

                    self.logger.info("Terminal restarted successfully")
                    return True
                time.sleep(poll_interval)
                elapsed += poll_interval

            # Timeout - dispatcher didn't become ready
            self.logger.warning(f"Dispatcher not ready after {timeout}s timeout")
            self.logger.warning("Terminal launched but dispatcher not responding yet")

            # Try to open dummy writer anyway (might work if dispatcher just slow to respond)
            if not self._open_dummy_writer():
                self.logger.warning("Failed to open dummy writer - FIFO EOF protection unavailable")

            return True  # Terminal is up, dispatcher might just need more time

        self.logger.error("Failed to launch terminal during restart")
        return False

    def cleanup(self) -> None:
        """Clean up resources (workers, FIFO, and terminal).

        IMPORTANT: Workers must be stopped FIRST to prevent deadlock on _state_lock.
        """
        # 1. STOP ALL WORKERS FIRST (before acquiring any locks)
        with self._workers_lock:
            workers_to_stop = list(self._active_workers)

        if workers_to_stop:
            self.logger.info(f"Stopping {len(workers_to_stop)} active workers before cleanup")

        for worker in workers_to_stop:
            # Request stop and wait with timeout
            worker.requestInterruption()
            if not worker.wait(2000):  # 2 second timeout
                self.logger.warning(f"Worker {id(worker)} did not stop gracefully")
                worker.terminate()
                _ = worker.wait(1000)  # Wait 1s for termination

        # Clear workers list
        with self._workers_lock:
            self._active_workers.clear()

        # Remove from test instances tracking
        with self.__class__._test_instances_lock:
            if self in self.__class__._test_instances:
                self.__class__._test_instances.remove(self)

        # 2. THEN cleanup terminal and resources (safe now that workers are stopped)
        # Close terminal if running
        if self._is_terminal_alive():
            _ = self.close_terminal()

        # Close dummy writer FD first
        self._close_dummy_writer_fd()

        # Remove FIFO if it exists
        if Path(self.fifo_path).exists():
            try:
                Path(self.fifo_path).unlink()
                self.logger.debug(f"Removed FIFO at {self.fifo_path}")
            except OSError as e:
                self.logger.warning(f"Could not remove FIFO: {e}")

    def cleanup_fifo_only(self) -> None:
        """Clean up FIFO without closing the terminal.

        This is useful when we want to keep the terminal open
        after the application exits.
        """
        # Remove from test instances tracking
        with self.__class__._test_instances_lock:
            if self in self.__class__._test_instances:
                self.__class__._test_instances.remove(self)

        # Close dummy writer FD first
        self._close_dummy_writer_fd()

        # Only remove FIFO, leave terminal running
        if Path(self.fifo_path).exists():
            try:
                Path(self.fifo_path).unlink()
                self.logger.debug(
                    f"Removed FIFO at {self.fifo_path}, terminal left running"
                )
            except OSError as e:
                self.logger.warning(f"Could not remove FIFO: {e}")

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            # Close dummy writer FD
            if hasattr(self, "_close_dummy_writer_fd"):
                self._close_dummy_writer_fd()

            # Only cleanup FIFO, leave terminal running
            if hasattr(self, "fifo_path") and Path(self.fifo_path).exists():
                Path(self.fifo_path).unlink()
        except Exception:
            pass

    @classmethod
    def cleanup_all_instances(cls) -> None:
        """Clean up all tracked instances (for test teardown).

        INTERNAL USE ONLY: This is called by pytest fixtures to ensure
        all PersistentTerminalManager instances are cleaned up before
        pytest-qt teardown begins.

        This prevents workers from spawning subprocesses during pytest teardown,
        which causes "Fatal Python error: Aborted" crashes.
        """
        with cls._test_instances_lock:
            instances = list(cls._test_instances)

        for instance in instances:
            try:
                instance.cleanup()
            except Exception:
                # Ignore errors during test cleanup
                pass
