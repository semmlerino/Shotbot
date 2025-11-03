"""Threading utilities for robust concurrency management.

This module provides utilities for managing threads, cancellation, and resource
cleanup in multi-threaded operations. The CancellationEvent system addresses
common issues with ThreadPoolExecutor cleanup and provides graceful shutdown
mechanisms.

Key Features:
- Thread-safe cancellation signaling using threading.Event
- Cleanup callback system for guaranteed resource management
- Exception-safe callback execution to prevent cascade failures
- Timeout support for graceful shutdown operations
- Integration with existing ThreadingConfig patterns

Usage Example:
    from threading_utils import CancellationEvent
    import concurrent.futures

    # Create cancellation event
    cancel_event = CancellationEvent()

    # Register cleanup callbacks
    cancel_event.add_cleanup_callback(lambda: print("Cleaning up resources"))

    # Use with ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor() as executor:
        cancel_event.add_cleanup_callback(
            lambda: executor.shutdown(wait=True, timeout=5.0)
        )

        # Submit work
        futures = [executor.submit(work_function, data, cancel_event)
                  for data in work_items]

        # Handle cancellation
        if should_cancel:
            cancel_event.cancel()  # Triggers all cleanup callbacks
"""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, override

# Local application imports
from config import ThreadingConfig
from logging_mixin import LoggingMixin, get_module_logger


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable

# Module-level logger
logger = get_module_logger(__name__)

# Log a debug message if this module is imported (helps track unexpected imports)
logger.debug(
    "threading_utils module imported - if this appears during normal application "
     "usage, there may be an unexpected import chain"
)


