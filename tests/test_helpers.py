"""Test helpers and doubles for ShotBot test suite.

Based on UNIFIED_TESTING_GUIDE_DO_NOT_DELETE.md - provides thread-safe
test doubles and helper classes for proper Qt testing without crashes.

Key Components:
    - SignalDouble: Signal test double for non-Qt objects (re-exported from fixtures)
    - process_qt_events: Process pending Qt events (preferred over qtbot.wait)
    - Factory fixtures and helpers
    - SynchronizationHelpers: Helpers to replace time.sleep() in tests
    - cleanup_qthread_properly: Proper QThread cleanup for test hygiene
    - ThreadSignalTester: Helper for testing Qt thread signals reliably
    - WorkerTestFramework: Complete framework for testing Qt workers

Note: ThreadSafeTestImage is available from tests.fixtures.test_doubles.
"""

from __future__ import annotations

# Standard library imports
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

# Third-party imports
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import QApplication

# Import canonical doubles - these are the recommended implementations
from tests.fixtures.test_doubles import SignalDouble  # noqa: F401 (re-export)


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    # Lazy import to avoid circular dependency (test_doubles imports from synchronization)


def process_qt_events(duration_ms: int = 5, iterations: int = 2) -> None:
    """Process pending Qt events.

    This helper processes Qt events in multiple iterations to ensure
    all pending events are handled. Use this instead of qtbot.wait(1)
    for event processing.

    NOTE: This does NOT flush DeferredDelete events. For end-of-test cleanup
    that includes DeferredDelete flushing, use the qt_cleanup fixture or
    call flush_deferred_deletes() explicitly after all widgets are destroyed.

    Args:
        duration_ms: Maximum time to spend processing events per iteration.
        iterations: Number of event processing rounds.

    """
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, duration_ms)


def flush_deferred_deletes() -> None:
    """Flush pending DeferredDelete events (deleteLater() calls).

    This explicitly processes all pending deleteLater() calls. Use this in
    test cleanup AFTER all widgets have been destroyed and you want to ensure
    their deletions are complete.

    WARNING: Only call this after widgets are fully disconnected from signals
    and their callbacks won't access deleted objects. Using this during mid-test
    event processing can cause segfaults.

    Example:
        widget.deleteLater()
        process_qt_events()
        flush_deferred_deletes()  # Now the widget is truly deleted

    """
    app = QApplication.instance()
    if app is None:
        return
    # Process events first to ensure all pending operations complete
    app.processEvents()
    # Then flush deferred deletes
    try:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    except (RuntimeError, SystemError):
        # Object may have been deleted already
        pass


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

    @staticmethod
    def wait_for_file_operation(
        file_path: Path,
        operation: str = "exists",
        timeout_ms: int = 1000,
    ) -> bool:
        """Wait for a file operation to complete.

        Args:
            file_path: Path to check
            operation: One of "exists", "not_exists", "writable"
            timeout_ms: Maximum time to wait

        Returns:
            True if operation succeeded, False if timeout

        Example:
            # Instead of: time.sleep(0.1)  # Wait for file deletion
            # Use: wait_for_file_operation(path, "not_exists", 100)

        """
        conditions = {
            "exists": lambda: file_path.exists(),
            "not_exists": lambda: not file_path.exists(),
            "writable": lambda: file_path.exists() and file_path.stat().st_mode & 0o200,
        }

        if operation not in conditions:
            raise ValueError(f"Unknown operation: {operation}")

        return SynchronizationHelpers.wait_for_condition(
            conditions[operation],
            timeout_ms,
        )

    @staticmethod
    def wait_for_qt_signal(
        qtbot: Any,
        signal: Signal,
        timeout_ms: int = 1000,
        trigger: Callable | None = None,
    ) -> Any:
        """Wait for a Qt signal to be emitted.

        Args:
            qtbot: pytest-qt fixture
            signal: Qt signal to wait for
            timeout_ms: Maximum time to wait
            trigger: Optional function to call to trigger the signal

        Returns:
            Signal arguments or raises TimeoutError

        Example:
            # Instead of: model.refresh(); time.sleep(0.5)
            # Use: wait_for_qt_signal(qtbot, model.refreshed, 500, model.refresh)

        """
        if trigger:
            with qtbot.waitSignal(signal, timeout=timeout_ms) as blocker:
                trigger()
            return blocker.args
        with qtbot.waitSignal(signal, timeout=timeout_ms) as blocker:
            pass
        return blocker.args

    @staticmethod
    def process_qt_events(_qapp: Any, duration_ms: int = 10) -> None:
        """Process Qt events for a specific duration without blocking.

        Args:
            _qapp: QApplication instance (unused, kept for API compatibility)
            duration_ms: How long to process events

        Example:
            # Instead of: time.sleep(0.01)  # Let UI update
            # Use: SynchronizationHelpers.process_qt_events(qapp, 10)

        """
        loop = QEventLoop()
        QTimer.singleShot(duration_ms, loop.quit)
        loop.exec()

    @staticmethod
    @contextmanager
    def wait_for_threads_to_start(
        max_wait_ms: int = 100,
    ) -> Generator[None, None, None]:
        """Context manager to ensure threads have started.

        Example:
            # ❌ WRONG - no cleanup guarantee
            thread.start()
            time.sleep(0.1)  # Anti-pattern

            # ✅ RIGHT - proper wait with cleanup
            thread = QThread()
            with wait_for_threads_to_start():
                thread.start()
            try:
                # ... test code ...
            finally:
                thread.quit()
                thread.wait(1000)

        """
        initial_count = threading.active_count()

        yield

        # Wait for thread count to increase
        SynchronizationHelpers.wait_for_condition(
            lambda: threading.active_count() > initial_count,
            timeout_ms=max_wait_ms,
        )

    @staticmethod
    def simulate_work_without_sleep(duration_ms: int = 10) -> None:
        """Simulate work without using sleep for stress tests.

        Args:
            duration_ms: How long to simulate work

        Example:
            # Instead of: time.sleep(0.01)  # Simulate work
            # Use: simulate_work_without_sleep(10)

        """
        # Use busy-wait with yield to simulate work without blocking
        start = time.perf_counter()
        target = start + (duration_ms / 1000.0)

        while time.perf_counter() < target:
            # Yield to other threads
            time.sleep(0)  # Minimal sleep just to yield


