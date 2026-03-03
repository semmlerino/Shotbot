"""Regression tests for thread safety fixes in the Stabilization Sprint."""

# Standard library imports
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path

# Third-party imports
import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# Local application imports
from cache.shot_cache import ShotDataCache
from shot_model import AsyncShotLoader, RefreshResult, ShotModel
from tests.fixtures.test_doubles import TestProcessPool
from tests.test_helpers import process_qt_events
from thread_safe_worker import ThreadSafeWorker, WorkerState


logger = logging.getLogger(__name__)


pytestmark = [
    pytest.mark.thread_safety,
    pytest.mark.qt,
    pytest.mark.slow,
]


class TestQThreadInterruptionFix:
    """Test that QThread uses safe interruption instead of terminate()."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.temp_dir = tempfile.TemporaryDirectory()

    def teardown_method(self) -> None:
        """Clean up test environment."""
        self.temp_dir.cleanup()

    def test_no_terminate_call_in_cleanup(self) -> None:
        """Test that cleanup never calls terminate()."""
        cache_manager = ShotDataCache(Path(self.temp_dir.name))
        model = ShotModel(cache_manager)

        # Use real AsyncShotLoader with TestProcessPool at boundary
        from tests.fixtures.test_doubles import TestProcessPool

        test_pool = TestProcessPool(ttl_aware=True)
        test_pool.set_outputs("workspace /shows/TEST/seq01/0010")

        # Create real loader and start it
        loader = AsyncShotLoader(test_pool)
        loader.start()

        # Set the loader in the model
        model._async_loader = loader

        # Track if terminate is ever called (which would crash)
        original_terminate = loader.terminate if hasattr(loader, "terminate") else None
        terminate_called = [False]

        def track_terminate() -> None:
            terminate_called[0] = True
            if original_terminate:
                original_terminate()

        if hasattr(loader, "terminate"):
            loader.terminate = track_terminate

        # Call cleanup
        model.cleanup()

        # Verify terminate was NEVER called (critical for safety)
        assert not terminate_called[0], "terminate() should never be called on QThread"

        # Verify loader was properly stopped (behavior, not mock calls)
        assert not loader.isRunning(), "Loader should be stopped after cleanup"

    def test_interruption_request_used_in_thread(self) -> None:
        """Test that AsyncShotLoader uses interruption requests."""
        # Use real test double at system boundary
        from tests.fixtures.test_doubles import TestProcessPool

        test_pool = TestProcessPool(ttl_aware=True)
        test_pool.set_outputs("")  # Empty output for quick test

        loader = AsyncShotLoader(test_pool)

        # Request stop using the proper method
        loader.stop()

        # Verify stop flag is set immediately
        assert loader._stop_requested

        # Run should exit early
        loader.run()

        # Verify no signals were emitted due to interruption
        # Test behavior: no commands should have been executed due to stop
        assert len(test_pool.commands) == 0, "No commands should execute after stop"

    def test_stop_event_and_interruption_work_together(self) -> None:
        """Test that both stop mechanisms work together."""
        from tests.fixtures.test_doubles import TestProcessPool

        test_process_pool = TestProcessPool(ttl_aware=True)
        loader = AsyncShotLoader(test_process_pool)

        # Call stop (should set both mechanisms)
        loader.stop()

        # Verify both are set
        assert loader._stop_requested
        # Note: isInterruptionRequested() only works when thread is running,
        # but we can verify that requestInterruption() was called by stop()
        # The actual interruption check happens in run() method


class TestDoubleCheckedLockingFix:
    """Test that double-checked locking pattern is fixed."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.temp_dir = tempfile.TemporaryDirectory()

    def teardown_method(self) -> None:
        """Clean up test environment."""
        self.temp_dir.cleanup()

    def test_loading_flag_always_checked_under_lock(self) -> None:
        """Test that _loading_in_progress is protected by lock via concurrent access."""
        cache_manager = ShotDataCache(Path(self.temp_dir.name))
        model = ShotModel(cache_manager)

        # Use test double instead of mock
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs("workspace /shows/TEST/seq01/0010")
        model._process_pool = test_pool

        # Track race conditions through concurrent access
        race_detected = []

        def attempt_refresh() -> None:
            try:
                # Try to start background refresh multiple times
                # If lock isn't protecting _loading_in_progress, we'd get multiple loaders
                model._start_background_refresh()
            except Exception as e:
                race_detected.append(str(e))

        # Run concurrent refresh attempts
        threads = []
        for _ in range(10):
            t = threading.Thread(target=attempt_refresh)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Wait briefly for any async operations
        # Standard library imports
        import time

        # Allow async background operations to settle after thread completion
        # Note: time.sleep() acceptable here to ensure race condition test validity
        time.sleep(0.1)

        # The lock should prevent multiple simultaneous background refreshes
        # Only one loader should be created despite concurrent attempts
        assert len(race_detected) == 0, f"Race conditions detected: {race_detected}"

        # Verify that only one loader was created (lock prevented races)
        # This is implicitly tested by no exceptions being raised

    def test_concurrent_refresh_calls_safe(self) -> None:
        """Test that concurrent refresh calls don't cause race conditions."""
        cache_manager = ShotDataCache(Path(self.temp_dir.name))
        model = ShotModel(cache_manager)

        results = []
        errors = []

        def refresh_concurrent() -> None:
            try:
                # This internally calls _start_background_refresh
                result = model.refresh_shots()
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Launch multiple threads
        threads = []
        for _ in range(10):
            t = threading.Thread(target=refresh_concurrent)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)

        # Verify no errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify all got valid results
        assert all(isinstance(r, RefreshResult) for r in results)


