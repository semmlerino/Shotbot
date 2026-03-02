"""Tests for SceneCache TTL-based caching with LRU eviction.

Tests cover:
- SceneCacheEntry: TTL expiration, validity, access statistics
- SceneCache: CRUD operations, TTL, LRU eviction, invalidation
- Thread safety for concurrent access
- Cache statistics and monitoring
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from scene_cache import SceneCache, SceneCacheEntry


# ==============================================================================
# Test Fixtures and Helpers
# ==============================================================================


@dataclass
class MockThreeDEScene:
    """Minimal mock of ThreeDEScene for cache testing."""

    show: str
    sequence: str
    shot: str
    user: str
    scene_path: Path
    modified_time: float = 0.0

    # Class variable to track instance creation
    _instance_count: ClassVar[int] = 0

    def __post_init__(self) -> None:
        MockThreeDEScene._instance_count += 1


@pytest.fixture
def mock_scene() -> MockThreeDEScene:
    """Create a single mock scene."""
    return MockThreeDEScene(
        show="testshow",
        sequence="seq01",
        shot="0010",
        user="artist1",
        scene_path=Path("/shows/testshow/shots/seq01/seq01_0010/user/artist1/scene.3de"),
        modified_time=time.time(),
    )


@pytest.fixture
def mock_scenes() -> list[MockThreeDEScene]:
    """Create a list of mock scenes."""
    return [
        MockThreeDEScene(
            show="testshow",
            sequence="seq01",
            shot=f"00{i}0",
            user="artist1",
            scene_path=Path(f"/shows/testshow/shots/seq01/seq01_00{i}0/scene.3de"),
            modified_time=time.time(),
        )
        for i in range(1, 4)
    ]


@pytest.fixture
def cache() -> SceneCache:
    """Create a fresh SceneCache instance."""
    return SceneCache(default_ttl=60, max_entries=100)


@pytest.fixture
def mock_time(monkeypatch: pytest.MonkeyPatch):
    """Fixture to control time.time() for TTL testing."""
    current_time = [time.time()]

    def get_time() -> float:
        return current_time[0]

    def advance(seconds: float) -> None:
        current_time[0] += seconds

    def set_time(new_time: float) -> None:
        current_time[0] = new_time

    monkeypatch.setattr("time.time", get_time)
    monkeypatch.setattr("scene_cache.time.time", get_time)

    return type(
        "MockTime",
        (),
        {"advance": staticmethod(advance), "get": staticmethod(get_time), "set": staticmethod(set_time)},
    )()


# ==============================================================================
# SceneCacheEntry Tests
# ==============================================================================


class TestSceneCacheEntry:
    """Tests for SceneCacheEntry TTL and access tracking."""

    def test_is_expired_false_within_ttl(self, mock_scenes: list[MockThreeDEScene]) -> None:
        """Entry is not expired within TTL window."""
        entry = SceneCacheEntry(
            scenes=mock_scenes,  # type: ignore[arg-type]
            timestamp=time.time(),
            ttl_seconds=60,
        )
        assert not entry.is_expired()

    def test_is_expired_true_after_ttl(
        self,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """Entry expires after TTL seconds."""
        entry = SceneCacheEntry(
            scenes=mock_scenes,  # type: ignore[arg-type]
            timestamp=mock_time.get(),  # type: ignore[attr-defined]
            ttl_seconds=60,
        )

        assert not entry.is_expired()

        # Advance time past TTL
        mock_time.advance(61)  # type: ignore[attr-defined]

        assert entry.is_expired()

    def test_is_valid_inverse_of_is_expired(
        self,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """is_valid() returns opposite of is_expired()."""
        entry = SceneCacheEntry(
            scenes=mock_scenes,  # type: ignore[arg-type]
            timestamp=mock_time.get(),  # type: ignore[attr-defined]
            ttl_seconds=30,
        )

        assert entry.is_valid()
        assert not entry.is_expired()

        mock_time.advance(31)  # type: ignore[attr-defined]

        assert not entry.is_valid()
        assert entry.is_expired()

    def test_touch_updates_access_stats(
        self,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """touch() increments access_count and updates last_access."""
        initial_time = mock_time.get()  # type: ignore[attr-defined]
        entry = SceneCacheEntry(
            scenes=mock_scenes,  # type: ignore[arg-type]
            timestamp=initial_time,
            ttl_seconds=60,
        )

        assert entry.access_count == 0
        assert entry.last_access == initial_time

        mock_time.advance(10)  # type: ignore[attr-defined]
        entry.touch()

        assert entry.access_count == 1
        assert entry.last_access > initial_time

        mock_time.advance(5)  # type: ignore[attr-defined]
        entry.touch()

        assert entry.access_count == 2

    def test_age_seconds_calculated_correctly(
        self,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """age_seconds() returns correct elapsed time."""
        entry = SceneCacheEntry(
            scenes=mock_scenes,  # type: ignore[arg-type]
            timestamp=mock_time.get(),  # type: ignore[attr-defined]
            ttl_seconds=60,
        )

        assert entry.age_seconds() == pytest.approx(0, abs=0.1)

        mock_time.advance(30)  # type: ignore[attr-defined]
        assert entry.age_seconds() == pytest.approx(30, abs=0.1)


# ==============================================================================
# SceneCache Basic Operations Tests
# ==============================================================================


class TestSceneCacheBasicOperations:
    """Tests for basic cache CRUD operations."""

    def test_cache_and_retrieve_shot_scenes(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Scenes can be cached and retrieved for a shot."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        result = cache.get_scenes_for_shot("show1", "seq01", "0010")

        assert result is not None
        assert len(result) == len(mock_scenes)

    def test_cache_returns_copy_not_reference(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Retrieved list is a copy, not the original reference."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        result1 = cache.get_scenes_for_shot("show1", "seq01", "0010")
        result2 = cache.get_scenes_for_shot("show1", "seq01", "0010")

        assert result1 is not result2  # Different list objects
        assert result1 is not mock_scenes  # Not the original

    def test_cache_miss_returns_none(self, cache: SceneCache) -> None:
        """Non-existent key returns None."""
        result = cache.get_scenes_for_shot("nonexistent", "seq", "shot")
        assert result is None

    def test_cache_scenes_for_show(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Scenes can be cached at show level."""
        cache.cache_scenes_for_show("show1", mock_scenes)  # type: ignore[arg-type]

        result = cache.get_scenes_for_show("show1")

        assert result is not None
        assert len(result) == len(mock_scenes)

    def test_make_shot_key_formats_correctly(self, cache: SceneCache) -> None:
        """_make_shot_key creates correct key format."""
        assert cache._make_shot_key("show", "seq", "shot") == "show/seq/shot"
        assert (
            cache._make_shot_key("show", "seq", "shot", shot_workspace_path="/ws/a")
            == "show/seq/shot:/ws/a:"
        )
        assert (
            cache._make_shot_key(
                "show", "seq", "shot", excluded_users=frozenset({"b", "a"})
            )
            == "show/seq/shot::a,b"
        )
        assert (
            cache._make_shot_key(
                "show", "seq", "shot",
                shot_workspace_path="/ws/a",
                excluded_users=frozenset({"x"}),
            )
            == "show/seq/shot:/ws/a:x"
        )

    def test_make_show_key_formats_correctly(self, cache: SceneCache) -> None:
        """_make_show_key creates correct key format."""
        assert cache._make_show_key("show") == "show"
        assert cache._make_show_key("show", show_root="/root") == "show:/root:"
        assert (
            cache._make_show_key("show", excluded_users=frozenset({"b", "a"}))
            == "show::a,b"
        )


