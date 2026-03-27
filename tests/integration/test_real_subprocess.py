"""Real subprocess integration tests.

These tests use @pytest.mark.real_subprocess to bypass the autouse subprocess mocks
and verify that actual subprocess execution works correctly.

Run these tests serially (not in parallel) to avoid contention:
    pytest tests/integration/test_real_subprocess.py -n 0 -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ==============================================================================
# LAUNCHER STACK SMOKE TESTS
# ==============================================================================
# These tests verify the actual launcher stack (not bare subprocess) with real execution.
# They test ProcessPoolManager.execute_workspace_command, bash -ilc quoting, and RezMode.


@pytest.mark.real_subprocess
@pytest.mark.xdist_group("real_subprocess")
@pytest.mark.smoke
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

        from workers.process_pool_manager import ProcessPoolManager

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
                    timeout=30,
                )
            except Exception as e:  # noqa: BLE001
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

    def test_rez_mode_auto_still_requires_explicit_rez(self, monkeypatch) -> None:
        """RezMode.AUTO still resolves explicit app packages inside base Rez shells."""
        from config import Config, RezMode
        from launch.environment_manager import EnvironmentManager

        monkeypatch.setenv("REZ_USED", "1")

        env_manager = EnvironmentManager()

        if Config.REZ_MODE == RezMode.AUTO:
            with patch("launch.environment_manager.shutil.which", return_value="/usr/bin/rez"):
                should_wrap = env_manager.should_wrap_with_rez(Config)
            assert should_wrap, "RezMode.AUTO should still resolve explicit app packages"

    def test_command_builder_validates_paths(self) -> None:
        """validate_path handles various path formats."""
        from launch.command_builder import validate_path

        # Safe path - no escaping needed
        safe_path = validate_path("/shows/myshow/shots/sq010/sh0010")
        assert safe_path == "/shows/myshow/shots/sq010/sh0010"

        # Path with spaces - should be quoted
        space_path = validate_path("/shows/my show/shots/sq010/sh0010")
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
        rv_packages = env_manager.get_rez_packages("rv", Config)

        # At minimum, should return a list (may be empty depending on config)
        assert isinstance(nuke_packages, list)
        assert isinstance(maya_packages, list)
        assert isinstance(threede_packages, list)
        assert isinstance(rv_packages, list)
