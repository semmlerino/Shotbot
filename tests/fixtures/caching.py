"""Caching fixtures and utilities for test isolation and cache behavior testing.

This module provides:
- Cache management utilities (moved from utils.py — test-only infrastructure)
- Fixtures for tests that need isolated cache environments

Functions:
    clear_all_caches: Clear all utility caches (path and version)
    disable_caching: Disable caching for the duration of a test
    enable_caching: Re-enable caching after a test

Fixtures:
    caching_enabled: Enable caching with isolated temp directory
    isolated_cache_manager: CacheManager with isolated temp directory
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    from cache import CacheCoordinator


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache management utilities (test-only infrastructure)
# ---------------------------------------------------------------------------


def clear_all_caches() -> None:
    """Clear all utility caches — useful for test isolation."""
    from path_validators import clear_path_cache
    from version_utils import VersionUtils

    clear_path_cache()
    VersionUtils.clear_version_cache()
    VersionUtils.extract_version_from_path.cache_clear()
    _logger.debug("Cleared all utility caches")


def disable_caching() -> None:
    """Disable caching completely for a test."""
    from path_validators import disable_path_caching

    disable_path_caching()
    clear_all_caches()
    _logger.debug("Caching disabled for testing")


def enable_caching() -> None:
    """Re-enable caching after a test."""
    from path_validators import enable_path_caching

    enable_path_caching()
    _logger.debug("Caching re-enabled after testing")


class CacheIsolation:
    """Context manager for cache isolation in tests.

    Clears and disables all utility caches for the duration of the block,
    then re-enables caching on exit.
    """

    def __enter__(self) -> CacheIsolation:
        """Enter context with isolated cache."""
        clear_all_caches()
        disable_caching()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context and restore caching."""
        enable_caching()
        _logger.debug("Cache isolation context exited")


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def caching_enabled(tmp_path: Path) -> Iterator[Path]:
    """Enable caching with isolated temp directory for cache behavior tests.

    This fixture:
    - Creates an isolated cache directory in tmp_path
    - Sets SHOTBOT_TEST_CACHE_DIR environment variable
    - Enables path caching (re-enables if disabled)
    - Clears all caches before test

    Use this for tests that verify cache hit/miss behavior, TTL expiration,
    cache persistence, etc.

    Yields:
        Path to the isolated cache directory

    Example:
        def test_cache_hit_returns_cached_result(caching_enabled):
            cache_dir = caching_enabled
            # Test cache behavior with caching enabled

    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Save original env var if set
    original_cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")

    # Set isolated cache directory
    os.environ["SHOTBOT_TEST_CACHE_DIR"] = str(cache_dir)

    # Ensure caching is enabled and caches are clear
    clear_all_caches()
    enable_caching()

    _logger.debug("Caching enabled with isolated directory: %s", cache_dir)

    yield cache_dir

    # Cleanup: restore original state
    clear_all_caches()

    if original_cache_dir is not None:
        os.environ["SHOTBOT_TEST_CACHE_DIR"] = original_cache_dir
    else:
        os.environ.pop("SHOTBOT_TEST_CACHE_DIR", None)


@pytest.fixture
def isolated_cache_manager(tmp_path: Path) -> Iterator[CacheCoordinator]:
    """Provide a CacheCoordinator instance with isolated temp directory.

    This fixture:
    - Creates an isolated cache directory
    - Instantiates real cache sub-managers (not test doubles)
    - Properly shuts down the coordinator after test

    Use this for integration tests that need to test cache behavior
    with real file I/O but isolated from the production cache.

    Yields:
        CacheCoordinator instance with isolated cache directory

    Example:
        def test_cache_persistence(isolated_cache_manager):
            coordinator = isolated_cache_manager
            coordinator.shot_cache.cache_shots([shot_data])
            # Verify data is persisted

    """
    from cache import (
        CacheCoordinator,
        LatestFileCache,
        SceneDiskCache,
        ShotDataCache,
        ThumbnailCache,
    )

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    thumbnail_cache = ThumbnailCache(cache_dir)
    shot_cache = ShotDataCache(cache_dir)
    scene_disk_cache = SceneDiskCache(cache_dir)
    latest_file_cache = LatestFileCache(cache_dir)
    coordinator = CacheCoordinator(cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)

    _logger.debug("Created isolated CacheCoordinator at: %s", cache_dir)

    yield coordinator

    # Cleanup
    try:
        coordinator.shutdown()
    except Exception as e:  # noqa: BLE001
        _logger.debug("CacheCoordinator shutdown exception: %s", e)
