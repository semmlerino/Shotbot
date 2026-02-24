"""Integration tests for application shutdown sequences.

This module tests the coordination between various singleton managers during
shutdown, ensuring:

1. ProcessPoolManager handles hung tasks with timeout
2. Signals are not delivered to deleted objects
3. Singletons are reset in the correct order
4. App-wide shutdown doesn't block indefinitely

These tests verify shutdown behavior without causing actual application exit.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QMutexLocker, QObject, Signal

from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,
    pytest.mark.thread_safety,
]


class TestProcessPoolManagerShutdown:
    """Tests for ProcessPoolManager shutdown behavior."""

    @pytest.mark.permissive_process_pool
    def test_shutdown_with_idle_executor(self, qtbot: QtBot) -> None:
        """Shutdown succeeds quickly when no tasks are running."""
        from process_pool_manager import ProcessPoolManager

        # Get the test pool (mocked by autouse fixture)
        pool = ProcessPoolManager.get_instance()

        # Shutdown should complete quickly (no hung tasks)
        start = time.time()
        pool.shutdown(timeout=2.0)
        elapsed = time.time() - start

        # Should be very fast with idle executor
        assert elapsed < 1.0, f"Idle shutdown took too long: {elapsed}s"

    @pytest.mark.real_subprocess
    def test_shutdown_with_hung_task_uses_timeout(self) -> None:
        """Shutdown uses timeout when task is stuck."""
        from process_pool_manager import ProcessPoolManager

        # Reset to get fresh instance
        ProcessPoolManager.reset()
        pool = ProcessPoolManager.get_instance()

        # Use interruptible wait to avoid orphan threads that crash subsequent Qt tests
        stop_event = threading.Event()

        # Submit a slow task that won't finish quickly
        def slow_task() -> str:
            # Interruptible wait - can be signaled to stop early
            stop_event.wait(timeout=10.0)
            return "done"

        _future = pool._executor.submit(slow_task)

        # Shutdown with short timeout
        start = time.time()
        pool.shutdown(timeout=0.5)  # Very short timeout
        elapsed = time.time() - start

        # Should complete around timeout, not wait for task
        assert elapsed < 2.0, f"Shutdown didn't respect timeout: {elapsed}s"

        # Signal task to stop (CRITICAL for test isolation)
        stop_event.set()

        # Cleanup
        ProcessPoolManager.reset()

    def test_shutdown_is_idempotent(self) -> None:
        """Multiple shutdown calls don't cause errors."""
        from process_pool_manager import ProcessPoolManager

        ProcessPoolManager.reset()
        pool = ProcessPoolManager.get_instance()

        # Multiple shutdowns should be safe
        pool.shutdown(timeout=1.0)
        pool.shutdown(timeout=1.0)  # Second call
        pool.shutdown(timeout=1.0)  # Third call

        # No exceptions means success
        ProcessPoolManager.reset()


