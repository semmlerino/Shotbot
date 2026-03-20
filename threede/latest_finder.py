"""Finder for the latest 3DE scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
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

    # Version extraction is handled by VersionHandlingMixin._extract_version()
    # The mixin respects our VERSION_PATTERN and provides fallback patterns
