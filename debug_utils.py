#!/usr/bin/env python3
"""Enhanced debugging utilities for ShotBot.

This module provides comprehensive debugging tools including timing profilers,
state tracking, and system diagnostics.
"""

from __future__ import annotations

# Standard library imports
import json
import os
import platform
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

# Local application imports
from logging_mixin import LoggingMixin, get_module_logger


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator

# Module-level logger for static methods
logger = get_module_logger(__name__)

# Debug levels from environment
DEBUG_LEVEL = os.environ.get("SHOTBOT_DEBUG_LEVEL", "0")
DEBUG_TIMING = "1" in DEBUG_LEVEL or "t" in DEBUG_LEVEL.lower()
DEBUG_IO = "2" in DEBUG_LEVEL or "i" in DEBUG_LEVEL.lower()
DEBUG_STATE = "3" in DEBUG_LEVEL or "s" in DEBUG_LEVEL.lower()
DEBUG_TRACE = "4" in DEBUG_LEVEL or "x" in DEBUG_LEVEL.lower()
DEBUG_ALL = DEBUG_LEVEL.lower() in ("all", "9", "verbose")
DEBUG_VERBOSE = (
    os.environ.get("SHOTBOT_DEBUG_VERBOSE", "").lower() in ("1", "true", "yes")
    or DEBUG_ALL
)


class TimingProfiler(LoggingMixin):
    """Track and report timing for operations."""

    def __init__(self, name: str = "default") -> None:
        """Initialize timing profiler.

        Args:
            name: Name for this profiler instance
        """
        super().__init__()
        self.name = name
        self.timings: dict[str, list[float]] = {}
        self.active_timers: dict[str, float] = {}
        self.enabled = DEBUG_TIMING or DEBUG_ALL

    @contextmanager
    def measure(self, operation_name: str) -> Generator[None, None, None]:
        """Context manager to measure operation timing.

        Args:
            operation_name: Name of the operation to measure
        """
        if not self.enabled:
            yield
            return

        start = time.perf_counter()
        self.active_timers[operation_name] = start

        try:
            yield
            elapsed = time.perf_counter() - start

            # Store timing
            if operation_name not in self.timings:
                self.timings[operation_name] = []
            self.timings[operation_name].append(elapsed)

            # Log if verbose
            if DEBUG_VERBOSE:
                self.logger.debug(f"⏱️ [{self.name}] {operation_name}: {elapsed:.3f}s")

        except Exception as e:
            elapsed = time.perf_counter() - start
            self.logger.error(
                f"⏱️ [{self.name}] {operation_name} FAILED after {elapsed:.3f}s: {e}",
            )
            raise
        finally:
            self.active_timers.pop(operation_name, None)

    def get_report(self) -> dict[str, dict[str, int | float]]:
        """Get timing report.

        Returns:
            Dictionary with timing statistics
        """
        report: dict[str, dict[str, int | float]] = {}
        for operation, times in self.timings.items():
            if times:
                report[operation] = {
                    "count": len(times),
                    "total": sum(times),
                    "average": sum(times) / len(times),
                    "min": min(times),
                    "max": max(times),
                    "last": times[-1],
                }
        return report

    def log_report(self) -> None:
        """Log timing report."""
        if not self.timings:
            return

        self.logger.info(f"\n{'=' * 60}")
        self.logger.info(f"Timing Report for {self.name}")
        self.logger.info(f"{'=' * 60}")

        for operation, stats in self.get_report().items():
            self.logger.info(

                    f"{operation}: "
                    f"avg={stats['average']:.3f}s, "
                    f"total={stats['total']:.3f}s, "
                    f"count={stats['count']}"

            )


