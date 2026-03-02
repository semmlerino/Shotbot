"""Plate discovery and resolution selection utilities for VFX workflows.

This module provides utilities for discovering available plate spaces (FG01, BG01, etc.)
and selecting the highest resolution directory for each plate.
"""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path

# Local application imports
from file_discovery import FileDiscovery
from logging_mixin import get_module_logger
from path_builders import PathBuilders
from path_validators import PathValidators
from utils import VersionUtils, find_path_case_insensitive


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
        base_path = PathBuilders.build_raw_plate_path(workspace_path)
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

    @staticmethod
    def get_plate_script_directory(
        workspace_path: str, plate_name: str
    ) -> Path | None:
        """DEPRECATED: Get plate media directory (NOT for script storage).

        WARNING: This method returns the plate MEDIA directory, not the script workspace.
        For script storage, use get_workspace_script_directory() instead.

        This method is kept for backward compatibility but should not be used for
        Nuke script storage as it couples scripts to plate media versions, breaking
        "open latest" workflow when plates are updated.

        Builds path: {workspace}/publish/turnover/plate/input_plate/{plate}/v{version}/exr/{resolution}/

        Args:
            workspace_path: Shot workspace path
            plate_name: Plate name (e.g., "FG01", "BG01")

        Returns:
            Path to highest resolution directory for the latest version, or None if not found

        See Also:
            get_workspace_script_directory(): Recommended method for script storage

        """
        logger.warning(
            "get_plate_script_directory() is deprecated for script storage. "
             "Use get_workspace_script_directory() instead."
        )
        base_path = PathBuilders.build_raw_plate_path(workspace_path)

        # Get plate directory with case-insensitive lookup
        plate_dir = find_path_case_insensitive(base_path, plate_name)
        if plate_dir is None:
            logger.error(f"Plate directory not found: {plate_name}")
            return None

        # Get latest version directory
        latest_version = VersionUtils.get_latest_version(plate_dir)
        if not latest_version:
            logger.error(f"No version directory found for plate {plate_name}")
            return None

        # Get highest resolution directory
        exr_base = plate_dir / latest_version / "exr"
        resolution_dir = PlateDiscovery.get_highest_resolution_dir(exr_base)

        if not resolution_dir:
            logger.error(
                f"No resolution directory found for {plate_name}/{latest_version}"
            )
            return None

        logger.info(f"Plate script directory: {resolution_dir}")
        return resolution_dir

    @staticmethod
    def get_workspace_script_directory(
        workspace_path: str, user: str | None, plate_name: str
    ) -> Path | None:
        """Get the workspace directory where Nuke scripts should be saved for a plate.

        This is the correct location for script storage, independent of plate media versions.
        Scripts saved here persist across plate version updates and support "open latest" workflow.

        Path format: {workspace}/user/{user}/mm/nuke/scripts/mm-default/scene/{plate_name}/

        Args:
            workspace_path: Shot workspace path
            user: Username (defaults to current user if None)
            plate_name: Plate name (e.g., "FG01", "BG01")

        Returns:
            Path to workspace script directory, or None if creation fails

        """
        # Standard library imports
        import os

        # Get user from environment if not provided
        if user is None:
            user = os.environ.get("USER", "gabriel-h")

        # Build path: {workspace}/user/{user}/mm/nuke/scripts/mm-default/scene/{plate_name}/
        script_dir = (
            Path(workspace_path) / "user" / user / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        )

        # Create directory if it doesn't exist
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Workspace script directory: {script_dir}")
        except (OSError, PermissionError):
            logger.exception(f"Failed to create workspace script directory {script_dir}")
            return None

        return script_dir

    @staticmethod
    def find_existing_scripts(
        workspace_path: str, shot_name: str, plate_name: str
    ) -> list[tuple[Path, int]]:
        """Find existing Nuke scripts for a plate in workspace directory.

        Searches in: {workspace}/user/{user}/mm/nuke/scripts/mm-default/scene/{plate_name}/

        Args:
            workspace_path: Shot workspace path
            shot_name: Shot name (e.g., "DM_066_3580")
            plate_name: Plate name (e.g., "FG01")

        Returns:
            List of (script_path, version) tuples sorted by version

        """
        script_dir = PlateDiscovery.get_workspace_script_directory(
            workspace_path, None, plate_name
        )
        if not script_dir:
            return []

        # Pattern: {shot}_mm-default_{plate}_scene_v*.nk
        pattern = f"{shot_name}_mm-default_{plate_name}_scene_v*.nk"
        version_regex = re.compile(
            pattern.replace(".", r"\.").replace("*", r"(\d{3})")
        )

        scripts: list[tuple[Path, int]] = []
        try:
            for file_path in script_dir.iterdir():
                if file_path.is_file() and file_path.suffix == ".nk":
                    match = version_regex.match(file_path.name)
                    if match:
                        try:
                            version = int(match.group(1))
                            scripts.append((file_path, version))
                        except (ValueError, IndexError):
                            continue
        except (OSError, PermissionError):
            logger.warning(f"Error scanning for scripts in {script_dir}", exc_info=True)
            return []

        # Sort by version
        scripts.sort(key=lambda x: x[1])
        logger.debug(f"Found {len(scripts)} existing scripts for {plate_name}")
        return scripts

    @staticmethod
    def get_next_script_version(workspace_path: str, shot_name: str, plate_name: str) -> int:
        """Get the next available version number for a Nuke script.

        Args:
            workspace_path: Shot workspace path
            shot_name: Shot name
            plate_name: Plate name

        Returns:
            Next version number (1 if no scripts exist)

        """
        existing_scripts = PlateDiscovery.find_existing_scripts(
            workspace_path, shot_name, plate_name
        )

        if not existing_scripts:
            return 1

        # Get highest version and increment
        _, highest_version = existing_scripts[-1]
        next_version = highest_version + 1
        logger.info(f"Next available version for {plate_name}: v{next_version:03d}")
        return next_version
