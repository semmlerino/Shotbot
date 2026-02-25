"""Test doubles for replacing real dependencies in tests.

This module provides test doubles (fakes, stubs, mocks) for complex dependencies
that are difficult or unsafe to use in tests. These doubles implement the same
interfaces as their real counterparts but with controllable behavior.

Fixtures:
    test_process_pool: TestProcessPool instance for mocking ProcessPoolManager
    make_test_launcher: Factory for creating CustomLauncher instances

Classes:
    SignalDouble: Lightweight signal test double for non-Qt objects
    QtSignalDouble: Qt-backed signal double with proper cross-thread semantics
    TestProcessPool: Unified test double for ProcessPoolManager
    TestCompletedProcess: Test double for subprocess.CompletedProcess
    TestSubprocess: Test double for subprocess operations
    PopenDouble: Test double for subprocess.Popen
    TestShot: Test double for Shot objects
    TestShotModel: Test double for ShotModel with real Qt signals
    TestCacheManager: Test double for CacheManager with real Qt signals
    TestLauncherEnvironment: Test double for launcher environment
    TestLauncherTerminal: Test double for launcher terminal settings
    TestLauncher: Test double for launcher configuration
    LauncherManagerDouble: Test double for LauncherManager with real Qt signals
    TestWorker: Test double for worker threads (QThread-based)
    ThreadSafeTestImage: Thread-safe test double for QPixmap using QImage
    TestProgressOperation: Minimal test double for progress operations
    TestProgressManager: Test double for progress manager
    TestFileSystem: Test double for file system operations
    TestQtWidget: Test double for Qt widget testing
    TestCache: In-memory cache replacement for testing
    TestThreadWorker: Thread-safe worker double for testing async operations
    TestCommand: Command executor double for testing command execution
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal
from PySide6.QtGui import QColor, QImage


def simulate_work_without_sleep(duration_ms: int = 10) -> None:
    """Simulate work without blocking the thread.

    Busy-waits for the given duration to simulate CPU work without
    using time.sleep() which can cause Qt event loop issues.

    Args:
        duration_ms: Duration in milliseconds to simulate work.

    """
    start = time.perf_counter()
    target = start + (duration_ms / 1000.0)
    while time.perf_counter() < target:
        time.sleep(0)  # Yield to other threads


if TYPE_CHECKING:
    from collections.abc import Callable


class SignalDouble:
    """Lightweight signal test double for non-Qt objects.

    Use this instead of trying to use QSignalSpy on Mock objects,
    which will crash. This provides a simple interface for testing
    signal emissions and connections.

    Example:
        signal = SignalDouble()
        results = []
        signal.connect(lambda *args: results.append(args))
        signal.emit("test", 123)
        assert signal.was_emitted
        assert results == [("test", 123)]

    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize the test signal."""
        self.emissions: list[tuple[Any, ...]] = []
        self.callbacks: list[Callable[..., Any]] = []

    def emit(self, *args: Any) -> None:
        """Emit the signal with arguments."""
        self.emissions.append(args)
        for callback in self.callbacks:
            try:
                callback(*args)
            except Exception as e:
                print(f"SignalDouble callback error: {e}")

    def connect(self, callback: Callable[..., Any], connection_type: Any = None) -> None:
        """Connect a callback to the signal.

        Args:
            callback: Callable to invoke on emit.
            connection_type: Ignored; accepted for Qt API compatibility.
        """
        self.callbacks.append(callback)

    def disconnect(self, callback: Callable[..., Any] | None = None) -> None:
        """Disconnect a callback or all callbacks."""
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)

    @property
    def was_emitted(self) -> bool:
        """Check if the signal was emitted at least once."""
        return len(self.emissions) > 0

    @property
    def emit_count(self) -> int:
        """Get the number of times the signal was emitted."""
        return len(self.emissions)

    def get_last_emission(self) -> tuple[Any, ...] | None:
        """Get the arguments from the last emission."""
        if self.emissions:
            return self.emissions[-1]
        return None

    def clear(self) -> None:
        """Clear emission history and callbacks."""
        self.emissions.clear()
        self.callbacks.clear()

    def reset(self) -> None:
        """Reset emission history (keeps callbacks)."""
        self.emissions.clear()


class QtSignalDouble:
    """Qt-backed signal double with proper cross-thread semantics.

    Unlike SignalDouble which uses synchronous Python callbacks, this class
    uses real Qt Signal internally to preserve proper queued connection
    semantics. This is important for testing code that relies on Qt signal
    ordering and thread-safety.

    Use this when:
    - Testing code that emits signals from background threads
    - Testing code that relies on signal ordering
    - Verifying that signals are properly queued

    Example:
        signal = QtSignalDouble()
        results = []
        signal.connect(lambda *args: results.append(args))
        signal.emit("test", 123)
        # Process Qt events to deliver queued signals
        QCoreApplication.processEvents()
        assert signal.was_emitted
        assert results == [("test", 123)]

    Note:
        Requires QApplication to be running. Use with qtbot fixture.

    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self, parent: Any = None) -> None:
        """Initialize the Qt-backed test signal.

        Args:
            parent: Optional parent QObject for proper Qt ownership.

        """
        from PySide6.QtCore import Qt

        # Create a QObject subclass dynamically to host the signal
        class SignalHost(QObject):
            signal = Signal(object)  # Generic signal carrying tuple of args

        self._host = SignalHost(parent)
        self.emissions: list[tuple[Any, ...]] = []
        self.callbacks: list[Any] = []

        # Connect internal recording (queued for proper thread semantics)
        self._host.signal.connect(
            self._record_emission,
            Qt.ConnectionType.QueuedConnection
        )

    def _record_emission(self, args: tuple[Any, ...]) -> None:
        """Record emission and invoke callbacks."""
        self.emissions.append(args)
        for callback in self.callbacks:
            try:
                callback(*args)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("QtSignalDouble callback error: %s", e)

    def emit(self, *args: Any) -> None:
        """Emit the signal with arguments.

        Note: Due to QueuedConnection, emissions are delivered when Qt
        event loop processes events, not immediately.
        """
        self._host.signal.emit(args)

    def connect(self, callback: Any) -> None:
        """Connect a callback to the signal."""
        self.callbacks.append(callback)

    def disconnect(self, callback: Any | None = None) -> None:
        """Disconnect a callback or all callbacks."""
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)

    @property
    def was_emitted(self) -> bool:
        """Check if the signal was emitted at least once."""
        return len(self.emissions) > 0

    @property
    def emit_count(self) -> int:
        """Get the number of times the signal was emitted."""
        return len(self.emissions)

    def get_last_emission(self) -> tuple[Any, ...] | None:
        """Get the arguments from the last emission."""
        if self.emissions:
            return self.emissions[-1]
        return None

    def clear(self) -> None:
        """Clear emission history and callbacks."""
        self.emissions.clear()
        self.callbacks.clear()

    def cleanup(self) -> None:
        """Clean up Qt resources."""
        self._host.signal.disconnect()
        self._host.deleteLater()


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
        except Exception:
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