# Convenience functions for direct import (mirrors synchronization.py public API)
wait_for_condition = SynchronizationHelpers.wait_for_condition
wait_for_file_operation = SynchronizationHelpers.wait_for_file_operation
wait_for_qt_signal = SynchronizationHelpers.wait_for_qt_signal
wait_for_threads_to_start = SynchronizationHelpers.wait_for_threads_to_start
simulate_work_without_sleep = SynchronizationHelpers.simulate_work_without_sleep


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
                (worker.started, on_started),
                (worker.finished, on_finished),
                (worker.progress, on_progress),
            ]

            try:
                with qtbot.waitSignal(worker.finished):
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


# ---------------------------------------------------------------------------
# Qt thread test helpers (migrated from tests/test_utils/qt_thread_test_helpers.py)
# ---------------------------------------------------------------------------


class ThreadSignalTester:
    """Helper for testing Qt thread signals reliably."""

    def __init__(self, qtbot: QtBot) -> None:
        """Initialize the thread signal tester."""
        self.qtbot = qtbot
        self.captured_signals: list[Any] = []

    def capture_signal(self, signal: Signal, capture_args: bool = True) -> Callable:
        """Create a signal handler that captures emitted data.

        Args:
            signal: Qt signal to capture
            capture_args: Whether to capture signal arguments

        Returns:
            Signal handler function

        """

        def handler(*args: Any) -> None:
            if capture_args:
                self.captured_signals.append(
                    args if len(args) > 1 else (args[0] if args else None),
                )
            else:
                self.captured_signals.append(True)

        signal.connect(handler)
        return handler

    def wait_for_worker_lifecycle(
        self,
        worker: QThread,
        expect_error: bool = False,
        timeout_ms: int = 5000,
    ) -> bool:
        """Wait for complete worker lifecycle including DELETED state.

        Args:
            worker: Worker thread to monitor
            expect_error: Whether to expect an error signal
            timeout_ms: Maximum time to wait

        Returns:
            True if lifecycle completed successfully

        """
        # Wait for thread to finish
        with self.qtbot.waitSignal(worker.finished, timeout=timeout_ms):
            pass

        # Minimal event processing for _on_finished slot
        self.qtbot.wait(1)

        return True

    @contextmanager
    def signal_sequence(self, signals: list[Signal], timeout_ms: int = 5000):  # type: ignore[return]
        """Context manager for waiting on multiple signals in sequence.

        Args:
            signals: List of signals to wait for in order
            timeout_ms: Timeout for each signal

        """
        try:
            for signal in signals:
                with self.qtbot.waitSignal(signal, timeout=timeout_ms):
                    pass
            yield
        finally:
            # Cleanup handled by context manager
            pass


def wait_for_thread_state(
    worker: Any,
    expected_state: Any,
    qtbot: QtBot,
    timeout_ms: int = 1000,
) -> bool:
    """Wait for worker to reach expected state.

    Args:
        worker: Worker with get_state() method
        expected_state: State to wait for
        qtbot: pytest-qt bot for event processing
        timeout_ms: Maximum time to wait

    Returns:
        True if state reached, False if timeout

    """
    start_time = time.time()

    while time.time() - start_time < (timeout_ms / 1000.0):
        qtbot.wait(1)  # Minimal event processing between checks
        if worker.get_state() == expected_state:
            return True

    return False


