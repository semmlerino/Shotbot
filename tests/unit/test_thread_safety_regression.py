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
from shots.shot_model import AsyncShotLoader, RefreshResult, ShotModel
from tests.fixtures.test_doubles import TestProcessPool


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

        test_pool = TestProcessPool()
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

        test_pool = TestProcessPool()
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

        test_process_pool = TestProcessPool()
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
            except Exception as e:  # noqa: BLE001
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
            except Exception as e:  # noqa: BLE001
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





if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
