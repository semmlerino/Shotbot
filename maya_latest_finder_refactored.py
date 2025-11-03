"""Refactored Maya finder using BaseSceneFinder."""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path
from typing import override

# Local application imports
from base_scene_finder import BaseSceneFinder


class MayaLatestFinder(BaseSceneFinder):
    """Finds the latest Maya scene file in a workspace.

    Simplified version using BaseSceneFinder for common functionality.
    """

    # Pattern to match version in Maya filenames (e.g., _v001, _v002)
    VERSION_PATTERN = re.compile(r"_v(\d{3})\.(ma|mb)$")

    @override
    def get_scene_paths(self, user_dir: Path) -> list[Path]:
        """Get Maya-specific scene directories.

        Args:
            user_dir: User directory path

        Returns:
            List of paths to search for Maya files
        """
        # Maya files are in: user/{username}/maya/scenes/
        maya_scenes = user_dir / "maya" / "scenes"
        return [maya_scenes] if maya_scenes.exists() else []

    @override
    def get_file_extensions(self) -> list[str]:
        """Get Maya file extensions.

        Returns:
            List of Maya file extensions
        """
        return [".ma", ".mb"]

    def find_latest_maya_scene(
        self,
        workspace_path: str,
        shot_name: str | None = None,
    ) -> Path | None:
        """Find the latest Maya scene file in a workspace.

        This method maintains the original interface for compatibility.

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for better logging

        Returns:
            Path to the latest Maya scene file, or None if not found
        """
        return self.find_latest_scene(workspace_path, shot_name)

    @staticmethod
    def find_all_maya_scenes(
        workspace_path: str,
        include_autosave: bool = False,
    ) -> list[Path]:
        """Find all Maya scene files in a workspace.

        Static method for compatibility with existing code.

        Args:
            workspace_path: Full path to the shot workspace
            include_autosave: If True, include autosave files

        Returns:
            List of paths to all Maya scene files, sorted by version
        """
        finder = MayaLatestFinder()
        all_scenes = finder.find_all_scenes(workspace_path)

        if not include_autosave:
            all_scenes = finder.filter_autosave_files(all_scenes)

        return all_scenes
