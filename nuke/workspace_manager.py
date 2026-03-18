"""Nuke workspace management utilities.

This module handles Nuke script management in the VFX pipeline workspace,
including finding existing scripts, creating new versions, and managing
the proper directory structure.
"""

from __future__ import annotations

# Standard library imports
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

# Local application imports
from config import Config
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from logging_mixin import ContextualLogger

# Local application imports
from version_utils import VersionUtils


class NukeWorkspaceManager(LoggingMixin):
    """Manages Nuke scripts in the VFX pipeline workspace."""

    @classmethod
    def _get_logger(cls) -> ContextualLogger:
        """Get a logger for static methods."""
        # Create a temporary instance to get the logger
        if not hasattr(cls, "_logger_instance"):
            cls._logger_instance: NukeWorkspaceManager = cls()
        return cls._logger_instance.logger

    @classmethod
    def get_workspace_script_directory(
        cls,
        workspace_path: str,
        user: str | None = None,
        plate: str = "mm-default",
        pass_name: str = "PL01",
    ) -> Path:
        """Get the Nuke scripts directory in workspace.

        Creates the directory structure if it doesn't exist.

        Args:
            workspace_path: Base workspace path for the shot
            user: Username (defaults to current user)
            plate: Plate name (defaults to "mm-default")
            pass_name: Pass name (defaults to "PL01")

        Returns:
            Path to the Nuke scripts directory

        """
        if user is None:
            user = os.environ.get("USER", Config.DEFAULT_USERNAME)

        # Build the path: {workspace}/user/{user}/mm/nuke/scripts/{plate}/scene/{pass}/
        script_dir = (
            Path(workspace_path)
            / "user"
            / user
            / "mm"
            / "nuke"
            / "scripts"
            / plate
            / "scene"
            / pass_name
        )

        # Create directory structure if it doesn't exist
        if not script_dir.exists():
            try:
                script_dir.mkdir(parents=True, exist_ok=True)
                cls._get_logger().info(f"Created Nuke script directory: {script_dir}")
            except (OSError, PermissionError):
                cls._get_logger().exception("Failed to create Nuke script directory")
                raise

        return script_dir

    @classmethod
    def find_latest_nuke_script(
        cls,
        directory: Path,
        shot_name: str,
        plate: str = "mm-default",
        pass_name: str = "PL01",
    ) -> Path | None:
        """Find the latest version of Nuke script for a shot.

        Args:
            directory: Directory to search in
            shot_name: Shot name (e.g., "BRX_166_0010")
            plate: Plate name (defaults to "mm-default")
            pass_name: Pass name (defaults to "PL01")

        Returns:
            Path to the latest Nuke script, or None if none exist

        """
        if not directory.exists():
            return None

        # Build pattern for the expected filename format
        # Pattern: {shot}_{plate}_{pass}_scene_v*.nk
        pattern = f"{shot_name}_{plate}_{pass_name}_scene_v*.nk"
        regex_pattern = pattern.replace(".", r"\.")
        regex_pattern = regex_pattern.replace("*", r"(\d{3})")  # Capture version number

        try:
            version_regex = re.compile(regex_pattern)
        except re.error:
            cls._get_logger().error(
                f"Invalid pattern for Nuke script search: {pattern}"
            )
            return None

        latest_file = None
        latest_version = 0

        try:
            for file_path in directory.iterdir():
                if file_path.is_file() and file_path.suffix == ".nk":
                    match = version_regex.match(file_path.name)
                    if match:
                        try:
                            version = int(match.group(1))
                            if version > latest_version:
                                latest_version = version
                                latest_file = file_path
                        except (ValueError, IndexError):
                            continue
        except (OSError, PermissionError):
            cls._get_logger().exception(f"Error scanning directory {directory}")
            return None

        if latest_file:
            cls._get_logger().info(
                f"Found latest Nuke script: {latest_file.name} (v{latest_version:03d})"
            )
        else:
            cls._get_logger().debug(
                f"No Nuke scripts found in {directory} for shot {shot_name}"
            )

        return latest_file

    @classmethod
    def get_next_script_path(
        cls,
        directory: Path,
        shot_name: str,
        plate: str = "mm-default",
        pass_name: str = "PL01",
    ) -> tuple[Path, int]:
        """Get path for the next version of Nuke script.

        Args:
            directory: Directory for scripts
            shot_name: Shot name (e.g., "BRX_166_0010")
            plate: Plate name (defaults to "mm-default")
            pass_name: Pass name (defaults to "PL01")

        Returns:
            Tuple of (path to next version, version number)

        """
        # Build the filename pattern
        pattern = f"{shot_name}_{plate}_{pass_name}_scene_v*.nk"

        # Get the next version number
        next_version = VersionUtils.get_next_version_number(directory, pattern)

        # Build the filename
        filename = f"{shot_name}_{plate}_{pass_name}_scene_v{next_version:03d}.nk"
        script_path = directory / filename

        cls._get_logger().info(
            f"Next Nuke script version: {filename} (v{next_version:03d})"
        )

        return script_path, next_version

    @classmethod
    def list_all_nuke_scripts(
        cls,
        workspace_path: str,
        user: str | None = None,
        plate: str = "mm-default",
        pass_name: str = "PL01",
    ) -> list[tuple[Path, int]]:
        """List all Nuke script versions for a shot.

        Args:
            workspace_path: Base workspace path for the shot
            user: Username (defaults to current user)
            plate: Plate name (defaults to "mm-default")
            pass_name: Pass name (defaults to "PL01")

        Returns:
            List of (path, version) tuples sorted by version

        """
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user, plate, pass_name
        )

        if not script_dir.exists():
            return []

        scripts: list[tuple[Path, int]] = []
        version_regex = re.compile(r".*_v(\d{3})\.nk$")

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
            cls._get_logger().exception("Error listing Nuke scripts")
            return []

        # Sort by version number
        scripts.sort(key=lambda x: x[1])

        return scripts
