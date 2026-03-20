"""Finder for the latest Maya scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

# Local application imports
from discovery.latest_finder_base import BaseLatestFinder


class MayaLatestFinder(BaseLatestFinder):
    """Finds the latest Maya scene file in a workspace.

    Uses BaseLatestFinder for the common search loop and VersionHandlingMixin
    (inherited via BaseLatestFinder) for version extraction and sorting.
    """

    _DCC_SUBPATH: ClassVar[str] = "mm/maya/scenes"
    _GLOB_PATTERNS: ClassVar[list[str]] = ["**/*.ma", "**/*.mb"]
    _DCC_LABEL: ClassVar[str] = "Maya"

    # Pattern to match version in Maya filenames (e.g., _v001, _v002)
    VERSION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"_v(\d{3})\.(ma|mb)$")

    def find_latest_maya_scene(
        self,
        workspace_path: str,
        shot_name: str | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Path | None:
        """Find the latest Maya scene file in a workspace.

        Searches for Maya files (.ma and .mb) in the standard VFX directory structure:
        /shows/{show}/shots/{sequence}/{shot}/user/*/mm/maya/scenes/**/*.ma
        /shows/{show}/shots/{sequence}/{shot}/user/*/mm/maya/scenes/**/*.mb

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for better logging
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            Path to the latest Maya scene file, or None if not found or cancelled

        """
        return self.find_latest_scene(workspace_path, shot_name, cancel_flag)

    # Version extraction is handled by VersionHandlingMixin._extract_version()
    # The mixin respects our VERSION_PATTERN and provides fallback patterns

    @staticmethod
    def find_all_maya_scenes(
        workspace_path: str,
        include_autosave: bool = False,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path]:
        """Find all Maya scene files in a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            include_autosave: Whether to include autosave files
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            List of all Maya scene files found (empty if cancelled)

        """
        if not workspace_path:
            return []

        workspace = Path(workspace_path)
        if not workspace.exists():
            return []

        user_base = workspace / "user"
        if not user_base.exists():
            return []

        finder = MayaLatestFinder()
        collected = finder._collect_scene_files(
            user_base,
            MayaLatestFinder._DCC_SUBPATH,
            MayaLatestFinder._GLOB_PATTERNS,
            cancel_flag,
        )
        if collected is None:
            return []

        if include_autosave:
            return collected

        return [f for f in collected if ".autosave" not in f.name]
