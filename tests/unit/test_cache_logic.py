"""Tests for path caching logic in path_validators.py.

These tests verify that the path caching infrastructure works correctly:
- Cache hits return cached results
- Cache misses trigger validation
- Cache can be cleared
- Cache can be enabled/disabled

Note: These tests use the caching_enabled fixture to test with caching ON,
since the default test behavior now keeps caching enabled (after the fix).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from cache_manager import CacheManager


def _validate_path(path: Path | str, description: str = "Path") -> bool:
    """Helper to call PathValidators.validate_path_exists."""
    from path_validators import PathValidators

    return PathValidators.validate_path_exists(path, description)


def _get_cache_stats() -> dict[str, int]:
    """Helper to get cache stats with consistent key name."""
    from path_validators import get_cache_stats

    stats = get_cache_stats()
    # Normalize key name
    return {"size": stats.get("path_cache_size", stats.get("size", 0))}


class TestPathCacheHitMiss:
    """Test path cache hit/miss behavior."""

    def test_cache_hit_returns_cached_result(self, tmp_path: Path) -> None:
        """Test that second lookup returns cached result."""
        from path_validators import clear_path_cache

        # Create a real path
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Clear cache to start fresh
        clear_path_cache()

        # First validation - cache miss
        result1 = _validate_path(test_dir, "test dir")
        assert result1 is True

        stats_after_first = _get_cache_stats()
        cache_size_after_first = stats_after_first["size"]

        # Second validation - should be cache hit
        result2 = _validate_path(test_dir, "test dir")
        assert result2 is True

        # Cache size should be same (hit, not miss)
        stats_after_second = _get_cache_stats()
        cache_size_after_second = stats_after_second["size"]

        # Same size means cache hit
        assert cache_size_after_first == cache_size_after_second

    def test_cache_miss_on_new_path(self, tmp_path: Path) -> None:
        """Test that new paths trigger cache miss."""
        from path_validators import clear_path_cache

        # Clear cache
        clear_path_cache()

        initial_stats = _get_cache_stats()
        initial_size = initial_stats["size"]

        # Validate a new path
        test_path1 = tmp_path / "path1"
        test_path1.mkdir()
        _validate_path(test_path1, "path 1")

        stats_after_first = _get_cache_stats()
        size_after_first = stats_after_first["size"]

        # Cache should have grown
        assert size_after_first > initial_size

        # Validate another new path
        test_path2 = tmp_path / "path2"
        test_path2.mkdir()
        _validate_path(test_path2, "path 2")

        stats_after_second = _get_cache_stats()
        size_after_second = stats_after_second["size"]

        # Cache should have grown again
        assert size_after_second > size_after_first

    def test_cache_returns_false_for_nonexistent(self, tmp_path: Path) -> None:
        """Test that cache correctly caches False for non-existent paths."""
        from path_validators import clear_path_cache

        clear_path_cache()

        nonexistent = tmp_path / "nonexistent"

        # First check - returns False
        result1 = _validate_path(nonexistent, "nonexistent")
        assert result1 is False

        # Second check - should still return False (cached)
        result2 = _validate_path(nonexistent, "nonexistent")
        assert result2 is False


class TestPathCacheClearing:
    """Test path cache clearing behavior."""

    def test_clear_cache_empties_cache(self, tmp_path: Path) -> None:
        """Test that clear_path_cache empties the cache."""
        from path_validators import clear_path_cache

        # Populate cache
        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")

        stats_before = _get_cache_stats()
        assert stats_before["size"] > 0

        # Clear cache
        clear_path_cache()

        stats_after = _get_cache_stats()
        assert stats_after["size"] == 0

    def test_cache_refills_after_clear(self, tmp_path: Path) -> None:
        """Test that cache refills after being cleared."""
        from path_validators import clear_path_cache

        test_path = tmp_path / "test"
        test_path.mkdir()

        # Populate cache
        _validate_path(test_path, "test")
        clear_path_cache()

        # Validate again
        _validate_path(test_path, "test")

        stats_after = _get_cache_stats()
        assert stats_after["size"] > 0


class TestCachingEnabledDisabled:
    """Test enabling/disabling caching."""

    def test_caching_disabled_bypasses_cache(
        self, tmp_path: Path, caching_disabled: None
    ) -> None:
        """Test that caching_disabled fixture bypasses cache."""
        test_path = tmp_path / "test"
        test_path.mkdir()

        # Validate multiple times
        _validate_path(test_path, "test")
        _validate_path(test_path, "test")
        _validate_path(test_path, "test")

        # Cache should be empty because caching is disabled
        stats = _get_cache_stats()
        assert stats["size"] == 0

    def test_caching_enabled_uses_cache(
        self, tmp_path: Path, caching_enabled: Path
    ) -> None:
        """Test that caching_enabled fixture enables caching."""
        from path_validators import clear_path_cache

        clear_path_cache()

        test_path = tmp_path / "test"
        test_path.mkdir()

        # Validate path
        _validate_path(test_path, "test")

        # Cache should have entry
        stats = _get_cache_stats()
        assert stats["size"] > 0


class TestCacheManagerWithCaching:
    """Test CacheManager behavior with caching enabled."""

    def test_shots_cache_survives_clear_all_caches(
        self, isolated_cache_manager: CacheManager
    ) -> None:
        """Test that CacheManager shot data survives clear_all_caches.

        clear_all_caches() only clears path validation cache and version cache,
        not CacheManager's persistent JSON caches.
        """
        from utils import clear_all_caches

        manager = isolated_cache_manager

        # Cache some shot data
        shot_data = [{"show": "TEST", "sequence": "SQ010", "shot": "SH0010"}]
        manager.cache_shots(shot_data)

        # Clear utility caches (should NOT affect CacheManager)
        clear_all_caches()

        # Shot data should still be cached
        cached = manager.get_cached_shots()
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["shot"] == "SH0010"


class TestCacheIsolationContext:
    """Test CacheIsolation context manager."""

    def test_cache_isolation_clears_and_disables(self, tmp_path: Path) -> None:
        """Test that CacheIsolation clears cache and disables caching inside context.

        CacheIsolation provides a clean, cache-disabled environment:
        - Clears cache on entry
        - Disables caching inside context (validations don't cache)
        - Re-enables caching on exit (cache remains empty)
        """
        from utils import CacheIsolation

        test_path = tmp_path / "test"
        test_path.mkdir()

        # Populate cache
        _validate_path(test_path, "test")
        stats_before = _get_cache_stats()
        size_before = stats_before["size"]
        assert size_before > 0

        # Use isolation context
        with CacheIsolation():
            # Cache should be empty inside context
            stats_inside = _get_cache_stats()
            assert stats_inside["size"] == 0

            # Validations inside context should NOT populate cache
            # (caching is disabled inside CacheIsolation)
            another_path = tmp_path / "another"
            another_path.mkdir()
            _validate_path(another_path, "another")

            # Cache should still be empty (caching disabled)
            stats_inside_after = _get_cache_stats()
            assert stats_inside_after["size"] == 0

        # After context, cache should still be empty
        # (caching re-enabled but nothing cached inside)
        stats_after = _get_cache_stats()
        assert stats_after["size"] == 0

    def test_cache_isolation_reenables_caching_on_exit(self, tmp_path: Path) -> None:
        """Test that CacheIsolation re-enables caching after context exits."""
        from path_validators import clear_path_cache
        from utils import CacheIsolation

        clear_path_cache()

        # Use isolation context
        with CacheIsolation():
            pass  # Just enter and exit

        # After context, caching should be re-enabled
        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")

        # Cache should now work (caching re-enabled after context)
        stats = _get_cache_stats()
        assert stats["size"] > 0
