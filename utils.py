"""Common utilities for ShotBot application."""

from __future__ import annotations

# Standard library imports
import os
import re
import subprocess
import tempfile
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

# Import path validation internals needed by this module (not re-exported)
from path_validators import (
    _PATH_CACHE_TTL,  # pyright: ignore[reportPrivateUsage]
    PathValidators,
    clear_path_cache,
    disable_path_caching,
    enable_path_caching,
)
from path_validators import get_cache_stats as get_path_cache_stats


__all__ = [
    "CacheIsolation",
    "FileUtils",
    "ImageUtils",
    "ValidationUtils",
    "VersionUtils",
    "clear_all_caches",
    "disable_caching",
    "enable_caching",
]


def clear_all_caches() -> None:
    """Clear all utility caches - useful for testing or debugging."""
    clear_path_cache()  # Clear path validation cache
    VersionUtils.clear_version_cache()
    # Clear lru_cache decorated functions
    VersionUtils.extract_version_from_path.cache_clear()
    logger.debug("Cleared all utility caches")  # DEBUG to reduce test log noise


def disable_caching() -> None:
    """Disable caching completely - useful for testing."""
    disable_path_caching()
    clear_all_caches()
    logger.debug("Caching disabled for testing")


def enable_caching() -> None:
    """Re-enable caching after testing."""
    enable_path_caching()
    logger.debug("Caching re-enabled after testing")


class CacheIsolation:
    """Context manager for cache isolation in tests.

    Note: This uses the path cache from path_validators module.
    The cache is managed through public functions to avoid accessing private variables.
    """

    def __enter__(self) -> CacheIsolation:
        """Enter context with isolated cache."""
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
        """Exit context and restore caching."""
        # Re-enable caching (cache will be empty)
        enable_caching()
        logger.debug("Cache isolation context exited")


