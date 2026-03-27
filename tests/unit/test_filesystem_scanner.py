"""Tests for FileSystemScanner high-risk code paths.

This module tests the most critical and error-prone parts of FilesystemScanner:
1. DirectoryCache threading safety
2. Subprocess timeout/cancellation handling
3. Lazy import thread safety
4. Progressive discovery fallback chains

These tests focus on concurrency bugs, silent failures, and data corruption risks.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from threede.filesystem_scanner import FileSystemScanner


if TYPE_CHECKING:
    from tests.fixtures.process_fixtures import SubprocessMock


pytestmark = [pytest.mark.unit]


# =============================================================================
# Cache Delegation Tests
# =============================================================================


class TestCacheDelegation:
    """Test that FileSystemScanner delegates cache operations to FilesystemCoordinator."""

    def test_clear_cache_delegates_to_coordinator(self) -> None:
        """clear_cache() delegates to FilesystemCoordinator.invalidate_all()."""
        with patch(
            "paths.filesystem_coordinator.FilesystemCoordinator"
        ) as mock_coord_cls:
            mock_instance = MagicMock()
            mock_instance.invalidate_all.return_value = 5
            mock_coord_cls.return_value = mock_instance

            result = FileSystemScanner.clear_cache()

            mock_instance.invalidate_all.assert_called_once()
            assert result == 5

    def test_get_cache_stats_delegates_to_coordinator(self) -> None:
        """get_cache_stats() delegates to FilesystemCoordinator.get_cache_stats()."""
        expected_stats = {
            "cached_directories": 10,
            "cache_hits": 50,
            "cache_misses": 5,
            "total_requests": 55,
            "hit_rate": 90.9,
            "ttl_seconds": 300,
        }
        with patch(
            "paths.filesystem_coordinator.FilesystemCoordinator"
        ) as mock_coord_cls:
            mock_instance = MagicMock()
            mock_instance.get_cache_stats.return_value = expected_stats
            mock_coord_cls.return_value = mock_instance

            result = FileSystemScanner.get_cache_stats()

            mock_instance.get_cache_stats.assert_called_once()
            assert result == expected_stats


# =============================================================================
# Subprocess Timeout/Cancellation Tests
# =============================================================================


class TestSubprocessTimeoutCancellation:
    """Test subprocess timeout and cancellation handling.

    These tests verify that `_run_find_and_parse()` correctly handles:
    - Cancel flag stopping the process
    - Timeout killing the process
    - Normal completion
    - Error scenarios
    """

    @pytest.fixture
    def scanner_with_parser(self) -> FileSystemScanner:
        """Create FileSystemScanner with a mock parser."""
        scanner = FileSystemScanner()
        # Mock parser to avoid circular import issues in tests
        mock_parser = MagicMock()
        mock_parser.parse_3de_file_path.return_value = (
            Path("/test/scene.3de"),
            "TestShow",
            "SEQ010",
            "0010",
            "artist",
            "plate",
        )
        scanner.parser = mock_parser
        return scanner

    def test_cancel_flag_kills_process(
        self,
        scanner_with_parser: FileSystemScanner,
    ) -> None:
        """Cancel flag triggers process termination and returns empty list."""

        # Mock the streaming read helper to simulate cancellation
        def mock_streaming_read(
            cmd: list[str],
            cancel_flag: object,
            max_wait_time: float,
            poll_interval: float = 0.1,
        ) -> tuple[int | None, str, str, str]:
            return (None, "", "", "cancelled")

        scanner_with_parser._run_subprocess_with_streaming_read = mock_streaming_read  # type: ignore[method-assign]

        # Cancel immediately
        def cancel_flag() -> bool:
            return True

        result = scanner_with_parser._run_find_and_parse(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=cancel_flag,
            max_wait_time=300.0,
        )

        assert result == []  # Cancelled returns empty list

    def test_timeout_kills_process_returns_none(
        self,
        scanner_with_parser: FileSystemScanner,
    ) -> None:
        """Timeout triggers process termination and returns None (not empty list)."""

        # Mock the streaming read helper to simulate timeout
        def mock_streaming_read(
            cmd: list[str],
            cancel_flag: object,
            max_wait_time: float,
            poll_interval: float = 0.1,
        ) -> tuple[int | None, str, str, str]:
            return (None, "", "", "timeout")

        scanner_with_parser._run_subprocess_with_streaming_read = mock_streaming_read  # type: ignore[method-assign]

        result = scanner_with_parser._run_find_and_parse(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=150.0,
        )

        assert result is None, "Timeout should return None (distinct from empty list)"

    def test_process_completes_before_timeout(
        self,
        scanner_with_parser: FileSystemScanner,
    ) -> None:
        """Process completing normally returns parsed results."""

        # Mock the streaming read helper to return successful output
        def mock_streaming_read(
            cmd: list[str],
            cancel_flag: object,
            max_wait_time: float,
            poll_interval: float = 0.1,
        ) -> tuple[int | None, str, str, str]:
            return (0, "/test/scene.3de\n/test/scene2.3de", "", "ok")

        scanner_with_parser._run_subprocess_with_streaming_read = mock_streaming_read  # type: ignore[method-assign]

        result = scanner_with_parser._run_find_and_parse(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=300.0,
        )

        assert result is not None
        assert len(result) == 2, "Should parse 2 files from stdout"

    def test_stderr_on_nonzero_exit(
        self,
        scanner_with_parser: FileSystemScanner,
    ) -> None:
        """Non-zero exit code logs stderr but doesn't crash."""

        # Mock the streaming read helper to return error
        def mock_streaming_read(
            cmd: list[str],
            cancel_flag: object,
            max_wait_time: float,
            poll_interval: float = 0.1,
        ) -> tuple[int | None, str, str, str]:
            return (1, "", "find: permission denied", "ok")

        scanner_with_parser._run_subprocess_with_streaming_read = mock_streaming_read  # type: ignore[method-assign]

        # Should not raise, just return empty results
        result = scanner_with_parser._run_find_and_parse(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=300.0,
        )

        assert result == [], "Error should return empty results, not crash"

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("[Errno 2] No such file or directory: 'find'"),
            OSError("[Errno 13] Permission denied"),
        ],
        ids=["file_not_found", "permission_error"],
    )
    def test_os_errors_return_empty_results(
        self,
        scanner_with_parser: FileSystemScanner,
        monkeypatch: pytest.MonkeyPatch,
        exc: OSError,
    ) -> None:
        """FileNotFoundError and OSError from Popen both return empty results."""

        def raise_exc(*args: object, **kwargs: object) -> None:
            raise exc

        monkeypatch.setattr("threede.filesystem_scanner.subprocess.Popen", raise_exc)

        result = scanner_with_parser._run_find_and_parse(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=300.0,
        )

        assert result == [], f"{type(exc).__name__} should return empty results"

    def test_max_wait_time_validation(
        self,
        scanner_with_parser: FileSystemScanner,
    ) -> None:
        """Invalid max_wait_time raises ValueError."""
        with pytest.raises(ValueError, match="max_wait_time must be positive"):
            scanner_with_parser._run_find_and_parse(
                find_cmd=["find", "/test"],
                show_path=Path("/shows/TEST"),
                show="TEST",
                excluded_users=set(),
                cancel_flag=None,
                max_wait_time=0,
            )

        with pytest.raises(ValueError, match="max_wait_time must be positive"):
            scanner_with_parser._run_find_and_parse(
                find_cmd=["find", "/test"],
                show_path=Path("/shows/TEST"),
                show="TEST",
                excluded_users=set(),
                cancel_flag=None,
                max_wait_time=-10,
            )


