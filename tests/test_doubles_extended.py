"""Extended test doubles library for ShotBot test suite.

This module provides additional test doubles that replace common Mock usage patterns,
following UNIFIED_TESTING_GUIDE principles:
- Test behavior, not implementation
- Use real components with test doubles ONLY at system boundaries
- No Mock() or MagicMock usage

These test doubles complement the existing test_doubles_library.py.
"""

from __future__ import annotations

# Standard library imports
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# Local application imports
from tests.helpers.synchronization import simulate_work_without_sleep


class TestFileSystem:
    """Test double for file system operations.

    Use this instead of mocking Path.exists(), os.makedirs(), etc.
    Works seamlessly with pytest's tmp_path fixture.

    Example usage:
        def test_shot_creation(tmp_path):
            fs = TestFileSystem(tmp_path)
            fs.create_vfx_structure("show1", "seq01", "0010")

            # Verify structure was created
            assert fs.created_files  # List of all created paths
            assert fs.exists_calls  # Track what was checked

            # Check specific path
            shot_path = tmp_path / "shows/show1/shots/seq01/seq01_0010"
            assert shot_path.exists()  # Real filesystem check
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self, base_path: Path | None = None) -> None:
        """Initialize test filesystem.

        Args:
            base_path: Base directory for operations (e.g., tmp_path from pytest)
        """
        self.base_path = base_path or Path("/tmp/test_fs")
        self.created_files: list[Path] = []
        self.created_directories: list[Path] = []
        self.exists_calls: list[Path] = []
        self.read_operations: list[tuple[Path, str]] = []  # (path, content_read)
        self.write_operations: list[tuple[Path, str]] = []  # (path, content_written)

    def create_vfx_structure(self, show: str, seq: str, shot: str) -> Path:
        """Create VFX directory structure for a shot.

        Creates: /shows/{show}/shots/{seq}/{seq}_{shot}
        With subdirectories: publish/editorial, publish/plates, work/3de, etc.

        Returns:
            Path to the shot directory
        """
        shot_path = self.base_path / "shows" / show / "shots" / seq / f"{seq}_{shot}"

        # Create main structure
        directories = [
            shot_path,
            shot_path / "publish" / "editorial",
            shot_path / "publish" / "plates",
            shot_path / "publish" / "3de",
            shot_path / "work" / "3de",
            shot_path / "work" / "nuke",
            shot_path / "work" / "maya",
        ]

        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)
            self.created_directories.append(dir_path)

        # Create thumbnail
        thumbnail_path = shot_path / "publish" / "editorial" / "thumbnail.jpg"
        self.create_file(thumbnail_path, b"fake_thumbnail_data")

        return shot_path

    def create_file(self, path: Path | str, content: bytes | str = "") -> Path:
        """Create a file with content.

        Args:
            path: File path to create
            content: File content (text or binary)

        Returns:
            Path object for the created file
        """
        path = Path(path) if isinstance(path, str) else path

        # Make absolute if relative
        if not path.is_absolute():
            path = self.base_path / path

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        if isinstance(content, str):
            path.write_text(content)
        else:
            path.write_bytes(content)

        self.created_files.append(path)
        self.write_operations.append((path, str(content)))

        return path

    def check_exists(self, path: Path | str) -> bool:
        """Check if path exists and track the call.

        This tracks existence checks for testing purposes.
        """
        path = Path(path) if isinstance(path, str) else path
        self.exists_calls.append(path)
        return path.exists()

    def read_file(self, path: Path | str) -> str:
        """Read file content and track the operation."""
        path = Path(path) if isinstance(path, str) else path
        content = path.read_text() if path.exists() else ""
        self.read_operations.append((path, content))
        return content

    def get_operation_stats(self) -> dict[str, int]:
        """Get statistics about filesystem operations."""
        return {
            "files_created": len(self.created_files),
            "directories_created": len(self.created_directories),
            "exists_checks": len(self.exists_calls),
            "read_operations": len(self.read_operations),
            "write_operations": len(self.write_operations),
        }


class TestQtWidget:
    """Test double for Qt widget testing without Mock.

    Tracks signal emissions and widget state changes without using Mock.
    Compatible with qtbot fixture for proper Qt testing.

    Example usage:
        def test_widget_behavior(qtbot):
            widget = TestQtWidget()

            # Simulate user interaction
            widget.emit_signal("clicked")
            widget.set_state("enabled", True)

            # Verify behavior
            assert widget.signals == [("clicked", ())]
            assert widget.state["enabled"] is True

            # Use with qtbot for timing
            qtbot.wait(10)  # Wait for Qt event processing
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test widget."""
        self.signals: list[tuple[str, tuple[Any, ...]]] = []
        self.state: dict[str, Any] = {
            "visible": True,
            "enabled": True,
            "geometry": (0, 0, 100, 100),
            "text": "",
            "selected": False,
        }
        self.connections: dict[str, list[callable]] = defaultdict(list)
        self.properties: dict[str, Any] = {}
        self.method_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def emit_signal(self, signal_name: str, *args: Any) -> None:
        """Emit a signal and track it.

        Args:
            signal_name: Name of the signal
            *args: Signal arguments
        """
        self.signals.append((signal_name, args))

        # Call connected slots
        for callback in self.connections.get(signal_name, []):
            callback(*args)

    def connect(self, signal_name: str, callback: callable) -> None:
        """Connect a callback to a signal."""
        self.connections[signal_name].append(callback)

    def disconnect(self, signal_name: str, callback: callable | None = None) -> None:
        """Disconnect callback(s) from a signal."""
        if callback:
            if callback in self.connections[signal_name]:
                self.connections[signal_name].remove(callback)
        else:
            self.connections[signal_name].clear()

    def set_state(self, key: str, value: Any) -> None:
        """Set widget state value."""
        self.state[key] = value
        # Emit state change signal
        self.emit_signal("stateChanged", key, value)

    def get_state(self, key: str) -> Any:
        """Get widget state value."""
        return self.state.get(key)

    def setProperty(self, name: str, value: Any) -> None:
        """Set a Qt property."""
        self.properties[name] = value

    def property(self, name: str) -> Any:
        """Get a Qt property."""
        return self.properties.get(name)

    def call_method(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Track method calls on the widget."""
        self.method_calls.append((method_name, args, kwargs))

        # Simulate some common method behaviors
        if method_name == "show":
            self.set_state("visible", True)
        elif method_name == "hide":
            self.set_state("visible", False)
        elif method_name == "setEnabled":
            self.set_state("enabled", args[0] if args else True)
        elif method_name == "setText" and args:
            self.set_state("text", args[0])

        return None  # Most Qt methods return None

    def reset(self) -> None:
        """Reset all tracking for a fresh test."""
        self.signals.clear()
        self.connections.clear()
        self.method_calls.clear()
        self.state = {
            "visible": True,
            "enabled": True,
            "geometry": (0, 0, 100, 100),
            "text": "",
            "selected": False,
        }

    def get_signal_count(self, signal_name: str) -> int:
        """Get count of emissions for a specific signal."""
        return sum(1 for name, _ in self.signals if name == signal_name)


