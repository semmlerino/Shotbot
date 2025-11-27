"""Real subprocess integration tests.

These tests use @pytest.mark.real_subprocess to bypass the autouse subprocess mocks
and verify that actual subprocess execution works correctly.

Run these tests serially (not in parallel) to avoid contention:
    pytest tests/integration/test_real_subprocess.py -n 0 -v
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.real_subprocess
class TestRealSubprocessExecution:
    """Tests that verify real subprocess execution works."""

    def test_echo_command(self) -> None:
        """Basic subprocess.run with echo command."""
        result = subprocess.run(
            ["echo", "hello world"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout

    def test_python_subprocess(self) -> None:
        """Subprocess can execute Python."""
        result = subprocess.run(
            [sys.executable, "-c", "print('subprocess works')"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "subprocess works" in result.stdout

    def test_subprocess_error_handling(self) -> None:
        """Subprocess returns error code for failed command."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.exit(42)"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 42

    def test_subprocess_stderr(self) -> None:
        """Subprocess captures stderr correctly."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.stderr.write('error output')"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "error output" in result.stderr

    def test_popen_basic(self) -> None:
        """Basic Popen usage without mocking."""
        process = subprocess.Popen(
            ["echo", "popen test"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, _stderr = process.communicate(timeout=5)
        assert process.returncode == 0
        assert "popen test" in stdout

    def test_subprocess_run_shell_mode(self) -> None:
        """Shell mode subprocess execution."""
        result = subprocess.run(
            "echo 'shell mode works'",
            check=False, shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "shell mode works" in result.stdout


@pytest.mark.real_subprocess
class TestSubprocessTimeout:
    """Tests for subprocess timeout behavior."""

    def test_subprocess_timeout_raises(self) -> None:
        """Subprocess timeout raises TimeoutExpired."""
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                check=False, capture_output=True,
                timeout=0.1,
            )

    def test_popen_timeout_communicates(self) -> None:
        """Popen communicate timeout works correctly."""
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=0.1)
        process.kill()
        process.wait()