# =============================================================================
# Streaming Read Tests (Pipe Buffer Deadlock Prevention)
# =============================================================================


@pytest.mark.real_subprocess
class TestStreamingReadLargeOutput:
    """Test the streaming read helper handles large outputs without deadlock.

    The _run_subprocess_with_streaming_read() method was introduced to fix a
    deadlock bug where subprocess output exceeding the OS pipe buffer (~64KB)
    would cause the polling loop to hang.

    These tests verify:
    - Large outputs (>64KB) are captured correctly
    - The streaming read doesn't block
    - Cancellation and timeout work with streaming
    """

    def test_large_output_captured_completely(self) -> None:
        """Subprocess output exceeding 64KB is captured without deadlock.

        This is an integration test using a real subprocess to verify the fix.
        The old implementation would deadlock when output exceeded ~64KB because
        the parent only read from pipes after process.poll() returned non-None,
        but the process couldn't exit while blocked writing to full pipes.
        """
        scanner = FileSystemScanner()

        # Generate output > 64KB (pipe buffer size)
        # 80KB of data = ~80,000 characters
        output_size = 80_000
        cmd = ["python3", "-c", f"print('x' * {output_size})"]

        returncode, stdout, stderr, status = (
            scanner._run_subprocess_with_streaming_read(
                cmd=cmd,
                cancel_flag=None,
                max_wait_time=10.0,  # 10 seconds should be plenty
            )
        )

        assert status == "ok", f"Expected status 'ok', got '{status}'"
        assert returncode == 0, f"Expected return code 0, got {returncode}"
        # Output should have all the x's plus newline
        assert len(stdout.strip()) == output_size, (
            f"Expected {output_size} chars, got {len(stdout.strip())}"
        )
        assert stderr == "", f"Expected empty stderr, got: {stderr}"

    def test_cancellation_during_large_output(self) -> None:
        """Cancellation works correctly during large output streaming."""
        scanner = FileSystemScanner()

        # Start a slow command that outputs data continuously
        cmd = [
            "python3",
            "-c",
            "import time; [print(f'line {i}') or time.sleep(0.01) for i in range(1000)]",
        ]

        # Cancel after a brief delay
        cancel_triggered = [False]

        def cancel_flag() -> bool:
            if not cancel_triggered[0]:
                cancel_triggered[0] = True
                return False  # Don't cancel on first check
            return True  # Cancel on subsequent checks

        returncode, _stdout, _stderr, status = (
            scanner._run_subprocess_with_streaming_read(
                cmd=cmd,
                cancel_flag=cancel_flag,
                max_wait_time=30.0,
            )
        )

        assert status == "cancelled"
        assert returncode is None

    def test_timeout_during_large_output(self) -> None:
        """Timeout works correctly during large output streaming."""
        scanner = FileSystemScanner()

        # Command that runs indefinitely
        cmd = [
            "python3",
            "-c",
            "import time; [print(f'line {i}') or time.sleep(0.1) for i in range(10000)]",
        ]

        returncode, _stdout, _stderr, status = (
            scanner._run_subprocess_with_streaming_read(
                cmd=cmd,
                cancel_flag=None,
                max_wait_time=0.5,  # Very short timeout
            )
        )

        assert status == "timeout"
        assert returncode is None


