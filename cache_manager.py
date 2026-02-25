"""Simplified cache manager for shot data and thumbnails.

This is a streamlined replacement for the complex cache architecture,
designed for a local VFX tool on a secure network.

Caching Strategies:
- Thumbnails: Persistent (no expiration, manual clear only)
- Shot data (shots.json): 30-minute TTL
- Previous shots (previous_shots.json): Persistent (no expiration, incremental accumulation)
- 3DE scenes (threede_scenes.json): Persistent with 60-day age-based pruning
- Latest files (latest_files.json): 5-minute TTL for Maya/3DE file paths per workspace

Rationale: Thumbnails are derived from static source images, so they should
persist indefinitely. Data caches reflect dynamic VFX workspace state and need
periodic refresh to stay current.

Incremental Merging:
- Uses composite key (show, sequence, shot) for global shot uniqueness
- Provides better deduplication than Shot.full_name property (which excludes 'show' field)
- Enables incremental accumulation where shots persist across refreshes
- Design rationale: Composite keys prevent cross-show collisions and enable
  robust merge/dedup algorithms in cache operations

Simplifications:
- File locking enabled by default (opt-out via SHOTBOT_FILE_LOCKING=disabled)
- No memory manager/LRU eviction
- No failure tracker with exponential backoff
- No storage backend abstraction
- Direct PIL processing (JPEG/PNG only)
- Simple atomic writes (temp file + os.replace)

Maintained features:
- All public API methods (backward compatible)
- Thumbnail caching (get_cached_thumbnail, cache_thumbnail)
- Shot/3DE/Previous shots data caching
- Directory structure
- Thread safety (basic QMutex)
"""

from __future__ import annotations

# Standard library imports
import contextlib
import json
import os
import shutil
import tempfile
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    ClassVar,
    NamedTuple,
    Protocol,
    TypeAlias,
    TypeVar,
    cast,
    final,
)

# Third-party imports
from PIL import Image
from PySide6.QtCore import QMutex, QMutexLocker, QObject, QRunnable, Qt, Signal

# Local application imports
from exceptions import ThumbnailError
from logging_mixin import LoggingMixin
from typing_compat import override


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from PySide6.QtGui import QImage

    from shot_model import Shot
    from type_definitions import ShotDict, ThreeDESceneDict

    class _HasToDict(Protocol):
        """Protocol for objects with to_dict() method."""

        def to_dict(self) -> ThreeDESceneDict: ...

# Type alias for JSON data (used for runtime validation) - Python 3.11 compatible
JSONValue: TypeAlias = (
    dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None
)

# TypeVar for _build_merge_lookups generic helper
_D = TypeVar("_D")

# Constants
DEFAULT_TTL_MINUTES = 30
LATEST_FILES_TTL_MINUTES = 5  # TTL for latest Maya/3DE file cache
THUMBNAIL_SIZE = 256
THUMBNAIL_QUALITY = 85
STAT_CACHE_TTL = 2.0  # Cache stat results for 2 seconds to reduce filesystem I/O
STAT_CACHE_MAX_SIZE = 1000  # Maximum entries in stat cache (LRU eviction)

# File locking configuration (enabled by default, opt-out via environment variable)
# Disable with: SHOTBOT_FILE_LOCKING=disabled
FILE_LOCKING_ENABLED = os.getenv("SHOTBOT_FILE_LOCKING", "enabled").lower() != "disabled"

# Check if fcntl is available (not on Windows)
# Import as optional module to avoid type errors
import types as _types


_fcntl: _types.ModuleType | None
try:
    import fcntl as _fcntl_module
    _fcntl = _fcntl_module
except ImportError:
    _fcntl = None


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
    removed_scenes: list[ThreeDESceneDict]  # No longer in fresh data (but retained)
    has_changes: bool  # Any changes detected
    pruned_count: int = 0  # Scenes removed due to age-based pruning


def _get_shot_key(shot: ShotDict) -> tuple[str, str, str]:
    """Get composite unique key for shot.

    Uses (show, sequence, shot) tuple instead of full_name to ensure
    global uniqueness across all shows.

    Args:
        shot: Shot dictionary with show, sequence, shot fields

    Returns:
        Tuple of (show, sequence, shot) for use as dict key

    """
    return (shot["show"], shot["sequence"], shot["shot"])


def _shot_to_dict(shot: object) -> ShotDict:
    """Convert Shot object or ShotDict to ShotDict.

    Args:
        shot: Shot object with to_dict() method or ShotDict

    Returns:
        ShotDict with all required fields

    """
    if isinstance(shot, dict):
        return cast("ShotDict", shot)
    # Assume Shot object with to_dict method — TYPE_CHECKING import prevents runtime check
    return cast("ShotDict", cast("_HasToDict", shot).to_dict())


def _get_scene_key(scene: ThreeDESceneDict) -> tuple[str, str, str]:
    """Get composite unique key for scene.

    Uses (show, sequence, shot) tuple for shot-level deduplication.
    This aligns with the current deduplication strategy where only one
    scene per shot is kept (selected by mtime and plate priority).

    Args:
        scene: Scene dictionary with show, sequence, shot fields

    Returns:
        Tuple of (show, sequence, shot) for use as dict key

    """
    return (scene["show"], scene["sequence"], scene["shot"])


