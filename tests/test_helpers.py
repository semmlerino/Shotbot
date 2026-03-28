"""Test helpers and doubles for ShotBot test suite.

Based on UNIFIED_TESTING_GUIDE_DO_NOT_DELETE.md - provides thread-safe
test doubles and helper classes for proper Qt testing without crashes.

Key Components:
    - SignalDouble: Signal test double for non-Qt objects (re-exported from fixtures)
    - cleanup_qthread_properly: Proper QThread cleanup for test hygiene

Note: ThreadSafeTestImage is available from tests.fixtures.test_doubles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QThread,
)

from tests.fixtures.model_fixtures import SignalDouble  # noqa: F401 (re-export)

# Import canonical doubles - these are the recommended implementations
from tests.fixtures.process_fixtures import (
    simulate_work_without_sleep,  # noqa: F401 (re-export from canonical location)
)


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


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