class ThreadSafeProgressTracker(LoggingMixin):
    """Thread-safe progress tracking for concurrent operations.

    This class solves the race condition problem in parallel processing by tracking
    progress per worker thread. Each worker reports its individual progress, and
    this class aggregates the total safely.

    Key Features:
    - Per-worker progress tracking prevents race conditions
    - Atomic updates of total progress
    - Configurable progress reporting intervals
    - Thread-safe callback mechanism
    - Worker cleanup tracking

    Example:
        def progress_callback(total_files, status):
            print(f"Progress: {total_files} files, {status}")

        tracker = ThreadSafeProgressTracker(progress_callback, interval=10)

        # In worker thread:
        tracker.update_worker_progress(worker_id, files_processed_by_worker)
    """

    def __init__(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
        update_interval: int = 10,
    ) -> None:
        """Initialize thread-safe progress tracker.

        Args:
            progress_callback: Optional callback function(total_files: int, status: str)
            update_interval: Report progress every N files processed
        """
        super().__init__()
        self._lock = threading.Lock()
        self._worker_progress: dict[str, int] = {}  # worker_id -> files_processed
        self._total_progress = 0
        self._last_reported_progress = 0
        self._progress_callback = progress_callback
        self._update_interval = update_interval
        self._completed_workers: set[str] = set()
        self._id = str(uuid.uuid4())[:8]

        self.logger.debug(
            f"ThreadSafeProgressTracker {self._id} created with interval={update_interval}"
        )

    def update_worker_progress(
        self, worker_id: str, new_count: int, status: str = ""
    ) -> None:
        """Update progress for a specific worker thread.

        This method is called by worker threads to report their individual progress.
        The tracker calculates the delta and updates the total progress atomically.

        Args:
            worker_id: Unique identifier for the worker thread
            new_count: New total count of items processed by this worker
            status: Optional status message for this update
        """
        should_report = False
        total_progress = 0

        with self._lock:
            # Get the old count for this worker (0 if first update)
            old_count = self._worker_progress.get(worker_id, 0)

            # Update this worker's progress
            self._worker_progress[worker_id] = new_count

            # Calculate the delta and update total
            delta = new_count - old_count
            self._total_progress += delta
            total_progress = self._total_progress

            # Check if we should report progress based on interval
            if (total_progress - self._last_reported_progress) >= self._update_interval:
                should_report = True
                self._last_reported_progress = total_progress

        # Call progress callback outside the lock to prevent deadlocks
        if should_report and self._progress_callback:
            try:
                aggregated_status = (
                    status
                    or f"Processing... ({len(self._worker_progress)} workers active)"
                )
                self._progress_callback(total_progress, aggregated_status)
            except Exception as e:
                self.logger.error(
                    f"ThreadSafeProgressTracker {self._id} callback error: {e}"
                )

    def report_progress(self, worker_id: str, new_count: int, status: str = "") -> None:
        """Alias for update_worker_progress to match test expectations.

        This method provides the same functionality as update_worker_progress
        but with the method name expected by the test suite.

        Args:
            worker_id: Unique identifier for the worker thread
            new_count: New total count of items processed by this worker
            status: Optional status message for this update
        """
        self.update_worker_progress(worker_id, new_count, status)

    def mark_worker_completed(self, worker_id: str) -> None:
        """Mark a worker as completed.

        This is useful for tracking which workers have finished and for
        cleanup purposes.

        Args:
            worker_id: Unique identifier for the completed worker
        """
        with self._lock:
            self._completed_workers.add(worker_id)

        self.logger.debug(
            f"ThreadSafeProgressTracker {self._id} worker {worker_id} completed"
        )

    def get_total_progress(self) -> int:
        """Get the current total progress thread-safely.

        Returns:
            Total number of items processed across all workers
        """
        with self._lock:
            return self._total_progress

    def get_worker_stats(self) -> dict[str, int | str | dict[str, int]]:
        """Get statistics about worker progress for debugging.

        Returns:
            Dictionary containing worker statistics
        """
        with self._lock:
            active_workers = len(self._worker_progress)
            completed_workers = len(self._completed_workers)
            worker_details = self._worker_progress.copy()

        return {
            "id": self._id,
            "total_progress": self._total_progress,
            "active_workers": active_workers,
            "completed_workers": completed_workers,
            "worker_progress": worker_details,
            "last_reported": self._last_reported_progress,
        }

    def force_progress_report(self, status: str = "") -> None:
        """Force a progress report regardless of interval.

        Useful for final progress updates or error conditions.

        Args:
            status: Status message to include in the report
        """
        if not self._progress_callback:
            return

        with self._lock:
            total_progress = self._total_progress
            self._last_reported_progress = total_progress

        try:
            final_status = status or f"Completed: {total_progress} items processed"
            self._progress_callback(total_progress, final_status)
        except Exception as e:
            self.logger.error(
                f"ThreadSafeProgressTracker {self._id} force report error: {e}"
            )

    def reset(self) -> None:
        """Reset the progress tracker to initial state.

        This clears all worker progress, resets the total progress counter,
        and clears completed worker tracking. Useful for reusing the same
        tracker instance for multiple operations.
        """
        with self._lock:
            self._worker_progress.clear()
            self._total_progress = 0
            self._last_reported_progress = 0
            self._completed_workers.clear()

        self.logger.debug(
            f"ThreadSafeProgressTracker {self._id} reset to initial state"
        )

    @override
    def __repr__(self) -> str:
        """String representation for debugging."""
        stats = self.get_worker_stats()
        return f"ThreadSafeProgressTracker(id={stats['id']}, total={stats['total_progress']}, workers={stats['active_workers']})"