def _scene_to_dict(scene: object) -> ThreeDESceneDict:
    """Convert ThreeDEScene object or dict to ThreeDESceneDict.

    Args:
        scene: ThreeDEScene object with to_dict() method or ThreeDESceneDict

    Returns:
        ThreeDESceneDict with all required fields

    """
    if isinstance(scene, dict):
        # Type narrowing: convert through object to satisfy type checker
        return cast("ThreeDESceneDict", cast("object", scene))
    # Assume ThreeDEScene object with to_dict method
    # Safe to call: we checked it's not a dict, so it must be object with to_dict()
    # Use _HasToDict protocol to ensure type safety without explicit Any
    return cast("_HasToDict", scene).to_dict()


@final
class ThumbnailCacheLoaderSignals(QObject):
    """Signals for ThumbnailCacheLoader."""

    loaded = Signal(str, str, str, Path)  # show, sequence, shot, cache_path
    failed = Signal(str, str, str, str)  # show, sequence, shot, error_message


@final
class ThumbnailCacheLoader(QRunnable):
    """Background thumbnail cache loader — caches a source thumbnail via CacheManager."""

    def __init__(
        self,
        cache_manager: CacheManager,
        source_path: Path | str,
        show: str,
        sequence: str,
        shot: str,
    ) -> None:
        super().__init__()
        self.cache_manager = cache_manager
        self.source_path = source_path
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.signals = ThumbnailCacheLoaderSignals()
        self.setAutoDelete(True)

    @override
    def run(self) -> None:
        try:
            result = self.cache_manager.cache_thumbnail(
                self.source_path, self.show, self.sequence, self.shot
            )
            if result:
                self.signals.loaded.emit(self.show, self.sequence, self.shot, result)
            else:
                self.signals.failed.emit(
                    self.show, self.sequence, self.shot, "cache_thumbnail returned None"
                )
        except Exception as e:
            self.signals.failed.emit(self.show, self.sequence, self.shot, str(e))


