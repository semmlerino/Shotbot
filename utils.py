"""Common utilities for ShotBot application."""

from __future__ import annotations

# Standard library imports
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

# Local application imports
from config import Config
from logging_mixin import get_module_logger

if TYPE_CHECKING:
    # Standard library imports
    from types import TracebackType

    # Third-party imports
    from PySide6.QtCore import QSize

# Performance monitoring removed - was using archived module

# Set up logger for this module
logger = get_module_logger(__name__)

# Cache for path existence checks (with TTL)
_path_cache: dict[str, tuple[bool, float]] = {}
_path_cache_lock = threading.Lock()  # Thread-safety for path cache access
_PATH_CACHE_TTL = 0.0  # seconds - 0 = no automatic expiry, manual refresh only
_cache_disabled = False  # Test isolation flag


def clear_all_caches() -> None:
    """Clear all utility caches - useful for testing or debugging."""
    global _path_cache
    with _path_cache_lock:
        _path_cache.clear()
    VersionUtils.clear_version_cache()
    # Clear lru_cache decorated functions
    VersionUtils.extract_version_from_path.cache_clear()
    logger.info("Cleared all utility caches")


def disable_caching() -> None:
    """Disable caching completely - useful for testing."""
    global _cache_disabled
    _cache_disabled = True
    clear_all_caches()
    logger.debug("Caching disabled for testing")


def enable_caching() -> None:
    """Re-enable caching after testing."""
    global _cache_disabled
    _cache_disabled = False
    logger.debug("Caching re-enabled after testing")