class ProcessStateTracker(LoggingMixin):
    """Track process state transitions for debugging."""

    STATES: ClassVar[list[str]] = [
        "INIT",
        "STARTING",
        "DRAINING",
        "WAITING_MARKER",
        "READY",
        "EXECUTING",
        "READING",
        "DEAD",
        "RESTARTING",
        "ERROR",
    ]

    def __init__(self) -> None:
        """Initialize state tracker."""
        super().__init__()
        self.states: dict[str, str] = {}
        self.state_history: dict[str, list[tuple[float, str, str, str]]] = {}
        self.state_timings: dict[str, dict[str, float]] = {}
        self.enabled = DEBUG_STATE or DEBUG_ALL

    def transition(self, session_id: str, to_state: str, reason: str = "") -> None:
        """Record state transition.

        Args:
            session_id: Session identifier
            to_state: New state
            reason: Optional reason for transition
        """
        if not self.enabled:
            return

        from_state = self.states.get(session_id, "UNKNOWN")
        timestamp = time.time()

        # Record transition
        self.states[session_id] = to_state

        # Record history
        if session_id not in self.state_history:
            self.state_history[session_id] = []
        self.state_history[session_id].append((timestamp, from_state, to_state, reason))

        # Track timing
        if session_id not in self.state_timings:
            self.state_timings[session_id] = {}

        # Calculate time in previous state
        if from_state in self.state_timings[session_id]:
            duration = timestamp - self.state_timings[session_id][from_state]
            if DEBUG_VERBOSE:
                self.logger.debug(

                        f"[{session_id}] STATE: {from_state} → {to_state} "
                        f"(duration: {duration:.2f}s) {f'[{reason}]' if reason else ''}"

                )
        elif DEBUG_VERBOSE:
            self.logger.debug(

                    f"[{session_id}] STATE: {from_state} → {to_state} "
                    f"{f'[{reason}]' if reason else ''}"

            )

        # Record new state start time
        self.state_timings[session_id][to_state] = timestamp

    def get_current_state(self, session_id: str) -> str:
        """Get current state for session.

        Args:
            session_id: Session identifier

        Returns:
            Current state or 'UNKNOWN'
        """
        return self.states.get(session_id, "UNKNOWN")

    def get_history(self, session_id: str) -> list[tuple[float, str, str, str]]:
        """Get state history for session.

        Args:
            session_id: Session identifier

        Returns:
            List of (timestamp, from_state, to_state, reason) tuples
        """
        return self.state_history.get(session_id, [])


class SystemDiagnostics(LoggingMixin):
    """Capture and log system diagnostic information."""

    @staticmethod
    def get_system_info() -> dict[
        str, str | int | float | list[str] | dict[str, float]
    ]:
        """Get comprehensive system information.

        Returns:
            Dictionary with system information (values can be primitives, lists, or nested dicts)
        """
        info: dict[str, str | int | float | list[str] | dict[str, float]] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "platform": platform.platform(),
            "python": sys.version,
            "python_executable": sys.executable,
            "hostname": socket.gethostname(),
            "user": os.environ.get("USER", "unknown"),
            "cwd": str(Path.cwd()),
            "pid": os.getpid(),
        }

        # Add PATH (first few entries)
        path_entries = os.environ.get("PATH", "").split(":")
        info["PATH"] = path_entries[:5] if path_entries else []

        # File descriptor count (Linux only)
        if Path("/proc/self/fd").exists():
            try:
                info["fd_count"] = len(list(Path("/proc/self/fd").iterdir()))
            except (OSError, PermissionError):
                info["fd_count"] = "N/A"

        # Memory info (if psutil available)
        try:
            # Third-party imports
            import psutil

            process = psutil.Process()
            mem_info = process.memory_info()
            rss_bytes = cast(
                "int", mem_info.rss
            )  # psutil returns int, cast for type checker
            info["memory"] = {
                "rss_mb": rss_bytes / 1024 / 1024,
                "percent": process.memory_percent(),
            }
        except ImportError:
            pass

        # ulimits (Unix only)
        if os.name == "posix":
            try:
                result = subprocess.run(
                    ["ulimit", "-a"],
                    check=False, capture_output=True,
                    text=True,
                    timeout=1,
                )
                if result.returncode == 0:
                    info["ulimits"] = result.stdout.split("\n")[:5]
            except (subprocess.SubprocessError, OSError):
                pass

        return info

    @staticmethod
    def log_system_info() -> None:
        """Log system information."""
        info = SystemDiagnostics.get_system_info()

        logger.info("\n" + "=" * 60)
        logger.info("System Diagnostics")
        logger.info("=" * 60)
        logger.info(json.dumps(info, indent=2))
        logger.info("=" * 60 + "\n")


class IOBufferInspector(LoggingMixin):
    """Inspect and debug I/O buffers."""

    @staticmethod
    def inspect(data: str, context: str, session_id: str = "") -> None:
        """Inspect buffer contents.

        Args:
            data: Buffer data to inspect
            context: Context description
            session_id: Optional session identifier
        """
        if not (DEBUG_IO or DEBUG_ALL):
            return

        if not data:
            logger.debug(f"[{session_id}] Buffer {context}: <empty>")
            return

        lines = data.count("\n")
        non_printable = sum(1 for c in data if ord(c) < 32 and c not in "\n\r\t")

        logger.debug(

                f"[{session_id}] Buffer {context}: "
                f"{len(data)} bytes, {lines} lines, {non_printable} non-printable"

        )

        # Show preview of data
        if DEBUG_VERBOSE:
            # First 100 chars
            preview = data[:100].encode("unicode_escape").decode("ascii")
            logger.debug(f"[{session_id}] └─ Preview: {preview}")

            # Show any markers or special strings
            if "SHOTBOT_INIT" in data:
                logger.debug(f"[{session_id}] └─ Contains initialization marker")
            if "error" in data.lower():
                logger.debug(f"[{session_id}] └─ Contains error message")


