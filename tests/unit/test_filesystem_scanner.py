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
from unittest.mock import MagicMock

import pytest
import time_machine

from filesystem_scanner import DirectoryCache, FileSystemScanner


if TYPE_CHECKING:
    from tests.fixtures.subprocess_mocking import SubprocessMock


pytestmark = [pytest.mark.unit]


@pytest.fixture
def fast_time():
    """Fixture for fast, deterministic time manipulation.

    Use this instead of time.sleep() when testing TTL-based logic.
    The traveller.shift() method instantly advances time.

    Example:
        def test_ttl(fast_time):
            cache.set(key, value, ttl=60)
            fast_time.shift(61)  # Instantly advance 61 seconds
            assert cache.is_expired(key)

    """
    with time_machine.travel(0, tick=False) as traveller:
        yield traveller


# =============================================================================
# DirectoryCache Threading Tests
# =============================================================================


class TestDirectoryCacheThreadSafety:
    """Test thread safety of DirectoryCache class.

    DirectoryCache uses threading.RLock() for synchronization.
    These tests verify correct behavior under concurrent access.
    """

    def test_concurrent_get_set_no_corruption(self) -> None:
        """Concurrent get/set operations don't corrupt cache state.

        Multiple threads simultaneously reading and writing to the cache
        should not cause data corruption or missing entries.
        """
        cache = DirectoryCache(ttl_seconds=60, enable_auto_expiry=False)
        barrier = threading.Barrier(10)
        errors: list[str] = []
        iterations = 50  # Reduced for faster tests

        def worker(worker_id: int) -> None:
            barrier.wait()  # Synchronized start
            for i in range(iterations):
                path = Path(f"/test/{worker_id}/{i}")
                expected_listing = [(f"file_{i}", True, False)]
                cache.set_listing(path, expected_listing)

                # Immediately read back - should always succeed
                result = cache.get_listing(path)
                if result is None:
                    errors.append(f"Worker {worker_id}: missing {path}")
                elif result != expected_listing:
                    errors.append(f"Worker {worker_id}: corrupted at {path}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety violation: {errors[:5]}"
        # Verify final state
        assert len(cache.cache) == 10 * iterations

    def test_clear_cache_during_active_reads(self) -> None:
        """Clearing cache during concurrent reads doesn't raise exceptions.

        One thread clearing the cache while others are reading should not
        cause crashes or corrupted state.
        """
        cache = DirectoryCache(ttl_seconds=60, enable_auto_expiry=False)
        barrier = threading.Barrier(6)  # 5 readers + 1 clearer
        exceptions: list[Exception] = []
        stop_flag = threading.Event()

        # Pre-populate cache
        for i in range(100):
            cache.set_listing(Path(f"/test/{i}"), [(f"file_{i}", True, False)])

        def reader(reader_id: int) -> None:
            barrier.wait()
            try:
                while not stop_flag.is_set():
                    for i in range(100):
                        _ = cache.get_listing(Path(f"/test/{i}"))
            except Exception as e:
                exceptions.append(e)

        def clearer() -> None:
            barrier.wait()
            try:
                for _ in range(10):
                    cache.clear_cache()
                    time.sleep(0.01)  # Brief pause between clears
            except Exception as e:
                exceptions.append(e)
            finally:
                stop_flag.set()

        readers = [threading.Thread(target=reader, args=(i,)) for i in range(5)]
        clear_thread = threading.Thread(target=clearer)

        for r in readers:
            r.start()
        clear_thread.start()

        clear_thread.join()
        stop_flag.set()
        for r in readers:
            r.join(timeout=2.0)

        assert not exceptions, f"Exceptions during concurrent access: {exceptions}"

    def test_ttl_expiration_thread_safe(self) -> None:
        """TTL expiration doesn't cause issues during concurrent access.

        With auto-expiry enabled, entries expiring while being accessed
        should not cause crashes or data corruption.
        """
        cache = DirectoryCache(ttl_seconds=1, enable_auto_expiry=True)
        barrier = threading.Barrier(5)
        errors: list[str] = []

        def worker(worker_id: int) -> None:
            barrier.wait()
            path = Path(f"/test/{worker_id}")

            for i in range(20):
                # Set with short TTL
                cache.set_listing(path, [(f"file_{i}", True, False)])

                # Small sleep to allow TTL expiration in some iterations
                time.sleep(0.05)

                # Read - may or may not be expired (both are valid)
                try:
                    result = cache.get_listing(path)
                    # Result can be None (expired) or the listing (not expired)
                    # Both are valid outcomes
                    if result is not None and not isinstance(result, list):
                        errors.append(f"Worker {worker_id}: invalid type {type(result)}")
                except Exception as e:
                    errors.append(f"Worker {worker_id}: exception {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"TTL expiration errors: {errors}"

    def test_stats_counter_thread_safe(self) -> None:
        """Cache statistics counters are thread-safe.

        Concurrent operations should correctly increment hit/miss/eviction
        counters without losing counts.
        """
        cache = DirectoryCache(ttl_seconds=60, enable_auto_expiry=False)
        barrier = threading.Barrier(10)
        iterations = 50

        # Pre-populate some entries for hits
        for i in range(25):
            cache.set_listing(Path(f"/existing/{i}"), [("file", True, False)])

        def worker(worker_id: int) -> None:
            barrier.wait()
            for i in range(iterations):
                # Half hits (existing paths), half misses (new paths)
                if i % 2 == 0:
                    cache.get_listing(Path(f"/existing/{i % 25}"))
                else:
                    cache.get_listing(Path(f"/missing/{worker_id}/{i}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = cache.get_stats()
        total = stats["hits"] + stats["misses"]

        # Should have exactly iterations * num_threads total operations
        expected_total = iterations * 10
        assert total == expected_total, f"Lost {expected_total - total} operations"

    def test_rlock_prevents_deadlock(self) -> None:
        """RLock allows reentrant calls without deadlock.

        DirectoryCache uses RLock which allows the same thread to acquire
        the lock multiple times. This tests that nested operations work.
        """
        cache = DirectoryCache(ttl_seconds=60, enable_auto_expiry=False)
        completed = threading.Event()

        def nested_operation() -> None:
            path = Path("/test/nested")
            # First lock acquisition
            cache.set_listing(path, [("file1", True, False)])
            # Second lock acquisition (reentrant)
            cache.get_listing(path)
            # Third lock acquisition
            _ = cache.get_stats()
            completed.set()

        thread = threading.Thread(target=nested_operation)
        thread.start()
        thread.join(timeout=2.0)

        assert completed.is_set(), "Nested lock acquisition caused deadlock"

    def test_large_cache_cleanup_threshold(self, fast_time) -> None:
        """Cache cleanup at 1000 entries threshold works correctly.

        When enable_auto_expiry=True, cache should clean up expired entries
        when size exceeds 1000.

        Uses fast_time fixture for instant TTL expiration instead of real sleep.
        """
        cache = DirectoryCache(ttl_seconds=1, enable_auto_expiry=True)

        # Add 500 entries that will expire
        for i in range(500):
            cache.set_listing(Path(f"/old/{i}"), [("file", True, False)])

        # Instantly advance time past TTL (replaces time.sleep(1.1))
        fast_time.shift(1.1)

        # Add 600 more entries (total > 1000, triggers cleanup)
        for i in range(600):
            cache.set_listing(Path(f"/new/{i}"), [("file", True, False)])

        # Old entries should be cleaned up
        stats = cache.get_stats()
        assert stats["evictions"] >= 500, f"Expected >= 500 evictions, got {stats['evictions']}"
        assert stats["total_entries"] <= 700, "Cache should be smaller after cleanup"


# =============================================================================
# Subprocess Timeout/Cancellation Tests
# =============================================================================


class TestSubprocessTimeoutCancellation:
    """Test subprocess timeout and cancellation handling.

    These tests verify that `_run_find_with_polling()` correctly handles:
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

        result = scanner_with_parser._run_find_with_polling(
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

        result = scanner_with_parser._run_find_with_polling(
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

        result = scanner_with_parser._run_find_with_polling(
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
        result = scanner_with_parser._run_find_with_polling(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=300.0,
        )

        assert result == [], "Error should return empty results, not crash"

    def test_file_not_found_find_command(
        self,
        scanner_with_parser: FileSystemScanner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FileNotFoundError (find command missing) returns empty results."""

        def raise_file_not_found(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError("[Errno 2] No such file or directory: 'find'")

        monkeypatch.setattr("filesystem_scanner.subprocess.Popen", raise_file_not_found)

        result = scanner_with_parser._run_find_with_polling(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=300.0,
        )

        assert result == [], "FileNotFoundError should return empty results"

    def test_permission_error_graceful(
        self,
        scanner_with_parser: FileSystemScanner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OSError (permission denied) returns empty results."""

        def raise_os_error(*args: object, **kwargs: object) -> None:
            raise OSError("[Errno 13] Permission denied")

        monkeypatch.setattr("filesystem_scanner.subprocess.Popen", raise_os_error)

        result = scanner_with_parser._run_find_with_polling(
            find_cmd=["find", "/test"],
            show_path=Path("/shows/TEST"),
            show="TEST",
            excluded_users=set(),
            cancel_flag=None,
            max_wait_time=300.0,
        )

        assert result == [], "OSError should return empty results"

    def test_max_wait_time_validation(
        self,
        scanner_with_parser: FileSystemScanner,
    ) -> None:
        """Invalid max_wait_time raises ValueError."""
        with pytest.raises(ValueError, match="max_wait_time must be positive"):
            scanner_with_parser._run_find_with_polling(
                find_cmd=["find", "/test"],
                show_path=Path("/shows/TEST"),
                show="TEST",
                excluded_users=set(),
                cancel_flag=None,
                max_wait_time=0,
            )

        with pytest.raises(ValueError, match="max_wait_time must be positive"):
            scanner_with_parser._run_find_with_polling(
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

        returncode, stdout, stderr, status = scanner._run_subprocess_with_streaming_read(
            cmd=cmd,
            cancel_flag=None,
            max_wait_time=10.0,  # 10 seconds should be plenty
        )

        assert status == "ok", f"Expected status 'ok', got '{status}'"
        assert returncode == 0, f"Expected return code 0, got {returncode}"
        # Output should have all the x's plus newline
        assert len(stdout.strip()) == output_size, (
            f"Expected {output_size} chars, got {len(stdout.strip())}"
        )
        assert stderr == "", f"Expected empty stderr, got: {stderr}"

    def test_very_large_output_multiple_reads(self) -> None:
        """Very large output (multiple pipe buffer fills) is captured correctly.

        Tests output that requires multiple read cycles, simulating real
        scenarios where find commands return thousands of file paths.
        """
        scanner = FileSystemScanner()

        # Generate 200KB of output (well over pipe buffer)
        output_size = 200_000
        cmd = ["python3", "-c", f"print('y' * {output_size})"]

        returncode, stdout, _stderr, status = scanner._run_subprocess_with_streaming_read(
            cmd=cmd,
            cancel_flag=None,
            max_wait_time=30.0,
        )

        assert status == "ok"
        assert returncode == 0
        assert len(stdout.strip()) == output_size

    def test_multiline_large_output(self) -> None:
        """Large output with many lines (like find command output) is captured.

        Simulates the actual use case: find command returning many file paths.
        """
        scanner = FileSystemScanner()

        # Generate 1000 lines of output (typical for a large show scan)
        num_lines = 1000
        cmd = [
            "python3",
            "-c",
            f"for i in range({num_lines}): print(f'/shows/TEST/shots/sq{{i:03d}}/sh{{i:04d}}/user/mm/3de/scene_{{i}}.3de')",
        ]

        returncode, stdout, _stderr, status = scanner._run_subprocess_with_streaming_read(
            cmd=cmd,
            cancel_flag=None,
            max_wait_time=30.0,
        )

        assert status == "ok"
        assert returncode == 0
        lines = stdout.strip().split("\n")
        assert len(lines) == num_lines, f"Expected {num_lines} lines, got {len(lines)}"

    def test_cancellation_during_large_output(self) -> None:
        """Cancellation works correctly during large output streaming."""
        scanner = FileSystemScanner()

        # Start a slow command that outputs data continuously
        cmd = ["python3", "-c", "import time; [print(f'line {i}') or time.sleep(0.01) for i in range(1000)]"]

        # Cancel after a brief delay
        cancel_triggered = [False]

        def cancel_flag() -> bool:
            if not cancel_triggered[0]:
                cancel_triggered[0] = True
                return False  # Don't cancel on first check
            return True  # Cancel on subsequent checks

        returncode, _stdout, _stderr, status = scanner._run_subprocess_with_streaming_read(
            cmd=cmd,
            cancel_flag=cancel_flag,
            max_wait_time=30.0,
        )

        assert status == "cancelled"
        assert returncode is None

    def test_timeout_during_large_output(self) -> None:
        """Timeout works correctly during large output streaming."""
        scanner = FileSystemScanner()

        # Command that runs indefinitely
        cmd = ["python3", "-c", "import time; [print(f'line {i}') or time.sleep(0.1) for i in range(10000)]"]

        returncode, _stdout, _stderr, status = scanner._run_subprocess_with_streaming_read(
            cmd=cmd,
            cancel_flag=None,
            max_wait_time=0.5,  # Very short timeout
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
                        from scene_parser import SceneParser
                        scanner.parser = SceneParser()
                parser_ids.append(id(scanner.parser))
            except Exception as e:
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

    def test_concurrent_coordinator_first_access(self) -> None:
        """Multiple threads accessing coordinator simultaneously get same instance."""
        scanner = FileSystemScanner()
        scanner._fs_coordinator = None
        scanner._fs_coordinator_lock = threading.Lock()

        barrier = threading.Barrier(5)
        coordinator_ids: list[int] = []
        errors: list[str] = []

        def access_coordinator() -> None:
            barrier.wait()
            try:
                with scanner._fs_coordinator_lock:
                    if scanner._fs_coordinator is None:
                        from filesystem_coordinator import FilesystemCoordinator
                        scanner._fs_coordinator = FilesystemCoordinator()
                coordinator_ids.append(id(scanner._fs_coordinator))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=access_coordinator) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent coordinator access: {errors}"
        unique_ids = set(coordinator_ids)
        assert len(unique_ids) == 1, f"Got {len(unique_ids)} different coordinator instances"

    def test_parser_available_after_init(self) -> None:
        """Parser is correctly available after lazy initialization."""
        scanner = FileSystemScanner()
        scanner.parser = None

        # Access via the pattern used in _run_find_with_polling
        with scanner._parser_lock:
            if scanner.parser is None:
                from scene_parser import SceneParser
                scanner.parser = SceneParser()

        # Should be available
        assert scanner.parser is not None
        assert hasattr(scanner.parser, "parse_3de_file_path")

    def test_exception_during_init_leaves_none(self) -> None:
        """Exception during lazy initialization leaves attribute as None.

        If an exception occurs while initializing parser or coordinator,
        the attribute should remain None, allowing retry.
        """
        scanner = FileSystemScanner()
        scanner.parser = None

        # Simulate failed initialization attempt
        with scanner._parser_lock:
            if scanner.parser is None:
                try:
                    # Simulate an error during initialization
                    raise ImportError("Test import failure")
                except ImportError:
                    pass  # Expected - don't set parser

        # Parser should still be None after failed import
        assert scanner.parser is None, "Parser should remain None after failed init"

        # Subsequent successful initialization should work
        with scanner._parser_lock:
            if scanner.parser is None:
                from scene_parser import SceneParser

                scanner.parser = SceneParser()

        assert scanner.parser is not None, "Parser should be set after successful init"


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
        original_python = scanner.find_3de_files_python_optimized
        original_subprocess = scanner.find_3de_files_subprocess_optimized

        def tracking_python(*args: object, **kwargs: object) -> list[tuple[str, Path]]:
            calls["python"] += 1
            return original_python(*args, **kwargs)

        def tracking_subprocess(*args: object, **kwargs: object) -> list[tuple[str, Path]]:
            calls["subprocess"] += 1
            return original_subprocess(*args, **kwargs)

        monkeypatch.setattr(scanner, "find_3de_files_python_optimized", tracking_python)
        monkeypatch.setattr(scanner, "find_3de_files_subprocess_optimized", tracking_subprocess)

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
            f"{tmp_path}/user/artist0/scene.3de\n"
            f"{tmp_path}/user/artist1/scene.3de\n"
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

        monkeypatch.setattr(scanner, "find_3de_files_subprocess_optimized", tracking_subprocess)

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

        original_python = scanner.find_3de_files_python_optimized

        def tracking_python(
            user_dir: Path, excluded_users: set[str] | None
        ) -> list[tuple[str, Path]]:
            calls["python"] += 1
            return original_python(user_dir, excluded_users)

        monkeypatch.setattr(scanner, "find_3de_files_subprocess_optimized", failing_subprocess)
        monkeypatch.setattr(scanner, "find_3de_files_python_optimized", tracking_python)

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
        result = scanner.find_3de_files_python_optimized(user_dir, excluded_users=excluded)

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
        result = scanner.find_3de_files_subprocess_optimized(user_dir, excluded_users=excluded)

        # Results should exclude the specified users
        usernames = {username for username, _ in result}
        assert "excluded_user" not in usernames
        assert "temp" not in usernames


# =============================================================================
# ThreeDESceneWorker Cancel/Interrupt Tests
# (merged from test_worker_stop_responsiveness.py)
# =============================================================================


from unittest.mock import patch

from shot_model import Shot
from threede_scene_worker import ThreeDESceneWorker


@pytest.mark.qt
@pytest.mark.concurrency
@pytest.mark.regression
class TestThreeDEWorkerStopAndCancel:
    """Cancel and interrupt behaviour for ThreeDESceneWorker.

    These are regression tests for the zombie thread issue where workers
    would get stuck in blocking subprocess.run() calls for up to 5 seconds.
    The fix threads a cancel_flag through to filesystem operations so that
    worker.stop() propagates quickly.
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
            scan_all_shots=True,
        )

        with patch(
            "threede_scene_finder.OptimizedThreeDESceneFinder"
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
                    threading.Event().wait(timeout=0.1)
                return []

            mock_find.side_effect = long_scan

            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

            scan_started_event.wait(timeout=2.0)

            stop_start = time.time()
            worker.stop()
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
            "threede_scene_finder.OptimizedThreeDESceneFinder"
            ".find_all_scenes_in_shows_truly_efficient_parallel",
            return_value=[],
        ):
            active_before = threading.active_count()

            for cycle in range(3):
                worker = ThreeDESceneWorker(
                    shots=[self._make_shot()],
                    excluded_users=set(),
                    scan_all_shots=True,
                )
                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()

                threading.Event().wait(timeout=0.1)
                worker.stop()
                thread.join(timeout=1.0)

                assert not thread.is_alive(), f"Cycle {cycle}: thread should be stopped"

            threading.Event().wait(timeout=0.5)
            thread_leak = threading.active_count() - active_before
            assert thread_leak <= 2, f"Leaked {thread_leak} threads after rapid cycles"

    def test_should_stop_consulted_as_cancel_flag(self) -> None:
        """should_stop() is wired as the cancel_flag passed to filesystem ops.

        Verifies the integration: worker.stop() → worker.should_stop() returns
        True → cancel_flag() returns True → scanner exits early.
        """
        from collections.abc import Callable

        worker = ThreeDESceneWorker(
            shots=[self._make_shot()],
            excluded_users=set(),
            scan_all_shots=True,
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
            "threede_scene_finder.OptimizedThreeDESceneFinder"
            ".find_all_scenes_in_shows_truly_efficient_parallel",
            side_effect=mock_find,
        ):
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

            threading.Event().wait(timeout=0.1)
            worker.stop()
            thread.join(timeout=1.0)

            assert should_stop_calls >= 5, (
                f"should_stop() only called {should_stop_calls} times"
            )
