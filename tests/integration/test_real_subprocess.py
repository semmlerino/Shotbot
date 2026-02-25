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


# ==============================================================================
# LAUNCHER REAL SUBPROCESS TESTS
# ==============================================================================
# These tests verify the launcher system works with real subprocess execution.
# They test the integration between CommandLauncher and the subprocess system.


@pytest.mark.real_subprocess
class TestLauncherRealSubprocess:
    """Real subprocess tests for the launcher system.

    These tests verify that the launcher can execute real commands and
    handle both success and error scenarios correctly.
    """

    def test_launcher_executes_simple_command(self) -> None:
        """Verify launcher infrastructure can call real subprocess."""
        # Test basic subprocess execution that the launcher would use
        result = subprocess.run(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert result.stdout.strip()  # Should have output (current directory)

    def test_launcher_handles_missing_command(self) -> None:
        """Verify subprocess reports command not found correctly."""
        with pytest.raises(FileNotFoundError):
            subprocess.run(
                ["nonexistent_command_xyz123"],
                check=False,
                capture_output=True,
                timeout=5,
            )


# ==============================================================================
# LAUNCHER STACK SMOKE TESTS
# ==============================================================================
# These tests verify the actual launcher stack (not bare subprocess) with real execution.
# They test ProcessPoolManager.execute_workspace_command, bash -ilc quoting, and RezMode.


@pytest.mark.real_subprocess
class TestLauncherStackSmoke:
    """Smoke tests for the actual launcher stack with real subprocess execution.

    These tests verify the complete launch pipeline including:
    - ProcessPoolManager.execute_workspace_command()
    - bash -ilc quoting behavior
    - RezMode handling

    Uses safe commands (echo, env checks) instead of actual app launches.
    """

    def test_process_pool_execute_workspace_command(self) -> None:
        """ProcessPoolManager.execute_workspace_command works with real bash."""
        import threading

        from process_pool_manager import ProcessPoolManager

        result_container: dict = {"output": None, "error": None}

        # Reset and initialize on main thread to ensure QObject lives in main thread
        ProcessPoolManager.reset()
        # Initialize singleton on main thread
        pool = ProcessPoolManager.get_instance()

        def run_command() -> None:
            # Worker thread only executes the command
            try:
                # We can access pool here because it's already initialized
                # and get_instance() is thread-safe(ish) or we use the captured variable
                result_container["output"] = pool.execute_workspace_command(
                    'echo "LAUNCHER_STACK_OK"',
                    cache_ttl=0,  # No caching for test
                    timeout=10,
                )
            except Exception as e:
                result_container["error"] = str(e)

        # Run in thread because ProcessPoolManager checks for main thread
        thread = threading.Thread(target=run_command)
        thread.start()
        thread.join(timeout=15)

        # Cleanup on main thread
        try:
            pool.shutdown(timeout=2.0)
        finally:
            ProcessPoolManager.reset()

        assert result_container["error"] is None, f"Error: {result_container['error']}"
        assert result_container["output"] is not None
        assert "LAUNCHER_STACK_OK" in result_container["output"]

    def test_bash_ilc_quoting_preserved(self) -> None:
        """Verify bash -ilc properly handles special characters."""
        # Test path with spaces - common in VFX environments
        # Use double quotes for easier escaping in Python
        result = subprocess.run(
            ["/bin/bash", "-ilc", 'echo "path with spaces/and_special-chars"'],
            capture_output=True,
            text=True,
            timeout=5, check=False,
        )
        assert result.returncode == 0
        assert "path with spaces" in result.stdout

    def test_bash_interactive_login_shell_works(self) -> None:
        """Verify bash -ilc (interactive login) mode initializes correctly."""
        # This tests the shell mode used by ProcessPoolManager and ProcessExecutor
        result = subprocess.run(
            ["/bin/bash", "-ilc", "echo shell_init_ok"],
            capture_output=True,
            text=True,
            timeout=10, check=False,  # Login shell may take longer to initialize
        )
        assert result.returncode == 0
        assert "shell_init_ok" in result.stdout

    def test_rez_mode_auto_detects_rez_used(self, monkeypatch) -> None:
        """RezMode.AUTO skips rez wrapping when REZ_USED is set."""
        from config import Config, RezMode
        from launch.environment_manager import EnvironmentManager

        # Simulate BlueBolt environment where rez is already initialized
        monkeypatch.setenv("REZ_USED", "1")

        env_manager = EnvironmentManager()

        # AUTO mode should skip wrapping when REZ_USED is set
        if Config.REZ_MODE == RezMode.AUTO:
            should_wrap = env_manager.should_wrap_with_rez(Config)
            # When REZ_USED is set, AUTO mode should NOT wrap
            assert not should_wrap, "RezMode.AUTO should skip wrapping when REZ_USED=1"

    def test_command_builder_validates_paths(self) -> None:
        """CommandBuilder.validate_path handles various path formats."""
        from launch.command_builder import CommandBuilder

        # Safe path - no escaping needed
        safe_path = CommandBuilder.validate_path("/shows/myshow/shots/sq010/sh0010")
        assert safe_path == "/shows/myshow/shots/sq010/sh0010"

        # Path with spaces - should be quoted
        space_path = CommandBuilder.validate_path("/shows/my show/shots/sq010/sh0010")
        # Verify it doesn't crash and returns something valid
        assert space_path is not None

    def test_env_manager_rez_packages(self) -> None:
        """EnvironmentManager returns rez packages for apps."""
        from config import Config
        from launch.environment_manager import EnvironmentManager

        env_manager = EnvironmentManager()

        # Get packages for known apps
        nuke_packages = env_manager.get_rez_packages("nuke", Config)
        maya_packages = env_manager.get_rez_packages("maya", Config)
        threede_packages = env_manager.get_rez_packages("3dequalizer", Config)

        # At minimum, should return a list (may be empty depending on config)
        assert isinstance(nuke_packages, list)
        assert isinstance(maya_packages, list)
        assert isinstance(threede_packages, list)


