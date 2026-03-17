"""Type definitions for shotbot application.

This module provides TypedDict, Protocol, and type alias definitions
used throughout the application for better type safety.
"""

from __future__ import annotations

# Standard library imports
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple, NotRequired, TypedDict, cast


logger = logging.getLogger(__name__)


# ==============================================================================
# TypedDict Definitions for Data Structures
# ==============================================================================


class _ShotDictRequired(TypedDict):
    """Required fields for ShotDict."""

    show: str
    sequence: str
    shot: str
    workspace_path: str


class ShotDict(_ShotDictRequired, total=False):
    """Dictionary representation of a Shot.

    Uses inheritance pattern to have required fields (show, sequence, shot, workspace_path)
    and optional fields (discovered_at, frame_start, frame_end) for cache migration compatibility.
    """

    discovered_at: float  # Unix timestamp when shot was added to previous shots
    frame_start: int | None  # First frame of main plate (None = no plate found)
    frame_end: int | None  # Last frame of main plate (None = no plate found)
    thumbnail_path: str  # Persisted thumbnail path (validated on restore)


# Sentinel value to distinguish between "not searched" and "searched but found nothing"
_NOT_SEARCHED = object()


@dataclass(slots=True)
class Shot:
    """Represents a single shot.

    This class is defined in type_definitions to avoid circular imports between
    shot_model.py and base_shot_model.py. It provides the core Shot data structure
    used throughout the application.
    """

    show: str
    sequence: str
    shot: str
    workspace_path: str
    discovered_at: float = 0.0  # Unix timestamp when added to previous shots (for sorting)
    frame_start: int | None = None  # First frame of main plate (None = no plate found)
    frame_end: int | None = None  # Last frame of main plate (None = no plate found)
    _cached_thumbnail_path: Path | None | object = field(
        default=_NOT_SEARCHED,
        init=False,
        repr=False,
        compare=False,
    )
    _thumbnail_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def full_name(self) -> str:
        """Get full shot name."""
        return f"{self.sequence}_{self.shot}"

    @property
    def frame_range_display(self) -> str:
        """Get formatted frame range for display.

        Returns:
            Formatted string like "1001-1150" or "No plate" if no plate found.

        """
        if self.frame_start is None or self.frame_end is None:
            return "No plate"
        return f"{self.frame_start}-{self.frame_end}"

    @property
    def scrub_key(self) -> str:
        """Get unique key for scrub preview cache.

        Returns:
            Key string in format "show/sequence/shot".

        """
        return f"{self.show}/{self.sequence}/{self.shot}"

    @property
    def thumbnail_dir(self) -> Path:
        """Get thumbnail directory path."""
        # Import here to avoid circular dependency at module level
        from config import Config
        from paths.builders import PathBuilders

        return PathBuilders.build_thumbnail_path(
            Config.SHOWS_ROOT,
            self.show,
            self.sequence,
            self.shot,
        )

    def get_thumbnail_path(self) -> Path | None:
        """Get first available thumbnail or None.

        Uses the unified thumbnail discovery logic from PathUtils.find_shot_thumbnail()
        to ensure consistent thumbnails across all views.

        Results are cached after the first search to avoid repeated
        expensive filesystem operations.

        Thread-safe: Uses double-checked locking to ensure only one thread performs
        the expensive thumbnail discovery while others wait for the cached result.
        The sentinel value _NOT_SEARCHED distinguishes "not searched" from "searched but found nothing".
        """
        # First check without lock (fast path for already-cached case)
        if self._cached_thumbnail_path is not _NOT_SEARCHED:
            return cast("Path | None", self._cached_thumbnail_path)

        # Acquire lock for expensive operation
        with self._thumbnail_lock:
            # Double-check inside lock (another thread may have populated cache)
            if self._cached_thumbnail_path is not _NOT_SEARCHED:
                return cast("Path | None", self._cached_thumbnail_path)

            # Import here to avoid circular dependency at module level
            from config import Config
            from thumbnail_finders import ThumbnailFinders

            # Use the unified thumbnail discovery method
            thumbnail = ThumbnailFinders.find_shot_thumbnail(
                Config.SHOWS_ROOT,
                self.show,
                self.sequence,
                self.shot,
            )

            # Cache the result (even if None) to avoid repeated searches
            self._cached_thumbnail_path = thumbnail
            return thumbnail

    def to_dict(self) -> ShotDict:
        """Convert shot to dictionary for serialization.

        Includes thumbnail_path if it has been discovered (not sentinel).
        This reduces filesystem I/O on subsequent loads.
        """
        data: ShotDict = {
            "show": self.show,
            "sequence": self.sequence,
            "shot": self.shot,
            "workspace_path": self.workspace_path,
            "discovered_at": self.discovered_at,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
        }
        # Persist thumbnail path if discovered (not sentinel)
        if self._cached_thumbnail_path is not _NOT_SEARCHED and self._cached_thumbnail_path:
            data["thumbnail_path"] = str(self._cached_thumbnail_path)
        return data

    @classmethod
    def from_dict(cls, data: ShotDict) -> Shot:
        """Create shot from dictionary data.

        Note: discovered_at defaults to 0.0 for cache migration of old entries.
        Frame range fields default to None for cache migration compatibility.
        Restores thumbnail_path if present AND file still exists (validated).
        """
        instance = cls(
            show=data["show"],
            sequence=data["sequence"],
            shot=data["shot"],
            workspace_path=data["workspace_path"],
            discovered_at=data.get("discovered_at", 0.0),
            frame_start=data.get("frame_start"),
            frame_end=data.get("frame_end"),
        )
        # Restore thumbnail path if present AND file still exists
        if "thumbnail_path" in data:
            cached_path = Path(data["thumbnail_path"])
            if cached_path.exists():
                instance._cached_thumbnail_path = cached_path
            # else: leave as _NOT_SEARCHED for re-discovery
        return instance


