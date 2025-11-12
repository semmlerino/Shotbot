"""Process execution management for application launching.

This module handles process execution and management:
- Persistent terminal routing
- New terminal window launching
- Process verification
- Signal-based status reporting
"""

import logging
import subprocess
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, QTimer, Signal

from notification_manager import NotificationManager


if TYPE_CHECKING:
    from config import Config
    from persistent_terminal_manager import PersistentTerminalManager

logger = logging.getLogger(__name__)


class ProcessExecutor(QObject):
    """Executes commands via terminal or subprocess.

    This class handles the actual execution of commands, either through
    a persistent terminal manager or by spawning new terminal windows.
    It provides signal-based status reporting and handles process verification.

    Signals:
        execution_started: Emitted when command execution starts
                          Args: (timestamp: str, message: str)
        execution_progress: Emitted for progress updates
                           Args: (timestamp: str, message: str)
        execution_completed: Emitted when execution completes
                            Args: (success: bool, error_message: str)
        execution_error: Emitted on execution errors
                        Args: (timestamp: str, error_message: str)
    """

    # Signals - type annotations for clarity
    execution_started: Signal = Signal(str, str)  # timestamp, message
    execution_progress: Signal = Signal(str, str)  # timestamp, message
    execution_completed: Signal = Signal(bool, str)  # success, error_message
    execution_error: Signal = Signal(str, str)  # timestamp, error_message

    # Known GUI applications that should run in background
    GUI_APPS: Final[set[str]] = {
        "3de",
        "nuke",
        "maya",
        "rv",
        "houdini",
        "mari",
        "katana",
        "clarisse",
    }

    def __init__(
        self,
        persistent_terminal: "PersistentTerminalManager | None",
        config: "type[Config]",
        parent: QObject | None = None,
    ) -> None:
        """Initialize ProcessExecutor.

        Args:
            persistent_terminal: Optional persistent terminal manager
            config: Application configuration class
            parent: Optional Qt parent object
        """
        super().__init__(parent)
        self.persistent_terminal: PersistentTerminalManager | None = persistent_terminal
        self.config: type[Config] = config
        self.logger: logging.Logger = logger

        # Connect to persistent terminal signals if available
        if self.persistent_terminal:
            _ = self.persistent_terminal.operation_progress.connect(
                self._on_terminal_progress
            )
            _ = self.persistent_terminal.command_result.connect(
                self._on_terminal_command_result
            )

    def is_gui_app(self, app_name: str) -> bool:
        """Check if an application is a GUI application.

        Args:
            app_name: Name of the application

        Returns:
            True if the app is a GUI application that should run in background

        Notes:
            GUI apps are typically backgrounded when launched so they don't
            block the terminal. Non-GUI apps run in foreground for interactivity.
        """
        return app_name.lower() in self.GUI_APPS

    def can_use_persistent_terminal(self) -> bool:
        """Check if persistent terminal can be used.

        Returns:
            True if persistent terminal is available and enabled

        Notes:
            Checks multiple conditions:
            - Persistent terminal object exists
            - Persistent terminal is enabled in config
            - USE_PERSISTENT_TERMINAL flag is set
            - Terminal is not in fallback mode
        """
        if not self.persistent_terminal:
            return False

        if not self.config.PERSISTENT_TERMINAL_ENABLED:
            return False

        if not self.config.USE_PERSISTENT_TERMINAL:
            return False

        # Check if terminal is in fallback mode
        if self.persistent_terminal.is_fallback_mode:
            self.logger.warning("Persistent terminal is in fallback mode")
            return False

        return True

    def execute_in_persistent_terminal(
        self, command: str, app_name: str
    ) -> bool:
        """Execute command in persistent terminal (async).

        Args:
            command: Command to execute
            app_name: Application name (for logging)

        Returns:
            True if command was queued successfully

        Notes:
            - Uses async send - returns immediately
            - GUI stays responsive during execution
            - Progress and completion reported via signals
            - Dispatcher handles backgrounding of GUI apps
        """
        if not self.can_use_persistent_terminal():
            self.logger.warning("Persistent terminal not available")
            return False

        self.logger.info(
            f"Sending command to persistent terminal (async): {command}"
        )

        is_gui = self.is_gui_app(app_name)
        self.logger.debug(
            f"Command details:\n  Command: {command!r}\n  Is GUI app: {is_gui}"
        )

        # Use async send - returns immediately, GUI stays responsive
        # Progress and completion are reported via signals
        assert self.persistent_terminal is not None  # Type narrowing
        self.persistent_terminal.send_command_async(command)
        self.logger.debug("Command queued for async execution in persistent terminal")
        return True

    def execute_in_new_terminal(
        self, command: str, app_name: str, terminal: str
    ) -> bool:
        """Execute command in new terminal window.

        Args:
            command: Command to execute
            app_name: Application name (for error messages and verification)
            terminal: Terminal emulator to use (gnome-terminal, konsole, xterm, etc.)

        Returns:
            True if process spawned successfully

        Raises:
            FileNotFoundError: If terminal executable not found
            PermissionError: If insufficient permissions to execute
            OSError: If other execution errors occur

        Notes:
            - Spawns new terminal window
            - Uses bash -ilc for interactive login shell (loads workspace functions)
            - Schedules process verification after 100ms
        """
        self.logger.info(f"Launching {app_name} in new {terminal} terminal")

        # Build command for the detected terminal
        if terminal == "gnome-terminal":
            term_cmd = ["gnome-terminal", "--", "bash", "-ilc", command]
        elif terminal == "konsole":
            term_cmd = ["konsole", "-e", "bash", "-ilc", command]
        elif terminal in ["xterm", "x-terminal-emulator"]:
            term_cmd = [terminal, "-e", "bash", "-ilc", command]
        else:
            # Fallback to direct execution
            term_cmd = ["/bin/bash", "-ilc", command]

        # Spawn process
        process = subprocess.Popen(term_cmd)

        # Verify spawn after 100ms (asynchronous to avoid blocking UI)
        # Use functools.partial for safe reference capture (avoids lambda race conditions)
        QTimer.singleShot(100, partial(self.verify_spawn, process, app_name))

        return True

    def verify_spawn(self, process: subprocess.Popen[bytes], app_name: str) -> None:
        """Verify process didn't crash immediately after spawning.

        This method polls the process after a short delay to detect immediate crashes.
        If the process has already exited, it indicates a launch failure.

        Args:
            process: The subprocess.Popen object to verify
            app_name: Name of the application being launched (for error messages)

        Notes:
            - Called via QTimer.singleShot after 100ms
            - Emits error signals if process crashed
            - Shows notification on failure
        """
        exit_code = process.poll()
        if exit_code is not None:
            # Process crashed
            timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
            error_msg = f"{app_name} crashed immediately (exit code {exit_code})"

            self.execution_error.emit(timestamp, error_msg)
            self.execution_completed.emit(False, error_msg)

            NotificationManager.error(
                "Launch Failed", f"{app_name} crashed immediately"
            )
        else:
            # Process spawned successfully
            self.logger.debug(f"{app_name} process spawned successfully (PID {process.pid})")
            timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
            self.execution_progress.emit(
                timestamp, f"{app_name} started successfully (PID {process.pid})"
            )

    def _on_terminal_progress(self, operation: str, message: str) -> None:
        """Handle progress updates from persistent terminal operations.

        Args:
            operation: Name of the operation (e.g., "send_command")
            message: Progress status message

        Notes:
            - Connected to persistent_terminal.operation_progress signal
            - Forwards progress to execution_progress signal with timestamp
        """
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.execution_progress.emit(timestamp, f"[{operation}] {message}")

    def _on_terminal_command_result(self, success: bool, error_message: str) -> None:
        """Handle command result from persistent terminal operations.

        Args:
            success: Whether the command completed successfully
            error_message: Error message if failed (empty if success)

        Notes:
            - Connected to persistent_terminal.command_result signal
            - Emits execution_completed and execution_error signals as appropriate
        """
        self.execution_completed.emit(success, error_message)

        if not success:
            timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
            error_msg = f"Terminal operation failed: {error_message}"
            self.execution_error.emit(timestamp, error_msg)