class CacheIsolation:
    """Context manager for cache isolation in tests."""

    def __init__(self) -> None:
        super().__init__()
        self.original_cache_state: dict[str, tuple[bool, float]] | None = None
        self.original_disabled_state: bool | None = None

    def __enter__(self) -> CacheIsolation:
        """Enter context with isolated cache."""
        global _path_cache, _cache_disabled
        # Save original state
        with _path_cache_lock:
            self.original_cache_state = _path_cache.copy()
        self.original_disabled_state = _cache_disabled

        # Clear and disable cache
        clear_all_caches()
        disable_caching()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context and restore original state."""
        global _path_cache, _cache_disabled
        # Restore original state
        with _path_cache_lock:
            _path_cache.clear()
            if self.original_cache_state is not None:
                # Update from dict items to handle type correctly
                _path_cache.update(self.original_cache_state)
        if self.original_disabled_state is not None:
            _cache_disabled = self.original_disabled_state
        logger.debug("Cache isolation context exited")


def get_cache_stats() -> dict[str, object]:
    """Get statistics about current cache usage."""
    with _path_cache_lock:
        path_cache_size = len(_path_cache)

    stats: dict[str, object] = {
        "path_cache_size": path_cache_size,
        "version_cache_size": VersionUtils.get_version_cache_size(),
        "extract_version_cache_info": VersionUtils.extract_version_from_path.cache_info(),
    }
    return stats


def normalize_plate_id(plate_id: str | None) -> str | None:
    """Normalize plate ID to canonical uppercase form.

    VFX convention uses uppercase (PL01, FG01, BG02), but filesystems
    may contain lowercase directories (pl01, fg01). This normalizes
    for consistent logging and comparison while preserving filesystem
    case for path operations.

    Args:
        plate_id: Plate identifier (e.g., "PL01", "pl01", "FG01")

    Returns:
        Normalized uppercase plate ID, or None if input is None/empty

    Examples:
        >>> normalize_plate_id("pl01")
        "PL01"
        >>> normalize_plate_id("  pl01  ")
        "PL01"
        >>> normalize_plate_id("")
        None
        >>> normalize_plate_id(None)
        None
    """
    if plate_id is None:
        return None

    # Strip whitespace and validate non-empty
    plate_id = plate_id.strip()
    if not plate_id:
        return None

    return plate_id.upper()


def find_path_case_insensitive(base_path: Path, plate_id: str) -> Path | None:
    """Find plate directory with case-insensitive fallback.

    Linux filesystems are case-sensitive, but VFX pipelines may have
    inconsistent casing (PL01/ vs pl01/). Try normalized uppercase first,
    then fall back to lowercase if not found.

    Args:
        base_path: Directory containing plate subdirectories (must exist)
        plate_id: Plate identifier (any case)

    Returns:
        Path to existing plate directory, or None if not found
    """
    # Validate base path exists
    if not base_path.exists():
        logger.warning(f"Base path does not exist: {base_path}")
        return None

    if not base_path.is_dir():
        logger.warning(f"Base path is not a directory: {base_path}")
        return None

    # Try normalized uppercase (VFX standard)
    normalized = normalize_plate_id(plate_id)
    if normalized:
        path = base_path / normalized
        if path.exists():
            return path

    # Fallback: try lowercase (legacy/non-standard)
    lowercase_path = base_path / plate_id.lower()
    if lowercase_path.exists():
        return lowercase_path

    # Fallback: try original case
    original_path = base_path / plate_id
    if original_path.exists():
        return original_path

    return None


class PathUtils:
    """Utilities for path construction and validation."""

    @staticmethod
    def build_path(base_path: str | Path, *segments: str) -> Path:
        """Build a path from base path and segments.

        Args:
            base_path: Base path to start from
            *segments: Path segments to append

        Returns:
            Constructed Path object
        """
        if not base_path:
            raise ValueError("Base path cannot be empty")

        path = Path(base_path)
        for segment in segments:
            if not segment:
                logger.warning(f"Empty segment in path construction from {base_path}")
                continue
            path = path / segment
        return path

    @staticmethod
    def build_thumbnail_path(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path:
        """Build thumbnail directory path.

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to thumbnail directory
        """
        # VFX convention: shot directory is named {sequence}_{shot}
        shot_dir = f"{sequence}_{shot}"
        return PathUtils.build_path(
            shows_root,
            show,
            "shots",
            sequence,
            shot_dir,
            *Config.THUMBNAIL_SEGMENTS,
        )

    @staticmethod
    def find_turnover_plate_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find thumbnail from turnover plate directories with preference order.

        Searches for plate files in:
        /shows/{show}/shots/{sequence}/{shot}/publish/turnover/plate/input_plate/{PLATE}/v001/exr/{resolution}/

        Plate preference order:
        1. FG plates (FG01, FG02, etc.)
        2. BG plates (BG01, BG02, etc.)
        3. Any other available plates (EL01, etc.)

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first frame of best available plate, or None if not found
        """
        # Build base path to turnover plates
        shot_dir = f"{sequence}_{shot}"
        base_path = PathUtils.build_path(
            shows_root,
            show,
            "shots",
            sequence,
            shot_dir,
            "publish",
            "turnover",
            "plate",
            "input_plate",
        )

        # Try the expected path first, but also check parent directories if it doesn't exist
        if not PathUtils.validate_path_exists(base_path, "Turnover plate base"):
            # Try without input_plate subdirectory
            base_path = PathUtils.build_path(
                shows_root,
                show,
                "shots",
                sequence,
                shot_dir,
                "publish",
                "turnover",
                "plate",
            )
            if not PathUtils.validate_path_exists(
                base_path,
                "Turnover plate directory",
            ):
                return None

        # Find all available plate directories
        try:
            plate_dirs = []
            # Check if input_plate is a subdirectory
            input_plate_path = base_path / "input_plate"
            if input_plate_path.exists() and input_plate_path.is_dir():
                # Look for plate directories inside input_plate
                plate_dirs = [d for d in input_plate_path.iterdir() if d.is_dir()]
            else:
                # Look for plate directories directly in base_path
                plate_dirs = [d for d in base_path.iterdir() if d.is_dir()]
        except (OSError, PermissionError) as e:
            logger.debug(f"Error accessing turnover plates: {e}")
            return None

        if not plate_dirs:
            logger.debug(f"No plate directories found in {base_path}")
            return None

        # Sort plates by preference
        def plate_priority(plate_dir: Path) -> tuple[int, str]:
            """Return priority tuple for sorting plates."""
            name = plate_dir.name.upper()
            # Priority: (order, name)
            # Lower order = higher priority
            if name.startswith("FG"):
                return (0, name)  # FG plates highest priority
            if name.startswith("BG"):
                return (1, name)  # BG plates second priority
            return (2, name)  # All others lowest priority

        sorted_plates = sorted(plate_dirs, key=plate_priority)

        # Try each plate in priority order
        for plate_dir in sorted_plates:
            plate_name = plate_dir.name

            # Look for v001/exr/*/
            version_path = plate_dir / "v001" / "exr"
            if not version_path.exists():
                continue

            # Find resolution directories (e.g., 4312x2304)
            try:
                resolution_dirs = [d for d in version_path.iterdir() if d.is_dir()]
            except (OSError, PermissionError):
                continue

            for res_dir in resolution_dirs:
                # Find first frame (typically .1001.exr or .0001.exr)
                exr_files = FileUtils.find_files_by_extension(res_dir, ".exr", limit=10)
                if not exr_files:
                    continue

                # Sort to get the first frame number
                # Files like: GG_000_0050_turnover-plate_EL01_lin_sgamut3cine_v001.1001.exr
                def extract_frame_number(path: Path) -> int:
                    """Extract frame number from filename."""
                    # Match pattern like .1001.exr or .0001.exr
                    match = re.search(r"\.(\d{4})\.exr$", path.name, re.IGNORECASE)
                    if match:
                        return int(match.group(1))
                    return 99999  # Sort non-matching files last

                sorted_frames = sorted(exr_files, key=extract_frame_number)

                if sorted_frames:
                    first_frame = sorted_frames[0]
                    # Check if we should use EXR as fallback
                    # Only return EXR if it's reasonably sized or if we're explicitly allowing fallback
                    file_size_mb = first_frame.stat().st_size / (1024 * 1024)
                    max_direct_size = getattr(
                        Config, "THUMBNAIL_MAX_DIRECT_SIZE_MB", 10
                    )

                    if file_size_mb <= max_direct_size:
                        # Small enough to use directly
                        logger.debug(
                            f"Using turnover plate EXR as fallback: {plate_name} - {first_frame.name} ({file_size_mb:.1f}MB)",
                        )
                        return first_frame
                    # Large EXR - return it anyway, cache_manager will resize with PIL
                    logger.debug(
                        f"Found large turnover plate EXR: {plate_name} - {first_frame.name} ({file_size_mb:.1f}MB) - will resize",
                    )
                    return first_frame

        logger.debug(f"No suitable turnover plates found for {sequence}_{shot}")
        return None

    @staticmethod
    def find_any_publish_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
        max_depth: int = 5,
    ) -> Path | None:
        """Find any EXR file with frame 1001 in the publish directory.

        This is a fallback thumbnail finder that recursively searches the publish
        directory for any EXR file containing "1001" in the filename (typically
        the first frame of a sequence).

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name
            max_depth: Maximum depth to search (default 5)

        Returns:
            Path to first matching EXR file, or None if not found
        """
        # Build path to publish directory
        shot_dir = f"{sequence}_{shot}"
        publish_path = PathUtils.build_path(
            shows_root,
            show,
            "shots",
            sequence,
            shot_dir,
            "publish",
        )

        # Check if publish directory exists
        if not publish_path.exists():
            logger.debug(f"Publish directory does not exist: {publish_path}")
            return None

        try:
            # Walk the directory tree with depth limiting
            for root, dirs, files in os.walk(publish_path):
                # Calculate current depth relative to publish_path
                rel_path = Path(root).relative_to(publish_path)
                depth = len(rel_path.parts) if str(rel_path) != "." else 0

                # Stop descending if we've reached max depth
                if depth >= max_depth:
                    dirs.clear()  # Don't descend further
                    continue

                # Look for EXR files with 1001 in the name
                for filename in files:
                    if "1001" in filename and filename.lower().endswith(".exr"):
                        result = Path(root) / filename
                        logger.debug(f"Found publish thumbnail: {result}")
                        return result

        except (OSError, PermissionError) as e:
            logger.debug(f"Error searching publish directory: {e}")
            return None

        logger.debug(f"No 1001.exr files found in {publish_path}")
        return None

    @staticmethod
    def build_raw_plate_path(workspace_path: str) -> Path:
        """Build raw plate base path.

        Args:
            workspace_path: Shot workspace path

        Returns:
            Path to raw plate directory
        """
        return PathUtils.build_path(workspace_path, *Config.RAW_PLATE_SEGMENTS)

    @staticmethod
    def build_undistortion_path(workspace_path: str, username: str) -> Path:
        """Build undistortion base path.

        Args:
            workspace_path: Shot workspace path
            username: Username for the path

        Returns:
            Path to undistortion directory
        """
        segments = ["user", username, *Config.UNDISTORTION_BASE_SEGMENTS[1:]]
        return PathUtils.build_path(workspace_path, *segments)

    @staticmethod
    def build_threede_scene_path(workspace_path: str, username: str) -> Path:
        """Build 3DE scene base path.

        Args:
            workspace_path: Shot workspace path
            username: Username for the path

        Returns:
            Path to 3DE scene directory
        """
        segments = ["user", username, *Config.THREEDE_SCENE_SEGMENTS]
        return PathUtils.build_path(workspace_path, *segments)

    @staticmethod
    def validate_path_exists(path: str | Path, description: str = "Path") -> bool:
        """Validate that a path exists.

        Uses caching for frequently checked paths to improve performance.

        Args:
            path: Path to validate
            description: Description for logging

        Returns:
            True if path exists, False otherwise
        """
        if not path:
            logger.debug(f"{description} is empty")
            return False

        # Skip caching if disabled (for testing)
        if _cache_disabled:
            path_obj = Path(path) if isinstance(path, str) else path
            exists = path_obj.exists()
            if not exists:
                logger.debug(f"{description} does not exist (no cache): {path_obj}")
            return exists

        # Convert to Path object and string for caching
        path_obj = Path(path) if isinstance(path, str) else path
        path_str = str(path_obj)
        current_time = time.time()

        # Check cache first with lock
        with _path_cache_lock:
            if path_str in _path_cache:
                cached_exists, timestamp = _path_cache[path_str]
                if _PATH_CACHE_TTL == 0 or current_time - timestamp < _PATH_CACHE_TTL:
                    # Return cached result without verification to avoid performance issues
                    if not cached_exists:
                        logger.debug(f"{description} does not exist (cached): {path_str}")
                    return cached_exists

        # Cache miss or expired - check actual path existence (outside lock)
        exists = path_obj.exists()

        # Cache the result with lock
        with _path_cache_lock:
            _path_cache[path_str] = (exists, current_time)

            # Clean old cache entries (simple cleanup)
            # Increased threshold from 1000 to 5000 for better performance
            cache_size = len(_path_cache)

        # Trigger cleanup outside lock if needed
        if cache_size > 5000:  # Prevent unlimited growth
            PathUtils._cleanup_path_cache()

        if not exists:
            logger.debug(f"{description} does not exist: {path_obj}")

        return exists

    @staticmethod
    def _cleanup_path_cache() -> None:
        """Clean expired entries from path cache.

        Optimized to only clean when cache is getting large,
        and to keep frequently accessed paths.

        Uses atomic update strategy to prevent race conditions during cleanup.
        """
        global _path_cache

        with _path_cache_lock:
            # Only clean if cache is significantly over limit
            if len(_path_cache) <= 2500:  # Keep some headroom
                return

            # Sort by timestamp to keep most recently accessed
            sorted_items = sorted(
                _path_cache.items(),
                key=lambda x: x[1][1],  # Sort by timestamp
                reverse=True,  # Most recent first
            )

            # Atomic update: create new dict and replace in single operation
            # This prevents other threads from seeing an empty cache mid-operation
            _path_cache = dict(sorted_items[:2500])

            logger.debug(f"Cleaned path cache, kept {len(_path_cache)} most recent entries")

    @staticmethod
    def batch_validate_paths(paths: list[str | Path]) -> dict[str, bool]:
        """Validate multiple paths at once for better performance.

        Args:
            paths: List of paths to validate

        Returns:
            Dictionary mapping path strings to existence status
        """
        results: dict[str, bool] = {}
        current_time = time.time()
        paths_to_check: list[tuple[str | Path, str]] = []

        # First pass - check cache with lock
        with _path_cache_lock:
            for path in paths:
                path_str = str(path)
                if path_str in _path_cache:
                    cached_exists, timestamp = _path_cache[path_str]
                    if _PATH_CACHE_TTL == 0 or current_time - timestamp < _PATH_CACHE_TTL:
                        # Use cached result without verification
                        results[path_str] = cached_exists
                        continue
                paths_to_check.append((path, path_str))

        # Second pass - check filesystem for uncached paths (outside lock)
        updates: list[tuple[str, bool]] = []
        for path, path_str in paths_to_check:
            path_obj: Path = Path(path) if isinstance(path, str) else path
            exists: bool = path_obj.exists()
            results[path_str] = exists
            updates.append((path_str, exists))

        # Update cache with lock
        with _path_cache_lock:
            for path_str, exists in updates:
                _path_cache[path_str] = (exists, current_time)

            # Check cache size
            cache_size = len(_path_cache)

        # Clean cache if needed (outside lock)
        # Increased threshold from 1000 to 5000 for better performance
        if cache_size > 5000:
            PathUtils._cleanup_path_cache()

        return results

    @staticmethod
    def safe_mkdir(path: str | Path, description: str = "Directory") -> bool:
        """Safely create directory with error handling.

        Args:
            path: Directory path to create
            description: Description for logging

        Returns:
            True if successful, False otherwise
        """
        if not path:
            logger.error(f"Cannot create {description}: empty path")
            return False

        path_obj = Path(path) if isinstance(path, str) else path
        try:
            path_obj.mkdir(parents=True, exist_ok=True)
            return True
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to create {description} {path_obj}: {e}")
            return False

    @staticmethod
    def find_undistorted_jpeg_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find JPEG thumbnail from undistorted plate in publish/mm structure.

        Searches for JPEG files in:
        /shows/{show}/shots/{sequence}/{shot}/publish/mm/default/{camera}/undistorted_plate/{version}/jpeg/{resolution}/

        This provides high-quality thumbnails without requiring EXR processing,
        using existing undistorted plates from the VFX pipeline.

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first JPEG file found, or None if not found
        """
        # Build base path to mm/default directory
        shot_dir = f"{sequence}_{shot}"
        mm_default_path = PathUtils.build_path(
            shows_root,
            show,
            "shots",
            sequence,
            shot_dir,
            "publish",
            "mm",
            "default",
        )

        if not PathUtils.validate_path_exists(mm_default_path, "MM default path"):
            return None

        # Discover available camera/plate directories using priority order
        plate_dirs = PathUtils.discover_plate_directories(mm_default_path)

        # Try each plate directory in priority order
        for plate_name, _priority in plate_dirs:
            # Get plate directory with case-insensitive lookup
            plate_dir = find_path_case_insensitive(mm_default_path, plate_name)
            if plate_dir is None:
                continue

            plate_path = plate_dir / "undistorted_plate"
            if not PathUtils.validate_path_exists(plate_path, "Undistorted plate path"):
                continue

            # Find latest version directory
            latest_version = VersionUtils.get_latest_version(plate_path)
            if not latest_version:
                logger.debug(f"No version found in {plate_path}")
                continue

            # Build path to jpeg subdirectory
            jpeg_base_path = plate_path / latest_version / "jpeg"

            if not PathUtils.validate_path_exists(jpeg_base_path, "JPEG base path"):
                continue

            # Find any resolution directory (4312x2304, etc.)
            try:
                for resolution_dir in jpeg_base_path.iterdir():
                    if resolution_dir.is_dir():
                        # Find first .jpeg file in this resolution
                        jpeg_file = FileUtils.get_first_image_file(resolution_dir)
                        if jpeg_file and jpeg_file.suffix.lower() in [".jpg", ".jpeg"]:
                            logger.info(
                                (f"Found undistorted JPEG thumbnail: {jpeg_file.name} "
                                f"(camera: {plate_name}, version: {latest_version})")
                            )
                            return jpeg_file
            except (OSError, PermissionError) as e:
                logger.debug(f"Error scanning JPEG directory {jpeg_base_path}: {e}")
                continue

        logger.debug(
            f"No undistorted JPEG thumbnails found for {show}/{sequence}/{shot}"
        )
        return None

    @staticmethod
    def find_user_workspace_jpeg_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find JPEG thumbnail from user workspace Nuke outputs.

        Searches for JPEGs in both common Nuke output structures:
        - {workspace}/user/{any_user}/mm/nuke/outputs/mm-default/undistort/{plate}/undistorted_plate/{version}/{resolution}/jpeg/
        - {workspace}/user/{any_user}/mm/nuke/outputs/mm-default/scene/{plate}/undistorted_plate/{version}/{resolution}/jpeg/

        Uses case-insensitive plate matching (pl01, PL01, Pl01 all match "PL" type).
        Discovers JPEGs generated by Nuke in artist workspaces, which are often
        more recent and higher quality than published thumbnails.

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first JPEG found in any user workspace, or None
        """
        shot_dir = f"{sequence}_{shot}"
        shot_path = PathUtils.build_path(shows_root, show, "shots", sequence, shot_dir)

        user_dir = shot_path / "user"
        if not PathUtils.validate_path_exists(user_dir, "User directory"):
            return None

        try:
            # Iterate through user directories
            for user_path in user_dir.iterdir():
                if not user_path.is_dir():
                    continue

                # Check if mm/nuke/outputs/mm-default exists
                mm_default_base = user_path / "mm" / "nuke" / "outputs" / "mm-default"
                if not mm_default_base.exists():
                    continue

                # Try both common Nuke output directory structures (undistort is more common)
                for output_type in ["undistort", "scene"]:
                    nuke_outputs = mm_default_base / output_type
                    if not nuke_outputs.exists():
                        continue

                    # Discover plate directories using dynamic discovery (now case-insensitive)
                    plate_dirs = PathUtils.discover_plate_directories(nuke_outputs)

                    # Try each plate in priority order
                    for plate_name, _priority in plate_dirs:
                        # Get plate directory with case-insensitive lookup
                        plate_dir = find_path_case_insensitive(nuke_outputs, plate_name)
                        if plate_dir is None:
                            continue

                        undistorted_path = plate_dir / "undistorted_plate"
                        if not undistorted_path.exists():
                            continue

                        # Find latest version
                        latest_version = VersionUtils.get_latest_version(
                            undistorted_path
                        )
                        if not latest_version:
                            continue

                        # Look for resolution/jpeg subdirectory structure
                        version_path = undistorted_path / latest_version

                        # Try direct jpeg subdirectory first, then version directory
                        for potential_jpeg_path in [
                            version_path / "jpeg",
                            version_path,
                        ]:
                            if not potential_jpeg_path.exists():
                                continue

                            # Check for resolution subdirectories
                            try:
                                for resolution_dir in potential_jpeg_path.iterdir():
                                    if not resolution_dir.is_dir():
                                        continue

                                    # Look for resolution/jpeg structure
                                    jpeg_dir = (
                                        resolution_dir / "jpeg"
                                        if (resolution_dir / "jpeg").exists()
                                        else resolution_dir
                                    )

                                    # Find first JPEG
                                    jpeg_file = FileUtils.get_first_image_file(jpeg_dir)
                                    if jpeg_file and jpeg_file.suffix.lower() in [
                                        ".jpg",
                                        ".jpeg",
                                    ]:
                                        logger.info(
                                            (f"Found user workspace JPEG: {jpeg_file.name} "
                                            f"(user: {user_path.name}, output_type: {output_type}, plate: {plate_name}, version: {latest_version})")
                                        )
                                        return jpeg_file
                            except (OSError, PermissionError):
                                continue

        except (OSError, PermissionError) as e:
            logger.debug(f"Error scanning user workspaces in {shot_path}: {e}")

        logger.debug(f"No user workspace JPEGs found for {show}/{sequence}/{shot}")
        return None

    @staticmethod
    def find_shot_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find thumbnail for a shot from editorial cutref directory.

        This is the single source of truth for shot thumbnail discovery,
        ensuring consistent thumbnails across "My Shots" and "Other 3DE scenes".

        Searches for JPEG thumbnails in:
        {workspace}/publish/editorial/cutref/{latest_version}/jpg/{resolution}/

        Args:
            shows_root: Root path for shows
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first JPEG file from latest editorial cutref version, or None if not found
        """
        # Build base path to editorial cutref directory
        shot_dir = f"{sequence}_{shot}"
        editorial_base = PathUtils.build_path(
            shows_root,
            show,
            "shots",
            sequence,
            shot_dir,
            "publish",
            "editorial",
            "cutref",
        )

        # Try to find editorial cutref thumbnail
        if PathUtils.validate_path_exists(editorial_base, "Editorial cutref directory"):
            # Find latest version directory (v001, v002, etc.)
            latest_version = VersionUtils.get_latest_version(editorial_base)
            if latest_version:
                # Build path to jpg subdirectory
                jpg_base_path = editorial_base / latest_version / "jpg"
                if PathUtils.validate_path_exists(jpg_base_path, "JPEG base path"):
                    # Find any resolution directory (1920x1080, 3840x2160, etc.)
                    try:
                        for resolution_dir in jpg_base_path.iterdir():
                            if resolution_dir.is_dir():
                                # Find first .jpg/.jpeg file in this resolution
                                jpeg_file = FileUtils.get_first_image_file(resolution_dir)
                                if jpeg_file and jpeg_file.suffix.lower() in [".jpg", ".jpeg"]:
                                    logger.info(
                                        (f"Found editorial cutref thumbnail: {jpeg_file.name} "
                                        f"(version: {latest_version}, resolution: {resolution_dir.name})")
                                    )
                                    return jpeg_file
                    except (OSError, PermissionError) as e:
                        logger.debug(f"Error scanning editorial cutref JPEG directory {jpg_base_path}: {e}")
                else:
                    logger.debug(f"No jpg directory found in {editorial_base}/{latest_version}")
            else:
                logger.debug(f"No version directories found in {editorial_base}")
        else:
            logger.debug(f"No editorial cutref directory found for {sequence}_{shot}")

        logger.debug(f"No editorial cutref JPEGs found for {show}/{sequence}/{shot}")

        # Fall back to turnover plate thumbnail if editorial cutref not found
        logger.debug(f"Attempting turnover plate fallback for {show}/{sequence}/{shot}")
        turnover_thumbnail = PathUtils.find_turnover_plate_thumbnail(
            shows_root, show, sequence, shot
        )
        if turnover_thumbnail:
            logger.info(f"Found turnover plate thumbnail: {turnover_thumbnail}")
            return turnover_thumbnail

        # Third fallback: any EXR with 1001 in publish folder
        logger.debug(f"Attempting publish directory fallback for {show}/{sequence}/{shot}")
        publish_thumbnail = PathUtils.find_any_publish_thumbnail(
            shows_root, show, sequence, shot
        )
        if publish_thumbnail:
            logger.info(f"Found publish thumbnail: {publish_thumbnail}")
            return publish_thumbnail

        logger.debug(f"No thumbnails found for {show}/{sequence}/{shot}")
        return None

    @staticmethod
    def find_mov_file_for_path(thumbnail_path: Path) -> Path | None:
        """Find a MOV file in the same version directory structure as a thumbnail.

        Given a path like:
        /shows/show/shots/seq/shot/publish/.../v001/exr/1920x1080/file.exr

        Searches for MOV files in:
        /shows/show/shots/seq/shot/publish/.../v001/mov/

        Args:
            thumbnail_path: Path to the original thumbnail (EXR or other format)

        Returns:
            Path to the MOV file if found, or None
        """
        try:
            # Walk up the directory tree to find a v001 (or similar version) directory
            current = thumbnail_path.parent
            version_dir = None
            max_depth = 5  # Limit search depth to avoid excessive traversal

            for _ in range(max_depth):
                if not current or current == current.parent:
                    break

                # Check if this looks like a version directory (v###)
                if current.name.startswith("v") and current.name[1:].isdigit():
                    version_dir = current
                    break

                current = current.parent

            if not version_dir:
                logger.debug(
                    f"Could not find version directory for path: {thumbnail_path}"
                )
                return None

            # Look for mov/ subdirectory
            mov_dir = version_dir / "mov"
            if not mov_dir.exists() or not mov_dir.is_dir():
                logger.debug(f"No mov directory found at: {mov_dir}")
                return None

            # Find MOV files in the directory
            mov_files = list(mov_dir.glob("*.mov")) + list(mov_dir.glob("*.MOV"))

            if not mov_files:
                logger.debug(f"No MOV files found in: {mov_dir}")
                return None

            # Return the first MOV file found (could be sorted by name if needed)
            mov_file = sorted(mov_files)[0]
            logger.debug(f"Found MOV file: {mov_file.name}")
            return mov_file

        except (OSError, PermissionError) as e:
            logger.debug(f"Error searching for MOV file: {e}")
            return None

    @staticmethod
    def discover_plate_directories(
        base_path: str | Path,
    ) -> list[tuple[str, float]]:
        """Dynamically discover plate directories using pattern matching and priority system.

        Supports: FG##, BG##, PL##, EL##, COMP## (where ## is any digit sequence).
        Only directories matching these patterns are returned.
        Uses Config.TURNOVER_PLATE_PRIORITY for ranking plates by type.

        This replaces the hardcoded PLATE_DISCOVERY_PATTERNS approach with dynamic
        discovery, allowing any plate naming (EL01, EL02, EL99, etc.) to work
        automatically without config updates.

        Args:
            base_path: Base path to search for plate directories

        Returns:
            List of (plate_name, priority) tuples sorted by priority (lower = higher priority)
        """
        if not PathUtils.validate_path_exists(base_path, "Plate base path"):
            return []

        path_obj = Path(base_path) if isinstance(base_path, str) else base_path
        found_plates: list[tuple[str, float]] = []

        # Define plate patterns with capturing groups for type identification
        plate_patterns = {
            r"^(FG)\d+$": "FG",  # FG01, FG02, etc.
            r"^(BG)\d+$": "BG",  # BG01, BG02, etc.
            r"^(EL)\d+$": "EL",  # EL01, EL02, etc. (element plates)
            r"^(COMP)\d+$": "COMP",  # COMP01, COMP02, etc.
            r"^(PL)\d+$": "PL",  # PL01, PL02, etc. (turnover plates)
        }

        try:
            for item in path_obj.iterdir():
                if not item.is_dir():
                    continue

                plate_name = item.name
                matched_prefix = None

                # Try to match against known patterns (case-insensitive to handle pl01, PL01, Pl01, etc.)
                for pattern, prefix in plate_patterns.items():
                    if re.match(pattern, plate_name, re.IGNORECASE):
                        matched_prefix = prefix
                        break

                # Only include directories that match known plate patterns
                if matched_prefix:
                    priority = Config.TURNOVER_PLATE_PRIORITY.get(matched_prefix, 3)
                    found_plates.append((plate_name, priority))
                    # Log normalized plate ID for consistency (but use filesystem case for paths)
                    normalized_name = normalize_plate_id(plate_name) or plate_name
                    logger.debug(
                        f"Found plate: {normalized_name} (type: {matched_prefix}, priority: {priority})"
                    )
                else:
                    # Skip non-plate directories (e.g., 'reference', 'backup', etc.)
                    logger.debug(f"Skipping non-plate directory: {plate_name}")

        except (OSError, PermissionError) as e:
            logger.warning(f"Error scanning plate directories in {base_path}: {e}")

        # Sort by priority (LOWER number = HIGHER priority as per config documentation)
        found_plates.sort(key=lambda x: x[1])

        return found_plates


class VersionUtils:
    """Utilities for handling versioned directories and files."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN: re.Pattern[str] = re.compile(r"^v(\d{3})$")

    # Cache for version directory listings
    _version_cache: ClassVar[dict[str, tuple[list[tuple[int, str]], float]]] = {}
    _version_cache_lock: ClassVar[threading.Lock] = threading.Lock()  # Thread-safety for version cache

    @classmethod
    def clear_version_cache(cls) -> None:
        """Clear the version cache."""
        with cls._version_cache_lock:
            cls._version_cache.clear()

    @classmethod
    def get_version_cache_size(cls) -> int:
        """Get the size of the version cache."""
        with cls._version_cache_lock:
            return len(cls._version_cache)

    @staticmethod
    def find_version_directories(base_path: str | Path) -> list[tuple[int, str]]:
        """Find all version directories in a path.

        Uses caching to avoid repeated directory scans for the same path.

        Args:
            base_path: Path to search for version directories

        Returns:
            List of (version_number, version_string) tuples sorted by version
        """
        if not PathUtils.validate_path_exists(base_path, "Version search path"):
            return []

        path_str = str(base_path)
        current_time = time.time()

        # Check cache first with lock
        with VersionUtils._version_cache_lock:
            if path_str in VersionUtils._version_cache:
                version_dirs, timestamp = VersionUtils._version_cache[path_str]
                if (
                    _PATH_CACHE_TTL == 0 or current_time - timestamp < _PATH_CACHE_TTL
                ):  # Use same TTL as path cache
                    return version_dirs.copy()  # Return a copy to prevent modification

        # Cache miss - scan filesystem (outside lock)
        path_obj = Path(base_path) if isinstance(base_path, str) else base_path
        version_dirs: list[tuple[int, str]] = []

        try:
            for item in path_obj.iterdir():
                if item.is_dir():
                    match = VersionUtils.VERSION_PATTERN.match(item.name)
                    if match:
                        version_num = int(match.group(1))
                        version_dirs.append((version_num, item.name))
        except (OSError, PermissionError) as e:
            logger.warning(f"Error scanning for version directories in {path_obj}: {e}")
            return []

        # Sort by version number
        version_dirs.sort(key=lambda x: x[0])

        # Cache the result with lock
        with VersionUtils._version_cache_lock:
            VersionUtils._version_cache[path_str] = (version_dirs.copy(), current_time)

            # Check cache size
            cache_size = len(VersionUtils._version_cache)

        # Clean cache if it gets too large (outside lock) - increased from 100 to 500
        if cache_size > 500:
            VersionUtils._cleanup_version_cache()

        return version_dirs

    @staticmethod
    def _cleanup_version_cache() -> None:
        """Clean expired entries from version cache.

        Optimized to keep frequently accessed version directories.

        Uses atomic update strategy to prevent race conditions during cleanup.
        """
        with VersionUtils._version_cache_lock:
            # Only clean if cache is significantly over limit
            if len(VersionUtils._version_cache) <= 250:
                return

            # Sort by timestamp to keep most recently accessed
            sorted_items = sorted(
                VersionUtils._version_cache.items(),
                key=lambda x: x[1][1],  # Sort by timestamp
                reverse=True,  # Most recent first
            )

            # Atomic update: create new dict and replace in single operation
            # This prevents other threads from seeing an empty cache mid-operation
            VersionUtils._version_cache = dict(sorted_items[:250])

            logger.debug(
                f"Cleaned version cache, kept {len(VersionUtils._version_cache)} most recent entries",
            )

    @staticmethod
    def get_latest_version(base_path: str | Path) -> str | None:
        """Get the latest version directory name.

        Args:
            base_path: Path to search for version directories

        Returns:
            Latest version string (e.g., "v003") or None if none found
        """
        version_dirs = VersionUtils.find_version_directories(base_path)
        if not version_dirs:
            logger.debug(f"No version directories found in {base_path}")
            return None

        latest_version = version_dirs[-1][
            1
        ]  # Get the version string from the last (highest) version
        logger.debug(f"Found latest version {latest_version} in {base_path}")
        return latest_version

    @staticmethod
    @lru_cache(maxsize=256)
    def extract_version_from_path(path: str | Path) -> str | None:
        """Extract version from a file or directory path.

        Uses LRU cache since this operation is pure and frequently called.

        Args:
            path: Path that may contain version information

        Returns:
            Version string if found, None otherwise
        """
        path_str = str(path)
        match = re.search(r"(v\d{3})", path_str)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def get_next_version_number(directory: str | Path, pattern: str) -> int:
        """Get the next available version number for files matching pattern.

        Args:
            directory: Directory to search in
            pattern: Filename pattern with version placeholder (e.g., "shot_*_v*.nk")

        Returns:
            Next available version number (1 if no files exist)
        """
        if not PathUtils.validate_path_exists(directory, "Version search directory"):
            return 1

        dir_path = Path(directory) if isinstance(directory, str) else directory

        # Convert pattern to regex, replacing * with appropriate patterns
        # Handle patterns like "shot_*_v*.nk" -> "shot_.*_v(\d{3})\.nk"
        # Standard library imports
        import re

        regex_pattern = pattern.replace(".", r"\.")  # Escape dots
        regex_pattern = regex_pattern.replace("*", ".*")  # Replace wildcards
        # Replace v* with v(\d{3}) to capture version numbers
        regex_pattern = re.sub(r"v\.\*", r"v(\\d{3})", regex_pattern)

        try:
            version_regex = re.compile(regex_pattern)
        except re.error:
            logger.warning(f"Invalid pattern for version search: {pattern}")
            return 1

        max_version = 0
        try:
            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    match = version_regex.match(file_path.name)
                    if match:
                        try:
                            version = int(match.group(1))
                            max_version = max(max_version, version)
                        except (ValueError, IndexError):
                            continue
        except (OSError, PermissionError) as e:
            logger.warning(f"Error scanning directory {dir_path} for versions: {e}")
            return 1

        return max_version + 1