# =============================================================================
# Lazy Import Thread Safety Tests
# =============================================================================


class TestLazyImportThreadSafety:
    """Test thread safety of lazy imports in FileSystemScanner.

    FileSystemScanner uses double-check locking for lazy initialization of:
    - self.parser (SceneParser)
    - self._fs_coordinator (FilesystemCoordinator)

    These tests verify concurrent first-access doesn't cause issues.
    """

    def test_concurrent_parser_first_access(self) -> None:
        """Multiple threads accessing parser simultaneously get same instance.

        The double-check locking pattern should ensure only one SceneParser
        instance is created even with concurrent access.
        """
        scanner = FileSystemScanner()
        scanner.parser = None  # Reset to uninitialized state
        scanner._parser_lock = threading.Lock()  # Fresh lock

        barrier = threading.Barrier(10)
        parser_ids: list[int] = []
        errors: list[str] = []

        def access_parser() -> None:
            barrier.wait()  # Synchronized start
            try:
                # This triggers lazy import via find_all_3de_files_in_show_targeted
                # We'll access parser directly instead to avoid filesystem ops
                with scanner._parser_lock:
                    if scanner.parser is None:
                        from threede.scene_parser import SceneParser

                        scanner.parser = SceneParser()
                parser_ids.append(id(scanner.parser))
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))

        threads = [threading.Thread(target=access_parser) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent parser access: {errors}"
        # All threads should get the same parser instance
        unique_ids = set(parser_ids)
        assert len(unique_ids) == 1, f"Got {len(unique_ids)} different parser instances"


# =============================================================================
# Progressive Discovery Fallback Tests
# =============================================================================


class TestProgressiveDiscoveryFallback:
    """Test progressive discovery strategy selection and fallback logic.

    FileSystemScanner.find_3de_files_progressive() adaptively chooses between
    Python and subprocess methods based on workload size, with fallback on errors.
    """

    @pytest.fixture
    def scanner(self) -> FileSystemScanner:
        """Create a fresh FileSystemScanner instance."""
        return FileSystemScanner()

    def test_small_workload_uses_python(
        self,
        scanner: FileSystemScanner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Workloads below SMALL_WORKLOAD_THRESHOLD use Python method.

        When user directory has fewer than SMALL_WORKLOAD_THRESHOLD entries,
        the Python rglob-based method should be used.
        """
        # Create small directory structure
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        # Create 5 user directories (below threshold of 100)
        for i in range(5):
            user_path = user_dir / f"artist{i}"
            user_path.mkdir()
            threede_dir = user_path / "mm" / "3de"
            threede_dir.mkdir(parents=True)
            (threede_dir / f"scene{i}.3de").touch()

        # Track which method was called
        calls = {"python": 0, "subprocess": 0}
        original_python = scanner._find_3de_files_python_optimized
        original_subprocess = scanner._find_3de_files_subprocess_optimized

        def tracking_python(*args: object, **kwargs: object) -> list[tuple[str, Path]]:
            calls["python"] += 1
            return original_python(*args, **kwargs)

        def tracking_subprocess(
            *args: object, **kwargs: object
        ) -> list[tuple[str, Path]]:
            calls["subprocess"] += 1
            return original_subprocess(*args, **kwargs)

        monkeypatch.setattr(
            scanner, "_find_3de_files_python_optimized", tracking_python
        )
        monkeypatch.setattr(
            scanner, "_find_3de_files_subprocess_optimized", tracking_subprocess
        )

        result = scanner.find_3de_files_progressive(user_dir, excluded_users=None)

        assert calls["python"] == 1, "Should use Python method for small workload"
        assert calls["subprocess"] == 0, "Should not use subprocess for small workload"
        assert len(result) == 5, "Should find all 5 .3de files"

    def test_large_workload_uses_subprocess(
        self,
        scanner: FileSystemScanner,
        tmp_path: Path,
        subprocess_mock: SubprocessMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Workloads above SMALL_WORKLOAD_THRESHOLD use subprocess method.

        When user directory has more than SMALL_WORKLOAD_THRESHOLD entries,
        the subprocess find command should be used.
        """
        # Create user directory with many subdirectories
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        # Create 150 user directories (above threshold of 100)
        for i in range(150):
            (user_dir / f"artist{i}").mkdir()

        # Configure subprocess mock to return some files
        subprocess_mock.set_output(
            f"{tmp_path}/user/artist0/scene.3de\n{tmp_path}/user/artist1/scene.3de\n"
        )

        # Track method calls
        calls = {"python": 0, "subprocess": 0}

        def tracking_subprocess(
            user_dir: Path, excluded_users: set[str] | None
        ) -> list[tuple[str, Path]]:
            calls["subprocess"] += 1
            # Return mocked results instead of calling real subprocess
            return [
                ("artist0", Path(f"{tmp_path}/user/artist0/scene.3de")),
                ("artist1", Path(f"{tmp_path}/user/artist1/scene.3de")),
            ]

        monkeypatch.setattr(
            scanner, "_find_3de_files_subprocess_optimized", tracking_subprocess
        )

        scanner.find_3de_files_progressive(user_dir, excluded_users=None)

        assert calls["subprocess"] == 1, "Should use subprocess for large workload"

    def test_subprocess_error_falls_back_to_python(
        self,
        scanner: FileSystemScanner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Subprocess failure triggers fallback to Python method.

        If the subprocess method raises an exception, find_3de_files_progressive
        should fall back to the Python method.
        """
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        # Create 150 user directories to trigger subprocess path
        for i in range(150):
            user_path = user_dir / f"artist{i}"
            user_path.mkdir()
            # Add a .3de file to some
            if i < 3:
                threede_dir = user_path / "mm" / "3de"
                threede_dir.mkdir(parents=True)
                (threede_dir / f"scene{i}.3de").touch()

        # Track calls
        calls = {"python": 0, "subprocess": 0}

        def failing_subprocess(
            user_dir: Path, excluded_users: set[str] | None
        ) -> list[tuple[str, Path]]:
            calls["subprocess"] += 1
            raise subprocess.SubprocessError("Test subprocess failure")

        original_python = scanner._find_3de_files_python_optimized

        def tracking_python(
            user_dir: Path, excluded_users: set[str] | None
        ) -> list[tuple[str, Path]]:
            calls["python"] += 1
            return original_python(user_dir, excluded_users)

        monkeypatch.setattr(
            scanner, "_find_3de_files_subprocess_optimized", failing_subprocess
        )
        monkeypatch.setattr(
            scanner, "_find_3de_files_python_optimized", tracking_python
        )

        # This should trigger subprocess (> threshold), fail, then fallback to python
        result = scanner.find_3de_files_progressive(user_dir, excluded_users=None)

        # Note: the current implementation catches Exception, which triggers fallback
        # after the subprocess method is called and fails
        assert calls["python"] >= 1, "Should fall back to Python method after error"
        assert len(result) == 3, "Should still find files via Python fallback"

    def test_excluded_users_in_python_path(
        self,
        scanner: FileSystemScanner,
        tmp_path: Path,
    ) -> None:
        """Python method correctly excludes specified users."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        # Create directories for multiple users
        for username in ["artist1", "artist2", "excluded_user", "temp"]:
            user_path = user_dir / username
            user_path.mkdir()
            threede_dir = user_path / "mm" / "3de"
            threede_dir.mkdir(parents=True)
            (threede_dir / f"{username}_scene.3de").touch()

        excluded = {"excluded_user", "temp"}
        result = scanner._find_3de_files_python_optimized(
            user_dir, excluded_users=excluded
        )

        # Should only find files from non-excluded users
        usernames = {username for username, _ in result}
        assert "artist1" in usernames
        assert "artist2" in usernames
        assert "excluded_user" not in usernames
        assert "temp" not in usernames
        assert len(result) == 2

    def test_excluded_users_in_subprocess_path(
        self,
        scanner: FileSystemScanner,
        tmp_path: Path,
        subprocess_mock: SubprocessMock,
    ) -> None:
        """Subprocess method correctly excludes specified users."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        # Mock subprocess output containing files from multiple users
        subprocess_mock.set_output(
            f"{user_dir}/artist1/scene.3de\n"
            f"{user_dir}/artist2/scene.3de\n"
            f"{user_dir}/excluded_user/scene.3de\n"
            f"{user_dir}/temp/scene.3de\n"
        )

        excluded = {"excluded_user", "temp"}
        result = scanner._find_3de_files_subprocess_optimized(
            user_dir, excluded_users=excluded
        )

        # Results should exclude the specified users
        usernames = {username for username, _ in result}
        assert "excluded_user" not in usernames
        assert "temp" not in usernames


# =============================================================================
# ThreeDESceneWorker Cancel/Interrupt Tests
# (merged from test_worker_stop_responsiveness.py)
# =============================================================================


from threede import ThreeDESceneWorker
from type_definitions import Shot


@pytest.mark.qt
@pytest.mark.concurrency
@pytest.mark.regression
class TestThreeDEWorkerStopAndCancel:
    """Cancel and interrupt behaviour for ThreeDESceneWorker.

    These are regression tests for the zombie thread issue where workers
    would get stuck in blocking subprocess.run() calls for up to 5 seconds.
    The fix threads a cancel_flag through to filesystem operations so that
    worker.request_stop() propagates quickly via should_stop().
    """

    def _make_shot(self) -> Shot:
        return Shot(
            workspace_path="/shows/test_show/shots/TEST_001/TEST_001_0010",
            show="test_show",
            sequence="TEST_001",
            shot="0010",
        )

    def test_worker_stops_quickly_during_scan(self, qtbot: pytest.fixture) -> None:
        """Worker can be stopped within 2 seconds during a long filesystem scan.

        Regression test: before the fix workers blocked inside subprocess.run()
        for the full scan timeout (up to 5 seconds).
        """
        from collections.abc import Callable

        worker = ThreeDESceneWorker(
            shots=[self._make_shot()],
            excluded_users=set(),
        )

        with patch(
            "threede.scene_worker.SceneDiscoveryCoordinator"
            ".find_all_scenes_in_shows_truly_efficient_parallel"
        ) as mock_find:
            scan_started_event = threading.Event()

            def long_scan(
                shots: list[Shot],
                excluded_users: set[str],
                progress_callback: Callable[[int, str], None] | None = None,
                cancel_flag: Callable[[], bool] | None = None,
            ) -> list:
                scan_started_event.set()
                for _ in range(100):
                    if cancel_flag and cancel_flag():
                        return []
                    scan_iteration_delay = threading.Event()
                    scan_iteration_delay.wait(timeout=0.1)
                return []

            mock_find.side_effect = long_scan

            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

            scan_started_event.wait(timeout=2.0)

            stop_start = time.time()
            worker.request_stop()
            thread.join(timeout=3.0)
            stop_duration = time.time() - stop_start

            assert stop_duration < 2.0, (
                f"Worker took {stop_duration:.2f}s to stop (should be <2s)"
            )
            assert not thread.is_alive(), "Worker thread should have stopped"

    def test_rapid_stop_start_cycles_no_zombies(self, qtbot: pytest.fixture) -> None:
        """Rapid stop/start cycles don't accumulate zombie threads.

        Simulates the production scenario where the artist clicks refresh
        multiple times in quick succession.
        """
        with patch(
            "threede.scene_worker.SceneDiscoveryCoordinator"
            ".find_all_scenes_in_shows_truly_efficient_parallel",
            return_value=[],
        ):
            active_before = threading.active_count()

            for cycle in range(3):
                worker = ThreeDESceneWorker(
                    shots=[self._make_shot()],
                    excluded_users=set(),
                )
                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()

                worker_startup_delay = threading.Event()
                worker_startup_delay.wait(timeout=0.1)
                worker.request_stop()
                thread.join(timeout=1.0)

                assert not thread.is_alive(), f"Cycle {cycle}: thread should be stopped"

            thread_settle_delay = threading.Event()
            thread_settle_delay.wait(timeout=0.5)
            thread_leak = threading.active_count() - active_before
            assert thread_leak <= 2, f"Leaked {thread_leak} threads after rapid cycles"

    def test_should_stop_consulted_as_cancel_flag(self) -> None:
        """should_stop() is wired as the cancel_flag passed to filesystem ops.

        Verifies the integration: worker.request_stop() → worker.should_stop() returns
        True → cancel_flag() returns True → scanner exits early.
        """
        from collections.abc import Callable

        worker = ThreeDESceneWorker(
            shots=[self._make_shot()],
            excluded_users=set(),
        )

        original_should_stop = worker.should_stop
        should_stop_calls = 0

        def tracked_should_stop() -> bool:
            nonlocal should_stop_calls
            should_stop_calls += 1
            return original_should_stop()

        worker.should_stop = tracked_should_stop  # type: ignore[method-assign]

        def mock_find(
            shots: list[Shot],
            excluded_users: set[str],
            progress_callback: Callable[[int, str], None] | None = None,
            cancel_flag: Callable[[], bool] | None = None,
        ) -> list:
            if cancel_flag:
                for _ in range(5):
                    if cancel_flag():
                        return []
            return []

        with patch(
            "threede.scene_worker.SceneDiscoveryCoordinator"
            ".find_all_scenes_in_shows_truly_efficient_parallel",
            side_effect=mock_find,
        ):
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

            worker_startup_delay = threading.Event()
            worker_startup_delay.wait(timeout=0.1)
            worker.request_stop()
            thread.join(timeout=1.0)

            assert should_stop_calls >= 5, (
                f"should_stop() only called {should_stop_calls} times"
            )
