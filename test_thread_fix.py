#!/usr/bin/env python3
"""Test script to verify thread cleanup fix without PySide6."""

# Standard library imports
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

# Local application imports
from logging_mixin import LoggingMixin, get_module_logger


logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(message)s")

# Module-level logger for test functions
logger = get_module_logger(__name__)


class MockWorker(LoggingMixin):
    """Mock worker to test zombie thread handling."""

    def __init__(self) -> None:
        self._stop_requested = False
        self._zombie = False
        self._thread = None

    def is_zombie(self) -> bool:
        """Check if thread is a zombie."""
        return self._zombie

    def request_stop(self) -> None:
        """Request thread to stop."""
        self.logger.info("Stop requested")
        self._stop_requested = True

    def should_stop(self) -> bool:
        """Check if thread should stop."""
        return self._stop_requested

    def run_parallel_task(self) -> None:
        """Simulate parallel scanning with ThreadPoolExecutor."""
        self.logger.info("Starting parallel task")

        def cancel_flag() -> bool:
            return self.should_stop()

        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit some work
            futures = []
            for i in range(10):
                future = executor.submit(self.process_item, i)
                futures.append(future)

            # Process results
            try:
                for future in futures:
                    if cancel_flag():
                        self.logger.info("Cancelling remaining futures")
                        for f in futures:
                            if not f.done():
                                f.cancel()
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    try:
                        result = future.result(timeout=0.1)
                        self.logger.debug(f"Got result: {result}")
                    except FuturesTimeoutError:
                        if cancel_flag():
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                        result = future.result()
            except Exception as e:
                self.logger.error(f"Error: {e}")
                for f in futures:
                    if not f.done():
                        f.cancel()
                executor.shutdown(wait=False, cancel_futures=True)

        self.logger.info("Parallel task completed")

    def process_item(self, item: int) -> str | None:
        """Process a single item."""
        for i in range(5):
            if self.should_stop():
                self.logger.debug(f"Item {item} cancelled at step {i}")
                return None
            time.sleep(0.1)
        return f"Processed {item}"

    def run(self) -> None:
        """Main thread execution."""
        try:
            self.run_parallel_task()
        finally:
            self.logger.info("Worker thread exiting")

    def start(self) -> None:
        """Start the worker thread."""
        self._thread = threading.Thread(target=self.run)
        self._thread.start()

    def stop_with_timeout(self, timeout: float = 2) -> bool:
        """Try to stop thread with timeout."""
        self.request_stop()
        self._thread.join(timeout)

        if self._thread.is_alive():
            self.logger.warning(
                "Thread still running after timeout - marking as zombie"
            )
            self._zombie = True
            return False
        self.logger.info("Thread stopped successfully")
        return True


def test_cleanup() -> None:
    """Test the thread cleanup behavior."""
    logger.info("=== Testing thread cleanup ===")

    worker = MockWorker()
    worker.start()

    # Let it run briefly
    time.sleep(0.5)

    # Try to stop it
    logger.info("Requesting shutdown...")
    stopped = worker.stop_with_timeout(timeout=2)

    if not stopped and worker.is_zombie():
        logger.warning("Worker is a zombie - NOT deleting to prevent crash")
        # In real code, we would NOT call deleteLater() here
    else:
        logger.info("Worker stopped cleanly - safe to delete")
        # In real code, we would call deleteLater() here

    logger.info("=== Test complete ===")


if __name__ == "__main__":
    test_cleanup()
