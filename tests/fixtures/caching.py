"""Caching fixtures for test isolation and cache behavior testing.

This module provides fixtures for tests that need to:
- Test with caching explicitly enabled (for cache behavior tests)
- Use isolated cache directories

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

    from cache_manager import CacheManager

_logger = logging.getLogger(__name__)


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
    from utils import clear_all_caches, enable_caching

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
def isolated_cache_manager(tmp_path: Path) -> Iterator[CacheManager]:
    """Provide a CacheManager instance with isolated temp directory.

    This fixture:
    - Creates an isolated cache directory
    - Instantiates a real CacheManager (not a test double)
    - Properly shuts down the manager after test

    Use this for integration tests that need to test CacheManager behavior
    with real file I/O but isolated from the production cache.

    Yields:
        CacheManager instance with isolated cache directory

    Example:
        def test_cache_persistence(isolated_cache_manager):
            manager = isolated_cache_manager
            manager.cache_shots([shot_data])
            # Verify data is persisted

    """
    from cache_manager import CacheManager

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Create subdirectories CacheManager expects
    (cache_dir / "thumbnails").mkdir(exist_ok=True)
    (cache_dir / "production").mkdir(exist_ok=True)

    manager = CacheManager(cache_dir=cache_dir)

    _logger.debug("Created isolated CacheManager at: %s", cache_dir)

    yield manager

    # Cleanup
    try:
        manager.shutdown()
    except Exception as e:
        _logger.debug("CacheManager shutdown exception: %s", e)


