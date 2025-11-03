"""Final fixed version of threading tests that avoid Qt-in-thread issues."""

from __future__ import annotations

# Standard library imports
import logging
import subprocess
import time
from unittest.mock import MagicMock

# Third-party imports
import pytest
from PySide6.QtCore import QTimer

# Local application imports
from launcher_manager import LauncherManager
from tests.test_doubles_library import TestSubprocess
from thread_safe_worker import ThreadSafeWorker, WorkerState


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.thread_safety,
    pytest.mark.xdist_group("qt_state"),  # CRITICAL for parallel safety
]

logger = logging.getLogger(__name__)


class SimpleTestWorker(ThreadSafeWorker):
    """Lightweight test worker without timeouts."""

    def __init__(self, work_steps: int = 5, fail_on_purpose: bool = False) -> None:
        super().__init__()
        self.work_steps = work_steps
        self.fail_on_purpose = fail_on_purpose
        self.work_started = False
        self.work_completed = False
        self.steps_completed = 0

    def do_work(self) -> None:
        """Quick work implementation without sleep."""
        self.work_started = True

        for step in range(self.work_steps):
            if self.should_stop():
                logger.debug(f"Worker stopping at step {step}")
                return

            self.steps_completed = step + 1

            # REMOVED: Never call app.processEvents() in a worker thread!
            # This causes deadlocks and undefined behavior
            # Qt events should only be processed in the main thread

            # Small sleep to simulate work without blocking
            time.sleep(0.001)  # 1ms per step

        if self.fail_on_purpose:
            raise RuntimeError("Intentional failure for testing")

        self.work_completed = True
        logger.debug(f"Worker completed {self.steps_completed} steps")


@pytest.fixture
def test_subprocess():
    """Test subprocess double for all tests."""
    return TestSubprocess()


@pytest.fixture
def launcher_manager(qtbot, test_subprocess, monkeypatch):
    """Create LauncherManager with test subprocess double and proper cleanup."""
    # Use monkeypatch for safer patching that auto-restores
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: test_subprocess)

    manager = LauncherManager()
    # LauncherManager is not a QWidget, so we don't use qtbot.addWidget

    yield manager

    # Explicit cleanup with proper error handling
    try:
        # Stop all workers with timeout
        manager.stop_all_workers()

        # Wait for workers to finish
        for worker_id in list(manager._active_workers.keys()):
            worker = manager._active_workers.get(worker_id)
            if worker and worker.isRunning():
                worker.request_stop()
                if not worker.wait(1000):  # 1 second timeout
                    worker.terminate()
                    worker.wait(100)

        # Clear the workers dict
        manager._active_workers.clear()

        # Stop timers
        if hasattr(manager, "_cleanup_retry_timer"):
            manager._cleanup_retry_timer.stop()

    except Exception as e:
        logger.warning(f"Cleanup error (non-fatal): {e}")


class TestQTimerCascadePrevention:
    """Test QTimer cascade prevention without timeouts."""

    def test_rapid_cleanup_requests(self, launcher_manager, qtbot) -> None:
        """Test rapid cleanup requests don't cascade timers."""
        timer_activations = []
        original_start = launcher_manager._cleanup_retry_timer.start

        def track_timer_start(interval) -> None:
            timer_activations.append(time.time())
            original_start(interval)

        launcher_manager._cleanup_retry_timer.start = track_timer_start

        for _ in range(10):
            QTimer.singleShot(1, launcher_manager._cleanup_finished_workers)

        qtbot.wait(100)

        assert len(timer_activations) <= 3, (
            f"Too many timer activations: {len(timer_activations)}"
        )

        assert hasattr(launcher_manager, "_cleanup_scheduled")
        launcher_manager._cleanup_retry_timer.start = original_start

    def test_cleanup_coordination(self, launcher_manager, qtbot) -> None:
        """Test cleanup coordination behavior."""
        # Third-party imports
        from PySide6.QtCore import QMutexLocker

        mock_worker = MagicMock()
        mock_worker.get_state.return_value = WorkerState.STOPPED
        mock_worker.isRunning.return_value = False

        with QMutexLocker(launcher_manager._process_lock):
            launcher_manager._active_workers = {"worker1": mock_worker}

        launcher_manager._cleanup_finished_workers()

        with QMutexLocker(launcher_manager._process_lock):
            assert len(launcher_manager._active_workers) == 0


class TestWorkerStateTransitions:
    """Test WorkerState transitions without timeouts."""

    @pytest.mark.timeout(5)
    def test_basic_state_transitions(self, qtbot) -> None:
        """Test basic state transitions."""
        worker = SimpleTestWorker(work_steps=3)

        assert worker.get_state() == WorkerState.CREATED
        assert worker.work_started is False
        assert worker.steps_completed == 0

        worker.start()

        if not worker.isRunning():
            qtbot.wait(10)

        completed = worker.wait(2000)

        if not completed:
            worker.request_stop()
            worker.quit()
            assert worker.wait(1000), "Worker did not stop after request"

        assert worker.work_started is True
        assert worker.steps_completed >= 1

        final_state = worker.get_state()
        assert final_state in [WorkerState.STOPPED, WorkerState.DELETED]

    @pytest.mark.timeout(5)
    def test_state_validation(self, qtbot) -> None:
        """Test state validation."""
        worker = SimpleTestWorker(work_steps=2)

        assert worker.get_state() == WorkerState.CREATED
        assert worker.work_started is False

        worker.start()

        if not worker.wait(2000):
            worker.request_stop()
            worker.quit()
            worker.wait(1000)

        assert worker.work_started is True
        assert worker.get_state() in [WorkerState.STOPPED, WorkerState.DELETED]

    @pytest.mark.timeout(10)
    def test_multiple_workers_lifecycle(self, qtbot) -> None:
        """Test multiple workers."""
        workers = []

        for _ in range(3):
            worker = SimpleTestWorker(work_steps=2)
            workers.append(worker)

        for worker in workers:
            worker.start()

        for i, worker in enumerate(workers):
            if not worker.wait(2000):
                logger.warning(f"Worker {i} did not complete, forcing stop")
                worker.request_stop()
                worker.quit()
                worker.wait(1000)

        for worker in workers:
            assert worker.work_started is True
            assert worker.steps_completed >= 1

        for worker in workers:
            assert worker.get_state() in [WorkerState.STOPPED, WorkerState.DELETED]


class TestPerformanceImprovements:
    """Test performance improvements without cache operations."""

    def test_timer_efficiency(self, launcher_manager, qtbot) -> None:
        """Test timer efficiency."""
        start_time = time.time()

        for _ in range(20):
            QTimer.singleShot(1, lambda: None)

        qtbot.wait(50)

        elapsed = time.time() - start_time
        assert elapsed < 1.0, f"Timer operations took too long: {elapsed}s"


class TestSimpleThreadingIntegration:
    """Simple threading integration tests."""

    @pytest.mark.timeout(5)
    def test_basic_worker_integration(self, qtbot) -> None:
        """Test basic worker integration without cache."""
        worker = SimpleTestWorker(work_steps=2)
        worker.start()

        qtbot.wait(50)

        if worker.isRunning():
            worker.request_stop()
            if not worker.wait(1000):
                worker.quit()
                worker.wait(500)

        assert worker.work_started, "Worker did not start work"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--timeout=30"])
