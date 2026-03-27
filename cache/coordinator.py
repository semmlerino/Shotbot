"""CacheCoordinator — cross-cutting cache operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, final

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from collections.abc import Callable

    from cache.latest_file_cache import LatestFileCache
    from cache.scene_cache_disk import SceneDiskCache
    from cache.shot_cache import ShotDataCache
    from cache.thumbnail_cache import ThumbnailCache


@final
class CacheCoordinator(LoggingMixin):
    """Coordinates cross-cutting cache operations across all sub-managers.

    Provides ``set_expiry()`` and ``shutdown()`` so callers don't need
    references to every individual cache.
    """

    def __init__(
        self,
        cache_dir: Path,
        thumbnail_cache: ThumbnailCache,
        shot_cache: ShotDataCache,
        scene_disk_cache: SceneDiskCache,
        latest_file_cache: LatestFileCache,
        on_cleared: Callable[[], None] | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.thumbnail_cache = thumbnail_cache
        self.shot_cache = shot_cache
        self.scene_disk_cache = scene_disk_cache
        self.latest_file_cache = latest_file_cache
        self._on_cleared = on_cleared

    # ------------------------------------------------------------------
    # Cross-cutting operations
    # ------------------------------------------------------------------

    def set_expiry_minutes(self, expiry_minutes: int) -> None:
        """Set TTL on all caches that support it."""
        self.shot_cache.set_expiry_minutes(expiry_minutes)
        self.scene_disk_cache.set_expiry_minutes(expiry_minutes)
        self.logger.debug(f"All cache TTLs set to {expiry_minutes} minutes")

    def shutdown(self) -> None:
        """Shutdown all sub-managers (no-op)."""
