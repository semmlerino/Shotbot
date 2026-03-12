"""Shot data caching with incremental merge support.

Handles shots.json, previous_shots.json, and migrated_shots.json.
TTL applies only to get_shots_with_ttl / get_cached_previous_shots;
all other reads bypass TTL for persistent incremental caching.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    TypeVar,
    cast,
    final,
)

from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal

from cache._json_store import file_lock, read_json_cache, write_json_cache
from cache.types import ShotMergeResult, get_shot_key, shot_to_dict
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from shot_model import Shot
    from type_definitions import ShotDict

# TypeVar for _build_merge_lookups generic helper
_D = TypeVar("_D")

DEFAULT_TTL_MINUTES = 30


@final
class ShotDataCache(LoggingMixin, QObject):
    """Shot data caching with incremental merge support."""

    cache_updated = Signal()
    shots_migrated = Signal(object)

    def __init__(self, cache_dir: Path) -> None:
        """Initialize shot data cache.

        Args:
            cache_dir: Directory to store cache files. Caller is responsible
                       for resolving the appropriate path (test vs production).

        """
        super().__init__()

        self._lock = QMutex()
        self._cache_ttl = timedelta(minutes=DEFAULT_TTL_MINUTES)

        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.shots_cache_file = cache_dir / "shots.json"
        self.previous_shots_cache_file = cache_dir / "previous_shots.json"
        self.migrated_shots_cache_file = cache_dir / "migrated_shots.json"

    # ========================================================================
    # Shot read methods
    # ========================================================================

    def get_shots_with_ttl(self) -> list[ShotDict] | None:
        """Get cached shot list if valid (subject to TTL expiry).

        Returns None when the cache file is absent or older than the configured
        TTL (default 30 minutes). Use get_shots_no_ttl() to bypass expiry.

        Returns:
            List of shot dictionaries or None if not cached/expired

        """
        result = read_json_cache(self.shots_cache_file, self._cache_ttl)
        return cast("list[ShotDict] | None", result)

    def get_shots_no_ttl(self) -> list[ShotDict] | None:
        """Get My Shots cache without TTL expiration.

        Unlike get_shots_with_ttl(), this method ignores TTL and returns whatever
        is on disk, surviving until explicitly invalidated. Enables incremental
        caching by preserving shot history across refresh cycles.

        Returns:
            List of shot dictionaries or None if not cached

        """
        result = read_json_cache(self.shots_cache_file, self._cache_ttl, check_ttl=False)
        return cast("list[ShotDict] | None", result)

    def get_shots_archive(self) -> list[ShotDict] | None:
        """Get shots that were migrated from My Shots.

        Returns persistent cache without TTL. These are shots that
        disappeared from ws -sg (e.g., approved/completed).

        Returns:
            List of shot dictionaries or None if not cached

        """
        result = read_json_cache(
            self.migrated_shots_cache_file, self._cache_ttl, check_ttl=False
        )
        return cast("list[ShotDict] | None", result)

    def get_cached_previous_shots(self) -> list[ShotDict] | None:
        """Get cached previous/approved shot list if valid (subject to TTL expiry).

        Returns None when the cache file is absent or older than the configured
        TTL. Use get_persistent_previous_shots() to bypass TTL and retrieve
        whatever is on disk regardless of age.

        Returns:
            List of shot dictionaries or None if not cached/expired

        """
        result = read_json_cache(self.previous_shots_cache_file, self._cache_ttl)
        return cast("list[ShotDict] | None", result)

    def get_persistent_previous_shots(self) -> list[ShotDict] | None:
        """Get cached previous/approved shot list without TTL expiration.

        Unlike get_cached_previous_shots(), this method ignores TTL and returns
        whatever is on disk, surviving until explicitly invalidated. Implements
        persistent incremental caching where shots accumulate over time.

        Returns:
            List of shot dictionaries or None if not cached

        """
        result = read_json_cache(
            self.previous_shots_cache_file, self._cache_ttl, check_ttl=False
        )
        return cast("list[ShotDict] | None", result)

    # ========================================================================
    # Shot write methods
    # ========================================================================

    def _write_shots_to_cache(
        self,
        shots: Sequence[Shot] | Sequence[ShotDict],
        cache_file: Path,
        cache_name: str,
    ) -> None:
        """Write a sequence of shots to a cache file, emitting signals on success/failure.

        Args:
            shots: Sequence of Shot objects or shot dictionaries
            cache_file: Target cache file path
            cache_name: Descriptive name used in log/signal messages (e.g. "shots")

        """
        shot_dicts = [shot_to_dict(s) for s in shots]
        success = write_json_cache(cache_file, shot_dicts)
        if success:
            self.cache_updated.emit()
        else:
            self.logger.warning(
                f"Failed to write {cache_name} cache - data may not persist across restarts"
            )

    def cache_shots(self, shots: Sequence[Shot] | Sequence[ShotDict]) -> None:
        """Cache shot list to file.

        Args:
            shots: Sequence of Shot objects or shot dictionaries

        """
        self._write_shots_to_cache(shots, self.shots_cache_file, "shots")

    def cache_previous_shots(self, shots: Sequence[Shot] | Sequence[ShotDict]) -> None:
        """Cache previous/approved shot list to file.

        Args:
            shots: Sequence of Shot objects or shot dictionaries

        """
        self._write_shots_to_cache(shots, self.previous_shots_cache_file, "previous_shots")

    def archive_shots_as_previous(self, shots: Sequence[Shot | ShotDict]) -> bool:
        """Move removed shots to Previous Shots migration cache.

        Merges with existing migrated shots (deduplicates by composite key).
        Lock protects the read-merge-write cycle for thread safety.

        Args:
            shots: List of Shot objects or ShotDicts to migrate

        Returns:
            True if migration was persisted successfully, False on write failure.
            Returns True for empty input (no-op success).

        Design:
            Uses (show, sequence, shot) composite key for consistent deduplication.
            Lock protects read-merge-write cycle; input conversion is outside lock.

        """
        if not shots:
            return True  # No-op is success

        # Phase 1: Convert input to dicts (outside lock - pure memory, no shared state)
        to_migrate = [shot_to_dict(s) for s in shots]

        # Phase 2-4: Read, merge, write under lock for thread and process safety
        # File lock protects against concurrent processes (opt-in via SHOTBOT_FILE_LOCKING=enabled)
        # QMutex protects against concurrent threads within this process
        with file_lock(self.migrated_shots_cache_file), QMutexLocker(self._lock):
            # Read existing shots
            existing = self.get_shots_archive() or []

            # Merge and deduplicate
            shots_by_key: dict[tuple[str, str, str], ShotDict] = {}

            # Add existing first
            for shot in existing:
                key = get_shot_key(shot)
                shots_by_key[key] = shot

            # Add/update with new migrations (overwrites if duplicate)
            for shot in to_migrate:
                key = get_shot_key(shot)
                shots_by_key[key] = shot

            merged = list(shots_by_key.values())

            # Write atomically (inside lock to prevent concurrent write races)
            write_success = write_json_cache(self.migrated_shots_cache_file, merged)

        # Phase 5: Log and emit signals (outside lock - no shared state mutation)
        if write_success:
            self.logger.info(
                f"Migrated {len(to_migrate)} shots to Previous (total: {len(merged)} after dedup)"
            )
            # Emit specific signal (NOT generic cache_updated)
            self.shots_migrated.emit(to_migrate)
        else:
            self.logger.error(
                f"Failed to persist {len(to_migrate)} migrated shots to disk. Migration will be lost on restart."
            )

        return write_success

    # ========================================================================
    # Incremental merge
    # ========================================================================

    @staticmethod
    def _build_merge_lookups(
        cached: Sequence[object] | None,
        fresh: Sequence[object],
        to_dict_fn: Callable[[object], _D],
        get_key_fn: Callable[[_D], tuple[str, str, str]],
    ) -> tuple[list[_D], list[_D], dict[tuple[str, str, str], _D], set[tuple[str, str, str]]]:
        """Build lookup structures shared by update_shots_cache and merge_scenes_incremental.

        Lock acquisition is NOT done here — callers are responsible for holding
        the lock and passing already-copied sequences. This helper operates
        purely on local data.

        Args:
            cached: Previously cached items (objects or dicts), or None
            fresh: Fresh items from discovery
            to_dict_fn: Converts each item to its dict representation
            get_key_fn: Extracts the composite (show, sequence, shot) key

        Returns:
            Tuple of (cached_dicts, fresh_dicts, cached_by_key, fresh_keys)

        """
        cached_dicts = [to_dict_fn(s) for s in (cached or [])]
        fresh_dicts = [to_dict_fn(s) for s in fresh]
        cached_by_key: dict[tuple[str, str, str], _D] = {
            get_key_fn(item): item for item in cached_dicts
        }
        fresh_keys = {get_key_fn(item) for item in fresh_dicts}
        return cached_dicts, fresh_dicts, cached_by_key, fresh_keys

    def update_shots_cache(
        self,
        cached: Sequence[Shot | ShotDict] | None,
        fresh: Sequence[Shot | ShotDict],
    ) -> ShotMergeResult:
        """Merge cached shots with fresh data incrementally.

        Algorithm:
        1. Convert to dicts for consistent handling
        2. Build lookup: cached_by_key[(show, seq, shot)] = shot (O(1))
        3. Build set: fresh_keys = {(show, seq, shot)}
        4. For each fresh shot:
           - If in cached: UPDATE metadata
           - If not in cached: ADD as new
        5. Identify removed: cached_keys - fresh_keys

        Args:
            cached: Previously cached shots (Shot objects or ShotDicts)
            fresh: Fresh shots from workspace command (Shot objects or ShotDicts)

        Returns:
            ShotMergeResult with updated list and statistics

        Design:
            Uses composite key (show, sequence, shot) for global uniqueness.
            This provides better deduplication than Shot.full_name property
            (which excludes 'show' field and could theoretically collide across shows).

        Thread Safety:
            Lock scope minimized to data copy only. Dict operations happen
            outside the lock since they operate on local copies.

        """
        # Phase 1: Convert and build lookups under lock (minimal critical section)
        with QMutexLocker(self._lock):
            cached_dicts, fresh_dicts, cached_by_key, fresh_keys = (
                self._build_merge_lookups(cached, fresh, shot_to_dict, get_shot_key)
            )

        # Phase 2: All merge logic outside lock (CPU-bound, no shared state)
        # Merge: Single O(n) pass using fresh data as source of truth
        updated_shots: list[ShotDict] = []
        new_shots: list[ShotDict] = []

        for fresh_shot in fresh_dicts:
            fresh_key = get_shot_key(fresh_shot)
            updated_shots.append(fresh_shot)  # Always use fresh data

            if fresh_key not in cached_by_key:
                # This is a new shot (not in cache)
                new_shots.append(fresh_shot)

        # Identify removed (cached keys not in fresh)
        removed_shots = [
            shot for shot in cached_dicts if get_shot_key(shot) not in fresh_keys
        ]

        has_changes = bool(new_shots or removed_shots)

        return ShotMergeResult(
            updated_shots=updated_shots,
            new_shots=new_shots,
            removed_shots=removed_shots,
            has_changes=has_changes,
        )

    # ========================================================================
    # Generic key-based caching (backward compatibility)
    # ========================================================================

    def cache_data(self, key: str, data: object) -> None:
        """Cache generic data with a key.

        Special case: the ``"previous_shots"`` key is routed through
        cache_previous_shots(), which persists the data to
        ``previous_shots.json`` on disk and does not apply a TTL.
        All other keys are written to ``<key>.json`` in the cache directory.

        Args:
            key: Cache key identifier
            data: Data to cache

        """
        if key == "previous_shots":
            # Runtime validation: data must be a sequence of shots or dicts
            if isinstance(data, list | tuple):
                self.cache_previous_shots(
                    cast("Sequence[Shot] | Sequence[ShotDict]", data)
                )
            else:
                self.logger.error(f"Invalid data type for previous_shots: {type(data)}")
        else:
            cache_file = self.cache_dir / f"{key}.json"
            _ = write_json_cache(cache_file, data)

    def get_cached_data(self, key: str) -> object | None:
        """Get cached generic data by key.

        Special case: the ``"previous_shots"`` key is routed through
        get_cached_previous_shots(), which applies TTL checking against the
        persistent ``previous_shots.json`` file. All other keys read from
        ``<key>.json`` with the standard TTL check.

        Args:
            key: Cache key identifier

        Returns:
            Cached data or None if not found/expired

        """
        if key == "previous_shots":
            return self.get_cached_previous_shots()
        cache_file = self.cache_dir / f"{key}.json"
        return read_json_cache(cache_file, self._cache_ttl)

    def clear_cached_data(self, key: str) -> None:
        """Clear cached generic data by key.

        Special case: the ``"previous_shots"`` key deletes the persistent
        ``previous_shots.json`` file directly. All other keys delete
        ``<key>.json`` from the cache directory.

        Args:
            key: Cache key identifier

        """
        if key == "previous_shots":
            if self.previous_shots_cache_file.exists():
                self.previous_shots_cache_file.unlink()
        else:
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                cache_file.unlink()

    # ========================================================================
    # Cache management
    # ========================================================================

    def clear_cache(self) -> None:
        """Clear shot-related cache files.

        Clears shots_cache_file, previous_shots_cache_file, and any extra
        JSON files in the cache directory. Does NOT clear thumbnails, threede
        scenes, or latest_files — those belong to other cache components.
        """
        with QMutexLocker(self._lock):
            try:
                for cache_file in [
                    self.shots_cache_file,
                    self.previous_shots_cache_file,
                ]:
                    if cache_file.exists():
                        cache_file.unlink()

                # Sweep any remaining JSON caches (excluding migration archive,
                # threede_scenes, and latest_files — not owned by this class)
                _excluded = {
                    "migrated_shots.json",
                    "threede_scenes.json",
                    "latest_files.json",
                }
                for extra_json in self.cache_dir.glob("*.json"):
                    if extra_json.name not in _excluded:
                        extra_json.unlink()

                self.logger.info("Shot cache cleared successfully")
                self.cache_updated.emit()

            except Exception:
                self.logger.exception("Failed to clear shot cache")

    def set_expiry_minutes(self, expiry_minutes: int) -> None:
        """Set cache expiry time.

        Args:
            expiry_minutes: Cache TTL in minutes

        """
        self._cache_ttl = timedelta(minutes=expiry_minutes)
        self.logger.debug(f"Cache TTL set to {expiry_minutes} minutes")

    def shutdown(self) -> None:
        """Shutdown stub for backward compatibility.

        ShotDataCache has no background threads or file handles to clean up.
        This method exists so callers that shut down CacheManager continue to work.
        """
        self.logger.debug("ShotDataCache shutdown called (no-op)")


def make_default_shot_cache(base_dir: Path | None = None) -> ShotDataCache:
    """Create a ShotDataCache using the env-resolved default directory.

    Args:
        base_dir: Override directory. If None, resolves from environment variables.
    """
    from cache._dir_resolver import resolve_default_cache_dir
    resolved = base_dir if base_dir is not None else resolve_default_cache_dir()
    resolved.mkdir(parents=True, exist_ok=True)
    return ShotDataCache(resolved)
