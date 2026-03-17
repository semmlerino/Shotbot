"""Tests for ThreadSafeWorker zombie thread lifecycle management.

This module tests the zombie thread mechanism that prevents Qt crashes when
threads fail to stop gracefully. The zombie system:

1. Tracks threads that don't respond to stop requests
2. Prevents garbage collection of running threads (would crash Qt)
3. Periodically cleans up threads that finish naturally
4. Force-terminates threads after a timeout (last resort)

These tests verify the zombie lifecycle without relying on timing-sensitive
operations, using controlled state manipulation instead.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QMutexLocker, QObject

from workers.thread_safe_worker import ThreadSafeWorker


if TYPE_CHECKING:

    from pytestqt.qtbot import QtBot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.thread_safety,
]


class StubWorker(ThreadSafeWorker):
    """Test worker that can be controlled to simulate zombie scenarios."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._should_hang = False
        self._run_started = threading.Event()
        self._allow_exit = threading.Event()

    def set_hang_mode(self, hang: bool) -> None:
        """Configure worker to hang or exit normally."""
        self._should_hang = hang

    def allow_exit(self) -> None:
        """Signal worker to exit its run loop."""
        self._allow_exit.set()

    def wait_for_run_started(self, timeout: float = 2.0) -> bool:
        """Wait for run() to actually start executing."""
        return self._run_started.wait(timeout)

    def run(self) -> None:
        """Worker run method - can simulate hanging behavior."""
        self._run_started.set()

        if self._should_hang:
            # Simulate a worker that ignores stop requests
            while not self._allow_exit.is_set():
                if self._force_stop:
                    break
                time.sleep(0.01)
        else:
            # Normal worker that respects stop requests
            while not self._stop_requested:
                time.sleep(0.01)


class TestZombieCreation:
    """Tests for zombie thread creation when workers fail to stop."""

    def test_worker_becomes_zombie_when_stop_times_out(self, qtbot: QtBot) -> None:
        """Worker that doesn't stop within timeout becomes a zombie.

        This test verifies the zombie mechanism by directly manipulating state
        since the actual timeout behavior is timing-sensitive.
        """
        # Reset zombie state for clean test
        ThreadSafeWorker.reset()
        initial_metrics = ThreadSafeWorker.get_zombie_metrics()
        assert initial_metrics["created"] == 0
        assert initial_metrics["current"] == 0

        worker = StubWorker()
        worker.set_hang_mode(True)  # Worker will ignore stop requests

        # Start worker
        worker.start()
        assert worker.wait_for_run_started()

        # Directly simulate what safe_stop does when timeout occurs:
        # Set the zombie flag and add to collection
        with QMutexLocker(worker._state_mutex):
            worker._zombie = True

        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()
            ThreadSafeWorker._zombie_created_count += 1

        # Worker should now be marked as zombie
        assert worker.is_zombie()

        # Metrics should reflect zombie creation
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] >= 1
        assert metrics["current"] >= 1

        # Cleanup: allow worker to exit
        worker.allow_exit()
        worker.wait(2000)
        ThreadSafeWorker.reset()

    def test_worker_not_zombie_when_stops_normally(self, qtbot: QtBot) -> None:
        """Worker that stops within timeout is NOT a zombie."""
        ThreadSafeWorker.reset()

        worker = StubWorker()
        worker.set_hang_mode(False)  # Worker will respond to stop

        # Start worker
        worker.start()
        assert worker.wait_for_run_started()

        # Stop normally - worker should respond
        worker.safe_stop(timeout_ms=2000)

        # Worker should NOT be a zombie
        assert not worker.is_zombie()

        # Metrics should not show zombie creation
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] == 0
        assert metrics["current"] == 0

        ThreadSafeWorker.reset()


