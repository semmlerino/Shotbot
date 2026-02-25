#!/usr/bin/env python3
"""Test to demonstrate ProcessPoolManager singleton race condition.

These tests verify thread-safety of ProcessPoolManager singleton initialization
under concurrent access conditions.
"""

# Standard library imports
import sys
from pathlib import Path


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

# Standard library imports
import concurrent.futures
import logging
import threading
import time
from typing import Any

# Third-party imports
import pytest


_logger = logging.getLogger(__name__)


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_process_pool():
    """Ensure ProcessPoolManager is shut down after test."""
    yield
    from process_pool_manager import ProcessPoolManager
    if ProcessPoolManager._instance:
        ProcessPoolManager._instance.shutdown(timeout=5.0)
        ProcessPoolManager._instance = None


@pytest.mark.slow
@pytest.mark.xdist_group("process_pool_race")
def test_process_pool_manager_race_condition() -> None:
    """Demonstrate race condition in ProcessPoolManager singleton initialization.

    This test attempts to create multiple ProcessPoolManager instances
    concurrently to expose the duplicate initialization bug.
    """
    # Clear any existing instance first
    # Local application imports
    from process_pool_manager import (
        ProcessPoolManager,
    )

    # Reset singleton state for testing
    ProcessPoolManager._instance = None
    ProcessPoolManager._initialized = False

    instances: list[Any] = []
    initialization_counts: list[int] = []
    errors: list[Exception] = []

    # Track how many times ThreadPoolExecutor is actually created (only happens during init)
    init_call_count = [0]
    actual_init_count = [0]
    init_lock = threading.Lock()

    original_thread_pool_executor = concurrent.futures.ThreadPoolExecutor

    def tracked_executor(*args, **kwargs):
        with init_lock:
            actual_init_count[0] += 1
            _logger.debug("ACTUAL initialization - ThreadPoolExecutor created (count=%d)", actual_init_count[0])
        return original_thread_pool_executor(*args, **kwargs)

    # Patch ThreadPoolExecutor to track actual initialization
    concurrent.futures.ThreadPoolExecutor = tracked_executor

    original_init = ProcessPoolManager.__init__

    def counted_init(self, *args, **kwargs):
        init_call_count[0] += 1
        return original_init(self, *args, **kwargs)

    ProcessPoolManager.__init__ = counted_init

    def create_instance() -> None:
        """Thread worker to create an instance."""
        try:
            instance = ProcessPoolManager()
            instances.append(instance)
            # Check if initialized flag is set (using correct attribute name)
            initialization_counts.append(getattr(instance, "_init_done", False))
        except Exception as e:
            errors.append(e)

    # Create threads to trigger race condition
    # Reduced from 10 to 5 threads to minimize resource usage while still testing concurrency
    threads = []
    for _ in range(5):
        thread = threading.Thread(target=create_instance)
        threads.append(thread)

    # Start all threads at once to maximize race condition probability
    for thread in threads:
        thread.start()

    # Wait for all threads
    for thread in threads:
        thread.join()

    # Restore originals
    ProcessPoolManager.__init__ = original_init
    concurrent.futures.ThreadPoolExecutor = original_thread_pool_executor

    # Analyze results
    _logger.debug("Instances created: %d", len(instances))
    _logger.debug("Unique instances: %d", len({id(i) for i in instances}))
    _logger.debug("Init called: %d times (expected 5)", init_call_count[0])
    _logger.debug("ACTUAL init performed: %d times (expected 1)", actual_init_count[0])
    _logger.debug("Errors: %d", len(errors))

    # The race condition manifests as:
    # 1. All instances should be the same object (singleton)
    assert len({id(i) for i in instances}) == 1, "Multiple instances created!"

    # 2. Actual initialization (past the early return) should only happen once
    assert actual_init_count[0] == 1, (
        f"Actual init performed {actual_init_count[0]} times, expected 1"
    )

    # 3. No errors should occur
    assert len(errors) == 0, f"Errors occurred: {errors}"


@pytest.mark.slow
@pytest.mark.xdist_group("process_pool_race")
def test_process_pool_manager_resource_leak() -> None:
    """Test for resource leaks due to duplicate initialization.

    The duplicate self._initialized = True on line 257 could cause
    resources to be created multiple times.
    """
    # Standard library imports
    import concurrent.futures

    # Local application imports
    from process_pool_manager import (
        ProcessPoolManager,
    )

    # Reset singleton completely
    ProcessPoolManager._instance = None
    ProcessPoolManager._initialized = False

    # Track ThreadPoolExecutor creations
    executor_creations = []
    original_executor_init = concurrent.futures.ThreadPoolExecutor.__init__

    def tracked_executor_init(self, *args, **kwargs):
        executor_creations.append(time.time())
        return original_executor_init(self, *args, **kwargs)

    concurrent.futures.ThreadPoolExecutor.__init__ = tracked_executor_init

    try:
        # Create instance
        ProcessPoolManager()

        # Check for duplicate executor creations
        _logger.debug("Executor creations: %d", len(executor_creations))
        assert len(executor_creations) == 1, "Multiple executors created!"

    finally:
        # Restore original
        concurrent.futures.ThreadPoolExecutor.__init__ = original_executor_init


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_process_pool_manager_race_condition()
    test_process_pool_manager_resource_leak()
    _logger.info("Tests completed - race conditions verified")
