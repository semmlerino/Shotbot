"""Persistent Terminal Manager for ShotBot.

This module manages a single persistent terminal window that handles all commands,
eliminating the need to spawn new terminals for each command.
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
from pathlib import Path

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from logging_mixin import LoggingMixin


class PersistentTerminalManager(LoggingMixin, QObject):
    """Manages a single persistent terminal for all commands."""

    # Signals
    terminal_started = Signal(int)  # PID of terminal
    terminal_closed = Signal()
    command_sent = Signal(str)  # Command that was sent

    def __init__(
        self, fifo_path: str | None = None, dispatcher_path: str | None = None
    ) -> None:
        """Initialize the persistent terminal manager.

        Args:
            fifo_path: Path to the FIFO for command communication
            dispatcher_path: Path to the terminal dispatcher script
        """
        super().__init__()

        # Set up paths
        self.fifo_path = fifo_path or "/tmp/shotbot_commands.fifo"

        # Find dispatcher script relative to this module
        if dispatcher_path:
            self.dispatcher_path = dispatcher_path
        else:
            module_dir = Path(__file__).parent
            self.dispatcher_path = str(module_dir / "terminal_dispatcher.sh")

        # Terminal state
        self.terminal_pid: int | None = None
        self.terminal_process: subprocess.Popen[bytes] | None = None

        # Thread safety: Lock for serializing FIFO writes
        # This prevents byte-level corruption when multiple threads
        # call send_command() concurrently
        self._write_lock = threading.Lock()

        # Ensure FIFO exists
        if not self._ensure_fifo():
            self.logger.warning(
                f"Failed to create FIFO at {self.fifo_path}, persistent terminal may not work properly"
            )

        self.logger.info(
            f"PersistentTerminalManager initialized with FIFO: {self.fifo_path}"
        )

    def _ensure_fifo(self) -> bool:
        """Ensure the FIFO exists for command communication.

        Returns:
            True if FIFO exists or was created successfully, False otherwise
        """
        if not os.path.exists(self.fifo_path):
            try:
                # Remove any existing file first (in case it's not a FIFO)
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(self.fifo_path)

                os.mkfifo(self.fifo_path, 0o600)  # Only user can read/write
                self.logger.debug(f"Created FIFO at {self.fifo_path}")
            except OSError as e:
                self.logger.error(f"Could not create FIFO at {self.fifo_path}: {e}")
                return False

        # Verify it's actually a FIFO
        if not os.path.exists(self.fifo_path):
            self.logger.error(
                f"FIFO does not exist after creation attempt: {self.fifo_path}"
            )
            return False

        # Check if path is a FIFO using cross-platform compatible method
        try:
            file_stat = os.stat(self.fifo_path)
            if not stat.S_ISFIFO(file_stat.st_mode):
                self.logger.error(f"Path exists but is not a FIFO: {self.fifo_path}")
                return False
        except OSError as e:
            self.logger.error(f"Could not stat FIFO path {self.fifo_path}: {e}")
            return False

        return True

    def _is_dispatcher_running(self) -> bool:
        """Check if the terminal dispatcher is running and ready to read from FIFO.

        Returns:
            True if dispatcher appears to be running, False otherwise
        """
        if not os.path.exists(self.fifo_path):
            return False

        try:
            # Try to open FIFO for writing in non-blocking mode
            # If no reader is available, this will fail with ENXIO
            fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            return True
        except OSError as e:
            if e.errno == errno.ENXIO:
                # No reader available - dispatcher not running
                return False
            # Other errors might indicate different issues
            return False

    def _is_terminal_alive(self) -> bool:
        """Check if the terminal process is still running."""
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

    def _launch_terminal(self) -> bool:
        """Launch the persistent terminal with dispatcher script.

        Returns:
            True if terminal launched successfully, False otherwise
        """
        if not os.path.exists(self.dispatcher_path):
            self.logger.error(f"Dispatcher script not found: {self.dispatcher_path}")
            return False

        # Try different terminal emulators
        terminal_commands = [
            # gnome-terminal with title
            [
                "gnome-terminal",
                "--title=ShotBot Terminal",
                "--",
                "bash",
                "-i",
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
                "-i",
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
                "-i",
                self.dispatcher_path,
                self.fifo_path,
            ],
            # fallback to any available terminal
            [
                "x-terminal-emulator",
                "-e",
                "bash",
                "-i",
                self.dispatcher_path,
                self.fifo_path,
            ],
        ]

        for cmd in terminal_commands:
            try:
                self.logger.debug(f"Trying to launch terminal with: {cmd[0]}")
                self.terminal_process = subprocess.Popen(cmd, start_new_session=True)
                self.terminal_pid = self.terminal_process.pid

                # Give terminal time to start
                time.sleep(0.5)

                if self._is_terminal_alive():
                    self.logger.info(
                        f"Terminal launched successfully with PID: {self.terminal_pid}"
                    )
                    self.terminal_started.emit(self.terminal_pid)
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
        # Ensure terminal is running if requested
        if ensure_terminal and not self._is_terminal_alive():
            self.logger.info("Terminal not running, launching new instance...")
            if not self._launch_terminal():
                self.logger.error("Failed to launch terminal")
                return False
            # Increased delay to ensure dispatcher is fully initialized
            # Give terminal time to set up
            time.sleep(1.5)

        # Ensure FIFO exists before trying to use it
        if not os.path.exists(self.fifo_path):
            self.logger.warning(
                f"FIFO missing, attempting to recreate: {self.fifo_path}"
            )
            if not self._ensure_fifo():
                self.logger.error(f"Failed to recreate FIFO: {self.fifo_path}")
                return False
            # Give the terminal a moment to reconnect to the new FIFO
            time.sleep(0.2)

        # Check if dispatcher is running
        # Track if we've already attempted a restart to prevent infinite loops
        already_restarted = False

        if not self._is_dispatcher_running():
            terminal_alive = self._is_terminal_alive()
            self.logger.warning(
                (f"Terminal dispatcher not reading from FIFO {self.fifo_path}. "
                f"Terminal process alive: {terminal_alive}")
            )

            # If terminal is alive but dispatcher is dead, we need to force restart
            # This happens when the dispatcher script crashes but terminal emulator stays open
            if terminal_alive and ensure_terminal:
                self.logger.warning(
                    "Terminal process is alive but dispatcher is dead - forcing full restart"
                )
                # Force kill the terminal process (dispatcher check will skip EXIT_TERMINAL)
                if self.terminal_pid:
                    try:
                        os.kill(self.terminal_pid, signal.SIGKILL)
                        self.logger.info(f"Force killed stale terminal process {self.terminal_pid}")
                    except (ProcessLookupError, PermissionError) as e:
                        self.logger.debug(f"Could not kill terminal: {e}")

                    self.terminal_pid = None
                    self.terminal_process = None

                # Now restart (which will clean up FIFO and launch fresh)
                if self.restart_terminal():
                    self.logger.info("Terminal restarted after dispatcher failure")
                    already_restarted = True
                    time.sleep(0.5)  # Brief pause before sending command
                else:
                    self.logger.error("Failed to restart terminal after dispatcher failure")
                    return False

        # Validate command before sending
        if not command or not command.strip():
            self.logger.error("Attempted to send empty command to FIFO")
            return False

        # Check for printable ASCII characters (basic sanity check)
        try:
            command.encode("ascii")
        except UnicodeEncodeError:
            self.logger.warning(f"Command contains non-ASCII characters: {command!r}")

        # Debug logging: log command details before sending
        self.logger.debug(
            (f"Preparing to send command to FIFO:\n"
            f"  Command: {command!r}\n"
            f"  Length: {len(command)} chars\n"
            f"  FIFO: {self.fifo_path}\n"
            f"  Terminal PID: {self.terminal_pid}")
        )

        # Acquire lock to serialize FIFO writes (prevents corruption from concurrent calls)
        self.logger.debug("Acquiring write lock for FIFO...")
        with self._write_lock:
            self.logger.debug("Write lock acquired, proceeding with FIFO write")

            # Send command to FIFO using non-blocking I/O
            fifo_fd = None
            max_retries = 2

            for attempt in range(max_retries):
                try:
                    # Open FIFO in non-blocking mode to prevent hanging
                    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)

                    # Use binary mode with unbuffered I/O to prevent WSL FIFO corruption
                    # Text mode + buffering was causing byte-level corruption in WSL2 FIFOs
                    # Binary mode bypasses Python's text buffering layer and writes directly
                    with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
                        fifo_fd = None  # File object now owns the descriptor
                        # Explicitly encode as UTF-8 bytes for complete control
                        fifo.write(command.encode("utf-8"))
                        fifo.write(b"\n")
                        # No flush() needed - unbuffered mode writes immediately

                    self.logger.info(
                        f"Successfully sent command to terminal via FIFO: {command}"
                    )
                    self.logger.debug(
                        f"FIFO path: {self.fifo_path}, Terminal PID: {self.terminal_pid}"
                    )
                    self.command_sent.emit(command)
                    return True

                except OSError as e:
                    if e.errno == errno.ENOENT:
                        # FIFO doesn't exist
                        if attempt < max_retries - 1:
                            self.logger.warning(
                                f"FIFO disappeared during write, recreating (attempt {attempt + 1}/{max_retries})"
                            )
                            if self._ensure_fifo():
                                time.sleep(0.2)
                                continue
                        self.logger.error(f"Failed to send command to FIFO: {e}")
                    elif e.errno == errno.ENXIO:
                        # No reader available - terminal not running
                        if attempt == 0 and ensure_terminal and not already_restarted:
                            # Try to restart terminal once (if not already restarted above)
                            self.logger.warning(
                                "No reader available for FIFO, attempting to restart terminal..."
                            )
                            if self.restart_terminal():
                                self.logger.info(
                                    "Terminal restarted successfully, retrying command..."
                                )
                                # Increased delay to ensure dispatcher is fully initialized
                                # before sending command (prevents FIFO corruption)
                                time.sleep(1.5)  # Give terminal time to set up
                                continue  # Retry the command
                            self.logger.error("Failed to restart terminal")
                        else:
                            self.logger.warning(
                                "No reader available for FIFO (terminal_dispatcher.sh not running?)"
                            )
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
            self.send_command("EXIT_TERMINAL", ensure_terminal=False)
            # Give it time to exit gracefully
            time.sleep(0.5)
        else:
            self.logger.debug("Dispatcher not running, skipping graceful exit")

        # Force kill if still running
        if self._is_terminal_alive() and self.terminal_pid:
            try:
                self.logger.debug(f"Force killing terminal process {self.terminal_pid}")
                os.kill(self.terminal_pid, signal.SIGTERM)
                time.sleep(0.5)
                if self._is_terminal_alive():
                    os.kill(self.terminal_pid, signal.SIGKILL)
                self.logger.info(f"Force killed terminal process {self.terminal_pid}")
            except ProcessLookupError:
                pass
            except Exception as e:
                self.logger.error(f"Error killing terminal process: {e}")

        self.terminal_pid = None
        self.terminal_process = None
        self.terminal_closed.emit()
        return True

    def restart_terminal(self) -> bool:
        """Restart the persistent terminal.

        Returns:
            True if terminal was restarted successfully
        """
        self.logger.info("Restarting terminal...")

        # Close existing terminal
        self.close_terminal()
        time.sleep(0.5)

        # Clean up and recreate FIFO to prevent stale file handle issues
        self.logger.debug("Cleaning up FIFO before restart")
        if os.path.exists(self.fifo_path):
            try:
                os.unlink(self.fifo_path)
                self.logger.debug(f"Removed stale FIFO at {self.fifo_path}")
            except OSError as e:
                self.logger.warning(f"Could not remove stale FIFO: {e}")

        # Recreate FIFO
        if not self._ensure_fifo():
            self.logger.error("Failed to recreate FIFO during restart")
            return False

        # Launch new terminal
        if self._launch_terminal():
            # Give dispatcher more time to fully initialize
            # This prevents race conditions where we try to write before reader is ready
            self.logger.debug("Waiting for dispatcher to fully initialize...")
            time.sleep(1.5)

            # Verify dispatcher is actually running
            if self._is_dispatcher_running():
                self.logger.info("Terminal restarted successfully with active dispatcher")
                return True
            self.logger.warning("Terminal launched but dispatcher not responding yet")
            return True  # Terminal is up, dispatcher might just need more time

        self.logger.error("Failed to launch terminal during restart")
        return False

    def cleanup(self) -> None:
        """Clean up resources (FIFO and terminal)."""
        # Close terminal if running
        if self._is_terminal_alive():
            self.close_terminal()

        # Remove FIFO if it exists
        if os.path.exists(self.fifo_path):
            try:
                os.unlink(self.fifo_path)
                self.logger.debug(f"Removed FIFO at {self.fifo_path}")
            except OSError as e:
                self.logger.warning(f"Could not remove FIFO: {e}")

    def cleanup_fifo_only(self) -> None:
        """Clean up FIFO without closing the terminal.

        This is useful when we want to keep the terminal open
        after the application exits.
        """
        # Only remove FIFO, leave terminal running
        if os.path.exists(self.fifo_path):
            try:
                os.unlink(self.fifo_path)
                self.logger.debug(
                    f"Removed FIFO at {self.fifo_path}, terminal left running"
                )
            except OSError as e:
                self.logger.warning(f"Could not remove FIFO: {e}")

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            # Only cleanup FIFO, leave terminal running
            if hasattr(self, "fifo_path") and os.path.exists(self.fifo_path):
                os.unlink(self.fifo_path)
        except Exception:
            pass