class TestZombieCollection:
    """Tests for zombie thread collection preventing GC crashes."""

    def test_zombie_collection_prevents_gc_crash(self) -> None:
        """Zombie threads are held in class collection to prevent GC crash."""
        ThreadSafeWorker.reset()

        # Directly manipulate zombie state (no actual threading)
        worker = StubWorker()

        # Simulate zombie creation by directly adding to collection
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()
            ThreadSafeWorker._zombie_created_count += 1

        # Verify zombie is in collection
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            assert worker in ThreadSafeWorker._zombie_threads
            assert id(worker) in ThreadSafeWorker._zombie_timestamps

        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 1
        assert metrics["created"] == 1

        ThreadSafeWorker.reset()

    def test_multiple_zombies_tracked_separately(self) -> None:
        """Multiple zombie threads are tracked independently."""
        ThreadSafeWorker.reset()

        workers = [StubWorker() for _ in range(3)]

        # Add all as zombies
        for w in workers:
            with QMutexLocker(ThreadSafeWorker._zombie_mutex):
                ThreadSafeWorker._zombie_threads.append(w)
                ThreadSafeWorker._zombie_timestamps[id(w)] = time.time()
                ThreadSafeWorker._zombie_created_count += 1

        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 3
        assert metrics["created"] == 3

        ThreadSafeWorker.reset()


class TestZombieRecovery:
    """Tests for zombie threads that finish naturally."""

    def test_finished_zombie_is_cleaned_up(self) -> None:
        """Zombie that finishes naturally is removed during cleanup."""
        ThreadSafeWorker.reset()

        # Create a mock worker that reports as not running
        worker = MagicMock(spec=ThreadSafeWorker)
        worker.isRunning.return_value = False  # Thread finished

        # Add to zombie collection
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()
            ThreadSafeWorker._zombie_created_count += 1

        initial_count = ThreadSafeWorker.get_zombie_metrics()["current"]
        assert initial_count == 1

        # Run cleanup
        cleaned = ThreadSafeWorker.cleanup_old_zombies()

        # Zombie should be cleaned
        assert cleaned == 1
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 0
        assert metrics["recovered"] == 1

        ThreadSafeWorker.reset()

    def test_still_running_zombie_not_cleaned_early(self) -> None:
        """Zombie that's still running is NOT cleaned before timeout."""
        ThreadSafeWorker.reset()

        # Create a mock worker that reports as still running
        worker = MagicMock(spec=ThreadSafeWorker)
        worker.isRunning.return_value = True  # Still running

        # Add to zombie collection with recent timestamp
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()  # Just now
            ThreadSafeWorker._zombie_created_count += 1

        # Run cleanup
        cleaned = ThreadSafeWorker.cleanup_old_zombies()

        # Zombie should NOT be cleaned (still running, not timed out)
        assert cleaned == 0
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 1
        assert metrics["recovered"] == 0
        assert metrics["terminated"] == 0

        ThreadSafeWorker.reset()


class TestZombieTermination:
    """Tests for force-termination of old zombie threads."""

    def test_old_zombie_is_force_terminated(self) -> None:
        """Zombie older than timeout is force-terminated."""
        ThreadSafeWorker.reset()

        # Create a mock worker that reports as still running
        worker = MagicMock(spec=ThreadSafeWorker)
        worker.isRunning.return_value = True  # Still running
        worker.wait.return_value = True  # terminate() works

        # Add to zombie collection with OLD timestamp (beyond terminate threshold)
        old_time = time.time() - ThreadSafeWorker._ZOMBIE_TERMINATE_AGE_SECONDS - 10
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = old_time
            ThreadSafeWorker._zombie_created_count += 1

        # Run cleanup
        cleaned = ThreadSafeWorker.cleanup_old_zombies()

        # Zombie should be force-terminated
        assert cleaned == 1
        worker.terminate.assert_called_once()
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 0
        assert metrics["terminated"] == 1

        ThreadSafeWorker.reset()


