"""Refactored ProcessPoolManager tests following UNIFIED_TESTING_GUIDE principles.

This refactored version demonstrates:
1. NO Mock() usage - uses test doubles with realistic behavior
2. Tests behavior through state changes and outcomes
3. Only mocks at system boundaries (subprocess)
4. Tests actual functionality, not implementation details

Key improvements over the original:
- Removed Mock() and @patch decorators
- Created BashSessionDouble with realistic behavior
- Tests actual caching behavior, not mock calls
- Verifies outcomes, not method invocations
"""

from __future__ import annotations

# Standard library imports
import threading
import time
from pathlib import Path
from typing import Self

# Third-party imports
import pytest

# Local application imports
from process_pool_manager import (
    CommandCache,
    ProcessMetrics,
    ProcessPoolManager,
)


pytestmark = [pytest.mark.unit, pytest.mark.slow]


# =============================================================================
# TEST DOUBLES AT SYSTEM BOUNDARY
# =============================================================================


class BashSessionDouble:
    """Test double for PersistentBashSession at system boundary.

    Provides realistic bash session behavior without actual subprocess.
    This is the ONLY place we mock - at the actual system boundary.
    """

    def __init__(self) -> None:
        """Initialize with predictable behavior."""
        self.executed_commands: list[str] = []
        self.responses: dict[str, str] = {}
        self.should_fail = False
        self.failure_message = "Command failed"
        self.execution_delay = 0.0  # Simulate execution time
        self.is_closed = False

    def execute(self, command: str, timeout: float | None = None) -> str:
        """Execute command with realistic behavior."""
        if self.is_closed:
            raise RuntimeError("Session is closed")

        self.executed_commands.append(command)

        # Simulate execution delay
        if self.execution_delay > 0:
            time.sleep(self.execution_delay)

        # Handle failure scenarios
        if self.should_fail:
            raise Exception(self.failure_message)

        # Return configured response first (highest priority)
        if command in self.responses:
            return self.responses[command]

        # Generate realistic default responses
        if command.startswith("echo "):
            return command[5:]  # Return what echo would output
        if command.startswith("ls "):
            return "file1.txt\nfile2.txt\nfile3.txt"
        if command == "pwd":
            return "/home/user/workspace"
        return f"Output for: {command}"

    def set_response(self, command: str, response: str) -> None:
        """Configure specific response for testing."""
        self.responses[command] = response

    def close(self) -> None:
        """Close the session."""
        self.is_closed = True

    def reset(self) -> None:
        """Reset for fresh test."""
        self.executed_commands.clear()
        self.responses.clear()
        self.should_fail = False
        self.is_closed = False


