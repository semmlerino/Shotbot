"""Base class for shot finder implementations.

This module provides common functionality for all shot finders,
eliminating duplication between targeted and previous shot finders.
"""

from __future__ import annotations

# Standard library imports
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict

# Local application imports
from config import Config
from finder_utils import FinderUtils
from progress_mixin import ProgressReportingMixin
from shot_model import Shot
from shot_parser import OptimizedShotParser


class FindShotsKwargs(TypedDict, total=False):
    """Type-safe kwargs for find_shots method.

    All fields are optional (total=False) to support flexible calling patterns
    across different shot finder implementations.
    """

    target_shows: set[str]
    shows_root: Path | None
    active_shots: list[Shot]


class ShotDetailsDict(TypedDict, total=False):
    """Type-safe return type for get_shot_details method.

    Required fields are always present, optional fields depend on filesystem state.
    """

    # Required fields
    show: str
    sequence: str
    shot: str
    workspace_path: str
    user_path: str
    status: str
    user_dir_exists: str

    # Optional fields (depend on filesystem state)
    has_3de: str
    has_nuke: str
    has_maya: str
    thumbnail_path: str


class ShotFinderBase(ProgressReportingMixin, ABC):
    """Abstract base class for shot finders with common functionality.

    Inherits progress reporting capabilities from ProgressReportingMixin,
    which includes LoggingMixin for consistent logging.
    """

    def __init__(self, username: str | None = None) -> None:
        """Initialize the shot finder with sanitized username.

        Args:
            username: Username to search for. If None, uses current user.

        """
        # Initialize parent class (ProgressReportingMixin -> LoggingMixin)
        super().__init__()

        # Get raw username
        # In mock mode, always use gabriel-h
        if os.environ.get("SHOTBOT_MOCK", "").lower() in ("1", "true", "yes"):
            raw_username = username or "gabriel-h"
        else:
            raw_username = username or os.environ.get("USER") or os.getlogin()

        # Use FinderUtils for username sanitization
        self.username: str = FinderUtils.sanitize_username(raw_username)
        self.user_path_pattern: str = f"/user/{self.username}"

        # Use OptimizedShotParser for improved performance
        self._parser: OptimizedShotParser = OptimizedShotParser()

        # Progress tracking is handled by ProgressReportingMixin

        self.logger.info(
            f"{self.__class__.__name__} initialized for user: {self.username}"
        )

    # Progress methods are inherited from ProgressReportingMixin:
    # - set_progress_callback()
    # - request_stop()
    # - _report_progress()
    # - _check_stop()

    def _parse_shot_from_path(self, path: str) -> Shot | None:
        """Parse shot information from a filesystem path.

        Args:
            path: Path containing shot information

        Returns:
            Shot object if path is valid, None otherwise

        """
        # Use OptimizedShotParser for better performance
        result = self._parser.parse_shot_path(path)
        if not result:
            return None

        # Validate shot is not empty
        if not result.shot:
            self.logger.debug(f"Empty shot extracted from path {path}")
            return None

        try:
            return Shot(
                show=result.show,
                sequence=result.sequence,
                shot=result.shot,
                workspace_path=result.workspace_path,
            )
        except Exception as e:
            self.logger.debug(f"Could not create Shot from path {path}: {e}")
            return None

    def get_shot_details(self, shot: Shot) -> ShotDetailsDict:
        """Get additional details about a shot.

        Args:
            shot: Shot to get details for

        Returns:
            Dictionary with shot details including paths and metadata

        """
        details: ShotDetailsDict = {
            "show": shot.show,
            "sequence": shot.sequence,
            "shot": shot.shot,
            "workspace_path": shot.workspace_path,
            "user_path": f"{shot.workspace_path}{self.user_path_pattern}",
            "status": self._get_shot_status(shot),
        }

        # Check if user directory still exists
        user_dir = Path(details["user_path"])
        details["user_dir_exists"] = str(user_dir.exists())

        # Check for common VFX work files
        if user_dir.exists():
            details["has_3de"] = str(any(user_dir.rglob("*.3de")))
            details["has_nuke"] = str(any(user_dir.rglob("*.nk")))
            details["has_maya"] = str(any(user_dir.rglob("*.m[ab]")))

            # Look for thumbnails
            thumbnail_path = self._find_thumbnail_for_shot(shot)
            if thumbnail_path:
                details["thumbnail_path"] = str(thumbnail_path)

        return details

    def _find_thumbnail_for_shot(self, shot: Shot) -> Path | None:
        """Find thumbnail for a shot using same logic as Shot class.

        Args:
            shot: Shot object to find thumbnail for

        Returns:
            Path to thumbnail or None if not found

        """
        # Local application imports
        from utils import FileUtils, PathUtils

        try:
            # Try editorial thumbnail first
            editorial_dir = Path(shot.workspace_path) / "publish" / "editorial"
            if editorial_dir.exists():
                thumbnail = FileUtils.get_first_image_file(editorial_dir)
                if thumbnail:
                    return thumbnail

            # Fall back to turnover plate thumbnails
            thumbnail = PathUtils.find_turnover_plate_thumbnail(
                Config.SHOWS_ROOT,
                shot.show,
                shot.sequence,
                shot.shot,
            )
            if thumbnail:
                return thumbnail

            # Third fallback: any EXR with 1001 in publish folder
            return PathUtils.find_any_publish_thumbnail(
                Config.SHOWS_ROOT,
                shot.show,
                shot.sequence,
                shot.shot,
            )

        except Exception as e:
            self.logger.debug(f"Error finding thumbnail for {shot.full_name}: {e}")
            return None

    @abstractmethod
    def _get_shot_status(self, shot: Shot) -> str:
        """Get the status of a shot (to be implemented by subclasses).

        Args:
            shot: Shot to get status for

        Returns:
            Status string (e.g., "approved", "active")

        """

    @abstractmethod
    def find_shots(self, **kwargs: FindShotsKwargs) -> list[Shot]:
        """Find shots based on implementation-specific logic.

        To be implemented by concrete subclasses.

        Args:
            **kwargs: Optional keyword arguments for shot finding
                - target_shows: Set of show names to search
                - shows_root: Root directory for shows
                - active_shots: List of currently active shots to filter

        Returns:
            List of found shots

        """
