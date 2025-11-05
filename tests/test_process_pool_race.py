#!/usr/bin/env python3
"""Test to demonstrate ProcessPoolManager singleton race condition."""

# Standard library imports
import sys
from pathlib import Path


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

# Standard library imports
import threading
import time
from typing import Any


# Third-party imports


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

    # Track how many times __init__ actually runs past the early return
    original_init = ProcessPoolManager.__init__
    init_call_count = [0]
    actual_init_count = [0]

    def tracked_init(self, *args, **kwargs):
        init_call_count[0] += 1
        was_initialized = ProcessPoolManager._initialized
        result = original_init(self, *args, **kwargs)
        # Check if initialization actually happened (flag changed from False to True)
        if not was_initialized and ProcessPoolManager._initialized:
            actual_init_count[0] += 1
            print(f"ACTUAL initialization performed (count={actual_init_count[0]})")
        return result

    ProcessPoolManager.__init__ = tracked_init

    def create_instance() -> None:
        """Thread worker to create an instance."""
        try:
            instance = ProcessPoolManager()
            instances.append(instance)
            # Check if initialized flag is set
            initialization_counts.append(getattr(instance, "_initialized", False))
        except Exception as e:
            errors.append(e)

    # Create threads to trigger race condition
    threads = []
    for _ in range(10):
        thread = threading.Thread(target=create_instance)
        threads.append(thread)

    # Start all threads at once to maximize race condition probability
    for thread in threads:
        thread.start()

    # Wait for all threads
    for thread in threads:
        thread.join()

    # Restore original init
    ProcessPoolManager.__init__ = original_init

    # Analyze results
    print(f"Instances created: {len(instances)}")
    print(f"Unique instances: {len({id(i) for i in instances})}")
    print(f"Init called: {init_call_count[0]} times (expected 10)")
    print(f"ACTUAL init performed: {actual_init_count[0]} times (expected 1)")
    print(f"Errors: {len(errors)}")

    # The race condition manifests as:
    # 1. All instances should be the same object (singleton)
    assert len({id(i) for i in instances}) == 1, "Multiple instances created!"

    # 2. Actual initialization (past the early return) should only happen once
    assert actual_init_count[0] == 1, (
        f"Actual init performed {actual_init_count[0]} times, expected 1"
    )

    # 3. No errors should occur
    assert len(errors) == 0, f"Errors occurred: {errors}"


def test_process_pool_manager_resource_leak() -> None:
    """Test for resource leaks due to duplicate initialization.

    The duplicate self._initialized = True on line 257 could cause
    resources to be created multiple times.
    """
    # Standard library imports
    import concurrent.futures  # noqa: PLC0415 - lazy import to avoid circular dependency

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
        print(f"Executor creations: {len(executor_creations)}")
        assert len(executor_creations) == 1, "Multiple executors created!"

    finally:
        # Restore original
        concurrent.futures.ThreadPoolExecutor.__init__ = original_executor_init


if __name__ == "__main__":
    test_process_pool_manager_race_condition()
    test_process_pool_manager_resource_leak()
    print("Tests completed - race conditions demonstrated")
