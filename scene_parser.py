"""SceneParser module - Extracted from threede_scene_finder_optimized.py

This module handles parsing of 3DE file paths and extraction of scene information
including plates, shots, sequences, and user details. Contains optimized regex
patterns and parsing logic.

Part of the Phase 2 refactoring to break down the monolithic scene finder.
"""
# pyright: reportImportCycles=false
# Import cycle is broken at runtime by lazy imports in threede_scene_finder_optimized.py
# and threede_scene_model.py. The TYPE_CHECKING import is only for type annotations.

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

# Local application imports
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from threede_scene_model import ThreeDEScene


class SceneParser(LoggingMixin):
    """Parser for 3DE scene file paths with optimized pattern matching.

    This class encapsulates all parsing logic extracted from the monolithic
    scene finder, providing clean separation of concerns for path analysis
    and scene information extraction.
    """

    # Pre-compiled regex patterns for performance
    _BG_FG_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^[bf]g\d{2}$", re.IGNORECASE)
    _PLATE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"^[bf]g\d{2}$", re.IGNORECASE),
        re.compile(r"^plate_?\d+$", re.IGNORECASE),
        re.compile(r"^comp_?\d+$", re.IGNORECASE),
        re.compile(r"^shot_?\d+$", re.IGNORECASE),
        re.compile(r"^sc\d+$", re.IGNORECASE),
        re.compile(r"^[\w]+_v\d{3}$", re.IGNORECASE),
    ]

    # Optimize generic directories lookup with set
    _GENERIC_DIRS: ClassVar[set[str]] = {
        "3de",
        "scenes",
        "scene",
        "mm",
        "matchmove",
        "tracking",
        "work",
        "wip",
        "exports",
        "user",
        "files",
        "data",
    }

    def __init__(self) -> None:
        """Initialize SceneParser."""
        super().__init__()

    @staticmethod
    def extract_shot_name(sequence: str, shot_dir: str) -> str:
        """Extract the shot identifier from a shot directory name.

        Shot directories follow the convention ``{sequence}_{shot}``.
        This method strips the sequence prefix to yield just the shot token.
        If the directory does not start with the expected prefix, it falls back
        to splitting on the last underscore.

        Args:
            sequence: Sequence name (e.g. "SQ010").
            shot_dir: Shot directory name (e.g. "SQ010_0010").

        Returns:
            Shot identifier string (e.g. "0010"), or the full ``shot_dir``
            if no underscore is found.

        """
        if shot_dir.startswith(f"{sequence}_"):
            return shot_dir[len(sequence) + 1:]  # +1 for the underscore
        shot_parts = shot_dir.rsplit("_", 1)
        return shot_parts[1] if len(shot_parts) == 2 else shot_dir

    def extract_plate_from_path(self, file_path: Path, user_path: Path) -> str:
        """Optimized plate extraction with fast path lookup.

        Args:
            file_path: Path to the .3de file
            user_path: Path to the user directory

        Returns:
            Extracted plate name

        """
        try:
            # Fast path: check parent directory name first (most common case)
            parent_name = file_path.parent.name

            # Quick BG/FG pattern check (most common)
            if self._BG_FG_PATTERN.match(parent_name):
                return parent_name

            # Get relative path for pattern matching
            try:
                relative_path = file_path.relative_to(user_path)
                path_parts = relative_path.parts[:-1]  # Exclude filename
            except ValueError:
                # Can't make relative path, use parent
                return parent_name

            # Check all patterns on path parts
            for part in path_parts:
                # BG/FG gets priority (already checked parent, check others)
                if self._BG_FG_PATTERN.match(part):
                    return part

                # Check other patterns
                for pattern in self._PLATE_PATTERNS:
                    if pattern.match(part):
                        return part

            # Fallback: use non-generic directory closest to file
            for part in reversed(path_parts):
                if part.lower() not in self._GENERIC_DIRS:
                    return part

            # Last resort: parent directory
            return parent_name

        except Exception:
            # Error handling: use parent directory
            return file_path.parent.name

    def parse_3de_file_path(
        self,
        threede_file: Path,
        show_path: Path,
        show: str,
        excluded_users: set[str],
    ) -> tuple[Path, str, str, str, str, str] | None:
        """Parse a 3DE file path to extract shot information.

        Args:
            threede_file: Path to the .3de file
            show_path: Path to the show directory
            show: Show name
            excluded_users: Set of usernames to exclude

        Returns:
            Tuple of (file_path, show, sequence, shot, user, plate) or None if invalid

        """
        try:
            # Parse the path to extract shot information
            parts = threede_file.relative_to(show_path).parts

            # Expected structure: shots/sequence/shot/user/username/.../file.3de
            # or: shots/sequence/shot/publish/.../file.3de
            if len(parts) < 4 or parts[0] != "shots":
                return None

            sequence = parts[1]
            shot_dir = parts[2]

            # Validate sequence and shot_dir are not empty
            if not sequence or not shot_dir:
                return None

            # Extract shot number from directory name to match ws -sg parsing
            # The shot directory format is {sequence}_{shot}
            shot = SceneParser.extract_shot_name(sequence, shot_dir)

            # Validate shot is not empty
            if not shot:
                return None

            # Determine user and plate
            if parts[3] == "user" and len(parts) > 4:
                user = parts[4]
                # Validate user is not empty
                if not user or user in excluded_users:
                    return None
            elif parts[3] == "publish":
                # For published files, create a pseudo-user
                department = parts[4] if len(parts) > 4 else "unknown"
                if not department:
                    department = "unknown"
                user = f"published-{department}"
            else:
                return None  # Skip non-standard paths

            # Extract plate from path
            workspace_path = show_path / "shots" / sequence / shot_dir
            user_path = (
                workspace_path / "user" / user
                if parts[3] == "user"
                else workspace_path / "publish"
            )
            plate = self.extract_plate_from_path(threede_file, user_path)

            return (threede_file, show, sequence, shot, user, plate)

        except (ValueError, IndexError) as e:
            self.logger.debug(f"Could not parse path {threede_file}: {e}")
            return None

    def create_scene_from_file_info(
        self,
        file_path: Path,
        show: str,
        sequence: str,
        shot: str,
        user: str,
        plate: str,
        workspace_path: str,
    ) -> ThreeDEScene:
        """Create a ThreeDEScene object from parsed file information.

        Args:
            file_path: Path to the .3de file
            show: Show name
            sequence: Sequence name
            shot: Shot name
            user: Username
            plate: Plate name
            workspace_path: Shot workspace path

        Returns:
            ThreeDEScene instance

        """
        # Local application imports
        from frame_range_extractor import extract_frame_range
        from threede_scene_model import ThreeDEScene

        # Get file modification time for sorting (0.0 if unavailable)
        try:
            modified_time = file_path.stat().st_mtime
        except OSError:
            modified_time = 0.0

        # Extract frame range for scrub preview
        frame_range = extract_frame_range(workspace_path)
        frame_start = frame_range[0] if frame_range else None
        frame_end = frame_range[1] if frame_range else None

        scene = ThreeDEScene(
            show=show,
            sequence=sequence,
            shot=shot,
            workspace_path=workspace_path,
            user=user,
            plate=plate,
            scene_path=file_path,
            modified_time=modified_time,
            frame_start=frame_start,
            frame_end=frame_end,
        )

        self.logger.debug(f"Created scene: {show}/{sequence}/{shot} - {user}/{plate}")
        return scene

    def extract_shot_from_workspace_path(
        self, workspace_path: str
    ) -> tuple[str, str, str] | None:
        """Extract show, sequence, and shot from a workspace path.

        Args:
            workspace_path: Full path to shot workspace

        Returns:
            Tuple of (show, sequence, shot) or None if parsing fails

        """
        try:
            path = Path(workspace_path)
            parts = path.parts

            # Find the 'shots' directory in the path
            shots_idx = None
            for i, part in enumerate(parts):
                if part == "shots":
                    shots_idx = i
                    break

            if shots_idx is None or len(parts) <= shots_idx + 2:
                return None

            # Extract show (directory before 'shots')
            show = parts[shots_idx - 1] if shots_idx > 0 else "unknown"

            # Extract sequence and shot directory
            sequence = parts[shots_idx + 1]
            shot_dir = parts[shots_idx + 2]

            # Parse shot from shot directory name
            if shot_dir.startswith(f"{sequence}_"):
                shot = shot_dir[len(sequence) + 1 :]
            else:
                shot_parts = shot_dir.rsplit("_", 1)
                shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

            return (show, sequence, shot)

        except (IndexError, ValueError) as e:
            self.logger.debug(f"Could not parse workspace path {workspace_path}: {e}")
            return None

    def validate_scene_file(self, scene_path: Path) -> bool:
        """Validate that a scene file is a valid .3de file.

        Args:
            scene_path: Path to the scene file

        Returns:
            True if valid .3de file, False otherwise

        """
        if not scene_path or not scene_path.exists():
            return False

        # Check file extension
        if scene_path.suffix.lower() not in [".3de"]:
            return False

        # Check if file is readable
        try:
            return scene_path.is_file() and scene_path.stat().st_size > 0
        except (OSError, PermissionError):
            return False

    def get_plate_patterns(self) -> list[re.Pattern[str]]:
        """Get the compiled regex patterns used for plate detection.

        Returns:
            List of compiled regex patterns

        """
        return self._PLATE_PATTERNS.copy()

    def get_generic_directories(self) -> set[str]:
        """Get the set of generic directory names that are deprioritized in plate extraction.

        Returns:
            Set of generic directory names

        """
        return self._GENERIC_DIRS.copy()

    def is_bg_fg_plate(self, plate_name: str) -> bool:
        """Check if a plate name matches the BG/FG pattern.

        Args:
            plate_name: Name to check

        Returns:
            True if matches BG/FG pattern, False otherwise

        """
        return bool(self._BG_FG_PATTERN.match(plate_name))

    def matches_plate_pattern(self, name: str) -> bool:
        """Check if a name matches any of the plate patterns.

        Args:
            name: Name to check

        Returns:
            True if matches any plate pattern, False otherwise

        """
        return any(pattern.match(name) for pattern in self._PLATE_PATTERNS)

    def is_generic_directory(self, dir_name: str) -> bool:
        """Check if a directory name is considered generic.

        Args:
            dir_name: Directory name to check

        Returns:
            True if generic directory, False otherwise

        """
        return dir_name.lower() in self._GENERIC_DIRS
