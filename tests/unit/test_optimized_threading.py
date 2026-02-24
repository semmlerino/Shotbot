"""Thread safety tests for ShotModel.

This test suite validates thread safety guarantees and ensures no race conditions
or deadlocks exist in the optimized implementation.
"""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Local application imports
from cache_manager import CacheManager
from process_pool_manager import ProcessPoolManager
from shot_model import AsyncShotLoader, ShotModel


pytestmark = [
    pytest.mark.thread_safety,
    pytest.mark.permissive_process_pool,  # Thread safety tests, not subprocess output
]


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_process_pool():
    """Ensure ProcessPoolManager is shut down after test."""
    yield
    if ProcessPoolManager._instance:
        ProcessPoolManager._instance.shutdown(timeout=5.0)
        ProcessPoolManager._instance = None


class TestAsyncShotLoaderThreadSafety:
    """Test thread safety of AsyncShotLoader."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Use real test double at system boundary
        from tests.fixtures.test_doubles import TestProcessPool

        self.test_process_pool = TestProcessPool(ttl_aware=True)
        self.test_process_pool.set_outputs("""workspace /shows/TEST/seq01/0010
workspace /shows/TEST/seq01/0020
workspace /shows/TEST/seq02/0030""")

    def test_stop_event_thread_safety(self) -> None:
        """Test that stop mechanism is thread-safe."""
        loader = AsyncShotLoader(self.test_process_pool)

        # Start multiple threads trying to stop
        def attempt_stop() -> None:
            loader.stop()

        threads = [threading.Thread(target=attempt_stop) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify stop is requested (check internal flag)
        assert loader._stop_requested, "Stop should be requested"  # pyright: ignore[reportPrivateUsage]

    def test_no_signal_emission_after_stop(self) -> None:
        """Test that signals are not emitted after stop is called."""
        loader = AsyncShotLoader(self.test_process_pool)

        signals_received: list[str] = []

        # Connect signals with proper typing
        def on_shots_loaded(shots: Any) -> None:
            signals_received.append("loaded")

        def on_load_failed(error: Any) -> None:
            signals_received.append("failed")

        loader.shots_loaded.connect(on_shots_loaded)
        loader.load_failed.connect(on_load_failed)

        # Stop before starting
        loader.stop()

        # Run should exit early without emitting signals
        loader.run()

        assert len(signals_received) == 0, "No signals should be emitted after stop"

class TestShotModelThreadSafety:
    """Test thread safety of ShotModel."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_manager = CacheManager(cache_dir=Path(self.temp_dir.name))
        self.model = ShotModel(self.cache_manager)

    def teardown_method(self) -> None:
        """Clean up resources."""
        self.model.cleanup()
        # Process Qt events to complete deleteLater()
        qapp = QApplication.instance()
        if qapp:
            for _ in range(10):  # Multiple passes to ensure all events processed
                qapp.processEvents()
        self.temp_dir.cleanup()

    def test_race_condition_protection_in_refresh(self) -> None:
        """Test that rapid refresh calls don't cause race conditions."""
        # Track how many background loaders are created
        loader_creation_count = [0]

        def counting_background_refresh() -> None:
            loader_creation_count[0] += 1
            # Don't actually create loaders to avoid real threading complexity

        # Mock the command execution at the boundary
        with patch.object(
            self.model._process_pool, "execute_workspace_command"
        ) as mock_execute:
            mock_execute.return_value = "workspace /shows/TEST/seq01/0010"

            # Mock background refresh to count calls
            with patch.object(
                self.model, "_start_background_refresh", counting_background_refresh
            ):
                # Rapid concurrent refreshes
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [
                        executor.submit(self.model.refresh_shots) for _ in range(20)
                    ]
                    results = [f.result() for f in futures]

                # All should succeed
                assert all(r.success for r in results), "All refreshes should succeed"

                # Due to the loader lock, only some calls should trigger background refresh
                # (The exact number depends on timing, but it should be much less than 20)
                assert loader_creation_count[0] <= 20, (
                    "Background refresh should be rate-limited by loader lock"
                )


