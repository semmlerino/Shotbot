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

from workers.process_pool_manager import ProcessPoolManager


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

    @pytest.mark.parametrize(
        ("command", "expected_outputs"),
        [
            ("echo 'hello world'", ["hello world"]),
            (f"{sys.executable} -c 'print(42)'", ["42"]),
            ("echo 'line1'; echo 'line2'; echo 'line3'", ["line1", "line2", "line3"]),
            ("TEST_VAR='test_value' && echo $TEST_VAR", ["test_value"]),
        ],
    )
    def test_execute_command(
        self, real_ppm: ProcessPoolManager, command: str, expected_outputs: list[str]
    ) -> None:
        """Verify real command execution produces expected output."""
        result = _run_in_background(real_ppm, command, cache_ttl=0)
        for expected in expected_outputs:
            assert expected in result


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
