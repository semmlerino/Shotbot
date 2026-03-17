"""Tests for FilesystemCoordinator - Singleton filesystem caching coordinator.

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real filesystem operations with tmp_path
- Test thread safety and singleton pattern
- Proper cleanup and isolation between tests
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest

from paths.filesystem_coordinator import FilesystemCoordinator


# Test markers
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Fixtures
@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None, None, None]:
    """Reset FilesystemCoordinator singleton between tests for isolation."""
    # Reset before test
    FilesystemCoordinator.reset()
    yield
    # Reset after test
    FilesystemCoordinator.reset()


@pytest.fixture
def coordinator() -> FilesystemCoordinator:
    """Get a FilesystemCoordinator instance with cleared cache for test isolation."""
    coord = FilesystemCoordinator()
    # Clear cache for test isolation (UNIFIED_TESTING_GUIDE: avoid shared state)
    coord._directory_cache.clear()
    coord._cache_hits = 0
    coord._cache_misses = 0
    return coord


@pytest.fixture
def make_test_directory(tmp_path: Path) -> Callable[[str, int, int], Path]:
    """Factory for creating test directory structures."""

    def _make(name: str = "test_dir", file_count: int = 5, subdirs: int = 2) -> Path:
        """Create a directory with files and subdirectories."""
        dir_path = tmp_path / name
        dir_path.mkdir(exist_ok=True)

        # Create files
        for i in range(file_count):
            (dir_path / f"file_{i}.txt").touch()

        # Create subdirectories
        for i in range(subdirs):
            subdir = dir_path / f"subdir_{i}"
            subdir.mkdir()
            (subdir / "nested.txt").touch()

        return dir_path

    return _make


class TestSingletonPattern:
    """Test the singleton pattern implementation."""

    def test_single_instance_created(self) -> None:
        """Test that only one instance is created."""
        coord1 = FilesystemCoordinator()
        coord2 = FilesystemCoordinator()

        assert coord1 is coord2
        assert id(coord1) == id(coord2)

    def test_thread_safe_initialization(self) -> None:
        """Test thread-safe singleton creation.

        Following guide: Thread safety testing pattern.
        """
        instances: list[FilesystemCoordinator] = []

        def create_instance() -> None:
            """Create instance in thread."""
            instances.append(FilesystemCoordinator())

        # Create multiple threads trying to instantiate
        threads = [Thread(target=create_instance) for _ in range(10)]

        # Start all threads
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be the same instance
        assert len(instances) == 10
        first_instance = instances[0]
        for instance in instances[1:]:
            assert instance is first_instance

    def test_singleton_persists_data(
        self, make_test_directory: Callable[[str, int, int], Path]
    ) -> None:
        """Test that singleton maintains state across calls."""
        test_dir = make_test_directory()

        # First instance caches directory
        coord1 = FilesystemCoordinator()
        listing1 = coord1.get_directory_listing(test_dir)

        # Second instance should have cached data
        coord2 = FilesystemCoordinator()
        # Access internal cache to verify (normally wouldn't do this)
        assert test_dir in coord2._directory_cache

        # Should return same listing
        listing2 = coord2.get_directory_listing(test_dir)
        assert listing1 == listing2


class TestDirectoryCaching:
    """Test directory listing cache functionality."""

    def test_get_directory_listing(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test basic directory listing retrieval."""
        test_dir = make_test_directory(file_count=3, subdirs=1)

        listing = coordinator.get_directory_listing(test_dir)

        # Should have 3 files + 1 subdir
        assert len(listing) == 4
        # Check entries are (name, is_dir, is_file) tuples
        assert all(isinstance(t, tuple) and len(t) == 3 for t in listing)
        # Check expected files exist
        assert any(name == "file_0.txt" for name, _, _ in listing)
        assert any(name == "subdir_0" for name, _, _ in listing)

    def test_cache_hit_performance(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test that cached access is faster than initial scan.

        Following UNIFIED_TESTING_GUIDE: Test behavior, not strict performance.
        Cache should provide speedup, but exact multiplier varies by system.
        """
        test_dir = make_test_directory(file_count=100, subdirs=10)

        # First access - should scan filesystem
        start = time.time()
        listing1 = coordinator.get_directory_listing(test_dir)
        first_time = time.time() - start

        # Verify cache miss was recorded
        initial_misses = coordinator._cache_misses
        initial_hits = coordinator._cache_hits

        # Second access - should use cache
        start = time.time()
        listing2 = coordinator.get_directory_listing(test_dir)
        second_time = time.time() - start

        # Verify cache hit was recorded (behavior test)
        assert coordinator._cache_hits == initial_hits + 1, "Should record cache hit"
        assert coordinator._cache_misses == initial_misses, (
            "Should not record additional miss"
        )

        # Cache should be faster (reasonable threshold for micro-benchmarks)
        # Using 2x speedup as minimum instead of 10x to avoid flakiness
        assert second_time < first_time / 2, (
            f"Cached access should be at least 2x faster: "
            f"first={first_time:.6f}s, second={second_time:.6f}s, "
            f"speedup={first_time / second_time if second_time > 0 else float('inf')}x"
        )

        # Results should match (correctness test)
        assert listing1 == listing2

    def test_cache_invalidation_on_change(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test that cache detects filesystem changes."""
        test_dir = make_test_directory(
            file_count=2, subdirs=0
        )  # Only files, no subdirs

        # Get initial listing
        listing1 = coordinator.get_directory_listing(test_dir)
        assert len(listing1) == 2

        # Add a new file
        (test_dir / "new_file.txt").touch()

        # Invalidate cache manually
        coordinator.invalidate_path(test_dir)

        # Get new listing
        listing2 = coordinator.get_directory_listing(test_dir)
        assert len(listing2) == 3
        assert any(name == "new_file.txt" for name, _, _ in listing2)

    def test_cache_ttl_expiration(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test that cache expires after TTL."""
        test_dir = make_test_directory(
            file_count=2, subdirs=0
        )  # Only files, no subdirs

        # Mock time to control TTL
        with patch("time.time") as mock_time:
            # Initial scan at time 0
            mock_time.return_value = 0
            listing1 = coordinator.get_directory_listing(test_dir)
            assert len(listing1) == 2

            # Add new file
            (test_dir / "new_file.txt").touch()

            # Access before TTL expiry (default 300s) - should use cache
            mock_time.return_value = 299
            listing2 = coordinator.get_directory_listing(test_dir)
            assert len(listing2) == 2  # Still cached

            # Access after TTL expiry - should rescan
            mock_time.return_value = 301
            listing3 = coordinator.get_directory_listing(test_dir)
            assert len(listing3) == 3  # Rescanned

    def test_nonexistent_directory(self, coordinator: FilesystemCoordinator) -> None:
        """Test handling of nonexistent directories."""
        fake_dir = Path("/nonexistent/directory")

        listing = coordinator.get_directory_listing(fake_dir)

        # Should return empty list
        assert listing == []

    def test_empty_directory(
        self, coordinator: FilesystemCoordinator, tmp_path: Path
    ) -> None:
        """Test handling of empty directories."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        listing = coordinator.get_directory_listing(empty_dir)

        assert listing == []


class TestSharedCaching:
    """Test that multiple components share the same cache."""

    def test_multiple_models_share_cache(
        self, make_test_directory: Callable[[str, int, int], Path]
    ) -> None:
        """Test that different models access the same cached data.

        Simulates how different shot models would share filesystem cache.
        """
        test_dir = make_test_directory(file_count=10)

        # Simulate multiple models
        coord1 = FilesystemCoordinator()  # Would be from ShotModel
        coord2 = FilesystemCoordinator()  # Would be from ThreeDEModel
        coord3 = FilesystemCoordinator()  # Would be from PreviousShotsModel

        # First model scans
        listing1 = coord1.get_directory_listing(test_dir)

        # Track if other models hit cache (mock scandir to detect)
        with patch("paths.filesystem_coordinator.os.scandir") as mock_scandir:
            # Other models should use cache, not scan
            listing2 = coord2.get_directory_listing(test_dir)
            listing3 = coord3.get_directory_listing(test_dir)

            # scandir should not have been called (cache hit)
            mock_scandir.assert_not_called()

        # All should have same listing
        assert listing1 == listing2 == listing3

    def test_concurrent_access_same_directory(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test concurrent access to the same directory.

        Following guide: Thread safety pattern.
        """
        test_dir = make_test_directory(file_count=50)
        results: list[int] = []

        def access_directory() -> None:
            """Access directory from thread."""
            listing = coordinator.get_directory_listing(test_dir)
            results.append(len(listing))

        # Create many concurrent accessors
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(access_directory) for _ in range(100)]
            for future in futures:
                future.result()

        # All should get same result
        assert len(results) == 100
        assert all(r == results[0] for r in results)


class TestCacheInvalidation:
    """Test cache invalidation mechanisms."""

    def test_invalidate_single_path(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test invalidating a single cached path."""
        dir1 = make_test_directory(name="dir1", file_count=2)
        dir2 = make_test_directory(name="dir2", file_count=3)

        # Cache both
        coordinator.get_directory_listing(dir1)
        coordinator.get_directory_listing(dir2)

        # Invalidate only dir1
        coordinator.invalidate_path(dir1)

        # Add file to dir1
        (dir1 / "new.txt").touch()

        # dir1 should rescan and show new file, dir2 should still be cached
        new_listing1 = coordinator.get_directory_listing(dir1)
        cached_listing2 = coordinator.get_directory_listing(dir2)

        # Should have updated dir1 with new file, dir2 unchanged
        assert (
            len(new_listing1) == 5
        )  # 2 original files + 2 default subdirs + 1 new file
        assert any(name == "new.txt" for name, _, _ in new_listing1)
        assert len(cached_listing2) == 5  # Still cached (3 files + 2 default subdirs)

        # Verify cache stats show the rescan
        stats = coordinator.get_cache_stats()
        assert stats["cache_hits"] >= 1  # dir2 was cached
        assert stats["cache_misses"] >= 3  # Initial scans + dir1 rescan

    def test_invalidate_all_cache(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test invalidating entire cache."""
        dir1 = make_test_directory(name="dir1")
        dir2 = make_test_directory(name="dir2")

        # Cache both
        coordinator.get_directory_listing(dir1)
        coordinator.get_directory_listing(dir2)

        # Verify cache contains entries
        stats_before = coordinator.get_cache_stats()
        assert stats_before["cached_directories"] == 2

        # Clear all cache
        coordinator.invalidate_all()

        # Verify cache is empty
        stats_after = coordinator.get_cache_stats()
        assert stats_after["cached_directories"] == 0
        assert stats_after["cache_hits"] == 0
        assert stats_after["cache_misses"] == 0

        # Access both again - should cause cache misses
        coordinator.get_directory_listing(dir1)
        coordinator.get_directory_listing(dir2)

        final_stats = coordinator.get_cache_stats()
        assert final_stats["cache_misses"] == 2  # Both rescanned

    def test_share_discovered_paths(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test sharing discovered paths between workers."""
        dir1 = make_test_directory(name="dir1", file_count=3, subdirs=0)  # Only files
        dir2 = make_test_directory(name="dir2", file_count=2, subdirs=0)  # Only files

        # Simulate a worker discovering paths (using tuple format)
        discovered_paths = {
            dir1: [(e.name, e.is_dir(), e.is_file()) for e in dir1.iterdir()],
            dir2: [(e.name, e.is_dir(), e.is_file()) for e in dir2.iterdir()],
        }

        # Share discovered paths
        coordinator.share_discovered_paths(discovered_paths)

        # Verify they are cached by checking cache stats
        stats_before = coordinator.get_cache_stats()
        assert stats_before["cached_directories"] == 2

        # These should now be cache hits
        listing1 = coordinator.get_directory_listing(dir1)
        listing2 = coordinator.get_directory_listing(dir2)

        # Verify cache was used (hits should increase)
        stats_after = coordinator.get_cache_stats()
        assert stats_after["cache_hits"] == 2
        assert stats_after["cache_misses"] == 0  # No new misses

        assert len(listing1) == 3
        assert len(listing2) == 2


class TestAdditionalMethods:
    """Test additional coordinator methods."""

    def test_find_files_with_extension(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test finding files with specific extension."""
        test_dir = make_test_directory()

        # Add some .txt and .py files
        (test_dir / "script.py").touch()
        (test_dir / "module.py").touch()
        (test_dir / "data.json").touch()

        # Find .py files
        py_files = coordinator.find_files_with_extension(test_dir, ".py")

        assert len(py_files) == 2
        assert all(f.suffix == ".py" for f in py_files)

    def test_find_files_recursive(
        self, coordinator: FilesystemCoordinator, tmp_path: Path
    ) -> None:
        """Test recursive file finding."""
        # Create nested structure
        root = tmp_path / "root"
        root.mkdir()
        (root / "file1.3de").touch()

        subdir = root / "subdir"
        subdir.mkdir()
        (subdir / "file2.3de").touch()
        (subdir / "other.txt").touch()

        # Find .3de files recursively
        files = coordinator.find_files_with_extension(root, ".3de", recursive=True)

        assert len(files) == 2
        assert any("file1.3de" in str(f) for f in files)
        assert any("file2.3de" in str(f) for f in files)

    def test_get_cache_stats(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test cache statistics tracking."""
        dir1 = make_test_directory(name="dir1")
        dir2 = make_test_directory(name="dir2")

        # Initial stats
        stats = coordinator.get_cache_stats()
        assert stats["cached_directories"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0

        # Access directories
        coordinator.get_directory_listing(dir1)  # miss
        coordinator.get_directory_listing(dir1)  # hit
        coordinator.get_directory_listing(dir2)  # miss
        coordinator.get_directory_listing(dir2)  # hit
        coordinator.get_directory_listing(dir2)  # hit

        # Check updated stats
        stats = coordinator.get_cache_stats()
        assert stats["cached_directories"] == 2
        assert stats["cache_hits"] == 3
        assert stats["cache_misses"] == 2
        assert stats["hit_rate"] == 0.6

    def test_cleanup_expired(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test cleanup of expired cache entries."""
        dir1 = make_test_directory(name="dir1")
        dir2 = make_test_directory(name="dir2")

        # Cache directories with mocked time
        with patch("time.time") as mock_time:
            # Cache at time 0
            mock_time.return_value = 0
            coordinator.get_directory_listing(dir1)
            coordinator.get_directory_listing(dir2)

            # Run cleanup at time 400 (past 300s TTL)
            mock_time.return_value = 400
            removed = coordinator.cleanup_expired()

        assert removed == 2
        assert len(coordinator._directory_cache) == 0

    def test_set_ttl(self, coordinator: FilesystemCoordinator) -> None:
        """Test changing TTL value."""
        # Default TTL
        stats = coordinator.get_cache_stats()
        assert stats["ttl_seconds"] == 300

        # Update TTL
        coordinator.set_ttl(600)

        stats = coordinator.get_cache_stats()
        assert stats["ttl_seconds"] == 600


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_permission_denied(
        self, coordinator: FilesystemCoordinator, tmp_path: Path
    ) -> None:
        """Test handling of permission denied errors."""
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()

        # Mock OSError for permission denied
        with patch(
            "paths.filesystem_coordinator.os.scandir",
            side_effect=PermissionError("Access denied"),
        ):
            listing = coordinator.get_directory_listing(restricted_dir)

        # Should return empty list on error
        assert listing == []

    def test_directory_deleted_after_cache(
        self,
        coordinator: FilesystemCoordinator,
        make_test_directory: Callable[[str, int, int], Path],
    ) -> None:
        """Test handling when cached directory is deleted."""
        test_dir = make_test_directory()

        # Cache the directory
        listing1 = coordinator.get_directory_listing(test_dir)
        assert len(listing1) > 0

        # Delete the directory
        import shutil

        shutil.rmtree(test_dir)

        # Invalidate cache after deletion (proper usage pattern)
        coordinator.invalidate_path(test_dir)

        # Should handle gracefully
        listing2 = coordinator.get_directory_listing(test_dir)
        assert listing2 == []  # Returns empty for missing dir

    def test_symbolic_links(self, tmp_path: Path) -> None:
        """Test handling of symbolic links."""
        coordinator = FilesystemCoordinator()

        # Create directory with symlink
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "file.txt").touch()

        link_dir = tmp_path / "link"
        link_dir.symlink_to(real_dir)

        # Should follow symlinks
        listing = coordinator.get_directory_listing(link_dir)
        assert len(listing) == 1
        assert listing[0][0] == "file.txt"