@final
class CacheManager(LoggingMixin, QObject):
    """Simplified cache manager for local VFX tool.

    Provides same public API as CacheManager but with simpler implementation.

    Thread Safety:
    This class uses two synchronization mechanisms:
    1. QMutex (self._lock) - For in-process thread safety
    2. File locks (_file_lock) - For cross-process safety (opt-in)

    Lock Ordering Contract:
    When both locks are needed, ALWAYS acquire file lock BEFORE QMutex:
        with self._file_lock(file), QMutexLocker(self._lock):
            ...
    This prevents deadlocks between threads/processes. Violating this order
    can cause deadlock if one thread holds QMutex waiting for file lock while
    another process holds file lock waiting for QMutex.
    """

    # Signals - maintain backward compatibility
    cache_updated = Signal()
    cache_write_failed = Signal(str)  # Emitted with cache name when write fails
    shots_migrated = Signal(list)  # Emitted when shots migrate to Previous Shots

    # Track initialized cache directories to suppress duplicate logs
    _initialized_cache_dirs: ClassVar[set[str]] = set()

    def __init__(
        self,
        cache_dir: Path | None = None,
        settings_manager: object | None = None,  # Ignored for simplicity
    ) -> None:
        """Initialize simplified cache manager.

        Args:
            cache_dir: Cache directory path. If None, uses mode-appropriate default
            settings_manager: Ignored in simplified implementation

        """
        super().__init__()

        # Thread safety
        self._lock = QMutex()

        # Stat result cache with LRU eviction: {path_str: (size, mtime, cache_time)}
        self._stat_cache: OrderedDict[str, tuple[int, float, float]] = OrderedDict()

        # Setup cache directory
        if cache_dir is None:
            # Standard library imports
            import sys

            # Use default cache location based on mode
            # Check for test-specific cache dir first (xdist worker isolation)
            test_cache_dir = os.getenv("SHOTBOT_TEST_CACHE_DIR")
            if test_cache_dir:
                cache_dir = Path(test_cache_dir)
            elif "pytest" in sys.modules or os.getenv("SHOTBOT_MODE") == "test":
                # Detect pytest automatically (takes highest priority)
                cache_dir = Path.home() / ".shotbot" / "cache_test"
            elif os.getenv("SHOTBOT_MODE") == "mock":
                cache_dir = Path.home() / ".shotbot" / "cache" / "mock"
            else:
                cache_dir = Path.home() / ".shotbot" / "cache" / "production"
        self.cache_dir = Path(cache_dir)
        self.thumbnails_dir = self.cache_dir / "thumbnails"
        self.shots_cache_file = self.cache_dir / "shots.json"
        self.previous_shots_cache_file = self.cache_dir / "previous_shots.json"
        self.threede_cache_file = self.cache_dir / "threede_scenes.json"
        self.migrated_shots_cache_file = self.cache_dir / "migrated_shots.json"
        self.latest_files_cache_file = self.cache_dir / "latest_files.json"

        # TTL configuration
        self._cache_ttl = timedelta(minutes=DEFAULT_TTL_MINUTES)
        self._latest_files_ttl = timedelta(minutes=LATEST_FILES_TTL_MINUTES)

        # Ensure directories exist
        self._ensure_cache_dirs()

        # Log initialization only once per cache directory to avoid duplicate logs
        cache_dir_str = str(self.cache_dir)
        if cache_dir_str not in CacheManager._initialized_cache_dirs:
            CacheManager._initialized_cache_dirs.add(cache_dir_str)
            self.logger.debug(f"SimpleCacheManager initialized: {self.cache_dir}")

    def _ensure_cache_dirs(self) -> None:
        """Ensure cache directories exist."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Ensured cache directory: {self.cache_dir}")
        except OSError as e:
            self.logger.error(f"Failed to create cache directories: {e}")

    def ensure_cache_directory(self) -> bool:
        """Ensure cache directory exists.

        Returns:
            True if successful

        """
        try:
            self._ensure_cache_dirs()
            return True
        except OSError:
            return False

    # ========================================================================
    # File Locking Methods (opt-in via SHOTBOT_FILE_LOCKING=enabled)
    # ========================================================================

    @contextlib.contextmanager
    def _file_lock(self, cache_file: Path):
        """Context manager for advisory file lock on cache operations.

        Only acquires lock if FILE_LOCKING_ENABLED is True and fcntl is available.
        Uses a separate .lock file to avoid conflicts with the actual cache file.

        Args:
            cache_file: The cache file being protected (lock file will be {cache_file}.lock)

        Yields:
            None - lock is held for the duration of the context

        """
        if not FILE_LOCKING_ENABLED or _fcntl is None:
            # File locking disabled or unavailable - just yield
            yield
            return

        lock_file = cache_file.with_suffix(cache_file.suffix + ".lock")
        lock_fd = None
        try:
            # Ensure parent directory exists
            lock_file.parent.mkdir(parents=True, exist_ok=True)

            # Open/create lock file
            lock_fd = lock_file.open("w")

            # Acquire exclusive lock (blocks until available)
            _fcntl.flock(lock_fd.fileno(), _fcntl.LOCK_EX)
            self.logger.debug(f"Acquired file lock: {lock_file}")

            yield

        except OSError as e:
            # Log but don't fail - fall back to no locking
            self.logger.warning(f"Failed to acquire file lock {lock_file}: {e}")
            yield

        finally:
            if lock_fd is not None:
                try:
                    # Release lock and close file
                    # Note: _fcntl is guaranteed non-None here (early return if None)
                    _fcntl.flock(lock_fd.fileno(), _fcntl.LOCK_UN)
                    lock_fd.close()
                    self.logger.debug(f"Released file lock: {lock_file}")
                except OSError as e:
                    self.logger.warning(f"Failed to release file lock: {e}")

    # ========================================================================
    # Thumbnail Caching Methods
    # ========================================================================

    def _get_file_stat_cached(self, path: Path) -> tuple[int, float] | None:
        """Get file size and mtime with caching to reduce filesystem I/O.

        Uses LRU eviction to prevent unbounded memory growth. Cache is limited
        to STAT_CACHE_MAX_SIZE entries, evicting oldest when full.

        Args:
            path: File path to stat

        Returns:
            Tuple of (size, mtime) or None if file doesn't exist or is inaccessible

        """
        import time

        path_str = str(path)
        current_time = time.time()

        # Check cache first (inside lock for thread safety)
        with QMutexLocker(self._lock):
            if path_str in self._stat_cache:
                size, mtime, cache_time = self._stat_cache[path_str]
                # Return cached result if still valid
                if current_time - cache_time < STAT_CACHE_TTL:
                    # Move to end (mark as recently used for LRU)
                    self._stat_cache.move_to_end(path_str)
                    return (size, mtime)
                # Expired - will re-stat below
                del self._stat_cache[path_str]

        # Cache miss or expired - do actual stat
        try:
            stat_result = path.stat()
            size = stat_result.st_size
            mtime = stat_result.st_mtime

            # Cache the result with LRU eviction (inside lock for thread safety)
            with QMutexLocker(self._lock):
                # Evict oldest entries if cache is full
                while len(self._stat_cache) >= STAT_CACHE_MAX_SIZE:
                    _ = self._stat_cache.popitem(last=False)  # Remove oldest (first)

                self._stat_cache[path_str] = (size, mtime, current_time)

            return (size, mtime)

        except (OSError, FileNotFoundError):
            # File doesn't exist or is inaccessible
            return None

    def get_cached_thumbnail(self, show: str, sequence: str, shot: str) -> Path | None:
        """Get path to cached thumbnail if it exists.

        Thumbnails are persistent and do not expire - they're only regenerated
        when manually cleared by the user.

        Uses cached stat results to reduce filesystem I/O overhead.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to thumbnail or None if not cached

        """
        # Compute path (no lock needed for this)
        cache_path = self.thumbnails_dir / show / sequence / f"{shot}_thumb.jpg"

        # Use cached stat to check if file exists and has content
        stat_result = self._get_file_stat_cached(cache_path)
        if stat_result is not None:
            size, _ = stat_result
            # Return path only if file has content (size > 0)
            if size > 0:
                return cache_path

        return None

    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Cache a thumbnail from source path.

        Optimized: Lock scope reduced to minimize contention. Most operations
        (path computation, file I/O, image processing) happen outside the lock.

        Args:
            source_path: Source image path
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail or None on error

        """
        source_path_obj = (
            Path(source_path) if isinstance(source_path, str) else source_path
        )

        # Validate parameters (no lock needed)
        if not all([show, sequence, shot]):
            error_msg = "Missing required parameters for thumbnail caching"
            self.logger.error(error_msg)
            raise ThumbnailError(
                error_msg,
                details={
                    "source_path": str(source_path),
                    "show": show,
                    "sequence": sequence,
                    "shot": shot,
                },
            )

        # Check source exists (no lock needed)
        if not source_path_obj.exists():
            self.logger.warning(f"Source path does not exist: {source_path_obj}")
            return None

        # Compute paths (no lock needed)
        output_dir = self.thumbnails_dir / show / sequence
        output_path = output_dir / f"{shot}_thumb.jpg"

        # Check if already cached using our cached stat (no lock needed)
        stat_result = self._get_file_stat_cached(output_path)
        if stat_result is not None:
            size, _ = stat_result
            if size > 0:
                self.logger.debug(f"Using existing thumbnail: {output_path}")
                return output_path

        # Ensure directory exists (brief lock for thread safety)
        with QMutexLocker(self._lock):
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as e:
                self.logger.error(f"Failed to create cache directories: {e}")
                return None

        # Process thumbnail WITHOUT holding lock (I/O and CPU intensive)
        try:
            return self._process_standard_thumbnail(source_path_obj, output_path)
        except Exception as e:
            self.logger.error(f"Failed to process thumbnail: {e}")
            return None

    def _process_standard_thumbnail(self, source: Path, output: Path) -> Path:
        """Process standard image formats to thumbnail.

        Args:
            source: Source image path
            output: Output thumbnail path

        Returns:
            Path to created thumbnail

        """
        temp_path = output.with_suffix(".tmp")
        try:
            with Image.open(source) as img:
                img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
                img.convert("RGB").save(temp_path, "JPEG", quality=THUMBNAIL_QUALITY)
            # Atomic rename to final path
            _ = temp_path.replace(output)
            self.logger.debug(f"Created thumbnail: {output}")
            return output
        except Exception as e:
            # Clean up temp file before attempting fallback
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            self.logger.debug(f"PIL thumbnail processing failed: {e}")

            # Try MOV fallback if PIL can't read the image (e.g., EXR files)
            self.logger.debug(f"Attempting MOV fallback for {source.name}")

            from file_discovery import FileDiscovery
            from utils import (
                ImageUtils,
            )

            mov_path = FileDiscovery.find_mov_file_for_path(source)
            if mov_path:
                self.logger.debug(f"Found MOV file for fallback: {mov_path.name}")
                extracted_frame = ImageUtils.extract_frame_from_mov(mov_path)

                try:
                    if extracted_frame and extracted_frame.exists():
                        self.logger.info(f"Successfully extracted frame from MOV: {mov_path.name}")

                        # Process the extracted JPEG frame
                        try:
                            temp_path = output.with_suffix(".tmp")
                            with Image.open(extracted_frame) as img:
                                img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
                                img.convert("RGB").save(temp_path, "JPEG", quality=THUMBNAIL_QUALITY)
                            # Atomic rename to final path
                            _ = temp_path.replace(output)
                            self.logger.debug(f"Created thumbnail from MOV fallback: {output}")
                            return output
                        except Exception as fallback_error:
                            self.logger.error(f"Failed to process MOV fallback frame: {fallback_error}")
                    else:
                        self.logger.debug("MOV frame extraction failed")
                finally:
                    # Always clean up extracted frame temp file
                    if extracted_frame and extracted_frame.exists():
                        with contextlib.suppress(Exception):
                            extracted_frame.unlink()
            else:
                self.logger.debug(f"No MOV file found for fallback: {source}")

            # If MOV fallback didn't work, raise original error
            self.logger.error(f"PIL thumbnail processing failed and MOV fallback unavailable: {e}")
            msg = f"Failed to process thumbnail: {e}"
            raise ThumbnailError(msg) from e

    def cache_thumbnail_direct(
        self,
        image: QImage,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Cache a thumbnail from QImage directly.

        Lock-minimized implementation: I/O and CPU work happen outside the lock.
        Only stat cache invalidation uses a brief lock acquisition.

        Args:
            image: QImage to cache
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail or None on error

        """
        # Compute paths (no lock needed - deterministic)
        output_dir = self.thumbnails_dir / show / sequence
        output_path = output_dir / f"{shot}_thumb.jpg"
        temp_path = output_path.with_suffix(".tmp")

        try:
            # Create directory (no lock needed - idempotent with exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Scale if needed (no lock needed - pure computation on local copy)
            if image.width() > THUMBNAIL_SIZE or image.height() > THUMBNAIL_SIZE:
                image = image.scaled(
                    THUMBNAIL_SIZE,
                    THUMBNAIL_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            # Save to temp file (no lock needed - unique temp path per shot)
            if not image.save(str(temp_path), b"JPEG", THUMBNAIL_QUALITY):
                temp_path.unlink(missing_ok=True)
                self.logger.error(f"Failed to save QImage to: {output_path}")
                return None

            # Atomic rename (no lock needed - atomic on POSIX)
            _ = temp_path.replace(output_path)

            # Invalidate stat cache for immediate visibility (minimal lock)
            with QMutexLocker(self._lock):
                _ = self._stat_cache.pop(str(output_path), None)

            self.logger.debug(f"Cached QImage thumbnail: {output_path}")
            return output_path

        except Exception as e:
            # Clean up temp file on any error
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            self.logger.error(f"QImage thumbnail caching failed: {e}")
            return None

    # ========================================================================
    # Shot Data Caching Methods
    # ========================================================================

    def get_cached_shots(self) -> list[ShotDict] | None:
        """Get cached shot list if valid.

        Returns:
            List of shot dictionaries or None if not cached/expired

        """
        result = self._read_json_cache(self.shots_cache_file)
        return cast("list[ShotDict] | None", result)

    def _cache_shot_list(
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
        shot_dicts = [_shot_to_dict(s) for s in shots]
        success = self._write_json_cache(cache_file, shot_dicts)
        if success:
            self.cache_updated.emit()
        else:
            self.logger.warning(
                f"Failed to write {cache_name} cache - data may not persist across restarts"
            )
            self.cache_write_failed.emit(cache_name)

    def cache_shots(self, shots: Sequence[Shot] | Sequence[ShotDict]) -> None:
        """Cache shot list to file.

        Args:
            shots: Sequence of Shot objects or shot dictionaries

        """
        self._cache_shot_list(shots, self.shots_cache_file, "shots")

    def get_persistent_shots(self) -> list[ShotDict] | None:
        """Get My Shots cache without TTL expiration.

        Similar to get_persistent_previous_shots() but for active shots.
        Enables incremental caching by preserving shot history.

        Returns:
            List of shot dictionaries or None if not cached

        """
        result = self._read_json_cache(self.shots_cache_file, check_ttl=False)
        return cast("list[ShotDict] | None", result)

    def get_migrated_shots(self) -> list[ShotDict] | None:
        """Get shots that were migrated from My Shots.

        Returns persistent cache without TTL. These are shots that
        disappeared from ws -sg (e.g., approved/completed).

        Returns:
            List of shot dictionaries or None if not cached

        """
        result = self._read_json_cache(self.migrated_shots_cache_file, check_ttl=False)
        return cast("list[ShotDict] | None", result)

    def migrate_shots_to_previous(self, shots: list[Shot | ShotDict]) -> bool:
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
        to_migrate = [_shot_to_dict(s) for s in shots]

        # Phase 2-4: Read, merge, write under lock for thread and process safety
        # File lock protects against concurrent processes (opt-in via SHOTBOT_FILE_LOCKING=enabled)
        # QMutex protects against concurrent threads within this process
        with self._file_lock(self.migrated_shots_cache_file), QMutexLocker(self._lock):
            # Read existing shots
            existing = self.get_migrated_shots() or []

            # Merge and deduplicate
            shots_by_key: dict[tuple[str, str, str], ShotDict] = {}

            # Add existing first
            for shot in existing:
                key = _get_shot_key(shot)
                shots_by_key[key] = shot

            # Add/update with new migrations (overwrites if duplicate)
            for shot in to_migrate:
                key = _get_shot_key(shot)
                shots_by_key[key] = shot

            merged = list(shots_by_key.values())

            # Write atomically (inside lock to prevent concurrent write races)
            write_success = self._write_json_cache(
                self.migrated_shots_cache_file, merged
            )

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
            self.cache_write_failed.emit("migrated_shots")

        return write_success

    def get_cached_previous_shots(self) -> list[ShotDict] | None:
        """Get cached previous/approved shot list if valid.

        Returns:
            List of shot dictionaries or None if not cached/expired

        """
        result = self._read_json_cache(self.previous_shots_cache_file)
        return cast("list[ShotDict] | None", result)

    def get_persistent_previous_shots(self) -> list[ShotDict] | None:
        """Get cached previous/approved shot list without TTL expiration.

        This method returns the cached previous shots regardless of age,
        implementing persistent incremental caching where shots accumulate
        over time without expiration.

        Returns:
            List of shot dictionaries or None if not cached

        """
        result = self._read_json_cache(self.previous_shots_cache_file, check_ttl=False)
        return cast("list[ShotDict] | None", result)

    def cache_previous_shots(self, shots: Sequence[Shot] | Sequence[ShotDict]) -> None:
        """Cache previous/approved shot list to file.

        Args:
            shots: Sequence of Shot objects or shot dictionaries

        """
        self._cache_shot_list(shots, self.previous_shots_cache_file, "previous_shots")

    @staticmethod
    def _build_merge_lookups(
        cached: Sequence[object] | None,
        fresh: Sequence[object],
        to_dict_fn: Callable[[object], _D],
        get_key_fn: Callable[[_D], tuple[str, str, str]],
    ) -> tuple[list[_D], list[_D], dict[tuple[str, str, str], _D], set[tuple[str, str, str]]]:
        """Build lookup structures shared by merge_shots_incremental and merge_scenes_incremental.

        Acquires the caller's lock externally is NOT done here — callers should
        pass already-copied sequences. This helper operates purely on local data.

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

    def merge_shots_incremental(
        self,
        cached: list[Shot | ShotDict] | None,
        fresh: list[Shot | ShotDict],
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
                self._build_merge_lookups(cached, fresh, _shot_to_dict, _get_shot_key)
            )

        # Phase 2: All merge logic outside lock (CPU-bound, no shared state)
        # Merge: Single O(n) pass using fresh data as source of truth
        updated_shots: list[ShotDict] = []
        new_shots: list[ShotDict] = []

        for fresh_shot in fresh_dicts:
            fresh_key = _get_shot_key(fresh_shot)
            updated_shots.append(fresh_shot)  # Always use fresh data

            if fresh_key not in cached_by_key:
                # This is a new shot (not in cache)
                new_shots.append(fresh_shot)

        # Identify removed (cached keys not in fresh)
        removed_shots = [
            shot for shot in cached_dicts if _get_shot_key(shot) not in fresh_keys
        ]

        has_changes = bool(new_shots or removed_shots)

        return ShotMergeResult(
            updated_shots=updated_shots,
            new_shots=new_shots,
            removed_shots=removed_shots,
            has_changes=has_changes,
        )

    def get_cached_threede_scenes(self) -> list[ThreeDESceneDict] | None:
        """Get cached 3DE scene list if valid.

        Returns:
            List of scene dictionaries or None if not cached/expired

        """
        result = self._read_json_cache(self.threede_cache_file)
        # Type narrowing: the cache file contains ThreeDESceneDict when written by cache_threede_scenes
        # Runtime validation ensures this is safe
        return cast("list[ThreeDESceneDict] | None", result)

    def get_persistent_threede_scenes(self) -> list[ThreeDESceneDict] | None:
        """Get cached 3DE scenes without TTL expiration.

        Enables incremental caching by preserving scene history across scans.
        Similar to get_persistent_previous_shots() but for 3DE scenes.

        Returns:
            List of scene dictionaries or None if not cached

        """
        result = self._read_json_cache(self.threede_cache_file, check_ttl=False)
        # Type narrowing: the cache file contains ThreeDESceneDict when written by cache_threede_scenes
        # Runtime validation ensures this is safe
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

    def cache_threede_scenes(
        self,
        scenes: list[ThreeDESceneDict],
        _metadata: dict[str, object] | None = None,
    ) -> None:
        """Cache 3DE scene list to file.

        Args:
            scenes: List of scene dictionaries
            metadata: Optional metadata (ignored in simple implementation)

        """
        success = self._write_json_cache(self.threede_cache_file, scenes)
        if success:
            self.cache_updated.emit()
        else:
            self.logger.warning(
                "Failed to write 3DE scenes cache - data may not persist across restarts"
            )
            self.cache_write_failed.emit("threede_scenes")

    def merge_scenes_incremental(
        self,
        cached: Sequence[object] | None,
        fresh: Sequence[object],
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

        Note: Uses shot-level key (show, sequence, shot) since deduplication
        is applied after merge to keep best scene per shot.

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
        # This protects against concurrent modification of input sequences
        with QMutexLocker(self._lock):
            _, fresh_dicts, cached_by_key, fresh_keys = (
                self._build_merge_lookups(cached, fresh, _scene_to_dict, _get_scene_key)
            )

        # Phase 2: All CPU-bound merge logic OUTSIDE lock
        # These operate on local copies, no shared state mutation

        # Merge: fresh scenes override cached (UPDATE or ADD)
        updated_by_key: dict[tuple[str, str, str], ThreeDESceneDict] = {}
        new_scenes: list[ThreeDESceneDict] = []
        pruned_count = 0

        # Process fresh scenes (always include, update last_seen)
        for fresh_scene in fresh_dicts:
            fresh_key = _get_scene_key(fresh_scene)
            if fresh_key not in cached_by_key:
                new_scenes.append(fresh_scene)
            # Update last_seen and add to result
            updated_scene = dict(fresh_scene)
            updated_scene["last_seen"] = now
            updated_by_key[fresh_key] = cast("ThreeDESceneDict", updated_scene)

        # Process cached scenes not in fresh (apply age-based pruning)
        removed_keys = set(cached_by_key.keys()) - fresh_keys
        removed_scenes: list[ThreeDESceneDict] = []

        for key in removed_keys:
            cached_scene = cached_by_key[key]
            # Get last_seen (default to now for legacy cache entries)
            scene_last_seen = cached_scene.get("last_seen", now)
            if scene_last_seen >= cutoff:
                # Within retention window - keep it
                updated_by_key[key] = cached_scene
                removed_scenes.append(cached_scene)  # Track as "not in fresh"
            else:
                # Too old - prune it
                pruned_count += 1

        # All scenes (kept + updated + new)
        updated_scenes = list(updated_by_key.values())
        has_changes = bool(new_scenes or removed_scenes or pruned_count > 0)

        return SceneMergeResult(
            updated_scenes=updated_scenes,
            new_scenes=new_scenes,
            removed_scenes=removed_scenes,
            has_changes=has_changes,
            pruned_count=pruned_count,
        )

    # ========================================================================
    # Latest File Cache Methods (Maya/3DE scene paths per workspace)
    # ========================================================================

    def get_cached_latest_file(
        self,
        workspace_path: str,
        file_type: str,
    ) -> Path | None:
        """Get cached latest file path for a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            file_type: Type of file ("maya" or "threede")

        Returns:
            Cached file path or None if not cached/expired

        """
        cache_data = self._read_latest_files_cache()
        if cache_data is None:
            return None

        # Create composite key
        key = f"{workspace_path}:{file_type}"
        entry = cache_data.get(key)
        if entry is None:
            return None

        # Check TTL
        cached_at_raw = entry.get("cached_at", 0.0)
        if isinstance(cached_at_raw, (int, float)):
            cached_at = float(cached_at_raw)
        else:
            cached_at = 0.0
        age = datetime.now(tz=UTC).timestamp() - cached_at
        if age > self._latest_files_ttl.total_seconds():
            self.logger.debug(f"Latest file cache expired for {key}")
            return None

        # Return cached path
        path_str = entry.get("path")
        if path_str and isinstance(path_str, str):
            cached_path = Path(path_str)
            # Verify file still exists
            if cached_path.exists():
                self.logger.debug(f"Latest file cache hit: {cached_path.name}")
                return cached_path
            self.logger.debug(f"Cached file no longer exists: {path_str}")
        return None

    def cache_latest_file(
        self,
        workspace_path: str,
        file_type: str,
        file_path: Path | None,
    ) -> None:
        """Cache the latest file path for a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            file_type: Type of file ("maya" or "threede")
            file_path: Path to cache (or None to cache "not found" result)

        """
        cache_data = self._read_latest_files_cache() or {}

        # Create composite key
        key = f"{workspace_path}:{file_type}"

        # Store entry with timestamp
        cache_data[key] = {
            "path": str(file_path) if file_path else None,
            "cached_at": datetime.now(tz=UTC).timestamp(),
        }

        _ = self._write_latest_files_cache(cache_data)
        if file_path:
            self.logger.debug(f"Cached latest {file_type} file: {file_path.name}")
        else:
            self.logger.debug(f"Cached 'not found' for {file_type} in {workspace_path}")

    def clear_latest_files_cache(self, workspace_path: str | None = None) -> None:
        """Clear the latest files cache.

        Args:
            workspace_path: If provided, only clear cache for this workspace.
                          If None, clear entire cache.

        """
        if workspace_path is None:
            # Clear entire cache
            if self.latest_files_cache_file.exists():
                self.latest_files_cache_file.unlink()
                self.logger.debug("Cleared all latest files cache")
        else:
            # Clear only entries for this workspace
            cache_data = self._read_latest_files_cache()
            if cache_data:
                keys_to_remove = [
                    k for k in cache_data if k.startswith(f"{workspace_path}:")
                ]
                for key in keys_to_remove:
                    del cache_data[key]
                _ = self._write_latest_files_cache(cache_data)
                self.logger.debug(
                    f"Cleared latest files cache for workspace: {workspace_path}"
                )

    def has_cache_entry(self, workspace_path: str, file_type: str) -> bool:
        """Check if a cache entry exists for a workspace/file_type (regardless of value).

        Unlike get_cached_latest_file(), this returns True even when the cached
        result is None (i.e., a "not found" result was cached), letting callers
        distinguish between "cache miss - need to search" and "searched, found nothing".

        Args:
            workspace_path: Full path to the shot workspace
            file_type: Type of file ("maya" or "threede")

        Returns:
            True if an entry exists in the cache (even if the path is None), False if no entry

        """
        cache_data = self._read_latest_files_cache()
        if cache_data is None:
            return False
        key = f"{workspace_path}:{file_type}"
        return key in cache_data

    def _read_latest_files_cache(self) -> dict[str, dict[str, object]] | None:
        """Read the latest files cache from disk.

        Returns:
            Cache data as dict or None if not found

        """
        if not self.latest_files_cache_file.exists():
            return None

        try:
            with self.latest_files_cache_file.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return cast("dict[str, dict[str, object]]", data)
            return None
        except Exception as e:
            self.logger.error(f"Failed to read latest files cache: {e}")
            return None

    def _write_latest_files_cache(
        self,
        data: dict[str, dict[str, object]],
    ) -> bool:
        """Write the latest files cache to disk.

        Args:
            data: Cache data to write

        Returns:
            True if successful, False otherwise

        """
        try:
            self._atomic_json_write(
                self.latest_files_cache_file, data, indent=2, fsync=False
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to write latest files cache: {e}")
            return False

    # ========================================================================
    # Generic Data Caching Methods (backward compatibility)
    # ========================================================================

    def cache_data(self, key: str, data: object) -> None:
        """Cache generic data with a key.

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
            _ = self._write_json_cache(cache_file, data)

    def get_cached_data(self, key: str) -> object | None:
        """Get cached generic data by key.

        Args:
            key: Cache key identifier

        Returns:
            Cached data or None if not found/expired

        """
        if key == "previous_shots":
            return self.get_cached_previous_shots()
        cache_file = self.cache_dir / f"{key}.json"
        return self._read_json_cache(cache_file)

    def clear_cached_data(self, key: str) -> None:
        """Clear cached generic data by key.

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
    # Cache Management Methods
    # ========================================================================

    def clear_cache(self) -> None:
        """Clear all cached data."""
        with QMutexLocker(self._lock):
            try:
                # Clear stat result cache
                self._stat_cache.clear()

                # Clear JSON caches
                for cache_file in [
                    self.shots_cache_file,
                    self.previous_shots_cache_file,
                    self.threede_cache_file,
                ]:
                    if cache_file.exists():
                        cache_file.unlink()

                # Clear thumbnails
                if self.thumbnails_dir.exists():
                    shutil.rmtree(self.thumbnails_dir)
                    self.thumbnails_dir.mkdir(parents=True, exist_ok=True)

                self.logger.info("Cache cleared successfully")
                self.cache_updated.emit()

                # Also invalidate ProcessPoolManager's in-memory command cache
                # to prevent stale workspace command output after cache clear
                try:
                    from process_pool_manager import ProcessPoolManager
                    pool = ProcessPoolManager.get_instance()
                    pool.invalidate_cache()
                except Exception:
                    pass  # ProcessPoolManager may not be initialized yet

            except Exception as e:
                self.logger.error(f"Failed to clear cache: {e}")

    def get_memory_usage(self) -> dict[str, float | int | str]:
        """Get cache memory usage statistics.

        Returns:
            Dictionary with cache size information

        """
        try:
            total_size = 0
            file_count = 0
            thumbnail_count = 0

            # Count thumbnails
            if self.thumbnails_dir.exists():
                for item in self.thumbnails_dir.rglob("*"):
                    if item.is_file():
                        total_size += item.stat().st_size
                        file_count += 1
                        thumbnail_count += 1

            # Count JSON files
            for cache_file in [
                self.shots_cache_file,
                self.previous_shots_cache_file,
                self.threede_cache_file,
            ]:
                if cache_file.exists():
                    total_size += cache_file.stat().st_size
                    file_count += 1

            return {
                "total_mb": total_size / (1024 * 1024),
                "file_count": file_count,
                "thumbnail_count": thumbnail_count,
                "thumbnail_dir": str(self.thumbnails_dir),
            }

        except Exception as e:
            self.logger.error(f"Failed to get memory usage: {e}")
            return {"total_mb": 0.0, "file_count": 0, "thumbnail_count": 0}

    # ========================================================================
    # Configuration Properties (backward compatibility)
    # ========================================================================

    @property
    def CACHE_THUMBNAIL_SIZE(self) -> int:
        """Get the cached thumbnail size."""
        return THUMBNAIL_SIZE

    @property
    def CACHE_EXPIRY_MINUTES(self) -> int:
        """Get cache expiry time in minutes."""
        return DEFAULT_TTL_MINUTES

    def set_expiry_minutes(self, expiry_minutes: int) -> None:
        """Set cache expiry time.

        Args:
            expiry_minutes: Cache TTL in minutes

        """
        self._cache_ttl = timedelta(minutes=expiry_minutes)
        self.logger.debug(f"Cache TTL set to {expiry_minutes} minutes")

    # ========================================================================
    # Internal Helper Methods
    # ========================================================================

    def _read_json_cache(
        self, cache_file: Path, check_ttl: bool = True
    ) -> list[ShotDict | ThreeDESceneDict] | None:
        """Read and validate JSON cache file.

        Args:
            cache_file: Path to cache file
            check_ttl: Whether to check TTL expiration (default True)

        Returns:
            Cached data or None if not found/expired/invalid

        """
        if not cache_file.exists():
            return None

        try:
            # Check TTL (if enabled)
            if check_ttl:
                age = datetime.now(tz=UTC) - datetime.fromtimestamp(
                    cache_file.stat().st_mtime, tz=UTC
                )
                if age > self._cache_ttl:
                    self.logger.debug(f"Cache expired: {cache_file}")
                    return None

            # Read JSON - returns JSONValue which we validate at runtime
            with Path(cache_file).open(encoding="utf-8") as f:
                raw_data: JSONValue = cast("JSONValue", json.load(f))

            # Validate structure through runtime checks and type narrowing
            if isinstance(raw_data, list):
                # Direct list format - validate ALL elements are dicts (not just first)
                # Uses generator for early exit on first non-dict
                if raw_data and not all(isinstance(item, dict) for item in raw_data):
                    self.logger.warning(
                        f"Invalid cache format: expected list of dicts in {cache_file}"
                    )
                    return None
                return cast("list[ShotDict | ThreeDESceneDict]", raw_data)

            if isinstance(raw_data, dict):
                # Handle wrapped format: {"data": [...], "cached_at": "..."}
                # Try nested keys: data.data, data.shots, data.scenes
                result: JSONValue = raw_data.get("data")
                if result is None:
                    result = raw_data.get("shots")
                if result is None:
                    result = raw_data.get("scenes", [])

                if isinstance(result, list):
                    # Validate ALL elements are dicts (not just first)
                    if result and not all(isinstance(item, dict) for item in result):
                        self.logger.warning(
                            f"Invalid cache format: expected list of dicts in {cache_file}"
                        )
                        return None
                    return cast("list[ShotDict | ThreeDESceneDict]", result)
                return []

            self.logger.warning(
                f"Unexpected cache format: {cache_file}, type: {type(raw_data)}"
            )
            return None

        except Exception as e:
            self.logger.error(f"Failed to read cache file {cache_file}: {e}")
            return None

    @staticmethod
    def _atomic_json_write(
        path: Path,
        payload: object,
        *,
        indent: int | None,
        fsync: bool,
    ) -> None:
        """Write *payload* as JSON to *path* atomically using a temp file + os.replace().

        Raises on error — callers are responsible for exception handling and logging.

        Args:
            path: Destination file path (parent directory must already exist)
            payload: JSON-serializable data to write
            indent: JSON indentation level (None = compact, 2 = pretty)
            fsync: If True, flush and fsync before the atomic rename

        """
        fd, temp_path = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=indent)
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())
            # Atomic rename (POSIX guarantees atomicity on same filesystem)
            _ = Path(temp_path).replace(path)
        except Exception:
            # Clean up temp file on error
            with contextlib.suppress(OSError):
                Path(temp_path).unlink()
            raise

    def _write_json_cache(self, cache_file: Path, data: object) -> bool:
        """Write data to JSON cache file atomically.

        Args:
            cache_file: Path to cache file
            data: Data to cache

        Returns:
            True if write succeeded, False on error

        """
        try:
            # Ensure directory exists
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            # Simple format with metadata
            cache_data = {
                "data": data,
                "cached_at": datetime.now(tz=UTC).isoformat(),
            }

            # Atomic write: write to temp file, then rename
            # os.replace() is atomic on POSIX, ensuring readers see either old or new file, never partial
            self._atomic_json_write(cache_file, cache_data, indent=None, fsync=True)
            self.logger.debug(f"Cached data to: {cache_file}")
            return True

        except (OSError, TypeError, ValueError) as e:
            self.logger.error(f"Failed to write cache file {cache_file}: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown cache manager (backward compatibility stub).

        The simplified cache manager doesn't need cleanup on shutdown.
        This method exists for backward compatibility with cleanup_manager.py.
        """
        self.logger.debug("Cache manager shutdown called (no-op in simplified version)")
