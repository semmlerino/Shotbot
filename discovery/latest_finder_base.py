"""Base class for DCC latest scene file finders.

Provides shared logic for finding the latest versioned scene file in a
workspace directory by searching under user subdirectories.
"""

from __future__ import annotations

# Standard library imports
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

# Local application imports
from version_mixin import VersionHandlingMixin


class BaseLatestFinder(VersionHandlingMixin):
    """Base class for DCC-specific latest scene file finders.

    Subclasses declare class-level attributes describing the DCC tool's
    directory structure and file patterns.  The concrete ``find_latest_scene``
    and ``find_all_scenes`` methods implement the common search loop so that
    each subclass only needs to supply configuration, not logic.

    Class attributes to define in each subclass:
        _DCC_SUBPATH: Relative path from a user directory to the DCC scene
            root (e.g. ``"mm/maya/scenes"``).
        _GLOB_PATTERNS: Glob patterns applied inside the scene root
            (e.g. ``["**/*.ma", "**/*.mb"]``).
        _DCC_LABEL: Human-readable name for log messages (e.g. ``"Maya"``).
    """

    _DCC_SUBPATH: ClassVar[str]
    _GLOB_PATTERNS: ClassVar[list[str]]
    _DCC_LABEL: ClassVar[str]

    def find_latest_scene(
        self,
        workspace_path: str,
        shot_name: str | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Path | None:
        """Find the latest DCC scene file in a workspace.

        Searches all user subdirectories under ``workspace_path/user/``,
        appends ``_DCC_SUBPATH``, then globs using ``_GLOB_PATTERNS``.
        Picks the file with the highest version number.

        Args:
            workspace_path: Full path to the shot workspace.
            shot_name: Optional shot name for log messages.
            cancel_flag: Optional callable returning ``True`` when the
                operation should be cancelled.

        Returns:
            Path to the latest scene file, or ``None`` if not found or
            cancelled.

        """
        if not workspace_path:
            self.logger.debug("No workspace path provided")
            return None

        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return None

        user_base = workspace / "user"
        if not user_base.exists():
            self.logger.debug(f"No user directory in workspace: {workspace_path}")
            return None

        files = self._collect_scene_files(
            user_base, self._DCC_SUBPATH, self._GLOB_PATTERNS, cancel_flag
        )
        if files is None:
            self.logger.debug(f"{self._DCC_LABEL} scene search cancelled")
            return None

        if not files:
            self.logger.debug(
                f"No {self._DCC_LABEL} files found in workspace: "
                f"{shot_name or workspace_path}"
            )
            return None

        latest_file = self._find_latest_by_version(files)
        if latest_file is None:
            self.logger.debug(
                f"No versioned {self._DCC_LABEL} files found in workspace: "
                f"{shot_name or workspace_path}"
            )
            return None

        self.logger.info(
            f"Found latest {self._DCC_LABEL} scene for "
            f"{shot_name or 'shot'}: {latest_file.name}"
        )
        return latest_file

    @classmethod
    def find_all_scenes(
        cls,
        workspace_path: str,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[Path]:
        """Find all DCC scene files in a workspace, sorted by version.

        Args:
            workspace_path: Full path to the shot workspace.
            cancel_flag: Optional callable returning ``True`` when the
                operation should be cancelled.

        Returns:
            List of scene file paths sorted by version (ascending), or an
            empty list if the workspace does not exist or the operation was
            cancelled.

        """
        if not workspace_path:
            return []

        workspace = Path(workspace_path)
        if not workspace.exists():
            return []

        user_base = workspace / "user"
        if not user_base.exists():
            return []

        finder = cls()
        collected = finder._collect_scene_files(
            user_base, cls._DCC_SUBPATH, cls._GLOB_PATTERNS, cancel_flag
        )
        if collected is None:
            return []

        return finder._sort_files_by_version(collected)