class TestCache:
    """In-memory cache replacement for testing.

    Use this instead of mocking cache operations.
    Provides metrics for cache hit/miss analysis.

    Example usage:
        def test_cache_behavior():
            cache = TestCache()

            # Store and retrieve
            cache.set("key1", "value1")
            assert cache.get("key1") == "value1"
            assert cache.hits == 1

            # Miss scenario
            assert cache.get("key2") is None
            assert cache.misses == 1

            # Check metrics
            metrics = cache.metrics
            assert metrics["hit_rate"] == 0.5  # 1 hit, 1 miss
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test cache."""
        self.cache_dir: Path | None = None  # Add missing cache_dir attribute
        self.data: dict[str, Any] = {}
        self.hits: int = 0
        self.misses: int = 0
        self.sets: int = 0
        self.evictions: int = 0
        self.max_size: int | None = None
        self.ttl_seconds: float | None = None
        self.access_times: dict[str, float] = {}
        self.creation_times: dict[str, float] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache.

        Updates hit/miss counters.

        Args:
            key: Cache key
            default: Default value if key not found

        Returns:
            Cached value or default
        """
        # Check TTL if configured
        if self.ttl_seconds and key in self.creation_times:
            age = time.time() - self.creation_times[key]
            if age > self.ttl_seconds:
                # Expired
                del self.data[key]
                del self.creation_times[key]
                if key in self.access_times:
                    del self.access_times[key]

        if key in self.data:
            self.hits += 1
            self.access_times[key] = time.time()
            return self.data[key]
        self.misses += 1
        return default

    def set(self, key: str, value: Any) -> None:
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        # Check size limit and evict if needed
        if (
            self.max_size
            and len(self.data) >= self.max_size
            and key not in self.data
            and self.access_times
        ):
            # Simple LRU eviction
            oldest_key = min(self.access_times, key=self.access_times.get)
            del self.data[oldest_key]
            del self.access_times[oldest_key]
            if oldest_key in self.creation_times:
                del self.creation_times[oldest_key]
            self.evictions += 1

        self.data[key] = value
        self.sets += 1
        self.creation_times[key] = time.time()
        self.access_times[key] = time.time()

    def clear(self) -> None:
        """Clear all cached data and reset counters."""
        self.data.clear()
        self.access_times.clear()
        self.creation_times.clear()
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.evictions = 0

    def delete(self, key: str) -> bool:
        """Delete a specific key from cache.

        Returns:
            True if key was deleted, False if not found
        """
        if key in self.data:
            del self.data[key]
            if key in self.access_times:
                del self.access_times[key]
            if key in self.creation_times:
                del self.creation_times[key]
            return True
        return False

    @property
    def metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary with cache statistics
        """
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0.0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "evictions": self.evictions,
            "hit_rate": hit_rate,
            "size": len(self.data),
            "total_requests": total_requests,
        }

    def set_ttl(self, seconds: float) -> None:
        """Set TTL for cache entries."""
        self.ttl_seconds = seconds

    def set_max_size(self, size: int) -> None:
        """Set maximum cache size with LRU eviction."""
        self.max_size = size


