"""Finder for the latest 3DE scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

# Local application imports
from discovery.latest_finder_base import BaseLatestFinder


class ThreeDELatestFinder(BaseLatestFinder):
    """Finds the latest 3DE scene file in a workspace.

    Uses BaseLatestFinder for the common search loop and VersionHandlingMixin
    (inherited via BaseLatestFinder) for version extraction and sorting.
    """

    _DCC_SUBPATH: ClassVar[str] = "mm/3de/mm-default/scenes/scene"
    _GLOB_PATTERNS: ClassVar[list[str]] = ["*/*.3de"]
    _DCC_LABEL: ClassVar[str] = "3DE"

    # Pattern to match version in 3DE filenames (e.g., _v001, _v002)
    VERSION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"_v(\d{3})\.3de$")

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
        return self.find_latest_scene(workspace_path, shot_name, cancel_flag)

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
        return ThreeDELatestFinder.find_all_scenes(workspace_path, cancel_flag)
