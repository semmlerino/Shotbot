"""Integration tests for cache persistence and edge case handling.

These tests verify the cache system handles real-world edge cases correctly:
- Valid cache files are loaded successfully
- Corrupted/invalid JSON is handled gracefully
- Missing required fields are handled gracefully
- Permission errors are handled gracefully

All tests use @pytest.mark.persistent_cache to skip automatic cache clearing,
and the seed_cache_file fixture to pre-populate cache files with specific content.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from tests.fixtures.caching import SeedCacheFile

# Module-level markers
pytestmark = [
    pytest.mark.integration,
    pytest.mark.persistent_cache,  # Skip automatic cache clearing
    pytest.mark.legacy,
]


class TestValidCacheLoading:
    """Tests for loading valid cache files."""

    def test_loads_valid_shots_cache(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify valid shots.json is loaded correctly."""
        from cache_manager import CacheManager

        # Seed a valid shots cache (directly in cache_dir, not production/)
        # CacheManager expects shots.json at cache_dir/shots.json
        valid_cache = {
            "shots": [
                {
                    "show": "test_show",
                    "sequence": "sq010",
                    "shot": "sh0010",
                    "full_path": "/shows/test_show/shots/sq010/sh0010",
                }
            ],
        }
        seed_cache_file("shots.json", valid_cache, in_production=False)

        # Load cache
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_cached_shots()

            # Verify shots loaded
            assert shots is not None
            assert len(shots) == 1
            assert shots[0]["show"] == "test_show"
        finally:
            manager.shutdown()

    def test_loads_valid_previous_shots_cache(
        self, seed_cache_file: SeedCacheFile
    ) -> None:
        """Verify valid previous_shots.json is loaded correctly.

        Note: Previous shots cache is persistent (no TTL), so timestamp doesn't matter.
        """
        from cache_manager import CacheManager

        # Seed a valid previous shots cache (directly in cache_dir, not production/)
        valid_cache = [
            {
                "show": "prev_show",
                "sequence": "sq020",
                "shot": "sh0020",
            }
        ]
        seed_cache_file("previous_shots.json", valid_cache, in_production=False)

        # Load cache
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_persistent_previous_shots()

            # Verify shots loaded
            assert shots is not None
            assert len(shots) == 1
            assert shots[0]["show"] == "prev_show"
        finally:
            manager.shutdown()


class TestCorruptedCacheHandling:
    """Tests for handling corrupted/invalid cache files."""

    def test_handles_corrupted_json(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify corrupted JSON is handled gracefully without crashing."""
        from cache_manager import CacheManager

        # Seed a corrupted cache file (in root cache_dir, not production/)
        seed_cache_file.corrupt("shots.json", in_production=False)

        # Load cache - should not crash
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_cached_shots()

            # Should return None or empty list (not crash)
            assert shots is None or shots == []
        finally:
            manager.shutdown()

    def test_handles_truncated_json(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify truncated JSON (cut off mid-stream) is handled gracefully."""
        from cache_manager import CacheManager

        # Seed a truncated cache file (in root cache_dir, not production/)
        seed_cache_file.truncated("shots.json", in_production=False)

        # Load cache - should not crash
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_cached_shots()

            # Should return None or empty list (not crash)
            assert shots is None or shots == []
        finally:
            manager.shutdown()

    def test_handles_empty_file(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify empty cache file is handled gracefully."""
        from cache_manager import CacheManager

        # Seed an empty cache file (in root cache_dir, not production/)
        seed_cache_file.empty("shots.json", in_production=False)

        # Load cache - should not crash
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_cached_shots()

            # Should return None or empty list (not crash)
            assert shots is None or shots == []
        finally:
            manager.shutdown()


class TestMissingFieldsHandling:
    """Tests for handling cache files with missing required fields."""

    def test_handles_missing_shots_key(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify cache without 'shots' key is handled gracefully."""
        from cache_manager import CacheManager

        # Seed cache without 'shots' key (in root cache_dir, not production/)
        invalid_cache = {"timestamp": 1700000000.0}
        seed_cache_file("shots.json", invalid_cache, in_production=False)

        # Load cache - should not crash
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_cached_shots()

            # Should return None or empty list
            assert shots is None or shots == []
        finally:
            manager.shutdown()

    def test_handles_null_shots_value(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify cache with null shots value is handled gracefully."""
        from cache_manager import CacheManager

        # Seed cache with null shots (in root cache_dir, not production/)
        invalid_cache = {"shots": None, "timestamp": 1700000000.0}
        seed_cache_file("shots.json", invalid_cache, in_production=False)

        # Load cache - should not crash
        manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
        try:
            shots = manager.get_cached_shots()

            # Should return None or empty list
            assert shots is None or shots == []
        finally:
            manager.shutdown()


class TestPermissionErrorHandling:
    """Tests for handling permission errors on cache files."""

    @pytest.mark.skipif(
        Path("/").stat().st_uid == 0,
        reason="Cannot test permission errors as root",
    )
    def test_handles_unreadable_file(self, seed_cache_file: SeedCacheFile) -> None:
        """Verify unreadable cache file is handled gracefully."""

        from cache_manager import CacheManager

        # Seed a valid cache file (in root cache_dir, not production/)
        cache_path = seed_cache_file(
            "shots.json", {"shots": [], "timestamp": 1700000000.0}, in_production=False
        )

        # Make it unreadable
        original_mode = cache_path.stat().st_mode
        try:
            cache_path.chmod(0o000)

            # Load cache - should not crash
            manager = CacheManager(cache_dir=seed_cache_file.cache_dir)
            try:
                shots = manager.get_cached_shots()

                # Should return None (permission denied)
                assert shots is None or shots == []
            finally:
                manager.shutdown()
        finally:
            # Restore permissions for cleanup
            cache_path.chmod(original_mode)
