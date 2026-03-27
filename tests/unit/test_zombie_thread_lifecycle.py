"""Tests for ThreadSafeWorker zombie thread lifecycle management.

This module tests the zombie thread mechanism that prevents Qt crashes when
threads fail to stop gracefully. The zombie system:

1. Tracks threads that don't respond to stop requests
2. Prevents garbage collection of running threads (would crash Qt)
3. Periodically cleans up threads that finish naturally
4. Force-terminates threads after a timeout (last resort)

These tests verify the zombie lifecycle using public APIs (get_zombie_metrics(),
cleanup_old_zombies(), reset_for_testing()) rather than private registry state.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QMutex, QObject

from workers import zombie_registry
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


def _make_zombie_mock() -> MagicMock:
    """Create a mock worker configured to become a zombie on safe_terminate().

    Must be called from the main thread (QMutex construction is not safe
    from background threads when pytestqt is processing events).
    """
    mock_worker: MagicMock = MagicMock(spec=ThreadSafeWorker)
    mock_worker._state_mutex = QMutex()
    mock_worker.isRunning.return_value = True
    mock_worker.wait.return_value = False
    return mock_worker


def _make_zombie_via_public_api() -> MagicMock:
    """Create a zombie entry in the registry via the public safe_terminate() API.

    Returns a mock worker that has been registered as a zombie through
    zombie_registry.safe_terminate(). The mock's wait() always returns False
    and isRunning() always returns True, forcing the zombie code path.
    """
    mock_worker = _make_zombie_mock()
    # get_state() returns a MagicMock (not STOPPED/DELETED), so safe_terminate proceeds
    zombie_registry.safe_terminate(mock_worker)
    return mock_worker


class TestZombieCreation:
    """Tests for zombie thread creation when workers fail to stop."""

    def test_worker_becomes_zombie_when_stop_times_out(self, qtbot: QtBot) -> None:
        """Worker that doesn't stop within timeout becomes a zombie.

        Uses the public safe_terminate() path to simulate what safe_stop() does
        when the worker fails to stop: the worker is registered as a zombie and
        get_zombie_metrics() reflects the creation.
        """
        ThreadSafeWorker.reset()
        initial_metrics = ThreadSafeWorker.get_zombie_metrics()
        assert initial_metrics["created"] == 0
        assert initial_metrics["current"] == 0

        # Inject a zombie via the public safe_terminate() path
        mock_worker = _make_zombie_via_public_api()

        # Metrics should reflect zombie creation
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] >= 1
        assert metrics["current"] >= 1

        # Cleanup
        mock_worker.isRunning.return_value = False
        ThreadSafeWorker.cleanup_old_zombies()
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

        # Inject a zombie via the public safe_terminate() path
        _make_zombie_via_public_api()

        # Registry should track it
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 1
        assert metrics["created"] == 1

        ThreadSafeWorker.reset()

    def test_multiple_zombies_tracked_separately(self) -> None:
        """Multiple zombie threads are tracked independently."""
        ThreadSafeWorker.reset()

        # Inject 3 zombies via the public path
        for _ in range(3):
            _make_zombie_via_public_api()

        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 3
        assert metrics["created"] == 3

        ThreadSafeWorker.reset()


class TestZombieRecovery:
    """Tests for zombie threads that finish naturally."""

    def test_finished_zombie_is_cleaned_up(self) -> None:
        """Zombie that finishes naturally is removed during cleanup."""
        ThreadSafeWorker.reset()

        # Inject a zombie, then simulate it finishing
        mock_worker = _make_zombie_via_public_api()

        initial_count = ThreadSafeWorker.get_zombie_metrics()["current"]
        assert initial_count == 1

        # Simulate the thread finishing naturally
        mock_worker.isRunning.return_value = False

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

        # Inject a zombie that stays running
        _make_zombie_via_public_api()
        # mock_worker.isRunning() returns True by default from _make_zombie_via_public_api

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
        import os

        ThreadSafeWorker.reset()

        # Inject a zombie via the public path
        mock_worker = _make_zombie_via_public_api()

        # Back-date the zombie timestamp to trigger the termination threshold.
        # _ZOMBIE_TERMINATE_AGE_SECONDS is a module constant (not mutable state),
        # read here only to calculate the required age offset.
        old_time = time.time() - zombie_registry._ZOMBIE_TERMINATE_AGE_SECONDS - 10
        zombie_registry._zombie_timestamps[id(mock_worker)] = old_time

        # Run cleanup in test mode (allows terminate())
        original_env = os.environ.get("SHOTBOT_TEST_MODE")
        os.environ["SHOTBOT_TEST_MODE"] = "1"
        try:
            cleaned = ThreadSafeWorker.cleanup_old_zombies()
        finally:
            if original_env is None:
                del os.environ["SHOTBOT_TEST_MODE"]
            else:
                os.environ["SHOTBOT_TEST_MODE"] = original_env

        # Zombie should be force-terminated
        assert cleaned == 1
        mock_worker.terminate.assert_called_once()
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["current"] == 0
        assert metrics["terminated"] == 1

        ThreadSafeWorker.reset()


class TestZombieMetrics:
    """Tests for zombie metrics tracking."""

    def test_reset_clears_metrics(self) -> None:
        """Reset clears all zombie metrics for test isolation."""
        # Add some zombies via the public path to get non-zero counters
        ThreadSafeWorker.reset()
        for _ in range(3):
            _make_zombie_via_public_api()

        pre_reset = ThreadSafeWorker.get_zombie_metrics()
        assert pre_reset["created"] >= 3

        # Reset
        ThreadSafeWorker.reset()

        # All counters should be zero
        metrics = ThreadSafeWorker.get_zombie_metrics()
        assert metrics["created"] == 0
        assert metrics["recovered"] == 0
        assert metrics["terminated"] == 0
        assert metrics["current"] == 0


class TestZombieCleanupTimer:
    """Tests for periodic zombie cleanup timer.

    Note: these tests access zombie_registry._state.cleanup_timer to inspect
    the timer's active/interval state. No public API exists for this inspection —
    the timer is purely internal infrastructure.
    """

    def test_timer_start_stop_and_idempotent(self, qtbot: QtBot) -> None:
        """Timer starts, stops, and multiple starts are idempotent."""
        ThreadSafeWorker.reset()

        # Initially no timer
        assert zombie_registry._state.cleanup_timer is None

        # Start timer
        ThreadSafeWorker.start_zombie_cleanup_timer()
        timer1 = zombie_registry._state.cleanup_timer
        assert timer1 is not None
        assert timer1.isActive()

        # Second start returns same timer (idempotent)
        ThreadSafeWorker.start_zombie_cleanup_timer()
        assert zombie_registry._state.cleanup_timer is timer1

        # Stop timer
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert zombie_registry._state.cleanup_timer is None

        ThreadSafeWorker.reset()

    def test_timer_interval_and_safe_stop(self, qtbot: QtBot) -> None:
        """Timer uses correct interval; stopping when not running is a no-op."""
        ThreadSafeWorker.reset()

        # Stop when not running is safe
        assert zombie_registry._state.cleanup_timer is None
        ThreadSafeWorker.stop_zombie_cleanup_timer()
        assert zombie_registry._state.cleanup_timer is None

        # Started timer has correct interval
        ThreadSafeWorker.start_zombie_cleanup_timer()
        timer = zombie_registry._state.cleanup_timer
        assert timer is not None
        assert timer.interval() == zombie_registry._ZOMBIE_CLEANUP_INTERVAL_MS

        ThreadSafeWorker.reset()


class TestZombieThreadSafety:
    """Tests for thread-safe access to zombie collections."""

    def test_concurrent_zombie_access_no_crash(self) -> None:
        """Concurrent reads/cleanup of zombie collections don't crash.

        Zombies are seeded on the main thread via safe_terminate() (which
        performs heavy Qt operations unsuitable for background threads).
        Background threads only read metrics and run cleanup — the
        operations that must be thread-safe in production.
        """
        ThreadSafeWorker.reset()

        # Seed zombies from the main thread (safe_terminate uses
        # QMutexLocker and Qt methods that crash from background threads
        # when pytestqt is processing events).
        for _ in range(20):
            _make_zombie_via_public_api()

        errors: list[Exception] = []
        iterations = 50

        def read_metrics() -> None:
            try:
                for _ in range(iterations):
                    _ = ThreadSafeWorker.get_zombie_metrics()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def cleanup_zombies() -> None:
            try:
                for _ in range(iterations // 5):
                    _ = ThreadSafeWorker.cleanup_old_zombies()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [
            threading.Thread(target=read_metrics),
            threading.Thread(target=read_metrics),
            threading.Thread(target=cleanup_zombies),
            threading.Thread(target=cleanup_zombies),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"Concurrent access caused errors: {errors}"

        ThreadSafeWorker.reset()
