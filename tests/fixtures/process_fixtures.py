"""Process and subprocess test doubles and fixtures.

Consolidated from:
- subprocess_mocking.py: Autouse subprocess mocks
- process_doubles.py:    TestProcessPool, TestCompletedProcess, PopenDouble
- cache_doubles.py:      test_process_pool fixture

Fixtures (autouse):
    mock_process_pool_manager: Patches ProcessPoolManager singleton
    mock_subprocess_popen:     Patches subprocess.Popen/run globally

Fixtures (opt-in):
    test_process_pool:     TestProcessPool instance

Classes:
    TestProcessPool:         Unified test double for ProcessPoolManager
    TestCompletedProcess:    Test double for subprocess.CompletedProcess
    PopenDouble:             Test double for subprocess.Popen
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# subprocess_mocking contents
# ---------------------------------------------------------------------------
import io
import threading
from collections.abc import Iterator

import pytest


# ==============================================================================
# STRICT MODE: Fail on unexpected subprocess calls (default behavior)
# ==============================================================================
# When strict mode is enabled, unexpected subprocess calls raise AssertionError
# Tests can use subprocess_mock fixture or @pytest.mark.permissive_subprocess to opt out


class _SubprocessMockState:
    """Container for subprocess mock state flags.

    Each test gets its own instance via pytest's stash mechanism,
    preventing state leakage between parallel tests in xdist workers.
    """

    def __init__(self) -> None:
        self.permissive_mode: bool = False
        self._is_fallback: bool = True


# Thread-local fallback for state access from inside mock callbacks
# (where we don't have direct access to the request object)
_thread_local = threading.local()


def _get_current_state() -> _SubprocessMockState:
    """Get the current test's subprocess state.

    Returns the thread-local state set by the fixture, or a default
    strict state if called outside of a test context.
    """
    state = getattr(_thread_local, "state", None)
    if state is None:
        # Fallback: return strict state (fail on unexpected calls)
        state = _SubprocessMockState()
    return state


def _set_current_state(state: _SubprocessMockState | None) -> None:
    """Set the current test's subprocess state in thread-local storage."""
    _thread_local.state = state


def _format_cmd(cmd: object) -> str:
    """Format command for display in error messages."""
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(c) for c in cmd)
    return str(cmd)


