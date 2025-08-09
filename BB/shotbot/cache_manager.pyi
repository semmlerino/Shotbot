"""Type stubs for cache_manager module."""

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, Signal

from shot_model import Shot

class CacheManager(QObject):
    """Manages caching of shot data and thumbnails with thread safety and memory monitoring."""

    # Signals
    cache_updated: Signal

    # Thread safety
    _lock: threading.RLock

    # Memory tracking
    _memory_usage_bytes: int
    _max_memory_bytes: int

    # Cache directories
    cache_dir: Path
    thumbnails_dir: Path
    shots_cache_file: Path
    threede_scenes_cache_file: Path

    # Track cached thumbnails
    _cached_thumbnails: Dict[str, int]

    # Properties
    @property
    def CACHE_THUMBNAIL_SIZE(self) -> int: ...
    @property
    def CACHE_EXPIRY_MINUTES(self) -> int: ...
    def __init__(self, cache_dir: Optional[Path] = ...) -> None: ...
    def _ensure_cache_dirs(self) -> None: ...
    def get_cached_thumbnail(
        self, show: str, sequence: str, shot: str
    ) -> Optional[Path]: ...
    def cache_thumbnail(
        self, source_path: Path, show: str, sequence: str, shot: str
    ) -> Optional[Path]: ...
    def get_cached_shots(self) -> Optional[List[Dict[str, Any]]]: ...
    def cache_shots(self, shots: Sequence[Shot]) -> None: ...
    def get_cached_threede_scenes(self) -> Optional[List[Dict[str, Any]]]: ...
    def cache_threede_scenes(self, scenes: List[Dict[str, Any]]) -> None: ...
    def _evict_old_thumbnails(self) -> None: ...
    def get_memory_usage(self) -> Dict[str, Any]: ...
    def clear_cache(self) -> None: ...

class ThumbnailCacheLoader:
    """Background thumbnail cache loader."""

    class Signals(QObject):
        loaded: Signal

    cache_manager: CacheManager
    source_path: Path
    show: str
    sequence: str
    shot: str
    signals: Signals

    def __init__(
        self,
        cache_manager: CacheManager,
        source_path: Path,
        show: str,
        sequence: str,
        shot: str,
    ) -> None: ...
    def run(self) -> None: ...
