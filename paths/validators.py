"""Path validation utilities with caching.

This module provides utilities for validating path existence with
performance optimization through caching.
"""

from __future__ import annotations

# Standard library imports
import threading
import time
from pathlib import Path

# Local application imports
from config import Config
from logging_mixin import get_module_logger


logger = get_module_logger(__name__)

# Cache for path existence checks (with TTL)
_path_cache: dict[str, tuple[bool, float]] = {}
_path_cache_lock = threading.Lock()  # Thread-safety for path cache access
_PATH_CACHE_TTL = Config.PATH_CACHE_TTL_SECONDS  # 60s for positive entries
_PATH_CACHE_NEGATIVE_TTL = Config.PATH_CACHE_NEGATIVE_TTL_SECONDS  # 10s for negative
_cache_disabled = False  # Test isolation flag


def clear_path_cache() -> None:
    """Clear path validation cache - useful for testing or debugging."""
    with _path_cache_lock:
        _path_cache.clear()
    logger.info("Cleared path cache")


def disable_path_caching() -> None:
    """Disable path caching completely - useful for testing."""
    global _cache_disabled  # noqa: PLW0603
    _cache_disabled = True
    clear_path_cache()
    logger.debug("Path caching disabled for testing")


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
    with _path_cache_lock:
        return {"path_cache_size": len(_path_cache)}


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

        # Skip caching if disabled (for testing)
        if _cache_disabled:
            path_obj = Path(path) if isinstance(path, str) else path
            exists = path_obj.exists()
            if not exists:
                logger.debug(f"{description} does not exist (no cache): {path_obj}")
            return exists

        # Convert to Path object and string for caching
        path_obj = Path(path) if isinstance(path, str) else path
        path_str = str(path_obj)
        current_time = time.time()

        # Check cache first with lock
        with _path_cache_lock:
            if path_str in _path_cache:
                cached_exists, timestamp = _path_cache[path_str]
                ttl = _PATH_CACHE_NEGATIVE_TTL if not cached_exists else _PATH_CACHE_TTL
                if current_time - timestamp < ttl:
                    # Return cached result without verification to avoid performance issues
                    if not cached_exists:
                        logger.debug(
                            f"{description} does not exist (cached): {path_str}"
                        )
                    return cached_exists

        # Cache miss or expired - check actual path existence (outside lock)
        exists = path_obj.exists()

        # Cache the result with lock
        with _path_cache_lock:
            _path_cache[path_str] = (exists, current_time)

            # Clean old cache entries (simple cleanup)
            # Increased threshold from 1000 to 5000 for better performance
            cache_size = len(_path_cache)

        # Trigger cleanup outside lock if needed
        if cache_size > 5000:  # Prevent unlimited growth
            PathValidators._cleanup_path_cache()

        if not exists:
            logger.debug(f"{description} does not exist: {path_obj}")

        return exists

    @staticmethod
    def _cleanup_path_cache() -> None:
        """Clean expired entries from path cache.

        Optimized to only clean when cache is getting large,
        and to keep frequently accessed paths.

        Uses atomic update strategy to prevent race conditions during cleanup.
        """
        global _path_cache  # noqa: PLW0603

        with _path_cache_lock:
            # Only clean if cache is significantly over limit
            if len(_path_cache) <= 2500:  # Keep some headroom
                return

            # Sort by timestamp to keep most recently accessed
            sorted_items = sorted(
                _path_cache.items(),
                key=lambda x: x[1][1],  # Sort by timestamp
                reverse=True,  # Most recent first
            )

            # Atomic update: create new dict and replace in single operation
            # This prevents other threads from seeing an empty cache mid-operation
            _path_cache = dict(sorted_items[:2500])

            logger.debug(
                f"Cleaned path cache, kept {len(_path_cache)} most recent entries"
            )

    @staticmethod
    def batch_validate_paths(paths: list[str | Path]) -> dict[str, bool]:
        """Validate multiple paths at once for better performance.

        Args:
            paths: List of paths to validate

        Returns:
            Dictionary mapping path strings to existence status

        """
        results: dict[str, bool] = {}
        current_time = time.time()
        paths_to_check: list[tuple[str | Path, str]] = []

        # First pass - check cache with lock
        with _path_cache_lock:
            for path in paths:
                path_str = str(path)
                if path_str in _path_cache:
                    cached_exists, timestamp = _path_cache[path_str]
                    ttl = _PATH_CACHE_NEGATIVE_TTL if not cached_exists else _PATH_CACHE_TTL
                    if current_time - timestamp < ttl:
                        # Use cached result without verification
                        results[path_str] = cached_exists
                        continue
                paths_to_check.append((path, path_str))

        # Second pass - check filesystem for uncached paths (outside lock)
        updates: list[tuple[str, bool]] = []
        for path, path_str in paths_to_check:
            path_obj: Path = Path(path) if isinstance(path, str) else path
            exists: bool = path_obj.exists()
            results[path_str] = exists
            updates.append((path_str, exists))

        # Update cache with lock
        with _path_cache_lock:
            for path_str, exists in updates:
                _path_cache[path_str] = (exists, current_time)

            # Check cache size
            cache_size = len(_path_cache)

        # Clean cache if needed (outside lock)
        # Increased threshold from 1000 to 5000 for better performance
        if cache_size > 5000:
            PathValidators._cleanup_path_cache()

        return results
