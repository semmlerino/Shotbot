"""Thumbnail finding utilities for VFX pipeline.

This module provides utilities for finding thumbnail images in various
locations within the VFX pipeline structure.
"""

from __future__ import annotations

# Standard library imports
import os
import re
from pathlib import Path

# Local application imports
from config import (
    Config,  # noqa: F401  # pyright: ignore[reportUnusedImport] — monkeypatched by tests
)
from discovery.file_discovery import FileDiscovery
from logging_mixin import get_module_logger
from paths.builders import PathBuilders
from paths.validators import PathValidators
from utils import FileUtils, find_path_case_insensitive
from version_utils import VersionUtils


logger = get_module_logger(__name__)


def _extract_frame_number(path: Path) -> int:
    """Extract frame number from a filename like ``name.1001.exr``."""
    match = re.search(r"\.(\d{4})\.exr$", path.name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 99999  # Sort non-matching files last


def _find_first_jpeg_in_version_tree(
    base_path: Path,
    image_subdir: str = "jpeg",
) -> Path | None:
    """Return the first JPEG found under ``base_path/<latest_version>/<image_subdir>/<resolution>/``.

    Calls ``VersionUtils.get_latest_version(base_path)`` to determine the version
    directory, then iterates resolution sub-directories (e.g. ``4312x2304``) looking
    for the first file whose suffix is ``.jpg`` or ``.jpeg``.

    Args:
        base_path: Directory that contains versioned sub-directories (v001, v002, …).
        image_subdir: Name of the image format directory inside the version directory.
            Defaults to ``"jpeg"``; pass ``"jpg"`` for editorial cutref paths.

    Returns:
        Path to the first JPEG file found, or ``None`` if nothing matches.

    """
    latest_version = VersionUtils.get_latest_version(base_path)
    if not latest_version:
        logger.debug(f"No version found in {base_path}")
        return None

    jpeg_base_path = base_path / latest_version / image_subdir
    if not PathValidators.validate_path_exists(jpeg_base_path, "JPEG base path"):
        return None

    try:
        for resolution_dir in jpeg_base_path.iterdir():
            if resolution_dir.is_dir():
                jpeg_file = FileUtils.get_first_image_file(resolution_dir)
                if jpeg_file and jpeg_file.suffix.lower() in [".jpg", ".jpeg"]:
                    logger.debug(
                        f"Found JPEG in version tree: {jpeg_file.name}"
                        f" (version: {latest_version}, resolution: {resolution_dir.name})"
                    )
                    return jpeg_file
    except (OSError, PermissionError) as e:
        logger.debug(f"Error scanning JPEG directory {jpeg_base_path}: {e}")

    return None


class ThumbnailFinders:
    """Utilities for finding thumbnail images in VFX pipeline."""

    @staticmethod
    def _shot_path(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
        *suffix: str,
    ) -> Path:
        """Build a path rooted at the shot directory, with optional suffix components."""
        shot_dir = f"{sequence}_{shot}"
        return PathBuilders.build_path(shows_root, show, "shots", sequence, shot_dir, *suffix)

    @staticmethod
    def find_turnover_plate_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find thumbnail from turnover plate directories with preference order.

        Searches for plate files in:
        /shows/{show}/shots/{sequence}/{shot}/publish/turnover/plate/input_plate/{PLATE}/v001/exr/{resolution}/

        Plate preference order:
        1. FG plates (FG01, FG02, etc.)
        2. BG plates (BG01, BG02, etc.)
        3. Any other available plates (EL01, etc.)

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first frame of best available plate, or None if not found

        """
        # Build candidate paths in preference order: with input_plate first, then without
        turnover_plate_base = ThumbnailFinders._shot_path(
            shows_root, show, sequence, shot, "publish", "turnover", "plate",
        )
        candidates = [
            turnover_plate_base / "input_plate",
            turnover_plate_base,
        ]
        base_path: Path | None = next(
            (p for p in candidates if PathValidators.validate_path_exists(p, "Turnover plate directory")),
            None,
        )
        if base_path is None:
            return None

        # Find all available plate directories
        try:
            plate_dirs = [d for d in base_path.iterdir() if d.is_dir()]
        except (OSError, PermissionError) as e:
            logger.debug(f"Error accessing turnover plates: {e}")
            return None

        if not plate_dirs:
            logger.debug(f"No plate directories found in {base_path}")
            return None

        # Sort plates by preference
        def plate_priority(plate_dir: Path) -> tuple[int, str]:
            """Return priority tuple for sorting plates."""
            name = plate_dir.name.upper()
            # Priority: (order, name)
            # Lower order = higher priority
            if name.startswith("FG"):
                return (0, name)  # FG plates highest priority
            if name.startswith("BG"):
                return (1, name)  # BG plates second priority
            return (2, name)  # All others lowest priority

        sorted_plates = sorted(plate_dirs, key=plate_priority)

        # Try each plate in priority order
        for plate_dir in sorted_plates:
            plate_name = plate_dir.name

            # Look for v001/exr/*/
            version_path = plate_dir / "v001" / "exr"
            if not version_path.exists():
                continue

            # Find resolution directories (e.g., 4312x2304)
            try:
                resolution_dirs = [d for d in version_path.iterdir() if d.is_dir()]
            except (OSError, PermissionError):
                continue

            for res_dir in resolution_dirs:
                # Find first frame (typically .1001.exr or .0001.exr)
                exr_files = FileUtils.find_files_by_extension(res_dir, ".exr", limit=10)
                if not exr_files:
                    continue

                # Sort to get the first frame number
                # Files like: GG_000_0050_turnover-plate_EL01_lin_sgamut3cine_v001.1001.exr
                sorted_frames = sorted(exr_files, key=_extract_frame_number)
                first_frame = sorted_frames[0]

                file_size_mb = first_frame.stat().st_size / (1024 * 1024)
                logger.debug(
                    f"Using turnover plate EXR: {plate_name} - {first_frame.name} ({file_size_mb:.1f}MB)",
                )
                return first_frame

        logger.debug(f"No suitable turnover plates found for {sequence}_{shot}")
        return None

    @staticmethod
    def find_any_publish_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
        max_depth: int = 5,
    ) -> Path | None:
        """Find any EXR file with frame 1001 in the publish directory.

        This is a fallback thumbnail finder that recursively searches the publish
        directory for any EXR file containing "1001" in the filename (typically
        the first frame of a sequence).

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name
            max_depth: Maximum depth to search (default 5)

        Returns:
            Path to first matching EXR file, or None if not found

        """
        # Build path to publish directory
        publish_path = ThumbnailFinders._shot_path(shows_root, show, sequence, shot, "publish")

        # Check if publish directory exists
        if not publish_path.exists():
            logger.debug(f"Publish directory does not exist: {publish_path}")
            return None

        try:
            # Walk the directory tree with depth limiting
            for root, dirs, files in os.walk(publish_path):
                # Calculate current depth relative to publish_path
                rel_path = Path(root).relative_to(publish_path)
                depth = len(rel_path.parts) if str(rel_path) != "." else 0

                # Stop descending if we've reached max depth
                if depth >= max_depth:
                    dirs.clear()  # Don't descend further
                    continue

                # Look for EXR files with 1001 in the name
                for filename in files:
                    if "1001" in filename and filename.lower().endswith(".exr"):
                        result = Path(root) / filename
                        logger.debug(f"Found publish thumbnail: {result}")
                        return result

        except (OSError, PermissionError) as e:
            logger.debug(f"Error searching publish directory: {e}")
            return None

        logger.debug(f"No 1001.exr files found in {publish_path}")
        return None

    @staticmethod
    def find_undistorted_jpeg_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find JPEG thumbnail from undistorted plate in publish/mm structure.

        Searches for JPEG files in:
        /shows/{show}/shots/{sequence}/{shot}/publish/mm/default/{camera}/undistorted_plate/{version}/jpeg/{resolution}/

        This provides high-quality thumbnails without requiring EXR processing,
        using existing undistorted plates from the VFX pipeline.

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first JPEG file found, or None if not found

        """
        # Build base path to mm/default directory
        mm_default_path = ThumbnailFinders._shot_path(
            shows_root, show, sequence, shot, "publish", "mm", "default",
        )

        if not PathValidators.validate_path_exists(mm_default_path, "MM default path"):
            return None

        # Discover available camera/plate directories using priority order
        plate_dirs = FileDiscovery.discover_plate_directories(mm_default_path)

        # Try each plate directory in priority order
        for plate_name, _priority in plate_dirs:
            # Get plate directory with case-insensitive lookup
            plate_dir = find_path_case_insensitive(mm_default_path, plate_name)
            if plate_dir is None:
                continue

            plate_path = plate_dir / "undistorted_plate"
            if not PathValidators.validate_path_exists(plate_path, "Undistorted plate path"):
                continue

            # Find latest version directory and first JPEG inside jpeg subdir
            jpeg_file = _find_first_jpeg_in_version_tree(plate_path, image_subdir="jpeg")
            if jpeg_file is not None:
                # jpeg_file path is: plate_path / version / jpeg / resolution / file.jpeg
                version_name = jpeg_file.parent.parent.parent.name
                logger.info(
                    f"Found undistorted JPEG thumbnail: {jpeg_file.name}"
                    f" (camera: {plate_name}, version: {version_name})"
                )
                return jpeg_file

        logger.debug(
            f"No undistorted JPEG thumbnails found for {show}/{sequence}/{shot}"
        )
        return None

    @staticmethod
    def _find_jpeg_in_nuke_output(
        mm_default_base: Path,
        user_path: Path,
    ) -> Path | None:
        """Search both Nuke output structures (undistort/scene) for a JPEG thumbnail.

        Args:
            mm_default_base: Path to user's mm/nuke/outputs/mm-default directory
            user_path: User workspace root (used only for log messages)

        Returns:
            Path to first JPEG found, or None

        """
        for output_type in ["undistort", "scene"]:
            nuke_outputs = mm_default_base / output_type
            if not nuke_outputs.exists():
                continue

            plate_dirs = FileDiscovery.discover_plate_directories(nuke_outputs)

            for plate_name, _priority in plate_dirs:
                plate_dir = find_path_case_insensitive(nuke_outputs, plate_name)
                if plate_dir is None:
                    continue

                undistorted_path = plate_dir / "undistorted_plate"
                if not undistorted_path.exists():
                    continue

                latest_version = VersionUtils.get_latest_version(undistorted_path)
                if not latest_version:
                    continue

                version_path = undistorted_path / latest_version
                jpeg_subdir = version_path / "jpeg"
                potential_jpeg_path = jpeg_subdir if jpeg_subdir.exists() else version_path
                if not potential_jpeg_path.exists():
                    continue

                try:
                    for resolution_dir in potential_jpeg_path.iterdir():
                        if not resolution_dir.is_dir():
                            continue

                        jpeg_dir = (
                            resolution_dir / "jpeg"
                            if (resolution_dir / "jpeg").exists()
                            else resolution_dir
                        )

                        jpeg_file = FileUtils.get_first_image_file(jpeg_dir)
                        if jpeg_file and jpeg_file.suffix.lower() in [".jpg", ".jpeg"]:
                            logger.info(
                                f"Found user workspace JPEG: {jpeg_file.name}"
                                f" (user: {user_path.name}, output_type: {output_type},"
                                f" plate: {plate_name}, version: {latest_version})"
                            )
                            return jpeg_file
                except (OSError, PermissionError):
                    continue

        return None

    @staticmethod
    def find_user_workspace_jpeg_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find JPEG thumbnail from user workspace Nuke outputs.

        Searches for JPEGs in both common Nuke output structures:
        - {workspace}/user/{any_user}/mm/nuke/outputs/mm-default/undistort/{plate}/undistorted_plate/{version}/{resolution}/jpeg/
        - {workspace}/user/{any_user}/mm/nuke/outputs/mm-default/scene/{plate}/undistorted_plate/{version}/{resolution}/jpeg/

        Uses case-insensitive plate matching (pl01, PL01, Pl01 all match "PL" type).
        Discovers JPEGs generated by Nuke in artist workspaces, which are often
        more recent and higher quality than published thumbnails.

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first JPEG found in any user workspace, or None

        """
        user_dir = ThumbnailFinders._shot_path(shows_root, show, sequence, shot, "user")
        if not PathValidators.validate_path_exists(user_dir, "User directory"):
            return None

        try:
            for user_path in user_dir.iterdir():
                if not user_path.is_dir():
                    continue

                mm_default_base = user_path / "mm" / "nuke" / "outputs" / "mm-default"
                if not mm_default_base.exists():
                    continue

                result = ThumbnailFinders._find_jpeg_in_nuke_output(mm_default_base, user_path)
                if result is not None:
                    return result

        except (OSError, PermissionError) as e:
            logger.debug(f"Error scanning user workspaces in {user_dir}: {e}")

        logger.debug(f"No user workspace JPEGs found for {show}/{sequence}/{shot}")
        return None

    @staticmethod
    def _find_editorial_cutref_thumbnail(editorial_base: Path) -> Path | None:
        """Search an editorial cutref directory for a JPEG thumbnail.

        Args:
            editorial_base: Path to publish/editorial/cutref

        Returns:
            Path to first JPEG from the latest version, or None

        """
        jpeg_file = _find_first_jpeg_in_version_tree(editorial_base, image_subdir="jpg")
        if jpeg_file is not None:
            # jpeg_file path is: editorial_base / version / jpg / resolution / file.jpg
            version_name = jpeg_file.parent.parent.parent.name
            resolution_name = jpeg_file.parent.name
            logger.info(
                f"Found editorial cutref thumbnail: {jpeg_file.name}"
                f" (version: {version_name}, resolution: {resolution_name})"
            )
        return jpeg_file

    @staticmethod
    def find_shot_thumbnail(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Find thumbnail for a shot from editorial cutref directory.

        This is the single source of truth for shot thumbnail discovery,
        ensuring consistent thumbnails across "My Shots" and "Other 3DE scenes".

        Searches for JPEG thumbnails in:
        {workspace}/publish/editorial/cutref/{latest_version}/jpg/{resolution}/

        Falls back to turnover plate thumbnail, then any publish EXR.

        Args:
            shows_root: Root path for shows
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to first JPEG file from latest editorial cutref version, or None if not found

        """
        editorial_base = ThumbnailFinders._shot_path(
            shows_root, show, sequence, shot, "publish", "editorial", "cutref",
        )

        if PathValidators.validate_path_exists(editorial_base, "Editorial cutref directory"):
            result = ThumbnailFinders._find_editorial_cutref_thumbnail(editorial_base)
            if result is not None:
                return result

        turnover_thumbnail = ThumbnailFinders.find_turnover_plate_thumbnail(
            shows_root, show, sequence, shot
        )
        if turnover_thumbnail:
            logger.info(f"Found turnover plate thumbnail: {turnover_thumbnail}")
            return turnover_thumbnail

        publish_thumbnail = ThumbnailFinders.find_any_publish_thumbnail(
            shows_root, show, sequence, shot
        )
        if publish_thumbnail:
            logger.info(f"Found publish thumbnail: {publish_thumbnail}")
            return publish_thumbnail

        logger.debug(f"No thumbnails found for {show}/{sequence}/{shot}")
        return None