@pytest.fixture
def make_test_launcher():
    """Factory fixture for creating CustomLauncher instances for testing.

    Returns a callable that creates CustomLauncher instances with sensible
    defaults for testing. All parameters are optional.

    Example usage:
        def test_launcher(make_test_launcher):
            launcher = make_test_launcher(name="Test", command="echo test")
            assert launcher.name == "Test"
    """
    from launcher import CustomLauncher

    def _make_launcher(
        name: str = "Test Launcher",
        command: str = "echo {shot_name}",
        description: str = "Test launcher",
        category: str = "test",
        launcher_id: str | None = None,
    ):
        """Create a CustomLauncher instance for testing.

        Args:
            name: Launcher name (default: "Test Launcher")
            command: Command to execute (default: "echo {shot_name}")
            description: Launcher description (default: "Test launcher")
            category: Launcher category (default: "test")
            launcher_id: Launcher ID (default: auto-generated UUID)

        Returns:
            CustomLauncher instance

        """
        if launcher_id is None:
            launcher_id = str(uuid.uuid4())

        return CustomLauncher(
            id=launcher_id,
            name=name,
            command=command,
            description=description,
            category=category,
        )

    return _make_launcher


@pytest.fixture
def shot_model_factory(test_process_pool: TestProcessPool):
    """Factory for ShotModel with injected test doubles.

    Creates ShotModel instances with the test process pool already injected
    via constructor, which is preferred over mutating model._process_pool
    after construction.

    Example usage:
        def test_something(shot_model_factory, test_process_pool, tmp_path):
            test_process_pool.set_outputs("workspace /shows/test/shots/sq01/sh01")
            model = shot_model_factory(cache_dir=tmp_path / "cache")
            # model already has test_process_pool injected via constructor

    Args:
        test_process_pool: The TestProcessPool fixture for mocking subprocess

    Returns:
        Factory callable that creates configured ShotModel instances

    """
    from cache_manager import CacheManager
    from shot_model import ShotModel

    def _create_model(
        cache_dir: Path | None = None,
        cache_manager: CacheManager | None = None,
        load_cache: bool = False,
        **kwargs: Any,
    ) -> ShotModel:
        """Create a ShotModel with test doubles.

        Args:
            cache_dir: Optional directory for cache (creates CacheManager if provided)
            cache_manager: Optional pre-configured CacheManager (takes precedence over cache_dir)
            load_cache: Whether to load existing cache on init (default False for tests)
            **kwargs: Additional arguments passed to ShotModel

        Returns:
            ShotModel instance with test_process_pool injected

        """
        if cache_manager is None and cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_manager = CacheManager(cache_dir=cache_dir)

        return ShotModel(
            cache_manager=cache_manager,
            load_cache=load_cache,
            process_pool=test_process_pool,
            **kwargs,
        )

    return _create_model


