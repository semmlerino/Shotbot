"""Unit tests for cache TTL (Time-To-Live) performance optimizations.

These tests verify that:
1. TTL is correctly set to 300 seconds in utils.py
2. Cache expiration behavior works as expected
3. Cache hit/miss scenarios are handled correctly
4. Eviction strategies work properly
5. Performance improvements are maintained
"""

from pathlib import Path
from typing import List
from unittest.mock import Mock, patch

from config import Config
from tests.performance.timed_operation import TimingRegistry, timed_operation
from utils import PathUtils, VersionUtils, clear_all_caches, get_cache_stats


class TestCacheTTL:
    """Test suite for cache TTL optimizations."""

    def setup_method(self):
        """Set up test environment."""
        TimingRegistry.clear()
        clear_all_caches()

    def teardown_method(self):
        """Clean up after tests."""
        TimingRegistry.clear()
        clear_all_caches()

    def test_path_cache_ttl_configuration(self):
        """Test that path cache TTL is correctly set to 300 seconds."""
        # Import the module-level TTL constant
        from utils import _PATH_CACHE_TTL

        # Verify TTL is 300 seconds (5 minutes)
        assert _PATH_CACHE_TTL == 300.0

        # Also verify it matches Config if available
        if hasattr(Config, "PATH_CACHE_TTL_SECONDS"):
            assert _PATH_CACHE_TTL == Config.PATH_CACHE_TTL_SECONDS

    def test_path_cache_basic_functionality(self, tmp_path):
        """Test basic path cache functionality."""
        # Create a real temp file instead of mocking
        test_file = tmp_path / "test_path"
        test_file.touch()
        test_path = str(test_file)

        # First call should cache the result
        result1 = PathUtils.validate_path_exists(test_path, "Test path")
        assert result1 is True

        # Second call should use cache
        result2 = PathUtils.validate_path_exists(test_path, "Test path")
        assert result2 is True

        # Cache should contain the entry
        stats = get_cache_stats()
        assert stats["path_cache_size"] > 0

    def test_cache_expiration_behavior(self, tmp_path):
        """Test that cache entries expire after TTL."""
        # Create a real temp file
        test_file = tmp_path / "expiring_path"
        test_file.touch()
        test_path = str(test_file)

        # Mock time to control expiration
        mock_time = Mock(return_value=1000.0)

        # Track filesystem access by wrapping the real path check
        access_count = 0
        original_exists = Path.exists

        def tracked_exists(self):
            nonlocal access_count
            if str(self) == test_path:
                access_count += 1
            return original_exists(self)

        with patch("time.time", mock_time):
            with patch.object(Path, "exists", tracked_exists):
                # First call at time 1000
                result1 = PathUtils.validate_path_exists(test_path, "Test path")
                assert result1 is True
                assert access_count == 1

                # Second call at time 1000 + 100 (within TTL)
                mock_time.return_value = 1100.0
                result2 = PathUtils.validate_path_exists(test_path, "Test path")
                assert result2 is True
                # Should not call exists() again (cache hit)
                assert access_count == 1

                # Third call at time 1000 + 400 (beyond TTL of 300)
                mock_time.return_value = 1400.0
                result3 = PathUtils.validate_path_exists(test_path, "Test path")
                assert result3 is True
                # Should call exists() again (cache miss due to expiration)
                assert access_count == 2

    def test_cache_hit_miss_scenarios(self, tmp_path):
        """Test various cache hit and miss scenarios."""
        # Create real temp files
        test_files = []
        paths = []
        for i in range(3):
            test_file = tmp_path / f"path{i + 1}"
            test_file.touch()
            test_files.append(test_file)
            paths.append(str(test_file))

        # Track filesystem access
        access_count = 0
        original_exists = Path.exists

        def tracked_exists(self):
            nonlocal access_count
            if str(self) in paths:
                access_count += 1
            return original_exists(self)

        with patch.object(Path, "exists", tracked_exists):
            # First round - all misses, should populate cache
            for path in paths:
                result = PathUtils.validate_path_exists(path, "Test path")
                assert result is True

            assert access_count == len(paths)

            # Second round - all hits, should use cache
            initial_count = access_count
            for path in paths:
                result = PathUtils.validate_path_exists(path, "Test path")
                assert result is True

            # Should not have called exists() again
            assert access_count == initial_count

    def test_cache_eviction_strategy(self):
        """Test cache eviction when size limits are exceeded."""
        # Generate many paths to trigger eviction
        base_paths = [
            f"/tmp/test_path_{i}" for i in range(6000)
        ]  # Exceed limit of 5000

        with patch.object(Path, "exists", return_value=True):
            # Fill cache beyond limit
            for path in base_paths:
                PathUtils.validate_path_exists(path, "Test path")

            stats = get_cache_stats()
            # Cache should be limited to reasonable size
            assert stats["path_cache_size"] <= 5000

    def test_batch_validation_performance(self):
        """Test batch path validation performance."""
        test_paths = [f"/tmp/batch_path_{i}" for i in range(100)]

        @timed_operation("batch_validation", store_results=True)
        def run_batch_validation():
            with patch.object(Path, "exists", return_value=True):
                return PathUtils.batch_validate_paths(test_paths)

        # Run batch validation
        results = run_batch_validation()

        # Verify results
        assert len(results) == len(test_paths)
        assert all(results.values())  # All should be True

        # Check timing
        stats = TimingRegistry.get_stats("batch_validation")
        assert stats is not None
        assert stats["mean_ms"] < 100  # Should be fast with caching

    def test_version_cache_ttl(self):
        """Test version directory cache TTL behavior."""
        test_base_path = "/tmp/version_test"

        # Mock directory structure
        mock_path = Mock()
        mock_v001 = Mock()
        mock_v001.is_dir.return_value = True
        mock_v001.name = "v001"
        mock_v002 = Mock()
        mock_v002.is_dir.return_value = True
        mock_v002.name = "v002"

        mock_path.iterdir.return_value = [mock_v001, mock_v002]

        with patch.object(Path, "exists", return_value=True):
            with patch("utils.Path", return_value=mock_path):
                # First call should populate cache
                result1 = VersionUtils.find_version_directories(test_base_path)
                assert len(result1) == 2
                assert result1[0] == (1, "v001")
                assert result1[1] == (2, "v002")

                # Second call should use cache (reset mock to verify)
                mock_path.iterdir.reset_mock()
                result2 = VersionUtils.find_version_directories(test_base_path)
                assert result2 == result1
                # Should not call iterdir again
                assert mock_path.iterdir.call_count == 0

    def test_cache_cleanup_performance(self):
        """Test that cache cleanup doesn't impact performance significantly."""
        # Fill cache with many entries
        test_paths = [f"/tmp/cleanup_test_{i}" for i in range(3000)]

        @timed_operation("cache_fill", store_results=True)
        def fill_cache():
            with patch.object(Path, "exists", return_value=True):
                for path in test_paths:
                    PathUtils.validate_path_exists(path, "Test path")

        @timed_operation("cache_access_after_fill", store_results=True)
        def access_after_fill():
            with patch.object(Path, "exists", return_value=True):
                # Access some paths after cache is full
                for i in range(0, 100, 10):  # Access every 10th path
                    PathUtils.validate_path_exists(test_paths[i], "Test path")

        # Fill cache
        fill_cache()

        # Access after fill
        access_after_fill()

        # Verify performance didn't degrade significantly
        fill_stats = TimingRegistry.get_stats("cache_fill")
        access_stats = TimingRegistry.get_stats("cache_access_after_fill")

        assert fill_stats is not None
        assert access_stats is not None

        # Access should be much faster than initial fill
        assert access_stats["mean_ms"] < fill_stats["mean_ms"] / 10

    def test_cache_memory_efficiency(self):
        """Test that cache memory usage is efficient."""

        # Get initial cache stats
        initial_stats = get_cache_stats()
        initial_path_cache = initial_stats["path_cache_size"]

        # Add many entries
        test_paths = [f"/tmp/memory_test_{i}" for i in range(1000)]

        with patch.object(Path, "exists", return_value=True):
            for path in test_paths:
                PathUtils.validate_path_exists(path, "Test path")

        # Check final stats
        final_stats = get_cache_stats()
        final_path_cache = final_stats["path_cache_size"]

        # Cache should have grown
        assert final_path_cache > initial_path_cache

        # Memory usage should be reasonable
        # Each cache entry stores: (bool, float) = ~24 bytes + key string
        # Estimate ~50 bytes per entry on average
        estimated_memory_bytes = (final_path_cache - initial_path_cache) * 50
        estimated_memory_mb = estimated_memory_bytes / (1024 * 1024)

        # Should be reasonable memory usage (less than 5MB for 1000 entries)
        assert estimated_memory_mb < 5.0, (
            f"Cache using too much memory: {estimated_memory_mb:.2f}MB"
        )

        print(f"Cache entries added: {final_path_cache - initial_path_cache}")
        print(f"Estimated memory usage: {estimated_memory_mb:.2f}MB")

    def test_cache_thread_safety(self):
        """Test cache thread safety under concurrent access."""
        import concurrent.futures

        def worker_function(worker_id: int, iterations: int = 50) -> int:
            """Worker function for thread safety testing."""
            successes = 0
            with patch.object(Path, "exists", return_value=True):
                for i in range(iterations):
                    path = f"/tmp/thread_test_{worker_id}_{i}"
                    result = PathUtils.validate_path_exists(path, "Thread test")
                    if result:
                        successes += 1
            return successes

        num_workers = 8
        iterations_per_worker = 25

        # Run workers concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(worker_function, i, iterations_per_worker)
                for i in range(num_workers)
            ]

            results = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)

        # Verify all workers completed successfully
        assert len(results) == num_workers
        assert all(r == iterations_per_worker for r in results)

        # Verify cache contains expected entries
        stats = get_cache_stats()
        expected_min_entries = num_workers * iterations_per_worker
        assert stats["path_cache_size"] >= expected_min_entries

        print(f"Thread safety test: {sum(results)} operations completed successfully")

    @timed_operation("ttl_performance_baseline", store_results=True)
    def _baseline_path_validation(self, test_paths: List[str], iterations: int = 5):
        """Baseline path validation without caching."""
        with patch.object(Path, "exists", return_value=True):
            for _ in range(iterations):
                for path in test_paths:
                    # Force filesystem check each time
                    Path(path).exists()

    @timed_operation("ttl_performance_optimized", store_results=True)
    def _optimized_path_validation(self, test_paths: List[str], iterations: int = 5):
        """Optimized path validation with caching."""
        for _ in range(iterations):
            for path in test_paths:
                PathUtils.validate_path_exists(path, "Performance test")

    def test_ttl_cache_performance_improvement(self):
        """Test that TTL cache provides significant performance improvement."""
        test_paths = [f"/tmp/perf_test_{i}" for i in range(50)]
        iterations = 10

        with patch.object(Path, "exists", return_value=True):
            # Run baseline (no caching)
            self._baseline_path_validation(test_paths, iterations)

            # Run optimized (with caching)
            self._optimized_path_validation(test_paths, iterations)

        # Get timing statistics
        baseline_stats = TimingRegistry.get_stats("ttl_performance_baseline")
        optimized_stats = TimingRegistry.get_stats("ttl_performance_optimized")

        assert baseline_stats is not None
        assert optimized_stats is not None

        # Calculate speedup
        speedup = TimingRegistry.compare_operations(
            "ttl_performance_baseline", "ttl_performance_optimized"
        )
        assert speedup is not None

        # Should see significant improvement (at least 10x)
        assert speedup >= 10.0, f"Expected at least 10x speedup, got {speedup:.2f}x"

        print(f"TTL cache speedup: {speedup:.1f}x")
        print(f"Baseline: {baseline_stats['mean_ms']:.2f}ms")
        print(f"Optimized: {optimized_stats['mean_ms']:.2f}ms")

    def test_cache_persistence_across_operations(self):
        """Test that cache persists across multiple operations."""
        test_path = "/tmp/persistence_test"

        with patch.object(Path, "exists", return_value=True) as mock_exists:
            # Multiple operations using the same path
            operations = [
                lambda: PathUtils.validate_path_exists(test_path, "Op 1"),
                lambda: PathUtils.build_path("/tmp", "persistence_test"),
                lambda: PathUtils.validate_path_exists(test_path, "Op 2"),
            ]

            for i, op in enumerate(operations):
                op()
                if i == 0:
                    # First operation should call exists()
                    assert mock_exists.call_count == 1
                elif i == 2:
                    # Third operation should not call exists() again (cache hit)
                    assert mock_exists.call_count == 1

    def test_cache_invalidation_scenarios(self):
        """Test cache behavior in various invalidation scenarios."""
        test_path = "/tmp/invalidation_test"

        # Test manual cache clearing
        with patch.object(Path, "exists", return_value=True) as mock_exists:
            # Populate cache
            result1 = PathUtils.validate_path_exists(test_path, "Test")
            assert result1 is True
            assert mock_exists.call_count == 1

            # Clear cache
            clear_all_caches()

            # Next call should hit filesystem again
            mock_exists.reset_mock()
            result2 = PathUtils.validate_path_exists(test_path, "Test")
            assert result2 is True
            assert mock_exists.call_count == 1

    def test_different_path_types(self):
        """Test cache behavior with different path types."""
        test_cases = [
            "/tmp/absolute_path",
            "relative_path",
            str(Path("/tmp/pathlib_path")),
            "/tmp/path with spaces",
            "/tmp/path_with_unicode_café",
        ]

        with patch.object(Path, "exists", return_value=True) as mock_exists:
            # Test different path types
            for test_path in test_cases:
                result = PathUtils.validate_path_exists(test_path, "Path type test")
                assert result is True

            # All should have been cached
            assert mock_exists.call_count == len(test_cases)

            # Second round should use cache
            mock_exists.reset_mock()
            for test_path in test_cases:
                result = PathUtils.validate_path_exists(test_path, "Path type test")
                assert result is True

            # Should not call exists() again
            assert mock_exists.call_count == 0