class CommandTracer(LoggingMixin):
    """Trace command execution."""

    @staticmethod
    def trace(command: str, session_id: str = "") -> None:
        """Trace command execution.

        Args:
            command: Command being executed
            session_id: Optional session identifier
        """
        if not (DEBUG_TRACE or DEBUG_ALL):
            return

        # Truncate long commands
        cmd_preview = command[:200] + "..." if len(command) > 200 else command

        logger.debug(f"[{session_id}] EXEC: {cmd_preview}")

        # Analyze command
        if DEBUG_VERBOSE:
            if "ws" in command:
                logger.debug(f"[{session_id}] └─ Workspace command detected")
            if "|" in command:
                pipes = command.count("|")
                logger.debug(f"[{session_id}] └─ Pipeline with {pipes} pipe(s)")
            if "&&" in command or ";" in command:
                logger.debug(f"[{session_id}] └─ Compound command")


class DeadlockDetector(LoggingMixin):
    """Detect potential deadlocks."""

    def __init__(self) -> None:
        """Initialize deadlock detector."""
        super().__init__()
        self.waiting_on: dict[str, tuple[str, float]] = {}
        self.enabled = DEBUG_ALL

    def waiting(self, session_id: str, resource: str) -> None:
        """Record that session is waiting for resource.

        Args:
            session_id: Session identifier
            resource: Resource being waited for
        """
        if not self.enabled:
            return

        self.waiting_on[session_id] = (resource, time.time())

        # Check for long waits
        self._check_long_waits()

    def done_waiting(self, session_id: str) -> None:
        """Record that session is done waiting.

        Args:
            session_id: Session identifier
        """
        if not self.enabled:
            return

        if session_id in self.waiting_on:
            resource, start_time = self.waiting_on[session_id]
            wait_time = time.time() - start_time
            if wait_time > 1.0:
                self.logger.debug(
                    f"[{session_id}] Waited {wait_time:.1f}s for {resource}"
                )
            del self.waiting_on[session_id]

    def _check_long_waits(self) -> None:
        """Check for sessions waiting too long."""
        current_time = time.time()
        for session_id, (resource, start_time) in list(self.waiting_on.items()):
            wait_time = current_time - start_time
            if wait_time > 5.0:
                self.logger.warning(
                    f"⚠️ POTENTIAL DEADLOCK: [{session_id}] waiting {wait_time:.1f}s for {resource}",
                )
            elif wait_time > 2.0 and DEBUG_VERBOSE:
                self.logger.debug(
                    f"[{session_id}] Still waiting for {resource} ({wait_time:.1f}s)",
                )


# Global instances
timing_profiler = TimingProfiler("global")
state_tracker = ProcessStateTracker()
deadlock_detector = DeadlockDetector()


def setup_enhanced_debugging() -> None:
    """Setup enhanced debugging based on environment variables."""
    if DEBUG_VERBOSE or DEBUG_ALL:
        logger.info("Enhanced debugging enabled")
        logger.info(f"Debug level: {DEBUG_LEVEL}")
        logger.info(f"  Timing: {DEBUG_TIMING}")
        logger.info(f"  I/O: {DEBUG_IO}")
        logger.info(f"  State: {DEBUG_STATE}")
        logger.info(f"  Trace: {DEBUG_TRACE}")

        # Log system info if verbose
        if DEBUG_ALL:
            SystemDiagnostics.log_system_info()


# Usage examples in docstring
"""
Usage Examples:

# Enable all debugging
export SHOTBOT_DEBUG_LEVEL=all

# Enable specific debugging
export SHOTBOT_DEBUG_LEVEL=13  # Timing + State
export SHOTBOT_DEBUG_LEVEL=t   # Timing only
export SHOTBOT_DEBUG_LEVEL=tsx  # Timing + State + Trace

# In code:
from debug_utils import timing_profiler, state_tracker, CommandTracer
from logging_mixin import LoggingMixin

# Time an operation
with timing_profiler.measure("database_query"):
    result = perform_query()

# Track state transitions
state_tracker.transition("session_1", "EXECUTING", "Running ws command")

# Trace commands
CommandTracer.trace("ws -sg | grep pattern", "session_1")

# Get timing report
timing_profiler.log_report()
"""
