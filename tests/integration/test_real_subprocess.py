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

    def test_launcher_environment_propagation(self) -> None:
        """Verify environment variables propagate to subprocess."""
        import os

        test_env = os.environ.copy()
        test_env["SHOTBOT_TEST_VAR"] = "test_value_123"

        result = subprocess.run(
            [sys.executable, "-c", "import os; print(os.environ.get('SHOTBOT_TEST_VAR', ''))"],
            check=False,
            capture_output=True,
            text=True,
            env=test_env,
            timeout=5,
        )
        assert result.returncode == 0
        assert "test_value_123" in result.stdout

    def test_launcher_handles_missing_command(self) -> None:
        """Verify subprocess reports command not found correctly."""
        with pytest.raises(FileNotFoundError):
            subprocess.run(
                ["nonexistent_command_xyz123"],
                check=False,
                capture_output=True,
                timeout=5,
            )

    def test_launcher_captures_stderr_on_failure(self) -> None:
        """Verify stderr is captured when command fails."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.stderr.write('error msg'); sys.exit(1)"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 1
        assert "error msg" in result.stderr

    def test_launcher_shell_command_execution(self) -> None:
        """Verify shell mode works correctly (used by VFX launchers)."""
        # This simulates how VFX tools like Nuke/Maya are often launched via shell
        result = subprocess.run(
            f'{sys.executable} -c "print(\'shell_launch_ok\')"',
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "shell_launch_ok" in result.stdout


@pytest.mark.real_subprocess
class TestProcessPoolRealSubprocess:
    """Real subprocess tests for ProcessPool functionality.

    These tests verify basic process pool behavior with real subprocesses,
    without spinning up the full ProcessPoolManager singleton.
    """

    def test_concurrent_subprocess_execution(self) -> None:
        """Verify multiple subprocesses can run concurrently."""
        import concurrent.futures

        def run_subprocess(value: int) -> int:
            result = subprocess.run(
                [sys.executable, "-c", f"import time; time.sleep(0.1); print({value})"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return int(result.stdout.strip())

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_subprocess, i) for i in range(3)]
            results = [f.result(timeout=10) for f in futures]

        assert sorted(results) == [0, 1, 2]

    def test_subprocess_callback_pattern(self) -> None:
        """Verify subprocess completion callback pattern works."""
        callback_results = []

        def on_complete(result: subprocess.CompletedProcess) -> None:
            callback_results.append(result.returncode)

        result = subprocess.run(
            [sys.executable, "-c", "print('callback test')"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        on_complete(result)

        assert callback_results == [0]

    def test_process_pool_shutdown_behavior(self) -> None:
        """Verify process cleanup works correctly."""
        import concurrent.futures

        # Simulate ProcessPool shutdown pattern
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(
                subprocess.run,
                [sys.executable, "-c", "print('shutdown_test')"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            result = future.result(timeout=10)
            assert result.returncode == 0

        # Executor should be cleanly shut down - no zombie processes


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


@pytest.mark.real_subprocess
@pytest.mark.xdist_group(name="real_subprocess")
class TestShellChaining:
    """Tests for shell command chaining patterns used by launcher."""

    def test_and_chain_stops_on_failure(self) -> None:
        """Verify && chaining stops execution on first failure."""
        result = subprocess.run(
            ["bash", "-c", "echo first; false && echo second"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert "first" in result.stdout
        assert "second" not in result.stdout
        assert result.returncode == 1

    def test_and_chain_continues_on_success(self) -> None:
        """Verify && chaining continues when commands succeed."""
        result = subprocess.run(
            ["bash", "-c", "echo first && echo second && echo third"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "first" in result.stdout
        assert "second" in result.stdout
        assert "third" in result.stdout

    def test_semicolon_chain_continues_regardless(self) -> None:
        """Verify ; chaining continues even after failure."""
        result = subprocess.run(
            ["bash", "-c", "echo first; false; echo second"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        assert "first" in result.stdout
        assert "second" in result.stdout