# =============================================================================
# SUBPROCESS TEST DOUBLES
# =============================================================================


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


# =============================================================================
# SHOT AND MODEL TEST DOUBLES
# =============================================================================


@dataclass
class TestShot:
    """Test double for Shot objects with real behavior."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    show: str = "test_show"
    sequence: str = "seq01"
    shot: str = "0010"
    workspace_path: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        """Initialize computed fields."""
        if not self.workspace_path:
            self.workspace_path = (
                f"/shows/{self.show}/shots/{self.sequence}/{self.sequence}_{self.shot}"
            )
        if not self.name:
            self.name = f"{self.sequence}_{self.shot}"

    @property
    def full_name(self) -> str:
        """Get full shot name (matches real Shot class interface)."""
        return f"{self.sequence}_{self.shot}"

    def get_thumbnail_path(self) -> Path:
        """Get path to thumbnail with real path construction."""
        return Path(self.workspace_path) / "publish" / "editorial" / "thumbnail.jpg"  # type: ignore[arg-type]

    def get_plate_path(self) -> Path:
        """Get path to plate directory."""
        return Path(self.workspace_path) / "publish" / "plates"  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for serialization."""
        return {
            "show": self.show,
            "sequence": self.sequence,
            "shot": self.shot,
            "workspace_path": self.workspace_path or "",
            "name": self.name or "",
        }


