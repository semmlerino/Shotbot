"""Process and subprocess test doubles and fixtures.

Consolidated from:
- subprocess_mocking.py: Autouse subprocess mocks, SubprocessMock class, fixtures
- process_doubles.py:    TestProcessPool, TestCompletedProcess, TestSubprocess, PopenDouble
- cache_doubles.py:      TestProgressOperation, TestProgressManager, test_process_pool fixture

Fixtures (autouse):
    mock_process_pool_manager: Patches ProcessPoolManager singleton
    mock_subprocess_popen:     Patches subprocess.Popen/run globally

Fixtures (opt-in):
    subprocess_mock:       Controllable subprocess mock
    subprocess_error_mock: Pre-configured for error scenarios
    test_process_pool:     TestProcessPool instance

Classes:
    SubprocessMock:          Controllable subprocess mock
    TestProcessPool:         Unified test double for ProcessPoolManager
    TestCompletedProcess:    Test double for subprocess.CompletedProcess
    TestSubprocess:          Test double for subprocess operations
    PopenDouble:             Test double for subprocess.Popen
    TestProgressOperation:   Minimal test double for progress operations
    TestProgressManager:     Test double for progress manager
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# subprocess_mocking contents
# ---------------------------------------------------------------------------
import io
import threading
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest


# ==============================================================================
# STRICT MODE: Fail on unexpected subprocess calls (default behavior)
# ==============================================================================
# When strict mode is enabled, unexpected subprocess calls raise AssertionError
# Tests can use subprocess_mock fixture or @pytest.mark.permissive_subprocess to opt out

# Stash key for per-test state (avoids module-level state race conditions)
_SUBPROCESS_STATE_KEY = pytest.StashKey["_SubprocessMockState"]()


class _SubprocessMockState:
    """Container for subprocess mock state flags.

    Each test gets its own instance via pytest's stash mechanism,
    preventing state leakage between parallel tests in xdist workers.
    """

    def __init__(self) -> None:
        self.permissive_mode: bool = False
        self.subprocess_mock_active: bool = False


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


def _set_subprocess_mock_active(active: bool) -> None:
    """Set subprocess_mock fixture state for current test."""
    state = _get_current_state()
    state.subprocess_mock_active = active


def _format_cmd(cmd: object) -> str:
    """Format command for display in error messages."""
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(c) for c in cmd)
    return str(cmd)


@pytest.fixture(autouse=True)
def mock_process_pool_manager(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch ProcessPoolManager to use test double (AUTOUSE).

    This fixture patches ProcessPoolManager globally to prevent subprocess crashes
    in parallel test execution. Many components (ShotModel, Workers) internally use
    ProcessPoolManager as a singleton, making it impractical to mock at every call site.

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
        @pytest.mark.real_subprocess: Skip this mock entirely (use real subprocess)
        @pytest.mark.permissive_process_pool: Disable strict mode (allow unconfigured calls)
        @pytest.mark.enforce_thread_guard: Enable main-thread rejection (contract testing)
        @pytest.mark.allow_main_thread: Allow calls from main/UI thread (opt-out from guard)

    """
    # Allow opt-out for tests that need real subprocess behavior
    if "real_subprocess" in [m.name for m in request.node.iter_markers()]:
        return  # Skip mock for this test

    # Check for permissive marker (escape hatch for tests that don't need specific output)
    is_permissive = "permissive_process_pool" in [
        m.name for m in request.node.iter_markers()
    ]

    # Check for thread guard marker (for contract testing)
    enforce_guard = "enforce_thread_guard" in [
        m.name for m in request.node.iter_markers()
    ]

    # Check for allow_main_thread marker (opt-out from default UI thread guard)
    allow_main = "allow_main_thread" in [
        m.name for m in request.node.iter_markers()
    ]

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


