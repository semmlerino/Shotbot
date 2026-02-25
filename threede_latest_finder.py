"""Finder for the latest 3DE scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path

# Local application imports
from version_mixin import VersionHandlingMixin


class ThreeDELatestFinder(VersionHandlingMixin):
    """Finds the latest 3DE scene file in a workspace.

    Uses VersionHandlingMixin for version extraction and sorting.
    """

    # Pattern to match version in 3DE filenames (e.g., _v001, _v002)
    VERSION_PATTERN: re.Pattern[str] = re.compile(r"_v(\d{3})\.3de$")

    def __init__(self) -> None:
        """Initialize the 3DE finder with version handling capabilities."""
        super().__init__()

    def find_latest_threede_scene(
        self,
        workspace_path: str,
        shot_name: str | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Path | None:
        """Find the latest 3DE scene file in a workspace.

        Searches for 3DE files in the standard VFX directory structure:
        /shows/{show}/shots/{sequence}/{shot}/user/*/mm/3de/mm-default/scenes/scene/*/*.3de

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for better logging
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            Path to the latest 3DE scene file, or None if not found or cancelled

        """
        if not workspace_path:
            self.logger.debug("No workspace path provided")
            return None

        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return None

        # Search pattern: user/*/mm/3de/mm-default/scenes/scene/*/*.3de
        threede_files: list[tuple[Path, int]] = []

        # Search in all user directories
        user_base = workspace / "user"
        if not user_base.exists():
            self.logger.debug(f"No user directory in workspace: {workspace_path}")
            return None

        # Find all 3DE files
        for user_dir in user_base.iterdir():
            # Check for cancellation between user directories
            if cancel_flag and cancel_flag():
                self.logger.debug("3DE scene search cancelled")
                return None

            if not user_dir.is_dir():
                continue

            # Check for 3de directory structure
            threede_base = user_dir / "mm" / "3de" / "mm-default" / "scenes" / "scene"
            if not threede_base.exists():
                continue

            # Search for .3de files in subdirectories (plates)
            for plate_dir in threede_base.iterdir():
                # Check for cancellation between plate directories
                if cancel_flag and cancel_flag():
                    self.logger.debug("3DE scene search cancelled")
                    return None

                if not plate_dir.is_dir():
                    continue

                for threede_file in plate_dir.glob("*.3de"):
                    # Extract version number from filename
                    version = self._extract_version(threede_file)
                    if version is not None:
                        threede_files.append((threede_file, version))
                        self.logger.debug(
                            f"Found 3DE file: {threede_file.name} (v{version:03d})"
                        )

        if not threede_files:
            self.logger.debug(
                f"No 3DE files found in workspace: {shot_name or workspace_path}"
            )
            return None

        # Sort by version number and get the latest
        threede_files.sort(key=lambda x: x[1])
        latest_file = threede_files[-1][0]

        self.logger.info(
            f"Found latest 3DE scene for {shot_name or 'shot'}: {latest_file.name}"
        )
        return latest_file

    # Version extraction is handled by VersionHandlingMixin._extract_version()
    # The mixin respects our VERSION_PATTERN and provides fallback patterns

    @staticmethod
    def find_all_threede_scenes(
        workspace_path: str,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path]:
        """Find all 3DE scene files in a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            List of all 3DE scene file paths, sorted by version (empty if cancelled)

        """
        if not workspace_path:
            return []

        workspace = Path(workspace_path)
        if not workspace.exists():
            return []

        # Create an instance to use _extract_version
        finder = ThreeDELatestFinder()
        threede_files: list[tuple[Path, int]] = []

        # Search in all user directories
        user_base = workspace / "user"
        if not user_base.exists():
            return []

        # Find all 3DE files
        for user_dir in user_base.iterdir():
            # Check for cancellation between user directories
            if cancel_flag and cancel_flag():
                return []

            if not user_dir.is_dir():
                continue

            # Check for 3de directory structure
            threede_base = user_dir / "mm" / "3de" / "mm-default" / "scenes" / "scene"
            if not threede_base.exists():
                continue

            # Search for .3de files in subdirectories
            for plate_dir in threede_base.iterdir():
                # Check for cancellation between plate directories
                if cancel_flag and cancel_flag():
                    return []

                if not plate_dir.is_dir():
                    continue

                for threede_file in plate_dir.glob("*.3de"):
                    version = finder._extract_version(threede_file)
                    if version is not None:
                        threede_files.append((threede_file, version))

        # Sort by version and return paths only
        threede_files.sort(key=lambda x: x[1])
        return [f[0] for f in threede_files]
