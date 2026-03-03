"""Tests for SceneDiskCache — 3DE scene disk persistence with incremental merge.

Covers:
- 3DE scene cache read/write
- Cache clear
- TTL management
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from cache.scene_cache_disk import SceneDiskCache
from config import Config


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scene_cache(tmp_path: Path) -> SceneDiskCache:
    """Create SceneDiskCache with temporary directory."""
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return SceneDiskCache(cache_dir)


# ---------------------------------------------------------------------------
# TestJSONCacheOperations (3DE scene paths)
# ---------------------------------------------------------------------------


class TestSceneCacheOperations:
    """Test 3DE scene JSON cache read/write operations."""

    def test_get_cached_threede_scenes_returns_data(
        self, scene_cache: SceneDiskCache
    ) -> None:
        """Test retrieving cached 3DE scenes."""
        scenes = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot010",
                "user": "artist1",
                "plate": "bg01",
                "scene_path": "/path/to/scene1.3de",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/seq01/shot010",
            },
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot020",
                "user": "artist2",
                "plate": "fg01",
                "scene_path": "/path/to/scene2.3de",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/seq01/shot020",
            },
        ]
        scene_cache.cache_threede_scenes(scenes)

        cached = scene_cache.get_cached_threede_scenes()

        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["show"] == "test_show"
        assert cached[0]["user"] == "artist1"

    def test_scene_cache_clear(self, scene_cache: SceneDiskCache) -> None:
        """Test clear_cache removes 3DE scene cache file."""
        scenes = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot010",
                "user": "artist1",
                "plate": "bg01",
                "scene_path": "/path/to/scene1.3de",
                "workspace_path": "/path",
            }
        ]
        scene_cache.cache_threede_scenes(scenes)
        assert scene_cache.threede_cache_file.exists()

        scene_cache.clear_cache()

        assert not scene_cache.threede_cache_file.exists()

    def test_set_expiry_minutes_changes_ttl(
        self, scene_cache: SceneDiskCache
    ) -> None:
        """Test set_expiry_minutes takes effect on subsequent TTL checks."""
        scenes = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot010",
                "user": "artist1",
                "plate": "bg01",
                "scene_path": "/path/to/scene1.3de",
                "workspace_path": "/path",
            }
        ]
        scene_cache.cache_threede_scenes(scenes)

        # Shorten TTL to 0 minutes (everything expires immediately)
        scene_cache.set_expiry_minutes(0)

        # With 0-minute TTL, cache should be expired
        cached = scene_cache.get_cached_threede_scenes()
        assert cached is None
