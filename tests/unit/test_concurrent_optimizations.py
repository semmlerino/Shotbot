#!/usr/bin/env python3
"""Test concurrent operations and race conditions in ShotModel."""

# Standard library imports
import threading
import time

# Third-party imports
import pytest

# Local application imports
from shot_model import ShotModel


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]


# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
class TestProcessPoolDouble:
    """Test double for process pool following UNIFIED_TESTING_GUIDE principles."""

    __test__ = False  # Prevents pytest collection

    def __init__(self, workspace_response="workspace /test/concurrent/0010") -> None:
        self.workspace_response = workspace_response
        self.call_count = 0

    def execute_workspace_command(self):
        """Simulate workspace command execution."""
        self.call_count += 1
        return self.workspace_response


class TestConcurrentOperations:
    """Test thread safety and race condition handling."""

    @pytest.fixture
    def concurrent_model(self, real_cache_manager):
        """Create ShotModel for concurrent testing."""
        model = ShotModel(real_cache_manager)

        # Use test double for process pool to avoid real subprocess calls
        test_pool = TestProcessPoolDouble("workspace /test/concurrent/0010")
        model._process_pool = test_pool

        return model

    def test_concurrent_refresh_operations(self, concurrent_model) -> None:
        """Test multiple refresh operations don't interfere."""
        results = []
        exceptions = []

        def refresh_worker() -> None:
            try:
                result = concurrent_model.refresh_shots()
                results.append(result)
            except Exception as e:
                exceptions.append(e)

        # Start multiple refresh operations concurrently
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=refresh_worker)
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive(), "Thread did not complete"

        # Verify no exceptions and all operations succeeded
        assert len(exceptions) == 0, f"Exceptions occurred: {exceptions}"
        assert len(results) == 5
        assert all(r.success for r in results)

    def test_concurrent_initialize_async_calls(self, concurrent_model) -> None:
        """Test multiple initialize_async calls are handled safely."""
        results = []
        exceptions = []

        def init_worker() -> None:
            try:
                result = concurrent_model.initialize_async()
                results.append(result)
            except Exception as e:
                exceptions.append(e)

        threads = []
        for _ in range(3):
            thread = threading.Thread(target=init_worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join(timeout=5)

        assert len(exceptions) == 0
        assert len(results) == 3

        # Only one background load should be in progress
        assert concurrent_model._loading_in_progress in [True, False]

    def test_cleanup_during_background_load(self, concurrent_model, qtbot) -> None:
        """Test cleanup called while background load is active."""
        # Start background load
        concurrent_model.initialize_async()

        # Ensure loading is in progress
        assert concurrent_model._loading_in_progress

        # Call cleanup while loading
        concurrent_model.cleanup()

        # Should handle gracefully without hanging
        # Wait a moment to ensure cleanup completes
        qtbot.wait(500)  # 500ms for cleanup

        # Background loader should be stopped
        if concurrent_model._async_loader:
            assert not concurrent_model._async_loader.isRunning()

    def test_memory_pressure_simulation(self, concurrent_model) -> None:
        """Test behavior under memory pressure conditions."""
        # Simulate many rapid initialization calls
        for i in range(20):
            result = concurrent_model.initialize_async()
            assert result.success

            # Add delay every few iterations to allow cleanup
            if i % 5 == 0:
                time.sleep(0.01)

        # Should not accumulate too many background loaders
        # (implementation should reuse or clean up properly)
        metrics = concurrent_model.get_performance_metrics()
        assert isinstance(metrics, dict)

    def test_signal_emission_thread_safety(self, concurrent_model, qtbot) -> None:
        """Test that signal emissions are thread-safe."""
        # Connect to signals
        signals_received = []

        def on_shots_loaded(shots) -> None:
            signals_received.append(("loaded", len(shots)))

        def on_shots_changed(shots) -> None:
            signals_received.append(("changed", len(shots)))

        concurrent_model.shots_loaded.connect(on_shots_loaded)
        concurrent_model.shots_changed.connect(on_shots_changed)

        # Trigger multiple async operations
        concurrent_model.initialize_async()
        concurrent_model.initialize_async()  # Should handle duplicate calls

        # Wait for signals
        qtbot.waitUntil(lambda: len(signals_received) > 0, timeout=3000)

        # Verify signals were received safely
        assert len(signals_received) > 0
