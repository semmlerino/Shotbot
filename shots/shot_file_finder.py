"""Shot file discovery service for finding files associated with shots."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from dcc.scene_file import FileType, SceneFile
from discovery import MayaLatestFinder
from threede import ThreeDELatestFinder
from utils import get_current_username
from version_mixin import VersionHandlingMixin


_CURRENT_USERNAME: str = get_current_username()


if TYPE_CHECKING:
    from type_definitions import Shot


class ShotFileFinder(VersionHandlingMixin):
    """Discovers files for a shot using existing finders.

    Provides a unified interface for finding 3DE, Maya, and Nuke files
    associated with a shot workspace.
    """

    # Version extraction patterns — end-anchored to match _v001.ext at filename end only
    VERSION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"_v(\d{3})\.[^.]+$")

    def find_all_files(self, shot: Shot) -> dict[FileType, list[SceneFile]]:
        """Find all files grouped by type.

        Args:
            shot: The shot to find files for

        Returns:
            Dictionary mapping FileType to list of SceneFile objects,
            sorted by modification time (newest first) within each type

        """
        return {
            FileType.THREEDE: self._find_threede_files(shot),
            FileType.MAYA: self._find_maya_files(shot),
            FileType.NUKE: self._find_nuke_files(shot),
        }

    def _find_threede_files(self, shot: Shot) -> list[SceneFile]:
        """Find 3DE scene files for a shot.

        Args:
            shot: The shot to find files for

        Returns:
            List of SceneFile objects for 3DE files, sorted by mtime (newest first)

        """
        paths = ThreeDELatestFinder.find_all_scenes(shot.workspace_path)
        return self._paths_to_scene_files(paths, FileType.THREEDE)

    def _find_maya_files(self, shot: Shot) -> list[SceneFile]:
        """Find Maya scene files for a shot.

        Args:
            shot: The shot to find files for

        Returns:
            List of SceneFile objects for Maya files, sorted by mtime (newest first)

        """
        from dataclasses import replace

        from discovery import load_maya_comments

        paths = MayaLatestFinder.find_all_scenes(shot.workspace_path)
        scene_files = self._paths_to_scene_files(paths, FileType.MAYA)

        # Attach version-up comments from ~/.maya_version_up/
        comments = load_maya_comments([f.path for f in scene_files])
        if comments:
            scene_files = [
                replace(f, comment=comments[str(f.path)])
                if str(f.path) in comments
                else f
                for f in scene_files
            ]

        return scene_files

    def _find_nuke_files(self, shot: Shot) -> list[SceneFile]:
        """Find Nuke script files for a shot.

        Scans all user directories for Nuke scripts following the pattern:
        workspace/user/*/mm/nuke/**/*.nk

        Args:
            shot: The shot to find files for

        Returns:
            List of SceneFile objects for Nuke files, sorted by mtime (newest first)

        """
        workspace = Path(shot.workspace_path)
        if not workspace.exists():
            return []

        nuke_files: list[Path] = []
        user_base = workspace / "user"

        if not user_base.exists():
            return []

        try:
            for user_dir in user_base.iterdir():
                if not user_dir.is_dir():
                    continue

                if user_dir.name != _CURRENT_USERNAME:
                    continue

                # Check for nuke directory structure (with mm/ department prefix)
                nuke_base = user_dir / "mm" / "nuke"
                if not nuke_base.exists():
                    continue

                # Get all .nk files recursively
                for nuke_file in nuke_base.glob("**/*.nk"):
                    # Skip autosave or backup files
                    if ".autosave" in nuke_file.name or nuke_file.name.startswith("."):
                        continue
                    nuke_files.append(nuke_file)

        except (OSError, PermissionError):
            self.logger.warning("Error scanning for Nuke files", exc_info=True)
            return []

        return self._paths_to_scene_files(nuke_files, FileType.NUKE)

    def _paths_to_scene_files(
        self,
        paths: list[Path],
        file_type: FileType,
    ) -> list[SceneFile]:
        """Convert list of paths to SceneFile objects.

        Args:
            paths: List of file paths
            file_type: The type of files

        Returns:
            List of SceneFile objects, sorted by modification time (newest first)

        """
        scene_files: list[SceneFile] = []

        for path in paths:
            try:
                stat = path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)  # noqa: DTZ006 - Local time from filesystem
                user = self._extract_user_from_path(path)
                version = self._extract_version(path)

                scene_file = SceneFile(
                    path=path,
                    file_type=file_type,
                    modified_time=mtime,
                    user=user,
                    version=version,
                    read_only=not os.access(path, os.W_OK),
                )
                scene_files.append(scene_file)

            except (OSError, PermissionError) as e:
                self.logger.debug(f"Could not stat file {path}: {e}")
                continue

        # Sort by modification time, newest first
        scene_files.sort(key=lambda f: f.modified_time, reverse=True)
        return scene_files

    def _extract_user_from_path(self, path: Path) -> str:
        """Extract username from file path.

        Expects path pattern: .../user/{username}/...

        Args:
            path: File path

        Returns:
            Username or 'unknown' if not found

        """
        parts = path.parts
        try:
            user_idx = parts.index("user")
            if user_idx + 1 < len(parts):
                return parts[user_idx + 1]
        except ValueError:
            pass
        return "unknown"
