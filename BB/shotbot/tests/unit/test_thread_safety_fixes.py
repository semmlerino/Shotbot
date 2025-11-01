"""Unit tests for Qt threading race condition fixes.

Tests the ThreadSafeWorker base class and related threading improvements
to ensure race conditions are properly handled.
"""

import os

# Import our thread-safe components
import sys
import threading
import time
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt, Signal
from PySide6.QtTest import QTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from thread_safe_worker import ThreadSafeWorker


class TestWorker(ThreadSafeWorker):
    """Test implementation of ThreadSafeWorker."""

    test_signal = Signal(str)

    def __init__(self, work_duration: float = 0.1, parent=None):
        super().__init__(parent)
        self.work_duration = work_duration
        self.work_started = False
        self.work_completed = False
        self.exception_to_raise = None

    def do_work(self):
        """Simulate work with configurable duration."""
        self.work_started = True

        if self.exception_to_raise:
            raise self.exception_to_raise

        # Simulate work with non-blocking periodic stop checks

        start_time = time.perf_counter()
        work_duration_sec = self.work_duration

        # Check for stop every 10ms without blocking
        while time.perf_counter() - start_time < work_duration_sec:
            if self.should_stop():  # Use should_stop() for better interruption handling
                break
            # Use QThread.msleep instead of time.sleep for better Qt integration
            self.msleep(10)  # Sleep for 10ms, interruptible by Qt

        self.work_completed = not self.should_stop()
        if self.work_completed:
            self.test_signal.emit("work_done")


class TestThreadSafeWorker:
    """Test ThreadSafeWorker base class."""

    @pytest.fixture
    def worker(self, qapp):
        """Create a test worker."""
        return TestWorker()

    def test_state_transitions(self, worker):
        """Test valid state transitions."""
        # Initial state
        assert worker.get_state() == "CREATED"

        # Valid transitions
        assert worker.set_state("STARTING")
        assert worker.get_state() == "STARTING"

        assert worker.set_state("RUNNING")
        assert worker.get_state() == "RUNNING"

        assert worker.set_state("STOPPING")
        assert worker.get_state() == "STOPPING"

        assert worker.set_state("STOPPED")
        assert worker.get_state() == "STOPPED"

        assert worker.set_state("DELETED")
        assert worker.get_state() == "DELETED"

    def test_invalid_state_transitions(self, worker):
        """Test invalid state transitions are rejected."""
        # Try invalid transition from CREATED to RUNNING
        assert worker.get_state() == "CREATED"
        assert not worker.set_state("RUNNING")
        assert worker.get_state() == "CREATED"  # State unchanged

        # Move to RUNNING properly
        assert worker.set_state("STARTING")
        assert worker.set_state("RUNNING")

        # Try invalid transition from RUNNING to CREATED
        assert not worker.set_state("CREATED")
        assert worker.get_state() == "RUNNING"  # State unchanged

    def test_request_stop_from_created(self, worker):
        """Test stop request from CREATED state."""
        assert worker.get_state() == "CREATED"
        assert worker.request_stop()
        assert worker.get_state() == "STOPPED"
        assert worker.is_stop_requested()

    def test_request_stop_from_running(self, worker):
        """Test stop request from RUNNING state."""
        worker.set_state("STARTING")
        worker.set_state("RUNNING")

        assert worker.request_stop()
        assert worker.get_state() == "STOPPING"
        assert worker.is_stop_requested()

    def test_request_stop_when_already_stopped(self, worker):
        """Test stop request when already stopped."""
        worker.set_state("STARTING")
        worker.set_state("RUNNING")
        worker.set_state("STOPPING")
        worker.set_state("STOPPED")

        assert not worker.request_stop()  # Already stopped
        assert worker.get_state() == "STOPPED"

    def test_normal_execution(self, qtbot, worker):
        """Test normal worker execution."""
        # Start worker
        worker.start()

        # Wait for completion
        assert worker.wait(2000)

        # Check execution
        assert worker.work_started
        assert worker.work_completed
        assert worker.get_state() == "STOPPED"

    def test_stop_during_execution(self, qtbot, worker):
        """Test stopping worker during execution."""
        # Use longer work duration
        worker.work_duration = 1.0

        # Start worker
        worker.start()
        QTest.qWait(100)  # Let it start

        # Request stop
        assert worker.request_stop()

        # Wait for stop
        assert worker.safe_wait(2000)

        # Check it was interrupted
        assert worker.work_started
        assert not worker.work_completed  # Didn't complete
        assert worker.get_state() == "STOPPED"

    def test_exception_handling(self, qtbot, worker):
        """Test exception handling in do_work."""
        # Set up exception
        worker.exception_to_raise = ValueError("Test exception")

        # Track error signal
        with qtbot.waitSignal(worker.worker_error, timeout=2000) as blocker:
            # Start worker
            worker.start()

            # Wait for completion
            assert worker.wait(2000)

        # Check error was emitted
        assert blocker.args[0] == "Test exception"
        # State should be STOPPED or DELETED (if garbage collected)
        assert worker.get_state() in ["STOPPED", "DELETED"]

    def test_safe_terminate(self, qtbot, worker):
        """Test safe termination."""
        # Use very long work duration
        worker.work_duration = 10.0

        # Start worker
        worker.start()
        QTest.qWait(100)  # Let it start

        # Safe terminate
        worker.safe_terminate()

        # Should be stopped
        assert worker.get_state() == "STOPPED"
        assert worker.wait(1000)  # Should finish quickly

    def test_signal_tracking(self, qtbot, worker):
        """Test signal connection tracking."""
        # Create a receiver
        receiver = Mock()

        # Connect using safe_connect
        worker.safe_connect(
            worker.test_signal, receiver.handle_signal, Qt.DirectConnection
        )

        # Check connection is tracked
        assert len(worker._connections) == 1

        # Emit signal
        worker.test_signal.emit("test")
        receiver.handle_signal.assert_called_once_with("test")

        # Disconnect all
        worker.disconnect_all()

        # Check connections cleared
        assert len(worker._connections) == 0

        # Signal should not reach receiver anymore
        receiver.reset_mock()
        worker.test_signal.emit("test2")
        receiver.handle_signal.assert_not_called()

    def test_concurrent_state_access(self, worker):
        """Test concurrent access to state is thread-safe."""
        results = []
        errors = []

        def try_state_transition():
            """Try multiple state transitions."""
            try:
                # Try to move to STARTING
                result = worker.set_state("STARTING")
                results.append(("STARTING", result))

                if result:
                    # Try to move to RUNNING
                    result2 = worker.set_state("RUNNING")
                    results.append(("RUNNING", result2))
            except Exception as e:
                errors.append(e)

        # Start multiple threads trying to change state
        threads = []
        for _ in range(10):
            t = threading.Thread(target=try_state_transition)
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0

        # Only one thread should have succeeded with STARTING
        starting_successes = sum(
            1 for state, result in results if state == "STARTING" and result
        )
        assert starting_successes == 1


