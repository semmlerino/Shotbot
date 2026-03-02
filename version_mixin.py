"""Mixin for version handling functionality.

This module provides a reusable mixin that adds version extraction
and sorting capabilities to any finder class, standardizing how
version numbers are parsed and compared across the codebase.
"""

from __future__ import annotations

# Standard library imports
import itertools
import re
from collections.abc import Callable
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

    def _collect_scene_files(
        self,
        user_base: Path,
        dcc_subpath: str,
        glob_patterns: list[str],
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path] | None:
        """Collect scene files from user directories for a given DCC tool.

        Walks all subdirectories under ``user_base``, appends ``dcc_subpath``
        to locate the DCC-specific scene directory, then globs using each
        pattern in ``glob_patterns`` via a single chained iterable with one
        cancellation check per file.

        Args:
            user_base: Path to the workspace ``user/`` directory.
            dcc_subpath: Relative path from each user directory to the scene
                base (e.g. ``"mm/maya/scenes"`` or
                ``"mm/3de/mm-default/scenes/scene"``).
            glob_patterns: Glob patterns applied relative to the scene base
                (e.g. ``["**/*.ma", "**/*.mb"]`` for recursive Maya search or
                ``["*/*.3de"]`` for one-level-deep 3DE search).
            cancel_flag: Optional callable returning ``True`` when the
                operation should be aborted.

        Returns:
            List of collected :class:`~pathlib.Path` objects, or ``None`` if
            the operation was cancelled.

        """
        collected: list[Path] = []

        for user_dir in user_base.iterdir():
            if cancel_flag and cancel_flag():
                self.logger.debug("Scene file collection cancelled")
                return None

            if not user_dir.is_dir():
                continue

            scene_base = user_dir / dcc_subpath
            if not scene_base.exists():
                continue

            globs = (scene_base.glob(pattern) for pattern in glob_patterns)
            for scene_file in itertools.chain.from_iterable(globs):
                if cancel_flag and cancel_flag():
                    self.logger.debug("Scene file collection cancelled")
                    return None
                collected.append(scene_file)

        return collected

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
