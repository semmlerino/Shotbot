"""Version directory and file utilities for ShotBot."""

from __future__ import annotations

# Standard library imports
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

# Local application imports
from logging_mixin import get_module_logger
from paths.validators import (
    _PATH_CACHE_TTL,  # pyright: ignore[reportPrivateUsage]
    PathValidators,
)


logger = get_module_logger(__name__)


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

    @staticmethod
    def is_version_directory(name: str) -> bool:
        """Return True if name looks like a version directory (e.g. v1, v001, v12).

        Accepts any number of digits after the leading 'v', unlike
        VERSION_PATTERN which requires exactly three digits.

        Args:
            name: Directory or path component name to test

        Returns:
            True if name starts with 'v' followed by one or more digits only

        """
        return name.startswith("v") and name[1:].isdigit()
