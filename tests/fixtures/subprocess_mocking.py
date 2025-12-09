"""Subprocess mocking fixtures for parallel test execution.

This module provides fixtures for mocking subprocess execution. The default
behavior is STRICT: unexpected subprocess calls FAIL immediately.

DESIGN PHILOSOPHY:
- STRICT MODE (default): Unexpected subprocess calls fail with AssertionError
- Tests must register expected commands OR use markers to opt-out
- This prevents silent success that masks bugs in error handling

HANDLING SUBPROCESS CALLS:
    1. Use subprocess_mock fixture and configure expected commands:
        def test_foo(subprocess_mock):
            subprocess_mock.set_output("success")
            # ... test code that calls subprocess ...

    2. Use @pytest.mark.real_subprocess for real subprocess execution:
        @pytest.mark.real_subprocess
        def test_real_command(): ...

    3. Use @pytest.mark.permissive_subprocess for legacy tests (DISCOURAGED):
        @pytest.mark.permissive_subprocess  # Deprecated - update to use subprocess_mock
        def test_legacy(): ...

Fixture Types:
    AUTOUSE (strict by default):
        mock_process_pool_manager: Patches ProcessPoolManager singleton
        mock_subprocess_popen: Patches subprocess.Popen globally (FAILS on unexpected)

    OPT-IN (control):
        subprocess_mock: Controllable mock for testing command execution
        subprocess_error_mock: Pre-configured for error scenarios
        subprocess_timeout_mock: Simulates timeout/hanging processes

DEBUGGING:
    Set SHOTBOT_TEST_TRACK_POPEN=1 to enable call tracking in the autouse mock.
    Use get_popen_calls() to retrieve tracked commands for debugging.
"""

from __future__ import annotations

import io
import os
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
import threading


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


def _set_permissive_mode(enabled: bool) -> None:
    """Set permissive mode for current test."""
    state = _get_current_state()
    state.permissive_mode = enabled


def _set_subprocess_mock_active(active: bool) -> None:
    """Set subprocess_mock fixture state for current test."""
    state = _get_current_state()
    state.subprocess_mock_active = active


def _format_cmd(cmd: object) -> str:
    """Format command for display in error messages."""
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(c) for c in cmd)
    return str(cmd)


# ==============================================================================
# OPT-IN CALL TRACKING (for debugging)
# ==============================================================================
# Module-level call tracking, enabled via SHOTBOT_TEST_TRACK_POPEN=1
_popen_calls: list[list[str]] = []
_TRACK_POPEN = os.environ.get("SHOTBOT_TEST_TRACK_POPEN", "").lower() in (
    "1",
    "true",
    "yes",
)


def get_popen_calls() -> list[list[str]]:
    """Get commands passed to Popen (only populated if SHOTBOT_TEST_TRACK_POPEN=1).

    Returns a copy of the tracked calls list for the current test.

    Example:
        # Enable tracking: SHOTBOT_TEST_TRACK_POPEN=1 pytest ...
        from tests.fixtures.subprocess_mocking import get_popen_calls
        calls = get_popen_calls()
        assert any("nuke" in " ".join(c) for c in calls)

    """
    return _popen_calls.copy()


def clear_popen_calls() -> None:
    """Clear tracked Popen calls.

    Called automatically at the start of each test when tracking is enabled.
    """
    _popen_calls.clear()


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
    from tests.fixtures.test_doubles import TestProcessPool

    internal_pool = TestProcessPool(
        strict=not is_permissive,
        enforce_thread_guard=enforce_guard,
        allow_main_thread=allow_main,
    )

    # Patch the singleton instance directly - get_instance() checks this first
    monkeypatch.setattr(
        "process_pool_manager.ProcessPoolManager._instance",
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

    # Clear tracked calls at the start of each test (if tracking enabled)
    if _TRACK_POPEN:
        clear_popen_calls()

    def _create_mock_popen(*args: object, **kwargs: object) -> MagicMock:
        """Create Popen mock with STRICT MODE."""
        # Track the command (only if enabled via SHOTBOT_TEST_TRACK_POPEN=1)
        cmd_str = ""
        if args:
            cmd = args[0]
            cmd_str = _format_cmd(cmd)
            if _TRACK_POPEN:
                if isinstance(cmd, (list, tuple)):
                    _popen_calls.append([str(c) for c in cmd])
                else:
                    _popen_calls.append([str(cmd)])

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
            if _TRACK_POPEN:
                if isinstance(cmd, (list, tuple)):
                    _popen_calls.append([str(c) for c in cmd])
                else:
                    _popen_calls.append([str(cmd)])

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


# ==============================================================================
# OPT-IN ERROR FIXTURES
# ==============================================================================
# These fixtures are NOT autouse - use them explicitly when testing error paths


@pytest.fixture
def subprocess_error_mock(monkeypatch: pytest.MonkeyPatch) -> SubprocessMock:
    """Provide subprocess mock pre-configured for error scenarios.

    This fixture returns a SubprocessMock that fails by default (return code 1).
    Use this when testing error handling paths in code that calls subprocess.

    Example:
        def test_launcher_handles_failure(subprocess_error_mock):
            subprocess_error_mock.set_output("", stderr="Command not found")
            result = my_launcher.run_command()
            assert result.success is False

    """
    # Signal that subprocess_mock is active - disables strict mode
    _set_subprocess_mock_active(True)

    mock = SubprocessMock()
    mock.set_return_code(1)  # Default to failure
    mock.set_output("", stderr="Command failed")
    monkeypatch.setattr("subprocess.Popen", mock.mock)
    monkeypatch.setattr("subprocess.run", mock.run_mock)
    return mock


@pytest.fixture
def subprocess_timeout_mock(monkeypatch: pytest.MonkeyPatch) -> SubprocessMock:
    """Provide subprocess mock that simulates timeout/hanging processes.

    This fixture creates a subprocess mock that never returns when polled,
    useful for testing timeout handling logic.

    Example:
        def test_launcher_timeout(subprocess_timeout_mock):
            with pytest.raises(TimeoutError):
                my_launcher.run_command(timeout=1)

    """
    # Signal that subprocess_mock is active - disables strict mode
    _set_subprocess_mock_active(True)

    mock = SubprocessMock()
    # Configure to never complete (poll returns None)
    mock._mock.return_value.poll.return_value = None
    mock._mock.return_value.returncode = None
    monkeypatch.setattr("subprocess.Popen", mock.mock)
    monkeypatch.setattr("subprocess.run", mock.run_mock)
    return mock


@pytest.fixture
def subprocess_exception_mock(monkeypatch: pytest.MonkeyPatch) -> SubprocessMock:
    """Provide subprocess mock that raises OSError on Popen.

    This fixture simulates the case where the subprocess cannot be started
    at all (e.g., command not found, permission denied).

    Example:
        def test_launcher_handles_missing_command(subprocess_exception_mock):
            subprocess_exception_mock.set_exception(
                FileNotFoundError("[Errno 2] No such file or directory: 'missing_cmd'")
            )
            result = my_launcher.run_command("missing_cmd")
            assert result.error_type == "FileNotFoundError"

    """
    # Signal that subprocess_mock is active - disables strict mode
    _set_subprocess_mock_active(True)

    mock = SubprocessMock()
    mock.set_exception(FileNotFoundError("[Errno 2] No such file or directory"))
    monkeypatch.setattr("subprocess.Popen", mock.mock)
    monkeypatch.setattr("subprocess.run", mock.run_mock)
    return mock
