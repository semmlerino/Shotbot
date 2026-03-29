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

from tests.test_helpers import drain_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [
    pytest.mark.qt,
    pytest.mark.thread_safety,
    pytest.mark.qt_heavy,
]


class TestProcessPoolManagerShutdown:
    """Tests for ProcessPoolManager shutdown behavior."""

    def test_shutdown_is_idempotent(self) -> None:
        """Multiple shutdown calls don't cause errors."""
        from workers.process_pool_manager import ProcessPoolManager

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
        qtbot.waitUntil(lambda: len(received) == 1, timeout=5000)
        assert len(received) == 1

        # Disconnect (simulating shutdown)
        emitter.test_signal.disconnect(handler)
        emitter._shutdown = True

        # Emit after disconnect should not crash
        # (would crash if handler was called with deleted object)
        emitter.emit_test()
        drain_qt_events()

        # Handler should not have received second signal
        assert len(received) == 1


class TestSingletonResetOrdering:
    """Tests for correct singleton reset ordering."""

    def test_singleton_registry_cleanup_order(self) -> None:
        """Singletons are reset in defined order."""
        from tests.fixtures.singleton_fixtures import SingletonRegistry

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
        from tests.fixtures.singleton_fixtures import SingletonRegistry

        missing_reset = SingletonRegistry.verify_all_have_reset()

        assert not missing_reset, f"Singletons missing reset() method: {missing_reset}"


class TestAppWideShutdown:
    """Tests for coordinated app-wide shutdown."""

    @pytest.mark.skip_if_parallel
    def test_multiple_manager_shutdown_no_deadlock(self, qtbot: QtBot) -> None:
        """Shutting down multiple managers concurrently doesn't deadlock."""
        from workers.process_pool_manager import ProcessPoolManager
        from workers.thread_safe_worker import ThreadSafeWorker

        # Reset both managers
        ProcessPoolManager.reset()
        ThreadSafeWorker.reset()

        errors: list[Exception] = []

        def shutdown_pool() -> None:
            try:
                pool = ProcessPoolManager.get_instance()
                pool.shutdown(timeout=1.0)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def shutdown_workers() -> None:
            try:
                ThreadSafeWorker.reset()
            except Exception as e:  # noqa: BLE001
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
        from workers.process_pool_manager import ProcessPoolManager

        ProcessPoolManager.reset()
        pool = ProcessPoolManager.get_instance()

        # Simulate active operations by holding the mutex briefly
        # (This is a simplified test - full integration would need ShotModel)
        active_operations = []
        lock_acquired = threading.Event()

        def simulate_operation() -> None:
            """Simulate an active operation."""
            try:
                with QMutexLocker(pool._mutex):
                    lock_acquired.set()
                    active_operations.append("started")
                    time.sleep(0.1)
                    active_operations.append("finished")
            except Exception:  # noqa: BLE001
                pass

        # Concurrent operation and shutdown
        op_thread = threading.Thread(target=simulate_operation)
        op_thread.start()

        # Wait for thread to actually acquire the lock before shutting down
        lock_acquired.wait(timeout=2.0)

        # Shutdown during operation
        qtbot.waitUntil(lambda: "started" in active_operations, timeout=1000)

        # Shutdown while operation is active
        pool.shutdown(timeout=2.0)

        # Wait for operation thread
        op_thread.join(timeout=2.0)

        # Should complete without crash
        assert "started" in active_operations

        ProcessPoolManager.reset()