class TestShotModel(QObject):
    """Test double for ShotModel with real Qt signals."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    # Real Qt signals for proper testing
    shots_updated = Signal()
    shot_selected = Signal(str)
    refresh_started = Signal()
    refresh_finished = Signal(bool)
    error_occurred = Signal(str)  # Added to match real ShotModel interface

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize test shot model."""
        super().__init__(parent)
        self._shots: list[TestShot] = []
        self._selected_shot: TestShot | None = None
        self.refresh_count = 0
        self.signal_emissions: dict[str, int] = {
            "shots_updated": 0,
            "shot_selected": 0,
            "refresh_started": 0,
            "refresh_finished": 0,
        }

        # Connect signals to track emissions
        self.shots_updated.connect(lambda: self._track_signal("shots_updated"))
        self.shot_selected.connect(lambda _x: self._track_signal("shot_selected"))
        self.refresh_started.connect(lambda: self._track_signal("refresh_started"))
        self.refresh_finished.connect(lambda _x: self._track_signal("refresh_finished"))

    def _track_signal(self, signal_name: str) -> None:
        """Track signal emissions for testing."""
        self.signal_emissions[signal_name] += 1

    def add_shot(self, shot: TestShot) -> None:
        """Add a shot and emit signal."""
        self._shots.append(shot)
        self.shots_updated.emit()

    def add_test_shots(self, shots: list[TestShot]) -> None:
        """Add multiple shots at once."""
        self._shots.extend(shots)
        self.shots_updated.emit()

    def get_shots(self) -> list[TestShot]:
        """Get all shots."""
        return self._shots.copy()

    @property
    def shots(self) -> list[TestShot]:
        """Get all shots as property for compatibility with ShotGrid."""
        return self._shots.copy()

    def get_shot_by_name(self, name: str) -> TestShot | None:
        """Find shot by name."""
        for shot in self._shots:
            if shot.name == name:
                return shot
        return None

    def refresh_shots(self, force_fresh: bool = False) -> tuple[bool, bool]:
        """Simulate shot refresh with configurable behavior."""
        self.refresh_count += 1
        self.refresh_started.emit()

        # Simulate some work
        simulate_work_without_sleep(10)  # 10ms

        # Determine if there are changes
        has_changes = self.refresh_count == 1 or len(self._shots) == 0

        if has_changes and self.refresh_count == 1:
            # Add default test shots on first refresh
            self.add_test_shots(
                [
                    TestShot("show1", "seq01", "0010"),
                    TestShot("show1", "seq01", "0020"),
                    TestShot("show1", "seq02", "0030"),
                ]
            )

        self.refresh_finished.emit(True)
        return (True, has_changes)

    def select_shot(self, shot: TestShot | str) -> None:
        """Select a shot and emit signal."""
        if isinstance(shot, str):
            shot = self.get_shot_by_name(shot)  # type: ignore[assignment]
        if shot:
            self._selected_shot = shot  # type: ignore[assignment]
            # Handle both TestShot and real Shot objects
            shot_name = getattr(shot, "name", None) or getattr(
                shot, "full_name", str(shot)
            )
            self.shot_selected.emit(shot_name)

    def clear(self) -> None:
        """Clear all shots."""
        self._shots.clear()
        self._selected_shot = None
        self.shots_updated.emit()

    def set_show_filter(self, show: str | None) -> None:
        """Set the show filter.

        Args:
            show: Show name to filter by or None for all shows

        """
        self._filter_show = show

    def get_filtered_shots(self) -> list[TestShot]:
        """Get shots filtered by the current show filter.

        Returns:
            Filtered list of shots

        """
        if not hasattr(self, "_filter_show"):
            self._filter_show = None

        if self._filter_show is None:
            return self._shots.copy()

        return [shot for shot in self._shots if shot.show == self._filter_show]

    def get_available_shows(self) -> set[str]:
        """Get all unique show names from current shots.

        Returns:
            Set of unique show names

        """
        return {shot.show for shot in self._shots}


# =============================================================================
# CACHE TEST DOUBLES
# =============================================================================