class FileUtils:
    """Utilities for file operations and validation."""

    @staticmethod
    def find_files_by_extension(
        directory: str | Path,
        extensions: str | list[str],
        limit: int | None = None,
    ) -> list[Path]:
        """Find files with specific extensions in a directory.

        This method performs optimized file discovery with early termination
        when limits are reached and uses set-based lookups for extension
        matching to achieve O(1) performance per file check.

        Args:
            directory: Directory path to search. Accepts both string paths
                and pathlib.Path objects for flexibility.
            extensions: File extension(s) to match. Can be a single extension
                string like "jpg" or ".jpg", or a list of extensions like
                ["jpg", "jpeg", "png"]. Leading dots are optional and normalized.
            limit: Maximum number of matching files to return. If None,
                returns all matching files. Used for performance optimization
                in large directories.

        Returns:
            list[Path]: List of pathlib.Path objects for all matching files.
                Returns empty list if directory doesn't exist or no matches found.
                Results are ordered by directory iteration order (not sorted).

        Raises:
            No exceptions are raised. Permission errors and OS errors are
            caught and logged as warnings, returning partial results.

        Examples:
            Single extension search:
                >>> files = FileUtils.find_files_by_extension("/tmp", "txt")
                >>> assert all(f.suffix == ".txt" for f in files)

            Multiple extensions with limit:
                >>> images = FileUtils.find_files_by_extension(
                ...     Path("/images"), ["jpg", "jpeg", "png"], limit=10
                ... )
                >>> assert len(images) <= 10

            Type-safe directory handling:
                >>> from pathlib import Path
                >>> path_obj = Path("/some/directory")
                >>> string_path = "/some/directory"
                >>> # Both work identically due to str | Path type
                >>> files1 = FileUtils.find_files_by_extension(path_obj, "py")
                >>> files2 = FileUtils.find_files_by_extension(string_path, "py")

        Performance:
            - O(n) time complexity where n is number of files in directory
            - Early termination when limit is reached reduces actual runtime
            - Set-based extension lookup provides O(1) extension matching
            - Path validation uses TTL caching to avoid repeated stat calls
        """
        if not PathUtils.validate_path_exists(directory, "Search directory"):
            return []

        # Normalize extensions to set for O(1) lookup
        if isinstance(extensions, str):
            extensions = [extensions]

        normalized_extensions: set[str] = set()
        for ext in extensions:
            if not ext.startswith("."):
                ext = "." + ext
            normalized_extensions.add(ext.lower())

        dir_path = Path(directory) if isinstance(directory, str) else directory
        matching_files: list[Path] = []

        try:
            # Use iterdir() but with early termination optimization
            for file_path in dir_path.iterdir():
                # Check is_file() first as it's usually faster than suffix check
                if file_path.is_file():
                    if file_path.suffix.lower() in normalized_extensions:
                        matching_files.append(file_path)
                        # Early termination if limit reached
                        if limit and len(matching_files) >= limit:
                            break
        except (OSError, PermissionError) as e:
            logger.warning(f"Error scanning directory {dir_path}: {e}")

        return matching_files

    @staticmethod
    def get_first_image_file(
        directory: str | Path,
        allow_fallback: bool = True,
    ) -> Path | None:
        """Get the first image file found in a directory.

        Args:
            directory: Directory to search
            allow_fallback: If True, will check heavy formats (EXR, TIFF) as fallback

        Returns:
            Path to first image file or None if none found
        """
        # First try lightweight preferred extensions
        for ext in Config.THUMBNAIL_EXTENSIONS:
            files = FileUtils.find_files_by_extension(directory, ext, limit=1)
            if files:
                return files[0]

        # If no lightweight formats found and fallback allowed, try heavy formats
        if allow_fallback and hasattr(Config, "THUMBNAIL_FALLBACK_EXTENSIONS"):
            for ext in Config.THUMBNAIL_FALLBACK_EXTENSIONS:
                files = FileUtils.find_files_by_extension(directory, ext, limit=1)
                if files:
                    # Check file size before returning
                    file_path = files[0]
                    max_size_mb = getattr(Config, "THUMBNAIL_MAX_DIRECT_SIZE_MB", 10)
                    if FileUtils.validate_file_size(file_path, max_size_mb):
                        logger.debug(
                            f"Using fallback {ext} file as thumbnail: {file_path.name}",
                        )
                        return file_path
                    logger.debug(
                        f"Fallback {ext} file too large for direct loading: {file_path.name}",
                    )
                    # Still return it - let cache_manager handle resizing
                    return file_path

        return None

    @staticmethod
    def validate_file_size(
        file_path: str | Path,
        max_size_mb: int | None = None,
    ) -> bool:
        """Validate that a file is not too large.

        Args:
            file_path: Path to file to check
            max_size_mb: Maximum size in megabytes (uses Config.MAX_FILE_SIZE_MB if None)

        Returns:
            True if file is within size limit, False otherwise
        """
        if max_size_mb is None:
            max_size_mb = Config.MAX_FILE_SIZE_MB

        if not PathUtils.validate_path_exists(file_path, "File"):
            return False

        path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        try:
            size_bytes = path_obj.stat().st_size
            size_mb = size_bytes / (1024 * 1024)

            if size_mb > max_size_mb:
                logger.warning(
                    f"File too large ({size_mb:.1f}MB > {max_size_mb}MB): {path_obj}",
                )
                return False

            return True
        except OSError as e:
            logger.warning(f"Error checking file size for {path_obj}: {e}")
            return False


