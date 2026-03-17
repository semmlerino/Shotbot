"""Cache package — domain-specific cache managers.

Re-exports all public types for convenient imports::

    from cache import ThumbnailCache, ShotDataCache, SceneDiskCache, LatestFileCache
    from cache import ShotMergeResult, SceneMergeResult, LatestFileCacheResult
    from cache import CacheCoordinator
"""

from __future__ import annotations

from cache._dir_resolver import resolve_default_cache_dir
from cache._json_store import atomic_json_write
from cache.coordinator import CacheCoordinator
from cache.latest_file_cache import LatestFileCache, make_default_latest_file_cache
from cache.scene_cache_disk import SceneDiskCache
from cache.shot_cache import ShotDataCache, make_default_shot_cache
from cache.thumbnail_cache import (
    ThumbnailCache,
    ThumbnailCacheLoader,
    ThumbnailCacheLoaderSignals,
    make_default_thumbnail_cache,
)
from cache.thumbnail_loader import ThumbnailLoader
from cache.types import LatestFileCacheResult, SceneMergeResult, ShotMergeResult


__all__ = [
    "CacheCoordinator",
    "LatestFileCache",
    "LatestFileCacheResult",
    "SceneDiskCache",
    "SceneMergeResult",
    "ShotDataCache",
    "ShotMergeResult",
    "ThumbnailCache",
    "ThumbnailCacheLoader",
    "ThumbnailCacheLoaderSignals",
    "ThumbnailLoader",
    "atomic_json_write",
    "make_default_latest_file_cache",
    "make_default_shot_cache",
    "make_default_thumbnail_cache",
    "resolve_default_cache_dir",
]
