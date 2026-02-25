"""SceneCache module - Scene-level caching for 3DE scene discovery

This module provides high-level caching for ThreeDEScene objects and discovery results,
complementing the filesystem-level DirectoryCache. Includes TTL-based expiration,
invalidation strategies, and cache warming capabilities.

Part of the Phase 2 refactoring to break down the monolithic scene finder.
"""
# pyright: reportImportCycles=false
# Import cycle: scene_cache → threede_scene_model → threede_scene_finder → threede_scene_finder_optimized
# → scene_discovery_coordinator → scene_cache (and similar chains through scene_discovery_strategy)
# Broken at runtime by lazy imports in scene_discovery_coordinator.__init__() and scene_discovery_strategy.__init__()

from __future__ import annotations

# Standard library imports
import threading
import time
from typing import TYPE_CHECKING, final

# Local application imports
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable

    # Local application imports
    from threede_scene_model import ThreeDEScene


@final
class SceneCacheEntry:
    """Individual cache entry for scene discovery results."""

    def __init__(
        self,
        scenes: list[ThreeDEScene],
        timestamp: float,
        ttl_seconds: int = 1800,  # 30 minutes default
    ) -> None:
        """Initialize cache entry.

        Args:
            scenes: List of discovered scenes
            timestamp: Creation timestamp
            ttl_seconds: Time-to-live in seconds

        """
        super().__init__()
        self.scenes = scenes
        self.timestamp = timestamp
        self.ttl_seconds = ttl_seconds
        self.access_count = 0
        self.last_access = timestamp

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.timestamp > self.ttl_seconds

    def is_valid(self) -> bool:
        """Check if cache entry is still valid (not expired)."""
        return not self.is_expired()

    def touch(self) -> None:
        """Update access statistics."""
        self.access_count += 1
        self.last_access = time.time()

    def age_seconds(self) -> float:
        """Get age of cache entry in seconds."""
        return time.time() - self.timestamp