@pytest.fixture(autouse=True)
def mock_subprocess_popen(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Mock subprocess.Popen with STRICT MODE (AUTOUSE).

    STRICT MODE (default): Unexpected subprocess calls FAIL with AssertionError.
    This prevents silent success that masks bugs in error handling.

    HANDLING SUBPROCESS CALLS:
        1. Use subprocess_mock fixture for controlled behavior
        2. Use @pytest.mark.real_subprocess for real subprocess
        3. Use @pytest.mark.permissive_subprocess to opt-out (DISCOURAGED)

    Args:
        request: Pytest request for marker checking
        monkeypatch: Pytest monkeypatch fixture

    Yields:
        None - fixture provides teardown cleanup

    """
    import warnings

    # Allow opt-out for tests that need real subprocess behavior
    if "real_subprocess" in [m.name for m in request.node.iter_markers()]:
        yield  # Still need to yield for generator fixture
        return

    # Check for permissive_subprocess marker (legacy opt-out)
    is_permissive = "permissive_subprocess" in [m.name for m in request.node.iter_markers()]
    if is_permissive:
        warnings.warn(
            f"Test '{request.node.name}' uses @pytest.mark.permissive_subprocess. "
            f"This is deprecated - update to use subprocess_mock fixture instead.",
            DeprecationWarning,
            stacklevel=1,
        )

    # Create per-test state instance (prevents race conditions in parallel tests)
    state = _SubprocessMockState()
    state.permissive_mode = is_permissive
    state.subprocess_mock_active = False

    # Store in thread-local for access from mock callbacks
    _set_current_state(state)

    # Also store in pytest stash for fixture-to-fixture communication
    request.node.stash[_SUBPROCESS_STATE_KEY] = state

    def _create_mock_popen(*args: object, **kwargs: object) -> MagicMock:
        """Create Popen mock with STRICT MODE."""
        cmd_str = ""
        if args:
            cmd = args[0]
            cmd_str = _format_cmd(cmd)

        # STRICT MODE: Fail on unexpected subprocess calls
        # Unless: permissive mode enabled OR subprocess_mock fixture is active
        current_state = _get_current_state()
        if not current_state.permissive_mode and not current_state.subprocess_mock_active:
            raise AssertionError(
                f"Unexpected subprocess command: {cmd_str}\n\n"
                f"STRICT MODE is enabled by default. To handle subprocess calls:\n"
                f"  1. Use subprocess_mock fixture to configure expected behavior:\n"
                f"       def test_foo(subprocess_mock):\n"
                f"           subprocess_mock.set_output('expected output')\n"
                f"           ...\n"
                f"  2. Use @pytest.mark.real_subprocess for real subprocess execution\n"
                f"  3. Use @pytest.mark.permissive_subprocess (DISCOURAGED - legacy opt-out)\n"
            )

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
    def _create_mock_run(*args: object, **kwargs: object) -> MagicMock:
        """Create subprocess.run mock with STRICT MODE."""
        cmd_str = ""
        if args:
            cmd = args[0]
            cmd_str = _format_cmd(cmd)

        # STRICT MODE: Fail on unexpected subprocess.run calls
        current_state = _get_current_state()
        if not current_state.permissive_mode and not current_state.subprocess_mock_active:
            raise AssertionError(
                f"Unexpected subprocess.run command: {cmd_str}\n\n"
                f"STRICT MODE is enabled by default. To handle subprocess.run calls:\n"
                f"  1. Use subprocess_mock fixture to configure expected behavior\n"
                f"  2. Use @pytest.mark.real_subprocess for real subprocess execution\n"
                f"  3. Use @pytest.mark.permissive_subprocess (DISCOURAGED - legacy opt-out)\n"
            )

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


class SubprocessMock:
    """Controllable subprocess mock for testing command execution.

    This class provides methods to configure expected subprocess behavior,
    including stdout, stderr, return codes, and exceptions.

    Mocks both subprocess.Popen and subprocess.run for complete coverage.

    Usage:
        def test_command_output(subprocess_mock):
            subprocess_mock.set_output("hello world")
            subprocess_mock.set_return_code(0)
            # ... run code that uses subprocess ...
            assert subprocess_mock.calls == [["my", "command"]]
    """

    def __init__(self) -> None:
        self._mock = MagicMock()
        self._run_mock = MagicMock()
        self._calls: list[list[str]] = []
        self._stdout = b""
        self._stderr = b""
        self._returncode = 0
        self._should_raise: Exception | None = None
        self._setup_mock()
        self._setup_run_mock()

    def _setup_mock(self) -> None:
        """Configure mock behavior."""

        def popen_side_effect(args: list[str], **kwargs: object) -> MagicMock:
            if self._should_raise:
                raise self._should_raise
            self._calls.append(list(args) if isinstance(args, (list, tuple)) else [str(args)])

            # Check if text mode requested (text=True, encoding=..., or universal_newlines=True)
            text_mode = (
                kwargs.get("text", False)
                or kwargs.get("encoding") is not None
                or kwargs.get("universal_newlines", False)
            )

            process = MagicMock()
            process.pid = 99999
            process.poll.return_value = self._returncode
            process.wait.return_value = self._returncode
            process.returncode = self._returncode

            # Return appropriate types based on text mode
            if text_mode:
                stdout_str = self._stdout.decode("utf-8")
                stderr_str = self._stderr.decode("utf-8")
                process.stdout = io.StringIO(stdout_str)
                process.stderr = io.StringIO(stderr_str)
                process.communicate.return_value = (stdout_str, stderr_str)
            else:
                process.stdout = io.BytesIO(self._stdout)
                process.stderr = io.BytesIO(self._stderr)
                process.communicate.return_value = (self._stdout, self._stderr)

            return process

        self._mock.side_effect = popen_side_effect

    def _setup_run_mock(self) -> None:
        """Configure subprocess.run mock behavior."""

        def run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
            if self._should_raise:
                raise self._should_raise
            self._calls.append(list(args) if isinstance(args, (list, tuple)) else [str(args)])

            # Check if text mode requested
            text_mode = (
                kwargs.get("text", False)
                or kwargs.get("encoding") is not None
                or kwargs.get("universal_newlines", False)
            )

            result = MagicMock()
            result.returncode = self._returncode

            if text_mode:
                result.stdout = self._stdout.decode("utf-8")
                result.stderr = self._stderr.decode("utf-8")
            else:
                result.stdout = self._stdout
                result.stderr = self._stderr

            return result

        self._run_mock.side_effect = run_side_effect

    @property
    def mock(self) -> MagicMock:
        """Get the underlying Popen mock object for patching."""
        return self._mock

    @property
    def run_mock(self) -> MagicMock:
        """Get the underlying subprocess.run mock object for patching."""
        return self._run_mock

    @property
    def calls(self) -> list[list[str]]:
        """Get list of command arguments passed to subprocess."""
        return self._calls

    def set_output(self, stdout: str, stderr: str = "") -> None:
        """Set stdout and stderr for mock subprocess."""
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")

    def set_return_code(self, code: int) -> None:
        """Set return code for mock subprocess."""
        self._returncode = code

    def set_exception(self, exc: Exception) -> None:
        """Configure subprocess to raise an exception."""
        self._should_raise = exc

    def reset(self) -> None:
        """Reset calls and configure defaults."""
        self._calls.clear()
        self._stdout = b""
        self._stderr = b""
        self._returncode = 0
        self._should_raise = None


@pytest.fixture
def subprocess_mock(monkeypatch: pytest.MonkeyPatch) -> SubprocessMock:
    """Provide controllable subprocess mock for testing.

    This fixture gives tests explicit control over subprocess behavior.
    Use this when you need to:
    - Verify specific commands were called
    - Test different stdout/stderr outputs
    - Test error handling for non-zero return codes
    - Test exception handling

    IMPORTANT: Using this fixture disables STRICT MODE for the test.
    Subprocess calls will succeed with the configured behavior instead
    of failing with AssertionError.

    Example:
        def test_launcher_output_parsing(subprocess_mock):
            subprocess_mock.set_output("workspace /shows/test/shots/010/0010")
            subprocess_mock.set_return_code(0)
            # ... test code ...
            assert ["ws", "-sg"] in subprocess_mock.calls

    """
    # Signal that subprocess_mock is active - disables strict mode
    _set_subprocess_mock_active(True)

    mock = SubprocessMock()
    # Patch Popen
    monkeypatch.setattr("subprocess.Popen", mock.mock)
    # Patch subprocess.run
    monkeypatch.setattr("subprocess.run", mock.run_mock)
    return mock


@pytest.fixture
def subprocess_error_mock(monkeypatch: pytest.MonkeyPatch) -> SubprocessMock:
    """Provide subprocess mock pre-configured for error scenarios.

    This fixture returns a SubprocessMock that fails by default (return code 1).
    Use this when testing error handling paths in code that calls subprocess.
    """
    _set_subprocess_mock_active(True)

    mock = SubprocessMock()
    mock.set_return_code(1)
    mock.set_output("", stderr="Command failed")
    monkeypatch.setattr("subprocess.Popen", mock.mock)
    monkeypatch.setattr("subprocess.run", mock.run_mock)
    return mock


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


# ---------------------------------------------------------------------------
# cache_doubles contents
# ---------------------------------------------------------------------------

import time as _time_module
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class TestProgressOperation:
    """Minimal test double for progress operations (internal to TestProgressManager)."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    title: str
    cancelable: bool = False
    progress: int = 0
    finished: bool = False


class TestProgressManager:
    """Test double for progress manager."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    _current_operation: ClassVar[TestProgressOperation | None] = None
    _operations_started: ClassVar[list[TestProgressOperation]] = []
    _operations_finished: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def start_operation(cls, config: Any) -> TestProgressOperation:
        """Start a new progress operation."""
        if isinstance(config, str):
            operation = TestProgressOperation(title=config)
        else:
            # Handle config object
            title = getattr(config, "title", "Test Operation")
            cancelable = getattr(config, "cancelable", False)
            operation = TestProgressOperation(title=title, cancelable=cancelable)

        cls._current_operation = operation
        cls._operations_started.append(operation)
        return operation

    @classmethod
    def finish_operation(cls, success: bool = True, error_message: str = "") -> None:
        """Finish the current progress operation."""
        if cls._current_operation:
            cls._operations_finished.append(
                {
                    "operation": cls._current_operation,
                    "success": success,
                    "error_message": error_message,
                    "timestamp": _time_module.time(),
                }
            )
            cls._current_operation = None

    @classmethod
    def get_current_operation(cls) -> TestProgressOperation | None:
        """Get the current progress operation."""
        return cls._current_operation


    @classmethod
    def get_operations_started_count(cls) -> int:
        """Get number of operations started (for testing)."""
        return len(cls._operations_started)

    @classmethod
    def get_operations_finished_count(cls) -> int:
        """Get number of operations finished (for testing)."""
        return len(cls._operations_finished)


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
    allow_main = "allow_main_thread" in [
        m.name for m in request.node.iter_markers()
    ]
    return TestProcessPool(
        strict=not is_permissive,
        enforce_thread_guard=enforce_guard,
        allow_main_thread=allow_main,
    )