@dataclass
class ThreeDEScene:
    """Represents a 3DE scene file from another user.

    This class is defined in type_definitions to avoid circular imports between
    threede_scene_model.py and modules that need the ThreeDEScene type.
    """

    show: str
    sequence: str
    shot: str
    workspace_path: str
    user: str
    plate: str
    scene_path: Path
    modified_time: float = 0.0  # Unix timestamp from file mtime (for sorting)
    frame_start: int | None = None  # First frame of main plate (for scrub preview)
    frame_end: int | None = None  # Last frame of main plate (for scrub preview)
    _cached_thumbnail_path: object | Path | None = field(
        default=_NOT_SEARCHED,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def full_name(self) -> str:
        """Get full shot name."""
        return f"{self.sequence}_{self.shot}"

    @property
    def display_name(self) -> str:
        """Get display name (simplified for deduplicated scenes)."""
        # Since we show only one scene per shot, we don't need plate info
        return f"{self.full_name} - {self.user}"

    @property
    def thumbnail_dir(self) -> Path:
        """Get thumbnail directory path (same as regular shots)."""
        # Import here to avoid circular dependency at module level
        from config import Config
        from paths.builders import PathBuilders

        return PathBuilders.build_thumbnail_path(
            Config.SHOWS_ROOT,
            self.show,
            self.sequence,
            self.shot,
        )

    def get_thumbnail_path(self) -> Path | None:
        """Get first available thumbnail or None.

        Uses the unified thumbnail discovery logic from PathUtils.find_shot_thumbnail()
        to ensure consistent thumbnails across all views.

        Results are cached after the first search to avoid repeated
        expensive filesystem operations.
        """
        # Return cached result if we've already searched
        if self._cached_thumbnail_path is not _NOT_SEARCHED:
            # Type narrowing: if it's not the sentinel, it must be Path | None
            return cast("Path | None", self._cached_thumbnail_path)

        # DEBUG: Log thumbnail search for 3DE scenes
        logger.debug(
            f"ThreeDEScene.get_thumbnail_path() called for {self.full_name} (show={self.show}, seq={self.sequence}, shot={self.shot})"
        )

        # Import here to avoid circular dependency at module level
        from config import Config
        from thumbnail_finders import ThumbnailFinders

        # Use the unified thumbnail discovery method
        thumbnail = ThumbnailFinders.find_shot_thumbnail(
            Config.SHOWS_ROOT,
            self.show,
            self.sequence,
            self.shot,
        )

        # DEBUG: Log result
        if thumbnail:
            logger.info(
                f"✅ Found thumbnail for 3DE scene {self.full_name}: {thumbnail}"
            )
        else:
            logger.warning(f"❌ No thumbnail found for 3DE scene {self.full_name}")

        # Cache the result (even if None) to avoid repeated searches
        self._cached_thumbnail_path = thumbnail
        return thumbnail

    def to_dict(self) -> dict[str, str | float | Path | int | None]:
        """Convert scene to dictionary for caching.

        Includes thumbnail_path if it has been discovered (not sentinel).
        This reduces filesystem I/O on subsequent loads.
        """
        data: dict[str, str | float | Path | int | None] = {
            "show": self.show,
            "sequence": self.sequence,
            "shot": self.shot,
            "workspace_path": self.workspace_path,
            "user": self.user,
            "plate": self.plate,
            "scene_path": str(self.scene_path),
            "modified_time": self.modified_time,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
        }
        # Persist thumbnail path if discovered (not sentinel)
        if self._cached_thumbnail_path is not _NOT_SEARCHED and self._cached_thumbnail_path:
            data["thumbnail_path"] = str(self._cached_thumbnail_path)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str | float | Path | int | None]) -> ThreeDEScene:
        """Create from dictionary.

        Note: modified_time defaults to 0.0 for cache migration of old entries.
        Frame range fields default to None for cache migration compatibility.
        Restores thumbnail_path if present AND file still exists (validated).
        """
        # Extract frame range with proper type handling
        frame_start_raw = data.get("frame_start")
        frame_end_raw = data.get("frame_end")
        # Handle numeric types only (int/float from cache)
        frame_start: int | None = None
        frame_end: int | None = None
        if isinstance(frame_start_raw, (int, float)):
            frame_start = int(frame_start_raw)
        if isinstance(frame_end_raw, (int, float)):
            frame_end = int(frame_end_raw)

        instance = cls(
            show=str(data["show"]),
            sequence=str(data["sequence"]),
            shot=str(data["shot"]),
            workspace_path=str(data["workspace_path"]),
            user=str(data["user"]),
            plate=str(data["plate"]),
            scene_path=Path(str(data["scene_path"])),
            modified_time=float(data.get("modified_time", 0.0)),  # type: ignore[arg-type]
            frame_start=frame_start,
            frame_end=frame_end,
        )
        # Restore thumbnail path if present AND file still exists
        if "thumbnail_path" in data:
            cached_path = Path(str(data["thumbnail_path"]))
            if cached_path.exists():
                instance._cached_thumbnail_path = cached_path
            # else: leave as _NOT_SEARCHED for re-discovery
        return instance