class TestCacheManager(QObject):
    """Test double for CacheManager with real behavior."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    cache_updated = Signal()
    thumbnail_cached = Signal(str)
    shots_migrated = Signal(list)  # Emitted when shots migrate to Previous Shots

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize test cache manager."""
        super().__init__()
        self.cache_dir = cache_dir or Path("/tmp/test_cache")
        self._cached_thumbnails: dict[str, Path] = {}
        self._cached_shots: list[TestShot] = []
        self._cached_previous_shots: list[dict[str, Any]] | None = None
        self._memory_usage_bytes: int = 0
        self._cache_operations: list[dict[str, Any]] = []
        self.thumbnails_dir = self.cache_dir / "thumbnails"

    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
        wait: bool = True,
        timeout: float | None = None,
    ) -> Path | None:
        """Cache a thumbnail with real behavior."""
        source = Path(source_path)
        cache_key = f"{show}_{sequence}_{shot}"

        # Record operation
        self._cache_operations.append(
            {
                "operation": "cache_thumbnail",
                "source": str(source),
                "key": cache_key,
                "timestamp": time.time(),
            }
        )

        # Simulate caching
        cached_path = self.cache_dir / "thumbnails" / show / sequence / f"{shot}.jpg"
        cached_path.parent.mkdir(parents=True, exist_ok=True)

        # Simulate file copy (just track it)
        self._cached_thumbnails[cache_key] = cached_path
        self._memory_usage_bytes += 50000  # Simulate 50KB thumbnail

        self.thumbnail_cached.emit(cache_key)
        self.cache_updated.emit()

        return cached_path

    def get_cached_thumbnail(self, show: str, sequence: str, shot: str) -> Path | None:
        """Get cached thumbnail path."""
        cache_key = f"{show}_{sequence}_{shot}"
        return self._cached_thumbnails.get(cache_key)

    def load_thumbnail_async(
        self, path: str | Path, size: tuple[int, int], callback: Callable[..., Any]
    ) -> Any:
        """Load a thumbnail asynchronously (test double)."""
        from concurrent.futures import Future

        from PySide6.QtCore import Qt

        future: Future[QImage] = Future()

        # Create a test image
        test_image = QImage(size[0], size[1], QImage.Format.Format_RGB32)
        test_image.fill(Qt.GlobalColor.blue)

        # Call the callback synchronously in test mode
        try:
            callback(str(path), test_image)
            future.set_result(test_image)
        except Exception as e:
            future.set_exception(e)

        return future

    def cache_shots(self, shots: list[TestShot | dict[str, str]]) -> bool:
        """Cache shot data."""
        self._cached_shots.clear()
        for shot in shots:
            shot_obj = TestShot(**shot) if isinstance(shot, dict) else shot
            self._cached_shots.append(shot_obj)
        self.cache_updated.emit()
        return True

    def get_cached_shots(self) -> list[TestShot]:
        """Get cached shots."""
        return self._cached_shots.copy()

    def get_cached_previous_shots(self) -> list[dict[str, Any]] | None:
        """Get cached previous/approved shot list if valid."""
        return (
            self._cached_previous_shots.copy() if self._cached_previous_shots else None
        )

    def get_persistent_previous_shots(self) -> list[dict[str, Any]] | None:
        """Get cached previous/approved shot list without TTL expiration.

        This method mirrors the persistent cache behavior where shots
        accumulate indefinitely without expiration.
        """
        return (
            self._cached_previous_shots.copy() if self._cached_previous_shots else None
        )

    def get_persistent_shots(self) -> list[dict[str, Any]] | None:
        """Get My Shots cache without TTL expiration.

        Similar to get_persistent_previous_shots() but for active shots.
        Enables incremental caching by preserving shot history.

        Returns:
            List of shot dictionaries or None if not cached

        """
        if not self._cached_shots:
            return None
        return [shot.to_dict() for shot in self._cached_shots]

    def cache_previous_shots(self, shots: list[TestShot | dict[str, Any]]) -> bool:
        """Cache previous shot data."""
        self._cached_previous_shots = []
        for shot in shots:
            shot_dict = shot.to_dict() if isinstance(shot, TestShot) else shot
            self._cached_previous_shots.append(shot_dict)
        self.cache_updated.emit()
        return True

    def get_memory_usage(self) -> dict[str, Any]:
        """Get memory usage statistics."""
        return {
            "total_mb": self._memory_usage_bytes / (1024 * 1024),
            "thumbnail_count": len(self._cached_thumbnails),
            "shot_count": len(self._cached_shots),
        }

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._cached_thumbnails.clear()
        self._cached_shots.clear()
        self._cached_previous_shots = None
        self._memory_usage_bytes = 0
        self._cache_operations.clear()
        self.cache_updated.emit()

    def clear_cached_data(self, key: str) -> None:
        """Clear cached generic data by key (for backward compatibility).

        Args:
            key: Cache key identifier

        """
        if key == "previous_shots":
            self._cached_previous_shots = None
        # For compatibility with other potential keys, we could extend this
        # but for now we only need previous_shots support
        self.cache_updated.emit()

    def get_cached_data(self, key: str) -> object | None:
        """Get cached generic data by key.

        Args:
            key: Cache key identifier

        Returns:
            Cached data or None if not found

        """
        # Test double: return None for any key (no persistent generic cache)
        return None

    def get_migrated_shots(self) -> list[dict[str, Any]] | None:
        """Get shots that were migrated from My Shots.

        Returns:
            List of migrated shot dictionaries or None

        """
        # Test double: return None (no migration tracking)
        return None

    def validate_cache(self) -> dict[str, Any]:
        """Validate cache integrity."""
        return {
            "valid": True,
            "orphaned_files": 0,
            "missing_files": 0,
            "invalid_entries": 0,
            "issues_found": 0,
            "issues_fixed": 0,
        }

    def get_cached_threede_scenes(self) -> list[dict[str, Any]] | None:
        """Get cached 3DE scene list if valid."""
        # For testing, return empty list to simulate no cached scenes initially
        return []

    def cache_threede_scenes(
        self, scenes: list[dict[str, Any]], metadata: dict[str, Any] | None = None
    ) -> bool:
        """Cache 3DE scene data."""
        # For testing, just track that this was called
        self._cache_operations.append(
            {
                "operation": "cache_threede_scenes",
                "scene_count": len(scenes),
                "metadata": metadata,
                "timestamp": time.time(),
            }
        )
        self.cache_updated.emit()
        return True

    def shutdown(self) -> None:
        """Gracefully shutdown the cache manager (test double)."""
        # For testing, just clear all cached data
        self.clear_cache()