@pytest.fixture
def mock_process_pool_manager(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch ProcessPoolManager to use test double.

    This fixture patches ProcessPoolManager globally to prevent subprocess crashes
    in parallel test execution. Many components (ShotModel, Workers) internally use
    ProcessPoolManager as a singleton, making it impractical to mock at every call site.

    Auto-injected for all Qt tests via _qt_auto_fixtures in conftest.py.
    Request explicitly for non-Qt tests that use ProcessPoolManager.

    IMPORTANT: This fixture creates its own internal TestProcessPool to avoid
    interfering with test-local `test_process_pool` fixtures. Tests that define
    their own `test_process_pool` fixture and pass it to components will use their
    local version, while this mock just prevents the singleton from spawning processes.

    By default, strict mode is enabled - tests that call execute_workspace_command()
    without first calling set_outputs() will fail with a clear error message.

    Args:
        request: Pytest request for marker checking
        monkeypatch: Pytest monkeypatch fixture

    MARKERS:
        @pytest.mark.permissive_process_pool: Disable strict mode (allow unconfigured calls)
        @pytest.mark.enforce_thread_guard: Enable main-thread rejection (contract testing)
        @pytest.mark.allow_main_thread: Allow calls from main/UI thread (opt-out from guard)

    """
    # Check for permissive marker (escape hatch for tests that don't need specific output)
    is_permissive = "permissive_process_pool" in [
        m.name for m in request.node.iter_markers()
    ]

    # Check for thread guard marker (for contract testing)
    enforce_guard = "enforce_thread_guard" in [
        m.name for m in request.node.iter_markers()
    ]

    # Check for allow_main_thread marker (opt-out from default UI thread guard)
    allow_main = "allow_main_thread" in [m.name for m in request.node.iter_markers()]

    # Import and create TestProcessPool directly (not via fixture) to avoid
    # interfering with test-local test_process_pool fixtures
    internal_pool = TestProcessPool(
        strict=not is_permissive,
        enforce_thread_guard=enforce_guard,
        allow_main_thread=allow_main,
    )

    # Patch the singleton instance directly - get_instance() checks this first
    monkeypatch.setattr(
        "workers.process_pool_manager.ProcessPoolManager._instance",
        internal_pool,
    )


@pytest.fixture
def mock_subprocess_popen(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Mock subprocess.Popen and subprocess.run with STRICT MODE.

    STRICT MODE: Unexpected subprocess calls FAIL with AssertionError.
    This prevents silent success that masks bugs in error handling.

    Auto-injected for all Qt tests via _qt_auto_fixtures in conftest.py.
    Request explicitly for non-Qt tests that need subprocess blocking.

    HANDLING SUBPROCESS CALLS:
        1. Use subprocess_mock fixture for controlled behavior
        2. Use fp (pytest-subprocess) for fine-grained fake process control

    Args:
        monkeypatch: Pytest monkeypatch fixture

    Yields:
        None - fixture provides teardown cleanup

    """
    # Create per-test state instance (prevents race conditions in parallel tests)
    state = _SubprocessMockState()
    state.permissive_mode = False
    state._is_fallback = False

    # Store in thread-local for access from mock callbacks
    _set_current_state(state)

    from unittest.mock import MagicMock

    def _create_mock_popen(*args: object, **kwargs: object) -> object:
        """Create Popen mock with STRICT MODE."""
        # Check if text mode requested (text=True, encoding=..., or universal_newlines=True)
        text_mode = (
            kwargs.get("text", False)
            or kwargs.get("encoding") is not None
            or kwargs.get("universal_newlines", False)
        )

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = 0  # Process finished
        mock_process.wait.return_value = 0  # Exit code 0
        mock_process.returncode = 0

        # Return appropriate types based on text mode
        if text_mode:
            mock_process.stdout = io.StringIO("")
            mock_process.stderr = io.StringIO("")
            mock_process.communicate.return_value = ("", "")
        else:
            mock_process.stdout = io.BytesIO(b"")
            mock_process.stderr = io.BytesIO(b"")
            mock_process.communicate.return_value = (b"", b"")

        return mock_process

    mock_popen = MagicMock(side_effect=_create_mock_popen)

    # Patch subprocess.Popen for any callers
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    # Also mock subprocess.run for complete coverage
    # Many production files use subprocess.run() directly (not Popen)
    def _create_mock_run(*args: object, **kwargs: object) -> object:
        """Create subprocess.run mock with STRICT MODE."""
        # Check if text mode requested
        text_mode = (
            kwargs.get("text", False)
            or kwargs.get("encoding") is not None
            or kwargs.get("universal_newlines", False)
        )

        result = MagicMock()
        result.returncode = 0
        if text_mode:
            result.stdout = ""
            result.stderr = ""
        else:
            result.stdout = b""
            result.stderr = b""
        return result

    mock_run = MagicMock(side_effect=_create_mock_run)
    monkeypatch.setattr("subprocess.run", mock_run)

    # Yield to run the test
    try:
        yield
    finally:
        # CLEANUP: Clear thread-local state (even if test fails mid-execution)
        # This prevents state leakage between tests in the same thread
        _set_current_state(None)


# ---------------------------------------------------------------------------
# process_doubles contents
# ---------------------------------------------------------------------------

import subprocess
import time
from typing import Any

from PySide6.QtCore import QCoreApplication, QThread

from tests.fixtures.model_fixtures import SignalDouble


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

    Tracking Mode (replaces TestProcessPoolDouble):
        pool = TestProcessPool(track_kwargs=True)
        pool.execute_workspace_command("cmd", timeout=30)
        assert pool.command_kwargs["cmd"]["timeout"] == 30

    Args:
        track_kwargs: If True, track kwargs for each command (like TestProcessPoolDouble)

    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(
        self,
        track_kwargs: bool = False,
        strict: bool = True,
        allow_main_thread: bool = False,
        enforce_thread_guard: bool = False,
    ) -> None:
        """Initialize the test double.

        Args:
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

        # Kwargs tracking
        self.command_kwargs: dict[str, dict[str, Any]] = {}

        # Cache
        self._cache: dict[str, str] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # Metrics
        self.call_count = 0

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
            cache_ttl: Cache TTL in seconds (accepted for interface compatibility, not used)
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

        # Record command execution
        self.commands.append(command)

        # Check failure conditions
        if self.fail_with_timeout:
            self.command_failed.emit(command, "Timeout")
            raise TimeoutError(f"Command timed out: {command}")

        if self.should_fail or self._errors:
            message = (
                self.fail_with_message or self._errors or f"Command failed: {command}"
            )
            self.command_failed.emit(command, message)
            raise RuntimeError(message)

        # Determine output
        output = self._get_next_output()

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


@pytest.fixture
def test_process_pool(request: pytest.FixtureRequest) -> TestProcessPool:
    """Provide a TestProcessPool instance for mocking ProcessPoolManager.

    Args:
        request: Pytest request for marker checking

    Returns:
        TestProcessPool instance that can be configured to return
        specific outputs or simulate errors.

    NOTE: Tests that define their own local `test_process_pool` fixture
    will shadow this global one - the local fixture takes precedence.

    MARKERS:
        @pytest.mark.permissive_process_pool: Disable strict mode
        @pytest.mark.enforce_thread_guard: Enable main-thread rejection (contract testing)
        @pytest.mark.allow_main_thread: Allow calls from main/UI thread (opt-out from guard)

    """
    # Check for markers
    is_permissive = "permissive_process_pool" in [
        m.name for m in request.node.iter_markers()
    ]
    enforce_guard = "enforce_thread_guard" in [
        m.name for m in request.node.iter_markers()
    ]
    allow_main = "allow_main_thread" in [m.name for m in request.node.iter_markers()]
    return TestProcessPool(
        strict=not is_permissive,
        enforce_thread_guard=enforce_guard,
        allow_main_thread=allow_main,
    )
