"""Utility for finding undistortion node files for shots."""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from config import Config
from utils import VersionUtils

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

        Searches flexibly for undistortion files across different plate types (FG01, BG01, etc.)
        and colorspace combinations.

        Args:
            shot_workspace_path: The shot's workspace path (e.g., /shows/ygsk/shots/108_CHV/108_CHV_0015)
            shot_name: The shot name (e.g., 108_CHV_0015)
            username: Username for the undistortion path (uses Config.DEFAULT_USERNAME if None)

        Returns:
            Path to the latest undistortion .nk file, or None if not found
        """
        if username is None:
            username = Config.DEFAULT_USERNAME

        # Build base path for scene exports (before plate-specific directories)
        scene_path = (
            Path(shot_workspace_path)
            / "user"
            / username
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
        )

        if not scene_path.exists():
            logger.debug(f"Scene path does not exist: {scene_path}")
            return None

        # Search for undistortion files in any plate directory (FG01, BG01, BC01, etc.)
        # Check all directories in scene path that match plate patterns
        found_files: List[Tuple[Path, str, str]] = []

        if scene_path.exists():
            for potential_plate in scene_path.iterdir():
                if not potential_plate.is_dir():
                    continue

                # Check if directory name matches plate pattern (case-insensitive)
                plate_name_upper = potential_plate.name.upper()
                if any(
                    plate_name_upper.startswith(prefix) for prefix in ["FG", "BG", "BC"]
                ):
                    undist_base = potential_plate / "nuke_lens_distortion"

                    if not undist_base.exists():
                        continue

                    # Find all version directories (case-insensitive)
                    version_dirs = [
                        d
                        for d in undist_base.iterdir()
                        if d.is_dir()
                        and VersionUtils.VERSION_PATTERN.match(d.name.lower())
                    ]

                    for version_dir in version_dirs:
                        # Search for .nk files recursively in subdirectories
                        # This handles both single and multiple levels of nesting
                        nk_files = list(version_dir.rglob(f"{shot_name}*LD*.nk"))
                        for nk_file in nk_files:
                            if nk_file.exists():
                                # Extract version from path
                                version = version_dir.name
                                plate_dir = (
                                    potential_plate.name
                                )  # Use actual directory name
                                found_files.append((nk_file, version, plate_dir))
                                logger.debug(f"Found undistortion file: {nk_file}")

        if not found_files:
            logger.debug(f"No undistortion files found for shot {shot_name}")
            return None

        # Sort by version (newest first) and plate preference (FG > BG > BC)
        def sort_key(item: Tuple[Path, str, str]) -> Tuple[int, int]:
            file_path, version, plate = item
            # Extract version number for sorting (v001 or V001 -> 1)
            version_lower = version.lower()
            version_num = int(version_lower[1:]) if version_lower[1:].isdigit() else 0
            # Plate priority: FG (foreground) > BG (background) > BC (background clean)
            plate_upper = plate.upper()
            if plate_upper.startswith("FG"):
                plate_priority = 0
            elif plate_upper.startswith("BG"):
                plate_priority = 1
            elif plate_upper.startswith("BC"):
                plate_priority = 2
            else:
                plate_priority = 3
            return (
                -version_num,
                plate_priority,
            )  # Negative for descending version order

        found_files.sort(key=sort_key)
        latest_file, version, plate = found_files[0]

        logger.info(
            f"Selected undistortion file: {latest_file} (version: {version}, plate: {plate})"
        )
        return latest_file

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