# =============================================================================
# LAUNCHER TEST DOUBLES
# =============================================================================


class TestLauncherEnvironment:
    """Test double for launcher environment."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(
        self,
        env_type: str = "none",
        packages: list[str] | None = None,
        command_prefix: str = "",
    ) -> None:
        self.type = env_type
        self.packages = packages or []
        self.command_prefix = command_prefix


class TestLauncherTerminal:
    """Test double for launcher terminal settings."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self, persist: bool = False, background: bool = False) -> None:
        self.persist = persist
        self.background = background


class TestLauncher:
    """Test double for launcher configuration."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(
        self,
        launcher_id: str | None = None,
        name: str = "Test Launcher",
        command: str = "echo {shot_name}",
        description: str = "Test launcher",
        category: str = "test",
        enabled: bool = True,
        environment: TestLauncherEnvironment | None = None,
        terminal: TestLauncherTerminal | None = None,
        launcher_id_compat: str | None = None,  # Backwards compatibility alias
    ) -> None:
        """Initialize test launcher."""
        # Support both launcher_id and launcher_id_compat parameter names
        self.id = (
            launcher_id_compat
            if launcher_id_compat is not None
            else (launcher_id if launcher_id is not None else "test_launcher")
        )
        self.name = name
        self.command = command
        self.description = description
        self.category = category
        self.enabled = enabled
        self.environment = environment or TestLauncherEnvironment()
        self.terminal = terminal or TestLauncherTerminal()
        self.execution_count = 0
        self.last_execution_args: dict[str, str | None] | None = None

    def execute(self, **kwargs: str) -> bool:
        """Simulate launcher execution."""
        self.execution_count += 1
        self.last_execution_args = kwargs  # type: ignore[assignment]
        return True


class LauncherManagerDouble(QObject):
    """Test double for LauncherManager with real signals."""

    launcher_added = Signal(str)
    launcher_removed = Signal(str)
    launcher_executed = Signal(str)
    execution_started = Signal(str)
    execution_finished = Signal(str, bool)
    launchers_changed = Signal()

    def __init__(self) -> None:
        """Initialize test launcher manager."""
        super().__init__()
        self._launchers: dict[str, TestLauncher] = {}
        self._execution_history: list[dict[str, Any]] = []
        self._validation_results: dict[str, tuple[bool, str | None]] = {}
        self._test_command: str | None = None  # For temporary test launchers

    def validate_command_syntax(self, command: str) -> tuple[bool, str | None]:
        """Validate command syntax with real behavior."""
        if not command or not command.strip():
            return (False, "Command cannot be empty")

        # Check for basic syntax issues
        if command.startswith("{") and not command.endswith("}"):
            return (False, "Unclosed variable substitution")

        # Allow override for testing specific scenarios
        if command in self._validation_results:
            return self._validation_results[command]

        return (True, None)

    def set_validation_result(
        self, command: str, is_valid: bool, error: str | None = None
    ) -> None:
        """Set custom validation result for testing."""
        self._validation_results[command] = (is_valid, error)

    def set_test_command(self, command: str) -> None:
        """Set command for temporary test launcher."""
        self._test_command = command

    def get_launcher_by_name(self, name: str) -> TestLauncher | None:
        """Find launcher by name with real search behavior."""
        for launcher in self._launchers.values():
            if launcher.name == name:
                return launcher
        return None

    def create_launcher(
        self,
        name: str,
        command: str,
        description: str = "",
        category: str = "custom",
        environment: TestLauncherEnvironment | None = None,
        terminal: TestLauncherTerminal | None = None,
    ) -> str | None:
        """Create a test launcher with real behavior."""
        # Check for duplicate names
        if self.get_launcher_by_name(name):
            return None  # Simulate creation failure

        launcher_id = f"launcher_{len(self._launchers)}"
        launcher = TestLauncher(launcher_id, name, command, description, category)
        self._launchers[launcher_id] = launcher
        self.launcher_added.emit(launcher_id)
        self.launchers_changed.emit()
        return launcher_id

    def update_launcher(
        self,
        launcher_id: str,
        name: str | None = None,
        command: str | None = None,
        description: str | None = None,
        category: str | None = None,
        environment: TestLauncherEnvironment | None = None,
        terminal: TestLauncherTerminal | None = None,
    ) -> bool:
        """Update existing launcher with real behavior."""
        if launcher_id not in self._launchers:
            return False

        launcher = self._launchers[launcher_id]

        # Check for name conflicts (excluding self)
        if name and name != launcher.name:
            existing = self.get_launcher_by_name(name)
            if existing and existing.id != launcher_id:
                return False

        # Apply updates
        if name is not None:
            launcher.name = name
        if command is not None:
            launcher.command = command
        if description is not None:
            launcher.description = description
        if category is not None:
            launcher.category = category

        self.launchers_changed.emit()
        return True

    def delete_launcher(self, launcher_id: str) -> bool:
        """Delete launcher with real behavior."""
        if launcher_id not in self._launchers:
            return False

        del self._launchers[launcher_id]
        self.launcher_removed.emit(launcher_id)
        self.launchers_changed.emit()
        return True

    def execute_launcher(
        self,
        launcher_id_or_launcher: str | TestLauncher,
        custom_vars: dict[str, str | None] | None = None,
        dry_run: bool = False,
    ) -> bool:
        """Execute a launcher with real behavior."""
        # Handle both launcher_id string and launcher object
        if hasattr(launcher_id_or_launcher, "id"):
            # It's a launcher object
            launcher_obj = launcher_id_or_launcher
            launcher_id = launcher_obj.id  # type: ignore[union-attr]
            if launcher_id not in self._launchers:
                # For test launcher objects, add temporarily
                self._launchers[launcher_id] = launcher_obj  # type: ignore[assignment]
        elif isinstance(launcher_id_or_launcher, str):
            # It's a launcher_id string
            launcher_id = launcher_id_or_launcher
        else:
            # Unsupported type
            raise ValueError(
                f"Expected launcher object or launcher_id string, got {type(launcher_id_or_launcher)}"
            )

        if launcher_id not in self._launchers:
            # For test scenarios, create a temporary launcher if it doesn't exist
            if launcher_id == "test":
                command = self._test_command or "echo test"
                temp_launcher = TestLauncher(
                    launcher_id=launcher_id, name="Temporary Test Launcher", command=command
                )
                self._launchers[launcher_id] = temp_launcher
            else:
                return False

        launcher = self._launchers[launcher_id]

        if not dry_run:
            self.execution_started.emit(launcher_id)

        # Record execution
        self._execution_history.append(
            {
                "launcher_id": launcher_id,
                "custom_vars": custom_vars,
                "dry_run": dry_run,
                "timestamp": time.time(),
            }
        )

        # Simulate execution (always succeeds unless command has issues)
        success = not launcher.command.startswith("bad")  # Simple failure simulation

        if not success:
            # Simulate execution failure with an exception
            raise RuntimeError(f"Command execution failed: {launcher.command}")

        if not dry_run:
            self.launcher_executed.emit(launcher_id)
            self.execution_finished.emit(launcher_id, success)

        return success

    def list_launchers(self) -> list[TestLauncher]:
        """List all launchers."""
        return list(self._launchers.values())

    def get_launcher(self, launcher_id: str) -> TestLauncher | None:
        """Get specific launcher."""
        return self._launchers.get(launcher_id)

    def was_dry_run_executed(self) -> bool:
        """Check if any dry run was executed (for testing)."""
        return any(entry.get("dry_run", False) for entry in self._execution_history)

    def get_created_launcher_count(self) -> int:
        """Get number of launchers created (for testing)."""
        return len(self._launchers)

    def get_last_created_launcher(self) -> TestLauncher | None:
        """Get the most recently created launcher (for testing)."""
        if not self._launchers:
            return None
        # Return the launcher with highest ID number (most recent)
        return max(
            self._launchers.values(),
            key=lambda launcher: int(launcher.id.split("_")[-1]),
        )


# =============================================================================
# WORKER TEST DOUBLES
# =============================================================================


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


# =============================================================================
# QT WIDGET TEST DOUBLES
# =============================================================================


class ThreadSafeTestImage:
    """Thread-safe test double for QPixmap using QImage internally.

    Critical for avoiding Qt threading violations in tests.
    QPixmap is NOT thread-safe and causes fatal errors in worker threads.
    QImage IS thread-safe and should be used instead.
    """

    def __init__(self, width: int = 100, height: int = 100) -> None:
        """Create a thread-safe test image."""
        # Use QImage which is thread-safe, unlike QPixmap
        self._image = QImage(width, height, QImage.Format.Format_RGB32)
        self._width = width
        self._height = height
        self._image.fill(QColor(255, 255, 255))  # White by default

    def fill(self, color: QColor | None = None) -> None:
        """Fill the image with a color."""
        if color is None:
            color = QColor(255, 255, 255)
        self._image.fill(color)

    def scaled(self, width: int, height: int) -> ThreadSafeTestImage:
        """Scale the image."""
        new_image = ThreadSafeTestImage(width, height)
        new_image._image = self._image.scaled(width, height)
        return new_image

    def size(self) -> tuple[int, int]:
        """Get image size as tuple."""
        return (self._width, self._height)

    def save(self, path: str | Path) -> bool:
        """Save image to file."""
        return self._image.save(str(path))

    def isNull(self) -> bool:
        """Check if image is null."""
        return self._image.isNull()

    def sizeInBytes(self) -> int:
        """Get size in bytes."""
        return self._image.sizeInBytes()


# =============================================================================
# PROGRESS MANAGER TEST DOUBLES
# =============================================================================


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
                    "timestamp": time.time(),
                }
            )
            cls._current_operation = None

    @classmethod
    def get_current_operation(cls) -> TestProgressOperation | None:
        """Get the current progress operation."""
        return cls._current_operation

    @classmethod
    def clear_all_operations(cls) -> None:
        """Clear all operations for testing."""
        cls._current_operation = None
        cls._operations_started.clear()
        cls._operations_finished.clear()

    @classmethod
    def get_operations_started_count(cls) -> int:
        """Get number of operations started (for testing)."""
        return len(cls._operations_started)

    @classmethod
    def get_operations_finished_count(cls) -> int:
        """Get number of operations finished (for testing)."""
        return len(cls._operations_finished)


# =============================================================================
# FILESYSTEM TEST DOUBLES
# =============================================================================


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
            qtbot.wait(1)  # Minimal event processing
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
        self.connections: dict[str, list[Callable[..., Any]]] = defaultdict(list)
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

    def connect(self, signal_name: str, callback: Callable[..., Any]) -> None:
        """Connect a callback to a signal."""
        self.connections[signal_name].append(callback)

    def disconnect(self, signal_name: str, callback: Callable[..., Any] | None = None) -> None:
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
            oldest_key = min(self.access_times, key=self.access_times.get)  # type: ignore[arg-type]
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
        self.fail_after_n_calls: int | None = None
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
