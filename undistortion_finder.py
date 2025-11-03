"""Utility for finding undistortion node files for shots."""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path

# Local application imports
from config import Config
from logging_mixin import get_module_logger
from utils import VersionUtils


# Set up logger for this module
logger = get_module_logger(__name__)


class UndistortionFinder:
    """Finds the latest undistortion .nk file for a shot."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN: re.Pattern[str] = VersionUtils.VERSION_PATTERN

    @staticmethod
    def find_latest_undistortion(
        shot_workspace_path: str,
        shot_name: str,
        username: str | None = None,
    ) -> Path | None:
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

        # Build base path for exports
        exports_path = (
            Path(shot_workspace_path)
            / "user"
            / username
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
        )

        if not exports_path.exists():
            logger.debug(f"Exports path does not exist: {exports_path}")
            return None

        # Search for undistortion files in any scene*/plate directory structure
        # Handles both exports/scene/ and exports/sceneMasterSurvey/ etc.
        found_files: list[tuple[Path, str, str]] = []

        # Look for scene directories (scene, sceneMasterSurvey, etc.)
        # Add defensive error handling for FileNotFoundError
        try:
            scene_dirs = [
                d
                for d in exports_path.iterdir()
                if d.is_dir() and "scene" in d.name.lower()
            ]
        except FileNotFoundError:
            logger.debug(
                f"Exports path no longer exists during iteration: {exports_path}"
            )
            return None

        if not scene_dirs:
            # Fallback to direct "scene" directory if it exists
            scene_path = exports_path / "scene"
            if scene_path.exists():
                scene_dirs = [scene_path]
            else:
                logger.debug(f"No scene directories found in {exports_path}")
                return None

        for scene_dir in scene_dirs:
            logger.debug(
                f"Searching for undistortion in scene directory: {scene_dir.name}",
            )
            # Add defensive error handling for scene directory iteration
            try:
                potential_plates = list(scene_dir.iterdir())
            except FileNotFoundError:
                logger.debug(f"Scene directory no longer exists: {scene_dir}")
                continue

            for potential_plate in potential_plates:
                if not potential_plate.is_dir():
                    continue

                # Check if directory name matches plate pattern (case-insensitive)
                plate_name_upper = potential_plate.name.upper()
                if any(
                    plate_name_upper.startswith(prefix)
                    for prefix in Config.UNDISTORTION_PLATE_PREFIXES
                ):
                    undist_base = potential_plate / "nuke_lens_distortion"

                    if not undist_base.exists():
                        continue

                    # Find all version directories (case-insensitive)
                    # Add defensive error handling for undist_base iteration
                    try:
                        version_dirs = [
                            d
                            for d in undist_base.iterdir()
                            if d.is_dir()
                            and VersionUtils.VERSION_PATTERN.match(d.name.lower())
                        ]
                    except FileNotFoundError:
                        logger.debug(
                            f"Undistortion base directory no longer exists: {undist_base}"
                        )
                        continue

                    for version_dir in version_dirs:
                        # Search for .nk files recursively in subdirectories
                        # First try the specific LD pattern, then fallback to any .nk with shot name
                        nk_files = list(version_dir.rglob(f"{shot_name}*LD*.nk"))

                        # If no LD files found, try more general pattern
                        if not nk_files:
                            nk_files = list(version_dir.rglob(f"{shot_name}*.nk"))

                        # If still nothing, try any .nk file in the directory
                        if not nk_files:
                            nk_files = list(version_dir.rglob("*.nk"))

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

        # Sort by version (newest first) and plate preference (FG > PL > BG > BC)
        def sort_key(item: tuple[Path, str, str]) -> tuple[float, int]:
            _, version, plate = item  # file_path not used in sorting
            # Extract version number for sorting (v001 or V001 -> 1)
            version_lower = version.lower()
            version_num = int(version_lower[1:]) if version_lower[1:].isdigit() else 0
            # Plate priority using configuration
            plate_upper = plate.upper()
            plate_priority = 999  # Default for unknown plates

            # Find matching prefix in configuration
            for prefix, priority in Config.UNDISTORTION_PLATE_PRIORITY.items():
                if plate_upper.startswith(prefix):
                    plate_priority = priority
                    break

            return (
                plate_priority,
                -version_num,
            )  # Plate priority first, then version (negative for descending)

        found_files.sort(key=sort_key)
        latest_file, version, plate = found_files[0]

        logger.info(
            f"Selected undistortion file: {latest_file} (version: {version}, plate: {plate})",
        )
        return latest_file

    @staticmethod
    def get_version_from_path(undistortion_path: Path) -> str | None:
        """
        Extract the version number from an undistortion file path.

        Args:
            undistortion_path: Path to the undistortion .nk file

        Returns:
            Version string (e.g., "v006") or None
        """
        # Use utility function for version extraction
        return VersionUtils.extract_version_from_path(undistortion_path)
