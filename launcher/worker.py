"""Worker thread for launcher command execution.

This module contains the LauncherWorker class that handles subprocess
execution in a separate thread, extracted from the original launcher_manager.py.
"""

from __future__ import annotations

# Standard library imports
import os
import shlex
import signal
import subprocess
import threading
from typing import IO, final

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from exceptions import SecurityError
from thread_safe_worker import ThreadSafeWorker
from typing_compat import override


@final
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
        parent: QObject | None = None,
    ) -> None:
        """Initialize launcher worker.

        Args:
            launcher_id: Unique identifier for this launcher
            command: Command to execute
            working_dir: Optional working directory for the command
            parent: Optional parent QObject for proper Qt cleanup
        """
        super().__init__(parent)
        self.launcher_id = launcher_id
        self.command = command
        self.working_dir = working_dir
        self._process: subprocess.Popen[bytes] | None = None
        # Thread tracking for proper cleanup
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def _sanitize_command(self, command: str) -> tuple[list[str], bool]:
        """Parse command string into argument list.

        Note: This is a single-user trusted tool in an isolated VFX environment.
        No whitelisting or injection detection per CLAUDE.md security posture.

        Args:
            command: Command string to parse

        Returns:
            Tuple of (command_list, use_shell) where use_shell is always False

        Raises:
            SecurityError: If command cannot be parsed
        """
        # Parse command into argument list
        try:
            cmd_list = shlex.split(command)

            # Never use shell=True (prevents accidental complexity)
            return cmd_list, False

        except ValueError as e:
            # If shlex.split fails, the command is malformed
            self.logger.error(f"Failed to parse command: {command[:100]}")
            raise SecurityError(
                f"Command could not be parsed: {e!s}"
            ) from e

    @override
    def do_work(self) -> None:
        """Execute the launcher command with proper lifecycle management.

        This method is called by the base class run() method and includes
        proper state management and error handling.
        """
        try:
            # Emit start signal
            try:
                self.command_started.emit(self.launcher_id, self.command)
            except RuntimeError:
                return  # Signal source deleted, abort work
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

            # Start threads to drain stdout and stderr (will be joined in cleanup)
            # Type narrowing: _process is guaranteed non-None after successful Popen()
            # Create daemon threads for stream draining - allows app exit even if stuck
            # We try to join them with timeout, but daemon ensures no blocking on exit
            self._stdout_thread = threading.Thread(
                target=drain_stream,
                args=(self._process.stdout,),
                daemon=True,
                name=f"stdout-drain-{self.launcher_id}"
            )
            self._stderr_thread = threading.Thread(
                target=drain_stream,
                args=(self._process.stderr,),
                daemon=True,
                name=f"stderr-drain-{self.launcher_id}"
            )
            self._stdout_thread.start()
            self._stderr_thread.start()

            # Monitor process with periodic checks for stop requests
            while not self.is_stop_requested():
                try:
                    # Check if process finished with timeout
                    # Type narrowing: _process is non-None throughout this loop
                    return_code = self._process.wait(timeout=1.0)
                    # Process finished normally
                    success = return_code == 0
                    self.logger.info(
                        f"Worker {id(self)} finished launcher '{self.launcher_id}' with code {return_code}",
                    )
                    try:
                        self.command_finished.emit(self.launcher_id, success, return_code)
                    except RuntimeError:
                        # Signal source deleted during shutdown
                        pass
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
                try:
                    self.command_finished.emit(self.launcher_id, False, -2)
                except RuntimeError:
                    pass  # Signal source deleted during shutdown

        except Exception as e:
            error_msg = f"Worker exception for launcher '{self.launcher_id}': {e!s}"
            self.logger.exception(error_msg)
            try:
                self.command_error.emit(self.launcher_id, error_msg)
                self.command_finished.emit(self.launcher_id, False, -1)
            except RuntimeError:
                pass  # Signal source deleted during shutdown
        finally:
            # Ensure process is cleaned up
            self._cleanup_process()

    def _terminate_process(self) -> None:
        """Safely terminate the subprocess and all children in its process group."""
        if not self._process:
            return

        try:
            # Get process group ID (same as process PID due to start_new_session=True)
            try:
                pgid = os.getpgid(self._process.pid)
            except (ProcessLookupError, PermissionError):
                # Process already dead
                return

            # Try graceful termination of entire process group
            try:
                os.killpg(pgid, signal.SIGTERM)
                self.logger.debug(f"Sent SIGTERM to process group {pgid}")
            except (ProcessLookupError, PermissionError):
                # Process group already dead or we don't have permission
                pass

            # Wait for process to terminate
            try:
                _ = self._process.wait(timeout=10)
                self.logger.debug(f"Process group {pgid} terminated gracefully")
            except subprocess.TimeoutExpired:
                # Force kill entire process group if necessary
                self.logger.warning(
                    f"Force killing process group {pgid} for launcher '{self.launcher_id}' after timeout",
                )
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                _ = self._process.wait(timeout=5)
        except Exception as e:
            self.logger.error(
                f"Error terminating process for '{self.launcher_id}': {e}"
            )

    def _cleanup_process(self) -> None:
        """Clean up process resources with force kill fallback."""
        if self._process:
            # Ensure process is terminated
            if self._process.poll() is None:
                try:
                    self._terminate_process()

                    # Wait for termination with timeout
                    try:
                        _ = self._process.wait(timeout=2)
                        self._process = None
                    except subprocess.TimeoutExpired:
                        # Defensive check: process could theoretically be None if modified externally
                        if self._process is None:  # pyright: ignore[reportUnnecessaryComparison]
                            self.logger.warning(
                                f"Process became None during termination timeout for '{self.launcher_id}'"
                            )
                            return
                        # Last resort: force kill
                        self.logger.error(
                            f"Process {self._process.pid} failed graceful termination for '{self.launcher_id}', forcing kill"
                        )
                        self._process.kill()
                        _ = self._process.wait(timeout=1)
                        self._process = None

                except Exception as e:
                    # Defensive check: process should be non-None here, but verify
                    if self._process is not None:  # pyright: ignore[reportUnnecessaryComparison]
                        self.logger.critical(
                            f"Failed to clean up process {self._process.pid} for '{self.launcher_id}': {e}, manual intervention may be required"
                        )
                        # DO NOT set to None - retain reference for monitoring/debugging
                    else:
                        self.logger.critical(
                            f"Failed to clean up process for '{self.launcher_id}': {e}, process reference lost"
                        )
            else:
                # Process already terminated
                self._process = None

        # Join drain threads (they'll exit when streams close)
        if self._stdout_thread and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=2.0)
            if self._stdout_thread.is_alive():
                self.logger.warning(
                    f"stdout drain thread still alive after 2s timeout for '{self.launcher_id}'"
                )

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2.0)
            if self._stderr_thread.is_alive():
                self.logger.warning(
                    f"stderr drain thread still alive after 2s timeout for '{self.launcher_id}'"
                )

    @override
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
