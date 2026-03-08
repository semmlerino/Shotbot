"""Process and subprocess test doubles.

Classes:
    TestProcessPool: Unified test double for ProcessPoolManager
    TestCompletedProcess: Test double for subprocess.CompletedProcess
    TestSubprocess: Test double for subprocess operations
    PopenDouble: Test double for subprocess.Popen
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QThread

from tests.fixtures.signal_doubles import SignalDouble


class TestProcessPool:
    """Unified test double for ProcessPoolManager implementing ProcessPoolProtocol.

    This is the canonical test double that consolidates features from:
    - fixtures/test_doubles.py (original canonical)
    - test_helpers.py TestProcessPoolManager (TTL-aware cache, signals)
    - TestProcessPool (metrics) — formerly in doubles_library.py
    - TestProcessPoolDouble (kwargs tracking, delays) — formerly in doubles_extended.py

    Basic Usage:
        def test_something(test_process_pool):
            test_process_pool.set_outputs("output1", "output2")
            # ... code that uses ProcessPoolManager ...
            assert "ws -sg" in test_process_pool.commands

    TTL-Aware Mode (replaces TestProcessPoolManager):
        pool = TestProcessPool(ttl_aware=True)
        pool.execute_workspace_command("cmd", cache_ttl=60)
        # Second call returns cached result if within TTL

    Tracking Mode (replaces TestProcessPoolDouble):
        pool = TestProcessPool(track_kwargs=True)
        pool.execute_workspace_command("cmd", timeout=30)
        assert pool.command_kwargs["cmd"]["timeout"] == 30

    Args:
        ttl_aware: If True, enable TTL-based caching (like TestProcessPoolManager)
        track_kwargs: If True, track kwargs for each command (like TestProcessPoolDouble)

    """

    __test__ = False  # Prevent pytest from collecting this as a test class
    _instance: TestProcessPool | None = None

    def __init__(
        self,
        ttl_aware: bool = False,
        track_kwargs: bool = False,
        strict: bool = True,
        allow_main_thread: bool = False,
        enforce_thread_guard: bool = False,
    ) -> None:
        """Initialize the test double.

        Args:
            ttl_aware: Enable TTL-based caching behavior
            track_kwargs: Enable command kwargs tracking
            strict: If True (default), raises AssertionError when execute_workspace_command
                   is called without first calling set_outputs(). This prevents tests from
                   silently passing with empty output. Use @pytest.mark.permissive_process_pool
                   to opt out for tests that intentionally don't need specific output.
            allow_main_thread: If True, allow calls from main/UI thread.
                   Default False to match production behavior (which raises RuntimeError).
                   Use @pytest.mark.allow_main_thread to opt-out for tests that intentionally
                   test synchronous UI behavior.
            enforce_thread_guard: If True, reject main-thread calls like the real ProcessPoolManager.
                   Use this in contract tests to verify proper threading behavior.
                   Takes precedence over allow_main_thread.

        """
        # Feature flags
        self._ttl_aware = ttl_aware
        self._track_kwargs = track_kwargs
        self._strict = strict
        # Default False to match production behavior (UI-thread calls raise RuntimeError)
        # Use @pytest.mark.allow_main_thread to opt-out for specific tests
        self._allow_main_thread = allow_main_thread and not enforce_thread_guard

        # Core state
        self.commands: list[str] = []
        self._outputs_queue: list[str] = []
        self._output_index = 0
        self.default_output = ""
        self._repeat_output: bool = True
        self._outputs_configured = False

        # Error simulation
        self.should_fail = False
        self.fail_with_timeout = False
        self.fail_with_message: str | None = None
        self._errors: str = ""  # Legacy compatibility

        # TTL-aware cache: command -> (output, timestamp)
        self._cache: dict[str, tuple[str, float]] = {}

        # Kwargs tracking
        self.command_kwargs: dict[str, dict[str, Any]] = {}

        # Metrics
        self.call_count = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # Delay simulation
        self.simulated_delay = 0.0
        self.execution_delays: list[float] = []

        # Signals
        self.command_completed = SignalDouble()
        self.command_failed = SignalDouble()

    def set_outputs(self, *outputs: str, repeat: bool = True) -> None:
        """Set multiple outputs to return from execute_workspace_command.

        Args:
            *outputs: Variable number of output strings
            repeat: If True (default), returns the last output repeatedly for all calls.
                   If False, returns outputs sequentially then returns default_output.

        Default behavior (repeat=True) handles race conditions with background threads
        that may call execute_workspace_command() multiple times unpredictably.
        Use repeat=False for tests that need specific sequential outputs.

        """
        self._outputs_configured = True
        self._outputs_queue = list(outputs)
        self._output_index = 0
        self._repeat_output = repeat

    def set_errors(self, error: str) -> None:
        """Configure to raise RuntimeError with given message (legacy compatibility)."""
        self._errors = error
        self.fail_with_message = error
        self.should_fail = True

    def set_should_fail(self, should_fail: bool, message: str = "Test failure") -> None:
        """Configure the manager to fail on next command.

        Args:
            should_fail: Whether to fail
            message: Error message to use

        """
        self.should_fail = should_fail
        self.fail_with_message = message

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Execute a workspace command (test double).

        Args:
            command: Command to execute
            cache_ttl: Cache TTL in seconds (used if ttl_aware=True)
            timeout: Command timeout (tracked if track_kwargs=True)
            **kwargs: Additional parameters (tracked if track_kwargs=True)

        Returns:
            Test output string

        Raises:
            RuntimeError: If configured to fail
            TimeoutError: If configured to timeout

        """
        self.call_count += 1

        # Mirror real ProcessPoolManager's UI-thread guard (process_pool_manager.py:360-371)
        # This prevents tests from silently calling from the UI thread, which would
        # freeze the real application but go undetected with the test double.
        if not self._allow_main_thread:
            current_thread = QThread.currentThread()
            app_instance = QCoreApplication.instance()
            if app_instance and current_thread == app_instance.thread():
                raise RuntimeError(
                    "execute_workspace_command() cannot be called on the main (UI) thread!\n"
                    "This method blocks and will freeze the UI.\n"
                    "Use AsyncShotLoader or background workers instead.\n"
                    "If this test intentionally tests synchronous UI behavior, use:\n"
                    "  TestProcessPool(allow_main_thread=True)"
                )

        # Track kwargs if enabled
        if self._track_kwargs:
            self.command_kwargs[command] = {
                "cache_ttl": cache_ttl,
                "timeout": timeout,
                **kwargs,
            }

        # Simulate delay if configured
        if self.simulated_delay > 0:
            time.sleep(self.simulated_delay)
            self.execution_delays.append(self.simulated_delay)

        # TTL-aware caching
        if self._ttl_aware and cache_ttl and cache_ttl > 0 and command in self._cache:
            cached_output, cached_time = self._cache[command]
            if time.time() - cached_time < cache_ttl:
                self._cache_hits += 1
                return cached_output

        # Record command execution
        self.commands.append(command)
        self._cache_misses += 1

        # Check failure conditions
        if self.fail_with_timeout:
            self.command_failed.emit(command, "Timeout")
            raise TimeoutError(f"Command timed out: {command}")

        if self.should_fail or self._errors:
            message = self.fail_with_message or self._errors or f"Command failed: {command}"
            self.command_failed.emit(command, message)
            raise RuntimeError(message)

        # Determine output
        output = self._get_next_output()

        # Cache result if TTL-aware mode
        if self._ttl_aware and cache_ttl and cache_ttl > 0:
            self._cache[command] = (output, time.time())

        self.command_completed.emit(command, output)
        return output

    def _get_next_output(self) -> str:
        """Get the next output based on configured mode."""
        # Strict mode: fail if set_outputs() was never called
        if self._strict and not self._outputs_configured:
            raise AssertionError(
                "TestProcessPool: set_outputs() required before execute_workspace_command().\n"
                "Fix: Call test_process_pool.set_outputs('expected output') in your test.\n"
                "If this test intentionally doesn't need specific output, add:\n"
                "  @pytest.mark.permissive_process_pool"
            )

        if not self._outputs_queue:
            return self.default_output

        if self._repeat_output:
            # Return output at current index, staying at last one
            idx = min(self._output_index, len(self._outputs_queue) - 1)
            self._output_index += 1
            return self._outputs_queue[idx]

        # Sequential mode: pop from front
        if self._outputs_queue:
            return self._outputs_queue.pop(0)
        return self.default_output

    def execute_command(self, command: str, **kwargs: Any) -> tuple[bool, str]:
        """Execute a general command (for compatibility with TestProcessPoolManager).

        Args:
            command: Command to execute
            **kwargs: Additional parameters

        Returns:
            Tuple of (success, output_or_error)

        """
        try:
            output = self.execute_workspace_command(command, **kwargs)
            return True, output
        except (RuntimeError, TimeoutError) as e:
            return False, str(e)

    def invalidate_cache(self, command: str | None = None) -> None:
        """Invalidate the cache for a specific command or all commands.

        Args:
            command: Specific command to invalidate, or None for all

        """
        if command:
            self._cache.pop(command, None)
            self.commands.append(f"invalidate:{command}")
        else:
            self._cache.clear()
            self.commands.append("invalidate:all")

    def reset(self) -> None:
        """Reset the test double state."""
        self.commands.clear()
        self._outputs_queue.clear()
        self._output_index = 0
        self.default_output = ""
        self._repeat_output = True
        self.should_fail = False
        self.fail_with_timeout = False
        self.fail_with_message = None
        self._errors = ""
        self._cache.clear()
        self.command_kwargs.clear()
        self.call_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self.simulated_delay = 0.0
        self.execution_delays.clear()
        self.command_completed.clear()
        self.command_failed.clear()

    def clear(self) -> None:
        """Clear command history (alias for partial reset, compatible with TestProcessPoolManager)."""
        self.commands.clear()
        self.command_kwargs.clear()
        self.command_completed.clear()
        self.command_failed.clear()
        self._cache.clear()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Shutdown the test double (resets state for test isolation)."""
        self.reset()

    def find_files_python(self, directory: str, pattern: str) -> list[str]:
        """Find files using Python glob (real implementation for test double).

        This method uses real filesystem operations since it doesn't involve
        subprocess calls that would cause parallel test issues.

        Args:
            directory: Directory to search in
            pattern: Glob pattern to match

        Returns:
            List of matching file paths

        """
        try:
            path = Path(directory)
            if not path.exists():
                return []
            files = list(path.rglob(pattern))
            return [str(f) for f in files]
        except Exception:  # noqa: BLE001
            return []

    def get_executed_commands(self) -> list[str]:
        """Get the list of executed commands (compatible with TestProcessPoolManager)."""
        return self.commands.copy()

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

    def get_metrics(self) -> dict[str, Any]:
        """Get execution metrics.

        Returns:
            Dictionary with execution statistics

        """
        total_delay = sum(self.execution_delays)
        return {
            "total_calls": self.call_count,
            "unique_commands": len(set(self.commands)),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits / max(1, self.call_count),
            "cache_size": len(self._cache),
            "total_delay_ms": total_delay * 1000,
            "average_delay_ms": (
                total_delay * 1000 / len(self.execution_delays)
                if self.execution_delays
                else 0.0
            ),
        }

    @classmethod
    def get_instance(cls) -> TestProcessPool:
        """Get a singleton instance (for compatibility with TestProcessPoolManager)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance."""
        cls._instance = None


class TestCompletedProcess:
    """Test double for subprocess.CompletedProcess."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(
        self,
        args: str | list[str],
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Initialize test completed process."""
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def check_returncode(self) -> None:
        """Raise CalledProcessError if return code is non-zero."""
        if self.returncode != 0:
            raise subprocess.CalledProcessError(
                self.returncode, self.args, self.stdout, self.stderr
            )


def simulate_work_without_sleep(duration_ms: int = 10) -> None:
    """Simulate work without blocking the thread.

    Busy-waits for the given duration to simulate CPU work without
    using time.sleep() which can cause Qt event loop issues.

    Args:
        duration_ms: Duration in milliseconds to simulate work.

    """
    import time as _time
    start = _time.perf_counter()
    target = start + (duration_ms / 1000.0)
    while _time.perf_counter() < target:
        _time.sleep(0)  # Yield to other threads


class TestSubprocess:
    """Test double for subprocess operations with configurable behavior.

    Replaces @patch("subprocess.Popen") anti-pattern with real behavior testing.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test subprocess handler."""
        self.executed_commands: list[str | list[str]] = []
        self.execution_history: list[dict[str, Any]] = []
        self.return_code: int = 0
        self.stdout: str = ""
        self.stderr: str = ""
        self.side_effect: Exception | None = None
        self.delay: float = 0.0  # Simulate execution time
        self.args: str | list[str] | None = None  # For subprocess compatibility

        # For different commands, different outputs
        self.command_outputs: dict[str, tuple[int, str, str]] = {}

    def __enter__(self) -> TestSubprocess:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""

    def communicate(
        self, input_data: bytes | None = None, timeout: float | None = None
    ) -> tuple[str, str]:
        """Simulate communicate method for subprocess compatibility."""
        return (self.stdout, self.stderr)

    def kill(self) -> None:
        """Simulate kill method for subprocess compatibility."""

    def poll(self) -> int | None:
        """Simulate poll method for subprocess compatibility."""
        return self.return_code if self.return_code != 0 else None

    def run(
        self,
        command: str | list[str],
        shell: bool = False,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> TestCompletedProcess:
        """Simulate subprocess.run() with real behavior."""
        self.args = command  # Set args for subprocess compatibility
        self.executed_commands.append(command)
        self.execution_history.append(
            {
                "command": command,
                "shell": shell,
                "capture_output": capture_output,
                "text": text,
                "check": check,
                "timeout": timeout,
                "kwargs": kwargs,
                "timestamp": time.time(),
            }
        )

        # Simulate delay if configured
        if self.delay > 0:
            simulate_work_without_sleep(int(self.delay * 1000))  # Convert to ms

        # Raise exception if configured
        if self.side_effect:
            raise self.side_effect

        # Check for command-specific output
        cmd_str = command if isinstance(command, str) else " ".join(command)
        for pattern, output in self.command_outputs.items():
            if pattern in cmd_str:
                return_code, stdout, stderr = output
                result = TestCompletedProcess(command, return_code, stdout, stderr)
                if check:
                    result.check_returncode()
                return result

        # Default output
        result = TestCompletedProcess(
            command, self.return_code, self.stdout, self.stderr
        )
        if check:
            result.check_returncode()
        return result

    def Popen(
        self,
        command: str | list[str],
        shell: bool = False,
        stdout: Any = None,
        stderr: Any = None,
        **kwargs: Any,
    ) -> PopenDouble:
        """Simulate subprocess.Popen() for process management."""
        self.executed_commands.append(command)

        # Raise exception if configured (for Popen calls)
        if self.side_effect:
            raise self.side_effect

        return PopenDouble(command, self.return_code, self.stdout, self.stderr)

    def set_command_output(
        self, pattern: str, return_code: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        """Set specific output for commands matching pattern."""
        self.command_outputs[pattern] = (return_code, stdout, stderr)

    def clear(self) -> None:
        """Clear execution history for fresh test."""
        self.executed_commands.clear()
        self.execution_history.clear()
        self.command_outputs.clear()

    def get_last_command(self) -> str | list[str] | None:
        """Get the last executed command."""
        return self.executed_commands[-1] if self.executed_commands else None

    def was_called_with(self, pattern: str) -> bool:
        """Check if any command contained the pattern."""
        for cmd in self.executed_commands:
            cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
            if pattern in cmd_str:
                return True
        return False


class PopenDouble:
    """Test double for subprocess.Popen."""

    def __init__(
        self,
        args: str | list[str],
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Initialize test process."""
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.pid = 12345  # Fake PID
        self._terminated = False
        self._killed = False

    def __enter__(self) -> PopenDouble:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""

    def poll(self) -> int | None:
        """Check if process has terminated."""
        if self._terminated or self._killed:
            # Ensure returncode is an integer when process is terminated
            return self.returncode if self.returncode is not None else 0
        return None

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process to complete."""
        # For PopenDouble, immediately terminate and return
        # Don't simulate delay to avoid Qt event loop blocking issues
        self._terminated = True
        # Ensure we return a valid integer, not None
        # Real subprocess.Popen.wait() always returns an int
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        """Terminate the process."""
        self._terminated = True

    def kill(self) -> None:
        """Kill the process."""
        self._killed = True

    def communicate(
        self, input_data: bytes | None = None, timeout: float | None = None
    ) -> tuple[str, str]:
        """Communicate with process."""
        if timeout:
            simulate_work_without_sleep(
                min(int(timeout * 1000), 100)
            )  # Convert to ms, max 100ms
        self._terminated = True
        return self.stdout, self.stderr