class ImageUtils:
    """Utilities for image validation and processing."""

    @staticmethod
    def validate_image_dimensions(
        width: int,
        height: int,
        max_dimension: int | None = None,
        max_memory_mb: int | None = None,
    ) -> bool:
        """Validate image dimensions and estimated memory usage.

        Args:
            width: Image width in pixels
            height: Image height in pixels
            max_dimension: Maximum allowed dimension (uses Config.MAX_THUMBNAIL_DIMENSION_PX if None)
            max_memory_mb: Maximum estimated memory usage in MB (uses Config.MAX_THUMBNAIL_MEMORY_MB if None)

        Returns:
            True if dimensions are acceptable, False otherwise
        """
        if max_dimension is None:
            max_dimension = Config.MAX_THUMBNAIL_DIMENSION_PX
        if max_memory_mb is None:
            max_memory_mb = Config.MAX_THUMBNAIL_MEMORY_MB

        # Check individual dimensions
        if width > max_dimension or height > max_dimension:
            logger.warning(
                f"Image dimensions too large ({width}x{height} > {max_dimension})",
            )
            return False

        # Estimate memory usage (4 bytes per pixel for RGBA)
        estimated_memory_bytes = width * height * 4
        estimated_memory_mb = estimated_memory_bytes / (1024 * 1024)

        if estimated_memory_mb > max_memory_mb:
            logger.warning(
                f"Estimated image memory usage too high ({estimated_memory_mb:.1f}MB > {max_memory_mb}MB)",
            )
            return False

        return True

    @staticmethod
    def get_safe_dimensions_for_thumbnail(
        max_size: int | None = None,
    ) -> tuple[int, int]:
        """Get safe dimensions for thumbnail generation.

        Args:
            max_size: Maximum dimension for thumbnail (uses Config.CACHE_THUMBNAIL_SIZE if None)

        Returns:
            (width, height) tuple for safe thumbnail dimensions
        """
        if max_size is None:
            max_size = Config.CACHE_THUMBNAIL_SIZE
        return (max_size, max_size)

    @staticmethod
    def is_image_too_large_for_thumbnail(
        size: QSize,
        max_dimension: int,
    ) -> bool:
        """Check if an image is too large for thumbnail processing.

        Args:
            size: QSize object with width() and height() methods
            max_dimension: Maximum allowed dimension in pixels

        Returns:
            True if image is too large, False if it's acceptable
        """
        width = size.width()
        height = size.height()

        # Return True if image is too large (inverse of validate_image_dimensions)
        return not ImageUtils.validate_image_dimensions(
            width=width,
            height=height,
            max_dimension=max_dimension,
            max_memory_mb=Config.MAX_THUMBNAIL_MEMORY_MB,
        )

    @staticmethod
    def extract_frame_from_mov(
        mov_path: Path,
        output_path: Path | None = None,
    ) -> Path | None:
        """Extract frame #5 from a MOV file using FFmpeg.

        Args:
            mov_path: Path to the MOV file
            output_path: Optional output path for the extracted frame.
                        If None, creates a temporary file.

        Returns:
            Path to the extracted JPEG frame, or None if extraction failed
        """
        import subprocess
        import tempfile

        if not mov_path.exists() or not mov_path.is_file():
            logger.debug(f"MOV file does not exist: {mov_path}")
            return None

        # Create output path if not provided
        if output_path is None:
            # Create temp file with .jpg extension
            temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="shotbot_thumb_")
            import os
            os.close(temp_fd)  # Close the file descriptor
            output_path = Path(temp_path)

        try:
            # Extract frame #5 using FFmpeg (frame numbering is 0-indexed, so frame 4 = 5th frame)
            # -i: input file
            # -an: disable audio (avoids audio codec library issues)
            # -vf "select=eq(n\,4)": select frame number 4 (the 5th frame)
            # -vframes 1: extract only 1 frame
            # -q:v 2: quality (2 is high quality for JPEG)
            # -y: overwrite output file
            cmd = [
                "ffmpeg",
                "-i",
                str(mov_path),
                "-an",  # Disable audio - only need video frame
                "-vf",
                "select=eq(n\\,4)",  # Select frame 4 (5th frame, 0-indexed)
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                str(output_path),
            ]

            # Run FFmpeg with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
                text=True,
            )

            if result.returncode == 0 and output_path.exists():
                logger.debug(
                    f"Successfully extracted frame #5 from MOV: {mov_path.name}"
                )
                return output_path
            else:
                logger.debug(
                    f"FFmpeg failed to extract frame from {mov_path.name}: {result.stderr}"
                )
                return None

        except subprocess.TimeoutExpired:
            logger.warning(f"FFmpeg timeout extracting frame from {mov_path.name}")
            return None
        except FileNotFoundError:
            logger.warning("FFmpeg not found in PATH - cannot extract MOV frames")
            return None
        except Exception as e:
            logger.exception(f"Error extracting frame from MOV {mov_path.name}: {e}")
            return None


