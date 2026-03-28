"""Process execution management for application launching.

This module handles process execution and management:
- New terminal window launching
- Process spawn verification (immediate crash detection)
- Signal-based status reporting
"""

import logging
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final

from PySide6.QtCore import QObject, QTimer, Signal


if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)


class ProcessExecutor(QObject):
    """Executes commands via terminal or subprocess.

    This class handles the actual execution of commands by spawning new terminal
    windows. It provides signal-based status reporting and handles process verification.

    Signals:
        execution_progress: Emitted for progress updates
                           Args: (timestamp: str, message: str)
        execution_completed: Emitted when execution completes
                            Args: (success: bool, error_message: str)
        execution_error: Emitted on execution errors
                        Args: (timestamp: str, error_message: str)
    """

    # Signals - type annotations for clarity
    execution_progress: ClassVar[Signal] = Signal(str, str)  # timestamp, message
    execution_completed: ClassVar[Signal] = Signal(bool, str)  # success, error_message
    execution_error: ClassVar[Signal] = Signal(str, str)  # timestamp, error_message

    headless_launch_warning: ClassVar[Signal] = Signal(str)  # app_name
    launch_crash_detected: ClassVar[Signal] = Signal(str)  # app_name

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

    # Zombie process reaping configuration
    # Reduced from 30s to 2s for better cleanup during high-frequency launches
    REAP_INTERVAL_MS: Final[int] = 2000  # Reap every 2 seconds

    def __init__(
        self,
        config: "type[Config]",
        parent: QObject | None = None,
    ) -> None:
        """Initialize ProcessExecutor.

        Args:
            config: Application configuration class
            parent: Optional Qt parent object

        """
        super().__init__(parent)
        self.config: type[Config] = config
        self.logger: logging.Logger = logger
        self._pending_timers: list[QTimer] = []

        # Track spawned processes to prevent zombie accumulation
        self._spawned_processes: list[subprocess.Popen[bytes]] = []

        # Periodic timer to reap finished processes
        self._reap_timer: QTimer = QTimer(self)
        self._reap_timer.setInterval(self.REAP_INTERVAL_MS)
        _ = self._reap_timer.timeout.connect(self._reap_zombie_processes)
        self._reap_timer.start()

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

    def _log_sgtk_env_vars(self) -> None:
        """Log SGTK-related environment variables for debugging.

        This helps diagnose file dialog issues caused by ShotGrid Toolkit
        environment configuration.
        """
        import os

        sgtk_vars = {
            k: v for k, v in os.environ.items() if k.startswith(("SGTK_", "SHOTGUN_"))
        }
        if sgtk_vars:
            logger.debug(f"SGTK/ShotGrid environment vars: {sgtk_vars}")
        else:
            logger.debug("No SGTK_*/SHOTGUN_* environment variables found")

        # Also log workspace-related vars that might affect context
        workspace_vars = ["SHOW", "SEQUENCE", "SHOT", "WORKSPACE_PATH", "REZ_USED"]
        ws_values = {k: os.environ.get(k, "<not set>") for k in workspace_vars}
        logger.debug(f"Workspace environment vars: {ws_values}")

    def _build_terminal_command(self, terminal: str | None, command: str) -> list[str]:
        """Build terminal-specific command list.

        Args:
            terminal: Terminal emulator name, or None for headless execution
            command: The command to execute

        Returns:
            Command list suitable for subprocess.Popen

        Notes:
            Launcher commands always use bash -ilc because the outer shell is
            responsible for studio workspace bootstrapping before any Rez command.

        """
        shell_cmd = ["/bin/bash", "-ilc", command]

        # Log the shell command for debugging file dialog issues
        logger.debug(f"Shell command: {shell_cmd}")

        if terminal == "gnome-terminal":
            return ["gnome-terminal", "--", *shell_cmd]
        if terminal == "konsole":
            return ["konsole", "-e", *shell_cmd]
        if terminal == "kitty":
            return ["kitty", *shell_cmd]
        if terminal in [
            "xterm",
            "x-terminal-emulator",
            "xfce4-terminal",
            "mate-terminal",
            "alacritty",
            "terminology",
        ]:
            # These terminals all use -e flag for command execution
            return [terminal, "-e", *shell_cmd]
        # Headless fallback: direct shell execution
        return shell_cmd

    def execute_in_new_terminal(
        self,
        command: str,
        app_name: str,
        terminal: str | None = None,
    ) -> subprocess.Popen[bytes] | None:
        """Execute command in new terminal or headless if no terminal available.

        Args:
            command: Command to execute
            app_name: Application name (for error messages and verification)
            terminal: Terminal emulator name, or None for headless execution

        Returns:
            Popen object on success, None on failure

        Notes:
            - If terminal is None, executes directly via bash (headless mode)
            - Uses bash -ilc for interactive login shell (loads workspace functions)
            - Schedules process verification after 100ms

        """
        if terminal is None:
            logger.warning(
                f"No terminal available, launching {app_name} in headless mode. "
                "If app prompts for input, it may hang."
            )
            self.headless_launch_warning.emit(app_name)
        else:
            logger.info(f"Launching {app_name} in new {terminal} terminal")

        # Log SGTK-related environment variables for debugging file dialog issues
        self._log_sgtk_env_vars()

        # Log the raw command before terminal wrapping
        logger.debug(f"Raw command to execute: {command}")

        # Build command for the detected terminal (or headless)
        term_cmd = self._build_terminal_command(terminal, command)

        # Log the final terminal command
        logger.debug(f"Final terminal command: {term_cmd}")

        try:
            # Spawn process
            process = subprocess.Popen(term_cmd)

            # Track process for zombie reaping
            self._spawned_processes.append(process)

            # Verify spawn after 100ms (asynchronous to avoid blocking UI)
            # Use a cancellable QTimer to avoid "Signal source deleted" errors
            # when ProcessExecutor is cleaned up before the timer fires
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(100)

            # Store timer reference for cleanup
            self._pending_timers.append(timer)

            # Connect with cleanup of timer from list
            def on_timeout() -> None:
                # Check if timer was removed by cleanup() - if so, skip callback
                if timer not in self._pending_timers:
                    return  # Cleanup already happened, ProcessExecutor may be deleted
                self._pending_timers.remove(timer)
                self.verify_spawn(process, app_name)
                timer.deleteLater()

            _ = timer.timeout.connect(on_timeout)
            timer.start()

            return process

        except FileNotFoundError:
            logger.exception(f"Failed to launch {app_name}: executable not found")
            return None
        except PermissionError:
            logger.exception(f"Failed to launch {app_name}: permission denied")
            return None
        except OSError:
            logger.exception(f"Failed to launch {app_name}")
            return None

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

            try:
                self.execution_error.emit(timestamp, error_msg)
                self.execution_completed.emit(False, error_msg)
            except RuntimeError:
                # Signal source deleted - object is being cleaned up
                return

            self.launch_crash_detected.emit(app_name)
        else:
            # Process spawned successfully
            logger.debug(
                f"{app_name} process spawned successfully (PID {process.pid})"
            )
            timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
            try:
                self.execution_progress.emit(
                    timestamp, f"{app_name} started successfully (PID {process.pid})"
                )
            except RuntimeError:
                # Signal source deleted - object is being cleaned up
                pass

    def _reap_zombie_processes(self) -> None:
        """Reap finished processes to prevent zombie accumulation.

        This method is called periodically via QTimer to clean up processes
        that have finished. It removes terminated processes from tracking
        to free system resources and prevent process table exhaustion.
        """
        if not self._spawned_processes:
            return

        still_running: list[subprocess.Popen[bytes]] = []
        reaped_count = 0

        for proc in self._spawned_processes:
            try:
                # poll() returns None if still running, return code if finished
                # This also reaps zombie processes (equivalent to waitpid WNOHANG)
                if proc.poll() is None:
                    still_running.append(proc)
                else:
                    reaped_count += 1
            except Exception:  # noqa: BLE001
                # Process may have been reaped by something else or invalid
                reaped_count += 1

        self._spawned_processes = still_running

        if reaped_count > 0:
            logger.debug(
                f"Reaped {reaped_count} finished processes, {len(still_running)} still running"
            )

    def cleanup(self) -> None:
        """Cleanup resources.

        This method is called before deleting the ProcessExecutor instance.
        Stops all pending timers to prevent "Signal source deleted" errors.
        """
        # Stop reap timer
        try:
            self._reap_timer.stop()
        except (RuntimeError, AttributeError):
            pass  # Timer may not exist or already deleted

        # Final reap of any remaining processes
        self._reap_zombie_processes()
        self._spawned_processes.clear()

        # Stop and clean up all pending timers
        for timer in self._pending_timers:
            try:
                # These timers are parented to this QObject, so stopping them is
                # sufficient here. Calling deleteLater() can queue a deferred
                # delete that outlives the parent and triggers double-destruction
                # during later Qt cleanup passes.
                timer.stop()
            except RuntimeError:
                pass  # Timer may already be deleted
        self._pending_timers.clear()
        if not sys.is_finalizing():
            logger.debug("ProcessExecutor cleanup completed")