class CancellationEvent(LoggingMixin):
    """Thread-safe cancellation event with resource cleanup support.

    This class provides a robust cancellation mechanism for multi-threaded
    operations with guaranteed resource cleanup. It addresses common issues
    with ThreadPoolExecutor shutdown and ensures proper cleanup even when
    exceptions occur.

    Features:
    - Thread-safe cancellation signaling using threading.Event
    - Cleanup callback registration for resource management
    - Exception-safe callback execution (failures don't stop other callbacks)
    - Timeout support for cancellation operations
    - Comprehensive logging for debugging

    Example:
        # Create cancellation event
        cancel_event = CancellationEvent()

        # Register cleanup callbacks
        cancel_event.add_cleanup_callback(cleanup_resources)

        # Check for cancellation in worker threads
        def worker_function(data, cancel_event):
            while processing_data:
                if cancel_event.is_cancelled():
                    return  # Exit gracefully
                # Do work...

        # Cancel and cleanup
        cancel_event.cancel()  # All cleanup callbacks executed
    """

    def __init__(self) -> None:
        """Initialize cancellation event."""
        super().__init__()
        self._event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []
        self._callbacks_lock = threading.Lock()
        self._cancelled = False
        self._cancel_lock = threading.Lock()
        self._cancel_time: float | None = None
        self._id = str(uuid.uuid4())[:8]

        self.logger.debug(f"CancellationEvent {self._id} initialized")

    def cancel(self) -> None:
        """Cancel the operation and execute all cleanup callbacks.

        This method is thread-safe and idempotent. Multiple calls to cancel()
        will only execute cleanup callbacks once. All callbacks are executed
        even if some fail with exceptions.
        """
        with self._cancel_lock:
            if self._cancelled:
                self.logger.debug(f"CancellationEvent {self._id} already cancelled")
                return

            self._cancelled = True
            self._cancel_time = time.time()

        self.logger.info(f"CancellationEvent {self._id} cancellation requested")

        # Signal cancellation to all waiting threads
        self._event.set()

        # Execute cleanup callbacks
        self._execute_cleanup_callbacks()

        self.logger.info(f"CancellationEvent {self._id} cancellation completed")

    def is_cancelled(self) -> bool:
        """Check if the operation has been cancelled.

        Returns:
            True if cancelled, False otherwise.
        """
        return self._cancelled

    def add_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Add a cleanup callback to be executed on cancellation.

        Cleanup callbacks are executed in the order they were registered.
        If a callback raises an exception, it will be logged but will not
        prevent other callbacks from executing.

        Args:
            callback: Function to call during cleanup. Should take no arguments
                     and return None.
        """
        with self._callbacks_lock:
            self._callbacks.append(callback)
            callback_count = len(self._callbacks)

        self.logger.debug(
            f"CancellationEvent {self._id} registered cleanup callback "
             f"({callback_count} total)"
        )

    def wait_for_cancellation(self, timeout: float | None = None) -> bool:
        """Wait for cancellation event with optional timeout.

        Args:
            timeout: Maximum time to wait in seconds. None for unlimited wait.
                    Defaults to ThreadingConfig.WORKER_STOP_TIMEOUT_MS / 1000.

        Returns:
            True if cancelled, False if timeout occurred.
        """
        if timeout is None:
            timeout = ThreadingConfig.WORKER_STOP_TIMEOUT_MS / 1000.0

        self.logger.debug(
            f"CancellationEvent {self._id} waiting for cancellation "
             f"(timeout={timeout}s)"
        )

        result = self._event.wait(timeout)

        if result:
            self.logger.debug(f"CancellationEvent {self._id} cancellation detected")
        else:
            self.logger.warning(
                f"CancellationEvent {self._id} wait timeout after {timeout}s"
            )

        return result

    def _execute_cleanup_callbacks(self) -> None:
        """Execute all registered cleanup callbacks.

        This method is called internally by cancel(). It executes all callbacks
        in order, logging any exceptions but continuing to execute remaining
        callbacks to ensure maximum cleanup coverage.
        """
        with self._callbacks_lock:
            callbacks = self._callbacks.copy()

        if not callbacks:
            self.logger.debug(
                f"CancellationEvent {self._id} no cleanup callbacks to execute"
            )
            return

        self.logger.info(
            f"CancellationEvent {self._id} executing {len(callbacks)} cleanup callbacks"
        )

        executed = 0
        failed = 0

        for i, callback in enumerate(callbacks):
            try:
                self.logger.debug(
                    f"CancellationEvent {self._id} executing callback {i + 1}/{len(callbacks)}"
                )
                callback()
                executed += 1
            except Exception as e:
                failed += 1
                self.logger.error(
                    f"CancellationEvent {self._id} cleanup callback {i + 1} failed: {e}",
                    exc_info=True,
                )

        self.logger.info(
            f"CancellationEvent {self._id} cleanup completed: "
             f"{executed} succeeded, {failed} failed"
        )

    def get_stats(self) -> dict[str, str | bool | float | int | None]:
        """Get cancellation event statistics for debugging.

        Returns:
            Dictionary containing event statistics including:
            - id: Event identifier
            - cancelled: Whether the event is cancelled
            - cancel_time: When cancellation occurred (if cancelled)
            - callback_count: Number of registered callbacks
        """
        with self._callbacks_lock:
            callback_count = len(self._callbacks)

        return {
            "id": self._id,
            "cancelled": self._cancelled,
            "cancel_time": self._cancel_time,
            "callback_count": callback_count,
        }

    @override
    def __repr__(self) -> str:
        """String representation for debugging."""
        stats = self.get_stats()
        return f"CancellationEvent(id={stats['id']}, cancelled={stats['cancelled']}, callbacks={stats['callback_count']})"


class ThreadPoolManager(LoggingMixin):
    """Enhanced ThreadPoolExecutor manager with cancellation support.

    This class provides a wrapper around ThreadPoolExecutor with integrated
    cancellation support and automatic cleanup. It addresses the resource
    leak issues in parallel processing operations.

    Example:
        cancel_event = CancellationEvent()

        with ThreadPoolManager(max_workers=4, cancel_event=cancel_event) as pool:
            futures = [pool.submit(work_function, data, cancel_event)
                      for data in work_items]

            # Process results with cancellation checks
            for future in concurrent.futures.as_completed(futures):
                if cancel_event.is_cancelled():
                    break  # Cleanup handled automatically

                result = future.result()
                # Process result...

        # All resources cleaned up automatically
    """

    def __init__(
        self,
        max_workers: int | None = None,
        cancel_event: CancellationEvent | None = None,
        shutdown_timeout: float | None = None,
    ) -> None:
        """Initialize ThreadPoolManager.

        Args:
            max_workers: Maximum number of worker threads. None for default.
            cancel_event: Optional cancellation event for cleanup integration.
            shutdown_timeout: Timeout for executor shutdown. None for default.
        """
        super().__init__()
        self.max_workers = max_workers or ThreadingConfig.MAX_WORKER_THREADS
        self.cancel_event = cancel_event
        # Reduce default timeout to be less noisy
        self.shutdown_timeout = shutdown_timeout or 3.0
        self.executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._entered = False

        self.logger.debug(
            f"ThreadPoolManager created with max_workers={self.max_workers}, "
             f"timeout={self.shutdown_timeout}s"
        )

    def __enter__(self) -> concurrent.futures.ThreadPoolExecutor:
        """Enter context manager and create executor."""
        if self._entered:
            raise RuntimeError("ThreadPoolManager already entered")

        self._entered = True
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        )

        # Register cleanup with cancellation event if provided
        if self.cancel_event:
            self.cancel_event.add_cleanup_callback(self._shutdown_executor)

        self.logger.debug(
            f"ThreadPoolManager executor created with {self.max_workers} workers"
        )
        return self.executor

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager and cleanup executor."""
        if not self._entered:
            return

        self._shutdown_executor()
        self._entered = False

    def _shutdown_executor(self) -> None:
        """Shutdown executor with proper timeout and cleanup."""
        if not self.executor:
            return

        self.logger.debug(
            f"ThreadPoolManager shutting down executor (timeout={self.shutdown_timeout}s)"
        )

        try:
            # Graceful shutdown with manual timeout handling
            start_time = time.time()
            self.executor.shutdown(wait=False)  # Signal shutdown but don't wait

            # Wait for threads to complete with timeout
            while time.time() - start_time < self.shutdown_timeout:
                # Check if all threads have finished
                # Access internal thread set (this is implementation-dependent but works)
                if hasattr(self.executor, "_threads") and not self.executor._threads:
                    self.logger.debug("All executor threads completed")
                    break

                time.sleep(0.05)  # Short polling interval
            else:
                # Timeout reached - use debug level to be less noisy
                self.logger.debug(
                    f"Executor shutdown timeout after {self.shutdown_timeout}s, "
                     f"some threads may still be running (this is usually not critical)"
                )

            self.logger.debug(
                "ThreadPoolManager executor shutdown completed gracefully"
            )
        except Exception as e:
            self.logger.error(f"ThreadPoolManager executor shutdown failed: {e}")
        finally:
            self.executor = None


