"""Process verification for launched applications.

This module provides utilities to verify that launched GUI applications actually started
by checking for PID files written by the terminal dispatcher and verifying the process exists.

Thread Safety:
    - All methods are thread-safe and can be called from worker threads
    - Uses only read-only filesystem operations and psutil checks
    - No shared mutable state between instances
"""

from __future__ import annotations

import time
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, final

import psutil

if TYPE_CHECKING:
    from logging_mixin import ContextualLogger


class ProcessVerificationError(Exception):
    """Raised when process verification fails."""

    pass


@final
class ProcessVerifier:
    """Verify that launched processes actually started.

    This class polls for PID files written by terminal_dispatcher.sh and verifies
    that the launched process exists using psutil.

    Attributes:
        VERIFICATION_TIMEOUT_SEC: Maximum time to wait for process to start
        POLL_INTERVAL_SEC: How often to check for PID file
        PID_FILE_DIR: Directory where dispatcher writes PID files
    """

    # Configuration
    VERIFICATION_TIMEOUT_SEC: float = 5.0  # How long to wait for process
    POLL_INTERVAL_SEC: float = 0.2  # How often to check
    PID_FILE_DIR: str = "/tmp/shotbot_pids"  # Where dispatcher writes PIDs

    def __init__(self, logger: Logger | ContextualLogger) -> None:
        """Initialize process verifier.

        Args:
            logger: Logger instance for debug output (standard Logger or ContextualLogger)
        """
        self.logger: Logger | ContextualLogger = logger
        self._ensure_pid_dir()

    def _ensure_pid_dir(self) -> None:
        """Create PID directory if it doesn't exist."""
        try:
            Path(self.PID_FILE_DIR).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.logger.warning(f"Could not create PID directory {self.PID_FILE_DIR}: {e}")

    def wait_for_process(
        self,
        command: str,
        timeout_sec: float | None = None,
    ) -> tuple[bool, str]:
        """Wait for launched process to start and verify it exists.

        Args:
            command: The command that was executed
            timeout_sec: How long to wait (default: VERIFICATION_TIMEOUT_SEC)

        Returns:
            (success, message) tuple
            - success: True if process verified, False if timeout/error
            - message: Description of result
        """
        if timeout_sec is None:
            timeout_sec = self.VERIFICATION_TIMEOUT_SEC

        # Check if this is a GUI app (needs verification)
        if not self._is_gui_app(command):
            return True, "Non-GUI command (no verification needed)"

        # Extract app name for PID file lookup
        app_name = self._extract_app_name(command)
        if not app_name:
            return True, "Could not extract app name (skipping verification)"

        # Wait for PID file to appear
        pid = self._wait_for_pid_file(app_name, timeout_sec)
        if pid is None:
            msg = f"PID file not found after {timeout_sec}s"
            self.logger.warning(f"Process verification failed: {msg}")
            return False, msg

        # Verify process exists
        if self._verify_process_exists(pid):
            msg = f"Process verified (PID: {pid})"
            self.logger.info(f"✓ {msg}")
            return True, msg
        else:
            msg = f"Process {pid} not found (crashed immediately?)"
            self.logger.warning(f"Process verification failed: {msg}")
            return False, msg

    def _is_gui_app(self, command: str) -> bool:
        """Check if command launches a GUI app that needs verification.

        Args:
            command: The command string

        Returns:
            True if this is a GUI app
        """
        # GUI apps we want to verify
        gui_apps = ["nuke", "3de", "maya", "rv", "houdini"]
        cmd_lower = command.lower()
        return any(app in cmd_lower for app in gui_apps)

    def _extract_app_name(self, command: str) -> str | None:
        """Extract app name from command for PID file lookup.

        Args:
            command: The command string

        Returns:
            App name (e.g., "nuke", "3de") or None
        """
        # Look for known app names
        gui_apps = ["nuke", "3de", "maya", "rv", "houdini"]
        cmd_lower = command.lower()

        for app in gui_apps:
            if app in cmd_lower:
                return app

        return None

    def _wait_for_pid_file(
        self,
        app_name: str,
        timeout_sec: float,
    ) -> int | None:
        """Wait for PID file to appear and read PID.

        Args:
            app_name: Name of app (e.g., "nuke")
            timeout_sec: How long to wait

        Returns:
            PID if found, None if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout_sec:
            # Look for latest PID file for this app
            # Format: /tmp/shotbot_pids/<app_name>_<timestamp>.pid
            pid_dir = Path(self.PID_FILE_DIR)
            if not pid_dir.exists():
                time.sleep(self.POLL_INTERVAL_SEC)
                continue

            pid_files = list(pid_dir.glob(f"{app_name}_*.pid"))

            if pid_files:
                # Use most recent file
                latest_pid_file = max(pid_files, key=lambda p: p.stat().st_mtime)

                try:
                    pid_str = latest_pid_file.read_text().strip()
                    pid = int(pid_str)
                    self.logger.debug(f"Found PID file: {latest_pid_file} -> {pid}")
                    return pid
                except (ValueError, OSError) as e:
                    self.logger.warning(f"Could not read PID file {latest_pid_file}: {e}")

            # Poll
            time.sleep(self.POLL_INTERVAL_SEC)

        return None

    def _verify_process_exists(self, pid: int) -> bool:
        """Verify that process with given PID exists.

        Args:
            pid: Process ID to check

        Returns:
            True if process exists
        """
        try:
            return psutil.pid_exists(pid)
        except Exception as e:
            self.logger.warning(f"Error checking PID {pid}: {e}")
            return False

    @staticmethod
    def cleanup_old_pid_files(max_age_hours: int = 24) -> None:
        """Clean up old PID files (call periodically).

        Args:
            max_age_hours: Remove files older than this
        """
        pid_dir = Path(ProcessVerifier.PID_FILE_DIR)
        if not pid_dir.exists():
            return

        cutoff_time = time.time() - (max_age_hours * 3600)

        for pid_file in pid_dir.glob("*.pid"):
            try:
                if pid_file.stat().st_mtime < cutoff_time:
                    pid_file.unlink()
            except OSError:
                pass  # Ignore errors during cleanup
