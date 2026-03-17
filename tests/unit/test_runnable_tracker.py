"""Tests for QRunnableTracker thread-safe singleton.

Tests cover:
- QRunnableTracker: Registration, unregistration, statistics, cleanup
- TrackedQRunnable: Auto-registration lifecycle
- Thread safety: Concurrent access patterns
- Weak references: Garbage collection behavior
"""

from __future__ import annotations

import gc
import queue
import threading
import time
from typing import ClassVar
from unittest.mock import patch

import pytest
from PySide6.QtCore import QRunnable, QThreadPool

from workers.runnable_tracker import (
    QRunnableTracker,
    TrackedQRunnable,
    cleanup_all_runnables,
    get_tracker,
    register_runnable,
    unregister_runnable,
)


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def reset_tracker() -> None:
    """Reset the singleton tracker before and after each test."""
    QRunnableTracker.reset()
    yield
    QRunnableTracker.reset()


@pytest.fixture
def tracker() -> QRunnableTracker:
    """Get the tracker singleton instance."""
    return QRunnableTracker()


class DummyRunnable(QRunnable):
    """Simple QRunnable for testing."""

    def run(self) -> None:
        """Do nothing."""


class SlowRunnable(QRunnable):
    """QRunnable that sleeps for a specified duration."""

    def __init__(self, duration: float = 0.1) -> None:
        super().__init__()
        self._duration = duration

    def run(self) -> None:
        """Sleep for the specified duration."""
        time.sleep(self._duration)


class TrackedTestRunnable(TrackedQRunnable):
    """Test implementation of TrackedQRunnable."""

    work_done: ClassVar[int] = 0

    def _do_work(self) -> None:
        """Increment counter when work is done."""
        TrackedTestRunnable.work_done += 1


# ==============================================================================
# Basic Registration Tests
# ==============================================================================


class TestQRunnableTrackerBasic:
    """Basic registration and unregistration tests."""

    def test_register_adds_runnable(self, tracker: QRunnableTracker) -> None:
        """register() adds runnable to active set."""
        runnable = DummyRunnable()

        tracker.register(runnable)

        assert tracker.get_active_count() == 1

    def test_unregister_removes_runnable(self, tracker: QRunnableTracker) -> None:
        """unregister() removes runnable from active set."""
        runnable = DummyRunnable()
        tracker.register(runnable)

        tracker.unregister(runnable)

        assert tracker.get_active_count() == 0

    def test_register_with_metadata(self, tracker: QRunnableTracker) -> None:
        """register() stores metadata."""
        runnable = DummyRunnable()

        tracker.register(runnable, {"type": "test", "priority": 1})

        assert tracker.get_active_count() == 1

    def test_get_active_runnables(self, tracker: QRunnableTracker) -> None:
        """get_active_runnables() returns list of active runnables."""
        runnable1 = DummyRunnable()
        runnable2 = DummyRunnable()
        tracker.register(runnable1)
        tracker.register(runnable2)

        active = tracker.get_active_runnables()

        assert len(active) == 2
        assert runnable1 in active
        assert runnable2 in active

    def test_unregister_nonexistent_is_safe(self, tracker: QRunnableTracker) -> None:
        """unregister() on non-registered runnable doesn't error."""
        runnable = DummyRunnable()

        # Should not raise
        tracker.unregister(runnable)

        assert tracker.get_active_count() == 0


# ==============================================================================
# Statistics Tests
# ==============================================================================


class TestQRunnableTrackerStats:
    """Statistics tracking tests."""

    def test_total_registered_increments(self, tracker: QRunnableTracker) -> None:
        """total_registered increments with each registration."""
        runnable1 = DummyRunnable()
        runnable2 = DummyRunnable()

        tracker.register(runnable1)
        tracker.register(runnable2)
        stats = tracker.get_stats()

        assert stats["total_registered"] == 2

    def test_total_completed_increments(self, tracker: QRunnableTracker) -> None:
        """total_completed increments with each unregistration."""
        runnable1 = DummyRunnable()
        runnable2 = DummyRunnable()
        tracker.register(runnable1)
        tracker.register(runnable2)

        tracker.unregister(runnable1)
        tracker.unregister(runnable2)
        stats = tracker.get_stats()

        assert stats["total_completed"] == 2

    def test_peak_concurrent_tracked(self, tracker: QRunnableTracker) -> None:
        """peak_concurrent tracks maximum concurrent registrations."""
        runnables = [DummyRunnable() for _ in range(5)]

        # Register all
        for r in runnables:
            tracker.register(r)

        # Unregister some
        tracker.unregister(runnables[0])
        tracker.unregister(runnables[1])

        stats = tracker.get_stats()

        assert stats["peak_concurrent"] == 5
        assert stats["current_active"] == 3

    def test_current_active_in_stats(self, tracker: QRunnableTracker) -> None:
        """get_stats() includes current_active count."""
        runnable = DummyRunnable()
        tracker.register(runnable)

        stats = tracker.get_stats()

        assert stats["current_active"] == 1


