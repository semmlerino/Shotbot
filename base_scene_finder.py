"""Base class for scene finders with common functionality."""

from __future__ import annotations

# Standard library imports
import re
from abc import ABC, abstractmethod
from pathlib import Path
from re import Pattern

# Local application imports
from version_mixin import VersionHandlingMixin


class BaseSceneFinder(ABC, VersionHandlingMixin):
    """Abstract base class for scene file finders.

    Provides common functionality for finding the latest scene files
    in a VFX workspace structure. Subclasses must define:
    - VERSION_PATTERN: Regex pattern for version extraction
    - get_scene_paths(): Method to get application-specific paths
    - get_file_extensions(): File extensions to search for
    """

    # Subclasses must define this pattern
    VERSION_PATTERN: Pattern[str] | None = None

    def __init__(self) -> None:
        """Initialize the scene finder with version handling capabilities."""
        super().__init__()
        self._validate_subclass()

    def _validate_subclass(self) -> None:
        """Validate that subclass has required attributes."""
        if self.VERSION_PATTERN is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define VERSION_PATTERN"
            )

    @abstractmethod
    def get_scene_paths(self, user_dir: Path) -> list[Path]:
        """Get application-specific scene directories.

        Args:
            user_dir: User directory path

        Returns:
            List of paths to search for scene files
        """
        raise NotImplementedError

    @abstractmethod
    def get_file_extensions(self) -> list[str]:
        """Get file extensions to search for.

        Returns:
            List of file extensions (e.g., ['.ma', '.mb'])
        """
        raise NotImplementedError

    def find_latest_scene(
        self,
        workspace_path: str,
        _shot_name: str | None = None,
    ) -> Path | None:
        """Find the latest scene file in a workspace.

        This is the main method that coordinates the search for scene files.
        It validates the workspace, searches through user directories,
        finds versioned files, and returns the latest one.

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for better logging

        Returns:
            Path to the latest scene file, or None if not found
        """
        # Validate workspace
        workspace = self._validate_workspace(workspace_path)
        if workspace is None:
            return None

        # Find all scene files with versions
        scene_files = self._find_all_scene_files(workspace, shot_name)

        if not scene_files:
            self.logger.debug(
                f"No scene files found in workspace: {shot_name or workspace_path}"
            )
            return None

        # Sort by version and get the latest
        scene_files.sort(key=lambda x: x[1])
        latest_file = scene_files[-1][0]

        self.logger.info(
            f"Found latest scene for {shot_name or 'shot'}: {latest_file.name}"
        )
        return latest_file

    def find_all_scenes(
        self,
        workspace_path: str,
        include_all: bool = False,
    ) -> list[Path]:
        """Find all scene files in a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            include_all: If True, include files without version numbers

        Returns:
            List of paths to all scene files, sorted by version
        """
        # Validate workspace
        workspace = self._validate_workspace(workspace_path)
        if workspace is None:
            return []

        # Find all scene files
        if include_all:
            # Include files without version numbers
            all_files = self._find_all_files(workspace)
            return all_files
        # Only versioned files
        scene_files = self._find_all_scene_files(workspace)
        scene_files.sort(key=lambda x: x[1])
        return [f[0] for f in scene_files]

    def _validate_workspace(self, workspace_path: str | None) -> Path | None:
        """Validate that workspace exists and is accessible.

        Args:
            workspace_path: Path to validate

        Returns:
            Path object if valid, None otherwise
        """
        if not workspace_path:
            self.logger.debug("No workspace path provided")
            return None

        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return None

        return workspace

    def _find_all_scene_files(
        self,
        workspace: Path,
        _shot_name: str | None = None,
    ) -> list[tuple[Path, int]]:
        """Find all versioned scene files in workspace.

        Args:
            workspace: Workspace path
            shot_name: Optional shot name for logging

        Returns:
            List of (path, version) tuples
        """
        scene_files: list[tuple[Path, int]] = []

        # Search in all user directories
        user_base = workspace / "user"
        if not user_base.exists():
            self.logger.debug(f"No user directory in workspace: {workspace}")
            return scene_files

        # Iterate through user directories
        for user_dir in user_base.iterdir():
            if not user_dir.is_dir():
                continue

            # Get application-specific paths
            scene_paths = self.get_scene_paths(user_dir)

            for scene_path in scene_paths:
                if not scene_path.exists():
                    continue

                # Search for files with appropriate extensions
                scene_files.extend(self._search_directory(scene_path))

        return scene_files

    def _find_all_files(self, workspace: Path) -> list[Path]:
        """Find all scene files (versioned and unversioned).

        Args:
            workspace: Workspace path

        Returns:
            List of all scene file paths
        """
        all_files: set[Path] = set()  # Use set to avoid duplicates

        # Search in all user directories
        user_base = workspace / "user"
        if not user_base.exists():
            return []

        for user_dir in user_base.iterdir():
            if not user_dir.is_dir():
                continue

            # Get application-specific paths
            scene_paths = self.get_scene_paths(user_dir)

            for scene_path in scene_paths:
                if not scene_path.exists():
                    continue

                # Get all files with appropriate extensions using rglob (includes subdirs)
                for ext in self.get_file_extensions():
                    pattern = f"*{ext}"
                    # rglob searches recursively, so we don't need separate glob
                    all_files.update(scene_path.rglob(pattern))

        return list(all_files)

    def _search_directory(self, directory: Path) -> list[tuple[Path, int]]:
        """Search a directory for versioned scene files.

        Args:
            directory: Directory to search

        Returns:
            List of (path, version) tuples
        """
        versioned_files: list[tuple[Path, int]] = []

        for ext in self.get_file_extensions():
            # Search in directory
            for scene_file in directory.glob(f"*{ext}"):
                version = self._extract_version(scene_file)
                if version is not None:
                    versioned_files.append((scene_file, version))
                    self.logger.debug(
                        f"Found scene file: {scene_file.name} (v{version:03d})"
                    )

            # Also search in subdirectories (for 3DE plate directories)
            for subdir in directory.iterdir():
                if subdir.is_dir():
                    for scene_file in subdir.glob(f"*{ext}"):
                        version = self._extract_version(scene_file)
                        if version is not None:
                            versioned_files.append((scene_file, version))
                            self.logger.debug(
                                f"Found scene file: {scene_file.name} (v{version:03d})"
                            )

        return versioned_files

    def filter_autosave_files(self, files: list[Path]) -> list[Path]:
        """Filter out autosave files from a list of paths.

        Args:
            files: List of file paths

        Returns:
            List with autosave files removed
        """
        return [f for f in files if "autosave" not in f.name.lower()]

    def filter_by_pattern(
        self,
        files: list[Path],
        pattern: str | Pattern[str],
    ) -> list[Path]:
        """Filter files by a regex pattern.

        Args:
            files: List of file paths
            pattern: Regex pattern to match

        Returns:
            List of files matching the pattern
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        return [f for f in files if pattern.search(str(f))]

    def group_by_user(self, files: list[Path]) -> dict[str, list[Path]]:
        """Group files by user directory.

        Args:
            files: List of file paths

        Returns:
            Dictionary mapping username to list of files
        """
        user_files: dict[str, list[Path]] = {}

        for file_path in files:
            # Extract username from path
            parts = file_path.parts
            if "user" in parts:
                user_index = parts.index("user")
                if user_index + 1 < len(parts):
                    username = parts[user_index + 1]
                    if username not in user_files:
                        user_files[username] = []
                    user_files[username].append(file_path)

        return user_files
