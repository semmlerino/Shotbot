"""Common utilities for all finder implementations.

This module provides reusable utility functions that are shared across
multiple finder classes, eliminating code duplication and providing
a single source of truth for common operations.
"""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path
from re import Pattern

# Local application imports
from config import Config


# Compiled regex patterns for performance
USERNAME_VALIDATION_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
PATH_TRAVERSAL_PATTERN = re.compile(r"[./\\]")
DEFAULT_VERSION_PATTERN = re.compile(r"_v(\d{3})")


class FinderUtils:
    """Static utilities for finder operations."""

    @staticmethod
    def sanitize_username(raw_username: str) -> str:
        """Sanitize username to prevent security issues.

        Removes path traversal characters and validates the username
        contains only alphanumeric characters, dashes, and underscores.

        Args:
            raw_username: Raw username input

        Returns:
            Sanitized username

        Raises:
            ValueError: If username is invalid after sanitization

        """
        # Remove any path traversal characters (., /, \) but keep hyphens
        username = PATH_TRAVERSAL_PATTERN.sub("", raw_username)

        # Validate that username is not empty after sanitization
        if not username:
            msg = f"Invalid username after sanitization: '{raw_username}'"
            raise ValueError(msg)

        # Additional validation: username should only contain alphanumeric, dash, and underscore
        if not USERNAME_VALIDATION_PATTERN.match(username):
            msg = f"Username contains invalid characters: '{username}'"
            raise ValueError(msg)

        return username

    @staticmethod
    def extract_version(
        path: Path | str, pattern: str | Pattern[str] = DEFAULT_VERSION_PATTERN
    ) -> int | None:
        """Extract version number from a file path.

        Supports custom version patterns for different file types.
        Default pattern matches _v001, _v002, etc.

        Args:
            path: File path to extract version from
            pattern: Regex pattern for version extraction (string or compiled)

        Returns:
            Version number as integer, or None if not found

        """
        # Convert Path to string if necessary
        path_str = str(path)

        # Compile pattern if it's a string
        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        match = pattern.search(path_str)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def build_user_path(
        workspace: Path, username: str, app: str, subdir: str = "scenes"
    ) -> Path:
        """Build standard VFX user path.

        Handles special cases for different applications.
        3DE has a unique directory structure compared to other apps.

        Args:
            workspace: Workspace root path
            username: Sanitized username
            app: Application name (maya, 3de, nuke)
            subdir: Subdirectory under app (default: scenes)

        Returns:
            Complete user path

        """
        if app == "3de":
            # 3DE has special structure: user/{username}/mm/3de/mm-default/scenes/scene
            return (
                workspace
                / "user"
                / username
                / "mm"
                / "3de"
                / "mm-default"
                / "scenes"
                / "scene"
            )
        # Standard structure for maya, nuke: user/{username}/{app}/{subdir}
        return workspace / "user" / username / app / subdir

    @staticmethod
    def find_latest_by_version(
        files: list[Path], version_pattern: str | Pattern[str] = DEFAULT_VERSION_PATTERN
    ) -> Path | None:
        """Find the latest file by version number.

        Sorts files by extracted version number and returns the highest.

        Args:
            files: List of file paths
            version_pattern: Pattern to extract version

        Returns:
            Path to latest version or None if no versioned files found

        """
        if not files:
            return None

        versioned_files: list[tuple[Path, int]] = []

        for file in files:
            version = FinderUtils.extract_version(file, version_pattern)
            if version is not None:
                versioned_files.append((file, version))

        if not versioned_files:
            return None

        # Sort by version (second element of tuple) and return latest
        versioned_files.sort(key=lambda x: x[1])
        return versioned_files[-1][0]

    @staticmethod
    def sort_by_version(
        files: list[Path],
        version_pattern: str | Pattern[str] = DEFAULT_VERSION_PATTERN,
        reverse: bool = False,
    ) -> list[Path]:
        """Sort files by version number.

        Files without versions are placed at the end, sorted alphabetically.

        Args:
            files: List of file paths to sort
            version_pattern: Pattern to extract version
            reverse: If True, sort in descending order

        Returns:
            Sorted list of files

        """
        versioned: list[tuple[Path, int]] = []
        unversioned: list[Path] = []

        for file in files:
            version = FinderUtils.extract_version(file, version_pattern)
            if version is not None:
                versioned.append((file, version))
            else:
                unversioned.append(file)

        # Sort versioned files by version number
        versioned.sort(key=lambda x: x[1], reverse=reverse)
        sorted_files = [f for f, _ in versioned]

        # Append unversioned files at the end, sorted alphabetically
        sorted_files.extend(sorted(unversioned))

        return sorted_files

    @staticmethod
    def sort_by_priority(
        items: list[tuple[str, Path]], priority_order: list[str]
    ) -> list[tuple[str, Path]]:
        """Sort items by priority order.

        Used for sorting plates (FG01 > PL01 > BG01 > BC01) or other
        prioritized items.

        Args:
            items: List of (key, path) tuples
            priority_order: Ordered list of priority keys

        Returns:
            Sorted list with highest priority first

        """

        def get_priority(item: tuple[str, Path]) -> int:
            key = item[0]
            try:
                return priority_order.index(key)
            except ValueError:
                return len(priority_order)  # Unknown items go last

        return sorted(items, key=get_priority)

    @staticmethod
    def parse_shot_path(path: str) -> tuple[str, str, str] | None:
        """Parse shot information from a filesystem path.

        Extracts show, sequence, and shot from standard VFX paths.

        Args:
            path: Path containing shot information

        Returns:
            Tuple of (show, sequence, shot) or None if invalid

        """
        # Pattern for standard VFX structure: /shows/{show}/shots/{sequence}/{shot}/
        shows_root = re.escape(Config.SHOWS_ROOT)
        pattern = re.compile(rf"{shows_root}/([^/]+)/shots/([^/]+)/([^/]+)/")

        match = pattern.search(path)
        if match:
            return match.group(1), match.group(2), match.group(3)
        return None

    @staticmethod
    def get_workspace_from_path(path: str) -> str | None:
        """Extract workspace path from a full path.

        Args:
            path: Full path containing workspace

        Returns:
            Workspace path or None if not found

        """
        # Extract up to and including the shot directory
        shot_info = FinderUtils.parse_shot_path(path)
        if shot_info:
            show, sequence, shot = shot_info
            return f"{Config.SHOWS_ROOT}/{show}/shots/{sequence}/{shot}"
        return None

    @staticmethod
    def is_valid_vfx_path(path: Path | str) -> bool:
        """Check if a path follows VFX structure conventions.

        Args:
            path: Path to validate

        Returns:
            True if path follows VFX conventions

        """
        path_str = str(path)
        return FinderUtils.parse_shot_path(path_str) is not None

    @staticmethod
    def filter_by_extensions(
        files: list[Path], extensions: list[str], case_sensitive: bool = False
    ) -> list[Path]:
        """Filter files by allowed extensions.

        Args:
            files: List of file paths
            extensions: Allowed extensions (e.g., [".ma", ".mb"])
            case_sensitive: If False, ignore case when matching

        Returns:
            Filtered list of files

        """
        if not case_sensitive:
            # Convert extensions to lowercase for comparison
            extensions = [ext.lower() for ext in extensions]
            return [f for f in files if f.suffix.lower() in extensions]
        return [f for f in files if f.suffix in extensions]

    @staticmethod
    def get_relative_path(path: Path, base: Path) -> Path:
        """Get relative path from base, handling different path types safely.

        Args:
            path: Full path
            base: Base path to make relative to

        Returns:
            Relative path

        """
        try:
            return path.relative_to(base)
        except ValueError:
            # Paths don't share a common base
            return path

    @staticmethod
    def find_files_recursive(
        root: Path, pattern: str, max_depth: int | None = None
    ) -> list[Path]:
        """Find files recursively with optional depth limit.

        More efficient than rglob for large directories when depth is limited.

        Args:
            root: Root directory to search
            pattern: Glob pattern to match
            max_depth: Maximum directory depth to search

        Returns:
            List of matching file paths

        """
        if not root.exists():
            return []

        results: list[Path] = []

        if max_depth is None:
            # No depth limit, use rglob
            results.extend(root.rglob(pattern))
        else:
            # Limited depth search
            def search_level(path: Path, current_depth: int) -> None:
                if current_depth > max_depth:
                    return

                # Check current level
                results.extend(path.glob(pattern))

                # Recurse into subdirectories
                if current_depth < max_depth:
                    for subdir in path.iterdir():
                        if subdir.is_dir():
                            search_level(subdir, current_depth + 1)

            search_level(root, 0)

        return results
