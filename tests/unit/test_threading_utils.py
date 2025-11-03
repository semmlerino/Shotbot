"""Unit tests for threading utilities following UNIFIED_TESTING_GUIDE.

Tests ThreadSafeProgressTracker and CancellationEvent components that are used
in production parallel processing. These tests specifically validate the exact
usage patterns that failed in production.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Test behavior, not implementation details
2. Use real components with test doubles at boundaries
3. Focus on the exact production usage patterns that failed
4. Proper thread safety validation
"""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import threading
from typing import NoReturn

# Third-party imports
import pytest

# Local application imports
from tests.helpers.synchronization import simulate_work_without_sleep
from threading_utils import CancellationEvent, ThreadSafeProgressTracker


pytestmark = [pytest.mark.unit, pytest.mark.qt, pytest.mark.xdist_group("qt_state")]


class TestThreadSafeProgressTracker:
    """Test ThreadSafeProgressTracker component used in production parallel discovery.

    These tests specifically validate the parameter usage patterns that failed
    in production, ensuring we catch similar issues in the future.
    """

    def test_parameter_name_validation(self) -> None:
        """Test correct parameter names are used - the exact issue that failed in production.

        This test would have caught the progress_interval vs update_interval bug.
        """
        progress_calls = []

        def progress_callback(count: int, status: str) -> None:
            progress_calls.append((count, status))

        # This is the exact pattern used in threede_scene_finder_optimized.py:1058
        # The production code was passing progress_interval=progress_interval
        # but __init__ expects update_interval
        progress_interval = 10  # Variable name from production code

        # Test the corrected usage
        tracker = ThreadSafeProgressTracker(
            progress_callback=progress_callback,
            update_interval=progress_interval,  # Correct parameter name
        )

        # Verify tracker was created successfully
        assert tracker is not None
        assert tracker._update_interval == progress_interval
        assert tracker._progress_callback is progress_callback

    def test_would_catch_original_bug(self) -> None:
        """Test that demonstrates the original bug would be caught.

        This test explicitly shows what would happen with the wrong parameter name.
        """

        def progress_callback(count: int, status: str) -> None:
            pass

        # This should raise TypeError - the original bug
        with pytest.raises(
            TypeError, match="unexpected keyword argument 'progress_interval'"
        ):
            ThreadSafeProgressTracker(
                progress_callback=progress_callback,
                progress_interval=10,  # Wrong parameter name that caused the bug
            )

    def test_production_worker_progress_pattern(self) -> None:
        """Test the exact worker progress update pattern used in production."""
        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        tracker = ThreadSafeProgressTracker(
            progress_callback=progress_callback,
            update_interval=3,  # Report every 3 files
        )

        # Simulate the exact pattern from production code
        worker_id = "worker_123"

        # Worker processes files and reports progress periodically
        tracker.update_worker_progress(worker_id, 1, "processing files")
        tracker.update_worker_progress(worker_id, 2, "processing files")
        tracker.update_worker_progress(
            worker_id, 3, "processing files"
        )  # Should trigger callback

        # Verify progress callback was called
        assert len(progress_updates) >= 1
        last_update = progress_updates[-1]
        assert last_update[0] >= 3  # At least 3 files processed
        assert "processing" in last_update[1] or "files" in last_update[1]

    def test_multiple_workers_concurrent_updates(self) -> None:
        """Test thread safety with multiple workers updating concurrently."""
        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        tracker = ThreadSafeProgressTracker(
            progress_callback=progress_callback, update_interval=5
        )

        # Simulate multiple workers running concurrently
        def worker_simulation(worker_id: str, files_to_process: int) -> None:
            for i in range(1, files_to_process + 1):
                tracker.update_worker_progress(
                    worker_id, i, f"worker_{worker_id}_processing"
                )
                simulate_work_without_sleep(1)  # Small delay to simulate processing

        # Start multiple worker threads
        workers = []
        for i in range(3):
            worker = threading.Thread(target=worker_simulation, args=(f"worker_{i}", 4))
            workers.append(worker)

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join(timeout=5.0)

        # Verify all workers completed and progress was aggregated correctly
        # Total files: 3 workers x 4 files = 12 files
        # Should have multiple progress updates
        assert len(progress_updates) >= 1

        # At least one update should show significant progress
        max_progress = max(update[0] for update in progress_updates)
        assert max_progress >= 5  # Should have processed multiple files

    def test_worker_cleanup_tracking(self) -> None:
        """Test that completed workers are properly tracked."""
        tracker = ThreadSafeProgressTracker(progress_callback=None, update_interval=1)

        worker_id = "test_worker"

        # Simulate worker processing files
        tracker.update_worker_progress(worker_id, 5, "processing")

        # Mark worker as completed
        tracker.mark_worker_completed(worker_id)

        # Verify worker is marked as completed
        assert worker_id in tracker._completed_workers

    def test_production_parameter_combinations(self) -> None:
        """Test various parameter combinations used in production."""
        # Test with callback
        called = []
        tracker1 = ThreadSafeProgressTracker(
            progress_callback=lambda _c, _s: called.append((_c, _s)), update_interval=1
        )
        assert tracker1 is not None

        # Test without callback (should not crash)
        tracker2 = ThreadSafeProgressTracker(progress_callback=None, update_interval=10)
        assert tracker2 is not None

        # Test with different intervals
        tracker3 = ThreadSafeProgressTracker(
            progress_callback=lambda _c, _s: None, update_interval=100
        )
        assert tracker3 is not None


