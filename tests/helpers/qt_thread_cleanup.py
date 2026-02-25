"""Qt QThread cleanup utilities for test hygiene.

Provides proper cleanup helpers to prevent Qt C++ object accumulation
that causes segfaults in large test suites.

Based on pytest-qt best practices and Qt Test guidelines.

References:
- https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html
- https://doc.qt.io/qt-6/objecttrees.html
- https://doc.qt.io/qt-6/qthread.html#details

"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QCoreApplication, QEvent, QThread


if TYPE_CHECKING:
    from collections.abc import Sequence


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


def create_cleanup_handler(
    thread: QThread,
    signal_handlers: Sequence[tuple[Any, Callable]] | None = None,
) -> Callable[[], None]:
    """Create a cleanup handler function for use in try/finally blocks.

    Args:
        thread: The QThread instance to clean up
        signal_handlers: Optional list of (signal, handler) tuples to disconnect

    Returns:
        A callable cleanup function that can be used in a finally block

    Example:
        ```python
        def test_worker(qtbot):
            worker = MyWorker()

            signal_handlers = [
                (worker.started, on_started),
                (worker.finished, on_finished),
            ]

            cleanup = create_cleanup_handler(worker, signal_handlers)

            try:
                with qtbot.waitSignal(worker.finished):
                    worker.start()
                # Test logic...
            finally:
                cleanup()
        ```

    """

    def cleanup() -> None:
        cleanup_qthread_properly(thread, signal_handlers)

    return cleanup
