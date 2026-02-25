"""Test helpers and doubles for ShotBot test suite.

Based on UNIFIED_TESTING_GUIDE_DO_NOT_DELETE.md - provides thread-safe
test doubles and helper classes for proper Qt testing without crashes.

Key Components:
    - SignalDouble: Signal test double for non-Qt objects (re-exported from fixtures)
    - process_qt_events: Process pending Qt events (preferred over qtbot.wait)
    - Factory fixtures and helpers
    - SynchronizationHelpers: Helpers to replace time.sleep() in tests
    - AsyncWaiter: Wait on multiple async operations
    - cleanup_qthread_properly: Proper QThread cleanup for test hygiene
    - ThreadSignalTester: Helper for testing Qt thread signals reliably
    - WorkerTestFramework: Complete framework for testing Qt workers

Note: ThreadSafeTestImage is available from tests.fixtures.test_doubles.
"""

from __future__ import annotations

# Standard library imports
import gc
import json
import os
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# Third-party imports
import psutil
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QObject,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy
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


class MockMainWindow(QObject):
    """Mock MainWindow with real Qt signals but mocked behavior.

    This is a real Qt object so QSignalSpy will work, but with
    simplified/mocked implementation for testing.
    """

    # Real Qt signals
    extract_requested = Signal()
    file_opened = Signal(str)
    shot_selected = Signal(str)
    refresh_started = Signal()
    refresh_finished = Signal(bool)

    def __init__(self, parent=None) -> None:
        """Initialize the mock main window."""
        super().__init__(parent)

        # Mock attributes
        self.status_messages: list[str] = []
        self.current_file: str | None = None
        self.current_shot: str | None = None
        self.extraction_params = {"vram_path": "/test/path"}

    def get_extraction_params(self) -> dict[str, Any]:
        """Get extraction parameters (mocked)."""
        return self.extraction_params.copy()

    def set_extraction_params(self, params: dict[str, Any]) -> None:
        """Set extraction parameters for testing."""
        self.extraction_params = params

    def showStatusMessage(self, message: str, timeout: int = 0) -> None:
        """Show status message (mocked)."""
        self.status_messages.append(message)

    def open_file(self, filepath: str) -> None:
        """Open a file (mocked)."""
        self.current_file = filepath
        self.file_opened.emit(filepath)

    def select_shot(self, shot_name: str) -> None:
        """Select a shot (mocked)."""
        self.current_shot = shot_name
        self.shot_selected.emit(shot_name)


class ImagePool:
    """Reuse ThreadSafeTestImage instances for performance.

    Creating QImage objects has some overhead, so this pool
    allows reusing instances in tests that create many images.
    """

    def __init__(self) -> None:
        """Initialize the image pool."""
        self._pool: list[Any] = []
        self._created_count = 0
        self._reused_count = 0

    def get_test_image(
        self, width: int = 100, height: int = 100
    ) -> Any:
        """Get a test image from the pool or create a new one."""
        # Try to find a matching size in the pool
        for i, image in enumerate(self._pool):
            if image.width() == width and image.height() == height:
                self._pool.pop(i)
                image.fill()  # Reset to white
                self._reused_count += 1
                return image

        # Create new image if none available
        from tests.fixtures.test_doubles import ThreadSafeTestImage

        self._created_count += 1
        return ThreadSafeTestImage(width, height)

    def return_image(self, image: Any) -> None:
        """Return an image to the pool for reuse."""
        if len(self._pool) < 10:  # Limit pool size
            self._pool.append(image)

    def get_stats(self) -> dict[str, int]:
        """Get pool statistics."""
        return {
            "created": self._created_count,
            "reused": self._reused_count,
            "pool_size": len(self._pool),
        }

    def clear(self) -> None:
        """Clear the pool."""
        self._pool.clear()


class TestCacheData:
    """Test data generator for cache-related tests."""

    @staticmethod
    def create_shot_data(count: int = 3) -> list[dict[str, Any]]:
        """Create test shot data."""
        return [
            {
                "show": f"test_show_{i}",
                "sequence": f"seq{i:03d}",
                "shot": f"shot{i:04d}",
                "workspace_path": f"/test/path/show_{i}/seq{i:03d}/shot{i:04d}",
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
            for i in range(count)
        ]

    @staticmethod
    def create_scene_data(count: int = 2) -> list[dict[str, Any]]:
        """Create test 3DE scene data."""
        return [
            {
                "path": f"/test/3de/scene_{i}.3de",
                "plate_name": f"plate_{i}",
                "user": f"user_{i}",
                "mtime": datetime.now(tz=UTC).timestamp(),
                "size": 1024 * (i + 1),
            }
            for i in range(count)
        ]

    @staticmethod
    def create_cache_file(cache_dir: Path, filename: str, data: Any) -> Path:
        """Create a cache file with test data."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / filename

        with cache_file.open("w") as f:
            json.dump(data, f, indent=2)

        return cache_file

    @staticmethod
    def create_test_image_file(
        filepath: Path, width: int = 100, height: int = 100
    ) -> Path:
        """Create a test image file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Create a simple QImage and save it
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor(100, 150, 200))  # Light blue
        image.save(str(filepath), "PNG")

        return filepath