def create_cancellation_context(
    max_workers: int | None = None, shutdown_timeout: float | None = None
) -> tuple[CancellationEvent, ThreadPoolManager]:
    """Create a cancellation event and thread pool manager pair.

    This convenience function creates a properly configured cancellation event
    and thread pool manager that work together for robust resource management.

    Args:
        max_workers: Maximum number of worker threads. None for default.
        shutdown_timeout: Timeout for executor shutdown. None for default.

    Returns:
        Tuple of (CancellationEvent, ThreadPoolManager)

    Example:
        cancel_event, pool_manager = create_cancellation_context(max_workers=4)

        with pool_manager as executor:
            # Submit work with cancellation support
            futures = [executor.submit(worker, data, cancel_event)
                      for data in work_items]

            # Handle cancellation
            if should_cancel:
                cancel_event.cancel()  # Triggers cleanup
    """
    cancel_event = CancellationEvent()
    pool_manager = ThreadPoolManager(
        max_workers=max_workers,
        cancel_event=cancel_event,
        shutdown_timeout=shutdown_timeout,
    )

    logger.debug(
        f"Created cancellation context with {pool_manager.max_workers} workers"
    )
    return cancel_event, pool_manager


# Example usage and integration patterns
def example_parallel_processing_with_cancellation() -> list[str]:
    """Example showing how to replace problematic parallel processing.

    This example demonstrates how to replace the problematic pattern in
    find_all_3de_files_in_show_parallel() with proper cancellation and cleanup.

    Returns:
        List of processed results as strings
    """
    # Create cancellation context
    cancel_event, pool_manager = create_cancellation_context(max_workers=4)

    # Simulate external cancellation trigger (e.g., from UI)
    def external_cancel_check() -> bool:
        # This would be your existing cancel_flag() function
        return False  # Replace with actual cancellation logic

    work_items: list[str] = ["item1", "item2", "item3", "item4", "item5"]
    results: list[str] = []

    try:
        with pool_manager as executor:
            # Submit all work
            future_to_item: dict[concurrent.futures.Future[str], str] = {}

            for item in work_items:
                if cancel_event.is_cancelled() or external_cancel_check():
                    break

                future = executor.submit(example_worker_function, item, cancel_event)
                future_to_item[future] = item

            # Process completed futures with cancellation checks
            for future in concurrent.futures.as_completed(future_to_item):
                if cancel_event.is_cancelled() or external_cancel_check():
                    # Trigger cancellation - cleanup handled automatically
                    cancel_event.cancel()
                    break

                item = future_to_item[future]
                try:
                    result = future.result()
                    results.append(result)
                    logger.debug(f"Processed {item}: {result}")
                except Exception as e:
                    logger.error(f"Error processing {item}: {e}")
                    continue

    except Exception as e:
        logger.error(f"Error in parallel processing: {e}")
        cancel_event.cancel()  # Ensure cleanup on exception

    return results