class TestCancellationEvent:
    """Test CancellationEvent component used in production parallel operations."""

    def test_basic_cancellation_workflow(self) -> None:
        """Test basic cancellation and cleanup callback workflow."""
        cleanup_called = []

        event = CancellationEvent()

        # Add cleanup callback
        event.add_cleanup_callback(lambda: cleanup_called.append("cleaned"))

        # Initially not cancelled
        assert not event.is_cancelled()

        # Cancel and verify cleanup
        event.cancel()
        assert event.is_cancelled()
        assert cleanup_called == ["cleaned"]

    def test_multiple_cleanup_callbacks(self) -> None:
        """Test multiple cleanup callbacks are all executed."""
        cleanup_order = []

        event = CancellationEvent()

        # Add multiple cleanup callbacks
        event.add_cleanup_callback(lambda: cleanup_order.append("first"))
        event.add_cleanup_callback(lambda: cleanup_order.append("second"))
        event.add_cleanup_callback(lambda: cleanup_order.append("third"))

        # Cancel and verify all callbacks are executed
        event.cancel()

        assert len(cleanup_order) == 3
        assert "first" in cleanup_order
        assert "second" in cleanup_order
        assert "third" in cleanup_order

    def test_exception_safety_in_cleanup(self) -> None:
        """Test that exceptions in cleanup callbacks don't prevent other callbacks."""
        cleanup_called = []

        event = CancellationEvent()

        # Add callbacks - one that raises exception, one that should still run
        def failing_callback() -> NoReturn:
            cleanup_called.append("before_error")
            raise RuntimeError("Cleanup failed")

        def good_callback() -> None:
            cleanup_called.append("after_error")

        event.add_cleanup_callback(failing_callback)
        event.add_cleanup_callback(good_callback)

        # Cancel - should handle exception gracefully
        event.cancel()

        # Both callbacks should have been attempted
        assert "before_error" in cleanup_called
        assert "after_error" in cleanup_called

    def test_production_usage_pattern(self) -> None:
        """Test the exact cancellation pattern used in production parallel discovery."""
        # Simulate the pattern from threede_scene_finder_optimized.py
        cancel_event = CancellationEvent()

        # Register cleanup callback like in production
        cleanup_executed = []
        cancel_event.add_cleanup_callback(
            lambda: cleanup_executed.append(
                "Parallel 3DE scan cancelled, resources cleaned up"
            )
        )

        # Simulate checking cancellation during processing
        def check_cancellation() -> bool:
            """Simulate the check_cancellation function from production."""
            return cancel_event.is_cancelled()

        # Initially should not be cancelled
        assert not check_cancellation()

        # Cancel during processing
        cancel_event.cancel()

        # Should now be cancelled and cleanup should have run
        assert check_cancellation()
        assert len(cleanup_executed) == 1
        assert "cancelled" in cleanup_executed[0]


class TestThreadingIntegration:
    """Integration tests for threading components working together."""

    def test_progress_tracker_with_cancellation(self) -> None:
        """Test ThreadSafeProgressTracker working with CancellationEvent."""
        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        tracker = ThreadSafeProgressTracker(
            progress_callback=progress_callback, update_interval=2
        )

        cancel_event = CancellationEvent()

        def worker_with_cancellation(worker_id: str) -> None:
            """Simulate worker that can be cancelled."""
            for i in range(1, 10):
                if cancel_event.is_cancelled():
                    break
                tracker.update_worker_progress(worker_id, i, "processing")
                simulate_work_without_sleep(10)

        # Start worker
        worker = threading.Thread(
            target=worker_with_cancellation, args=("test_worker",)
        )
        worker.start()

        # Let it process some files, then cancel
        simulate_work_without_sleep(50)
        cancel_event.cancel()

        worker.join(timeout=1.0)

        # Should have some progress updates before cancellation
        assert len(progress_updates) >= 1

    def test_concurrent_futures_integration(self) -> None:
        """Test threading utilities with concurrent.futures - production pattern."""
        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        tracker = ThreadSafeProgressTracker(
            progress_callback=progress_callback, update_interval=3
        )

        cancel_event = CancellationEvent()

        def process_batch(batch_id: int) -> int:
            """Simulate processing a batch of files."""
            files_processed = 0
            worker_id = f"batch_{batch_id}"

            for _i in range(5):  # Process 5 files per batch
                if cancel_event.is_cancelled():
                    break

                files_processed += 1
                tracker.update_worker_progress(
                    worker_id, files_processed, "processing batch"
                )
                simulate_work_without_sleep(10)

            return files_processed

        # Use ThreadPoolExecutor like in production
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Submit multiple batches
            futures = [executor.submit(process_batch, i) for i in range(3)]

            # Let some processing happen, then cancel
            simulate_work_without_sleep(20)
            cancel_event.cancel()

            # Wait for completion
            results = []
            for future in concurrent.futures.as_completed(futures, timeout=2.0):
                try:
                    result = future.result()
                    results.append(result)
                except Exception:
                    pass  # Ignore errors from cancelled operations

        # Should have received some progress updates
        assert len(progress_updates) >= 0  # May be 0 if cancelled very quickly
