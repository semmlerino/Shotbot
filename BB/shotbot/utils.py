"""Common utilities for ShotBot application."""

import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from config import Config

# Set up logger for this module
logger = logging.getLogger(__name__)

# Cache for path existence checks (with TTL)
_path_cache: Dict[str, Tuple[bool, float]] = {}
_PATH_CACHE_TTL = 30.0  # seconds


def clear_all_caches():
    """Clear all utility caches - useful for testing or debugging."""
    global _path_cache
    _path_cache.clear()
    VersionUtils._version_cache.clear()
    # Clear lru_cache decorated functions
    VersionUtils.extract_version_from_path.cache_clear()
    logger.info("Cleared all utility caches")


def get_cache_stats():
    """Get statistics about current cache usage."""
    stats = {
        "path_cache_size": len(_path_cache),
        "version_cache_size": len(VersionUtils._version_cache),
        "extract_version_cache_info": VersionUtils.extract_version_from_path.cache_info(),
    }
    return stats


class PathUtils:
    """Utilities for path construction and validation."""

    @staticmethod
    def build_path(base_path: Union[str, Path], *segments: str) -> Path:
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
        shows_root: str, show: str, sequence: str, shot: str
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
        return PathUtils.build_path(
            shows_root, show, "shots", sequence, shot, *Config.THUMBNAIL_SEGMENTS
        )

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
        segments = ["user", username] + Config.UNDISTORTION_BASE_SEGMENTS[2:]
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
        segments = ["user", username] + Config.THREEDE_SCENE_SEGMENTS
        return PathUtils.build_path(workspace_path, *segments)

    @staticmethod
    def validate_path_exists(path: Union[str, Path], description: str = "Path") -> bool:
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

        # Use string representation for caching
        path_str = str(path)
        current_time = time.time()

        # Check cache first
        if path_str in _path_cache:
            exists, timestamp = _path_cache[path_str]
            if current_time - timestamp < _PATH_CACHE_TTL:
                if not exists:
                    logger.debug(f"{description} does not exist (cached): {path_str}")
                return exists

        # Check actual path existence
        path_obj = Path(path) if isinstance(path, str) else path
        exists = path_obj.exists()

        # Cache the result
        _path_cache[path_str] = (exists, current_time)

        # Clean old cache entries (simple cleanup)
        if len(_path_cache) > 1000:  # Prevent unlimited growth
            PathUtils._cleanup_path_cache()

        if not exists:
            logger.debug(f"{description} does not exist: {path_obj}")

        return exists

    @staticmethod
    def _cleanup_path_cache():
        """Clean expired entries from path cache."""
        current_time = time.time()
        expired_keys = [
            key
            for key, (_, timestamp) in _path_cache.items()
            if current_time - timestamp >= _PATH_CACHE_TTL
        ]
        for key in expired_keys:
            del _path_cache[key]
        logger.debug(f"Cleaned {len(expired_keys)} expired path cache entries")

    @staticmethod
    def batch_validate_paths(paths: List[Union[str, Path]]) -> Dict[str, bool]:
        """Validate multiple paths at once for better performance.

        Args:
            paths: List of paths to validate

        Returns:
            Dictionary mapping path strings to existence status
        """
        results = {}
        current_time = time.time()
        paths_to_check = []

        # First pass - check cache
        for path in paths:
            path_str = str(path)
            if path_str in _path_cache:
                exists, timestamp = _path_cache[path_str]
                if current_time - timestamp < _PATH_CACHE_TTL:
                    results[path_str] = exists
                    continue
            paths_to_check.append((path, path_str))

        # Second pass - check filesystem for uncached paths
        for path, path_str in paths_to_check:
            path_obj = Path(path) if isinstance(path, str) else path
            exists = path_obj.exists()
            results[path_str] = exists
            _path_cache[path_str] = (exists, current_time)

        # Clean cache if needed
        if len(_path_cache) > 1000:
            PathUtils._cleanup_path_cache()

        return results

    @staticmethod
    def safe_mkdir(path: Union[str, Path], description: str = "Directory") -> bool:
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