def create_test_shot(
    show: str = "test", seq: str = "seq001", shot: str = "shot0010"
) -> dict[str, str]:
    """Factory function for creating test shot dictionaries."""
    return {
        "show": show,
        "sequence": seq,
        "shot": shot,
        "workspace_path": f"/shows/{show}/{seq}/{shot}",
    }


def create_test_process_result(
    success: bool = True, output: str = "Test output"
) -> tuple[bool, str]:
    """Factory function for process result tuples."""
    return success, output


def with_thread_safe_images(test_func: Callable) -> Callable:
    """Decorator to ensure thread-safe image usage in tests.

    Automatically patches QPixmap creation to use ThreadSafeTestImage
    in the decorated test function.
    """
    from unittest.mock import patch

    from tests.fixtures.test_doubles import ThreadSafeTestImage

    def wrapper(*args, **kwargs):
        with patch("PySide6.QtGui.QPixmap", ThreadSafeTestImage):
            return test_func(*args, **kwargs)

    wrapper.__name__ = test_func.__name__
    wrapper.__doc__ = test_func.__doc__
    return wrapper


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
    def wait_for_cache_operation(
        cache_manager: Any,
        operation: str = "thumbnail_exists",
        timeout_ms: int = 100,
        **kwargs: Any,
    ) -> bool:
        """Wait for cache operation to complete.

        Args:
            cache_manager: CacheManager instance
            operation: Type of operation to wait for
            timeout_ms: Maximum wait time
            **kwargs: Arguments for the check (show, sequence, shot)

        Example:
            # Instead of: cache_thumbnail(); time.sleep(0.1)
            # Use: cache_thumbnail(); wait_for_cache_operation(manager, "thumbnail_exists", show=...)

        """
        if operation == "thumbnail_exists":
            show = kwargs.get("show")
            sequence = kwargs.get("sequence")
            shot = kwargs.get("shot")

            return SynchronizationHelpers.wait_for_condition(
                lambda: cache_manager.get_cached_thumbnail(show, sequence, shot)
                is not None,
                timeout_ms=timeout_ms,
            )
        if operation == "directory_exists":
            return SynchronizationHelpers.wait_for_condition(
                lambda: cache_manager.thumbnails_dir.exists(),
                timeout_ms=timeout_ms,
            )
        raise ValueError(f"Unknown operation: {operation}")

    @staticmethod
    def wait_for_process_completion(
        process_manager: Any,
        process_key: str,
        timeout_ms: int = 1000,
    ) -> bool:
        """Wait for a process to complete.

        Args:
            process_manager: Process manager instance
            process_key: Key of the process to wait for
            timeout_ms: Maximum wait time

        Returns:
            True if process completed, False if timeout

        Example:
            # Instead of: launch_process(); time.sleep(0.5)
            # Use: key = launch_process(); wait_for_process_completion(manager, key, 500)

        """
        return SynchronizationHelpers.wait_for_condition(
            lambda: not process_manager.is_process_active(process_key),
            timeout_ms=timeout_ms,
        )

    @staticmethod
    def wait_for_memory_cleanup(
        threshold_mb: float = 100,
        timeout_ms: int = 1000,
    ) -> bool:
        """Wait for memory to be cleaned up after operations.

        Args:
            threshold_mb: Memory threshold in MB
            timeout_ms: Maximum wait time

        Returns:
            True if memory below threshold, False if timeout

        Example:
            # Instead of: del large_object; time.sleep(0.1); gc.collect()
            # Use: del large_object; wait_for_memory_cleanup(100, 1000)

        """
        process = psutil.Process(os.getpid())
        threshold_bytes = threshold_mb * 1024 * 1024

        def check_memory() -> bool:
            gc.collect()
            return process.memory_info().rss < threshold_bytes

        return SynchronizationHelpers.wait_for_condition(
            check_memory,
            timeout_ms=timeout_ms,
            poll_interval_ms=50,
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

    @staticmethod
    def create_async_waiter(qtbot: Any) -> AsyncWaiter:
        """Create an async waiter for complex multi-signal scenarios.

        Example:
            waiter = create_async_waiter(qtbot)
            waiter.add_signal(model.started)
            waiter.add_signal(model.finished)
            model.start_operation()
            waiter.wait_for_all(timeout_ms=1000)

        """
        return AsyncWaiter(qtbot)


class AsyncWaiter:
    """Helper for waiting on multiple async operations."""

    def __init__(self, qtbot: Any) -> None:
        """Initialize the async waiter."""
        self.qtbot = qtbot
        self.signals: list[Signal] = []
        self.conditions: list[Callable[[], bool]] = []

    def add_signal(self, signal: Signal) -> AsyncWaiter:
        """Add a signal to wait for."""
        self.signals.append(signal)
        return self

    def add_condition(self, condition: Callable[[], bool]) -> AsyncWaiter:
        """Add a condition to wait for."""
        self.conditions.append(condition)
        return self

    def wait_for_all(self, timeout_ms: int = 1000) -> bool:
        """Wait for all signals and conditions."""
        # Create blockers for all signals
        blockers = []
        for signal in self.signals:
            spy = QSignalSpy(signal)
            blockers.append(spy)

        # Wait for all conditions and signals
        start_time = time.perf_counter()
        timeout_sec = timeout_ms / 1000.0

        while time.perf_counter() - start_time < timeout_sec:
            # Check if all signals received
            signals_done = all(len(blocker) > 0 for blocker in blockers)

            # Check if all conditions met
            conditions_done = all(cond() for cond in self.conditions)

            if signals_done and conditions_done:
                return True

            # Process events
            QEventLoop().processEvents()
            time.sleep(0.001)  # Minimal sleep

        return False


# Convenience functions for direct import (mirrors synchronization.py public API)
wait_for_condition = SynchronizationHelpers.wait_for_condition
wait_for_file_operation = SynchronizationHelpers.wait_for_file_operation
wait_for_qt_signal = SynchronizationHelpers.wait_for_qt_signal
wait_for_threads_to_start = SynchronizationHelpers.wait_for_threads_to_start
wait_for_cache_operation = SynchronizationHelpers.wait_for_cache_operation
wait_for_process_completion = SynchronizationHelpers.wait_for_process_completion
wait_for_memory_cleanup = SynchronizationHelpers.wait_for_memory_cleanup
simulate_work_without_sleep = SynchronizationHelpers.simulate_work_without_sleep
create_async_waiter = SynchronizationHelpers.create_async_waiter


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


def ensure_qt_events_processed(qtbot: QtBot, cycles: int = 3) -> None:
    """Ensure Qt events are processed multiple times.

    This is useful when signals need to propagate through multiple
    event loop cycles.

    Args:
        qtbot: pytest-qt bot
        cycles: Number of event processing cycles

    """
    for _ in range(cycles):
        qtbot.wait(1)  # Minimal event processing per cycle
        app = QCoreApplication.instance()
        if app:
            SynchronizationHelpers.process_qt_events(app, 10)


class WorkerTestFramework:
    """Complete framework for testing Qt workers with lifecycle management."""

    def __init__(self, qtbot: QtBot) -> None:
        """Initialize the worker test framework."""
        self.qtbot = qtbot
        self.signal_tester = ThreadSignalTester(qtbot)

    def test_worker_complete_lifecycle(
        self,
        worker: QThread,
        work_duration: float = 0.05,
        expected_final_state: Any = None,
    ) -> dict[str, Any]:
        """Test complete worker lifecycle with comprehensive verification.

        Args:
            worker: Worker thread to test
            work_duration: Expected work duration for timeout calculation
            expected_final_state: Expected final state (e.g., WorkerState.DELETED)

        Returns:
            Dictionary with test results and captured data

        """
        results: dict[str, Any] = {
            "signals_captured": [],
            "final_state": None,
            "success": True,
            "error_messages": [],
        }

        # Set up signal capturing
        if hasattr(worker, "worker_started"):
            self.signal_tester.capture_signal(worker.worker_started)
        if hasattr(worker, "worker_stopped"):
            self.signal_tester.capture_signal(worker.worker_stopped)
        if hasattr(worker, "worker_error"):

            def error_handler(msg: str) -> None:
                results["error_messages"].append(msg)

            worker.worker_error.connect(error_handler)

        # Start worker
        worker.start()

        # Wait for complete lifecycle
        timeout_ms = max(5000, int(work_duration * 1000 * 10))  # 10x safety margin

        try:
            # Wait for thread to finish
            with self.qtbot.waitSignal(worker.finished, timeout=timeout_ms):
                pass

            # Minimal event processing for final state transitions
            self.qtbot.wait(1)

            # Capture final state
            if hasattr(worker, "get_state"):
                results["final_state"] = worker.get_state()

            # Verify expected final state
            if (
                expected_final_state is not None
                and results["final_state"] != expected_final_state
            ):
                results["success"] = False

        except Exception as e:
            results["success"] = False
            results["error_messages"].append(str(e))

        results["signals_captured"] = self.signal_tester.captured_signals
        return results