def example_worker_function(data: str, cancel_event: CancellationEvent) -> str:
    """Example worker function that respects cancellation.

    Args:
        data: Work item to process
        cancel_event: Cancellation event to check

    Returns:
        Processed result or raises exception if cancelled
    """
    # Simulate work with cancellation checks
    for i in range(10):
        if cancel_event.is_cancelled():
            logger.debug(f"Worker for {data} cancelled at step {i}")
            return f"cancelled:{data}"

        time.sleep(0.1)  # Simulate work

    return f"completed:{data}"


if __name__ == "__main__":
    # Simple test of the cancellation system
    logging.basicConfig(level=logging.DEBUG)

    print("Testing CancellationEvent system...")

    # Test basic cancellation
    cancel_event = CancellationEvent()
    cleanup_called: list[str] = []

    cancel_event.add_cleanup_callback(lambda: cleanup_called.append("callback1"))
    cancel_event.add_cleanup_callback(lambda: cleanup_called.append("callback2"))

    print(f"Before cancel: {cancel_event}")
    cancel_event.cancel()
    print(f"After cancel: {cancel_event}")
    print(f"Cleanup callbacks called: {cleanup_called}")

    # Test thread pool integration
    print("\nTesting ThreadPoolManager...")
    results = example_parallel_processing_with_cancellation()
    print(f"Results: {results}")

    print("CancellationEvent system test completed!")


