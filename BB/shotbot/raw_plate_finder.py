"""Utility for finding raw plate files for shots."""

import re
from pathlib import Path
from typing import Optional


class RawPlateFinder:
    """Finds the latest raw plate file for a shot."""

    # Pattern for version directories (v001, v002, etc.)
    VERSION_PATTERN = re.compile(r"^v(\d{3})$")

    @staticmethod
    def find_latest_raw_plate(
        shot_workspace_path: str, shot_name: str
    ) -> Optional[str]:
        """
        Find the latest raw plate file path for a shot.

        Args:
            shot_workspace_path: The shot's workspace path (e.g., /shows/ygsk/shots/108_CHV/108_CHV_0015)
            shot_name: The shot name (e.g., 108_CHV_0015)

        Returns:
            Path to the latest raw plate with #### for frame numbers, or None if not found
        """
        # Base path for raw plate files
        base_path = (
            Path(shot_workspace_path)
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "bg01"
        )

        if not base_path.exists():
            return None

        # Find all version directories
        version_dirs: list[tuple[int, str]] = []
        for item in base_path.iterdir():
            if item.is_dir():
                match = RawPlateFinder.VERSION_PATTERN.match(item.name)
                if match:
                    version_num = int(match.group(1))
                    version_dirs.append((version_num, item.name))

        if not version_dirs:
            return None

        # Sort by version number and get the latest
        version_dirs.sort(key=lambda x: x[0], reverse=True)
        latest_version: str = version_dirs[0][1]  # e.g., "v002"

        # Check for EXR directory
        exr_base = base_path / latest_version / "exr"
        if not exr_base.exists():
            return None

        # Find resolution directory (e.g., 4042x2274)
        resolution_dirs = [
            d for d in exr_base.iterdir() if d.is_dir() and "x" in d.name
        ]
        if not resolution_dirs:
            return None

        # Use the first resolution directory found
        resolution_dir = resolution_dirs[0]

        # Construct the file pattern with #### for frame numbers
        plate_pattern = (
            f"{shot_name}_turnover-plate_bg01_aces_{latest_version}.####.exr"
        )

        # Return the full path
        return str(resolution_dir / plate_pattern)

    @staticmethod
    def get_version_from_path(plate_path: str) -> Optional[str]:
        """
        Extract the version number from a raw plate file path.

        Args:
            plate_path: Path to the raw plate file

        Returns:
            Version string (e.g., "v002") or None
        """
        # Extract version from the filename pattern
        match = re.search(r"_aces_(v\d{3})\.", plate_path)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def verify_plate_exists(plate_path: str) -> bool:
        """
        Verify that at least one frame of the plate sequence exists.

        Args:
            plate_path: Path with #### pattern

        Returns:
            True if at least one frame exists
        """
        if not plate_path or "####" not in plate_path:
            return False

        # Check for common frame numbers
        common_frames = ["1001", "0001", "1000", "0000"]
        for frame in common_frames:
            test_path = plate_path.replace("####", frame)
            if Path(test_path).exists():
                return True

        # Try to find any frame by listing directory
        dir_path = Path(plate_path).parent
        if dir_path.exists():
            # Look for any .exr file matching the pattern
            base_pattern = Path(plate_path).stem.replace("####", r"\d{4}")
            pattern = re.compile(f"{base_pattern}\\.exr$")
            for file in dir_path.iterdir():
                if pattern.match(file.name):
                    return True

        return False