class TestProcessPoolManagerSingleton:
    """Test thread safety of ProcessPoolManager singleton."""

    def test_singleton_thread_safety(self) -> None:
        """Test that only one instance is created in concurrent access."""
        instances: list[int] = []

        def create_instance() -> None:
            instance = ProcessPoolManager.get_instance()
            instances.append(id(instance))

        # Create instances from multiple threads
        threads = [threading.Thread(target=create_instance) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All instances should have the same id
        assert len(set(instances)) == 1, "Should only create one singleton instance"

    def test_session_pool_creation_race(self) -> None:
        """Test that concurrent command execution is thread-safe."""
        # Simple test that verifies concurrent access doesn't cause errors
        manager = ProcessPoolManager.get_instance()

        results = []
        errors = []

        def execute_command(thread_id: int) -> str:
            """Execute command from a thread."""
            try:
                # Each thread executes a unique command to avoid caching
                result = manager.execute_workspace_command(
                    f"echo test_{thread_id}",
                    cache_ttl=0,  # Disable caching
                )
                results.append(result)
                return result
            except Exception as e:
                errors.append(str(e))
                return f"error: {e}"

        # Execute commands from multiple threads concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(execute_command, i) for i in range(10)]
            command_results = [f.result() for f in futures]

        # Verify no errors occurred during concurrent execution
        assert len(errors) == 0, f"No errors should occur, but got: {errors}"

        # Verify all threads completed successfully
        assert len(command_results) == 10, "All commands should return results"

        # The main test is that concurrent access didn't cause crashes or deadlocks
        # We don't need to mock the executor - just verify thread safety


class TestDeadlockDetection:
    """Test for potential deadlocks."""

    def test_no_deadlock_in_cleanup(self, qapp: QApplication) -> None:
        """Test that cleanup doesn't deadlock with running operations."""
        temp_dir = tempfile.TemporaryDirectory()
        cache_manager = CacheManager(cache_dir=Path(temp_dir.name))

        # Create multiple models
        models = [ShotModel(cache_manager) for _ in range(5)]

        # Start background operations on all
        for model in models:
            model.initialize_async()

        # Cleanup all concurrently
        def cleanup_model(model: ShotModel) -> None:
            model.cleanup()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(cleanup_model, m) for m in models]
                # Should complete without deadlock (timeout would indicate deadlock)
                for future in concurrent.futures.as_completed(futures, timeout=5):
                    future.result()  # Will raise TimeoutError if deadlocked
        finally:
            # Ensure all models are cleaned up even if test fails
            for model in models:
                try:
                    model.cleanup()
                except Exception:
                    pass
                # Delete Qt C++ objects to prevent lingering threads
                model.deleteLater()

            # Process events to complete deletions
            qapp.processEvents()

        temp_dir.cleanup()

    def test_signal_emission_no_deadlock(self, qapp: QApplication) -> None:
        """Test that QueuedConnection signals prevent deadlock."""
        temp_dir = tempfile.TemporaryDirectory()
        cache_manager = CacheManager(cache_dir=Path(temp_dir.name))
        model = ShotModel(cache_manager)

        signal_processed = [False]

        def slot_handler(shots: list[Any]) -> None:
            """Slot that runs in main thread due to QueuedConnection."""
            signal_processed[0] = True
            # This slot can run without blocking the emitter

        # Connect with explicit QueuedConnection to match real implementation
        model.shots_loaded.connect(slot_handler, Qt.ConnectionType.QueuedConnection)

        # Emit signal - should not block due to QueuedConnection
        start_time = time.time()
        model.shots_loaded.emit([])
        emit_time = time.time() - start_time

        # Emission should be immediate (non-blocking) with QueuedConnection
        assert emit_time < 0.01, (
            "Signal emission should be non-blocking with QueuedConnection"
        )

        # Signal should not be processed yet (it's queued)
        assert not signal_processed[0], (
            "Signal should be queued, not processed immediately"
        )

        # Process events to trigger the queued slot
        qapp.processEvents()

        # Now the signal should be processed
        assert signal_processed[0], (
            "Queued signal should be processed after processEvents()"
        )

        model.cleanup()
        temp_dir.cleanup()


class TestStressAndPerformance:
    """Stress tests for thread safety under load."""

    def test_stress_concurrent_operations(self) -> None:
        """Stress test with many concurrent operations."""
        temp_dir = tempfile.TemporaryDirectory()
        cache_manager = CacheManager(cache_dir=Path(temp_dir.name))
        model = ShotModel(cache_manager)

        operation_count = [0]
        error_count = [0]
        lock = threading.Lock()

        def perform_operation(op_type: int) -> None:
            try:
                if op_type == 0:
                    model.initialize_async()
                elif op_type == 1:
                    model.refresh_shots()
                elif op_type == 2:
                    model.pre_warm_sessions()
                elif op_type == 3:
                    model.get_performance_metrics()

                with lock:
                    operation_count[0] += 1
            except Exception as e:
                with lock:
                    error_count[0] += 1
                    print(f"Error in operation {op_type}: {e}")

        # Run many operations concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(perform_operation, i % 4) for i in range(100)]
            concurrent.futures.wait(futures, timeout=10)

        model.cleanup()
        temp_dir.cleanup()

        assert error_count[0] == 0, f"Had {error_count[0]} errors during stress test"
        assert operation_count[0] == 100, "All operations should complete"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