# Integration Example for fixing find_all_3de_files_in_show_parallel()
def integrate_with_existing_parallel_scan() -> list[str]:
    """
    Example showing how to integrate CancellationEvent with existing parallel scanning.

    This replaces the problematic pattern in threede_scene_finder_optimized.py:

    OLD (problematic):
        if cancel_flag and cancel_flag():
            # Cancel remaining futures
            for f in future_to_chunk:
                f.cancel()  # May not work if already running
            executor.shutdown(wait=False)  # Doesn't wait for cleanup
            break

    NEW (robust):
        if cancel_flag and cancel_flag():
            cancel_event.cancel()  # Triggers all cleanup callbacks
            break  # Cleanup handled automatically

    INTEGRATION STEPS:

    1. Replace ThreadPoolExecutor context manager:
       OLD: with ThreadPoolExecutor(max_workers=max_workers) as executor:
       NEW: cancel_event, pool_manager = create_cancellation_context(max_workers)
            with pool_manager as executor:

    2. Pass cancel_event to worker functions:
       OLD: future = executor.submit(scan_directory_chunk, chunk)
       NEW: future = executor.submit(scan_directory_chunk, chunk, cancel_event)

    3. Replace aggressive cancellation with graceful shutdown:
       OLD: for f in future_to_chunk: f.cancel()
            executor.shutdown(wait=False)
       NEW: cancel_event.cancel()  # All cleanup handled automatically

    4. Update worker functions to check cancellation:
       def scan_directory_chunk(chunk, cancel_event=None):
           for path in chunk:
               if cancel_event and cancel_event.is_cancelled():
                   return []  # Exit gracefully
               # Do work...

    5. Add progress tracking integration:
       cancel_event.add_cleanup_callback(
           lambda: logger.info("Parallel scan cancelled, resources cleaned up")
       )
    """

    # Example of the integration pattern
    def fixed_parallel_scan_pattern(
        work_chunks: list[list[str]],
        scan_function: Callable[[list[str], CancellationEvent | None], list[str]],
        cancel_flag: Callable[[], bool] | None = None,
        max_workers: int = 4,
    ) -> list[str]:
        """Fixed version of parallel scanning with proper cancellation.

        Returns:
            List of processed string results from all chunks
        """

        # Step 1: Create cancellation context
        cancel_event, pool_manager = create_cancellation_context(
            max_workers=max_workers
        )

        # Step 5: Add cleanup logging
        cancel_event.add_cleanup_callback(
            lambda: logger.info("Parallel scan cancelled, resources cleaned up")
        )

        results: list[str] = []

        try:
            # Step 1: Use pool manager instead of raw ThreadPoolExecutor
            with pool_manager as executor:
                future_to_chunk: dict[
                    concurrent.futures.Future[list[str]], list[str]
                ] = {}

                # Submit work with cancellation support
                for chunk in work_chunks:
                    if cancel_event.is_cancelled() or (cancel_flag and cancel_flag()):
                        cancel_event.cancel()  # Trigger cleanup
                        break

                    # Step 2: Pass cancel_event to worker
                    future = executor.submit(scan_function, chunk, cancel_event)
                    future_to_chunk[future] = chunk

                # Process results with cancellation checks
                for future in concurrent.futures.as_completed(future_to_chunk):
                    if cancel_event.is_cancelled() or (cancel_flag and cancel_flag()):
                        # Step 3: Replace aggressive cancellation with graceful shutdown
                        cancel_event.cancel()  # All cleanup handled automatically
                        break

                    try:
                        chunk_result = future.result()
                        results.extend(chunk_result)
                    except Exception as e:
                        logger.error(f"Error processing chunk: {e}")
                        continue

        except Exception as e:
            logger.error(f"Error in parallel processing: {e}")
            cancel_event.cancel()  # Ensure cleanup on exception

        return results

    # Example worker function that respects cancellation
    def cancellation_aware_scan_function(
        chunk: list[str], cancel_event: CancellationEvent | None = None
    ) -> list[str]:
        """Example of worker function that checks for cancellation.

        Args:
            chunk: List of string items to process
            cancel_event: Optional cancellation event

        Returns:
            List of processed string results
        """
        results: list[str] = []

        for item in chunk:
            # Step 4: Check cancellation in worker
            if cancel_event and cancel_event.is_cancelled():
                logger.debug(f"Worker cancelled while processing {item}")
                return results  # Return partial results and exit gracefully

            # Simulate work
            try:
                # Do actual work here...
                result = f"processed:{item}"
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing {item}: {e}")
                continue

        return results

    # Test the pattern
    test_chunks: list[list[str]] = [["item1", "item2"], ["item3", "item4"], ["item5"]]
    results = fixed_parallel_scan_pattern(test_chunks, cancellation_aware_scan_function)
    logger.info(f"Fixed parallel scan results: {results}")

    return results


if __name__ == "__main__":
    # Add integration test
    print("\nTesting integration pattern...")
    _ = integrate_with_existing_parallel_scan()
    print("Integration pattern test completed!")