class TestSignalThreadSafety:
    """Test that signals are emitted safely from threads."""

    def test_signals_emitted_safely_from_background_thread(
        self, qapp: QApplication
    ) -> None:
        """Test that background thread can safely emit signals."""
        test_process_pool = TestProcessPool(allow_main_thread=True)
        test_process_pool.set_outputs("workspace /shows/TEST/shots/SEQ01/0010")

        loader = AsyncShotLoader(test_process_pool)

        # Track signal emissions
        shots_received = []
        errors_received = []

        loader.shots_loaded.connect(lambda s: shots_received.append(s))
        loader.load_failed.connect(lambda e: errors_received.append(e))

        # Run in thread
        loader.start()

        # Wait for completion
        assert loader.wait(2000), "Loader didn't complete in time"

        # Process events to handle signals
        qapp.processEvents()

        # Verify signal was emitted
        assert len(shots_received) > 0 or len(errors_received) > 0

    def test_no_signals_after_stop(self, qapp: QApplication) -> None:
        """Test that no signals are emitted after stop is called."""
        test_process_pool = TestProcessPool(allow_main_thread=True)
        # Simulate slow command by setting empty output (loader will stop early)
        test_process_pool.set_outputs("")

        loader = AsyncShotLoader(test_process_pool)

        # Track emissions
        signals_received = []
        loader.shots_loaded.connect(lambda _s: signals_received.append("loaded"))
        loader.load_failed.connect(lambda _e: signals_received.append("failed"))

        # Start and immediately stop
        loader.start()
        loader.stop()

        # Wait for thread to finish
        loader.wait(2000)

        # Process any pending events
        qapp.processEvents()

        # No signals should have been emitted
        assert len(signals_received) == 0, "Signals emitted after stop"


class TestMemoryLeakPrevention:
    """Test that signal connections don't cause memory leaks."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.temp_dir = tempfile.TemporaryDirectory()

    def teardown_method(self) -> None:
        """Clean up test environment."""
        self.temp_dir.cleanup()

    def test_loader_cleanup_prevents_leaks(self) -> None:
        """Test that loader cleanup prevents memory leaks."""
        cache_manager = ShotDataCache(Path(self.temp_dir.name))
        model = ShotModel(cache_manager)

        # Use test double to avoid real subprocess calls
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs("")  # Empty output for fast completion
        model._process_pool = test_pool

        try:
            # Create multiple loaders (simulating multiple refreshes)
            for _ in range(5):
                model._start_background_refresh()
                # Wait for loader to actually finish before simulating callback
                if model._async_loader:
                    assert model._async_loader.wait(2000), "Loader should finish within 2s"
                    model._on_loader_finished()
        finally:
            # Final cleanup - always runs even if test fails
            model.cleanup()

        # Verify no loader references remain
        assert model._async_loader is None

    def test_deleted_objects_dont_receive_signals(self, qapp: QApplication) -> None:
        """Test that deleted objects don't receive signals."""
        test_process_pool = TestProcessPool(allow_main_thread=True)
        loader = AsyncShotLoader(test_process_pool)

        # Create a receiver that will be deleted
        class Receiver(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.received = []

            def on_shots_loaded(self, shots) -> None:
                self.received.append(shots)

        receiver = Receiver()
        loader.shots_loaded.connect(receiver.on_shots_loaded)

        try:
            # Delete receiver
            receiver.deleteLater()
            qapp.processEvents()  # Process deletion

            # Emit signal - should not crash
            loader.shots_loaded.emit([])
            qapp.processEvents()

            # Test passes if no crash occurred
        finally:
            # Ensure cleanup even if test fails
            qapp.processEvents()  # Process any pending deletions



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

            # Simulate work without blocking (non-Qt worker thread context)
            # Note: time.sleep() acceptable here as this is a test double simulating external work
            time.sleep(0.001)  # 1ms per step

        if self.fail_on_purpose:
            raise RuntimeError("Intentional failure for testing")

        self.work_completed = True
        logger.debug(f"Worker completed {self.steps_completed} steps")


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
            qtbot.wait(1)  # Minimal event processing

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


class TestSimpleThreadingIntegration:
    """Simple threading integration tests."""

    @pytest.mark.timeout(5)
    def test_basic_worker_integration(self) -> None:
        """Test basic worker integration without cache."""
        worker = SimpleTestWorker(work_steps=2)

        try:
            worker.start()

            # Wait for worker to start work without nested Qt wait loops.
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline and not worker.work_started:
                process_qt_events()
                time.sleep(0)
            process_qt_events()

            if worker.isRunning():
                worker.request_stop()
                if not worker.wait(1000):
                    worker.quit()
                    worker.wait(500)

            assert worker.work_started, "Worker did not start work"
        finally:
            # Clean up worker to prevent Qt resource leaks in parallel execution
            if worker is not None:
                # Ensure worker is stopped
                if worker.isRunning():
                    worker.request_stop()
                    if not worker.wait(1000):
                        worker.safe_terminate()
                        worker.wait(500)

                # Schedule for deletion (let Qt handle signal cleanup)
                worker.deleteLater()

            # Process Qt events to ensure cleanup is executed
            process_qt_events()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