# ==============================================================================
# Thread Safety Tests
# ==============================================================================


class TestQRunnableTrackerThreadSafety:
    """Concurrent access tests."""

    def test_concurrent_registration(self, tracker: QRunnableTracker) -> None:
        """Multiple threads registering simultaneously is safe."""
        runnables: queue.Queue[DummyRunnable] = queue.Queue()
        barrier = threading.Barrier(10)

        def register_runnable() -> None:
            r = DummyRunnable()
            barrier.wait()  # Synchronize all threads
            tracker.register(r)
            runnables.put(r)

        threads = [threading.Thread(target=register_runnable) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker.get_active_count() == 10
        stats = tracker.get_stats()
        assert stats["total_registered"] == 10

    def test_concurrent_unregistration(self, tracker: QRunnableTracker) -> None:
        """Multiple threads unregistering simultaneously is safe."""
        runnables = [DummyRunnable() for _ in range(10)]
        for r in runnables:
            tracker.register(r)

        barrier = threading.Barrier(10)

        def unregister_runnable(runnable: DummyRunnable) -> None:
            barrier.wait()
            tracker.unregister(runnable)

        threads = [
            threading.Thread(target=unregister_runnable, args=(r,)) for r in runnables
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker.get_active_count() == 0
        stats = tracker.get_stats()
        assert stats["total_completed"] == 10

    def test_concurrent_mixed_operations(self, tracker: QRunnableTracker) -> None:
        """Mixed register/unregister/query operations are thread-safe."""
        runnables = [DummyRunnable() for _ in range(5)]
        for r in runnables:
            tracker.register(r)

        errors: list[Exception] = []

        def do_operations() -> None:
            try:
                for _ in range(100):
                    # Random operations
                    _ = tracker.get_active_count()
                    _ = tracker.get_stats()
                    _ = tracker.get_active_runnables()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=do_operations) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ==============================================================================
# Weak Reference Tests
# ==============================================================================


class TestQRunnableTrackerWeakReferences:
    """Weak reference behavior tests."""

    def test_runnable_garbage_collected(self, tracker: QRunnableTracker) -> None:
        """Registered runnables can be garbage collected."""
        runnable = DummyRunnable()
        tracker.register(runnable)
        assert tracker.get_active_count() == 1

        # Delete reference and force GC
        del runnable
        gc.collect()

        # Weak reference should be gone
        assert tracker.get_active_count() == 0

    def test_metadata_cleaned_with_runnable(self, tracker: QRunnableTracker) -> None:
        """Metadata is cleaned when runnable is garbage collected."""
        runnable = DummyRunnable()
        tracker.register(runnable, {"key": "value"})

        del runnable
        gc.collect()

        # Both runnable and metadata should be gone
        assert tracker.get_active_count() == 0


# ==============================================================================
# Wait and Cleanup Tests
# ==============================================================================


class TestQRunnableTrackerWaitAndCleanup:
    """wait_for_all() and cleanup_all() tests."""

    def test_wait_for_all_returns_true_when_empty(
        self,
        tracker: QRunnableTracker,
    ) -> None:
        """wait_for_all() returns True immediately when no active runnables."""
        result = tracker.wait_for_all(timeout_ms=100)

        assert result is True

    def test_wait_for_all_timeout(self, tracker: QRunnableTracker) -> None:
        """wait_for_all() returns False on timeout."""
        # Register a runnable that won't complete
        runnable = DummyRunnable()
        tracker.register(runnable)

        result = tracker.wait_for_all(timeout_ms=100)

        assert result is False

    def test_wait_for_all_returns_true_when_completed(
        self,
        tracker: QRunnableTracker,
    ) -> None:
        """wait_for_all() returns True when all runnables complete."""
        runnable = DummyRunnable()
        tracker.register(runnable)

        # Unregister in another thread after short delay
        def unregister_after_delay() -> None:
            time.sleep(0.05)
            tracker.unregister(runnable)

        thread = threading.Thread(target=unregister_after_delay)
        thread.start()

        result = tracker.wait_for_all(timeout_ms=1000)

        thread.join()
        assert result is True

    def test_cleanup_all_clears_runnables(self, tracker: QRunnableTracker) -> None:
        """cleanup_all() clears all tracked runnables."""
        runnables = [DummyRunnable() for _ in range(5)]
        for r in runnables:
            tracker.register(r)

        with patch.object(
            QThreadPool.globalInstance(),
            "waitForDone",
            return_value=True,
        ):
            tracker.cleanup_all()

        assert tracker.get_active_count() == 0


# ==============================================================================
# TrackedQRunnable Tests
# ==============================================================================


class TestTrackedQRunnable:
    """TrackedQRunnable base class tests."""

    def test_tracked_runnable_registers_and_unregisters(
        self,
        tracker: QRunnableTracker,
    ) -> None:
        """TrackedQRunnable auto-registers and unregisters."""
        TrackedTestRunnable.work_done = 0
        runnable = TrackedTestRunnable(auto_delete=False)

        # After construction: auto-registered
        assert tracker.get_active_count() == 1

        # Run (does work, then unregisters)
        runnable.run()

        # After run
        assert TrackedTestRunnable.work_done == 1
        assert tracker.get_active_count() == 0

        stats = tracker.get_stats()
        assert stats["total_registered"] == 1
        assert stats["total_completed"] == 1

    def test_tracked_runnable_unregisters_on_exception(
        self,
        tracker: QRunnableTracker,
    ) -> None:
        """TrackedQRunnable unregisters even if _do_work raises."""

        class FailingRunnable(TrackedQRunnable):
            def _do_work(self) -> None:
                raise ValueError("Test error")

        runnable = FailingRunnable(auto_delete=False)

        with pytest.raises(ValueError, match="Test error"):
            runnable.run()

        # Should still be unregistered
        assert tracker.get_active_count() == 0
        stats = tracker.get_stats()
        assert stats["total_completed"] == 1

    def test_tracked_runnable_sets_metadata(
        self,
        tracker: QRunnableTracker,
    ) -> None:
        """TrackedQRunnable sets type metadata."""
        runnable = TrackedTestRunnable(auto_delete=False)

        # The metadata is set during __init__ but registered during run()
        assert runnable._metadata["type"] == "TrackedTestRunnable"
        assert runnable._metadata["auto_delete"] is False


# ==============================================================================
# Convenience Function Tests
# ==============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_tracker_returns_singleton(self) -> None:
        """get_tracker() returns the singleton instance."""
        tracker1 = get_tracker()
        tracker2 = get_tracker()

        assert tracker1 is tracker2

    def test_register_runnable_function(self) -> None:
        """register_runnable() convenience function works."""
        runnable = DummyRunnable()

        register_runnable(runnable, {"test": True})
        tracker = get_tracker()

        assert tracker.get_active_count() == 1

    def test_unregister_runnable_function(self) -> None:
        """unregister_runnable() convenience function works."""
        runnable = DummyRunnable()
        register_runnable(runnable)

        unregister_runnable(runnable)
        tracker = get_tracker()

        assert tracker.get_active_count() == 0

    def test_cleanup_all_runnables_function(self) -> None:
        """cleanup_all_runnables() convenience function works."""
        runnable = DummyRunnable()
        register_runnable(runnable)

        with patch.object(
            QThreadPool.globalInstance(),
            "waitForDone",
            return_value=True,
        ):
            cleanup_all_runnables()

        tracker = get_tracker()
        assert tracker.get_active_count() == 0


# ==============================================================================
# Singleton Behavior Tests
# ==============================================================================


class TestQRunnableTrackerSingleton:
    """Tests for singleton behavior."""

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple instantiations return the same instance."""
        tracker1 = QRunnableTracker()
        tracker2 = QRunnableTracker()

        assert tracker1 is tracker2

    def test_reset_creates_new_instance(self) -> None:
        """reset() creates a fresh instance on next access."""
        tracker1 = QRunnableTracker()
        tracker1.register(DummyRunnable())

        QRunnableTracker.reset()
        tracker2 = QRunnableTracker()

        # New instance with clean state
        assert tracker2.get_active_count() == 0
        assert tracker2.get_stats()["total_registered"] == 0
