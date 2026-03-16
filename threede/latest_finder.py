"""Finder for the latest 3DE scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path

# Local application imports
from version_mixin import VersionHandlingMixin


_THREEDE_DCC_SUBPATH = "mm/3de/mm-default/scenes/scene"
_THREEDE_GLOB_PATTERNS = ["*/*.3de"]


class ThreeDELatestFinder(VersionHandlingMixin):
    """Finds the latest 3DE scene file in a workspace.

    Uses VersionHandlingMixin for version extraction and sorting.
    """

    # Pattern to match version in 3DE filenames (e.g., _v001, _v002)
    VERSION_PATTERN: re.Pattern[str] = re.compile(r"_v(\d{3})\.3de$")

    def __init__(self) -> None:
        """Initialize the 3DE finder with version handling capabilities."""
        super().__init__()

    def find_latest_threede_scene(
        self,
        workspace_path: str,
        shot_name: str | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Path | None:
        """Find the latest 3DE scene file in a workspace.

        Searches for 3DE files in the standard VFX directory structure:
        /shows/{show}/shots/{sequence}/{shot}/user/*/mm/3de/mm-default/scenes/scene/*/*.3de

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for better logging
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            Path to the latest 3DE scene file, or None if not found or cancelled

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

        threede_files = self._collect_scene_files(
            user_base, _THREEDE_DCC_SUBPATH, _THREEDE_GLOB_PATTERNS, cancel_flag
        )
        if threede_files is None:
            # Cancelled
            self.logger.debug("3DE scene search cancelled")
            return None

        if not threede_files:
            self.logger.debug(
                f"No 3DE files found in workspace: {shot_name or workspace_path}"
            )
            return None

        latest_file = self._find_latest_by_version(threede_files)
        if latest_file is None:
            self.logger.debug(
                f"No versioned 3DE files found in workspace: {shot_name or workspace_path}"
            )
            return None

        self.logger.info(
            f"Found latest 3DE scene for {shot_name or 'shot'}: {latest_file.name}"
        )
        return latest_file

    # Version extraction is handled by VersionHandlingMixin._extract_version()
    # The mixin respects our VERSION_PATTERN and provides fallback patterns

    @staticmethod
    def find_all_threede_scenes(
        workspace_path: str,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path]:
        """Find all 3DE scene files in a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            List of all 3DE scene file paths, sorted by version (empty if cancelled)

        """
        if not workspace_path:
            return []

        workspace = Path(workspace_path)
        if not workspace.exists():
            return []

        user_base = workspace / "user"
        if not user_base.exists():
            return []

        finder = ThreeDELatestFinder()
        collected = finder._collect_scene_files(
            user_base, _THREEDE_DCC_SUBPATH, _THREEDE_GLOB_PATTERNS, cancel_flag
        )
        if collected is None:
            return []

        return finder._sort_files_by_version(collected)
