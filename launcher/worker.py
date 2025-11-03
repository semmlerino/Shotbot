"""Worker thread for launcher command execution.

This module contains the LauncherWorker class that handles subprocess
execution in a separate thread, extracted from the original launcher_manager.py.
"""

from __future__ import annotations

# Standard library imports
import re
import shlex
import subprocess
import threading
from typing import IO

# Third-party imports
from PySide6.QtCore import Signal

# Local application imports
from exceptions import SecurityError
from thread_safe_worker import ThreadSafeWorker


class LauncherWorker(ThreadSafeWorker):
    """Thread-safe worker for executing launcher commands.

    This worker inherits thread-safe lifecycle management from ThreadSafeWorker
    and adds launcher-specific functionality.
    """

    # Launcher-specific signals
    command_started = Signal(str, str)  # launcher_id, command
    command_finished = Signal(str, bool, int)  # launcher_id, success, return_code
    command_error = Signal(str, str)  # launcher_id, error_message

    def __init__(
        self,
        launcher_id: str,
        command: str,
        working_dir: str | None = None,
    ) -> None:
        """Initialize launcher worker.

        Args:
            launcher_id: Unique identifier for this launcher
            command: Command to execute
            working_dir: Optional working directory for the command
        """
        super().__init__()
        self.launcher_id = launcher_id
        self.command = command
        self.working_dir = working_dir
        self._process: subprocess.Popen[bytes] | None = None

    def _sanitize_command(self, command: str) -> tuple[list[str], bool]:
        """Safely parse and validate command to prevent shell injection.

        Args:
            command: Command string to sanitize

        Returns:
            Tuple of (command_list, use_shell) where use_shell is always False
            for security

        Raises:
            SecurityError: If command contains dangerous patterns or isn't whitelisted
        """
        # Whitelist of allowed base commands
        ALLOWED_COMMANDS = {
            "3de",
            "3de4",
            "3dequalizer",
            "nuke",
            "nuke_i",
            "nukex",
            "maya",
            "mayapy",
            "rv",
            "rvpkg",
            "houdini",
            "hython",
            "katana",
            "mari",
            "publish",
            "publish_standalone",
            "python",
            "python3",
            # SECURITY: bash and sh removed - use specific safe commands only
        }

        # Dangerous patterns that indicate potential injection attempts
        DANGEROUS_PATTERNS = [
            r";\s*(rm|sudo|su|chmod|chown|dd|mkfs|fdisk)\s",
            r"&&\s*(rm|sudo|su|chmod|chown|dd|mkfs|fdisk)\s",
            r"\|\s*(rm|sudo|su|chmod|chown|dd|mkfs|fdisk)\s",
            r"`[^`]*`",  # Command substitution
            r"\$\([^)]*\)",  # Command substitution
            r"\$\{[^}]*\}",  # Variable expansion that could be dangerous
            r">\s*/dev/(sda|sdb|sdc|null)",  # Dangerous redirects
            r"2>&1.*>/dev/null.*rm",  # Hidden rm commands
        ]

        # Check for dangerous patterns
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise SecurityError(
                    f"Command contains dangerous pattern and was blocked: {command[:100]}"
                )

        # Try to parse the command safely
        try:
            cmd_list = shlex.split(command)

            # Validate the base command is in whitelist
            if cmd_list:
                base_command = cmd_list[0].split("/")[
                    -1
                ]  # Get command name without path
                if base_command not in ALLOWED_COMMANDS:
                    # Check if it's a full path to an allowed command
                    allowed = False
                    for allowed_cmd in ALLOWED_COMMANDS:
                        if allowed_cmd in cmd_list[0]:
                            allowed = True
                            break

                    if not allowed:
                        # Note: Using module-level log since this is a static validation method
                        # Will be converted to self.logger when this becomes an instance method
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"Command '{base_command}' not in whitelist. Command: {command[:100]}"
                        )
                        raise SecurityError(
                            f"Command '{base_command}' is not in the allowed command whitelist"
                        )

            # Never use shell=True for security
            return cmd_list, False

        except ValueError as e:
            # If shlex.split fails, the command is malformed
            # Do not fall back to shell=True - this is a security risk
            # Note: Using module-level log since this is a static validation method
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to parse command safely: {command[:100]}")
            raise SecurityError(
                f"Command could not be parsed safely and was blocked: {e!s}"
            ) from e

    def do_work(self) -> None:
        """Execute the launcher command with proper lifecycle management.

        This method is called by the base class run() method and includes
        proper state management and error handling.
        """
        try:
            # Emit start signal
            self.command_started.emit(self.launcher_id, self.command)
            self.logger.info(
                f"Worker {id(self)} starting launcher '{self.launcher_id}': {self.command}",
            )

            # Parse command properly to avoid shell injection
            # Security: Parse and validate command to prevent injection
            # Sanitize and validate the command
            cmd_list, use_shell = self._sanitize_command(self.command)

            # Start the process
            # Use PIPE instead of DEVNULL to prevent deadlock with verbose applications
            self._process = subprocess.Popen(
                cmd_list,
                shell=use_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.working_dir,
                start_new_session=True,  # Isolate process group
            )

            # Create drain threads to consume output and prevent buffer-full deadlock
            def drain_stream(stream: IO[bytes] | None) -> None:
                """Continuously read and discard output from a stream."""
                if stream is None:
                    return
                try:
                    for _ in stream:
                        pass  # Discard output
                except (OSError, ValueError):
                    pass  # Stream closed or process terminated

            # Start daemon threads to drain stdout and stderr
            # Type guard: _process is guaranteed to be non-None after Popen() call
            assert self._process is not None
            stdout_thread = threading.Thread(
                target=drain_stream, args=(self._process.stdout,), daemon=True
            )
            stderr_thread = threading.Thread(
                target=drain_stream, args=(self._process.stderr,), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()

            # Monitor process with periodic checks for stop requests
            while not self.is_stop_requested():
                try:
                    # Check if process finished with timeout
                    # Type guard: _process is guaranteed to be non-None at this point
                    assert self._process is not None
                    return_code = self._process.wait(timeout=1.0)
                    # Process finished normally
                    success = return_code == 0
                    self.logger.info(
                        f"Worker {id(self)} finished launcher '{self.launcher_id}' with code {return_code}",
                    )
                    self.command_finished.emit(self.launcher_id, success, return_code)
                    return
                except subprocess.TimeoutExpired:
                    # Process still running, check for stop request
                    continue

            # Stop was requested - terminate the process
            if self._process and self._process.poll() is None:
                self.logger.info(
                    f"Worker {id(self)} stopping launcher '{self.launcher_id}' due to stop request",
                )
                self._terminate_process()
                self.command_finished.emit(self.launcher_id, False, -2)

        except Exception as e:
            error_msg = f"Worker exception for launcher '{self.launcher_id}': {e!s}"
            self.logger.exception(error_msg)
            self.command_error.emit(self.launcher_id, error_msg)
            self.command_finished.emit(self.launcher_id, False, -1)
        finally:
            # Ensure process is cleaned up
            self._cleanup_process()

    def _terminate_process(self) -> None:
        """Safely terminate the subprocess."""
        if not self._process:
            return

        try:
            # Try graceful termination first
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Force kill if necessary
                self.logger.warning(
                    f"Force killing launcher '{self.launcher_id}' after timeout",
                )
                self._process.kill()
                self._process.wait(timeout=5)
        except Exception as e:
            self.logger.error(
                f"Error terminating process for '{self.launcher_id}': {e}"
            )

    def _cleanup_process(self) -> None:
        """Clean up process resources."""
        if self._process:
            # Ensure process is terminated
            if self._process.poll() is None:
                try:
                    self._terminate_process()
                    # Only set to None if termination succeeded or process is dead
                    if self._process.poll() is not None:
                        self._process = None
                    else:
                        # Process still alive after termination attempt
                        self.logger.error(

                                f"Failed to terminate process for launcher '{self.launcher_id}', "
                                f"process {self._process.pid} may be orphaned"

                        )
                        # Still set to None to avoid repeated termination attempts
                        # but log the issue for debugging
                        self._process = None
                except Exception as e:
                    self.logger.error(

                            f"Exception during process cleanup for launcher '{self.launcher_id}': {e}, "
                            "process may be orphaned"

                    )
                    # Set to None to avoid repeated attempts but log the failure
                    self._process = None
            else:
                # Process already terminated
                self._process = None

    def request_stop(self) -> bool:
        """Override to handle process termination.

        Always terminates the subprocess if running, regardless of parent's stop state.
        This prevents zombie processes if the worker is already in stopping state.
        """
        # CRITICAL: Always terminate subprocess first, before calling parent
        # This prevents resource leaks even if parent is already stopping
        if self._process and self._process.poll() is None:
            self._terminate_process()

        # Then call parent implementation for state management
        return super().request_stop()