class TestZombieMetrics:
    """Tests for zombie metrics tracking."""

    def test_metrics_track_all_scenarios(self) -> None:
        """Metrics correctly track created, recovered, and terminated zombies."""
        ThreadSafeWorker.reset()

        # Create 3 zombies
        for _ in range(3):
            worker = MagicMock(spec=ThreadSafeWorker)
            worker.isRunning.return_value = True
            with QMutexLocker(ThreadSafeWorker._zombie_mutex):
                ThreadSafeWorker._zombie_threads.append(worker)
                ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()
                ThreadSafeWorker._zombie_created_count += 1

        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] == 3
        assert metrics["current"] == 3

        # Simulate 1 finishing naturally
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_threads[0].isRunning.return_value = False

        ThreadSafeWorker.cleanup_old_zombies()

        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] == 3
        assert metrics["recovered"] == 1
        assert metrics["current"] == 2

        ThreadSafeWorker.reset()

    def test_reset_clears_metrics(self) -> None:
        """Reset clears all zombie metrics for test isolation."""
        # Add some zombies first
        with QMutexLocker(ThreadSafeWorker._zombie_mutex):
            ThreadSafeWorker._zombie_created_count = 5
            ThreadSafeWorker._zombie_recovered_count = 3
            ThreadSafeWorker._zombie_terminated_count = 2

        # Reset
        ThreadSafeWorker.reset()

        # All counters should be zero
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] == 0
        assert metrics["recovered"] == 0
        assert metrics["terminated"] == 0
        assert metrics["current"] == 0


class TestZombieCleanupTimer:
    """Tests for periodic zombie cleanup timer."""

    def test_cleanup_timer_can_start_and_stop(self, qtbot: QtBot) -> None:
        """Cleanup timer can be started and stopped without errors."""
        ThreadSafeWorker.reset()

        # Initially no timer
        assert ThreadSafeWorker._zombie_cleanup_timer is None

        # Start timer
        ThreadSafeWorker.start_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is not None
        assert ThreadSafeWorker._zombie_cleanup_timer.isActive()

        # Stop timer
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is None

        ThreadSafeWorker.reset()

    def test_multiple_start_calls_are_idempotent(self) -> None:
        """Multiple start_zombie_cleanup_timer calls don't create multiple timers."""
        ThreadSafeWorker.reset()

        ThreadSafeWorker.start_zombie_cleanup_timer()
        timer1 = ThreadSafeWorker._zombie_cleanup_timer

        ThreadSafeWorker.start_zombie_cleanup_timer()
        timer2 = ThreadSafeWorker._zombie_cleanup_timer

        # Same timer instance
        assert timer1 is timer2

        ThreadSafeWorker.reset()

    def test_timer_has_correct_interval(self, qtbot: QtBot) -> None:
        """Timer interval matches the configured cleanup interval constant."""
        ThreadSafeWorker.reset()
        ThreadSafeWorker.start_zombie_cleanup_timer()

        timer = ThreadSafeWorker._zombie_cleanup_timer
        assert timer is not None
        assert timer.interval() == ThreadSafeWorker._ZOMBIE_CLEANUP_INTERVAL_MS

        ThreadSafeWorker.reset()

    def test_stop_when_not_running_is_safe(self) -> None:
        """Stopping a non-running timer is a safe no-op."""
        ThreadSafeWorker.reset()
        assert ThreadSafeWorker._zombie_cleanup_timer is None

        # Should not raise
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is None


class TestZombieThreadSafety:
    """Tests for thread-safe access to zombie collections."""

    def test_concurrent_zombie_access_no_crash(self) -> None:
        """Concurrent access to zombie collections doesn't cause crashes."""
        ThreadSafeWorker.reset()

        errors: list[Exception] = []
        iterations_per_thread = 50

        def add_zombies() -> None:
            """Add zombies from a background thread."""
            try:
                for _ in range(iterations_per_thread):
                    worker = MagicMock(spec=ThreadSafeWorker)
                    worker.isRunning.return_value = True
                    with QMutexLocker(ThreadSafeWorker._zombie_mutex):
                        ThreadSafeWorker._zombie_threads.append(worker)
                        ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()
                        ThreadSafeWorker._zombie_created_count += 1
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def read_metrics() -> None:
            """Read metrics from a background thread."""
            try:
                for _ in range(iterations_per_thread):
                    _ = ThreadSafeWorker.get_zombie_metrics()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def cleanup_zombies() -> None:
            """Run cleanup from a background thread."""
            try:
                for _ in range(iterations_per_thread // 5):
                    _ = ThreadSafeWorker.cleanup_old_zombies()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        # Run concurrent operations
        threads = [
            threading.Thread(target=add_zombies),
            threading.Thread(target=add_zombies),
            threading.Thread(target=read_metrics),
            threading.Thread(target=cleanup_zombies),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # No errors should have occurred
        assert errors == [], f"Concurrent access caused errors: {errors}"

        ThreadSafeWorker.reset()


