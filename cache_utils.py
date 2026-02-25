"""Cache utilities to eliminate TTL and stats tracking duplication.

This module provides reusable cache patterns found throughout the codebase:
- TTL (Time-To-Live) expiration checking
- Cache statistics tracking (hits, misses, evictions)

Usage:
    from cache_utils import is_expired, find_expired_keys, CacheStatsMixin

    class MyCache(CacheStatsMixin):
        def get(self, key: str) -> str | None:
            if key in self._cache:
                timestamp = self._timestamps[key]
                if not is_expired(timestamp, self._ttl):
                    self._record_hit()
                    return self._cache[key]
            self._record_miss()
            return None
"""

from __future__ import annotations

import time
from typing import Any, TypeVar


K = TypeVar("K")
V = TypeVar("V")


def is_expired(timestamp: float, ttl_seconds: float) -> bool:
    """Check if a timestamp has exceeded its TTL.

    Args:
        timestamp: The time.time() when the item was cached
        ttl_seconds: Time-to-live in seconds

    Returns:
        True if the entry has expired

    """
    return time.time() - timestamp >= ttl_seconds


def find_expired_keys(
    cache: dict[K, tuple[V, float]],
    ttl_seconds: float,
) -> list[K]:
    """Find all expired keys in a cache with (value, timestamp) entries.

    Args:
        cache: Dictionary mapping keys to (value, timestamp) tuples
        ttl_seconds: TTL in seconds

    Returns:
        List of expired keys (can be used to delete entries)

    """
    return [key for key, (_, timestamp) in cache.items() if is_expired(timestamp, ttl_seconds)]


class CacheStatsMixin:
    """Mixin providing standardized cache statistics tracking.

    Tracks hits, misses, and evictions with computed hit rate.

    Usage:
        class MyCache(CacheStatsMixin):
            def __init__(self) -> None:
                super().__init__()
                # ... your cache initialization ...

            def get(self, key: str) -> str | None:
                if key in self._cache:
                    self._record_hit()
                    return self._cache[key]
                self._record_miss()
                return None
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize stats tracking and continue MRO chain."""
        super().__init__(*args, **kwargs)
        self._cache_stats: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }

    def _record_hit(self) -> None:
        """Record a cache hit."""
        self._cache_stats["hits"] += 1

    def _record_miss(self) -> None:
        """Record a cache miss."""
        self._cache_stats["misses"] += 1

    def _record_eviction(self, count: int = 1) -> None:
        """Record cache eviction(s).

        Args:
            count: Number of entries evicted (default 1)

        """
        self._cache_stats["evictions"] += count

    def _reset_stats(self) -> None:
        """Reset all statistics to zero."""
        self._cache_stats = {"hits": 0, "misses": 0, "evictions": 0}

    def get_cache_stats(self) -> dict[str, int | float]:
        """Get cache statistics with computed hit rate.

        Returns:
            Dictionary with hits, misses, evictions, total_requests, hit_rate_percent

        """
        total = self._cache_stats["hits"] + self._cache_stats["misses"]
        hit_rate = (self._cache_stats["hits"] / total * 100) if total > 0 else 0.0

        return {
            "hits": self._cache_stats["hits"],
            "misses": self._cache_stats["misses"],
            "evictions": self._cache_stats["evictions"],
            "total_requests": total,
            "hit_rate_percent": hit_rate,
        }