class ValidationUtils:
    """Common validation utilities."""

    @staticmethod
    def validate_not_empty(
        *values: str | None,
        names: list[str] | None = None,
    ) -> bool:
        """Validate that values are not None or empty strings.

        Args:
            *values: Values to validate
            names: Optional names for logging (must match length of values)

        Returns:
            True if all values are non-empty, False otherwise
        """
        if names and len(names) != len(values):
            raise ValueError("Names list must match values length")

        for i, value in enumerate(values):
            if not value:
                name = names[i] if names else f"value {i}"
                logger.warning(f"Empty or None {name}")
                return False

        return True

    @staticmethod
    def validate_shot_components(show: str, sequence: str, shot: str) -> bool:
        """Validate shot component strings.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            True if all components are valid, False otherwise
        """
        return ValidationUtils.validate_not_empty(
            show,
            sequence,
            shot,
            names=["show", "sequence", "shot"],
        )

    @staticmethod
    def get_current_username() -> str:
        """Get the current username from environment.

        Returns:
            Current username, falling back to Config.DEFAULT_USERNAME if not found
        """
        # In mock mode, always use gabriel-h to match the production data
        if os.environ.get("SHOTBOT_MOCK", "").lower() in ("1", "true", "yes"):
            logger.debug("Mock mode: using production username 'gabriel-h'")
            return "gabriel-h"

        # Try multiple environment variables in order of preference
        for env_var in ["USER", "USERNAME", "LOGNAME"]:
            username = os.environ.get(env_var)
            if username:
                logger.debug(f"Found username '{username}' from ${env_var}")
                return username

        # Fallback to config default
        logger.debug(
            f"No username found in environment, using default: {Config.DEFAULT_USERNAME}",
        )
        return Config.DEFAULT_USERNAME

    @staticmethod
    def get_excluded_users(additional_users: set[str] | None = None) -> set[str]:
        """Get set of users to exclude from searches.

        Automatically excludes the current user and any additional specified users.

        Args:
            additional_users: Additional users to exclude beyond current user

        Returns:
            Set of usernames to exclude
        """
        excluded = {ValidationUtils.get_current_username()}

        if additional_users:
            excluded.update(additional_users)

        logger.debug(f"Excluding users: {excluded}")
        return excluded
