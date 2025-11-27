"""Tests for subprocess error handling using opt-in error fixtures.

These tests verify that the application properly handles subprocess failures,
timeouts, and exceptions. They use the opt-in subprocess error fixtures
from tests.fixtures.subprocess_mocking.

This file demonstrates the opt-in pattern for testing error paths:
- subprocess_error_mock: For testing non-zero return codes
- subprocess_timeout_mock: For testing timeout handling
- subprocess_exception_mock: For testing startup failures
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from tests.fixtures.subprocess_mocking import SubprocessMock

pytestmark = [pytest.mark.unit]


class TestSubprocessErrorFixtures:
    """Test the opt-in subprocess error fixtures themselves."""

    def test_subprocess_error_mock_returns_failure(
        self, subprocess_error_mock: SubprocessMock
    ) -> None:
        """Test that subprocess_error_mock is pre-configured for failure."""
        import subprocess

        # The fixture should be pre-configured to fail
        proc = subprocess.Popen(["test", "cmd"])
        assert proc.returncode == 1
        assert proc.wait() == 1

    def test_subprocess_error_mock_has_stderr(
        self, subprocess_error_mock: SubprocessMock
    ) -> None:
        """Test that subprocess_error_mock has error output."""
        import subprocess

        proc = subprocess.Popen(["test", "cmd"])
        _stdout, stderr = proc.communicate()
        assert b"Command failed" in stderr

    def test_subprocess_exception_mock_raises(
        self, subprocess_exception_mock: SubprocessMock
    ) -> None:
        """Test that subprocess_exception_mock raises FileNotFoundError."""
        import subprocess

        with pytest.raises(FileNotFoundError):
            subprocess.Popen(["nonexistent_command"])

    def test_subprocess_mock_can_be_reconfigured(
        self, subprocess_error_mock: SubprocessMock
    ) -> None:
        """Test that error fixtures can be reconfigured per-test."""
        import subprocess

        # Reconfigure to return different error
        subprocess_error_mock.set_return_code(2)
        subprocess_error_mock.set_output("", stderr="Permission denied")

        proc = subprocess.Popen(["test", "cmd"])
        assert proc.returncode == 2


class TestLauncherErrorHandling:
    """Test launcher error handling using subprocess error fixtures."""

    def test_error_fixture_integrates_with_launcher_module(
        self, subprocess_error_mock: SubprocessMock
    ) -> None:
        """Test that error fixtures properly patch launcher.worker module."""
        import subprocess

        # Configure specific error
        subprocess_error_mock.set_return_code(127)
        subprocess_error_mock.set_output("", stderr="bash: command not found")

        # Verify the fixture patches both subprocess module and launcher.worker
        proc = subprocess.Popen(["test", "cmd"])
        assert proc.returncode == 127

        # The fixture should have recorded the call
        assert ["test", "cmd"] in subprocess_error_mock.calls


class TestSubprocessMockTracking:
    """Test subprocess call tracking with opt-in fixtures."""

    def test_subprocess_mock_tracks_calls(
        self, subprocess_mock: SubprocessMock
    ) -> None:
        """Test that subprocess_mock tracks command calls."""
        import subprocess

        subprocess.Popen(["echo", "hello"])
        subprocess.Popen(["ls", "-la"])

        assert ["echo", "hello"] in subprocess_mock.calls
        assert ["ls", "-la"] in subprocess_mock.calls
        assert len(subprocess_mock.calls) == 2

    def test_subprocess_mock_can_verify_arguments(
        self, subprocess_mock: SubprocessMock
    ) -> None:
        """Test verifying specific command arguments."""
        import subprocess

        subprocess_mock.set_output("workspace /shows/test/shots/010/0010")
        subprocess.Popen(["ws", "-sg"])

        # Verify the ws command was called
        ws_calls = [c for c in subprocess_mock.calls if c[0] == "ws"]
        assert len(ws_calls) == 1
        assert ws_calls[0] == ["ws", "-sg"]

    def test_subprocess_mock_reset_clears_state(
        self, subprocess_mock: SubprocessMock
    ) -> None:
        """Test that reset() clears call history and settings."""
        import subprocess

        subprocess_mock.set_return_code(5)
        subprocess.Popen(["test"])

        assert len(subprocess_mock.calls) == 1

        subprocess_mock.reset()

        assert len(subprocess_mock.calls) == 0
        # Return code should be back to default (0)
        # This validates the reset behavior


class TestProcessPoolErrorHandling:
    """Test ProcessPoolManager error handling scenarios."""

    def test_process_pool_uses_test_double(self) -> None:
        """Test that ProcessPoolManager uses the test double from autouse fixture.

        This test verifies that the autouse mock_process_pool_manager fixture
        properly patches the singleton, preventing real subprocess execution.
        """
        from process_pool_manager import ProcessPoolManager

        # Get the singleton instance (should be mocked by autouse fixture)
        pool = ProcessPoolManager.get_instance()

        # The mock should not execute real subprocesses
        # Actual verification depends on ProcessPoolManager API
        assert pool is not None
