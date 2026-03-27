"""Base class for shot finder implementations.

This module provides common functionality for all shot finders,
eliminating duplication between targeted and previous shot finders.
"""

from __future__ import annotations

# Standard library imports
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict

from typing_extensions import Unpack

# Local application imports
from config import Config
from discovery import sanitize_username
from progress_mixin import ProgressReportingMixin
from shots.shot_parser import OptimizedShotParser
from type_definitions import Shot
from utils import get_current_username


class FindShotsKwargs(TypedDict, total=False):
    """Type-safe kwargs for find_shots method.

    All fields are optional (total=False) to support flexible calling patterns
    across different shot finder implementations.
    """

    target_shows: set[str]
    shows_root: Path | None
    active_shots: list[Shot]


class _ShotDetailsDictRequired(TypedDict):
    """Required fields for shot details dictionary."""

    show: str
    sequence: str
    shot: str
    workspace_path: str
    user_path: str
    status: str
    user_dir_exists: str


class ShotDetailsDict(_ShotDetailsDictRequired, total=False):
    """Type-safe return type for get_shot_details method.

    Required fields are always present, optional fields depend on filesystem state.
    """

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

        # Get raw username, falling back to the canonical resolver
        raw_username = username or get_current_username()

        # Sanitize username to prevent security issues
        self.username: str = sanitize_username(raw_username)
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
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Could not create Shot from path {path}: {e}")
            return None

    def get_shot_details(self, shot: Shot) -> ShotDetailsDict:
        """Get additional details about a shot.

        Args:
            shot: Shot to get details for

        Returns:
            Dictionary with shot details including paths and metadata

        """
        # Check if user directory still exists
        user_path = f"{shot.workspace_path}{self.user_path_pattern}"
        user_dir = Path(user_path)

        details: ShotDetailsDict = {
            "show": shot.show,
            "sequence": shot.sequence,
            "shot": shot.shot,
            "workspace_path": shot.workspace_path,
            "user_path": user_path,
            "status": self._get_shot_status(shot),
            "user_dir_exists": str(user_dir.exists()),
        }

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
        from discovery.thumbnail_finders import (
            find_any_publish_thumbnail,
            find_turnover_plate_thumbnail,
        )
        from utils import FileUtils

        try:
            # Try editorial thumbnail first
            editorial_dir = Path(shot.workspace_path) / "publish" / "editorial"
            if editorial_dir.exists():
                thumbnail = FileUtils.get_first_image_file(editorial_dir)
                if thumbnail:
                    return thumbnail

            # Fall back to turnover plate thumbnails
            thumbnail = find_turnover_plate_thumbnail(
                Config.SHOWS_ROOT,
                shot.show,
                shot.sequence,
                shot.shot,
            )
            if thumbnail:
                return thumbnail

            # Third fallback: any EXR with 1001 in publish folder
            return find_any_publish_thumbnail(
                Config.SHOWS_ROOT,
                shot.show,
                shot.sequence,
                shot.shot,
            )

        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Error finding thumbnail for {shot.full_name}: {e}")
            return None

    def _filter_approved_shots(
        self, all_user_shots: list[Shot], active_shots: list[Shot]
    ) -> list[Shot]:
        """Filter out active shots to get only approved/completed ones.

        Args:
            all_user_shots: All shots where user has work.
            active_shots: Currently active shots from workspace.

        Returns:
            List of approved shots (user shots minus active shots).

        """
        # Create a set of active shot identifiers for efficient lookup
        active_ids = {(shot.show, shot.sequence, shot.shot) for shot in active_shots}

        # Filter out active shots
        approved_shots = [
            shot
            for shot in all_user_shots
            if (shot.show, shot.sequence, shot.shot) not in active_ids
        ]

        self.logger.info(
            f"Filtered {len(all_user_shots)} user shots to "
            f"{len(approved_shots)} approved shots"
        )

        return approved_shots

    @abstractmethod
    def _get_shot_status(self, shot: Shot) -> str:
        """Get the status of a shot (to be implemented by subclasses).

        Args:
            shot: Shot to get status for

        Returns:
            Status string (e.g., "approved", "active")

        """

    @abstractmethod
    def find_shots(self, **kwargs: Unpack[FindShotsKwargs]) -> list[Shot]:
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
