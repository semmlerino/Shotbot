"""Test doubles for filesystem scanner testing.

Provides specialized test doubles for testing FilesystemScanner behavior,
particularly for subprocess polling and timeout simulation that requires
more control than the standard subprocess_mock fixture provides.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest


class MockFileObject:
    """Mock file object that works with selectors testing.

    Provides a file-like interface for stdout/stderr that can be read
    in chunks or all at once.
    """

    __test__ = False

    def __init__(self, data: str = "") -> None:
        """Initialize with optional data."""
        self._data = data
        self._position = 0
        self._closed = False

    def read(self, size: int = -1) -> str:
        """Read data from the mock file.

        Args:
            size: Number of characters to read, or -1 for all remaining.

        Returns:
            String data read from the mock file.
        """
        if self._closed:
            return ""
        if size < 0:
            result = self._data[self._position :]
            self._position = len(self._data)
            return result
        result = self._data[self._position : self._position + size]
        self._position += len(result)
        return result

    def fileno(self) -> int:
        """Return a fake file descriptor.

        Note: This won't work with real selectors, but allows tests
        to verify registration attempts.
        """
        return -1  # Invalid fd, but allows testing

    def close(self) -> None:
        """Mark the file as closed."""
        self._closed = True

    @property
    def remaining(self) -> int:
        """Return how much data remains to be read."""
        return len(self._data) - self._position


class MockSelector:
    """Mock selector for testing streaming read behavior.

    Simulates selectors.DefaultSelector behavior for unit testing
    without requiring real file descriptors.
    """

    __test__ = False

    def __init__(self) -> None:
        """Initialize the mock selector."""
        self._registered: dict[Any, tuple[Any, str]] = {}  # fileobj -> (events, data)
        self._select_returns: list[list[tuple[Any, int]]] = []
        self._select_index = 0

    def register(
        self, fileobj: Any, events: int, data: str | None = None
    ) -> MagicMock:
        """Register a file object."""
        self._registered[fileobj] = (events, data)
        key = MagicMock()
        key.fileobj = fileobj
        key.data = data
        return key

    def unregister(self, fileobj: Any) -> None:
        """Unregister a file object."""
        self._registered.pop(fileobj, None)

    def set_select_returns(self, returns: list[list[tuple[Any, int]]]) -> None:
        """Configure what select() returns on each call.

        Args:
            returns: List of return values for successive select() calls.
                    Each return value is a list of (key, events) tuples.
        """
        self._select_returns = returns
        self._select_index = 0

    def select(self, timeout: float | None = None) -> list[tuple[Any, int]]:
        """Return configured ready file objects."""
        if self._select_index < len(self._select_returns):
            result = self._select_returns[self._select_index]
            self._select_index += 1
            return result
        # Default: return all registered as ready
        keys = []
        for fileobj, (events, data) in self._registered.items():
            key = MagicMock()
            key.fileobj = fileobj
            key.data = data
            keys.append((key, events))
        return keys

    def close(self) -> None:
        """Close the selector."""
        self._registered.clear()


class PollingProcessDouble:
    """Test double for subprocess.Popen that simulates polling behavior.

    This double is specifically designed for testing `_run_find_with_polling()`
    which uses selectors to read stdout/stderr while polling.

    Features:
    - Configurable poll sequence (None = running, int = exit code)
    - Tracks kill() and wait() calls
    - Configurable stdout/stderr output via MockFileObject
    - Supports cancel_flag testing
    - Compatible with selectors-based streaming read

    Usage:
        process = PollingProcessDouble()
        process.set_poll_sequence([None, None, None, 0])  # Run 3 polls then complete
        process.stdout_data = "/path/to/file1.3de\\n/path/to/file2.3de"

        # In test:
        with monkeypatch.context() as m:
            m.setattr("subprocess.Popen", lambda *a, **k: process)
            result = scanner._run_find_with_polling(cmd, ...)

        assert process.poll_count == 4  # Called 4 times
        assert not process.killed  # Should complete normally
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize the polling process double."""
        self._stdout_data: str = ""
        self._stderr_data: str = ""
        self._poll_sequence: list[int | None] = [0]  # Default: complete immediately
        self._poll_index: int = 0
        self.returncode: int | None = None
        self.killed: bool = False
        self.wait_called: bool = False
        self.poll_count: int = 0
        self.pid: int = 12345

        # File-like stdout/stderr for selectors-based reading
        self.stdout: MockFileObject = MockFileObject()
        self.stderr: MockFileObject = MockFileObject()

        # Track communicate() calls (legacy, still supported)
        self.communicate_called: bool = False
        self.communicate_timeout: float | None = None

    @property
    def stdout_data(self) -> str:
        """Get stdout data."""
        return self._stdout_data

    @stdout_data.setter
    def stdout_data(self, value: str) -> None:
        """Set stdout data and update the MockFileObject."""
        self._stdout_data = value
        self.stdout = MockFileObject(value)

    @property
    def stderr_data(self) -> str:
        """Get stderr data."""
        return self._stderr_data

    @stderr_data.setter
    def stderr_data(self, value: str) -> None:
        """Set stderr data and update the MockFileObject."""
        self._stderr_data = value
        self.stderr = MockFileObject(value)

    def set_poll_sequence(self, sequence: list[int | None]) -> None:
        """Set the sequence of poll() return values.

        Args:
            sequence: List where None means "still running", int means exit code.
                     The last value is returned for all subsequent calls.

        Example:
            # Process runs for 3 poll cycles then exits with code 0
            process.set_poll_sequence([None, None, None, 0])
        """
        self._poll_sequence = sequence
        self._poll_index = 0

    def poll(self) -> int | None:
        """Return the next poll result from the sequence."""
        self.poll_count += 1
        if self._poll_index < len(self._poll_sequence):
            result = self._poll_sequence[self._poll_index]
            self._poll_index += 1
            if result is not None:
                self.returncode = result
            return result
        # Return last value in sequence for subsequent calls
        result = self._poll_sequence[-1] if self._poll_sequence else 0
        if result is not None:
            self.returncode = result
        return result

    def kill(self) -> None:
        """Mark the process as killed."""
        self.killed = True
        self.returncode = -9  # SIGKILL

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process completion."""
        self.wait_called = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        """Return configured stdout/stderr."""
        self.communicate_called = True
        self.communicate_timeout = timeout
        return (self.stdout_data, self.stderr_data)


