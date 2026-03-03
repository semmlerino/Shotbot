"""Temporary directory fixtures for isolated test file operations.

This module provides fixtures for creating isolated temporary directories
used in tests that need filesystem access, caching, or VFX directory structures.

Fixtures:
    temp_cache_dir: Temporary cache directory
    cache_manager: CacheManager instance with temp cache dir
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def temp_cache_dir() -> Iterator[Path]:
    """Create temporary cache directory for testing.

    Yields:
        Path to a temporary directory for cache files

    """
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = Path(temp_dir)
        yield cache_dir


@pytest.fixture
def cache_manager(temp_cache_dir: Path) -> Iterator[object]:
    """Create CacheCoordinator instance for testing.

    Uses temp_cache_dir to ensure isolation between tests.

    Args:
        temp_cache_dir: Temporary cache directory fixture

    Yields:
        CacheCoordinator instance configured with temp directory

    """
    from cache import (
        CacheCoordinator,
        LatestFileCache,
        SceneDiskCache,
        ShotDataCache,
        ThumbnailCache,
    )

    thumbnail_cache = ThumbnailCache(temp_cache_dir)
    shot_cache = ShotDataCache(temp_cache_dir)
    scene_disk_cache = SceneDiskCache(temp_cache_dir)
    latest_file_cache = LatestFileCache(temp_cache_dir)
    manager = CacheCoordinator(temp_cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)
    yield manager
    # Cleanup
    manager.clear_cache()


@pytest.fixture
def shot_cache(cache_manager: object) -> object:
    """Extract ShotDataCache from the CacheCoordinator fixture."""
    return cache_manager.shot_cache  # type: ignore[attr-defined]


@pytest.fixture
def scene_disk_cache(cache_manager: object) -> object:
    """Extract SceneDiskCache from the CacheCoordinator fixture."""
    return cache_manager.scene_disk_cache  # type: ignore[attr-defined]