class VersionUtils:
    """Utilities for handling versioned directories and files."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN = re.compile(r"^v(\d{3})$")

    # Cache for version directory listings
    _version_cache: Dict[str, Tuple[List[Tuple[int, str]], float]] = {}

    @staticmethod
    def find_version_directories(base_path: Union[str, Path]) -> List[Tuple[int, str]]:
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

        # Check cache first
        if path_str in VersionUtils._version_cache:
            version_dirs, timestamp = VersionUtils._version_cache[path_str]
            if current_time - timestamp < _PATH_CACHE_TTL:
                return version_dirs.copy()  # Return a copy to prevent modification

        path_obj = Path(base_path) if isinstance(base_path, str) else base_path
        version_dirs: List[Tuple[int, str]] = []

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

        # Cache the result
        VersionUtils._version_cache[path_str] = (version_dirs.copy(), current_time)

        # Clean cache if it gets too large
        if len(VersionUtils._version_cache) > 100:
            VersionUtils._cleanup_version_cache()

        return version_dirs

    @staticmethod
    def _cleanup_version_cache():
        """Clean expired entries from version cache."""
        current_time = time.time()
        expired_keys = [
            key
            for key, (_, timestamp) in VersionUtils._version_cache.items()
            if current_time - timestamp >= _PATH_CACHE_TTL
        ]
        for key in expired_keys:
            del VersionUtils._version_cache[key]
        logger.debug(f"Cleaned {len(expired_keys)} expired version cache entries")

    @staticmethod
    def get_latest_version(base_path: Union[str, Path]) -> Optional[str]:
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
    def extract_version_from_path(path: Union[str, Path]) -> Optional[str]:
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


class FileUtils:
    """Utilities for file operations and validation."""

    @staticmethod
    def find_files_by_extension(
        directory: Union[str, Path],
        extensions: Union[str, List[str]],
        limit: Optional[int] = None,
    ) -> List[Path]:
        """Find files with specific extensions in a directory.

        Optimized to stop early when limit is reached and use set lookup for extensions.

        Args:
            directory: Directory to search
            extensions: File extension(s) to search for (with or without dots)
            limit: Maximum number of files to return

        Returns:
            List of matching file paths
        """
        if not PathUtils.validate_path_exists(directory, "Search directory"):
            return []

        # Normalize extensions to set for O(1) lookup
        if isinstance(extensions, str):
            extensions = [extensions]

        normalized_extensions = set()
        for ext in extensions:
            if not ext.startswith("."):
                ext = "." + ext
            normalized_extensions.add(ext.lower())

        dir_path = Path(directory) if isinstance(directory, str) else directory
        matching_files: List[Path] = []

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
    def get_first_image_file(directory: Union[str, Path]) -> Optional[Path]:
        """Get the first image file found in a directory.

        Args:
            directory: Directory to search

        Returns:
            Path to first image file or None if none found
        """
        # Try common image extensions from config in order of preference
        preferred_extensions = Config.IMAGE_EXTENSIONS

        for ext in preferred_extensions:
            files = FileUtils.find_files_by_extension(directory, ext, limit=1)
            if files:
                return files[0]

        return None

    @staticmethod
    def validate_file_size(
        file_path: Union[str, Path], max_size_mb: Optional[int] = None
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
                    f"File too large ({size_mb:.1f}MB > {max_size_mb}MB): {path_obj}"
                )
                return False

            return True
        except (OSError, IOError) as e:
            logger.warning(f"Error checking file size for {path_obj}: {e}")
            return False


class ImageUtils:
    """Utilities for image validation and processing."""

    @staticmethod
    def validate_image_dimensions(
        width: int,
        height: int,
        max_dimension: Optional[int] = None,
        max_memory_mb: Optional[int] = None,
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
                f"Image dimensions too large ({width}x{height} > {max_dimension})"
            )
            return False

        # Estimate memory usage (4 bytes per pixel for RGBA)
        estimated_memory_bytes = width * height * 4
        estimated_memory_mb = estimated_memory_bytes / (1024 * 1024)

        if estimated_memory_mb > max_memory_mb:
            logger.warning(
                f"Estimated image memory usage too high ({estimated_memory_mb:.1f}MB > {max_memory_mb}MB)"
            )
            return False

        return True

    @staticmethod
    def get_safe_dimensions_for_thumbnail(
        max_size: Optional[int] = None,
    ) -> Tuple[int, int]:
        """Get safe dimensions for thumbnail generation.

        Args:
            max_size: Maximum dimension for thumbnail (uses Config.CACHE_THUMBNAIL_SIZE if None)

        Returns:
            (width, height) tuple for safe thumbnail dimensions
        """
        if max_size is None:
            max_size = Config.CACHE_THUMBNAIL_SIZE
        return (max_size, max_size)


class ValidationUtils:
    """Common validation utilities."""

    @staticmethod
    def validate_not_empty(
        *values: Union[str, None], names: Optional[List[str]] = None
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
            show, sequence, shot, names=["show", "sequence", "shot"]
        )

    @staticmethod
    def get_current_username() -> str:
        """Get the current username from environment.

        Returns:
            Current username, falling back to Config.DEFAULT_USERNAME if not found
        """
        # Try multiple environment variables in order of preference
        for env_var in ["USER", "USERNAME", "LOGNAME"]:
            username = os.environ.get(env_var)
            if username:
                logger.debug(f"Found username '{username}' from ${env_var}")
                return username

        # Fallback to config default
        logger.debug(
            f"No username found in environment, using default: {Config.DEFAULT_USERNAME}"
        )
        return Config.DEFAULT_USERNAME

    @staticmethod
    def get_excluded_users(additional_users: Optional[Set[str]] = None) -> Set[str]:
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
