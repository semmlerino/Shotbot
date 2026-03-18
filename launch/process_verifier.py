"""Process verification for launched applications.

This module provides utilities to verify that launched GUI applications actually started
by checking for PID files written by the terminal dispatcher and verifying the process exists.

Thread Safety:
    - All methods are thread-safe and can be called from worker threads
    - Uses only read-only filesystem operations and psutil checks
    - No shared mutable state between instances
"""

from __future__ import annotations

import re
import time
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

import psutil


if TYPE_CHECKING:
    from logging_mixin import ContextualLogger


class ProcessVerificationError(Exception):
    """Raised when process verification fails."""



@final
class ProcessVerifier:
    """Verify that launched processes actually started.

    This class polls for PID files and verifies that the launched process
    exists using psutil.

    Attributes:
        VERIFICATION_TIMEOUT_SEC: Maximum time to wait for process to start
        POLL_INTERVAL_SEC: How often to check for PID file
        PID_FILE_DIR: Directory where PID files are written

    """

    # Configuration
    # CRITICAL FIX: Increased from 5.0 to 30.0 to prevent command double-execution
    # GUI apps like Nuke/Maya can take 8-15 seconds to write PID files
    # Previously, timeout would trigger fallback retry, launching duplicate instances
    VERIFICATION_TIMEOUT_SEC: float = 30.0  # How long to wait for process
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
        except OSError:
            self.logger.warning(f"Could not create PID directory {self.PID_FILE_DIR}", exc_info=True)

    def wait_for_process(
        self,
        command: str,
        timeout_sec: float | None = None,
        enqueue_time: float | None = None,
    ) -> tuple[bool, str]:
        """Wait for launched process to start and verify it exists.

        Args:
            command: The command that was executed
            timeout_sec: How long to wait (default: VERIFICATION_TIMEOUT_SEC)
            enqueue_time: Time when command was enqueued (for filtering stale PID files).
                         If None, uses current time minus timeout (conservative filter).

        Returns:
            (success, message) tuple
            - success: True if process verified, False if timeout/error
            - message: Description of result

        """
        if timeout_sec is None:
            timeout_sec = self.VERIFICATION_TIMEOUT_SEC

        # If no enqueue time provided, use conservative estimate
        # (current time minus timeout ensures we don't reject fresh PIDs)
        if enqueue_time is None:
            enqueue_time = time.time() - timeout_sec

        # Check if this is a GUI app (needs verification)
        if not self._is_gui_app(command):
            return True, "Non-GUI command (no verification needed)"

        # Extract app name for PID file lookup
        app_name = self._extract_app_name(command)
        if not app_name:
            return True, "Could not extract app name (skipping verification)"

        # Try PID file method first
        pid = self._wait_for_pid_file(app_name, timeout_sec / 2, enqueue_time)

        # Fallback: use psutil process scanning if PID file not found
        if pid is None:
            self.logger.debug("PID file not found, falling back to process scanning")
            pid = self._scan_for_process(app_name, enqueue_time, timeout_sec / 2)

        if pid is None:
            msg = f"Process not found after {timeout_sec}s"
            self.logger.warning(f"Process verification failed: {msg}")
            return False, msg

        # Verify process exists
        if self._verify_process_exists(pid):
            msg = f"Process verified (PID: {pid})"
            self.logger.info(f"✓ {msg}")
            return True, msg
        msg = f"Process {pid} not found (crashed immediately?)"
        self.logger.warning(f"Process verification failed: {msg}")
        return False, msg

    def scan_for_process(
        self,
        app_name: str,
        enqueue_time: float,
        timeout_sec: float | None = None,
        poll_interval_sec: float | None = None,
    ) -> tuple[bool, int | None, str]:
        """Scan for a running process by app name using psutil.

        This is the primary verification method when PID files are not available.
        It scans running processes and looks for ones matching the app name that
        were started after enqueue_time.

        Args:
            app_name: Name of the application (e.g., "nuke", "maya", "3de")
            enqueue_time: Time when command was enqueued (processes started before
                         this time are ignored)
            timeout_sec: How long to wait (default: VERIFICATION_TIMEOUT_SEC)
            poll_interval_sec: How often to scan (default: POLL_INTERVAL_SEC)

        Returns:
            (success, pid, message) tuple
            - success: True if process found, False if timeout
            - pid: Process ID if found, None if not
            - message: Description of result

        """
        if timeout_sec is None:
            timeout_sec = self.VERIFICATION_TIMEOUT_SEC
        if poll_interval_sec is None:
            poll_interval_sec = self.POLL_INTERVAL_SEC

        pid = self._scan_for_process(app_name, enqueue_time, timeout_sec, poll_interval_sec)

        if pid is not None:
            msg = f"{app_name} started (PID: {pid})"
            self.logger.info(f"✓ {msg}")
            return True, pid, msg
        msg = f"Could not find {app_name} process after {timeout_sec}s"
        self.logger.warning(msg)
        return False, None, msg

    def _scan_for_process(
        self,
        app_name: str,
        enqueue_time: float,
        timeout_sec: float,
        poll_interval_sec: float | None = None,
    ) -> int | None:
        """Internal method to scan for process using psutil.

        Args:
            app_name: Name of app to find
            enqueue_time: Ignore processes started before this time
            timeout_sec: How long to wait
            poll_interval_sec: How often to scan (default: POLL_INTERVAL_SEC)

        Returns:
            PID if found, None if timeout

        """
        if poll_interval_sec is None:
            poll_interval_sec = self.POLL_INTERVAL_SEC

        # Map app names to possible process names
        # (handles cases where process name differs from command)
        app_process_names: dict[str, list[str]] = {
            "nuke": ["nuke", "nuke.bin", "nukex", "nukex.bin", "nukestudio"],
            "maya": ["maya", "maya.bin", "mayapy"],
            "3de": ["3de", "3dequalizer", "tde4"],
            "rv": ["rv", "rv.bin", "rvio"],
            "houdini": ["houdini", "houdinifx", "hython"],
        }
        search_names = app_process_names.get(app_name.lower(), [app_name.lower()])

        # Allow some clock skew tolerance (process may have started slightly before enqueue)
        clock_skew_tolerance = 2.0
        cutoff_time = enqueue_time - clock_skew_tolerance

        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout_sec:
            for proc in psutil.process_iter(["name", "create_time", "pid"]):
                try:
                    proc_name = (proc.info.get("name") or "").lower()
                    create_time = cast("float", proc.info.get("create_time", 0))
                    proc_pid = cast("int", proc.info.get("pid", 0))

                    # Check if process name matches and was created after our command
                    if any(name in proc_name for name in search_names):
                        if create_time >= cutoff_time:
                            self.logger.debug(
                                f"Found process: {proc_name} (PID: {proc_pid}, "
                                f"created: {create_time:.1f}, cutoff: {cutoff_time:.1f})"
                            )
                            return proc_pid
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process disappeared or we can't access it - skip
                    continue

            time.sleep(poll_interval_sec)

        return None

    def _is_gui_app(self, command: str) -> bool:
        """Check if command launches a GUI app that needs verification.

        Args:
            command: The command string

        Returns:
            True if this is a GUI app

        Note:
            Uses word boundaries to avoid false positives (e.g., "rv" in "/srv/data")

        """
        # GUI apps we want to verify
        gui_apps = ["nuke", "3de", "maya", "rv", "houdini"]
        cmd_lower = command.lower()

        # Use word boundaries to avoid false matches like "rv" in "/srv/"
        return any(re.search(rf"\b{re.escape(app)}\b", cmd_lower) for app in gui_apps)

    def _extract_app_name(self, command: str) -> str | None:
        """Extract app name from command for PID file lookup.

        Args:
            command: The command string

        Returns:
            App name (e.g., "nuke", "3de") or None

        Note:
            Uses word boundaries to avoid false matches (e.g., "rv" in "/srv/data")

        """
        # Look for known app names
        gui_apps = ["nuke", "3de", "maya", "rv", "houdini"]
        cmd_lower = command.lower()

        # Use word boundaries to avoid false matches
        for app in gui_apps:
            if re.search(rf"\b{re.escape(app)}\b", cmd_lower):
                return app

        return None

    def _wait_for_pid_file(
        self,
        app_name: str,
        timeout_sec: float,
        enqueue_time: float,
    ) -> int | None:
        """Wait for PID file to appear and read PID.

        Args:
            app_name: Name of app (e.g., "nuke")
            timeout_sec: How long to wait
            enqueue_time: Time when command was enqueued (filters stale PID files)

        Returns:
            PID if found, None if timeout

        Note:
            Only considers PID files created after enqueue_time to avoid accepting
            stale PID files from previous launches.

            Uses monotonic time for timeout loop to prevent clock changes from
            affecting the wait duration.

        """
        # Use monotonic time for timeout to avoid clock skew issues
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout_sec:
            # Look for latest PID file for this app
            # Format: /tmp/shotbot_pids/<app_name>_<timestamp>.pid
            pid_dir = Path(self.PID_FILE_DIR)
            if not pid_dir.exists():
                time.sleep(self.POLL_INTERVAL_SEC)
                continue

            pid_files = list(pid_dir.glob(f"{app_name}_*.pid"))

            # CRITICAL BUG FIX #21: Cache stat results to prevent race condition
            # Race scenario: stat() called twice (filter + max) → file deleted between calls → FileNotFoundError
            # Solution: Call stat() once per file, cache results, filter out errors
            clock_skew_tolerance = 2.0
            file_stats: list[tuple[Path, float]] = []

            for f in pid_files:
                try:
                    mtime = f.stat().st_mtime
                    # Filter out stale PID files (created before command was enqueued)
                    if mtime >= enqueue_time - clock_skew_tolerance:
                        file_stats.append((f, mtime))
                except OSError:
                    # File deleted or inaccessible - skip it
                    continue

            if file_stats:
                # Use most recent file (use cached mtime instead of calling stat() again)
                latest_pid_file, _ = max(file_stats, key=lambda x: x[1])

                try:
                    pid_str = latest_pid_file.read_text().strip()
                    pid = int(pid_str)
                    self.logger.debug(f"Found PID file: {latest_pid_file} -> {pid}")
                    return pid
                except (ValueError, OSError):
                    self.logger.warning(f"Could not read PID file {latest_pid_file}", exc_info=True)

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
        except Exception:  # noqa: BLE001
            self.logger.warning(f"Error checking PID {pid}", exc_info=True)
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
