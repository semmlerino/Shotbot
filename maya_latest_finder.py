"""Finder for the latest Maya scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path

# Local application imports
from version_mixin import VersionHandlingMixin


_MAYA_DCC_SUBPATH = "mm/maya/scenes"
_MAYA_GLOB_PATTERNS = ["**/*.ma", "**/*.mb"]


class MayaLatestFinder(VersionHandlingMixin):
    """Finds the latest Maya scene file in a workspace.

    Uses VersionHandlingMixin for version extraction and sorting.
    """

    # Pattern to match version in Maya filenames (e.g., _v001, _v002)
    VERSION_PATTERN: re.Pattern[str] = re.compile(r"_v(\d{3})\.(ma|mb)$")

    def __init__(self) -> None:
        """Initialize the Maya finder with version handling capabilities."""
        super().__init__()

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
        if not workspace_path:
            self.logger.debug("No workspace path provided")
            return None

        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return None

        user_base = workspace / "user"
        if not user_base.exists():
            self.logger.debug(f"No user directory in workspace: {workspace_path}")
            return None

        maya_files = self._collect_scene_files(
            user_base, _MAYA_DCC_SUBPATH, _MAYA_GLOB_PATTERNS, cancel_flag
        )
        if maya_files is None:
            # Cancelled
            self.logger.debug("Maya scene search cancelled")
            return None

        if not maya_files:
            self.logger.debug(
                f"No Maya files found in workspace: {shot_name or workspace_path}"
            )
            return None

        latest_file = self._find_latest_by_version(maya_files)
        if latest_file is None:
            self.logger.debug(
                f"No versioned Maya files found in workspace: {shot_name or workspace_path}"
            )
            return None

        self.logger.info(
            f"Found latest Maya scene for {shot_name or 'shot'}: {latest_file.name}"
        )
        return latest_file

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
            user_base, _MAYA_DCC_SUBPATH, _MAYA_GLOB_PATTERNS, cancel_flag
        )
        if collected is None:
            return []

        if include_autosave:
            return collected

        return [f for f in collected if ".autosave" not in f.name]
