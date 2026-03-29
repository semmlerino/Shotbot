"""Path validation utilities with caching.

This module provides utilities for validating path existence with
performance optimization through caching.
"""

from __future__ import annotations

# Standard library imports
import threading
from pathlib import Path
from typing import cast

# Third-party imports
from cachetools import TTLCache

# Local application imports
from config import Config
from logging_mixin import get_module_logger


logger = get_module_logger(__name__)

# Separate caches for hits (positive) and misses (negative) with different TTLs.
# pyright: ignore needed because vendored cachetools lacks type stubs.
_hit_cache: TTLCache[str, bool] = TTLCache(  # pyright: ignore[reportInvalidTypeArguments]
    maxsize=2500, ttl=Config.Cache.PATH_TTL_SECONDS
)
_miss_cache: TTLCache[str, bool] = TTLCache(  # pyright: ignore[reportInvalidTypeArguments]
    maxsize=500, ttl=Config.Cache.PATH_NEGATIVE_TTL_SECONDS
)
_cache_lock = threading.Lock()
_cache_disabled = False  # Test isolation flag


def clear_path_cache() -> None:
    """Clear path validation cache - useful for testing or debugging."""
    with _cache_lock:
        _hit_cache.clear()
        _miss_cache.clear()
    logger.info("Cleared path cache")


def enable_path_caching() -> None:
    """Re-enable path caching after testing."""
    global _cache_disabled  # noqa: PLW0603
    _cache_disabled = False
    logger.debug("Path caching re-enabled after testing")


def get_cache_stats() -> dict[str, int]:
    """Get path cache statistics.

    Returns:
        Dictionary with cache size

    """
    with _cache_lock:
        return {"path_cache_size": len(_hit_cache) + len(_miss_cache)}


class PathValidators:
    """Utilities for path validation with caching."""

    @staticmethod
    def validate_path_exists(path: str | Path, description: str = "Path") -> bool:
        """Validate that a path exists.

        Uses caching for frequently checked paths to improve performance.

        Args:
            path: Path to validate
            description: Description for logging

        Returns:
            True if path exists, False otherwise

        """
        if not path:
            logger.debug(f"{description} is empty")
            return False

        path_obj = Path(path) if isinstance(path, str) else path
        path_str = str(path_obj)

        # Skip caching if disabled (for testing)
        if _cache_disabled:
            exists = path_obj.exists()
            if not exists:
                logger.debug(f"{description} does not exist (no cache): {path_obj}")
            return exists

        # Check hit cache, then miss cache
        with _cache_lock:
            hit = cast("bool | None", _hit_cache.get(path_str))  # pyright: ignore[reportUnknownMemberType]
            if hit is not None:
                return True
            miss = cast("bool | None", _miss_cache.get(path_str))  # pyright: ignore[reportUnknownMemberType]
            if miss is not None:
                logger.debug(f"{description} does not exist (cached): {path_str}")
                return False

        # Cache miss — check filesystem
        exists = path_obj.exists()

        with _cache_lock:
            if exists:
                _hit_cache[path_str] = True  # pyright: ignore[reportUnknownMemberType]
            else:
                _miss_cache[path_str] = False  # pyright: ignore[reportUnknownMemberType]
                logger.debug(f"{description} does not exist: {path_obj}")

        return exists

    @staticmethod
    def batch_validate_paths(paths: list[str | Path]) -> dict[str, bool]:
        """Validate multiple paths at once for better performance.

        Args:
            paths: List of paths to validate

        Returns:
            Dictionary mapping path strings to existence status

        """
        return {str(p): PathValidators.validate_path_exists(p) for p in paths}
