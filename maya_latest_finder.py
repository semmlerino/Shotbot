"""Finder for the latest Maya scene files in a workspace."""

from __future__ import annotations

# Standard library imports
import re
from collections.abc import Callable
from pathlib import Path

# Local application imports
from version_mixin import VersionHandlingMixin


class MayaLatestFinder(VersionHandlingMixin):
    """Finds the latest Maya scene file in a workspace.

    Uses VersionHandlingMixin for version extraction and sorting.
    """

    # Pattern to match version in Maya filenames (e.g., _v001, _v002)
    VERSION_PATTERN: re.Pattern[str] = re.compile(r"_v(\d{3})\.(ma|mb)$")

    def __init__(self) -> None:
        """Initialize the Maya finder with version handling capabilities."""
        super().__init__()

    def find_latest_maya_scene(
        self,
        workspace_path: str,
        shot_name: str | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Path | None:
        """Find the latest Maya scene file in a workspace.

        Searches for Maya files (.ma and .mb) in the standard VFX directory structure:
        /shows/{show}/shots/{sequence}/{shot}/user/*/mm/maya/scenes/**/*.ma
        /shows/{show}/shots/{sequence}/{shot}/user/*/mm/maya/scenes/**/*.mb

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for better logging
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            Path to the latest Maya scene file, or None if not found or cancelled
        """
        if not workspace_path:
            self.logger.debug("No workspace path provided")
            return None

        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return None

        maya_files: list[tuple[Path, int]] = []

        # Search in all user directories
        user_base = workspace / "user"
        if not user_base.exists():
            self.logger.debug(f"No user directory in workspace: {workspace_path}")
            return None

        # Find all Maya files
        # Search pattern: user/*/mm/maya/scenes/**/*.ma or *.mb
        # The mm/ prefix is the matchmove department directory
        for user_dir in user_base.iterdir():
            # Check for cancellation between user directories
            if cancel_flag and cancel_flag():
                self.logger.debug("Maya scene search cancelled")
                return None

            if not user_dir.is_dir():
                continue

            # Check for maya directory structure (with mm/ department prefix)
            maya_scenes = user_dir / "mm" / "maya" / "scenes"
            if not maya_scenes.exists():
                continue

            # Search recursively for .ma and .mb files (scenes are in subdirs)
            for maya_file in maya_scenes.glob("**/*.ma"):
                # Check for cancellation between files
                if cancel_flag and cancel_flag():
                    self.logger.debug("Maya scene search cancelled")
                    return None

                version = self._extract_version(maya_file)
                if version is not None:
                    maya_files.append((maya_file, version))
                    self.logger.debug(
                        f"Found Maya ASCII file: {maya_file.name} (v{version:03d})"
                    )

            # Check for cancellation between glob operations
            if cancel_flag and cancel_flag():
                self.logger.debug("Maya scene search cancelled")
                return None

            for maya_file in maya_scenes.glob("**/*.mb"):
                # Check for cancellation between files
                if cancel_flag and cancel_flag():
                    self.logger.debug("Maya scene search cancelled")
                    return None

                version = self._extract_version(maya_file)
                if version is not None:
                    maya_files.append((maya_file, version))
                    self.logger.debug(
                        f"Found Maya Binary file: {maya_file.name} (v{version:03d})"
                    )

        if not maya_files:
            self.logger.debug(
                f"No Maya files found in workspace: {shot_name or workspace_path}"
            )
            return None

        # Sort by version number and get the latest
        maya_files.sort(key=lambda x: x[1])
        latest_file = maya_files[-1][0]

        self.logger.info(
            f"Found latest Maya scene for {shot_name or 'shot'}: {latest_file.name}"
        )
        return latest_file

    # Version extraction is handled by VersionHandlingMixin._extract_version()
    # The mixin respects our VERSION_PATTERN and provides fallback patterns

    @staticmethod
    def find_all_maya_scenes(
        workspace_path: str,
        include_autosave: bool = False,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path]:
        """Find all Maya scene files in a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            include_autosave: Whether to include autosave files
            cancel_flag: Optional callable returning True if operation should cancel

        Returns:
            List of all Maya scene files found (empty if cancelled)
        """
        if not workspace_path:
            return []

        workspace = Path(workspace_path)
        if not workspace.exists():
            return []

        maya_files: list[Path] = []
        user_base = workspace / "user"

        if not user_base.exists():
            return []

        for user_dir in user_base.iterdir():
            # Check for cancellation between user directories
            if cancel_flag and cancel_flag():
                return []

            if not user_dir.is_dir():
                continue

            # Check for maya directory structure (with mm/ department prefix)
            maya_scenes = user_dir / "mm" / "maya" / "scenes"
            if not maya_scenes.exists():
                continue

            # Get all .ma and .mb files recursively
            for maya_file in maya_scenes.glob("**/*.ma"):
                # Check for cancellation between files
                if cancel_flag and cancel_flag():
                    return []

                # Skip autosave files unless requested
                if not include_autosave and ".autosave" in maya_file.name:
                    continue
                maya_files.append(maya_file)

            # Check for cancellation between glob operations
            if cancel_flag and cancel_flag():
                return []

            for maya_file in maya_scenes.glob("**/*.mb"):
                # Check for cancellation between files
                if cancel_flag and cancel_flag():
                    return []

                # Skip autosave files unless requested
                if not include_autosave and ".autosave" in maya_file.name:
                    continue
                maya_files.append(maya_file)

        return maya_files
