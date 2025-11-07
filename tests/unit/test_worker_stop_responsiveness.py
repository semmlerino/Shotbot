"""Tests for worker thread stop responsiveness and zombie thread prevention.

These tests are designed to catch issues where worker threads become unresponsive
to stop signals due to blocking operations, particularly during filesystem scanning.

The zombie thread issue (fixed in commit XXX) was caused by blocking subprocess.run()
calls that couldn't be interrupted. These tests verify that:
1. Workers can be stopped quickly (within reasonable timeout)
2. cancel_flag is checked during long operations
3. Blocking operations are properly interruptible
4. No zombie threads remain after stop
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

from filesystem_scanner import FileSystemScanner
from shot_model import Shot
from threede_scene_worker import ThreeDESceneWorker


if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.threading
@pytest.mark.regression
class TestWorkerStopResponsiveness:
    """Tests for worker thread stop responsiveness."""

    def test_worker_stops_quickly_during_scan(self, qtbot: pytest.fixture) -> None:
        """Test that worker can be stopped quickly during filesystem scan.

        This is a regression test for the zombie thread issue where workers
        would get stuck in blocking subprocess.run() calls for up to 5 seconds.

        CRITICAL: Worker should stop within 1 second, not 5+ seconds.
        """
        # Create a test shot
        test_shot = Shot(
            workspace_path="/shows/test_show/shots/TEST_001/TEST_001_0010",
            show="test_show",
            sequence="TEST_001",
            shot="0010",
        )

        # Create worker that would scan (but won't actually scan in this test)
        worker = ThreeDESceneWorker(
            shots=[test_shot],
            excluded_users=set(),
            scan_all_shots=True,  # This triggers the blocking filesystem scan
        )

        # Mock the filesystem scanner to simulate a long-running operation
        with patch(
            "threede_scene_finder_optimized.OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel"
        ) as mock_find:
            # Simulate a long-running scan that checks cancel_flag
            def long_scan(
                shots: list[Shot],
                excluded_users: set[str],
                progress_callback: Callable[[int, str], None] | None = None,
                cancel_flag: Callable[[], bool] | None = None,
            ) -> list:
                """Simulate long scan that checks cancel_flag."""
                # Simulate scanning for up to 10 seconds, checking cancel_flag
                for _i in range(100):  # 100 iterations = 10 seconds if not cancelled
                    if cancel_flag and cancel_flag():
                        return []  # Exit quickly on cancellation
                    time.sleep(0.1)  # 100ms per iteration
                return []

            mock_find.side_effect = long_scan

            # Start worker in background thread
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

            # Give worker time to start and begin scanning
            time.sleep(0.3)

            # Stop worker and measure response time
            stop_start_time = time.time()
            worker.stop()

            # Wait for thread to finish with timeout
            thread.join(timeout=2.0)  # 2 second timeout
            stop_duration = time.time() - stop_start_time

            # CRITICAL ASSERTION: Worker should stop within 1 second
            # The zombie thread issue caused 5+ second delays
            assert (
                stop_duration < 1.0
            ), f"Worker took {stop_duration:.2f}s to stop (should be <1s)"

            # Thread should be dead
            assert not thread.is_alive(), "Worker thread should have stopped"

    def test_cancel_flag_checked_during_subprocess(self) -> None:
        """Test that cancel_flag is checked during subprocess execution.

        This verifies the core fix: subprocess.Popen() with polling loop
        that checks cancel_flag every 100ms.
        """
        scanner = FileSystemScanner()

        # Track cancel flag checks
        cancel_check_count = 0
        cancel_after_checks = 5  # Cancel after 5 checks (~500ms)

        def cancel_flag() -> bool:
            nonlocal cancel_check_count
            cancel_check_count += 1
            return cancel_check_count >= cancel_after_checks

        # Mock subprocess.Popen to simulate long-running find command
        mock_process = Mock()
        mock_process.poll.return_value = (
            None  # Process still running (will be checked repeatedly)
        )
        mock_process.returncode = -9  # Killed by signal

        # Track how many times poll() was called
        poll_count = 0

        def mock_poll_side_effect() -> int | None:
            nonlocal poll_count
            poll_count += 1
            # After several polls, simulate process completion
            if poll_count >= 10:
                return 0  # Process finished
            return None  # Still running

        mock_process.poll.side_effect = mock_poll_side_effect
        mock_process.communicate.return_value = ("", "")

        with (
            patch("filesystem_scanner.subprocess.Popen", return_value=mock_process),
            patch("pathlib.Path.exists", return_value=True),
        ):
            # Call the method that was blocking before the fix
            start_time = time.time()
            result = scanner.find_all_3de_files_in_show_targeted(
                show_root="/shows",
                show="test_show",
                excluded_users=set(),
                cancel_flag=cancel_flag,
            )
            duration = time.time() - start_time

            # Verify cancel_flag was checked multiple times
            assert (
                cancel_check_count >= cancel_after_checks
            ), f"cancel_flag only checked {cancel_check_count} times"

            # Verify the operation stopped quickly (not waiting for full timeout)
            assert duration < 2.0, f"Operation took {duration:.2f}s (should be quick)"

            # When cancelled, should return empty list
            assert result == [], "Should return empty list when cancelled"

    def test_subprocess_killed_on_cancellation(self) -> None:
        """Test that subprocess is actually killed when cancel_flag returns True.

        This verifies the fix properly kills the subprocess instead of
        letting it continue running in the background.
        """
        scanner = FileSystemScanner()

        # Create mock process
        mock_process = Mock()
        mock_process.poll.return_value = None  # Process running
        mock_process.kill = Mock()
        mock_process.wait = Mock()

        # cancel_flag that returns True immediately
        def cancel_flag() -> bool:
            return True

        with (
            patch("filesystem_scanner.subprocess.Popen", return_value=mock_process),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = scanner.find_all_3de_files_in_show_targeted(
                show_root="/shows",
                show="test_show",
                excluded_users=set(),
                cancel_flag=cancel_flag,
            )

            # Verify process was killed
            mock_process.kill.assert_called_once()
            # Verify zombie cleanup happened
            mock_process.wait.assert_called_once()

            # Result should be empty on cancellation
            assert result == []

    def test_rapid_stop_start_cycles_no_zombies(self, qtbot: pytest.fixture) -> None:
        """Test that rapid stop/start cycles don't create zombie threads.

        This tests the scenario from the production log where refreshing
        within 2 seconds caused zombie threads.
        """
        test_shot = Shot(
            workspace_path="/shows/test_show/shots/TEST_001/TEST_001_0010",
            show="test_show",
            sequence="TEST_001",
            shot="0010",
        )

        # Mock the finder to return immediately
        with patch(
            "threede_scene_finder_optimized.OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel",
            return_value=[],
        ):
            active_threads_before = threading.active_count()

            # Simulate rapid stop/start cycles (like rapid refresh clicks)
            for cycle in range(3):
                worker = ThreeDESceneWorker(
                    shots=[test_shot],
                    excluded_users=set(),
                    scan_all_shots=True,
                )

                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()

                # Very brief delay before stopping
                time.sleep(0.1)

                # Stop immediately
                worker.stop()

                # Wait for thread to finish
                thread.join(timeout=1.0)

                # Thread should be dead
                assert not thread.is_alive(), f"Cycle {cycle}: Thread should be stopped"

            # Give threads time to fully clean up
            time.sleep(0.5)

            # Check that we didn't accumulate zombie threads
            active_threads_after = threading.active_count()
            thread_leak = active_threads_after - active_threads_before

            # Should not have more than 1-2 extra threads (some background Qt threads ok)
            assert (
                thread_leak <= 2
            ), f"Leaked {thread_leak} threads after rapid stop/start cycles"


@pytest.mark.threading
@pytest.mark.regression
class TestFileSystemScannerInterruptibility:
    """Tests for FileSystemScanner cancel_flag support."""

    def test_cancel_flag_parameter_exists(self) -> None:
        """Test that cancel_flag parameter was added to the right methods."""
        scanner = FileSystemScanner()

        # Verify the method signature includes cancel_flag
        import inspect

        sig = inspect.signature(scanner.find_all_3de_files_in_show_targeted)
        params = sig.parameters

        assert (
            "cancel_flag" in params
        ), "cancel_flag parameter missing from find_all_3de_files_in_show_targeted"

        # Verify it's optional
        assert (
            params["cancel_flag"].default is not inspect.Parameter.empty
        ), "cancel_flag should be optional (have default value)"

    def test_cancel_flag_none_works(self) -> None:
        """Test that passing cancel_flag=None works (backward compatibility)."""
        scanner = FileSystemScanner()

        # Mock subprocess to return immediately
        mock_process = Mock()
        mock_process.poll.return_value = 0  # Finished immediately
        mock_process.returncode = 0
        mock_process.communicate.return_value = ("", "")

        with (
            patch("filesystem_scanner.subprocess.Popen", return_value=mock_process),
            patch("pathlib.Path.exists", return_value=True),
        ):
            # Should not raise error when cancel_flag is None
            result = scanner.find_all_3de_files_in_show_targeted(
                show_root="/shows",
                show="test_show",
                excluded_users=set(),
                cancel_flag=None,  # Explicitly pass None
            )

            # Should complete normally
            assert isinstance(result, list)

    def test_timeout_still_enforced_without_cancel_flag(self) -> None:
        """Test that 300s timeout is still enforced when cancel_flag is None."""
        scanner = FileSystemScanner()

        # Mock a process that runs forever
        mock_process = Mock()

        call_count = 0

        def mock_poll() -> None:
            nonlocal call_count
            call_count += 1
            # Simulate long-running process
            # After enough calls to exceed timeout, return finished
            if call_count > 3100:  # More than 300s worth of 0.1s intervals
                return 0
            return None

        mock_process.poll.side_effect = mock_poll
        mock_process.kill = Mock()
        mock_process.wait = Mock()
        mock_process.returncode = -9

        with (
            patch("filesystem_scanner.subprocess.Popen", return_value=mock_process),
            patch("pathlib.Path.exists", return_value=True),
            patch("time.sleep"),  # Speed up test
        ):
            result = scanner.find_all_3de_files_in_show_targeted(
                show_root="/shows",
                show="test_show",
                excluded_users=set(),
                cancel_flag=None,  # No cancel flag
            )

            # Should timeout and kill process
            assert mock_process.kill.called, "Process should be killed on timeout"

            # Should return empty list (fallback was called)
            assert isinstance(result, list)


@pytest.mark.threading
@pytest.mark.regression
class TestThreadSafeWorkerStopMechanism:
    """Tests for ThreadSafeWorker base class stop mechanism."""

    def test_should_stop_checked_in_polling_loop(self) -> None:
        """Test that should_stop() is the mechanism checked in polling loop.

        This verifies the integration between ThreadSafeWorker.should_stop()
        and the cancel_flag passed to filesystem operations.
        """
        test_shot = Shot(
            workspace_path="/shows/test_show/shots/TEST_001/TEST_001_0010",
            show="test_show",
            sequence="TEST_001",
            shot="0010",
        )

        worker = ThreeDESceneWorker(
            shots=[test_shot],
            excluded_users=set(),
            scan_all_shots=True,
        )

        # Track if should_stop() is consulted
        original_should_stop = worker.should_stop
        should_stop_call_count = 0

        def tracked_should_stop() -> bool:
            nonlocal should_stop_call_count
            should_stop_call_count += 1
            return original_should_stop()

        worker.should_stop = tracked_should_stop  # type: ignore[method-assign]

        # Mock the finder to check cancel_flag
        def mock_find(
            shots: list[Shot],
            excluded_users: set[str],
            progress_callback: Callable[[int, str], None] | None = None,
            cancel_flag: Callable[[], bool] | None = None,
        ) -> list:
            # Call cancel_flag a few times (as polling loop would)
            if cancel_flag:
                for _ in range(5):
                    if cancel_flag():
                        return []
            return []

        with patch(
            "threede_scene_finder_optimized.OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel",
            side_effect=mock_find,
        ):
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

            time.sleep(0.1)
            worker.stop()
            thread.join(timeout=1.0)

            # should_stop() should have been called multiple times
            # (once to create cancel_flag, then multiple times during polling)
            assert (
                should_stop_call_count >= 5
            ), f"should_stop() only called {should_stop_call_count} times"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
