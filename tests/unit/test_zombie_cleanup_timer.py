"""Tests for ThreadSafeWorker periodic zombie cleanup timer."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from thread_safe_worker import ThreadSafeWorker


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


class TestZombieCleanupTimer:
    """Test periodic zombie cleanup timer functionality."""

    def test_timer_starts_and_stops(self, qtbot: QtBot) -> None:
        """Test that zombie cleanup timer can be started and stopped."""
        # Ensure timer is not running initially
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is None

        # Start timer
        ThreadSafeWorker.start_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is not None
        assert ThreadSafeWorker._zombie_cleanup_timer.isActive()

        # Stop timer
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is None

    def test_timer_idempotent_start(self, qtbot: QtBot) -> None:
        """Test that starting timer multiple times is safe."""
        # Ensure timer is not running initially
        ThreadSafeWorker.stop_zombie_cleanup_timer()

        # Start timer twice
        ThreadSafeWorker.start_zombie_cleanup_timer()
        timer1 = ThreadSafeWorker._zombie_cleanup_timer

        ThreadSafeWorker.start_zombie_cleanup_timer()
        timer2 = ThreadSafeWorker._zombie_cleanup_timer

        # Should be same timer instance (idempotent)
        assert timer1 is timer2

        # Cleanup
        ThreadSafeWorker.stop_zombie_cleanup_timer()

    def test_timer_interval_correct(self, qtbot: QtBot) -> None:
        """Test that timer has correct interval."""
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        ThreadSafeWorker.start_zombie_cleanup_timer()

        timer = ThreadSafeWorker._zombie_cleanup_timer
        assert timer is not None
        assert timer.interval() == ThreadSafeWorker._ZOMBIE_CLEANUP_INTERVAL_MS

        ThreadSafeWorker.stop_zombie_cleanup_timer()

    def test_timer_cleanup_callback_works(self, qtbot: QtBot) -> None:
        """Test that timer callback actually cleans up zombies."""
        ThreadSafeWorker.stop_zombie_cleanup_timer()

        # Manually add a finished "zombie" (simulate safe_terminate scenario)
        # Create a worker that finishes immediately
        class QuickWorker(ThreadSafeWorker):
            def do_work(self) -> None:
                pass  # Exits immediately

        worker = QuickWorker()

        try:
            # Start worker and wait for it to finish using Qt's native wait
            # (safer than wait_signal for instant-finishing threads)
            worker.start()
            finished = worker.wait(2000)  # Use Qt's native wait
            assert finished, "Worker did not finish in time"

            # Worker should be finished now
            assert not worker.isRunning()

            # Now manually zombify it (simulate safe_terminate path)
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time() - 61  # Old zombie

            assert len(ThreadSafeWorker._zombie_threads) == 1

            # Manually trigger cleanup (instead of waiting 60s for timer)
            cleaned = ThreadSafeWorker.cleanup_old_zombies()

            # Should have cleaned up the finished worker
            assert cleaned == 1
            assert len(ThreadSafeWorker._zombie_threads) == 0
        finally:
            # Ensure QThread cleanup even if assertions fail
            if worker.isRunning():
                worker.request_stop()
                worker.wait(1000)
            worker.deleteLater()

    def test_timer_doesnt_clean_young_zombies(self, qtbot: QtBot) -> None:
        """Test that timer doesn't terminate recently added still-running zombies.

        Note: Finished zombies ARE removed immediately regardless of age (correct behavior).
        This test verifies that young RUNNING zombies are not terminated.
        """
        ThreadSafeWorker.stop_zombie_cleanup_timer()

        # Create a worker that stays running (uses wait condition)
        class BlockingWorker(ThreadSafeWorker):
            def do_work(self) -> None:
                # Block until stop is requested
                while not self.should_stop():
                    self.msleep(10)

        worker = BlockingWorker()

        try:
            worker.start()
            # Wait for worker to start running
            qtbot.waitUntil(worker.isRunning, timeout=1000)

            # Add as fresh zombie (age = 0) while still running
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()

            assert len(ThreadSafeWorker._zombie_threads) == 1
            assert worker.isRunning()

            # Try cleanup - should NOT remove or terminate (too young AND still running)
            cleaned = ThreadSafeWorker.cleanup_old_zombies()
            assert cleaned == 0
            assert len(ThreadSafeWorker._zombie_threads) == 1
            assert worker.isRunning()  # Still running, not terminated

            # Cleanup manually
            ThreadSafeWorker._zombie_threads.clear()
            ThreadSafeWorker._zombie_timestamps.clear()
        finally:
            # Ensure QThread cleanup
            if worker.isRunning():
                worker.request_stop()
                worker.wait(2000)
            worker.deleteLater()

    def test_timer_cleans_finished_zombies_regardless_of_age(self, qtbot: QtBot) -> None:
        """Test that finished zombies are removed immediately regardless of age."""
        ThreadSafeWorker.stop_zombie_cleanup_timer()

        # Create a worker that finishes quickly
        class QuickWorker(ThreadSafeWorker):
            def do_work(self) -> None:
                pass

        worker = QuickWorker()

        try:
            worker.start()
            assert worker.wait(1000)
            assert not worker.isRunning()  # Worker has finished

            # Add as fresh zombie (age = 0) - but already finished
            ThreadSafeWorker._zombie_threads.append(worker)
            ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()

            assert len(ThreadSafeWorker._zombie_threads) == 1

            # Cleanup should remove finished zombie immediately
            cleaned = ThreadSafeWorker.cleanup_old_zombies()
            assert cleaned == 1  # Finished zombies removed regardless of age
            assert len(ThreadSafeWorker._zombie_threads) == 0
        finally:
            worker.deleteLater()

    def test_stop_timer_when_not_running(self, qtbot: QtBot) -> None:
        """Test that stopping non-running timer is safe."""
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is None

        # Call stop again - should be no-op
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert ThreadSafeWorker._zombie_cleanup_timer is None

    @pytest.fixture(autouse=True)
    def cleanup_timer(self) -> None:
        """Cleanup timer after each test."""
        yield
        # Ensure timer is stopped and zombies cleared
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        ThreadSafeWorker._zombie_threads.clear()
        ThreadSafeWorker._zombie_timestamps.clear()
