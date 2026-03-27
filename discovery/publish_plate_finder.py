"""Find main plates in publish/turnover for RV preview."""

from __future__ import annotations

import re
from pathlib import Path

from version_utils import VersionUtils


def find_main_plate(workspace_path: str) -> str | None:
    """Find the main plate (FG01) in publish/turnover for RV preview.

    Path pattern:
    {workspace}/publish/turnover/plate/input_plate/FG01/{version}/exr/{resolution}/*.exr

    Args:
        workspace_path: Shot workspace path (e.g., /shows/myshow/shots/sq010/sh0010)

    Returns:
        Path pattern with @@@@ for frame numbers (RV format), or None if not found.
        Example: /shows/.../FG01/v001/exr/4312x2304/shot_name.@@@@.exr

    """
    # Build base path to FG01
    fg01_path = Path(workspace_path) / "publish" / "turnover" / "plate" / "input_plate" / "FG01"

    if not fg01_path.exists():
        return None

    # Find latest version directory
    version_dir = VersionUtils.get_latest_version_path(fg01_path)
    if version_dir is None:
        return None

    # Navigate to exr/{resolution}/
    exr_path = version_dir / "exr"
    if not exr_path.exists():
        return None

    # Find highest-resolution directory (e.g., 4312x2304 over 1920x1080)
    from discovery.plate_discovery import (
        PlateDiscovery,
    )

    resolution_dir = PlateDiscovery.get_highest_resolution_dir(exr_path)
    if resolution_dir is None:
        return None

    # Find first .exr file and extract pattern
    return _extract_plate_pattern(resolution_dir)


def _find_latest_version(base_path: Path) -> Path | None:  # pyright: ignore[reportUnusedFunction]
    """Find the latest version directory (v001, v002, etc.).

    Args:
        base_path: Path containing version directories

    Returns:
        Path to latest version directory, or None if none found

    """
    versions = [
        (VersionUtils.version_number_from_name(item.name), item)
        for item in base_path.iterdir()
        if item.is_dir() and VersionUtils.is_version_directory(item.name)
    ]

    if not versions:
        return None

    versions.sort(key=lambda x: x[0], reverse=True)
    return versions[0][1]


def _extract_plate_pattern(resolution_dir: Path) -> str | None:
    """Extract plate pattern from resolution directory.

    Finds first .exr file and converts frame number to @@@@ for RV.

    Args:
        resolution_dir: Directory containing .exr files

    Returns:
        Path pattern with @@@@ for frame numbers, or None if no exr found

    """
    # Pattern to match frame numbers in filename
    # Example: shot_name_turnover-plate_FG01_lin_sgamut3cine_v001.1001.exr
    frame_pattern = re.compile(r"^(.+)\.(\d+)\.exr$")

    for item in resolution_dir.iterdir():
        if item.is_file() and item.suffix.lower() == ".exr":
            match = frame_pattern.match(item.name)
            if match:
                base_name = match.group(1)
                frame_digits = len(match.group(2))
                # RV uses @@@@ for frame padding
                frame_placeholder = "@" * frame_digits
                pattern_name = f"{base_name}.{frame_placeholder}.exr"
                return str(resolution_dir / pattern_name)

    # If no frame pattern found, just return first exr file
    for item in resolution_dir.iterdir():
        if item.is_file() and item.suffix.lower() == ".exr":
            return str(item)

    return None
