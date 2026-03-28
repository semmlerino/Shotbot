"""Frame range extraction utility for shot plates.

This module provides functionality to extract frame range from turnover plates,
combining plate discovery with frame range detection.
"""

from __future__ import annotations

import re
from pathlib import Path

import fileseq

from logging_mixin import get_module_logger


logger = get_module_logger(__name__)


def detect_frame_range(directory: Path, extension: str = "exr") -> tuple[int, int]:
    """Scan directory for frame-numbered files, return (min_frame, max_frame).

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
    _min_digits = re.compile(rf"\.(\d{{4,}})\.{re.escape(extension)}$", re.IGNORECASE)
    try:
        names = [
            p.name for p in directory.iterdir()
            if p.is_file() and _min_digits.search(p.name)
        ]
    except OSError:
        logger.debug(f"Error reading directory {directory}", exc_info=True)
        return 1001, 1100

    sequences = fileseq.findSequencesInList(names)
    frames: list[int] = []
    for seq in sequences:
        frame_set = seq.frameSet()
        if frame_set is not None:
            frames.extend(int(f) for f in frame_set)

    if frames:
        return min(frames), max(frames)

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

    try:
        sequences = fileseq.findSequencesOnDisk(plate_pattern, strictPadding=True)
        for seq in sequences:
            frame_set = seq.frameSet()
            if frame_set is not None:
                result = (int(frame_set.start()), int(frame_set.end()))
                logger.info(f"Frame range for {workspace_path}: {result[0]}-{result[1]}")
                return result

        logger.info(f"No matching frame files found for {plate_pattern}")
        return None

    except OSError:
        logger.warning(
            f"Error extracting frame range from {plate_pattern}", exc_info=True
        )
        return None
