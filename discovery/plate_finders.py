"""Plate discovery and publishing utilities for VFX workflows.

Provides utilities for discovering available plate spaces (FG01, BG01, etc.),
selecting the highest resolution directory for each plate, and finding main
plates in publish/turnover for RV preview.
"""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path

# Local application imports
from config import Config
from discovery.file_discovery import FileDiscovery
from logging_mixin import get_module_logger
from paths.validators import PathValidators
from version_utils import VersionUtils


# Module logger
logger = get_module_logger(__name__)


class PlateDiscovery:
    """Discover and filter available plates for a shot."""

    @staticmethod
    def get_available_plates(workspace_path: str) -> list[str]:
        """Get list of available primary plates (FG##, BG##).

        Returns plates sorted by priority (FG before BG).
        Excludes reference plates (BC##, PL##) by default.

        Args:
            workspace_path: Shot workspace path

        Returns:
            List of plate names sorted by priority (e.g., ['FG01', 'BG01', 'FG02'])

        """
        base_path = Path(workspace_path, *Config.RAW_PLATE_SEGMENTS)
        if not PathValidators.validate_path_exists(base_path, "Plate base path"):
            logger.debug(f"No plate base path found: {base_path}")
            return []

        # Discover all plates
        all_plates = FileDiscovery.discover_plate_directories(str(base_path))

        # Filter to primary plates only (FG, BG)
        # Excludes PL (reference/turnover), BC (background clean), etc.
        primary_plates = [
            (name, priority)
            for name, priority in all_plates
            if name.upper().startswith(("FG", "BG"))
        ]

        if not primary_plates:
            logger.debug(f"No primary plates (FG/BG) found in {base_path}")
            return []

        # Sort by priority (lower = higher priority) and return names
        primary_plates.sort(key=lambda x: x[1])
        plate_names = [name for name, _ in primary_plates]

        logger.info(f"Found {len(plate_names)} primary plates: {plate_names}")
        return plate_names

    @staticmethod
    def get_highest_resolution_dir(plate_dir: Path) -> Path | None:
        """Get highest resolution directory for a plate.

        Looks for directories matching the pattern {width}x{height} and returns
        the one with the highest total pixel count.

        Args:
            plate_dir: Path to search (e.g., .../FG01/v001/exr/)

        Returns:
            Path to highest resolution dir (e.g., .../4312x2304/) or None if not found

        """
        if not plate_dir.exists():
            logger.debug(f"Plate directory does not exist: {plate_dir}")
            return None

        # Find all resolution directories (format: {width}x{height})
        resolution_pattern = re.compile(r"^(\d+)x(\d+)$")
        resolution_dirs: list[tuple[int, Path]] = []

        try:
            for d in plate_dir.iterdir():
                if d.is_dir():
                    match = resolution_pattern.match(d.name)
                    if match:
                        width, height = int(match.group(1)), int(match.group(2))
                        total_pixels = width * height
                        resolution_dirs.append((total_pixels, d))
                        logger.debug(
                            f"Found resolution: {d.name} ({total_pixels:,} pixels)"
                        )
        except (OSError, PermissionError):
            logger.warning(f"Error scanning plate directory {plate_dir}", exc_info=True)
            return None

        if not resolution_dirs:
            logger.debug(f"No resolution directories found in {plate_dir}")
            return None

        # Sort by total pixels (descending) and return highest
        resolution_dirs.sort(reverse=True, key=lambda x: x[0])
        highest_pixels, highest_dir = resolution_dirs[0]
        logger.info(
            f"Selected highest resolution: {highest_dir.name} ({highest_pixels:,} pixels)"
        )
        return highest_dir


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
    fg01_path = (
        Path(workspace_path) / "publish" / "turnover" / "plate" / "input_plate" / "FG01"
    )

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
    resolution_dir = PlateDiscovery.get_highest_resolution_dir(exr_path)
    if resolution_dir is None:
        return None

    # Find first .exr file and extract pattern
    return _extract_plate_pattern(resolution_dir)


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