class TestWorker:
    """Thread-safe worker double for testing async operations.

    Use this instead of mocking QThread or worker classes.
    Thread-safe design avoids Qt threading violations.

    Example usage:
        def test_async_operation():
            worker = TestWorker()

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
        self._result = None
        self._error = None
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


class TestCommand:
    """Command executor double for testing command execution.

    Use this instead of mocking subprocess or command execution.

    Example usage:
        def test_command_execution():
            executor = TestCommand()
            executor.set_output("ws -sg", "seq01_0010\\nseq01_0020")

            result = executor.execute("ws -sg")
            assert result == "seq01_0010\\nseq01_0020"
            assert executor.execution_count == 1
            assert "ws -sg" in executor.executed_commands
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize command executor."""
        self.executed_commands: list[str] = []
        self.outputs: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.return_codes: dict[str, int] = {}
        self.execution_times: list[float] = []
        self.default_output = ""
        self.default_error = ""
        self.default_return_code = 0
        self.should_fail = False
        self.fail_after_n_calls = None
        self._call_count = 0

    def set_output(
        self, command: str, output: str, error: str = "", return_code: int = 0
    ) -> None:
        """Set output for a specific command.

        Args:
            command: Command or command pattern
            output: Standard output to return
            error: Standard error to return
            return_code: Return code for the command
        """
        self.outputs[command] = output
        self.errors[command] = error
        self.return_codes[command] = return_code

    def execute(self, command: str, **kwargs: Any) -> str:
        """Execute command and return output.

        Args:
            command: Command to execute
            **kwargs: Additional execution parameters (tracked)

        Returns:
            Command output

        Raises:
            RuntimeError: If command fails or should_fail is set
        """
        start_time = time.time()
        self.executed_commands.append(command)
        self._call_count += 1

        # Check if should fail
        if self.should_fail:
            raise RuntimeError(f"Command failed: {command}")

        if self.fail_after_n_calls and self._call_count >= self.fail_after_n_calls:
            raise RuntimeError(
                f"Command failed after {self._call_count} calls: {command}"
            )

        # Find matching output
        output = self.default_output
        error = self.default_error
        return_code = self.default_return_code

        for pattern, cmd_output in self.outputs.items():
            if pattern in command or pattern == command:
                output = cmd_output
                error = self.errors.get(pattern, self.default_error)
                return_code = self.return_codes.get(pattern, self.default_return_code)
                break

        # Track execution time
        self.execution_times.append(time.time() - start_time)

        # Simulate error if return code is non-zero
        if return_code != 0:
            raise RuntimeError(f"Command exited with code {return_code}: {error}")

        return output

    @property
    def execution_count(self) -> int:
        """Get total number of executions."""
        return len(self.executed_commands)

    def get_last_command(self) -> str | None:
        """Get the last executed command."""
        return self.executed_commands[-1] if self.executed_commands else None

    def was_called_with(self, pattern: str) -> bool:
        """Check if any command contained the pattern."""
        return any(pattern in cmd for cmd in self.executed_commands)

    def get_execution_time(self, index: int = -1) -> float:
        """Get execution time for a command.

        Args:
            index: Command index (default: -1 for last command)

        Returns:
            Execution time in seconds
        """
        if self.execution_times and abs(index) <= len(self.execution_times):
            return self.execution_times[index]
        return 0.0

    def reset(self) -> None:
        """Reset all tracking."""
        self.executed_commands.clear()
        self.outputs.clear()
        self.errors.clear()
        self.return_codes.clear()
        self.execution_times.clear()
        self._call_count = 0
        self.should_fail = False
        self.fail_after_n_calls = None


class TestProcessPoolDouble:
    """Enhanced subprocess boundary mock for workspace commands.

    This extends the basic TestProcessPool from test_doubles_library.py
    with additional tracking capabilities.

    Example usage:
        def test_workspace_command():
            pool = TestProcessPool()
            pool.set_outputs(
                "workspace /shows/test/shots/seq01/seq01_0010",
                "workspace /shows/test/shots/seq01/seq01_0020"
            )

            result1 = pool.execute_workspace_command("ws -sg")
            assert "seq01_0010" in result1

            # Check tracking
            assert pool.commands == ["ws -sg"]
            assert pool.command_kwargs["ws -sg"]["timeout"] == 30  # default
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize enhanced process pool."""
        self.commands: list[str] = []
        self.command_kwargs: dict[str, dict[str, Any]] = {}
        self.outputs: list[str] = []
        self.default_output = "workspace /test/path"
        self._output_index = 0
        self._cache: dict[str, str] = {}
        self.should_fail = False
        self.fail_with_timeout = False
        self.fail_with_message: str | None = None
        self.execution_delays: list[float] = []
        self.simulated_delay = 0.0

    def set_outputs(self, *outputs: str) -> None:
        """Queue outputs for sequential returns.

        Args:
            *outputs: Output strings to return in sequence
        """
        self.outputs = list(outputs)
        self._output_index = 0

    def execute_workspace_command(self, command: str, **kwargs: Any) -> str:
        """Execute workspace command with test output.

        Args:
            command: Command to execute
            **kwargs: Additional parameters (tracked)

        Returns:
            Test output string

        Raises:
            RuntimeError: If configured to fail
            TimeoutError: If configured to timeout
        """
        # Track execution
        self.commands.append(command)
        self.command_kwargs[command] = kwargs

        # Simulate delay if configured
        if self.simulated_delay > 0:
            simulate_work_without_sleep(int(self.simulated_delay * 1000))
            self.execution_delays.append(self.simulated_delay)

        # Check failure conditions
        if self.should_fail:
            message = self.fail_with_message or f"Command failed: {command}"
            raise RuntimeError(message)

        if self.fail_with_timeout:
            raise TimeoutError(f"Command timed out: {command}")

        # Check cache
        if command in self._cache:
            return self._cache[command]

        # Return queued output or default
        if self.outputs and self._output_index < len(self.outputs):
            output = self.outputs[self._output_index]
            self._output_index += 1
        else:
            output = self.default_output

        # Cache result
        self._cache[command] = output
        return output

    def invalidate_cache(self, command: str | None = None) -> None:
        """Invalidate cache for command(s).

        Args:
            command: Specific command to invalidate, or None for all
        """
        if command:
            self._cache.pop(command, None)
        else:
            self._cache.clear()

    def get_execution_count(self, command_pattern: str | None = None) -> int:
        """Get execution count for commands matching pattern.

        Args:
            command_pattern: Pattern to match, or None for total count

        Returns:
            Number of matching executions
        """
        if command_pattern is None:
            return len(self.commands)
        return sum(1 for cmd in self.commands if command_pattern in cmd)

    def get_last_kwargs(self, command: str | None = None) -> dict[str, Any]:
        """Get kwargs from last execution of command.

        Args:
            command: Specific command, or None for last command

        Returns:
            Kwargs dictionary
        """
        if command:
            return self.command_kwargs.get(command, {})
        if self.commands:
            last_cmd = self.commands[-1]
            return self.command_kwargs.get(last_cmd, {})
        return {}

    def reset(self) -> None:
        """Reset all state for fresh test."""
        self.commands.clear()
        self.command_kwargs.clear()
        self.outputs.clear()
        self._output_index = 0
        self._cache.clear()
        self.execution_delays.clear()
        self.should_fail = False
        self.fail_with_timeout = False
        self.fail_with_message = None
        self.simulated_delay = 0.0

    def get_metrics(self) -> dict[str, Any]:
        """Get execution metrics.

        Returns:
            Dictionary with execution statistics
        """
        total_delay = sum(self.execution_delays)
        avg_delay = (
            total_delay / len(self.execution_delays) if self.execution_delays else 0.0
        )

        return {
            "total_calls": len(self.commands),
            "unique_commands": len(set(self.commands)),
            "cache_hits": sum(1 for cmd in self.commands if cmd in self._cache),
            "cache_size": len(self._cache),
            "total_delay_ms": total_delay * 1000,
            "average_delay_ms": avg_delay * 1000,
        }


# Export all test doubles
__all__ = [
    "TestCache",
    "TestCommand",
    "TestFileSystem",
    "TestProcessPoolDouble",
    "TestQtWidget",
    "TestWorker",
]