# ==============================================================================
# TTL Expiration Tests
# ==============================================================================


class TestSceneCacheTTL:
    """Tests for TTL-based cache expiration."""

    def test_expired_entry_returns_none(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """Expired cache entry returns None on get."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        # Within TTL
        result = cache.get_scenes_for_shot("show1", "seq01", "0010")
        assert result is not None

        # Expire the entry
        mock_time.advance(cache.default_ttl + 1)  # type: ignore[attr-defined]

        result = cache.get_scenes_for_shot("show1", "seq01", "0010")
        assert result is None

    def test_expired_entry_removed_on_access(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """Expired entries are removed from cache on access."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]
        assert len(cache.cache) == 1

        mock_time.advance(cache.default_ttl + 1)  # type: ignore[attr-defined]

        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")

        assert len(cache.cache) == 0

    def test_custom_ttl_per_entry(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """Custom TTL can be specified per entry."""
        # Cache with custom short TTL
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes, ttl=10)  # type: ignore[arg-type]

        mock_time.advance(5)  # type: ignore[attr-defined]
        assert cache.get_scenes_for_shot("show1", "seq01", "0010") is not None

        mock_time.advance(6)  # type: ignore[attr-defined]  # Total 11 seconds
        assert cache.get_scenes_for_shot("show1", "seq01", "0010") is None

    def test_cleanup_expired_removes_all_expired(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """cleanup_expired() removes all expired entries."""
        # Add multiple entries
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show1", "seq01", "0020", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show1", "seq01", "0030", mock_scenes)  # type: ignore[arg-type]

        assert len(cache.cache) == 3

        # Expire all
        mock_time.advance(cache.default_ttl + 1)  # type: ignore[attr-defined]

        removed = cache.cleanup_expired()

        assert removed == 3
        assert len(cache.cache) == 0


# ==============================================================================
# LRU Eviction Tests
# ==============================================================================


class TestSceneCacheLRU:
    """Tests for LRU eviction when cache is full."""

    def test_evict_lru_when_at_max_entries(
        self,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """LRU entry evicted when cache reaches max_entries."""
        cache = SceneCache(default_ttl=60, max_entries=3)

        cache.cache_scenes_for_shot("show", "seq", "shot1", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show", "seq", "shot2", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show", "seq", "shot3", mock_scenes)  # type: ignore[arg-type]

        assert len(cache.cache) == 3

        # Adding 4th entry should evict LRU
        cache.cache_scenes_for_shot("show", "seq", "shot4", mock_scenes)  # type: ignore[arg-type]

        assert len(cache.cache) == 3  # Still at max

    def test_lru_evicts_least_recently_accessed(
        self,
        mock_scenes: list[MockThreeDEScene],
        mock_time: object,
    ) -> None:
        """LRU eviction removes least recently accessed entry."""
        cache = SceneCache(default_ttl=60, max_entries=3)

        # Add entries with staggered times
        cache.cache_scenes_for_shot("show", "seq", "shot1", mock_scenes)  # type: ignore[arg-type]
        mock_time.advance(1)  # type: ignore[attr-defined]

        cache.cache_scenes_for_shot("show", "seq", "shot2", mock_scenes)  # type: ignore[arg-type]
        mock_time.advance(1)  # type: ignore[attr-defined]

        cache.cache_scenes_for_shot("show", "seq", "shot3", mock_scenes)  # type: ignore[arg-type]
        mock_time.advance(1)  # type: ignore[attr-defined]

        # Touch shot1 and shot3 to update access time
        _ = cache.get_scenes_for_shot("show", "seq", "shot1")
        mock_time.advance(1)  # type: ignore[attr-defined]
        _ = cache.get_scenes_for_shot("show", "seq", "shot3")

        # shot2 is now LRU (oldest last_access)

        # Add 4th entry
        cache.cache_scenes_for_shot("show", "seq", "shot4", mock_scenes)  # type: ignore[arg-type]

        # shot2 should be evicted
        assert cache.get_scenes_for_shot("show", "seq", "shot1") is not None
        assert cache.get_scenes_for_shot("show", "seq", "shot2") is None  # Evicted
        assert cache.get_scenes_for_shot("show", "seq", "shot3") is not None


# ==============================================================================
# Invalidation Tests
# ==============================================================================


class TestSceneCacheInvalidation:
    """Tests for cache invalidation."""

    def test_invalidate_shot_removes_entry(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """invalidate_shot() removes specific entry."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        result = cache.invalidate_shot("show1", "seq01", "0010")

        assert result is True
        assert cache.get_scenes_for_shot("show1", "seq01", "0010") is None

    def test_invalidate_shot_returns_false_if_not_found(
        self,
        cache: SceneCache,
    ) -> None:
        """invalidate_shot() returns False if entry doesn't exist."""
        result = cache.invalidate_shot("nonexistent", "seq", "shot")
        assert result is False

    def test_invalidate_show_removes_all_related(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """invalidate_show() removes all entries for that show."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show1", "seq01", "0020", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show1", "seq02", "0010", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show2", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        count = cache.invalidate_show("show1")

        assert count == 3
        assert cache.get_scenes_for_shot("show1", "seq01", "0010") is None
        assert cache.get_scenes_for_shot("show1", "seq01", "0020") is None
        assert cache.get_scenes_for_shot("show1", "seq02", "0010") is None
        # show2 should still be cached
        assert cache.get_scenes_for_shot("show2", "seq01", "0010") is not None

    def test_clear_cache_removes_all_entries(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """clear_cache() removes all entries."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show2", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        count = cache.clear_cache()

        assert count == 2
        assert len(cache.cache) == 0


# ==============================================================================
# Cache Statistics Tests
# ==============================================================================


class TestSceneCacheStatistics:
    """Tests for cache statistics tracking."""

    def test_stats_track_hits_and_misses(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Statistics track cache hits and misses."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        # Generate hits
        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")
        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")

        # Generate misses
        _ = cache.get_scenes_for_shot("nonexistent", "seq", "shot")
        _ = cache.get_scenes_for_shot("also_nonexistent", "seq", "shot")

        stats = cache.get_cache_stats()

        assert stats["hits"] == 2
        assert stats["misses"] == 2

    def test_hit_rate_calculation_correct(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Hit rate percentage calculated correctly."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        # 3 hits
        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")
        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")
        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")

        # 1 miss
        _ = cache.get_scenes_for_shot("nonexistent", "seq", "shot")

        stats = cache.get_cache_stats()

        assert stats["hit_rate_percent"] == 75.0  # 3/4 = 75%

    def test_stats_no_division_by_zero(self, cache: SceneCache) -> None:
        """Empty cache doesn't cause division by zero in stats."""
        stats = cache.get_cache_stats()

        assert stats["hit_rate_percent"] == 0.0
        assert stats["total_entries"] == 0

    def test_get_cache_stats_includes_all_fields(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """get_cache_stats() returns all expected fields."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        stats = cache.get_cache_stats()

        assert "total_entries" in stats
        assert "total_scenes_cached" in stats
        assert "hit_rate_percent" in stats
        assert "average_age_seconds" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "evictions" in stats
        assert "invalidations" in stats


# ==============================================================================
# Cache Warming Tests
# ==============================================================================


class TestSceneCacheWarming:
    """Tests for cache warming functionality."""

    def test_warm_cache_populates_entry(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """warm_cache() populates cache with warmer results."""
        # Create warmer function
        def warmer(show: str, seq: str, shot: str) -> list[MockThreeDEScene]:
            return mock_scenes

        cache.warm_cache(warmer, "show1", "seq01", "0010")  # type: ignore[arg-type]

        result = cache.get_scenes_for_shot("show1", "seq01", "0010")
        assert result is not None
        assert len(result) == len(mock_scenes)

    def test_warm_cache_handles_warmer_error(self, cache: SceneCache) -> None:
        """warm_cache() handles exceptions in warmer function."""

        def failing_warmer(show: str, seq: str, shot: str) -> list[MockThreeDEScene]:
            raise RuntimeError("Discovery failed")

        # Should not raise
        cache.warm_cache(failing_warmer, "show1", "seq01", "0010")  # type: ignore[arg-type]

        # Entry should not be cached
        result = cache.get_scenes_for_shot("show1", "seq01", "0010")
        assert result is None

    def test_warm_cache_increments_stats(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """warm_cache() increments cache_warmings stat."""

        def warmer(show: str, seq: str, shot: str) -> list[MockThreeDEScene]:
            return mock_scenes

        cache.warm_cache(warmer, "show1", "seq01", "0010")  # type: ignore[arg-type]

        stats = cache.get_cache_stats()
        assert stats["cache_warmings"] == 1


# ==============================================================================
# Thread Safety Tests
# ==============================================================================


class TestSceneCacheThreadSafety:
    """Tests for thread-safe cache operations."""

    def test_concurrent_reads_safe(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Concurrent read operations are thread-safe."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        results: queue.Queue[list[MockThreeDEScene] | None] = queue.Queue()
        errors: queue.Queue[Exception] = queue.Queue()

        def read_cache() -> None:
            try:
                for _ in range(100):
                    result = cache.get_scenes_for_shot("show1", "seq01", "0010")
                    results.put(result)
            except Exception as e:
                errors.put(e)

        threads = [threading.Thread(target=read_cache) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert errors.empty()

        # All reads successful
        collected = []
        while not results.empty():
            collected.append(results.get())
        assert len(collected) == 500  # 5 threads * 100 reads
        assert all(r is not None for r in collected)

    def test_concurrent_writes_safe(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Concurrent write operations are thread-safe."""
        errors: queue.Queue[Exception] = queue.Queue()

        def write_cache(thread_id: int) -> None:
            try:
                for i in range(50):
                    cache.cache_scenes_for_shot(
                        f"show{thread_id}",
                        "seq01",
                        f"shot{i}",
                        mock_scenes,  # type: ignore[arg-type]
                    )
            except Exception as e:
                errors.put(e)

        threads = [threading.Thread(target=write_cache, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert errors.empty()

        # Verify some writes succeeded
        assert len(cache.cache) > 0

    def test_concurrent_read_write_safe(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """Mixed concurrent read/write operations are thread-safe."""
        # Pre-populate some entries
        for i in range(10):
            cache.cache_scenes_for_shot("show", "seq", f"shot{i}", mock_scenes)  # type: ignore[arg-type]

        errors: queue.Queue[Exception] = queue.Queue()

        def reader() -> None:
            try:
                for i in range(100):
                    _ = cache.get_scenes_for_shot("show", "seq", f"shot{i % 10}")
            except Exception as e:
                errors.put(e)

        def writer() -> None:
            try:
                for i in range(100):
                    cache.cache_scenes_for_shot("show", "seq", f"new_shot{i}", mock_scenes)  # type: ignore[arg-type]
            except Exception as e:
                errors.put(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert errors.empty()


# ==============================================================================
# Utility Method Tests
# ==============================================================================


class TestSceneCacheUtilities:
    """Tests for cache utility methods."""

    def test_get_cache_keys_returns_all_keys(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """get_cache_keys() returns all current cache keys."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]
        cache.cache_scenes_for_shot("show2", "seq02", "0020", mock_scenes)  # type: ignore[arg-type]

        keys = cache.get_cache_keys()

        assert len(keys) == 2
        assert "show1/seq01/0010" in keys
        assert "show2/seq02/0020" in keys

    def test_get_cache_info_returns_entry_details(
        self,
        cache: SceneCache,
        mock_scenes: list[MockThreeDEScene],
    ) -> None:
        """get_cache_info() returns detailed entry information."""
        cache.cache_scenes_for_shot("show1", "seq01", "0010", mock_scenes)  # type: ignore[arg-type]

        # Access to update stats
        _ = cache.get_scenes_for_shot("show1", "seq01", "0010")

        info = cache.get_cache_info("show1/seq01/0010")

        assert info is not None
        assert info["scene_count"] == len(mock_scenes)
        assert info["access_count"] == 1
        assert info["is_expired"] is False
        assert "age_seconds" in info
        assert "ttl_seconds" in info

    def test_get_cache_info_returns_none_for_missing(
        self,
        cache: SceneCache,
    ) -> None:
        """get_cache_info() returns None for non-existent key."""
        info = cache.get_cache_info("nonexistent")
        assert info is None


# ==============================================================================
# Key Discrimination Tests
# ==============================================================================


def create_mock_scene(show: str, sequence: str, shot: str, user: str) -> MockThreeDEScene:
    """Create a MockThreeDEScene with the given attributes."""
    return MockThreeDEScene(
        show=show,
        sequence=sequence,
        shot=shot,
        user=user,
        scene_path=Path(f"/shows/{show}/shots/{sequence}/{sequence}_{shot}/{user}/scene.3de"),
        modified_time=time.time(),
    )


class TestSceneCacheKeyDiscrimination:
    """Test that cache keys discriminate on all inputs that affect results."""

    def test_same_shot_different_workspace_different_entries(self) -> None:
        """Same shot with different workspace paths should yield different cache entries."""
        cache = SceneCache(default_ttl=300)
        scene_a = create_mock_scene("show", "seq", "shot", "userA")
        scene_b = create_mock_scene("show", "seq", "shot", "userB")

        cache.cache_scenes_for_shot(
            "show", "seq", "shot", [scene_a],  # type: ignore[list-item]
            shot_workspace_path="/workspace/a",
        )
        cache.cache_scenes_for_shot(
            "show", "seq", "shot", [scene_b],  # type: ignore[list-item]
            shot_workspace_path="/workspace/b",
        )

        result_a = cache.get_scenes_for_shot(
            "show", "seq", "shot", shot_workspace_path="/workspace/a"
        )
        result_b = cache.get_scenes_for_shot(
            "show", "seq", "shot", shot_workspace_path="/workspace/b"
        )

        assert result_a is not None
        assert result_b is not None
        assert len(result_a) == 1
        assert len(result_b) == 1
        assert result_a[0].user == "userA"  # type: ignore[union-attr]
        assert result_b[0].user == "userB"  # type: ignore[union-attr]

    def test_same_show_different_exclusions_different_entries(self) -> None:
        """Same show with different excluded users should yield different cache entries."""
        cache = SceneCache(default_ttl=300)
        scene_all = create_mock_scene("show", "seq", "shot", "userA")
        scene_filtered = create_mock_scene("show", "seq", "shot", "userB")

        cache.cache_scenes_for_show(
            "show", [scene_all],  # type: ignore[list-item]
            excluded_users=frozenset({"admin"}),
        )
        cache.cache_scenes_for_show(
            "show", [scene_filtered],  # type: ignore[list-item]
            excluded_users=frozenset({"admin", "bot"}),
        )

        result_admin = cache.get_scenes_for_show(
            "show", excluded_users=frozenset({"admin"})
        )
        result_both = cache.get_scenes_for_show(
            "show", excluded_users=frozenset({"admin", "bot"})
        )

        assert result_admin is not None
        assert result_both is not None
        assert result_admin[0].user == "userA"  # type: ignore[union-attr]
        assert result_both[0].user == "userB"  # type: ignore[union-attr]

    def test_same_inputs_cache_hit(self) -> None:
        """Same inputs should produce a cache hit."""
        cache = SceneCache(default_ttl=300)
        scene = create_mock_scene("show", "seq", "shot", "userA")

        cache.cache_scenes_for_shot(
            "show", "seq", "shot", [scene],  # type: ignore[list-item]
            shot_workspace_path="/workspace/a",
        )

        result = cache.get_scenes_for_shot(
            "show", "seq", "shot", shot_workspace_path="/workspace/a"
        )
        assert result is not None
        assert len(result) == 1

        # Verify stats show a hit
        stats = cache.get_cache_stats()
        assert stats["hits"] >= 1

    def test_same_shot_different_exclusions_different_entries(self) -> None:
        """Same shot with different excluded users should yield different cache entries."""
        cache = SceneCache(default_ttl=300)
        scene_a = create_mock_scene("show", "seq", "shot", "userA")
        scene_b = create_mock_scene("show", "seq", "shot", "userB")

        cache.cache_scenes_for_shot(
            "show", "seq", "shot", [scene_a],  # type: ignore[list-item]
            excluded_users=frozenset({"admin"}),
        )
        cache.cache_scenes_for_shot(
            "show", "seq", "shot", [scene_b],  # type: ignore[list-item]
            excluded_users=frozenset({"admin", "bot"}),
        )

        result_a = cache.get_scenes_for_shot(
            "show", "seq", "shot", excluded_users=frozenset({"admin"})
        )
        result_b = cache.get_scenes_for_shot(
            "show", "seq", "shot", excluded_users=frozenset({"admin", "bot"})
        )

        assert result_a is not None
        assert result_b is not None
        assert len(result_a) == 1
        assert len(result_b) == 1
        assert result_a[0].user == "userA"  # type: ignore[union-attr]
        assert result_b[0].user == "userB"  # type: ignore[union-attr]
