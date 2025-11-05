"""Mixin for version handling functionality.

This module provides a reusable mixin that adds version extraction
and sorting capabilities to any finder class, standardizing how
version numbers are parsed and compared across the codebase.
"""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path
from re import Pattern
from typing import ClassVar

# Local application imports
from logging_mixin import LoggingMixin


class VersionHandlingMixin(LoggingMixin):
    """Mixin to add version extraction and sorting capabilities.

    This mixin provides:
    - Version number extraction from filenames
    - Sorting files by version
    - Finding latest versions
    - Customizable version patterns

    The default pattern matches _v001, _v002, etc., but can be
    customized per class or per method call.

    Usage:
        class MyFinder(BaseFinder, VersionHandlingMixin):
            # Override pattern for this class
            VERSION_PATTERN = re.compile(r"_v(\\d{3})\\.ma$")

            def find_latest(self, files):
                return self._find_latest_by_version(files)
    """

    # Default version pattern - matches _v001, _v002, etc.
    # Can be overridden in subclasses
    VERSION_PATTERN: Pattern[str] = re.compile(r"_v(\d{3})")

    # Secondary patterns for common version formats
    # These are tried if the primary pattern fails
    FALLBACK_PATTERNS: ClassVar[list[Pattern[str]]] = [
        re.compile(r"\.v(\d{3})"),  # .v001 format
        re.compile(r"_ver(\d{3})"),  # _ver001 format
        re.compile(r"\.(\d{4})\."),  # .0001. format (frame numbers)
        re.compile(r"_(\d{3})$"),  # _001 at end of name
    ]

    def _extract_version(
        self, path: Path | str, pattern: str | Pattern[str] | None = None
    ) -> int | None:
        """Extract version number from a file path.

        Args:
            path: Path to extract version from
            pattern: Optional custom pattern (uses class pattern if None)

        Returns:
            Version number as integer, or None if not found
        """
        # Convert Path to string
        path_str = str(path)

        # Use provided pattern or class default
        if pattern is None:
            pattern = self.VERSION_PATTERN
        elif isinstance(pattern, str):
            pattern = re.compile(pattern)

        # Try primary pattern
        match = pattern.search(path_str)
        if match:
            version = int(match.group(1))
            self.logger.debug(f"Extracted version {version} from {Path(path).name}")
            return version

        # Try fallback patterns if configured
        if hasattr(self, "FALLBACK_PATTERNS") and self.FALLBACK_PATTERNS:
            for fallback in self.FALLBACK_PATTERNS:
                match = fallback.search(path_str)
                if match:
                    version = int(match.group(1))
                    msg = (
                        f"Extracted version {version} from {Path(path).name} "
                        "using fallback pattern"
                    )
                    self.logger.debug(msg)
                    return version

        return None

    def _find_latest_by_version(
        self, files: list[Path], pattern: str | Pattern[str] | None = None
    ) -> Path | None:
        """Find the latest file by version number.

        Args:
            files: List of file paths to search
            pattern: Optional custom version pattern

        Returns:
            Path to latest version or None if no versioned files
        """
        if not files:
            return None

        versioned_files: list[tuple[Path, int]] = []

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None:
                versioned_files.append((file, version))

        if not versioned_files:
            self.logger.debug("No versioned files found")
            return None

        # Sort by version (ascending) and get the last one
        versioned_files.sort(key=lambda x: x[1])
        latest_file, latest_version = versioned_files[-1]

        self.logger.info(
            f"Found latest version: {latest_file.name} (v{latest_version:03d})"
        )
        return latest_file

    def _find_earliest_by_version(
        self, files: list[Path], pattern: str | Pattern[str] | None = None
    ) -> Path | None:
        """Find the earliest file by version number.

        Args:
            files: List of file paths to search
            pattern: Optional custom version pattern

        Returns:
            Path to earliest version or None if no versioned files
        """
        if not files:
            return None

        versioned_files: list[tuple[Path, int]] = []

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None:
                versioned_files.append((file, version))

        if not versioned_files:
            return None

        # Sort by version and get the first one
        versioned_files.sort(key=lambda x: x[1])
        earliest_file, earliest_version = versioned_files[0]

        self.logger.info(
            f"Found earliest version: {earliest_file.name} (v{earliest_version:03d})"
        )
        return earliest_file

    def _sort_files_by_version(
        self,
        files: list[Path],
        reverse: bool = False,
        pattern: str | Pattern[str] | None = None,
    ) -> list[Path]:
        """Sort files by version number.

        Files without version numbers are placed at the end,
        sorted alphabetically.

        Args:
            files: List of files to sort
            reverse: If True, sort in descending order (latest first)
            pattern: Optional custom version pattern

        Returns:
            Sorted list of files
        """
        if not files:
            return []

        versioned: list[tuple[Path, int]] = []
        unversioned: list[Path] = []

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None:
                versioned.append((file, version))
            else:
                unversioned.append(file)

        # Sort versioned files
        versioned.sort(key=lambda x: x[1], reverse=reverse)
        sorted_files = [f for f, _ in versioned]

        # Append unversioned files at the end, sorted alphabetically
        sorted_files.extend(sorted(unversioned))

        msg = (
            f"Sorted {len(versioned)} versioned and "
            f"{len(unversioned)} unversioned files"
        )
        self.logger.debug(msg)

        return sorted_files

    def _get_version_range(
        self, files: list[Path], pattern: str | Pattern[str] | None = None
    ) -> tuple[int, int] | None:
        """Get the version range (min, max) from a list of files.

        Args:
            files: List of file paths
            pattern: Optional custom version pattern

        Returns:
            Tuple of (min_version, max_version) or None if no versions found
        """
        versions: list[int] = []

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None:
                versions.append(version)

        if not versions:
            return None

        return (min(versions), max(versions))

    def _filter_by_version_range(
        self,
        files: list[Path],
        min_version: int | None = None,
        max_version: int | None = None,
        pattern: str | Pattern[str] | None = None,
    ) -> list[Path]:
        """Filter files by version range.

        Args:
            files: List of file paths
            min_version: Minimum version (inclusive), None for no minimum
            max_version: Maximum version (inclusive), None for no maximum
            pattern: Optional custom version pattern

        Returns:
            Filtered list of files within version range
        """
        filtered: list[Path] = []

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None:
                if min_version is not None and version < min_version:
                    continue
                if max_version is not None and version > max_version:
                    continue
                filtered.append(file)

        msg = (
            f"Filtered to {len(filtered)} files in version range "
            f"[{min_version or 'any'}, {max_version or 'any'}]"
        )
        self.logger.debug(msg)

        return filtered

    def _group_files_by_version(
        self, files: list[Path], pattern: str | Pattern[str] | None = None
    ) -> dict[int, list[Path]]:
        """Group files by their version numbers.

        Useful for finding all files with the same version across
        different directories or with different extensions.

        Args:
            files: List of file paths
            pattern: Optional custom version pattern

        Returns:
            Dictionary mapping version numbers to lists of files
        """
        groups: dict[int, list[Path]] = {}

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None:
                if version not in groups:
                    groups[version] = []
                groups[version].append(file)

        self.logger.debug(f"Grouped files into {len(groups)} version groups")

        return groups

    def _find_next_version(
        self, files: list[Path], pattern: str | Pattern[str] | None = None
    ) -> int:
        """Find the next available version number.

        Useful for creating new files with automatic versioning.

        Args:
            files: List of existing file paths
            pattern: Optional custom version pattern

        Returns:
            Next version number (highest + 1, or 1 if no versions found)
        """
        if not files:
            return 1

        max_version = 0

        for file in files:
            version = self._extract_version(file, pattern)
            if version is not None and version > max_version:
                max_version = version

        next_version = max_version + 1
        self.logger.debug(f"Next available version: {next_version:03d}")
        return next_version

    def _format_version_string(self, version: int, padding: int = 3) -> str:
        """Format a version number as a padded string.

        Args:
            version: Version number
            padding: Number of digits to pad to

        Returns:
            Formatted version string (e.g., "001", "042")
        """
        return f"{version:0{padding}d}"
