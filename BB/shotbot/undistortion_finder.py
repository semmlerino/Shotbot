"""Utility for finding undistortion node files for shots."""

import re
from pathlib import Path
from typing import Optional


class UndistortionFinder:
    """Finds the latest undistortion .nk file for a shot."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN = re.compile(r"^v(\d{3})$")

    @staticmethod
    def find_latest_undistortion(
        shot_workspace_path: str, shot_name: str
    ) -> Optional[Path]:
        """
        Find the latest undistortion .nk file for a shot.

        Args:
            shot_workspace_path: The shot's workspace path (e.g., /shows/ygsk/shots/108_CHV/108_CHV_0015)
            shot_name: The shot name (e.g., 108_CHV_0015)

        Returns:
            Path to the latest undistortion .nk file, or None if not found
        """
        # Base path for undistortion files
        base_path = (
            Path(shot_workspace_path)
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )

        if not base_path.exists():
            return None

        # Find all version directories
        version_dirs: list[tuple[int, str]] = []
        for item in base_path.iterdir():
            if item.is_dir():
                match = UndistortionFinder.VERSION_PATTERN.match(item.name)
                if match:
                    version_num = int(match.group(1))
                    version_dirs.append((version_num, item.name))

        if not version_dirs:
            return None

        # Sort by version number and get the latest
        version_dirs.sort(key=lambda x: x[0], reverse=True)
        latest_version: str = version_dirs[0][1]  # e.g., "v006"

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
        # The version appears in two places in the path, extract from parent directory
        parent_dir = undistortion_path.parent.parent
        if parent_dir.exists():
            match = UndistortionFinder.VERSION_PATTERN.match(parent_dir.name)
            if match:
                return parent_dir.name
        return None
