"""Finder for user-specific image sequences (Maya playblasts, Nuke renders).

This module discovers image sequences for the current user only, returning
only the latest version of each sequence type.

Path patterns:
- Maya: {workspace}/user/{username}/mm/maya/playblast/{type}/v###/{type}.#.png
- Nuke: {workspace}/user/{username}/mm/nuke/outputs/mm-default/scene/{plate}/camera/{type}/v###/{resolution}/exr/{filename}.#.exr
"""

from __future__ import annotations

import getpass
import os
import re
from datetime import datetime
from pathlib import Path

from logging_mixin import get_module_logger
from scene_file import ImageSequence


logger = get_module_logger(__name__)


class UserSequenceFinder:
    """Find Maya playblasts and Nuke renders for current user only.

    Returns only the latest version of each sequence type.
    """

    @staticmethod
    def get_current_username() -> str:
        """Get current username from environment or system."""
        return os.environ.get("USER", getpass.getuser())

    @classmethod
    def find_maya_playblasts(
        cls,
        workspace_path: str,
        username: str | None = None,
    ) -> list[ImageSequence]:
        """Find Maya playblast sequences for user.

        Scans: {workspace}/user/{username}/mm/maya/playblast/{type}/v###/
        Returns only the LATEST version of each playblast type.

        Args:
            workspace_path: Shot workspace path
            username: Username to search for (defaults to current user)

        Returns:
            List of ImageSequence objects, sorted by modified time (newest first)

        """
        if username is None:
            username = cls.get_current_username()

        logger.info(
            f"Searching Maya playblasts for user '{username}' in workspace: {workspace_path}"
        )

        base_path = (
            Path(workspace_path) / "user" / username / "mm" / "maya" / "playblast"
        )
        if not base_path.exists():
            logger.info(f"Maya playblast path does not exist: {base_path}")
            return []

        logger.info(f"Found playblast directory, scanning: {base_path}")

        sequences: dict[str, ImageSequence] = {}  # type -> latest sequence

        try:
            # Scan for playblast types (subdirectories like "Cones", "Wireframe")
            for type_dir in base_path.iterdir():
                if not type_dir.is_dir():
                    continue

                playblast_type = type_dir.name
                latest = cls._find_latest_version_sequence(
                    type_dir=type_dir,
                    render_type=playblast_type,
                    sequence_type="maya_playblast",
                    username=username,
                    extension="png",
                )
                if latest:
                    sequences[playblast_type] = latest

        except OSError as e:
            logger.warning(f"Error scanning Maya playblasts at {base_path}: {e}")
            return []

        # Sort by modified time (newest first)
        result = sorted(sequences.values(), key=lambda s: s.modified_time, reverse=True)
        logger.info(f"Found {len(result)} Maya playblast sequence(s)")
        return result

    @classmethod
    def find_nuke_renders(
        cls,
        workspace_path: str,
        username: str | None = None,
    ) -> list[ImageSequence]:
        """Find Nuke render sequences for user.

        Scans: {workspace}/user/{username}/mm/nuke/outputs/
        Returns only the LATEST version of each render type.

        Args:
            workspace_path: Shot workspace path
            username: Username to search for (defaults to current user)

        Returns:
            List of ImageSequence objects, sorted by modified time (newest first)

        """
        if username is None:
            username = cls.get_current_username()

        logger.info(
            f"Searching Nuke renders for user '{username}' in workspace: {workspace_path}"
        )

        base_path = Path(workspace_path) / "user" / username / "mm" / "nuke" / "outputs"
        if not base_path.exists():
            logger.info(f"Nuke outputs path does not exist: {base_path}")
            return []

        logger.info(f"Found Nuke outputs directory, scanning: {base_path}")

        sequences: dict[str, ImageSequence] = {}  # unique_key -> latest

        try:
            # Recursively find 'exr' directories containing renders
            for exr_dir in base_path.rglob("exr"):
                if not exr_dir.is_dir():
                    continue

                # Find EXR files in this directory
                exr_files = list(exr_dir.glob("*.exr"))
                if not exr_files:
                    continue

                # Use first file to create sequence
                sample = exr_files[0]
                sequence = cls._create_sequence_from_nuke_render(
                    sample_file=sample,
                    containing_dir=exr_dir,
                    username=username,
                )
                if sequence:
                    # Deduplicate by render_type (keep latest version)
                    key = sequence.render_type
                    existing = sequences.get(key)
                    if existing is None or (sequence.version or 0) > (
                        existing.version or 0
                    ):
                        sequences[key] = sequence

        except OSError as e:
            logger.warning(f"Error scanning Nuke renders at {base_path}: {e}")
            return []

        result = sorted(sequences.values(), key=lambda s: s.modified_time, reverse=True)
        logger.info(f"Found {len(result)} Nuke render sequence(s)")
        return result

    @classmethod
    def _find_latest_version_sequence(
        cls,
        type_dir: Path,
        render_type: str,
        sequence_type: str,
        username: str,
        extension: str,
    ) -> ImageSequence | None:
        """Find latest version directory and create sequence from it.

        Args:
            type_dir: Directory containing version subdirectories
            render_type: Type name (e.g., "Cones", "Wireframe")
            sequence_type: Sequence category ("maya_playblast" or "nuke_render")
            username: Username
            extension: File extension to look for

        Returns:
            ImageSequence for the latest version, or None if not found

        """
        # Find version directories (v001, v002, etc.)
        version_dirs: list[tuple[Path, int]] = []
        try:
            for d in type_dir.iterdir():
                if d.is_dir() and d.name.startswith("v"):
                    version_str = d.name[1:]
                    if version_str.isdigit():
                        version_dirs.append((d, int(version_str)))
        except OSError:
            return None

        if not version_dirs:
            return None

        # Sort by version number descending to get latest
        version_dirs.sort(key=lambda x: x[1], reverse=True)
        latest_dir, latest_version = version_dirs[0]

        # Find sequence files
        try:
            files = list(latest_dir.glob(f"*.{extension}"))
        except OSError:
            return None

        if not files:
            return None

        # Get sample file for metadata
        sample = files[0]

        return cls._create_sequence_from_sample(
            sample_file=sample,
            containing_dir=latest_dir,
            render_type=render_type,
            sequence_type=sequence_type,
            username=username,
            version=latest_version,
            extension=extension,
        )

    @classmethod
    def _create_sequence_from_sample(
        cls,
        sample_file: Path,
        containing_dir: Path,
        render_type: str,
        sequence_type: str,
        username: str,
        version: int,
        extension: str,
    ) -> ImageSequence | None:
        """Create ImageSequence from a sample file.

        Args:
            sample_file: A sample file from the sequence
            containing_dir: Directory containing the sequence
            render_type: Type name
            sequence_type: Sequence category
            username: Username
            version: Version number
            extension: File extension

        Returns:
            ImageSequence object, or None on error

        """
        # Build pattern path (replace frame numbers with ####)
        # Match 4+ digit frame numbers at end of filename before extension
        frame_pattern = re.sub(
            rf"\.(\d{{4,}})\.{extension}$",
            f".####.{extension}",
            sample_file.name,
            flags=re.IGNORECASE,
        )
        pattern_path = containing_dir / frame_pattern

        # Detect frame range by scanning directory
        first_frame, last_frame = cls._detect_frame_range(containing_dir, extension)

        # Get modification time from sample file
        try:
            mtime = datetime.fromtimestamp(  # noqa: DTZ006 - Local time is intentional
                sample_file.stat().st_mtime
            )
        except OSError:
            mtime = datetime.now()  # noqa: DTZ005 - Local time is intentional

        return ImageSequence(
            path=pattern_path,
            sequence_type=sequence_type,
            modified_time=mtime,
            user=username,
            version=version,
            first_frame=first_frame,
            last_frame=last_frame,
            render_type=render_type,
        )

    @classmethod
    def _create_sequence_from_nuke_render(
        cls,
        sample_file: Path,
        containing_dir: Path,
        username: str,
    ) -> ImageSequence | None:
        """Create ImageSequence from a Nuke render sample file.

        Extracts render type and version from path structure.

        Args:
            sample_file: A sample EXR file
            containing_dir: Directory containing the sequence
            username: Username

        Returns:
            ImageSequence object, or None on error

        """
        # Extract version from path (look for v### pattern)
        path_str = str(sample_file)
        version_match = re.search(r"/v(\d{3})/", path_str)
        version = int(version_match.group(1)) if version_match else None

        # Extract render type from path
        # Path: .../camera/{type}/v###/...
        # Look for the directory before the version directory
        render_type = cls._extract_render_type_from_path(containing_dir)

        return cls._create_sequence_from_sample(
            sample_file=sample_file,
            containing_dir=containing_dir,
            render_type=render_type,
            sequence_type="nuke_render",
            username=username,
            version=version or 1,
            extension="exr",
        )

    @staticmethod
    def _extract_render_type_from_path(exr_dir: Path) -> str:
        """Extract render type name from Nuke output path.

        Path structure: .../camera/{type}/v###/{resolution}/exr/
        We want to extract {type}.

        Args:
            exr_dir: The 'exr' directory path

        Returns:
            Render type name, or "unknown" if not found

        """
        # Walk up the path looking for the type directory
        # exr -> resolution -> v### -> type -> camera
        parts = exr_dir.parts

        # Find 'exr' position and walk back
        for i, part in enumerate(parts):
            if part == "exr" and i >= 4:
                # resolution is at i-1, v### at i-2, type at i-3
                potential_type = parts[i - 3]
                # Verify v### is at i-2
                if parts[i - 2].startswith("v") and parts[i - 2][1:].isdigit():
                    return potential_type

        # Fallback: use parent directory name before exr
        if len(parts) >= 2:
            return parts[-2]

        return "unknown"

    @staticmethod
    def _detect_frame_range(directory: Path, extension: str) -> tuple[int, int]:
        """Detect frame range by scanning files in directory.

        Args:
            directory: Directory containing sequence files
            extension: File extension to scan

        Returns:
            Tuple of (first_frame, last_frame), defaults to (1001, 1100)

        """
        # Pattern to extract frame numbers from filenames
        frame_pattern = re.compile(rf"\.(\d{{4,}})\.{extension}$", re.IGNORECASE)

        frames: list[int] = []
        try:
            for file_path in directory.iterdir():
                if not file_path.is_file():
                    continue
                match = frame_pattern.search(file_path.name)
                if match:
                    frames.append(int(match.group(1)))
        except OSError:
            pass

        if frames:
            return min(frames), max(frames)

        # Default VFX frame range
        return 1001, 1100
