"""Utility for finding undistortion node files for shots."""

import logging
from pathlib import Path
from typing import Optional

from config import Config
from utils import PathUtils, VersionUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class UndistortionFinder:
    """Finds the latest undistortion .nk file for a shot."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN = VersionUtils.VERSION_PATTERN

    @staticmethod
    def find_latest_undistortion(
        shot_workspace_path: str, shot_name: str, username: Optional[str] = None
    ) -> Optional[Path]:
        """
        Find the latest undistortion .nk file for a shot.

        Args:
            shot_workspace_path: The shot's workspace path (e.g., /shows/ygsk/shots/108_CHV/108_CHV_0015)
            shot_name: The shot name (e.g., 108_CHV_0015)
            username: Username for the undistortion path (uses Config.DEFAULT_USERNAME if None)

        Returns:
            Path to the latest undistortion .nk file, or None if not found
        """
        if username is None:
            username = Config.DEFAULT_USERNAME

        # Build base path for undistortion files using utilities
        base_path = PathUtils.build_undistortion_path(shot_workspace_path, username)

        if not PathUtils.validate_path_exists(base_path, "Undistortion base path"):
            return None

        # Find the latest version directory
        latest_version = VersionUtils.get_latest_version(base_path)
        if not latest_version:
            logger.debug(f"No version directories found in {base_path}")
            return None

        # Construct the full path to the .nk file
        nk_file_path: Path = (
            base_path
            / latest_version
            / f"{shot_name}_turnover-plate_bg01_aces_v002"
            / f"{shot_name}_mm_default_LD_{latest_version}.nk"
        )

        # Check if the file exists
        if nk_file_path.exists():
            return nk_file_path

        return None

    @staticmethod
    def get_version_from_path(undistortion_path: Path) -> Optional[str]:
        """
        Extract the version number from an undistortion file path.

        Args:
            undistortion_path: Path to the undistortion .nk file

        Returns:
            Version string (e.g., "v006") or None
        """
        # Use utility function for version extraction
        return VersionUtils.extract_version_from_path(undistortion_path)
