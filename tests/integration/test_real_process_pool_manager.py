"""Integration tests for real ProcessPoolManager implementation.

These tests use @pytest.mark.real_subprocess to bypass the autouse subprocess mocks
and verify that actual ProcessPoolManager behavior works correctly, including:
- Command execution with real subprocess
- Caching behavior
- Metrics collection
- Shutdown and cleanup

Run these tests serially (not in parallel) to avoid contention:
    pytest tests/integration/test_real_process_pool_manager.py -n 0 -v

These tests execute safe commands (echo, python -c) that don't modify the system.

Note: execute_workspace_command() rejects calls from the main Qt thread to prevent
UI freezes. Tests use a helper to run commands in background threads.
"""

from __future__ import annotations

import concurrent.futures
import sys
import time

import pytest

from process_pool_manager import ProcessPoolManager


def _run_in_background(
    ppm: ProcessPoolManager,
    command: str,
    cache_ttl: int = 0,
    timeout: int = 5,
    use_login_shell: bool = True,
) -> str:
    """Run execute_workspace_command in a background thread.

    ProcessPoolManager.execute_workspace_command rejects calls from the main Qt
    thread to prevent UI freezes. This helper runs the command in a background
    thread to satisfy that requirement.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            ppm.execute_workspace_command,
            command,
            cache_ttl=cache_ttl,
            timeout=timeout,
            use_login_shell=use_login_shell,
        )
        return future.result(timeout=timeout + 5)


# Module-level markers - all tests in this file use real subprocess and run serialized
pytestmark = [
    pytest.mark.real_subprocess,
    pytest.mark.integration,
    pytest.mark.xdist_group(name="real_subprocess"),  # Serialize for safety
]


@pytest.fixture
def real_ppm() -> ProcessPoolManager:
    """Get real ProcessPoolManager instance for testing.

    Note: The autouse mocks are bypassed due to @pytest.mark.real_subprocess.
    """
    # Reset any existing instance to get fresh state
    ProcessPoolManager.reset()
    return ProcessPoolManager.get_instance()


@pytest.fixture(autouse=True)
def cleanup_ppm() -> None:
    """Clean up ProcessPoolManager after each test."""
    yield
    # Ensure clean state for next test
    ProcessPoolManager.reset()


class TestRealProcessPoolManagerExecution:
    """Tests for real command execution."""

    def test_execute_echo_command(self, real_ppm: ProcessPoolManager) -> None:
        """Verify real echo command execution."""
        result = _run_in_background(real_ppm, "echo 'hello world'", cache_ttl=0)
        assert "hello world" in result

    def test_execute_python_command(self, real_ppm: ProcessPoolManager) -> None:
        """Verify real Python command execution."""
        result = _run_in_background(
            real_ppm, f"{sys.executable} -c 'print(42)'", cache_ttl=0
        )
        assert "42" in result

    def test_execute_multiline_output(self, real_ppm: ProcessPoolManager) -> None:
        """Verify commands with multiline output work correctly."""
        result = _run_in_background(
            real_ppm, "echo 'line1'; echo 'line2'; echo 'line3'", cache_ttl=0
        )
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    def test_execute_with_env_variable(self, real_ppm: ProcessPoolManager) -> None:
        """Verify environment variables work in commands."""
        result = _run_in_background(
            real_ppm, "TEST_VAR='test_value' && echo $TEST_VAR", cache_ttl=0
        )
        assert "test_value" in result


class TestRealProcessPoolManagerCaching:
    """Tests for command caching behavior."""

    def test_cache_hit_returns_cached_result(
        self, real_ppm: ProcessPoolManager
    ) -> None:
        """Verify caching returns same result on repeat calls."""
        command = f"echo 'cache_test_{time.time()}'"  # Unique command

        # First call - cache miss
        result1 = _run_in_background(real_ppm, command, cache_ttl=60)

        # Second call - should be cache hit
        result2 = _run_in_background(real_ppm, command, cache_ttl=60)

        assert result1 == result2

    def test_cache_metrics_increment(self, real_ppm: ProcessPoolManager) -> None:
        """Verify cache metrics are tracked correctly."""
        command = f"echo 'metrics_test_{time.time()}'"  # Unique command

        metrics_before = real_ppm.get_metrics()
        initial_hits = metrics_before["cache_hits"]
        initial_misses = metrics_before["cache_misses"]

        # First call - cache miss
        _run_in_background(real_ppm, command, cache_ttl=60)

        metrics_after_first = real_ppm.get_metrics()
        assert metrics_after_first["cache_misses"] == initial_misses + 1

        # Second call - cache hit
        _run_in_background(real_ppm, command, cache_ttl=60)

        metrics_after_second = real_ppm.get_metrics()
        assert metrics_after_second["cache_hits"] == initial_hits + 1

    def test_cache_invalidation(self, real_ppm: ProcessPoolManager) -> None:
        """Verify cache invalidation clears cached results."""
        command = f"echo 'invalidation_test_{time.time()}'"

        # First call - cache miss
        _run_in_background(real_ppm, command, cache_ttl=60)

        # Invalidate cache
        real_ppm.invalidate_cache()

        metrics_before = real_ppm.get_metrics()
        initial_misses = metrics_before["cache_misses"]

        # After invalidation, same command should be cache miss again
        _run_in_background(real_ppm, command, cache_ttl=60)

        metrics_after = real_ppm.get_metrics()
        assert metrics_after["cache_misses"] == initial_misses + 1


class TestRealProcessPoolManagerShutdown:
    """Tests for shutdown and cleanup."""

    def test_shutdown_completes_cleanly(self) -> None:
        """Verify shutdown releases resources without errors."""
        # Get fresh instance
        ProcessPoolManager.reset()
        ppm = ProcessPoolManager.get_instance()

        # Execute a command to ensure instance is fully initialized
        _run_in_background(ppm, "echo 'pre-shutdown'", cache_ttl=0)

        # Shutdown should complete without errors
        ppm.shutdown()

        # After shutdown, new commands should raise
        with pytest.raises(RuntimeError, match="shut down"):
            _run_in_background(ppm, "echo 'post-shutdown'", cache_ttl=0)

    def test_reset_allows_new_commands(self) -> None:
        """Verify reset() allows creating new instance."""
        # Get instance and shut it down
        ProcessPoolManager.reset()
        ppm1 = ProcessPoolManager.get_instance()
        ppm1.shutdown()

        # Reset and get new instance
        ProcessPoolManager.reset()
        ppm2 = ProcessPoolManager.get_instance()

        # New instance should work
        result = _run_in_background(ppm2, "echo 'after_reset'", cache_ttl=0)
        assert "after_reset" in result


class TestRealProcessPoolManagerMetrics:
    """Tests for metrics collection.

    Note: The public get_metrics() API returns PerformanceMetricsDict with
    cache-related metrics. Internal metrics like subprocess_calls are
    tracked but not directly exposed. Cache behavior is tested in
    TestRealProcessPoolManagerCaching.
    """

    def test_metrics_returns_valid_structure(
        self, real_ppm: ProcessPoolManager
    ) -> None:
        """Verify metrics returns expected structure."""
        metrics = real_ppm.get_metrics()

        # Verify expected keys exist in the public API
        assert "cache_hits" in metrics
        assert "cache_misses" in metrics
        assert "cache_hit_rate" in metrics

    def test_metrics_types_are_correct(
        self, real_ppm: ProcessPoolManager
    ) -> None:
        """Verify metrics have correct types."""
        # Execute a command to populate some metrics
        _run_in_background(real_ppm, "echo 'type_test'", cache_ttl=0)

        metrics = real_ppm.get_metrics()

        # Verify types
        assert isinstance(metrics["cache_hits"], int)
        assert isinstance(metrics["cache_misses"], int)
        assert isinstance(metrics["cache_hit_rate"], float)


class TestRealProcessPoolManagerSingleton:
    """Tests for singleton behavior."""

    def test_get_instance_returns_same_object(self) -> None:
        """Verify get_instance() returns singleton."""
        ProcessPoolManager.reset()

        ppm1 = ProcessPoolManager.get_instance()
        ppm2 = ProcessPoolManager.get_instance()

        assert ppm1 is ppm2

    def test_reset_creates_new_instance(self) -> None:
        """Verify reset() creates new singleton instance."""
        ProcessPoolManager.reset()
        ppm1 = ProcessPoolManager.get_instance()

        ProcessPoolManager.reset()
        ppm2 = ProcessPoolManager.get_instance()

        assert ppm1 is not ppm2


class TestRealProcessPoolManagerErrorHandling:
    """Tests for error handling in real execution."""

    def test_nonzero_exit_raises(self, real_ppm: ProcessPoolManager) -> None:
        """Verify non-zero exit codes raise exceptions."""
        import subprocess

        with pytest.raises(subprocess.CalledProcessError):
            _run_in_background(
                real_ppm, f"{sys.executable} -c 'import sys; sys.exit(1)'", cache_ttl=0
            )

    def test_timeout_raises(self, real_ppm: ProcessPoolManager) -> None:
        """Verify command timeout raises exception."""
        import subprocess

        with pytest.raises(subprocess.TimeoutExpired):
            _run_in_background(
                real_ppm,
                f"{sys.executable} -c 'import time; time.sleep(10)'",
                cache_ttl=0,
                timeout=1,  # Short timeout
            )


class TestRealProcessPoolManagerBatchExecution:
    """Tests for batch command execution.

    Note: batch_execute() returns a dict mapping commands to results,
    where None indicates failure/timeout.
    """

    def test_batch_execute_multiple_commands(
        self, real_ppm: ProcessPoolManager
    ) -> None:
        """Verify batch execution processes multiple commands."""
        commands = [
            "echo 'batch1'",
            "echo 'batch2'",
            "echo 'batch3'",
        ]

        # batch_execute can be called from main thread (uses internal thread pool)
        results = real_ppm.batch_execute(commands, cache_ttl=0, timeout=10)

        assert len(results) == 3
        assert all(cmd in results for cmd in commands)
        assert "batch1" in (results[commands[0]] or "")
        assert "batch2" in (results[commands[1]] or "")
        assert "batch3" in (results[commands[2]] or "")

    def test_batch_execute_partial_failure(
        self, real_ppm: ProcessPoolManager
    ) -> None:
        """Verify batch handles partial failures gracefully."""
        commands = [
            "echo 'good1'",
            f"{sys.executable} -c 'import sys; sys.exit(1)'",  # Fails
            "echo 'good2'",
        ]

        results = real_ppm.batch_execute(commands, cache_ttl=0, timeout=10)

        # First and last should succeed
        assert results[commands[0]] is not None
        assert "good1" in results[commands[0]]
        # Failed command returns None
        assert results[commands[1]] is None
        # Third should succeed
        assert results[commands[2]] is not None
        assert "good2" in results[commands[2]]

    def test_batch_execute_uses_cache(
        self, real_ppm: ProcessPoolManager
    ) -> None:
        """Verify batch execution uses cache for repeated commands."""
        commands = ["echo 'cached_batch'"]

        # First execution - cache miss
        results1 = real_ppm.batch_execute(commands, cache_ttl=60, timeout=10)
        assert "cached_batch" in (results1[commands[0]] or "")

        # Get metrics after first call
        metrics1 = real_ppm.get_metrics()
        misses_after_first = metrics1["cache_misses"]

        # Second execution - should hit cache
        results2 = real_ppm.batch_execute(commands, cache_ttl=60, timeout=10)
        assert "cached_batch" in (results2[commands[0]] or "")

        # Misses should not have increased (cache hit)
        metrics2 = real_ppm.get_metrics()
        assert metrics2["cache_hits"] > metrics1["cache_hits"]
        assert metrics2["cache_misses"] == misses_after_first
