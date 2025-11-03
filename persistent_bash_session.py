"""Persistent Bash Session for efficient subprocess handling.

This module provides a reusable bash session to avoid repeated process spawning,
with exponential backoff, non-blocking I/O, and robust error recovery.

Extracted from process_pool_manager.py to reduce complexity.
"""

from __future__ import annotations

# Standard library imports
import logging
import os
import subprocess
import threading
import time

# Local application imports
from config import ThreadingConfig
from logging_mixin import LoggingMixin


# Try to import fcntl for non-blocking I/O (Unix-only)
try:
    # Standard library imports
    import fcntl as _fcntl_module

    _has_fcntl = True
except ImportError:
    _fcntl_module = None
    _has_fcntl = False
    logging.warning("fcntl module not available - will use blocking I/O")

HAS_FCNTL = _has_fcntl

# Import debug utilities
try:
    # Local application imports
    from debug_utils import CommandTracer as _CommandTracer
    from debug_utils import deadlock_detector as _deadlock_detector
    from debug_utils import state_tracker as _state_tracker

    _has_debug_utils = True
except ImportError:
    _CommandTracer = None
    _deadlock_detector = None
    _state_tracker = None
    _has_debug_utils = False

HAS_DEBUG_UTILS = _has_debug_utils

# Create module-level logger for configuration
_module_logger = logging.getLogger(__name__)

# Enable verbose debug logging if environment variable is set
DEBUG_VERBOSE = os.environ.get("SHOTBOT_DEBUG_VERBOSE", "").lower() in (
    "1",
    "true",
    "yes",
)
if DEBUG_VERBOSE:
    _module_logger.setLevel(logging.DEBUG)
    _module_logger.info("VERBOSE DEBUG MODE ENABLED for PersistentBashSession")


