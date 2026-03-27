"""Test helpers and doubles for ShotBot test suite.

Based on UNIFIED_TESTING_GUIDE_DO_NOT_DELETE.md - provides thread-safe
test doubles and helper classes for proper Qt testing without crashes.

Key Components:
    - SignalDouble: Signal test double for non-Qt objects (re-exported from fixtures)
    - process_qt_events: Process pending Qt events (preferred over qtbot.wait)
    - Factory fixtures and helpers
    - SynchronizationHelpers: Helpers to replace time.sleep() in tests
    - cleanup_qthread_properly: Proper QThread cleanup for test hygiene

Note: ThreadSafeTestImage is available from tests.fixtures.test_doubles.
"""

from __future__ import annotations

# Standard library imports
import time
from typing import TYPE_CHECKING, Any

# Third-party imports
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QThread,
)
from PySide6.QtWidgets import QApplication

from tests.fixtures.model_fixtures import SignalDouble  # noqa: F401 (re-export)

# Import canonical doubles - these are the recommended implementations
from tests.fixtures.process_fixtures import (
    simulate_work_without_sleep,  # noqa: F401 (re-export from canonical location)
)


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    # Lazy import to avoid circular dependency (test_doubles imports from synchronization)


def process_qt_events(duration_ms: int = 5, iterations: int = 2) -> None:
    """Process pending Qt events.

    This helper processes Qt events in multiple iterations to ensure
    all pending events are handled. Use this instead of qtbot.wait(1)
    for event processing.

    NOTE: This does NOT flush DeferredDelete events. For end-of-test cleanup
    that includes DeferredDelete flushing, use the qt_cleanup fixture.

    Args:
        duration_ms: Maximum time to spend processing events per iteration.
        iterations: Number of event processing rounds.

    """
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, duration_ms)


# SignalDouble is now imported from tests.fixtures.test_doubles (see imports above)


# ---------------------------------------------------------------------------
# Synchronization helpers (migrated from tests/helpers/synchronization.py)
# ---------------------------------------------------------------------------


class SynchronizationHelpers:
    """Helper methods for proper test synchronization without time.sleep()."""

    @staticmethod
    def wait_for_condition(
        condition: Callable[[], bool],
        timeout_ms: int = 1000,
        poll_interval_ms: int = 10,
    ) -> bool:
        """Wait for a condition to become true with polling.

        Args:
            condition: Function that returns True when condition is met
            timeout_ms: Maximum time to wait in milliseconds
            poll_interval_ms: How often to check condition in milliseconds

        Returns:
            True if condition was met, False if timeout

        Example:
            # Instead of: time.sleep(0.1)
            # Use: wait_for_condition(lambda: widget.isVisible(), timeout_ms=100)

        """
        start_time = time.perf_counter()
        timeout_sec = timeout_ms / 1000.0
        poll_interval_sec = poll_interval_ms / 1000.0

        while time.perf_counter() - start_time < timeout_sec:
            if condition():
                return True
            time.sleep(poll_interval_sec)  # Small sleep for polling

        return False


# simulate_work_without_sleep is imported from process_doubles (canonical location)


# ---------------------------------------------------------------------------
# QThread cleanup helpers (migrated from tests/helpers/qt_thread_cleanup.py)
# ---------------------------------------------------------------------------


def cleanup_qthread_properly(
    thread: QThread,
    signal_handlers: Sequence[tuple[Any, Callable]] | None = None,
    wait_timeout_ms: int = 5000,
) -> None:
    """Properly clean up a QThread to prevent Qt C++ object accumulation.

    This function implements the complete cleanup sequence required to prevent
    Qt objects from accumulating across tests, which causes segfaults in large
    test suites when run serially.

    Args:
        thread: The QThread instance to clean up
        signal_handlers: Optional list of (signal, handler) tuples to disconnect
        wait_timeout_ms: Maximum time to wait for thread termination (default: 5000ms)

    Example:
        ```python
        def test_worker(qtbot):
            worker = MyWorker()

            # Track signal connections for cleanup
            signal_handlers = [
                (worker.worker_discovery_started, on_started),
                (worker.discovery_finished, on_finished),
                (worker.progress, on_progress),
            ]

            try:
                with qtbot.waitSignal(worker.discovery_finished):
                    worker.start()

                # Test logic...

            finally:
                cleanup_qthread_properly(worker, signal_handlers)
        ```

    Cleanup sequence:
        1. Disconnect all signal handlers (prevents dangling callbacks)
        2. Stop the thread (requestInterruption → quit → wait)
        3. Delete the Qt C++ object (deleteLater)
        4. Process events to flush deletion queue (CRITICAL)
        5. Process events again for cascading cleanups

    See UNIFIED_TESTING_V2.md section "Large Qt Test Suite Stability" for details.

    """
    # Step 1: Disconnect all signal handlers FIRST
    # This prevents Qt from calling handlers on objects that are being deleted
    if signal_handlers:
        for signal, handler in signal_handlers:
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                # Already disconnected or object deleted
                pass

    # Step 2: Stop the thread gracefully
    if thread.isRunning():
        # Request graceful shutdown
        thread.requestInterruption()

        # Tell event loop to stop
        thread.quit()

        # Wait for thread to finish (with timeout to prevent hangs)
        if not thread.wait(wait_timeout_ms):
            # Thread didn't finish gracefully - force termination as last resort
            thread.terminate()
            thread.wait(1000)  # Brief wait after terminate

    # Step 3: Schedule Qt C++ object for deletion
    # This is CRITICAL - without deleteLater(), the Qt C++ object accumulates
    thread.deleteLater()

    # Step 4: Process events to flush the deletion queue
    # This ensures the Qt C++ object is actually deleted NOW, not later
    QCoreApplication.processEvents()

    # Step 5: Process deferred deletes explicitly
    # This handles any objects that were marked for deferred deletion
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    # Step 6: Process events again for cascading cleanups
    # Child objects may have been scheduled for deletion in step 5
    QCoreApplication.processEvents()
