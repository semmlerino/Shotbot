"""Finder for the latest Maya scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

# Third-party imports
from typing_extensions import override

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

    # Version extraction is handled by VersionHandlingMixin._extract_version()
    # The mixin respects our VERSION_PATTERN and provides fallback patterns

    @override
    @classmethod
    def find_all_scenes(
        cls,
        workspace_path: str,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path]:
        """Find all Maya scene files in a workspace, excluding autosave files.

        Args:
            workspace_path: Full path to the shot workspace
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            List of all Maya scene files found, excluding autosave files
            (empty if cancelled)

        """
        scenes = super().find_all_scenes(workspace_path, cancel_flag)
        return [f for f in scenes if ".autosave" not in f.name]
