"""Frame range extraction utility for shot plates.

This module provides functionality to extract frame range from turnover plates,
combining plate discovery with frame range detection.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path


logger = logging.getLogger(__name__)


def detect_frame_range(directory: Path, extension: str = "exr") -> tuple[int, int]:
    """Scan directory for frame-numbered files, return (min_frame, max_frame).

    Searches for files with pattern like filename.1001.ext and extracts frame numbers.
    Returns (1001, 1100) as default if no frames found.

    Args:
        directory: Directory to scan for frame-numbered files.
        extension: File extension to match (default "exr"). Do not include the dot.

    Returns:
        Tuple of (first_frame, last_frame). Defaults to (1001, 1100) if no frames found.

    Example:
        >>> from pathlib import Path
        >>> detect_frame_range(Path("/shots/sh0010/plates"))
        (1001, 1150)

    """
    # Pattern to extract frame numbers from filenames
    # Matches: filename.1001.exr, plate.0001.exr, etc.
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
        logger.debug(f"Error reading directory {directory}", exc_info=True)

    if frames:
        return min(frames), max(frames)

    # Default VFX frame range
    return 1001, 1100


def extract_frame_range(workspace_path: str) -> tuple[int, int] | None:
    """Extract frame range from turnover plate.

    Finds the main plate (FG01) in publish/turnover and extracts the frame range
    by scanning the actual files in the directory.

    Args:
        workspace_path: Shot workspace path (e.g., /shows/myshow/shots/sq010/sh0010)

    Returns:
        Tuple of (first_frame, last_frame) or None if no plate found.

    Example:
        >>> extract_frame_range("/shows/myshow/shots/sq010/sh0010")
        (1001, 1150)

    """
    from discovery.plate_finders import find_main_plate

    # Get plate path pattern (returns path with @@@@ for frame numbers)
    plate_pattern = find_main_plate(workspace_path)
    if plate_pattern is None:
        logger.info(f"No main plate found for {workspace_path}")
        return None
    logger.info(f"Found plate pattern: {plate_pattern}")

    # Convert @@@@ pattern to regex for file matching
    # find_main_plate returns: /path/to/shot.@@@@.exr
    # We need to match: /path/to/shot.1001.exr, shot.1002.exr, etc.
    plate_dir = Path(plate_pattern).parent
    if not plate_dir.exists():
        logger.debug(f"Plate directory does not exist: {plate_dir}")
        return None

    # Build regex pattern from the @@@@ placeholder
    base_name = Path(plate_pattern).name
    # Replace @@@@ with a capturing group for digits
    # Count the @'s to determine digit padding
    at_match = re.search(r"@+", base_name)
    if at_match:
        num_digits = len(at_match.group())
        # Replace @@@@ with regex pattern that matches that many digits
        pattern_str = base_name.replace(at_match.group(), rf"(\d{{{num_digits}}})")
    else:
        # No @'s found - might be a single frame or different pattern
        logger.debug(f"No frame pattern found in plate path: {plate_pattern}")
        return None

    try:
        frame_regex = re.compile(pattern_str)
        frame_numbers: list[int] = []

        for file in plate_dir.iterdir():
            match = frame_regex.match(file.name)
            if match:
                frame_numbers.append(int(match.group(1)))

        if frame_numbers:
            result = (min(frame_numbers), max(frame_numbers))
            logger.info(f"Frame range for {workspace_path}: {result[0]}-{result[1]}")
            return result

        logger.info(f"No matching frame files found in {plate_dir}")
        return None

    except (OSError, re.error):
        logger.warning(f"Error extracting frame range from {plate_dir}", exc_info=True)
        return None
