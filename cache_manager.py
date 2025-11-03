"""Simplified cache manager for shot data and thumbnails.

This is a streamlined replacement for the complex cache architecture,
designed for a local VFX tool on a secure network.

Caching Strategies:
- Thumbnails: Persistent (no expiration, manual clear only)
- Shot data (shots.json): 30-minute TTL
- Previous shots (previous_shots.json): 30-minute TTL
- 3DE scenes (threede_scenes.json): 30-minute TTL

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
- No platform-specific file locking (basic QMutex only)
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypeAlias, cast

# Third-party imports
from PIL import Image
from PySide6.QtCore import QMutex, QMutexLocker, QObject, Qt, Signal

# Local application imports
from exceptions import ThumbnailError
from logging_mixin import LoggingMixin

if TYPE_CHECKING:
    from collections.abc import Sequence

    from PySide6.QtGui import QImage

    from shot_model import Shot
    from type_definitions import ShotDict, ThreeDESceneDict

# Type alias for JSON data (used for runtime validation) - Python 3.11 compatible
JSONValue: TypeAlias = (
    dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None
)

# Constants
DEFAULT_TTL_MINUTES = 30
THUMBNAIL_SIZE = 256
THUMBNAIL_QUALITY = 85


# Incremental merging support
class ShotMergeResult(NamedTuple):
    """Result of incremental shot merge operation."""

    updated_shots: list[ShotDict]  # All shots (kept + new)
    new_shots: list[ShotDict]  # Just new additions
    removed_shots: list[ShotDict]  # No longer in fresh data
    has_changes: bool  # Any changes detected


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


def _shot_to_dict(shot: Shot | ShotDict) -> ShotDict:
    """Convert Shot object or ShotDict to ShotDict.

    Args:
        shot: Shot object with to_dict() method or ShotDict

    Returns:
        ShotDict with all required fields
    """
    if isinstance(shot, dict):
        return shot
    return shot.to_dict()


# Backward compatibility exports from old cache system
class ThumbnailCacheResult:
    """Stub for backward compatibility - no longer used in simplified implementation."""

    def __init__(self) -> None:
        super().__init__()
        self.future = None
        self.path = None
        self.is_complete = False


class ThumbnailCacheLoader:
    """Stub for backward compatibility - no longer used in simplified implementation."""


class CacheManager(LoggingMixin, QObject):
    """Simplified cache manager for local VFX tool.

    Provides same public API as CacheManager but with simpler implementation.
    """

    # Signals - maintain backward compatibility
    cache_updated = Signal()
    shots_migrated = Signal(list)  # Emitted when shots migrate to Previous Shots

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

        # Setup cache directory
        if cache_dir is None:
            # Standard library imports
            import sys

            # Use default cache location based on mode
            # Detect pytest automatically (takes highest priority)
            is_pytest = "pytest" in sys.modules

            if is_pytest or os.getenv("SHOTBOT_MODE") == "test":
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

        # TTL configuration
        self._cache_ttl = timedelta(minutes=DEFAULT_TTL_MINUTES)

        # Ensure directories exist
        self._ensure_cache_dirs()

        self.logger.info(f"SimpleCacheManager initialized: {self.cache_dir}")

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
    # Thumbnail Caching Methods
    # ========================================================================

    def get_cached_thumbnail(self, show: str, sequence: str, shot: str) -> Path | None:
        """Get path to cached thumbnail if it exists.

        Thumbnails are persistent and do not expire - they're only regenerated
        when manually cleared by the user.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to thumbnail or None if not cached
        """
        with QMutexLocker(self._lock):
            cache_path = self.thumbnails_dir / show / sequence / f"{shot}_thumb.jpg"

            if cache_path.exists():
                return cache_path

            return None

    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
        wait: bool = True,
        timeout: float | None = None,
    ) -> Path | None:
        """Cache a thumbnail from source path.

        Args:
            source_path: Source image path
            show: Show name
            sequence: Sequence name
            shot: Shot name
            wait: Ignored in simplified implementation (always synchronous)
            timeout: Ignored in simplified implementation

        Returns:
            Path to cached thumbnail or None on error
        """
        source_path_obj = (
            Path(source_path) if isinstance(source_path, str) else source_path
        )

        # Validate parameters
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

        if not source_path_obj.exists():
            self.logger.warning(f"Source path does not exist: {source_path_obj}")
            return None

        with QMutexLocker(self._lock):
            # Create output directory
            output_dir = self.thumbnails_dir / show / sequence
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as e:
                self.logger.error(f"Failed to create cache directories: {e}")
                return None
            output_path = output_dir / f"{shot}_thumb.jpg"

            # Already cached? (thumbnails are persistent)
            if output_path.exists():
                self.logger.debug(f"Using existing thumbnail: {output_path}")
                return output_path

            # Process as standard thumbnail (JPEG/PNG only - no EXR support)
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
        try:
            img = Image.open(source)
            img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
            img.convert("RGB").save(output, "JPEG", quality=THUMBNAIL_QUALITY)
            self.logger.debug(f"Created thumbnail: {output}")
            return output
        except Exception as e:
            self.logger.debug(f"PIL thumbnail processing failed: {e}")

            # Try MOV fallback if PIL can't read the image (e.g., EXR files)
            self.logger.debug(f"Attempting MOV fallback for {source.name}")

            from utils import ImageUtils, PathUtils

            mov_path = PathUtils.find_mov_file_for_path(source)
            if mov_path:
                self.logger.debug(f"Found MOV file for fallback: {mov_path.name}")
                extracted_frame = ImageUtils.extract_frame_from_mov(mov_path)

                if extracted_frame and extracted_frame.exists():
                    self.logger.info(f"Successfully extracted frame from MOV: {mov_path.name}")

                    # Process the extracted JPEG frame
                    try:
                        img = Image.open(extracted_frame)
                        img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
                        img.convert("RGB").save(output, "JPEG", quality=THUMBNAIL_QUALITY)
                        self.logger.debug(f"Created thumbnail from MOV fallback: {output}")

                        # Clean up temp file
                        try:
                            extracted_frame.unlink()
                        except Exception:
                            pass

                        return output
                    except Exception as fallback_error:
                        self.logger.error(f"Failed to process MOV fallback frame: {fallback_error}")
                else:
                    self.logger.debug("MOV frame extraction failed")
            else:
                self.logger.debug(f"No MOV file found for fallback: {source}")

            # If MOV fallback didn't work, raise original error
            self.logger.error(f"PIL thumbnail processing failed and MOV fallback unavailable: {e}")
            raise ThumbnailError(f"Failed to process thumbnail: {e}") from e

    def cache_thumbnail_direct(
        self,
        image: QImage,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Cache a thumbnail from QImage directly.

        Args:
            image: QImage to cache
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail or None on error
        """
        with QMutexLocker(self._lock):
            output_dir = self.thumbnails_dir / show / sequence
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{shot}_thumb.jpg"

            try:
                # Scale if needed
                if image.width() > THUMBNAIL_SIZE or image.height() > THUMBNAIL_SIZE:
                    image = image.scaled(
                        THUMBNAIL_SIZE,
                        THUMBNAIL_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

                # Save - QImage.save() accepts str or bytes for format parameter
                if image.save(str(output_path), b"JPEG", THUMBNAIL_QUALITY):
                    self.logger.debug(f"Cached QImage thumbnail: {output_path}")
                    return output_path
                self.logger.error(f"Failed to save QImage to: {output_path}")
                return None

            except Exception as e:
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
        return self._read_json_cache(self.shots_cache_file)

    def cache_shots(self, shots: Sequence[Shot] | Sequence[ShotDict]) -> None:
        """Cache shot list to file.

        Args:
            shots: Sequence of Shot objects or shot dictionaries
        """
        # Convert Shot objects to dicts
        shot_dicts: list[ShotDict] = []
        for shot in shots:
            if isinstance(shot, dict):
                shot_dicts.append(shot)
            else:
                # Assume Shot object with to_dict method - TYPE_CHECKING import prevents runtime check
                shot_dicts.append(shot.to_dict())

        self._write_json_cache(self.shots_cache_file, shot_dicts)
        self.cache_updated.emit()

    def get_persistent_shots(self) -> list[ShotDict] | None:
        """Get My Shots cache without TTL expiration.

        Similar to get_persistent_previous_shots() but for active shots.
        Enables incremental caching by preserving shot history.

        Returns:
            List of shot dictionaries or None if not cached
        """
        return self._read_json_cache(self.shots_cache_file, check_ttl=False)

    def get_migrated_shots(self) -> list[ShotDict] | None:
        """Get shots that were migrated from My Shots.

        Returns persistent cache without TTL. These are shots that
        disappeared from ws -sg (e.g., approved/completed).

        Returns:
            List of shot dictionaries or None if not cached
        """
        return self._read_json_cache(self.migrated_shots_cache_file, check_ttl=False)

    def migrate_shots_to_previous(self, shots: list[Shot | ShotDict]) -> None:
        """Move removed shots to Previous Shots migration cache.

        Merges with existing migrated shots (deduplicates by composite key).

        Args:
            shots: List of Shot objects or ShotDicts to migrate

        Design:
            Uses (show, sequence, shot) composite key for consistent deduplication.
        """
        if not shots:
            return

        with QMutexLocker(self._lock):
            # Load existing migrated shots
            existing = self.get_migrated_shots() or []

            # Convert to dicts using helper
            to_migrate = [_shot_to_dict(s) for s in shots]

            # Merge and deduplicate using composite key
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

            # Write atomically (check return value for success)
            write_success = self._write_json_cache(
                self.migrated_shots_cache_file, merged
            )

            if write_success:
                self.logger.info(
                    (f"Migrated {len(to_migrate)} shots to Previous "
                    f"(total: {len(merged)} after dedup)")
                )
                # Emit specific signal (NOT generic cache_updated)
                self.shots_migrated.emit(to_migrate)
            else:
                self.logger.error(
                    f(("Failed to persist {len(to_migrate)} migrated shots to disk. "
                    "Migration will be lost on restart."))
                )

    def get_cached_previous_shots(self) -> list[ShotDict] | None:
        """Get cached previous/approved shot list if valid.

        Returns:
            List of shot dictionaries or None if not cached/expired
        """
        return self._read_json_cache(self.previous_shots_cache_file)

    def get_persistent_previous_shots(self) -> list[ShotDict] | None:
        """Get cached previous/approved shot list without TTL expiration.

        This method returns the cached previous shots regardless of age,
        implementing persistent incremental caching where shots accumulate
        over time without expiration.

        Returns:
            List of shot dictionaries or None if not cached
        """
        return self._read_json_cache(self.previous_shots_cache_file, check_ttl=False)

    def cache_previous_shots(self, shots: Sequence[Shot] | Sequence[ShotDict]) -> None:
        """Cache previous/approved shot list to file.

        Args:
            shots: Sequence of Shot objects or shot dictionaries
        """
        shot_dicts: list[ShotDict] = []
        for shot in shots:
            if isinstance(shot, dict):
                shot_dicts.append(shot)
            else:
                # Assume Shot object with to_dict method - TYPE_CHECKING import prevents runtime check
                shot_dicts.append(shot.to_dict())

        self._write_json_cache(self.previous_shots_cache_file, shot_dicts)
        self.cache_updated.emit()

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
            Protected by internal mutex to prevent concurrent merge operations
            that could produce inconsistent results.
        """
        with QMutexLocker(self._lock):
            # Convert to dicts using helper (from Phase 1 Task 2)
            cached_dicts = [_shot_to_dict(s) for s in (cached or [])]
            fresh_dicts = [_shot_to_dict(s) for s in fresh]

            # Build lookups using composite key (O(1) operations)
            cached_by_key: dict[tuple[str, str, str], ShotDict] = {
                _get_shot_key(shot): shot for shot in cached_dicts
            }
            fresh_keys = {_get_shot_key(shot) for shot in fresh_dicts}

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

    def has_valid_threede_cache(self) -> bool:
        """Check if we have a valid 3DE cache.

        Returns:
            True if cache exists and is valid
        """
        cached = self.get_cached_threede_scenes()
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
        self._write_json_cache(self.threede_cache_file, scenes)
        self.cache_updated.emit()

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
            self._write_json_cache(cache_file, data)

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
    # Stub Methods (for backward compatibility, no-ops in simple implementation)
    # ========================================================================

    def clear_failed_attempts(self, _cache_key: str | None = None) -> None:
        """Clear failed attempts (no-op in simple implementation).

        Args:
            cache_key: Ignored
        """
        # No failure tracking in simple implementation

    def get_failed_attempts_status(self) -> dict[str, dict[str, object]]:
        """Get failed attempts status (always empty in simple implementation).

        Returns:
            Empty dictionary
        """
        return {}

    def set_memory_limit(self, _max_memory_mb: int) -> None:
        """Set memory limit (no-op in simple implementation).

        Args:
            max_memory_mb: Ignored
        """
        # No memory management in simple implementation

    def get_failure_status(self) -> dict[str, object]:
        """Get failure status (always empty in simple implementation).

        Returns:
            Empty dictionary
        """
        return {}

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
                age = datetime.now() - datetime.fromtimestamp(
                    cache_file.stat().st_mtime
                )
                if age > self._cache_ttl:
                    self.logger.debug(f"Cache expired: {cache_file}")
                    return None

            # Read JSON - returns JSONValue which we validate at runtime
            with open(cache_file) as f:
                raw_data: JSONValue = cast("JSONValue", json.load(f))

            # Validate structure through runtime checks and type narrowing
            if isinstance(raw_data, list):
                # Direct list format - validate it's a list of dicts
                if raw_data and not isinstance(raw_data[0], dict):
                    self.logger.warning(
                        f"Invalid cache format: expected list of dicts, got list of {type(raw_data[0])}"
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
                    # Validate it's a list of dicts
                    if result and not isinstance(result[0], dict):
                        self.logger.warning(
                            f"Invalid cache format: expected list of dicts, got list of {type(result[0])}"
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
                "cached_at": datetime.now().isoformat(),
            }

            # Atomic write: write to temp file, then rename
            # os.replace() is atomic on POSIX, ensuring readers see either old or new file, never partial
            fd, temp_path = tempfile.mkstemp(
                dir=cache_file.parent, prefix=f".{cache_file.name}.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(cache_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk

                # Atomic rename (POSIX guarantees atomicity on same filesystem)
                os.replace(temp_path, cache_file)

                self.logger.debug(f"Cached data to: {cache_file}")
                return True

            except Exception:
                # Clean up temp file on error
                with contextlib.suppress(OSError):
                    os.unlink(temp_path)
                raise

        except (OSError, TypeError, ValueError) as e:
            self.logger.error(f"Failed to write cache file {cache_file}: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown cache manager (backward compatibility stub).

        The simplified cache manager doesn't need cleanup on shutdown.
        This method exists for backward compatibility with cleanup_manager.py.
        """
        self.logger.debug("Cache manager shutdown called (no-op in simplified version)")
