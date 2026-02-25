#!/usr/bin/env python3
"""Simple test to verify file locking works."""

# Standard library imports
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

# Standard library imports
import fcntl
import tempfile
import threading
import time
from pathlib import Path


def test_basic_file_locking() -> None:
    """Test that fcntl file locking works as expected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_file = Path(tmpdir) / "test.lock"
        data_file = Path(tmpdir) / "counter.txt"

        # Initialize counter
        data_file.write_text("0")

        successful_increments = []
        lock_acquisitions = []

        def increment_with_lock(thread_id: int) -> None:
            """Increment counter with proper locking."""
            for i in range(5):
                with lock_file.open("w") as lock_fd:
                    # Acquire exclusive lock
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                    lock_acquisitions.append((thread_id, i))

                    try:
                        # Read
                        current = int(data_file.read_text())

                        # Small delay to increase race probability using threading.Event
                        delay_event = threading.Event()
                        delay_event.wait(timeout=0.001)

                        # Increment and write
                        new_value = current + 1
                        data_file.write_text(str(new_value))
                        successful_increments.append((thread_id, new_value))

                    finally:
                        # Release lock
                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

        # Create threads
        threads = []
        num_threads = 10

        for i in range(num_threads):
            thread = threading.Thread(target=increment_with_lock, args=(i,))
            threads.append(thread)

        # Start all threads
        start_time = time.time()
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()
        elapsed = time.time() - start_time

        # Check result
        final_value = int(data_file.read_text())
        expected = num_threads * 5

        print(f"Expected: {expected}")
        print(f"Actual: {final_value}")
        print(f"Lock acquisitions: {len(lock_acquisitions)}")
        print(f"Successful increments: {len(successful_increments)}")
        print(f"Time elapsed: {elapsed:.2f}s")

        assert final_value == expected, f"Lost {expected - final_value} increments"
        print("✓ File locking works correctly!")


if __name__ == "__main__":
    try:
        test_basic_file_locking()
        sys.exit(0)
    except AssertionError:
        sys.exit(1)
