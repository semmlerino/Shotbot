"""Thread diagnostics for pre-termination analysis and metrics.

This module provides infrastructure for capturing thread state before abandonment,
logging structured abandonment events, and tracking metrics for monitoring.

The goal is to replace raw terminate() calls with observable abandonment that:
1. Captures stack traces for debugging
2. Records metrics for monitoring
3. Allows threads to be marked as abandoned rather than hard-killed
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import QThread


if TYPE_CHECKING:
    from types import FrameType

logger = logging.getLogger(__name__)


@dataclass
class ThreadDiagnosticReport:
    """Diagnostic information captured before thread abandonment.

    Attributes:
        thread_id: Native thread identifier
        thread_name: Human-readable thread name
        stack_trace: List of formatted stack trace lines
        state: Thread state (e.g., "RUNNING", "STOPPING")
        time_running_seconds: How long the thread has been running
        abandon_reason: Why the thread is being abandoned
        timestamp: When this report was created

    """

    thread_id: int
    thread_name: str
    stack_trace: list[str]
    state: str
    time_running_seconds: float
    abandon_reason: str
    timestamp: float = field(default_factory=time.time)

    def format_summary(self) -> str:
        """Format a concise summary for logging."""
        stack_preview = ""
        if self.stack_trace:
            # Show last 3 stack frames
            stack_preview = "\n".join(self.stack_trace[-3:])

        return (
            f"Thread: {self.thread_name} (id={self.thread_id})\n"
            f"State: {self.state}\n"
            f"Runtime: {self.time_running_seconds:.1f}s\n"
            f"Reason: {self.abandon_reason}\n"
            f"Stack:\n{stack_preview}"
        )


class ThreadDiagnostics:
    """Centralized thread diagnostics for pre-termination analysis.

    This class provides static methods for:
    - Capturing thread state (stack traces, state, runtime)
    - Logging structured abandonment events
    - Tracking metrics for monitoring

    All methods are thread-safe via a class-level lock.
    """

    _abandonment_reports: ClassVar[list[ThreadDiagnosticReport]] = []
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # Metrics counters
    _total_captured: ClassVar[int] = 0
    _total_abandoned: ClassVar[int] = 0

    @classmethod
    def capture_thread_state(
        cls,
        thread: QThread | threading.Thread,
        start_time: float | None = None,
    ) -> ThreadDiagnosticReport:
        """Capture full diagnostic state of a thread.

        Args:
            thread: The thread to capture state from (QThread or threading.Thread)
            start_time: Optional epoch timestamp when thread started (for runtime calc)

        Returns:
            ThreadDiagnosticReport with captured state

        """
        cls._total_captured += 1

        # Get thread identity
        if isinstance(thread, threading.Thread):
            thread_id = thread.ident or 0
            thread_name = thread.name
        else:
            # QThread - use Python object id as identifier
            thread_id = id(thread)
            thread_name = thread.objectName() or f"QThread-{thread_id}"

        # Get stack trace using sys._current_frames()
        # Note: _current_frames is technically private but is the only way to get
        # stack traces for other threads without modifying them
        stack_trace: list[str] = []
        frames: dict[int, FrameType] = sys._current_frames()  # pyright: ignore[reportPrivateUsage]

        if thread_id and thread_id in frames:
            frame = frames[thread_id]
            stack_trace = traceback.format_stack(frame)
        elif isinstance(thread, threading.Thread) and thread.ident:
            # Try with native thread id
            if thread.ident in frames:
                frame = frames[thread.ident]
                stack_trace = traceback.format_stack(frame)

        # Determine thread state
        state = cls._get_thread_state(thread)

        # Calculate runtime
        time_running = time.time() - start_time if start_time else 0.0

        return ThreadDiagnosticReport(
            thread_id=thread_id,
            thread_name=thread_name,
            stack_trace=stack_trace,
            state=state,
            time_running_seconds=time_running,
            abandon_reason="",  # Set by caller via log_abandonment
        )

    @classmethod
    def _get_thread_state(cls, thread: QThread | threading.Thread) -> str:
        """Get human-readable thread state."""
        # Check for ThreadSafeWorker's get_state() method
        # ThreadSafeWorker has get_state() but QThread/Thread don't - we use hasattr
        if hasattr(thread, "get_state"):
            try:
                state = thread.get_state()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportUnknownVariableType]
                if hasattr(state, "name"):  # pyright: ignore[reportUnknownArgumentType]
                    return str(state.name)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                return str(state)  # pyright: ignore[reportUnknownArgumentType]
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Failed to get thread state via get_state()", exc_info=True
                )

        # Fallback for QThread
        if isinstance(thread, QThread):
            if thread.isFinished():
                return "FINISHED"
            if thread.isRunning():
                return "RUNNING"
            return "NOT_STARTED"

        # Fallback for threading.Thread (already narrowed by union type)
        if thread.is_alive():
            return "ALIVE"
        return "DEAD"

    @classmethod
    def log_abandonment(
        cls,
        _thread: QThread | threading.Thread,
        reason: str,
        report: ThreadDiagnosticReport,
    ) -> None:
        """Log structured abandonment event for analysis.

        Args:
            _thread: The thread being abandoned (unused, info is in report)
            reason: Human-readable reason for abandonment
            report: Pre-captured diagnostic report

        """
        report.abandon_reason = reason

        with cls._lock:
            cls._abandonment_reports.append(report)
            cls._total_abandoned += 1

        # Log structured data at WARNING level
        logger.warning(
            "THREAD ABANDONED: %s (id=%d)\n"
            "  Reason: %s\n"
            "  State: %s\n"
            "  Runtime: %.1fs\n"
            "  Stack trace:\n%s",
            report.thread_name,
            report.thread_id,
            reason,
            report.state,
            report.time_running_seconds,
            "".join(report.stack_trace[-5:])
            if report.stack_trace
            else "  <unavailable>",
        )

    @classmethod
    def get_abandonment_metrics(cls) -> dict[str, int | float | list[str]]:
        """Get metrics about abandoned threads for monitoring.

        Returns:
            Dictionary with:
            - total_captured: How many threads have been captured
            - total_abandoned: How many threads have been abandoned
            - recent_reasons: List of recent abandonment reasons (last 5)
            - avg_runtime_before_abandon: Average runtime before abandonment

        """
        with cls._lock:
            reports = cls._abandonment_reports.copy()

        if not reports:
            return {
                "total_captured": cls._total_captured,
                "total_abandoned": 0,
                "recent_reasons": [],
                "avg_runtime_before_abandon": 0.0,
            }

        return {
            "total_captured": cls._total_captured,
            "total_abandoned": len(reports),
            "recent_reasons": [r.abandon_reason for r in reports[-5:]],
            "avg_runtime_before_abandon": sum(r.time_running_seconds for r in reports)
            / len(reports),
        }

    @classmethod
    def get_recent_reports(cls, count: int = 10) -> list[ThreadDiagnosticReport]:
        """Get most recent abandonment reports.

        Args:
            count: Maximum number of reports to return

        Returns:
            List of most recent ThreadDiagnosticReport instances

        """
        with cls._lock:
            return cls._abandonment_reports[-count:]

    @classmethod
    def reset(cls) -> None:
        """Reset all state for testing.

        Clears all captured reports and resets counters.
        """
        with cls._lock:
            cls._abandonment_reports.clear()
            cls._total_captured = 0
            cls._total_abandoned = 0
