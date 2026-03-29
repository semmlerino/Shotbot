"""Version directory and file utilities for ShotBot."""

from __future__ import annotations

# Standard library imports
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, cast

# Third-party imports
from cachetools import TTLCache

# Local application imports
from config import Config
from logging_mixin import get_module_logger
from paths.validators import PathValidators


_VERSION_CACHE_TTL = Config.Cache.PATH_TTL_SECONDS  # 60s TTL for version cache


logger = get_module_logger(__name__)


class VersionUtils:
    """Utilities for handling versioned directories and files."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN: re.Pattern[str] = re.compile(r"^v(\d{3})$")

    # Cache for version directory listings
    # TTLCache handles both expiry (ttl=60s) and LRU eviction (maxsize=500) automatically.
    # timer=time.time allows tests to mock version_utils.time.time for TTL control.
    # pyright: ignore needed because vendored cachetools lacks type stubs.
    _version_cache: ClassVar[TTLCache[str, list[tuple[int, str]]]] = TTLCache(  # pyright: ignore[reportInvalidTypeArguments]
        maxsize=500, ttl=_VERSION_CACHE_TTL, timer=lambda: time.time()
    )
    _version_cache_lock: ClassVar[threading.Lock] = (
        threading.Lock()
    )  # Thread-safety for version cache

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

        # Check cache first with lock.
        # cast() used because vendored cachetools lacks type stubs.
        with VersionUtils._version_cache_lock:
            cached = cast(
                "list[tuple[int, str]] | None",
                VersionUtils._version_cache.get(path_str),  # pyright: ignore[reportUnknownMemberType]
            )
            if cached is not None:
                return list(cached)  # Return a copy to prevent modification

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
            logger.warning(
                f"Error scanning for version directories in {path_obj}", exc_info=True
            )
            return []

        # Sort by version number
        version_dirs.sort(key=lambda x: x[0])

        # Cache the result with lock
        with VersionUtils._version_cache_lock:
            VersionUtils._version_cache[path_str] = version_dirs.copy()

        return version_dirs

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
    def get_latest_version_path(base_path: str | Path) -> Path | None:
        """Return Path to the highest version directory, or None.

        Args:
            base_path: Path to search for version directories

        Returns:
            Path object pointing to the latest version directory, or None if none found

        """
        version_dirs = VersionUtils.find_version_directories(base_path)
        if not version_dirs:
            return None
        return Path(base_path) / version_dirs[-1][1]

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

    @staticmethod
    def version_number_from_name(name: str) -> int:
        """Extract version number from a version directory name (e.g. 'v001' -> 1).

        Caller must have already validated the name via is_version_directory().

        Args:
            name: Version directory name starting with 'v' followed by digits

        Returns:
            Integer version number

        """
        return int(name[1:])