class TimeControlledPollingProcess(PollingProcessDouble):
    """Polling process double with simulated elapsed time.

    Extends PollingProcessDouble to track simulated elapsed time,
    useful for testing timeout logic without actual sleeping.

    The caller can optionally provide a custom time function that
    returns incrementing values to simulate time passage.
    """

    __test__ = False

    def __init__(self, time_increments: list[float] | None = None) -> None:
        """Initialize with optional time increments.

        Args:
            time_increments: List of time values to return from time.time() calls.
                           If None, uses real time.
        """
        super().__init__()
        self._time_increments = time_increments or []
        self._time_index = 0
        self.simulated_elapsed: float = 0.0

    def get_simulated_time(self) -> float:
        """Get the next simulated time value."""
        if self._time_index < len(self._time_increments):
            result = self._time_increments[self._time_index]
            self._time_index += 1
            self.simulated_elapsed = result
            return result
        # After sequence exhausted, return last value + 1 each time
        if self._time_increments:
            self.simulated_elapsed += 1.0
            return self.simulated_elapsed
        return time.time()  # Fall back to real time


@pytest.fixture
def polling_process() -> PollingProcessDouble:
    """Provide a PollingProcessDouble for testing subprocess polling.

    Returns:
        PollingProcessDouble instance that can be configured to simulate
        various process states during poll loops.

    Example:
        def test_timeout_handling(polling_process, monkeypatch):
            polling_process.set_poll_sequence([None] * 100)  # Never complete
            monkeypatch.setattr("subprocess.Popen", lambda *a, **k: polling_process)
            # Test timeout logic...
    """
    return PollingProcessDouble()


@pytest.fixture
def time_controlled_process() -> TimeControlledPollingProcess:
    """Provide a TimeControlledPollingProcess for deterministic timeout testing.

    Returns:
        TimeControlledPollingProcess instance with time simulation capabilities.
    """
    return TimeControlledPollingProcess()