class PersistentBashSession(LoggingMixin):
    """Reusable bash session to avoid repeated process spawning."""

    # Exponential backoff configuration
    INITIAL_RETRY_DELAY = 0.1  # 100ms
    MAX_RETRY_DELAY = 5.0  # 5 seconds
    BACKOFF_MULTIPLIER = 2.0
    MAX_RETRIES = 5

    # Polling configuration for efficient subprocess reading
    INITIAL_POLL_INTERVAL = ThreadingConfig.INITIAL_POLL_INTERVAL  # 10ms
    MAX_POLL_INTERVAL = ThreadingConfig.MAX_POLL_INTERVAL  # 500ms
    POLL_BACKOFF_FACTOR = ThreadingConfig.POLL_BACKOFF_FACTOR

    def __init__(self, session_id: str) -> None:
        """Initialize persistent bash session.

        Args:
            session_id: Unique identifier for this session
        """
        super().__init__()
        self.session_id = session_id
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._command_count = 0
        self._start_time = time.time()
        self._last_command_time = time.time()
        self._retry_count = 0
        self._retry_delay = self.INITIAL_RETRY_DELAY
        self._last_retry_time = 0
        self._poll_interval = self.INITIAL_POLL_INTERVAL
        self._consecutive_empty_polls = 0
        self._stderr_drain_thread: threading.Thread | None = None
        self._start_session()

    def _start_session(self, with_backoff: bool = False) -> None:
        """Start persistent bash session with optional exponential backoff.

        Args:
            with_backoff: Whether to use exponential backoff for retries
        """
        if DEBUG_VERBOSE:
            self.logger.debug(
                f"[{self.session_id}] Starting session (with_backoff={with_backoff})",
            )

        # Track state transition
        if HAS_DEBUG_UTILS and _state_tracker is not None:
            _state_tracker.transition(
                self.session_id,
                "STARTING",
                "Session initialization",
            )

        # Ensure any existing process is cleaned up first
        if self._process is not None:
            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] Cleaning up existing process before start",
                )
            self._kill_session()

        if with_backoff and self._retry_count > 0:
            # Apply exponential backoff if this is a retry
            current_time = time.time()
            time_since_last_retry = current_time - self._last_retry_time

            # Only apply delay if we're retrying quickly
            if time_since_last_retry < self._retry_delay:
                sleep_time = self._retry_delay - time_since_last_retry
                self.logger.info(
                    f"Backing off for {sleep_time:.2f}s before retry {self._retry_count}",
                )
                time.sleep(sleep_time)

            # Update retry delay with exponential backoff
            self._retry_delay = min(
                self._retry_delay * self.BACKOFF_MULTIPLIER,
                self.MAX_RETRY_DELAY,
            )
            self._last_retry_time = current_time

        try:
            # Use interactive bash (required for ws command)
            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] Creating subprocess.Popen with interactive bash",
                )
                # Log file descriptors before subprocess creation
                # Standard library imports
                import sys

                self.logger.debug(
                    f"[{self.session_id}] FDs before Popen: stdin={sys.stdin.fileno() if hasattr(sys.stdin, 'fileno') else 'N/A'}, stdout={sys.stdout.fileno() if hasattr(sys.stdout, 'fileno') else 'N/A'}, stderr={sys.stderr.fileno() if hasattr(sys.stderr, 'fileno') else 'N/A'}",
                )

            # Prepare environment to prevent terminal escape sequences
            env = os.environ.copy()
            env["TERM"] = "dumb"  # Disable terminal escape sequences
            env["PS1"] = ""  # Clear primary prompt
            env["PS2"] = ""  # Clear secondary prompt

            # Use interactive bash for real applications where ws command is needed
            # The -i flag is required for shell functions like 'ws'
            self._process = subprocess.Popen(
                ["/bin/bash", "-i"],  # Interactive mode required for ws command
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Separate stderr to filter warnings
                text=True,
                bufsize=1,  # Line buffered (unbuffered not supported with text mode)
                env=env,
                # CRITICAL Linux fixes to prevent file descriptor inheritance deadlock
                close_fds=True,  # Close all FDs except stdin/stdout/stderr to prevent Qt FD inheritance
                start_new_session=True,  # Create new process group (POSIX only, ignored on Windows)
                restore_signals=True,  # Reset signal handlers to defaults (prevents Qt signal interference)
            )

            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] Process created with PID: {self._process.pid}",
                )
                if self._process.stdin and self._process.stdout:
                    self.logger.debug(
                        f"[{self.session_id}] Process FDs: stdin={self._process.stdin.fileno()}, stdout={self._process.stdout.fileno()}",
                    )

            # Verify process started successfully
            if self._process.poll() is not None:
                raise RuntimeError("Bash process died immediately after starting")

            # Start stderr drain thread to prevent buffer-full deadlock
            self._stderr_drain_thread = threading.Thread(
                target=self._drain_stderr,
                daemon=True,
                name=f"stderr-drain-{self.session_id}",
            )
            self._stderr_drain_thread.start()

            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] Started stderr drain thread"
                )

            # Set stdout to non-blocking mode to avoid hanging in pytest
            try:
                if self._process.stdout is None:
                    raise RuntimeError("Process stdout is None")

                stdout_fd = self._process.stdout.fileno()

                # Only attempt non-blocking I/O if fcntl is available
                if HAS_FCNTL:
                    if hasattr(os, "set_blocking"):
                        # Python 3.5+ way
                        os.set_blocking(stdout_fd, False)
                    # Fallback for older Python - use module-level fcntl import
                    elif _fcntl_module is not None:
                        flags = _fcntl_module.fcntl(
                            stdout_fd, _fcntl_module.F_GETFL
                        )
                        _fcntl_module.fcntl(
                            stdout_fd, _fcntl_module.F_SETFL, flags | os.O_NONBLOCK
                        )
                else:
                    self.logger.debug(
                        "Skipping non-blocking I/O setup (fcntl not available)",
                    )

            except (OSError, ValueError, AttributeError) as e:
                self.logger.debug(f"Could not set non-blocking mode on stdout: {e}")
                # This is not critical - continue without non-blocking mode

            # Set up session - simplified without problematic draining
            try:
                # Delay to let bash initialize properly
                # Increase delay for subsequent sessions to avoid resource contention
                if "workspace_1" in self.session_id or "workspace_2" in self.session_id:
                    time.sleep(0.2)  # More delay for second/third sessions
                else:
                    time.sleep(0.1)  # Standard delay for first session

                # Send a unique marker to verify session is ready
                # Standard library imports
                import uuid

                marker = f"SHOTBOT_INIT_{uuid.uuid4().hex[:8]}"

                # Simple initialization - just set PS1 and echo marker
                init_command = f"export PS1=''; export PS2=''; echo '{marker}'\n"
                if self._process.stdin is not None:
                    self._process.stdin.write(init_command)
                    self._process.stdin.flush()
                else:
                    raise RuntimeError("Process stdin is None")

                # CRITICAL FIX: Read output until we find our marker
                # This ensures the session is ready and prevents deadlock
                start_time = time.time()
                timeout = 2.0  # 2 second timeout for initialization
                found_marker = False

                if DEBUG_VERBOSE:
                    self.logger.debug(
                        f"[{self.session_id}] Waiting for initialization marker: {marker}",
                    )

                # Track state
                if (
                    HAS_DEBUG_UTILS
                    and _state_tracker is not None
                    and _deadlock_detector is not None
                ):
                    _state_tracker.transition(
                        self.session_id,
                        "WAITING_MARKER",
                        "Waiting for init marker",
                    )
                    _deadlock_detector.waiting(self.session_id, "initialization_marker")

                # Accumulate all output to search for marker
                accumulated_output = ""
                poll_interval = self.INITIAL_POLL_INTERVAL

                while time.time() - start_time < timeout:
                    elapsed = time.time() - start_time
                    remaining_time = timeout - elapsed

                    if self._process.stdout:
                        try:
                            if HAS_FCNTL:
                                # Non-blocking read - check if data is available
                                try:
                                    # Standard library imports
                                    import select

                                    if (
                                        DEBUG_VERBOSE and int(elapsed * 10) % 5 == 0
                                    ):  # Log every 0.5 seconds
                                        self.logger.debug(
                                            f"[{self.session_id}] Checking for data at {elapsed:.1f}s...",
                                        )

                                    # Use adaptive timeout with exponential backoff
                                    ready, _, _ = select.select(
                                        [self._process.stdout],
                                        [],
                                        [],
                                        min(poll_interval, remaining_time),
                                    )
                                    if ready:
                                        # Read available data - use readline to avoid blocking
                                        line = self._process.stdout.readline()
                                        if line:
                                            accumulated_output += line
                                            # Reset backoff on successful read
                                            poll_interval = self.INITIAL_POLL_INTERVAL
                                            self._consecutive_empty_polls = 0
                                            if DEBUG_VERBOSE:
                                                self.logger.debug(
                                                    f"[{self.session_id}] Read line ({len(line)} bytes): {line[:100].strip()}",
                                                )
                                            if marker in accumulated_output:
                                                found_marker = True
                                                self.logger.debug(
                                                    f"[{self.session_id}] Session initialized successfully (non-blocking)",
                                                )
                                                break
                                    else:
                                        # No data available - apply exponential backoff
                                        self._consecutive_empty_polls += 1
                                        poll_interval = min(
                                            poll_interval * self.POLL_BACKOFF_FACTOR,
                                            self.MAX_POLL_INTERVAL,
                                        )

                                        # Log if polling for extended time
                                        if (
                                            self._consecutive_empty_polls > 10
                                            and DEBUG_VERBOSE
                                        ):
                                            self.logger.debug(
                                                f"[{self.session_id}] No output for {self._consecutive_empty_polls} polls, interval: {poll_interval:.3f}s",
                                            )

                                        # Yield CPU to other threads for long polls
                                        if poll_interval > 0.1:
                                            time.sleep(0.001)  # Small yield
                                except ImportError:
                                    # select not available, fall back to readline
                                    self.logger.debug(
                                        "select module not available, using readline",
                                    )
                                    line = self._process.stdout.readline()
                                    if line:
                                        accumulated_output += line
                                        if marker in accumulated_output:
                                            found_marker = True
                                            self.logger.debug(
                                                "Session initialized successfully (readline)",
                                            )
                                            break
                            else:
                                # Blocking read with readline
                                line = self._process.stdout.readline()
                                if line:
                                    accumulated_output += line
                                    if marker in accumulated_output:
                                        found_marker = True
                                        self.logger.debug(
                                            "Session initialized successfully (blocking)",
                                        )
                                        break
                        except Exception as read_error:
                            self.logger.debug(
                                f"[{self.session_id}] Read error during initialization: {read_error}",
                            )
                            # Small sleep to avoid busy loop
                            time.sleep(0.01)

                    # Also check if process died
                    if self._process.poll() is not None:
                        exit_code = self._process.returncode
                        self.logger.error(
                            f"[{self.session_id}] Bash process died during initialization with exit code: {exit_code}",
                        )
                        raise RuntimeError(
                            f"Bash process died during initialization (exit code: {exit_code})",
                        )

                # Check if we successfully initialized
                if not found_marker:
                    self.logger.warning(
                        f"[{self.session_id}] Session initialization marker not found after {timeout}s",
                    )
                    self.logger.warning(
                        f"[{self.session_id}] Accumulated output: {accumulated_output[:500]}",
                    )
                    # Try a simpler initialization as fallback
                    try:
                        if self._process.stdin:
                            self._process.stdin.write("echo 'FALLBACK_INIT'\n")
                            self._process.stdin.flush()
                            time.sleep(0.2)
                            # Try to read any response
                            if self._process.stdout:
                                try:
                                    test_line = self._process.stdout.readline()
                                    if test_line:
                                        self.logger.info(
                                            f"[{self.session_id}] Fallback init response: {test_line.strip()}",
                                        )
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    # Continue anyway - the session might still work

            except Exception as e:
                self.logger.error(f"Failed to initialize bash session: {e}")
                self._kill_session()
                raise RuntimeError(f"Session initialization failed: {e}") from e

            # Reset retry count on successful start
            self._retry_count = 0
            self._retry_delay = self.INITIAL_RETRY_DELAY

            self.logger.info(f"Started persistent bash session: {self.session_id}")
            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] Session fully initialized and ready"
                )

            # Track successful initialization
            if (
                HAS_DEBUG_UTILS
                and _state_tracker is not None
                and _deadlock_detector is not None
            ):
                _state_tracker.transition(
                    self.session_id,
                    "READY",
                    "Session initialized",
                )
                _deadlock_detector.done_waiting(self.session_id)

        except Exception as e:
            self._process = None  # Ensure clean state
            self._retry_count += 1
            if self._retry_count > self.MAX_RETRIES:
                self.logger.error(
                    f"Failed to start bash session {self.session_id} after {self.MAX_RETRIES} retries: {e}",
                )
                self._retry_count = 0  # Reset for next attempt
                raise
            self.logger.warning(
                f"Failed to start bash session {self.session_id} (retry {self._retry_count}/{self.MAX_RETRIES}): {e}",
            )
            raise

    def _strip_escape_sequences(self, text: str) -> str:
        """Strip ANSI/terminal escape sequences from text.

        Args:
            text: Text potentially containing escape sequences

        Returns:
            Clean text without escape sequences
        """
        # Standard library imports
        import re

        # Remove OSC (Operating System Command) sequences like ]777;...
        text = re.sub(r"\x1b\].*?(\x07|\x1b\\)", "", text)  # ESC ] ... BEL or ESC \
        text = re.sub(r"\]777;[^\x07\n]*", "", text)  # ]777; sequences without ESC

        # Remove CSI (Control Sequence Introducer) sequences like ESC[...
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)

        # Remove other escape sequences
        text = re.sub(r"\x1b[>=]", "", text)  # ESC > or ESC =
        text = re.sub(r"\x1b\([B0UK]", "", text)  # Character set sequences

        # Remove any remaining control characters except newline and tab
        return "".join(char for char in text if ord(char) >= 32 or char in "\n\t")


    def _drain_stderr(self) -> None:
        """Drain stderr to prevent deadlock from buffer-full blocking.

        This method runs in a background thread and continuously reads stderr
        to prevent the process from blocking when stderr buffer fills up.
        """
        if not self._process or not self._process.stderr:
            return

        # Capture stderr stream reference to avoid None check issues during iteration
        stderr_stream = self._process.stderr

        try:
            # Use iterator pattern for line-by-line reading (same as launcher/worker.py)
            for line in stderr_stream:
                # Discard output by default (stderr from bash -i is mostly noise)
                if DEBUG_VERBOSE:
                    # Only log in verbose mode to aid debugging
                    clean_line = line.rstrip()
                    if clean_line:
                        self.logger.debug(f"[{self.session_id}] stderr: {clean_line}")
        except ValueError:
            # Stream closed - this is expected during shutdown
            if DEBUG_VERBOSE:
                self.logger.debug(f"[{self.session_id}] stderr stream closed (normal shutdown)")
        except OSError as e:
            # Stream I/O errors - expected during process termination
            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] stderr I/O error (likely process termination): {e}"
                )
        except Exception as e:
            # Truly unexpected errors - log at warning level with stack trace
            self.logger.warning(
                f"[{self.session_id}] Unexpected stderr drain error: {e}", exc_info=True
            )

    def _read_with_backoff(
        self,
        timeout: float,
        marker: str | None = None,
    ) -> tuple[str, bool]:
        """Read from subprocess with exponential backoff polling.

        Args:
            timeout: Maximum time to wait for data
            marker: Optional marker to stop reading when found

        Returns:
            Tuple of (output, found_marker)
        """
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Process not available for reading")

        output: list[str] = []
        buffer = ""
        start_time = time.time()
        poll_interval = self.INITIAL_POLL_INTERVAL
        consecutive_empty_polls = 0
        found_marker = False

        # Decide whether to use select or fcntl based on availability
        use_select = False
        select_module = None
        try:
            # Standard library imports
            import select as select_module

            use_select = True
        except ImportError:
            if not HAS_FCNTL:
                self.logger.warning(
                    "Neither select nor fcntl available - using blocking I/O",
                )

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time
            remaining_time = max(0.01, timeout - elapsed)

            try:
                if use_select and select_module is not None:
                    # Use select with adaptive timeout
                    ready, _, _ = select_module.select(
                        [self._process.stdout],
                        [],
                        [],
                        min(poll_interval, remaining_time),
                    )

                    if ready:
                        # Data available - read it
                        if HAS_FCNTL:
                            # Non-blocking read
                            chunk = self._process.stdout.read(4096)
                            if chunk:
                                buffer += chunk
                                lines = buffer.split("\n")
                                buffer = lines[-1]

                                for line in lines[:-1]:
                                    if marker and marker in line:
                                        found_marker = True
                                        return "\n".join(output), found_marker

                                    # Filter initialization markers
                                    if not line.startswith("SHOTBOT_INIT_"):
                                        clean_line = self._strip_escape_sequences(
                                            line.rstrip(),
                                        )
                                        if clean_line:
                                            output.append(clean_line)

                                # Reset backoff on successful read
                                poll_interval = self.INITIAL_POLL_INTERVAL
                                consecutive_empty_polls = 0
                        else:
                            # Blocking readline
                            line = self._process.stdout.readline()
                            if line:
                                if marker and marker in line:
                                    found_marker = True
                                    return "\n".join(output), found_marker

                                if not line.startswith("SHOTBOT_INIT_"):
                                    clean_line = self._strip_escape_sequences(
                                        line.rstrip(),
                                    )
                                    if clean_line:
                                        output.append(clean_line)

                                # Reset backoff
                                poll_interval = self.INITIAL_POLL_INTERVAL
                                consecutive_empty_polls = 0
                    else:
                        # No data available - apply exponential backoff
                        consecutive_empty_polls += 1
                        poll_interval = min(
                            poll_interval * self.POLL_BACKOFF_FACTOR,
                            self.MAX_POLL_INTERVAL,
                        )

                        # Yield CPU to other threads for long polls
                        if poll_interval > 0.1:
                            time.sleep(0.001)

                        if DEBUG_VERBOSE and consecutive_empty_polls > 10:
                            self.logger.debug(
                                f"[{self.session_id}] No output for {consecutive_empty_polls} polls, interval: {poll_interval:.3f}s",
                            )

                elif HAS_FCNTL:
                    # No select, but have fcntl - non-blocking read with sleep
                    chunk = self._process.stdout.read(4096)
                    if chunk:
                        buffer += chunk
                        lines = buffer.split("\n")
                        buffer = lines[-1]

                        for line in lines[:-1]:
                            if marker and marker in line:
                                found_marker = True
                                return "\n".join(output), found_marker

                            if not line.startswith("SHOTBOT_INIT_"):
                                clean_line = self._strip_escape_sequences(line.rstrip())
                                if clean_line:
                                    output.append(clean_line)

                        poll_interval = self.INITIAL_POLL_INTERVAL
                    else:
                        # Apply backoff
                        poll_interval = min(
                            poll_interval * self.POLL_BACKOFF_FACTOR,
                            self.MAX_POLL_INTERVAL,
                        )
                        time.sleep(poll_interval)

                else:
                    # Fallback to blocking readline
                    line = self._process.stdout.readline()
                    if line:
                        if marker and marker in line:
                            found_marker = True
                            return "\n".join(output), found_marker

                        if not line.startswith("SHOTBOT_INIT_"):
                            clean_line = self._strip_escape_sequences(line.rstrip())
                            if clean_line:
                                output.append(clean_line)

            except OSError as e:
                # Handle EAGAIN for non-blocking I/O
                # Note: select.error is a subclass of IOError, so it's handled here too
                if HAS_FCNTL:
                    # Standard library imports
                    import errno

                    if e.errno == errno.EAGAIN:
                        # No data available - apply backoff
                        poll_interval = min(
                            poll_interval * self.POLL_BACKOFF_FACTOR,
                            self.MAX_POLL_INTERVAL,
                        )
                        time.sleep(poll_interval)
                        continue
                # Log if it's a select error
                if "select" in str(type(e).__name__).lower():
                    self.logger.error(f"Select error during read: {e}")
                raise

        # Timeout reached
        return "\n".join(output), found_marker

    def execute(
        self,
        command: str,
        timeout: int | None = None,
    ) -> str:
        """Execute command in persistent session.

        Args:
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            Command output

        Raises:
            TimeoutError: If command times out
            RuntimeError: If session is dead
        """
        if timeout is None:
            timeout = int(ThreadingConfig.SUBPROCESS_TIMEOUT)

        if DEBUG_VERBOSE:
            self.logger.debug(
                f"[{self.session_id}] Execute called with command: {command[:100]}...",
            )

        # Trace command execution
        if (
            HAS_DEBUG_UTILS
            and _CommandTracer is not None
            and _state_tracker is not None
        ):
            _CommandTracer.trace(command, self.session_id)
            _state_tracker.transition(self.session_id, "EXECUTING", "Running command")

        with self._lock:
            # Try to restart session with exponential backoff if dead
            if not self._is_alive():
                self.logger.warning(
                    f"Session {self.session_id} died, restarting with backoff...",
                )

                # Attempt restart with exponential backoff
                restart_attempts = 0
                while restart_attempts < self.MAX_RETRIES:
                    try:
                        self._start_session(with_backoff=True)
                        break
                    except Exception as e:
                        restart_attempts += 1
                        if restart_attempts >= self.MAX_RETRIES:
                            raise RuntimeError(
                                f"Failed to restart session {self.session_id} after {self.MAX_RETRIES} attempts: {e}",
                            ) from e
                        self.logger.debug(
                            f"Restart attempt {restart_attempts} failed, retrying...",
                        )

            # Verify process is available after restart
            if (
                self._process is None
                or self._process.stdin is None
                or self._process.stdout is None
            ):
                raise RuntimeError(f"Failed to start session {self.session_id}")

            # Send command with unique marker
            marker = f"<<<SHOTBOT_{self.session_id}_{time.time()}>>>"
            # Always print the marker, even if command fails (using || true to bypass set -e)
            full_command = f'({command}) || true; echo "{marker}"'

            if DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{self.session_id}] Sending command with marker: {marker}",
                )
                self.logger.debug(
                    f"[{self.session_id}] Full command: {full_command[:200]}...",
                )

            try:
                self._process.stdin.write(f"{full_command}\n")
                self._process.stdin.flush()

                if DEBUG_VERBOSE:
                    self.logger.debug(
                        f"[{self.session_id}] Command sent to stdin and flushed",
                    )

                # Read output until marker using improved polling
                try:
                    output, found_marker = self._read_with_backoff(timeout, marker)

                    if not found_marker:
                        self.logger.debug(
                            f"[{self.session_id}] Marker not found after {timeout}s for command: {command[:50]}...",
                        )
                        if DEBUG_VERBOSE:
                            self.logger.debug(
                                f"[{self.session_id}] Output collected: {output[:500] if output else 'None'}",
                            )
                        # Try to recover
                        self._kill_session()
                        # Don't try to restart here - let next execute() handle it
                        self._process = None
                        raise TimeoutError(
                            f"Command timed out after {timeout}s: {command}",
                        )

                    # Success - update counters
                    self._command_count += 1
                    self._last_command_time = time.time()

                    if DEBUG_VERBOSE:
                        self.logger.debug(
                            f"[{self.session_id}] Returning {len(output)} chars of output",
                        )

                    return output

                except RuntimeError as e:
                    self.logger.error(
                        f"[{self.session_id}] Process died during execution: {e}",
                    )
                    self._kill_session()
                    self._process = None
                    raise

            except TimeoutError:
                # Re-raise timeout errors as-is
                raise
            except Exception as e:
                self.logger.error(
                    f"Error executing command in session {self.session_id}: {e}",
                )
                # Try to recover with exponential backoff
                self._kill_session()
                self._retry_count += 1
                self.logger.warning(
                    f"Command execution failed, attempting recovery (retry {self._retry_count})",
                )
                # Don't restart here - let next execute() handle it
                self._process = None
                raise

    def _execute_internal(self, command: str) -> None:
        """Execute internal setup command without markers.

        Args:
            command: Setup command to execute

        Raises:
            RuntimeError: If process is not available
        """
        if not self._process or not self._process.stdin:
            raise RuntimeError("Process not available for internal command")

        try:
            self._process.stdin.write(f"{command}\n")
            self._process.stdin.flush()
            time.sleep(0.1)  # Brief pause for command to complete
        except (BrokenPipeError, OSError) as e:
            self.logger.error(f"Failed to execute internal command: {e}")
            raise RuntimeError(f"Internal command failed: {e}") from e

    def _is_alive(self) -> bool:
        """Check if session is still alive.

        Returns:
            True if session is alive
        """
        return self._process is not None and self._process.poll() is None

    def _kill_session(self) -> None:
        """Kill the current session."""
        # FIRST: Stop stderr drain thread BEFORE killing process
        # Capture reference to avoid race conditions during cleanup
        drain_thread = self._stderr_drain_thread
        if drain_thread is not None:
            # Close stderr stream to unblock the iterator in _drain_stderr
            if self._process and self._process.stderr:
                try:
                    self._process.stderr.close()
                except (OSError, ValueError):
                    # Ignore errors during stream close
                    pass

            # Wait for drain thread to finish with timeout (even if not currently alive)
            # This ensures we don't leak threads that might start after our check
            if drain_thread.is_alive():
                drain_thread.join(timeout=1.0)

                if drain_thread.is_alive():
                    self.logger.warning(
                        f"[{self.session_id}] stderr drain thread did not finish in time"
                    )

            # Clear reference even if thread is still alive (daemon threads won't block exit)
            self._stderr_drain_thread = None

        # THEN: Kill the process (existing code)
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.logger.warning(
                    f"Session {self.session_id} didn't terminate gracefully, killing",
                )
                try:
                    self._process.kill()
                    self._process.wait(timeout=1)
                except Exception as e:
                    self.logger.error(f"Failed to kill session {self.session_id}: {e}")
            except OSError as e:
                self.logger.warning(f"Error terminating session {self.session_id}: {e}")
            finally:
                self._process = None

    def get_stats(self) -> dict[str, str | bool | int | float]:
        """Get session statistics.

        Returns:
            Dictionary with session stats (session_id, alive status, command count, uptime, idle time)
        """
        uptime = time.time() - self._start_time
        idle_time = time.time() - self._last_command_time

        return {
            "session_id": self.session_id,
            "alive": self._is_alive(),
            "commands_executed": self._command_count,
            "uptime_seconds": uptime,
            "idle_seconds": idle_time,
        }

    def close(self) -> None:
        """Close the session gracefully."""
        self._kill_session()
        self.logger.info(f"Closed bash session: {self.session_id}")
