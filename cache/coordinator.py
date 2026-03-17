"""CacheCoordinator — cross-cutting cache operations."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, final

from cache.shot_cache import DEFAULT_TTL_MINUTES, ShotDataCache
from cache.thumbnail_cache import THUMBNAIL_SIZE, ThumbnailCache
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from collections.abc import Callable

    from cache.latest_file_cache import LatestFileCache
    from cache.scene_cache_disk import SceneDiskCache


@final
class CacheCoordinator(LoggingMixin):
    """Coordinates cross-cutting cache operations across all sub-managers.

    Provides ``clear_all()``, ``set_expiry()``, ``get_disk_usage()``, and
    ``shutdown()`` so callers (e.g. SettingsController, CleanupManager) don't
    need references to every individual cache.
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
    # Properties for backward compatibility
    # ------------------------------------------------------------------

    @property
    def CACHE_THUMBNAIL_SIZE(self) -> int:
        return THUMBNAIL_SIZE

    @property
    def CACHE_EXPIRY_MINUTES(self) -> int:
        return DEFAULT_TTL_MINUTES

    # ------------------------------------------------------------------
    # Cross-cutting operations
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Clear all caches (thumbnails, shots, scenes, latest files)."""
        self.shot_cache.clear_cache()
        self.scene_disk_cache.clear_cache()
        self.latest_file_cache.clear_latest_files_cache()

        # Clear thumbnails directory
        thumbnails_dir = self.thumbnail_cache.thumbnails_dir
        if thumbnails_dir.exists():
            shutil.rmtree(thumbnails_dir)
            thumbnails_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("All caches cleared")

        if self._on_cleared:
            self._on_cleared()

    def set_expiry_minutes(self, expiry_minutes: int) -> None:
        """Set TTL on all caches that support it."""
        self.shot_cache.set_expiry_minutes(expiry_minutes)
        self.scene_disk_cache.set_expiry_minutes(expiry_minutes)
        self.logger.debug(f"All cache TTLs set to {expiry_minutes} minutes")

    def get_disk_usage(self) -> dict[str, float | int | str]:
        """Get aggregate disk usage across all cache types."""
        try:
            total_size = 0
            file_count = 0
            thumbnail_count = 0

            thumbnails_dir = self.thumbnail_cache.thumbnails_dir
            if thumbnails_dir.exists():
                for item in thumbnails_dir.rglob("*"):
                    if item.is_file():
                        total_size += item.stat().st_size
                        file_count += 1
                        thumbnail_count += 1

            for cache_file in [
                self.shot_cache.shots_cache_file,
                self.shot_cache.previous_shots_cache_file,
                self.scene_disk_cache.threede_cache_file,
            ]:
                if cache_file.exists():
                    total_size += cache_file.stat().st_size
                    file_count += 1

            return {
                "total_mb": total_size / (1024 * 1024),
                "file_count": file_count,
                "thumbnail_count": thumbnail_count,
                "thumbnail_dir": str(thumbnails_dir),
            }

        except Exception:
            self.logger.exception("Failed to get disk usage")
            return {"total_mb": 0.0, "file_count": 0, "thumbnail_count": 0}

    def shutdown(self) -> None:
        """Shutdown all sub-managers."""
        self.shot_cache.shutdown()
        self.scene_disk_cache.shutdown()
        self.latest_file_cache.shutdown()
        self.logger.debug("All cache managers shut down")