class ThreeDESceneDict(TypedDict):
    """Dictionary representation of a 3DE scene."""

    filepath: str
    show: str
    sequence: str
    shot: str
    user: str
    filename: str
    modified_time: float
    workspace_path: str
    last_seen: NotRequired[float]  # Timestamp when scene was last discovered (for pruning)
    thumbnail_path: NotRequired[str]  # Persisted thumbnail path (validated on restore)


class LauncherDict(TypedDict, total=False):
    """Dictionary representation of a custom launcher."""

    id: str
    name: str
    command: str
    description: str | None
    icon: str | None
    category: str | None
    show_in_menu: bool
    requires_shot: bool


class ProcessInfoDict(TypedDict):
    """Information about a running process.

    Used by LauncherProcessManager.get_active_process_info() to return
    normalized information about both subprocesses and workers.
    """

    type: Literal["subprocess", "worker"]
    key: str
    launcher_id: str
    launcher_name: str
    command: str
    pid: int
    running: bool
    start_time: float


class CacheMetricsDict(TypedDict):
    """Cache performance metrics."""

    total_size_bytes: int
    item_count: int
    hit_rate: float
    miss_rate: float
    eviction_count: int
    last_cleanup: float


class ThumbnailInfoDict(TypedDict, total=False):
    """Thumbnail information with metadata."""

    path: str
    size_bytes: int
    width: int
    height: int
    format: str
    cached_at: float


# ==============================================================================
# Test Type Definitions
# ==============================================================================


class PerformanceMetricsDict(TypedDict):
    """Performance metrics for shot models.

    Contains base metrics from BaseShotModel and extended metrics
    from OptimizedShotModel with async loading support.
    """

    # Base metrics from BaseShotModel.get_performance_metrics()
    total_shots: int
    total_refreshes: int
    last_refresh_time: float
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float

    # Extended metrics from OptimizedShotModel (optional for base model)
    loading_in_progress: bool
    session_warmed: bool


# ==============================================================================
# Core type definitions (consolidated from historical shot_types module)
# ==============================================================================


class RefreshResult(NamedTuple):
    """Result of a shot refresh operation.

    This NamedTuple provides type-safe results from ShotModel.refresh_shots()
    operations, allowing callers to determine both operation success and whether
    the shot list actually changed.

    Attributes:
        success: Whether the refresh operation completed successfully.
        has_changes: Whether the shot list changed compared to the previous refresh.

    """

    success: bool
    has_changes: bool
