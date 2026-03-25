"""Plate discovery and resolution selection utilities for VFX workflows.

This module provides utilities for discovering available plate spaces (FG01, BG01, etc.)
and selecting the highest resolution directory for each plate.
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

