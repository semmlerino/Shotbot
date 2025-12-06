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
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QCoreApplication, QThread


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

    def connect(self, callback: Callable[..., Any]) -> None:
        """Connect a callback to the signal."""
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
        from PySide6.QtCore import QObject, Qt, Signal

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
    - test_doubles_library.py TestProcessPool (metrics)
    - test_doubles_extended.py TestProcessPoolDouble (kwargs tracking, delays)

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
        allow_main_thread: bool = True,
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
            allow_main_thread: If True (default), allow calls from main/UI thread.
                   Default True for backward compatibility with existing tests.
            enforce_thread_guard: If True, reject main-thread calls like the real ProcessPoolManager.
                   Use this in contract tests to verify proper threading behavior.
                   Takes precedence over allow_main_thread.
        """
        # Feature flags
        self._ttl_aware = ttl_aware
        self._track_kwargs = track_kwargs
        self._strict = strict
        # For backward compatibility: allow_main_thread=True by default
        # For contract testing: enforce_thread_guard=True to enable the guard
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
    """
    # Check for markers
    is_permissive = "permissive_process_pool" in [
        m.name for m in request.node.iter_markers()
    ]
    enforce_guard = "enforce_thread_guard" in [
        m.name for m in request.node.iter_markers()
    ]
    return TestProcessPool(strict=not is_permissive, enforce_thread_guard=enforce_guard)


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
