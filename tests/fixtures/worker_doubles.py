"""Worker test doubles.

Classes:
    TestWorker: Test double for worker threads (QThread-based)
    TestThreadWorker: Thread-safe worker double for testing async operations
"""

from __future__ import annotations

import threading
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from tests.fixtures.process_doubles import simulate_work_without_sleep


class TestWorker(QThread):
    """Test double for worker threads with real Qt signals."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    # Real signals for testing
    started = Signal()
    finished = Signal(str)
    progress = Signal(int)
    error = Signal(str)
    result_ready = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize test worker."""
        super().__init__(parent)
        self.name: str = "test_worker"  # Add missing name attribute
        self.test_result: Any = "success"
        self.test_error: str | None = None
        self.progress_values: list[int] = [25, 50, 75, 100]
        self.execution_time: float = 0.01  # Fast for tests
        self.was_started = False
        self.was_stopped = False

    def set_test_result(self, result: Any) -> None:
        """Set the result that will be emitted."""
        self.test_result = result

    def set_test_error(self, error: str) -> None:
        """Set an error to be emitted."""
        self.test_error = error

    def run(self) -> None:
        """Run the worker thread."""
        self.was_started = True
        self.started.emit()

        # Simulate work with progress
        for progress_value in self.progress_values:
            if self.isInterruptionRequested():
                self.was_stopped = True
                break
            simulate_work_without_sleep(
                int((self.execution_time / len(self.progress_values)) * 1000)
            )  # Convert to ms
            self.progress.emit(progress_value)

        # Emit result or error
        if self.test_error:
            self.error.emit(self.test_error)
            self.finished.emit("error")
        else:
            self.result_ready.emit(self.test_result)
            self.finished.emit("success")

    def stop(self) -> None:
        """Stop the worker."""
        self.requestInterruption()
        self.wait(1000)  # Wait up to 1 second
        self.was_stopped = True


class TestThreadWorker:
    """Thread-safe worker double for testing async operations.

    Use this instead of mocking QThread or worker classes when pure-Python
    thread semantics are sufficient (no Qt signals needed).

    Example usage:
        def test_async_operation():
            worker = TestThreadWorker()

            # Start work
            worker.start()
            assert worker.started
            assert worker.is_running

            # Complete work
            worker.complete({"data": "result"})
            assert worker.finished
            assert worker.result == {"data": "result"}
            assert not worker.is_running
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize thread-safe worker."""
        self._lock = threading.RLock()
        self._started = False
        self._finished = False
        self._result: Any = None
        self._error: Exception | None = None
        self._progress_updates: list[tuple[float, str]] = []
        self._cancelled = False
        self._paused = False

    @property
    def started(self) -> bool:
        """Check if worker has started."""
        with self._lock:
            return self._started

    @property
    def finished(self) -> bool:
        """Check if worker has finished."""
        with self._lock:
            return self._finished

    @property
    def result(self) -> Any:
        """Get worker result (thread-safe)."""
        with self._lock:
            return self._result

    @property
    def error(self) -> Exception | None:
        """Get worker error if any."""
        with self._lock:
            return self._error

    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        with self._lock:
            return self._started and not self._finished

    @property
    def is_cancelled(self) -> bool:
        """Check if worker was cancelled."""
        with self._lock:
            return self._cancelled

    @property
    def is_paused(self) -> bool:
        """Check if worker is paused."""
        with self._lock:
            return self._paused

    def start(self) -> None:
        """Start the worker."""
        with self._lock:
            if self._started:
                raise RuntimeError("Worker already started")
            self._started = True
            self._finished = False
            self._cancelled = False
            self._paused = False

    def complete(self, result: Any = None) -> None:
        """Complete the worker with a result."""
        with self._lock:
            if not self._started:
                raise RuntimeError("Worker not started")
            if self._finished:
                raise RuntimeError("Worker already finished")
            self._result = result
            self._finished = True

    def fail(self, error: Exception) -> None:
        """Mark worker as failed with error."""
        with self._lock:
            if not self._started:
                raise RuntimeError("Worker not started")
            self._error = error
            self._finished = True

    def cancel(self) -> None:
        """Cancel the worker."""
        with self._lock:
            self._cancelled = True
            self._finished = True

    def pause(self) -> None:
        """Pause the worker."""
        with self._lock:
            if self.is_running:
                self._paused = True

    def resume(self) -> None:
        """Resume the worker."""
        with self._lock:
            self._paused = False

    def update_progress(self, progress: float, message: str = "") -> None:
        """Update worker progress (thread-safe)."""
        with self._lock:
            self._progress_updates.append((progress, message))

    def get_progress_updates(self) -> list[tuple[float, str]]:
        """Get all progress updates."""
        with self._lock:
            return self._progress_updates.copy()

    def reset(self) -> None:
        """Reset worker to initial state."""
        with self._lock:
            self._started = False
            self._finished = False
            self._result = None
            self._error = None
            self._progress_updates.clear()
            self._cancelled = False
            self._paused = False

    def wait(self, timeout_ms: int = 1000) -> bool:
        """Simulate waiting for worker completion.

        Args:
            timeout_ms: Maximum wait time in milliseconds

        Returns:
            True if worker finished, False if timeout

        """
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            if self.finished:
                return True
            simulate_work_without_sleep(10)  # Small sleep to avoid busy wait
        return False
