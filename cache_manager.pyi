"""Type stubs for cache_manager module."""

# Standard library imports
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

# Third-party imports
from PySide6.QtCore import QObject, QRunnable, Signal

from shot_model import Shot
from type_definitions import ShotDict, ThreeDESceneDict
from typing_compat import override

# Incremental merging support
class ShotMergeResult(NamedTuple):
    """Result of incremental shot merge operation."""

    updated_shots: list[ShotDict]  # All shots (kept + new)
    new_shots: list[ShotDict]  # Just new additions
    removed_shots: list[ShotDict]  # No longer in fresh data
    has_changes: bool  # Any changes detected

class SceneMergeResult(NamedTuple):
    """Result of incremental scene merge operation."""

    updated_scenes: list[ThreeDESceneDict]  # All scenes (kept + new)
    new_scenes: list[ThreeDESceneDict]  # Just new additions
    removed_scenes: list[ThreeDESceneDict]  # No longer in fresh data
    has_changes: bool  # Any changes detected

# Backward compatibility stub
class ThumbnailCacheResult:
    """Stub for backward compatibility - no longer used in simplified implementation."""

    future: None
    path: Path | None
    is_complete: bool
    def __init__(self) -> None: ...

class CacheManager(QObject):
    """Manages caching of shot data and thumbnails with thread safety and memory monitoring."""

    # Signals
    cache_updated: Signal
    shots_migrated: Signal

    # Thread safety
    _lock: threading.RLock

    # Memory tracking
    _memory_usage_bytes: int
    _max_memory_bytes: int

    # Cache directories
    cache_dir: Path
    thumbnails_dir: Path
    shots_cache_file: Path
    previous_shots_cache_file: Path
    threede_scenes_cache_file: Path
    migrated_shots_cache_file: Path

    # Track cached thumbnails
    _cached_thumbnails: dict[str, int]

    # Properties
    @property
    def CACHE_THUMBNAIL_SIZE(self) -> int: ...  # noqa: N802
    @property
    def CACHE_EXPIRY_MINUTES(self) -> int: ...  # noqa: N802
    def __init__(self, cache_dir: Path | None = ...) -> None: ...
    def _ensure_cache_dirs(self) -> None: ...
    def get_cached_thumbnail(
        self,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None: ...
    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
        wait: bool = True,
        timeout: float | None = None,
    ) -> Path | ThumbnailCacheResult | None: ...
    def get_cached_shots(self) -> list[ShotDict] | None: ...
    def cache_shots(self, shots: Sequence[Shot]) -> None: ...
    def get_cached_threede_scenes(self) -> list[ThreeDESceneDict] | None: ...
    def get_persistent_threede_scenes(self) -> list[ThreeDESceneDict] | None: ...
    def cache_threede_scenes(self, scenes: list[ThreeDESceneDict]) -> None: ...
    def has_valid_threede_cache(self) -> bool: ...
    def merge_scenes_incremental(
        self,
        cached: Sequence[object] | None,
        fresh: Sequence[object],
    ) -> SceneMergeResult: ...
    def _evict_old_thumbnails(self) -> None: ...
    def get_memory_usage(self) -> dict[str, float | int]: ...
    def clear_cache(self) -> None: ...
    def set_memory_limit(self, max_memory_mb: int) -> None: ...
    def set_expiry_minutes(self, expiry_minutes: int) -> None: ...
    def ensure_cache_directory(self) -> bool: ...
    def get_cached_previous_shots(self) -> list[ShotDict] | None: ...
    def get_persistent_shots(self) -> list[ShotDict] | None: ...
    def merge_shots_incremental(
        self,
        cached: Sequence[Shot | ShotDict] | None,
        fresh: Sequence[Shot | ShotDict],
    ) -> ShotMergeResult: ...
    def get_migrated_shots(self) -> list[ShotDict] | None: ...
    def migrate_shots_to_previous(self, shots: Sequence[Shot | ShotDict]) -> None: ...
    def cache_previous_shots(
        self, shots: Sequence[Shot] | Sequence[ShotDict]
    ) -> None: ...
    def cache_data(self, key: str, data: object) -> None: ...
    def get_cached_data(self, key: str) -> object | None: ...
    def clear_cached_data(self, key: str) -> None: ...
    def validate_cache(self) -> dict[str, object]: ...
    def clear_failed_attempts(self, cache_key: str | None = ...) -> None: ...
    def get_failed_attempts_status(self) -> dict[str, dict[str, object]]: ...
    def shutdown(self) -> None: ...

class ThumbnailCacheLoaderSignals(QObject):
    """Signals for ThumbnailCacheLoader."""

    loaded: Signal  # (show: str, sequence: str, shot: str, cache_path: Path)
    failed: Signal  # (show: str, sequence: str, shot: str, error_message: str)

class ThumbnailCacheLoader(QRunnable):
    """Background thumbnail cache loader."""

    cache_manager: CacheManager
    source_path: Path
    show: str
    sequence: str
    shot: str
    signals: ThumbnailCacheLoaderSignals

    def __init__(
        self,
        cache_manager: CacheManager,
        source_path: Path | str,
        show: str,
        sequence: str,
        shot: str,
        result: dict[str, object] | None = ...,
    ) -> None: ...
    @override
    def run(self) -> None: ...