def get_cache_stats() -> dict[str, object]:
    """Get statistics about current cache usage."""
    stats: dict[str, object] = {
        **get_path_cache_stats(),  # Get path cache stats from path_validators
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
        if not PathValidators.validate_path_exists(base_path, "Version search path"):
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
        except (OSError, PermissionError):
            logger.warning(f"Error scanning for version directories in {path_obj}", exc_info=True)
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
        if not PathValidators.validate_path_exists(directory, "Version search directory"):
            return 1

        dir_path = Path(directory) if isinstance(directory, str) else directory

        # Convert pattern to regex, replacing * with appropriate patterns
        # Handle patterns like "shot_*_v*.nk" -> "shot_.*_v(\d{3})\.nk"
        regex_pattern = pattern.replace(".", r"\.")  # Escape dots
        # Replace v* with version capture BEFORE generic wildcard replacement
        regex_pattern = regex_pattern.replace("v*", r"v(\d{3})")
        regex_pattern = regex_pattern.replace("*", ".*")  # Replace remaining wildcards

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
        except (OSError, PermissionError):
            logger.warning(f"Error scanning directory {dir_path} for versions", exc_info=True)
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
        if not PathValidators.validate_path_exists(directory, "Search directory"):
            return []

        # Normalize extensions to set for O(1) lookup
        if isinstance(extensions, str):
            extensions = [extensions]

        normalized_extensions: set[str] = set()
        for ext in extensions:
            normalized_ext = ext if ext.startswith(".") else "." + ext
            normalized_extensions.add(normalized_ext.lower())

        dir_path = Path(directory) if isinstance(directory, str) else directory
        matching_files: list[Path] = []

        try:
            # Use iterdir() but with early termination optimization
            for file_path in dir_path.iterdir():
                # Check is_file() first as it's usually faster than suffix check
                if (
                    file_path.is_file()
                    and file_path.suffix.lower() in normalized_extensions
                ):
                    matching_files.append(file_path)
                    # Early termination if limit reached
                    if limit and len(matching_files) >= limit:
                        break
        except (OSError, PermissionError):
            logger.warning(f"Error scanning directory {dir_path}", exc_info=True)

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
                    file_path = files[0]
                    logger.debug(
                        f"Using fallback {ext} file as thumbnail: {file_path.name}",
                    )
                    # Return regardless of size — cache_manager handles resizing
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

        if not PathValidators.validate_path_exists(file_path, "File"):
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
        except OSError:
            logger.warning(f"Error checking file size for {path_obj}", exc_info=True)
            return False


def _make_temp_jpeg(prefix: str) -> Path:
    """Create a named temporary JPEG file and return its path.

    Opens and immediately closes the OS file descriptor so the path can be
    passed to external tools (FFmpeg, oiiotool) that need to write to it
    themselves.

    Args:
        prefix: Filename prefix for the temp file (e.g., "shotbot_thumb_")

    Returns:
        Path to the newly created (empty) temporary JPEG file

    """
    temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix=prefix)
    os.close(temp_fd)
    return Path(temp_path)


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

        if not mov_path.exists() or not mov_path.is_file():
            logger.debug(f"MOV file does not exist: {mov_path}")
            return None

        # Create output path if not provided
        if output_path is None:
            output_path = _make_temp_jpeg("shotbot_thumb_")

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
                check=False, capture_output=True,
                timeout=30,
                text=True,
            )

            if result.returncode == 0 and output_path.exists():
                logger.debug(
                    f"Successfully extracted frame #5 from MOV: {mov_path.name}"
                )
                return output_path
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
        except Exception:
            logger.exception(f"Error extracting frame from MOV {mov_path.name}")
            return None

    @staticmethod
    def extract_frame_at_time(
        mov_path: Path,
        time_seconds: float,
        output_path: Path | None = None,
        width: int = 200,
    ) -> Path | None:
        """Extract a frame at a specific timestamp from a MOV file.

        Uses -ss before -i for fast seeking (crucial for performance).

        Args:
            mov_path: Path to the MOV file
            time_seconds: Timestamp in seconds to extract
            output_path: Optional output path for the extracted frame.
                        If None, creates a temporary file.
            width: Width to scale the output frame to (height auto-calculated)

        Returns:
            Path to the extracted JPEG frame, or None if extraction failed

        """

        if not mov_path.exists() or not mov_path.is_file():
            logger.debug(f"MOV file does not exist: {mov_path}")
            return None

        # Create output path if not provided
        if output_path is None:
            output_path = _make_temp_jpeg("shotbot_scrub_")

        try:
            # -ss BEFORE -i for fast seeking (critical for performance)
            # -an: disable audio
            # -vf "scale=width:-1": scale to width, auto-calculate height
            # -vframes 1: extract only 1 frame
            # -q:v 2: high quality JPEG
            cmd = [
                "ffmpeg",
                "-ss", str(time_seconds),  # Seek BEFORE input for fast seeking
                "-i", str(mov_path),
                "-an",
                "-vf", f"scale={width}:-1",
                "-vframes", "1",
                "-q:v", "2",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                timeout=10,  # Shorter timeout for single frame
                text=True,
            )

            if result.returncode == 0 and output_path.exists():
                return output_path

            logger.debug(
                f"FFmpeg failed at {time_seconds}s from {mov_path.name}: {result.stderr}"
            )
            return None

        except subprocess.TimeoutExpired:
            logger.warning(f"FFmpeg timeout at {time_seconds}s from {mov_path.name}")
            return None
        except FileNotFoundError:
            logger.warning("FFmpeg not found in PATH")
            return None
        except Exception:
            logger.exception(f"Error extracting frame at {time_seconds}s from {mov_path.name}")
            return None

    @staticmethod
    def extract_frame_from_exr(
        exr_path: Path,
        output_path: Path | None = None,
        width: int = 200,
    ) -> Path | None:
        """Extract and convert an EXR frame to JPEG using oiiotool.

        Args:
            exr_path: Path to the EXR file
            output_path: Optional output path for the converted frame.
                        If None, creates a temporary file.
            width: Width to scale the output frame to (height auto-calculated)

        Returns:
            Path to the converted JPEG frame, or None if conversion failed

        """

        if not exr_path.exists() or not exr_path.is_file():
            logger.debug(f"EXR file does not exist: {exr_path}")
            return None

        # Create output path if not provided
        if output_path is None:
            output_path = _make_temp_jpeg("shotbot_scrub_")

        try:
            # oiiotool command:
            # --resize widthx0 : resize to width, auto-calculate height (0 = preserve aspect)
            # -o : output file
            cmd = [
                "oiiotool",
                str(exr_path),
                "--resize", f"{width}x0",
                "-o", str(output_path),
            ]

            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                timeout=30,  # EXR processing can be slower
                text=True,
            )

            if result.returncode == 0 and output_path.exists():
                return output_path

            logger.debug(
                f"oiiotool failed for {exr_path.name}: {result.stderr}"
            )
            return None

        except subprocess.TimeoutExpired:
            logger.warning(f"oiiotool timeout for {exr_path.name}")
            return None
        except FileNotFoundError:
            logger.warning("oiiotool not found in PATH")
            return None
        except Exception:
            logger.exception(f"Error converting EXR {exr_path.name}")
            return None

    @staticmethod
    def get_mov_duration(mov_path: Path) -> float | None:
        """Get the duration of a MOV file in seconds using ffprobe.

        Args:
            mov_path: Path to the MOV file

        Returns:
            Duration in seconds, or None if unable to determine

        """

        if not mov_path.exists():
            return None

        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(mov_path),
            ]

            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                timeout=10,
                text=True,
            )

            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())

            return None

        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return None
        except Exception:
            logger.exception(f"Error getting duration for {mov_path.name}")
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
            msg = "Names list must match values length"
            raise ValueError(msg)

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

