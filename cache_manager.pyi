"""Type stubs for cache_manager module."""

# Standard library imports
import threading
from collections.abc import Callable, Sequence
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
    stale_scenes: list[ThreeDESceneDict]  # In cache but not in current scan (retained within retention window)
    has_changes: bool  # Any changes detected
    pruned_count: int = 0

class CacheManager(QObject):
    """Manages caching of shot data and thumbnails with thread safety and memory monitoring."""

    # Signals
    cache_updated: Signal
    cache_write_failed: Signal
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
    latest_files_cache_file: Path

    # Track cached thumbnails
    _cached_thumbnails: dict[str, int]

    # Properties
    @property
    def CACHE_THUMBNAIL_SIZE(self) -> int: ...
    @property
    def CACHE_EXPIRY_MINUTES(self) -> int: ...
    def __init__(self, cache_dir: Path | None = ..., settings_manager: object | None = ..., on_cleared: Callable[[], None] | None = ...) -> None: ...
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
    ) -> Path | None: ...
    def get_shots_with_ttl(self) -> list[ShotDict] | None: ...
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
    def get_disk_usage(self) -> dict[str, float | int]: ...
    def clear_cache(self) -> None: ...
    def set_expiry_minutes(self, expiry_minutes: int) -> None: ...
    def ensure_cache_directory(self) -> bool: ...
    def get_cached_previous_shots(self) -> list[ShotDict] | None: ...
    def get_shots_no_ttl(self) -> list[ShotDict] | None: ...
    def update_shots_cache(
        self,
        cached: Sequence[Shot | ShotDict] | None,
        fresh: Sequence[Shot | ShotDict],
    ) -> ShotMergeResult: ...
    def get_shots_archive(self) -> list[ShotDict] | None: ...
    def archive_shots_as_previous(self, shots: Sequence[Shot | ShotDict]) -> bool: ...
    def cache_previous_shots(
        self, shots: Sequence[Shot] | Sequence[ShotDict]
    ) -> None: ...
    def cache_data(self, key: str, data: object) -> None: ...
    def get_cached_data(self, key: str) -> object | None: ...
    def clear_cached_data(self, key: str) -> None: ...
    def validate_cache(self) -> dict[str, object]: ...
    def shutdown(self) -> None: ...
    # Latest file cache methods
    def get_cached_latest_file(
        self,
        workspace_path: str,
        file_type: str,
    ) -> Path | None: ...
    def cache_latest_file(
        self,
        workspace_path: str,
        file_type: str,
        file_path: Path | None,
    ) -> None: ...
    def clear_latest_files_cache(
        self,
        workspace_path: str | None = ...,
    ) -> None: ...
    def has_cache_entry(self, workspace_path: str, file_type: str) -> bool: ...
    def _read_latest_files_cache(self) -> dict[str, dict[str, object]] | None: ...

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
    ) -> None: ...
    @override
    def run(self) -> None: ...