class TestLauncherWorkerIntegration:
    """Test LauncherWorker with ThreadSafeWorker base."""

    @pytest.fixture
    def launcher_worker(self, qapp):
        """Create a launcher worker."""
        from launcher_manager import LauncherWorker

        return LauncherWorker(
            launcher_id="test_launcher", command="echo test", working_dir=None
        )

    def test_launcher_worker_lifecycle(self, qtbot, launcher_worker):
        """Test launcher worker follows proper lifecycle."""
        # Track signals
        with qtbot.waitSignal(launcher_worker.command_started, timeout=2000):
            with qtbot.waitSignal(launcher_worker.command_finished, timeout=3000):
                # Start worker
                launcher_worker.start()

                # Wait for completion
                assert launcher_worker.safe_wait(3000)

        # Check state - should be STOPPED or DELETED (if garbage collected)
        assert launcher_worker.get_state() in ["STOPPED", "DELETED"]

    def test_launcher_worker_stop(self, qtbot, launcher_worker):
        """Test stopping launcher worker."""
        # Use a longer-running command
        launcher_worker.command = "sleep 10"

        # Start worker
        launcher_worker.start()
        QTest.qWait(100)  # Let it start

        # Request stop
        assert launcher_worker.request_stop()

        # Should stop quickly
        assert launcher_worker.safe_wait(2000)
        assert launcher_worker.get_state() == "STOPPED"


class TestThreadingStress:
    """Stress tests for threading improvements."""

    def test_rapid_start_stop_cycles(self, qapp, qtbot):
        """Test rapid start/stop cycles don't cause race conditions."""
        workers = []

        for i in range(10):
            worker = TestWorker(work_duration=0.05)
            workers.append(worker)

            # Start worker
            worker.start()

            # Randomly stop some immediately
            if i % 3 == 0:
                worker.request_stop()

        # Wait for all to finish
        for worker in workers:
            assert worker.safe_wait(2000)
            assert worker.get_state() in ["STOPPED", "DELETED"]

    def test_concurrent_cleanup(self, qapp):
        """Test concurrent cleanup operations."""
        from launcher_manager import LauncherManager

        manager = LauncherManager()

        # Start multiple cleanup threads
        threads = []
        errors = []

        def run_cleanup():
            try:
                manager._cleanup_finished_workers()
            except Exception as e:
                errors.append(e)

        for _ in range(5):
            t = threading.Thread(target=run_cleanup)
            threads.append(t)
            t.start()

        # All should complete without deadlock
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive()

        # Should have no errors
        assert len(errors) == 0

    def test_signal_disconnection_during_emission(self, qapp, qtbot):
        """Test disconnecting signals while they're being emitted."""
        worker = TestWorker(work_duration=0.2)

        # Connect multiple receivers
        receivers = [Mock() for _ in range(5)]
        for receiver in receivers:
            worker.safe_connect(
                worker.test_signal, receiver.handle, Qt.QueuedConnection
            )

        # Start worker
        worker.start()

        # Disconnect while running
        QTest.qWait(50)
        worker.disconnect_all()

        # Should still complete without crash
        assert worker.safe_wait(2000)
        assert worker.get_state() == "STOPPED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
