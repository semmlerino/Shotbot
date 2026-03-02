"""Integration tests verifying cache architecture seam correctness.

These tests verify that the cache refactoring (elimination of split-brain caches,
key discrimination, and TTL consistency) works correctly at the integration level.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from cache_manager import CacheManager
from filesystem_coordinator import FilesystemCoordinator
from filesystem_scanner import FileSystemScanner
from scene_discovery_coordinator import SceneDiscoveryCoordinator


@pytest.fixture
def clean_coordinator():
    """Provide a clean FilesystemCoordinator, cleaned up after the test."""
    # Reset any existing singleton
    FilesystemCoordinator.reset()
    coord = FilesystemCoordinator()
    yield coord
    FilesystemCoordinator.reset()


# =============================================================================
# Directory Cache Coherence
# =============================================================================


class TestDirectoryCacheCoherence:
    """Verify FileSystemScanner/ThreeDESceneFinder delegate to FilesystemCoordinator."""

    def test_clear_cache_clears_coordinator(self, clean_coordinator, tmp_path) -> None:
        """FileSystemScanner.clear_cache() clears the real coordinator cache."""
        # Populate the coordinator cache with a real directory
        test_dir = tmp_path / "shots" / "seq01"
        test_dir.mkdir(parents=True)
        (test_dir / "file1.3de").touch()
        (test_dir / "file2.3de").touch()

        # Read through coordinator to populate cache
        _ = clean_coordinator.get_directory_listing(test_dir)
        stats_before = clean_coordinator.get_cache_stats()
        assert stats_before["cached_directories"] >= 1

        # Clear via FileSystemScanner (the public API)
        count = FileSystemScanner.clear_cache()

        # Verify coordinator is actually cleared
        stats_after = clean_coordinator.get_cache_stats()
        assert stats_after["cached_directories"] == 0
        assert count >= 1

    def test_stats_reflect_coordinator(self, clean_coordinator, tmp_path) -> None:
        """FileSystemScanner.get_cache_stats() reflects coordinator state."""
        test_dir = tmp_path / "shots"
        test_dir.mkdir(parents=True)
        (test_dir / "file1.3de").touch()

        # First call populates cache (miss)
        _ = clean_coordinator.get_directory_listing(test_dir)
        # Second call hits cache
        _ = clean_coordinator.get_directory_listing(test_dir)

        stats = FileSystemScanner.get_cache_stats()
        assert stats["cache_hits"] >= 1
        assert stats["cached_directories"] >= 1


# =============================================================================
# Scene Discovery Single Cache
# =============================================================================


class TestSceneDiscoverySingleCache:
    """Verify strategy has no independent cache after refactoring."""

    def test_strategy_has_no_cache(self) -> None:
        """SceneDiscoveryCoordinator's strategy should not have a .cache attribute."""
        coordinator = SceneDiscoveryCoordinator(enable_caching=True)
        assert not hasattr(coordinator.strategy, "cache")

    def test_clear_cache_leaves_no_stale_data(self) -> None:
        """After coordinator.clear_cache(), re-discovery hits the filesystem."""
        coordinator = SceneDiscoveryCoordinator(enable_caching=True)

        # Mock the strategy to track calls
        mock_strategy = MagicMock()
        mock_strategy.find_scenes_for_shot.return_value = []
        mock_strategy.get_strategy_name.return_value = "mock"
        coordinator.strategy = mock_strategy

        # First call should miss cache and call strategy
        _ = coordinator.find_scenes_for_shot(
            "/workspace", "SHOW", "SEQ", "0010"
        )
        assert mock_strategy.find_scenes_for_shot.call_count == 1

        # Second call should hit cache (no additional strategy call)
        _ = coordinator.find_scenes_for_shot(
            "/workspace", "SHOW", "SEQ", "0010",
        )
        assert mock_strategy.find_scenes_for_shot.call_count == 1  # Still 1

        # Clear cache
        coordinator.clear_cache()

        # Third call should miss cache again and call strategy
        _ = coordinator.find_scenes_for_shot(
            "/workspace", "SHOW", "SEQ", "0010",
        )
        assert mock_strategy.find_scenes_for_shot.call_count == 2  # Now 2


# =============================================================================
# Latest File TTL Consistency
# =============================================================================


class TestLatestFileTTLConsistency:
    """Verify latest file cache respects TTL for all states."""

    def test_expired_not_found_becomes_miss(self, tmp_path) -> None:
        """A cached None result past TTL should return 'miss', not stale 'not_found'."""
        manager = CacheManager(cache_dir=tmp_path / "cache")

        # Cache a "not found" result
        manager.cache_latest_file("/workspace", "threede", None)

        # Verify it's "not_found" while fresh
        result = manager.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "not_found"

        # Manually expire by writing old timestamp
        cache_data = json.loads(manager.latest_files_cache_file.read_text())
        cache_data["/workspace:threede"]["cached_at"] = 0.0  # epoch = very old
        manager.latest_files_cache_file.write_text(json.dumps(cache_data))

        # Now should be "miss" (expired)
        result = manager.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "miss"

    def test_active_not_found_within_ttl(self, tmp_path) -> None:
        """A cached None result within TTL should return 'not_found'."""
        manager = CacheManager(cache_dir=tmp_path / "cache")

        # Cache a "not found" result
        manager.cache_latest_file("/workspace", "threede", None)

        # Check immediately (within TTL)
        result = manager.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "not_found"
        assert result.path is None
