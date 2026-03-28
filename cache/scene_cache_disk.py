from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal

from cache._json_store import read_json_cache, write_json_cache
from cache._merge import build_merge_lookups
from cache.types import SceneMergeResult, get_scene_key, scene_to_dict


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from type_definitions import ThreeDEScene, ThreeDESceneDict

DEFAULT_TTL_MINUTES = 30


@final
class SceneDiskCache(QObject):
    """3DE scene disk persistence with incremental merge."""

    cache_updated = Signal()

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = QMutex()
        self._cache_ttl = timedelta(minutes=DEFAULT_TTL_MINUTES)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.threede_cache_file = cache_dir / "threede_scenes.json"

    def get_cached_threede_scenes(self) -> list[ThreeDESceneDict] | None:
        """Get cached 3DE scene list if valid.

        Returns:
            List of scene dictionaries or None if not cached/expired

        """
        result = read_json_cache(self.threede_cache_file, self._cache_ttl)
        return cast("list[ThreeDESceneDict] | None", result)

    def get_persistent_threede_scenes(self) -> list[ThreeDESceneDict] | None:
        """Get cached 3DE scenes without TTL expiration.

        Enables incremental caching by preserving scene history across scans.

        Returns:
            List of scene dictionaries or None if not cached

        """
        result = read_json_cache(
            self.threede_cache_file, self._cache_ttl, check_ttl=False
        )
        return cast("list[ThreeDESceneDict] | None", result)

    def has_valid_threede_cache(self) -> bool:
        """Check if we have a valid 3DE cache.

        Uses persistent cache (no TTL check) since 3DE scenes use
        incremental caching where scene history is preserved.

        Returns:
            True if cache file exists with data

        """
        cached = self.get_persistent_threede_scenes()
        return cached is not None

    def is_cache_fresh(self) -> bool:
        """Check if 3DE cache exists and is within TTL.

        Unlike has_valid_threede_cache() which ignores TTL, this method
        returns False when the cache has expired, triggering background
        discovery to refresh stale data.

        Returns:
            True if cache file exists with data AND is within TTL

        """
        cached = self.get_cached_threede_scenes()
        return cached is not None

    def cache_threede_scenes(
        self,
        scenes: list[ThreeDESceneDict],
    ) -> None:
        """Cache 3DE scene list to file.

        Args:
            scenes: List of scene dictionaries

        """
        success = write_json_cache(self.threede_cache_file, scenes)
        if success:
            self.cache_updated.emit()
        else:
            logger.warning(
                "Failed to write 3DE scenes cache - data may not persist across restarts"
            )

    def merge_scenes_incremental(
        self,
        cached: Sequence[ThreeDESceneDict | ThreeDEScene] | None,
        fresh: Sequence[ThreeDESceneDict | ThreeDEScene],
        max_age_days: int = 60,
    ) -> SceneMergeResult:
        """Merge cached 3DE scenes with fresh data incrementally.

        Algorithm:
        1. Convert to dicts for consistent handling
        2. Build lookup: cached_by_key[(show, seq, shot)] = scene
        3. Build set: fresh_keys = {(show, seq, shot)}
        4. For each fresh scene:
           - If in cached: UPDATE with fresh data (newer mtime/plate)
           - If not in cached: ADD as new
           - Update last_seen timestamp
        5. Identify removed: cached_keys - fresh_keys (retained unless too old)
        6. Prune scenes not seen in max_age_days

        Args:
            cached: Previously cached scenes (ThreeDEScene objects or dicts)
            fresh: Fresh scenes from discovery (ThreeDEScene objects or dicts)
            max_age_days: Maximum age for cached scenes not in fresh data (default 60)

        Returns:
            SceneMergeResult with merged list, statistics, and pruned count

        Thread Safety:
            Lock scope minimized to data copy only. CPU-bound dict operations
            happen outside the lock since they operate on local copies.

        """
        now = datetime.now(UTC).timestamp()
        cutoff = now - (max_age_days * 24 * 60 * 60)

        # Phase 1: Convert and build lookups under lock (minimal critical section)
        with QMutexLocker(self._lock):
            _, fresh_dicts, cached_by_key, fresh_keys = build_merge_lookups(
                cached, fresh, scene_to_dict, get_scene_key
            )

        # Phase 2: All CPU-bound merge logic OUTSIDE lock
        # These operate on local copies, no shared state mutation

        # Merge: fresh scenes override cached (UPDATE or ADD)
        updated_by_key: dict[tuple[str, str, str], ThreeDESceneDict] = {}
        new_scenes: list[ThreeDESceneDict] = []
        pruned_count = 0

        # Process fresh scenes (always include, update last_seen)
        for fresh_scene in fresh_dicts:
            fresh_key = get_scene_key(fresh_scene)
            if fresh_key not in cached_by_key:
                new_scenes.append(fresh_scene)
            # Update last_seen and add to result
            updated_scene = dict(fresh_scene)
            updated_scene["last_seen"] = now
            updated_by_key[fresh_key] = cast("ThreeDESceneDict", updated_scene)

        # Process cached scenes not in fresh (apply age-based pruning)
        removed_keys = set(cached_by_key.keys()) - fresh_keys
        stale_scenes: list[ThreeDESceneDict] = []

        for key in removed_keys:
            cached_scene = cached_by_key[key]
            # Get last_seen (default to now for legacy cache entries)
            scene_last_seen = cached_scene.get("last_seen", now)
            if scene_last_seen >= cutoff:
                # Within retention window - keep it
                updated_by_key[key] = cached_scene
                stale_scenes.append(cached_scene)  # Track as "not in fresh"
            else:
                # Too old - prune it
                pruned_count += 1

        # All scenes (kept + updated + new)
        updated_scenes = list(updated_by_key.values())
        has_changes = bool(new_scenes or stale_scenes or pruned_count > 0)

        return SceneMergeResult(
            updated_scenes=updated_scenes,
            new_scenes=new_scenes,
            stale_scenes=stale_scenes,
            has_changes=has_changes,
            pruned_count=pruned_count,
        )

    def set_expiry_minutes(self, expiry_minutes: int) -> None:
        """Set cache TTL.

        Args:
            expiry_minutes: Cache TTL in minutes

        """
        self._cache_ttl = timedelta(minutes=expiry_minutes)
        logger.debug(f"SceneDiskCache TTL set to {expiry_minutes} minutes")

    def clear_cache(self) -> None:
        """Delete the 3DE scenes cache file."""
        if self.threede_cache_file.exists():
            self.threede_cache_file.unlink()
            logger.debug("Cleared 3DE scenes cache")

    def cache_files(self) -> list[Path]:
        """Return list of cache file paths managed by this cache.

        Returns:
            List of cache file Path objects

        """
        return [self.threede_cache_file]