@final
class SceneCache(LoggingMixin):
    """High-level cache for scene discovery results with TTL and invalidation.

    This cache stores complete scene discovery results at the shot/show level,
    providing faster retrieval for repeated queries and reducing filesystem I/O.
    """

    def __init__(self, default_ttl: int = 1800, max_entries: int = 1000) -> None:
        """Initialize scene cache.

        Args:
            default_ttl: Default TTL for cache entries in seconds (30 min)
            max_entries: Maximum number of cache entries before LRU eviction

        """
        super().__init__()
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self.cache: dict[str, SceneCacheEntry] = {}
        self.lock = threading.RLock()

        # Statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "invalidations": 0,
            "cache_warmings": 0,
        }

    def _make_key(
        self, show: str, sequence: str | None = None, shot: str | None = None
    ) -> str:
        """Create cache key from shot components.

        Args:
            show: Show name
            sequence: Sequence name (optional for show-level caching)
            shot: Shot name (optional for sequence-level caching)

        Returns:
            Cache key string

        """
        if shot and sequence:
            return f"{show}/{sequence}/{shot}"
        if sequence:
            return f"{show}/{sequence}"
        return show

    def get_scenes_for_shot(
        self, show: str, sequence: str, shot: str
    ) -> list[ThreeDEScene] | None:
        """Get cached scenes for a specific shot.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            List of scenes if cached and valid, None otherwise

        """
        key = self._make_key(show, sequence, shot)

        with self.lock:
            entry = self.cache.get(key)
            if entry and entry.is_valid():
                entry.touch()
                self.stats["hits"] += 1
                self.logger.debug(f"Cache hit for {key}: {len(entry.scenes)} scenes")
                return entry.scenes.copy()

            if entry and entry.is_expired():
                # Remove expired entry
                del self.cache[key]
                self.stats["evictions"] += 1
                self.logger.debug(f"Removed expired cache entry for {key}")

            self.stats["misses"] += 1
            return None

    def get_scenes_for_show(self, show: str) -> list[ThreeDEScene] | None:
        """Get cached scenes for an entire show.

        Args:
            show: Show name

        Returns:
            List of all scenes in show if cached and valid, None otherwise

        """
        key = self._make_key(show)

        with self.lock:
            entry = self.cache.get(key)
            if entry and entry.is_valid():
                entry.touch()
                self.stats["hits"] += 1
                self.logger.debug(
                    f"Cache hit for show {key}: {len(entry.scenes)} scenes"
                )
                return entry.scenes.copy()

            if entry and entry.is_expired():
                del self.cache[key]
                self.stats["evictions"] += 1
                self.logger.debug(f"Removed expired show cache entry for {key}")

            self.stats["misses"] += 1
            return None

    def cache_scenes_for_shot(
        self,
        show: str,
        sequence: str,
        shot: str,
        scenes: list[ThreeDEScene],
        ttl: int | None = None,
    ) -> None:
        """Cache scenes for a specific shot.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name
            scenes: List of scenes to cache
            ttl: Custom TTL in seconds (uses default if None)

        """
        key = self._make_key(show, sequence, shot)
        ttl = ttl or self.default_ttl

        with self.lock:
            # Check if we need to evict entries
            if len(self.cache) >= self.max_entries:
                self._evict_lru()

            entry = SceneCacheEntry(scenes.copy(), time.time(), ttl)
            self.cache[key] = entry

            self.logger.debug(f"Cached {len(scenes)} scenes for {key} (TTL: {ttl}s)")

    def cache_scenes_for_show(
        self, show: str, scenes: list[ThreeDEScene], ttl: int | None = None
    ) -> None:
        """Cache scenes for an entire show.

        Args:
            show: Show name
            scenes: List of all scenes in show
            ttl: Custom TTL in seconds (uses default if None)

        """
        key = self._make_key(show)
        ttl = ttl or self.default_ttl

        with self.lock:
            # Check if we need to evict entries
            if len(self.cache) >= self.max_entries:
                self._evict_lru()

            entry = SceneCacheEntry(scenes.copy(), time.time(), ttl)
            self.cache[key] = entry

            self.logger.debug(
                f"Cached {len(scenes)} scenes for show {key} (TTL: {ttl}s)"
            )

    def invalidate_shot(self, show: str, sequence: str, shot: str) -> bool:
        """Invalidate cached scenes for a specific shot.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            True if entry was invalidated, False if not found

        """
        key = self._make_key(show, sequence, shot)

        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.stats["invalidations"] += 1
                self.logger.debug(f"Invalidated cache for {key}")
                return True
            return False

    def invalidate_show(self, show: str) -> int:
        """Invalidate all cached scenes for a show.

        Args:
            show: Show name

        Returns:
            Number of entries invalidated

        """
        invalidated = 0

        with self.lock:
            # Find all keys that start with the show name
            keys_to_remove = [
                key for key in self.cache if key.startswith(f"{show}/") or key == show
            ]

            for key in keys_to_remove:
                del self.cache[key]
                invalidated += 1

            self.stats["invalidations"] += invalidated
            self.logger.debug(
                f"Invalidated {invalidated} cache entries for show {show}"
            )

        return invalidated

    def warm_cache(
        self,
        cache_warmer: Callable[[str, str, str], list[ThreeDEScene]],
        show: str,
        sequence: str | None = None,
        shot: str | None = None,
    ) -> None:
        """Pre-populate cache with scenes using provided warmer function.

        Args:
            cache_warmer: Function that discovers scenes for given shot
            show: Show name
            sequence: Sequence name (optional)
            shot: Shot name (optional)

        """
        try:
            if shot and sequence:
                # Warm specific shot
                scenes = cache_warmer(show, sequence, shot)
                self.cache_scenes_for_shot(show, sequence, shot, scenes)
                self.stats["cache_warmings"] += 1
                self.logger.info(
                    f"Warmed cache for {show}/{sequence}/{shot}: {len(scenes)} scenes"
                )
            else:
                self.logger.warning("Cache warming requires both sequence and shot")

        except Exception as e:
            self.logger.error(f"Error warming cache for {show}/{sequence}/{shot}: {e}")

    def _evict_lru(self) -> None:
        """Evict least recently used entries when cache is full."""
        if not self.cache:
            return

        # Find LRU entry
        lru_key = min(self.cache.keys(), key=lambda k: self.cache[k].last_access)
        del self.cache[lru_key]
        self.stats["evictions"] += 1
        self.logger.debug(f"Evicted LRU cache entry: {lru_key}")

    def cleanup_expired(self) -> int:
        """Remove all expired entries from cache.

        Returns:
            Number of entries removed

        """
        removed = 0

        with self.lock:
            expired_keys = [
                key for key, entry in self.cache.items() if entry.is_expired()
            ]

            for key in expired_keys:
                del self.cache[key]
                removed += 1

            self.stats["evictions"] += removed

        if removed > 0:
            self.logger.debug(f"Cleaned up {removed} expired cache entries")

        return removed

    def get_cache_stats(self) -> dict[str, int | float]:
        """Get comprehensive cache statistics.

        Returns:
            Dictionary with cache statistics

        """
        with self.lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = (
                (self.stats["hits"] / total_requests * 100)
                if total_requests > 0
                else 0.0
            )

            # Calculate memory usage estimate
            total_scenes = sum(len(entry.scenes) for entry in self.cache.values())

            # Get age distribution
            current_time = time.time()
            ages = [current_time - entry.timestamp for entry in self.cache.values()]
            avg_age = sum(ages) / len(ages) if ages else 0.0

            return {
                "total_entries": len(self.cache),
                "total_scenes_cached": total_scenes,
                "hit_rate_percent": round(hit_rate, 1),
                "average_age_seconds": round(avg_age, 1),
                **self.stats,
            }

    def clear_cache(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared

        """
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            self.stats["evictions"] += count

        self.logger.info(f"Cleared all cache entries: {count}")
        return count

    def get_cache_keys(self) -> list[str]:
        """Get all cache keys for debugging.

        Returns:
            List of cache keys

        """
        with self.lock:
            return list(self.cache.keys())

    def get_cache_info(self, key: str) -> dict[str, float | int] | None:
        """Get detailed information about a specific cache entry.

        Args:
            key: Cache key

        Returns:
            Dictionary with entry information or None if not found

        """
        with self.lock:
            entry = self.cache.get(key)
            if not entry:
                return None

            return {
                "scene_count": len(entry.scenes),
                "age_seconds": entry.age_seconds(),
                "access_count": entry.access_count,
                "is_expired": entry.is_expired(),
                "ttl_seconds": entry.ttl_seconds,
            }