class InjectableProcessPoolManager(ProcessPoolManager):
    """ProcessPoolManager with dependency injection for testing.

    Allows injection of BashSessionDouble without mocking the manager itself.
    Bypasses singleton pattern to ensure fresh instances for each test.
    """

    def __new__(cls, *_args, **_kwargs) -> Self:
        """Override to bypass singleton pattern in tests."""
        # Don't use singleton for test instances - use QObject's __new__
        # Third-party imports
        from PySide6.QtCore import QObject

        return QObject.__new__(cls)

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize with optional session injection."""
        # Initialize directly without calling super().__init__() to avoid singleton issues
        # Standard library imports
        import concurrent.futures

        # Third-party imports
        from PySide6.QtCore import QObject

        # Local application imports
        from secure_command_executor import get_secure_executor

        QObject.__init__(self)  # Initialize QObject directly

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        # Initialize secure executor (required by parent class methods)
        self._secure_executor = get_secure_executor()
        self._session_pools: dict[str, list[BashSessionDouble]] = {}
        self._session_round_robin: dict[str, int] = {}
        self._sessions_per_type = 3
        self._cache = CommandCache(default_ttl=30)
        self._session_lock = threading.RLock()
        # Add condition variable for proper thread synchronization
        self._session_condition = threading.Condition(self._session_lock)
        self._metrics = ProcessMetrics()
        self._initialized = True
        self._test_session: BashSessionDouble | None = None
        # Instance-level mutex and shutdown flag (added to parent class)
        # Third-party imports
        from PySide6.QtCore import QMutex

        self._mutex = QMutex()
        self._shutdown_requested = False

    def set_test_session(self, session: BashSessionDouble) -> None:
        """Inject test session for testing."""
        self._test_session = session

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        timeout: int | None = None,
    ) -> str:
        """Override to use test session when available."""
        if self._test_session:
            # Use test session instead of secure executor
            # Standard library imports
            import time

            # Check cache first (same as parent)
            cached = self._cache.get(command)
            if cached is not None:
                self._metrics.cache_hits += 1
                return cached

            self._metrics.cache_misses += 1
            self._metrics.subprocess_calls += 1

            # Execute with test session
            start_time = time.time()
            try:
                result = self._test_session.execute(command, timeout)

                # Cache result
                self._cache.set(command, result, ttl=cache_ttl)

                # Update metrics
                elapsed = (time.time() - start_time) * 1000
                self._metrics.update_response_time(elapsed)

                # Emit completion signal
                self.command_completed.emit(command, result)

                return result

            except Exception as e:
                self.command_failed.emit(command, str(e))
                raise
        else:
            # Use parent implementation with secure executor
            return super().execute_workspace_command(command, cache_ttl, timeout)

    def _execute_with_session_pool(
        self,
        command: str,
        cache_ttl: int,
        session_type: str,
    ) -> str:
        """Override to use test session for batch execution."""
        if self._test_session:
            # Use test session instead of secure executor for batch commands
            # Standard library imports
            import time

            start_time = time.time()
            result = self._test_session.execute(command, timeout=30)

            # Update metrics
            elapsed = (time.time() - start_time) * 1000
            self._metrics.update_response_time(elapsed)
            self._metrics.subprocess_calls += 1

            return result
        # Use parent implementation
        return super()._execute_with_session_pool(command, cache_ttl, session_type)

    def _get_bash_session(self, session_type: str):
        """Override to return injected test session when available."""
        if self._test_session:
            return self._test_session
        return super()._get_bash_session(session_type)


# =============================================================================
# BEHAVIOR-FOCUSED TEST CLASSES
# =============================================================================


class TestCommandCacheBehavior:
    """Test CommandCache behavior through state changes."""

    def test_cache_stores_and_retrieves_values(self) -> None:
        """Test that cache correctly stores and retrieves values.

        CORRECT: Testing actual behavior, not implementation.
        """
        cache = CommandCache(default_ttl=10)

        # Store value
        cache.set("echo test", "test output", ttl=5)

        # Test BEHAVIOR: Value can be retrieved
        result = cache.get("echo test")
        assert result == "test output"

        # Test BEHAVIOR: Non-existent key returns None
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_respects_ttl(self) -> None:
        """Test that cache respects TTL expiration.

        CORRECT: Testing time-based behavior, not mocking time.
        """
        cache = CommandCache(default_ttl=0.1)  # 100ms TTL

        # Store value with short TTL
        cache.set("temp_key", "temp_value", ttl=0.1)

        # Test BEHAVIOR: Value available immediately
        assert cache.get("temp_key") == "temp_value"

        # Wait for expiration
        time.sleep(0.15)

        # Test BEHAVIOR: Value expired
        assert cache.get("temp_key") is None

    def test_cache_tracks_statistics(self) -> None:
        """Test that cache tracks hit/miss statistics.

        CORRECT: Testing observable behavior through stats.
        """
        cache = CommandCache()

        # Set up cache state
        cache.set("existing", "value")

        # Generate hits and misses
        cache.get("existing")  # Hit
        cache.get("existing")  # Hit
        cache.get("missing")  # Miss
        cache.get("missing2")  # Miss
        cache.get("missing3")  # Miss

        # Test BEHAVIOR: Statistics are tracked correctly
        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 3
        assert stats["hit_rate"] == 40.0  # 40%

    def test_cache_invalidation_by_pattern(self) -> None:
        """Test selective cache invalidation.

        CORRECT: Testing outcome of invalidation, not method calls.
        """
        cache = CommandCache()

        # Set up cache with commands that will be stored in value[3]
        # The cache stores (result, timestamp, ttl, command) tuples
        # and invalidate() checks if pattern is in the command
        cache.set("test_cmd1", "output1")  # command="test_cmd1"
        cache.set("test_cmd2", "output2")  # command="test_cmd2"
        cache.set("other_cmd", "output3")  # command="other_cmd"
        cache.set("another_test", "output4")  # command="another_test"

        # Invalidate by pattern - checks if pattern is IN the command string
        cache.invalidate(pattern="test_")

        # Test BEHAVIOR: Entries with "test_" in command are invalidated
        assert cache.get("test_cmd1") is None  # Has "test_" in command
        assert cache.get("test_cmd2") is None  # Has "test_" in command
        assert cache.get("other_cmd") == "output3"  # Doesn't have "test_"
        assert cache.get("another_test") == "output4"  # Has "test" but not "test_"


class TestProcessMetricsBehavior:
    """Test ProcessMetrics behavior and calculations."""

    def test_metrics_track_operations(self) -> None:
        """Test that metrics track operations correctly.

        CORRECT: Testing state changes, not internal counters.
        """
        metrics = ProcessMetrics()

        # Perform operations that should be tracked
        metrics.subprocess_calls += 1
        metrics.subprocess_calls += 1
        metrics.cache_hits += 3
        metrics.python_operations += 5

        # Record response times
        metrics.update_response_time(100)
        metrics.update_response_time(200)
        metrics.update_response_time(150)

        # Test BEHAVIOR: Metrics reflect operations
        report = metrics.get_report()
        assert report["subprocess_calls"] == 2
        assert report["python_operations"] == 5
        assert report["average_response_ms"] == 150  # (100+200+150)/3

    def test_metrics_reset_functionality(self) -> None:
        """Test that metrics can be reinitialized.

        CORRECT: Testing observable state after creating new instance.
        """
        # Generate some metrics in first instance
        metrics = ProcessMetrics()
        metrics.subprocess_calls = 10
        metrics.cache_hits = 20
        metrics.update_response_time(500)

        # Create fresh instance (since ProcessMetrics has no reset method)
        metrics = ProcessMetrics()

        # Test BEHAVIOR: New instance starts with clean state
        assert metrics.subprocess_calls == 0
        assert metrics.cache_hits == 0
        assert metrics.response_count == 0


class TestProcessPoolManagerBehavior:
    """Test ProcessPoolManager behavior with injected dependencies."""

    def test_singleton_ensures_single_instance(self) -> None:
        """Test that singleton pattern creates only one instance.

        CORRECT: Testing behavior (single instance), not implementation.
        """
        # Reset singleton for test isolation
        ProcessPoolManager._instance = None

        # Create multiple "instances"
        manager1 = ProcessPoolManager(max_workers=2)
        manager2 = ProcessPoolManager(max_workers=4)
        manager3 = ProcessPoolManager()

        # Test BEHAVIOR: All references point to same instance
        assert manager1 is manager2
        assert manager2 is manager3

        # Cleanup
        manager1.shutdown()
        ProcessPoolManager._instance = None

    def test_command_execution_with_caching(self, qapp) -> None:
        """Test that commands are cached and reused.

        CORRECT: Using test double at system boundary, testing behavior.
        """
        # Reset singleton
        ProcessPoolManager._instance = None

        # Create manager with injected session
        manager = InjectableProcessPoolManager()
        session = BashSessionDouble()
        # Don't set custom response - use default echo logic that returns "hello" for "echo hello"
        manager.set_test_session(session)

        # First execution - should call session
        result1 = manager.execute_workspace_command("echo hello", cache_ttl=10)
        # The BashSessionDouble returns "hello" for "echo hello" commands (default logic)
        assert result1 == "hello"
        assert len(session.executed_commands) == 1

        # Second execution - should use cache
        result2 = manager.execute_workspace_command("echo hello", cache_ttl=10)
        assert result2 == "hello"
        assert len(session.executed_commands) == 1  # Still 1, used cache

        # Test BEHAVIOR: Cache statistics reflect usage
        metrics = manager.get_metrics()
        assert metrics["cache_hits"] == 1
        assert metrics["cache_misses"] == 1

        # Cleanup InjectableProcessPoolManager (it bypasses singleton)
        manager.shutdown()

    def test_batch_command_execution(self) -> None:
        """Test batch execution of multiple commands.

        Following UNIFIED_TESTING_GUIDE: Test behavior (all commands executed),
        not implementation (execution order). batch_execute uses parallel execution
        via concurrent.futures.as_completed(), so order is not guaranteed.
        """
        # Reset singleton
        ProcessPoolManager._instance = None

        manager = InjectableProcessPoolManager()
        session = BashSessionDouble()

        # Configure realistic responses
        session.set_response("ls /tmp", "file1\nfile2")
        session.set_response("pwd", "/home/user")
        session.set_response("echo done", "done")

        manager.set_test_session(session)

        # Execute batch
        commands = ["ls /tmp", "pwd", "echo done"]
        results = manager.batch_execute(commands)

        # Test BEHAVIOR: All commands executed and results returned
        assert len(results) == 3
        assert results["ls /tmp"] == "file1\nfile2"
        assert results["pwd"] == "/home/user"
        assert results["echo done"] == "done"

        # Test BEHAVIOR: All commands were executed (order not guaranteed in parallel)
        assert set(session.executed_commands) == set(commands), (
            f"Expected all commands to be executed. "
            f"Executed: {session.executed_commands}, Expected: {commands}"
        )
        assert len(session.executed_commands) == len(commands), (
            "Should execute each command exactly once"
        )

        # Cleanup InjectableProcessPoolManager (it bypasses singleton)
        manager.shutdown()

    def test_error_recovery_during_execution(self) -> None:
        """Test that manager recovers from execution errors.

        CORRECT: Testing error recovery behavior, not error detection.
        """
        ProcessPoolManager._instance = None

        manager = InjectableProcessPoolManager()
        session = BashSessionDouble()

        # Configure session to fail initially
        session.should_fail = True
        session.failure_message = "Connection lost"

        manager.set_test_session(session)

        # First execution should handle error gracefully
        with pytest.raises(Exception, match="Connection lost"):
            manager.execute_workspace_command("echo test")

        # Reset session to working state
        session.should_fail = False
        session.reset()

        # Test BEHAVIOR: Manager recovers and works after error
        result = manager.execute_workspace_command("echo recovered")
        assert result == "recovered"

        # Cleanup InjectableProcessPoolManager (it bypasses singleton)
        manager.shutdown()

    def test_concurrent_access_thread_safety(self, qapp) -> None:
        """Test thread-safe singleton access following Qt threading rules.

        CORRECT: Tests singleton pattern without violating Qt thread affinity.
        Qt Rule: QObjects can only be accessed from the thread they belong to.

        This test validates that:
        1. Multiple threads can safely get the same singleton instance
        2. The singleton pattern works under concurrent access
        3. No Qt threading violations occur
        """
        # Standard library imports
        import queue
        from concurrent.futures import ThreadPoolExecutor

        # Reset singleton to ensure clean state
        ProcessPoolManager._instance = None

        # Create main thread instance
        main_manager = ProcessPoolManager()

        # Queue to collect singleton instances from threads
        instance_queue = queue.Queue()

        def get_singleton_instance(thread_id) -> None:
            """Get singleton instance from thread (safe operation)."""
            # Getting the singleton instance is thread-safe (doesn't access QObject methods)
            instance = ProcessPoolManager()
            instance_queue.put((thread_id, id(instance)))

        # Test with multiple threads getting singleton instances
        num_threads = 10
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(get_singleton_instance, i) for i in range(num_threads)
            ]

            # Wait for all threads to complete
            for future in futures:
                future.result(timeout=5.0)

        # Collect all instance IDs
        instance_ids = []
        while not instance_queue.empty():
            _thread_id, instance_id = instance_queue.get()
            instance_ids.append(instance_id)

        # Verify all threads got the same singleton instance
        assert len(instance_ids) == num_threads
        assert all(inst_id == instance_ids[0] for inst_id in instance_ids), (
            "Not all threads got the same singleton instance"
        )

        # Verify it's the same as main thread instance
        assert id(main_manager) == instance_ids[0], (
            "Thread instances don't match main thread instance"
        )

        # Cleanup
        main_manager.shutdown()
        ProcessPoolManager._instance = None


class TestPythonFileOperations:
    """Test Python-based file operations without subprocess."""

    def test_find_files_in_directory(self, tmp_path) -> None:
        """Test file finding using Python glob.

        CORRECT: Using real filesystem with temp directory.
        """
        ProcessPoolManager._instance = None
        manager = ProcessPoolManager()

        # Create test directory structure
        test_dir = tmp_path / "test_files"
        test_dir.mkdir()

        # Create test files
        (test_dir / "doc1.txt").touch()
        (test_dir / "doc2.txt").touch()
        (test_dir / "image.png").touch()
        (test_dir / "data.json").touch()

        # Create subdirectory with more files
        sub_dir = test_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "nested.txt").touch()

        # Test BEHAVIOR: Finds correct files by pattern (rglob is recursive)
        txt_files = manager.find_files_python(str(test_dir), "*.txt")
        assert len(txt_files) == 3  # doc1.txt, doc2.txt, and nested.txt in subdir
        assert all("txt" in f for f in txt_files)

        # Test BEHAVIOR: Different patterns work
        json_files = manager.find_files_python(str(test_dir), "*.json")
        assert len(json_files) == 1
        assert "data.json" in json_files[0]

        # Test BEHAVIOR: Returns empty list for no matches
        pdf_files = manager.find_files_python(str(test_dir), "*.pdf")
        assert pdf_files == []

        # Cleanup
        manager.shutdown()
        ProcessPoolManager._instance = None

    def test_nonexistent_directory_handling(self) -> None:
        """Test behavior with nonexistent directories.

        CORRECT: Testing actual error handling behavior.
        """
        ProcessPoolManager._instance = None
        manager = ProcessPoolManager()

        # Test BEHAVIOR: Returns empty list for nonexistent path
        results = manager.find_files_python("/this/does/not/exist", "*.txt")
        assert results == []

        # Test BEHAVIOR: Manager remains functional after error
        # (Can still perform other operations)
        # Standard library imports
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "test.txt").touch()
            results = manager.find_files_python(temp_dir, "*.txt")
            assert len(results) == 1

        # Cleanup
        manager.shutdown()
        ProcessPoolManager._instance = None


class TestCacheInvalidation:
    """Test cache invalidation strategies."""

    def test_selective_cache_invalidation(self) -> None:
        """Test that cache can be selectively invalidated.

        CORRECT: Testing behavior through observable state changes.
        """
        ProcessPoolManager._instance = None

        manager = InjectableProcessPoolManager()
        session = BashSessionDouble()
        manager.set_test_session(session)

        # Populate cache with various commands
        session.set_response("ls /tmp", "tmp files")
        session.set_response("ls /home", "home files")
        session.set_response("pwd", "/current/dir")

        # Execute commands to populate cache
        manager.execute_workspace_command("ls /tmp", cache_ttl=60)
        manager.execute_workspace_command("ls /home", cache_ttl=60)
        manager.execute_workspace_command("pwd", cache_ttl=60)

        # Reset session to track new executions
        initial_count = len(session.executed_commands)

        # Invalidate ls commands
        manager.invalidate_cache(pattern="ls ")

        # Test BEHAVIOR: ls commands need re-execution
        manager.execute_workspace_command("ls /tmp", cache_ttl=60)
        manager.execute_workspace_command("ls /home", cache_ttl=60)

        # These should have been re-executed
        assert len(session.executed_commands) > initial_count

        # Test BEHAVIOR: pwd still cached
        initial_count = len(session.executed_commands)
        manager.execute_workspace_command("pwd", cache_ttl=60)
        assert len(session.executed_commands) == initial_count  # Not re-executed

        # Cleanup InjectableProcessPoolManager (it bypasses singleton)
        manager.shutdown()


# =============================================================================
# KEY IMPROVEMENTS DEMONSTRATED
# =============================================================================

"""
This refactored version demonstrates:

1. NO Mock() objects - uses BashSessionDouble with realistic behavior
2. Dependency injection through InjectableProcessPoolManager
3. Tests actual behavior:
   - Cache hit/miss rates
   - TTL expiration
   - Thread safety
   - Error recovery
4. Real filesystem operations with tmp_path
5. Verifies outcomes, not method calls
6. Tests state changes, not implementation

The tests are now:
- More reliable (test actual behavior)
- Less fragile (don't break on refactoring)
- More valuable (catch real bugs)
- Easier to understand (clear intent)
"""