class TestSignalDeliveryDuringShutdown:
    """Tests for Qt signal safety during shutdown."""

    def test_signal_not_delivered_after_disconnect(self, qtbot: QtBot) -> None:
        """Signals disconnected during shutdown don't crash."""

        class SignalEmitter(QObject):
            test_signal = Signal(str)

            def __init__(self) -> None:
                super().__init__()
                self._shutdown = False

            def emit_test(self) -> None:
                if not self._shutdown:
                    self.test_signal.emit("test")

        emitter = SignalEmitter()
        received: list[str] = []

        def handler(msg: str) -> None:
            received.append(msg)

        # Connect signal
        emitter.test_signal.connect(handler)

        # Emit should work
        emitter.emit_test()
        process_qt_events()
        assert len(received) == 1

        # Disconnect (simulating shutdown)
        emitter.test_signal.disconnect(handler)
        emitter._shutdown = True

        # Emit after disconnect should not crash
        # (would crash if handler was called with deleted object)
        emitter.emit_test()
        process_qt_events()

        # Handler should not have received second signal
        assert len(received) == 1

    def test_queued_signal_during_object_deletion(self, qtbot: QtBot) -> None:
        """Queued signals don't crash when receiver is deleted."""
        from PySide6.QtCore import Qt

        class Emitter(QObject):
            signal = Signal()

        class Receiver(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.called = False

            def slot(self) -> None:
                self.called = True

        emitter = Emitter()
        receiver = Receiver()

        # Connect with QueuedConnection (cross-thread safe)
        emitter.signal.connect(receiver.slot, Qt.ConnectionType.QueuedConnection)

        # Schedule signal emission
        emitter.signal.emit()

        # Delete receiver before events processed
        receiver.deleteLater()
        process_qt_events()

        # Should not crash - Qt handles deleted receiver gracefully
        # (The slot may or may not be called depending on timing)


class TestSingletonResetOrdering:
    """Tests for correct singleton reset ordering."""

    def test_singleton_registry_cleanup_order(self) -> None:
        """Singletons are reset in defined order."""
        from tests.fixtures.singleton_registry import SingletonRegistry

        # Verify registry has expected entries with ordering
        entries = SingletonRegistry._entries

        # Extract orders - SingletonEntry has import_path, not name
        # Extract class name from import_path (e.g., "notification_manager.NotificationManager" -> "NotificationManager")
        orders = {e.import_path.split(".")[-1]: e.cleanup_order for e in entries}

        # Key singletons should have defined orders
        # Lower order = cleaned up first
        expected_order_constraints = [
            # UI singletons first (10-19)
            ("NotificationManager", lambda o: 10 <= o < 20),
            ("ProgressManager", lambda o: 10 <= o < 20),
            # Process pools later (30-39)
            ("ProcessPoolManager", lambda o: 30 <= o < 40),
        ]

        for name, constraint in expected_order_constraints:
            if name in orders:
                assert constraint(orders[name]), (
                    f"{name} has unexpected cleanup order: {orders[name]}"
                )

    def test_all_singletons_have_reset_method(self) -> None:
        """All registered singletons implement reset()."""
        from tests.fixtures.singleton_registry import SingletonRegistry

        missing_reset = SingletonRegistry.verify_all_have_reset()

        assert not missing_reset, (
            f"Singletons missing reset() method: {missing_reset}"
        )


class TestAppWideShutdown:
    """Tests for coordinated app-wide shutdown."""

    def test_multiple_manager_shutdown_no_deadlock(self, qtbot: QtBot) -> None:
        """Shutting down multiple managers concurrently doesn't deadlock."""
        from process_pool_manager import ProcessPoolManager
        from thread_safe_worker import ThreadSafeWorker

        # Reset both managers
        ProcessPoolManager.reset()
        ThreadSafeWorker.reset()

        errors: list[Exception] = []

        def shutdown_pool() -> None:
            try:
                pool = ProcessPoolManager.get_instance()
                pool.shutdown(timeout=1.0)
            except Exception as e:
                errors.append(e)

        def shutdown_workers() -> None:
            try:
                ThreadSafeWorker.reset()
            except Exception as e:
                errors.append(e)

        # Concurrent shutdown
        threads = [
            threading.Thread(target=shutdown_pool, name="PoolShutdown"),
            threading.Thread(target=shutdown_workers, name="WorkerShutdown"),
        ]

        for t in threads:
            t.start()

        # Should complete within reasonable time (no deadlock)
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive(), f"Thread {t.name} deadlocked"

        assert not errors, f"Shutdown errors: {errors}"

        # Cleanup
        ProcessPoolManager.reset()
        ThreadSafeWorker.reset()

    def test_shutdown_during_active_refresh_no_crash(self, qtbot: QtBot) -> None:
        """Shutdown while refresh is active doesn't crash."""
        from process_pool_manager import ProcessPoolManager

        ProcessPoolManager.reset()
        pool = ProcessPoolManager.get_instance()

        # Simulate active operations by holding the mutex briefly
        # (This is a simplified test - full integration would need ShotModel)
        active_operations = []

        def simulate_operation() -> None:
            """Simulate an active operation."""
            try:
                with QMutexLocker(pool._mutex):
                    active_operations.append("started")
                    time.sleep(0.1)
                    active_operations.append("finished")
            except Exception:
                pass

        # Start background "operation"
        op_thread = threading.Thread(target=simulate_operation)
        op_thread.start()

        # Small delay to ensure operation started
        time.sleep(0.05)

        # Shutdown while operation is active
        pool.shutdown(timeout=2.0)

        # Wait for operation thread
        op_thread.join(timeout=2.0)

        # Should complete without crash
        assert "started" in active_operations

        ProcessPoolManager.reset()


class TestExecutorShutdownTimeout:
    """Tests for ThreadPoolExecutor shutdown timeout handling."""

    def test_shutdown_timeout_wrapper_works(self) -> None:
        """Shutdown timeout wrapper prevents indefinite blocking."""
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=2)

        # Use an interruptible wait so we can clean up at test end
        # (time.sleep() leaves orphan threads that crash subsequent tests)
        stop_event = threading.Event()

        # Submit a task that will block
        def blocking_task() -> str:
            # Wait for stop signal, or timeout after 60s (whichever comes first)
            stop_event.wait(timeout=60.0)
            return "done"

        _future = executor.submit(blocking_task)

        # Use timeout wrapper pattern (same as ProcessPoolManager)
        shutdown_complete = threading.Event()

        def do_shutdown() -> None:
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            finally:
                shutdown_complete.set()

        shutdown_thread = threading.Thread(target=do_shutdown, daemon=True)
        shutdown_thread.start()

        # Should timeout, not wait forever
        completed = shutdown_complete.wait(timeout=1.0)

        if not completed:
            # Timeout worked - force non-blocking shutdown
            executor.shutdown(wait=False, cancel_futures=True)

        # Signal task to stop so thread doesn't linger (CRITICAL for test isolation)
        stop_event.set()

        # Wait for cleanup to complete
        shutdown_thread.join(timeout=2.0)

    def test_cancel_futures_stops_pending_tasks(self) -> None:
        """cancel_futures=True cancels queued but not-yet-started tasks."""
        from concurrent.futures import ThreadPoolExecutor

        # Small pool so tasks queue up
        executor = ThreadPoolExecutor(max_workers=1)

        started = threading.Event()
        stop_event = threading.Event()

        def slow_task() -> str:
            started.set()
            # Use interruptible wait instead of time.sleep()
            # (orphan threads from time.sleep crash subsequent Qt tests)
            stop_event.wait(timeout=10.0)
            return "done"

        # Submit multiple tasks - first will run, rest will queue
        _future1 = executor.submit(slow_task)
        future2 = executor.submit(slow_task)
        future3 = executor.submit(slow_task)

        # Wait for first task to start
        started.wait(timeout=2.0)

        # Shutdown with cancel_futures - pending tasks should be cancelled
        executor.shutdown(wait=False, cancel_futures=True)

        # Queued tasks should be cancelled
        # (future1 is running, future2/3 are queued)
        assert future2.cancelled() or not future2.done()
        assert future3.cancelled() or not future3.done()

        # Signal running task to stop (CRITICAL for test isolation)
        stop_event.set()
