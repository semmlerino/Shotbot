"""Frame range extraction utility for shot plates.

This module provides functionality to extract frame range from turnover plates,
combining plate discovery with frame range detection.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path


logger = logging.getLogger(__name__)


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
    from discovery.publish_plate_finder import find_main_plate

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
        pattern_str = base_name.replace(
            at_match.group(), rf"(\d{{{num_digits}}})"
        )
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
            logger.info(
                f"Frame range for {workspace_path}: {result[0]}-{result[1]}"
            )
            return result

        logger.info(f"No matching frame files found in {plate_dir}")
        return None

    except (OSError, re.error):
        logger.warning(f"Error extracting frame range from {plate_dir}", exc_info=True)
        return None
