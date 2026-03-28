"""Frame number extraction and manipulation utilities.

This module consolidates frame-number parsing patterns found across the
discovery and scrub packages into a single authoritative location.
"""

from __future__ import annotations

import re


# Matches frame-numbered filenames with dot or underscore separator.
# Captures the frame number from patterns like:
#   name.1001.exr   name_1001.exr
#   name.1001.ma    name.1001.mb
# Group 1: frame number digits (4 or more)
# Group 2: file extension (exr, ma, or mb)
FRAME_PATTERN: re.Pattern[str] = re.compile(
    r"[._](\d{4,})\.(exr|ma|mb)$",
    re.IGNORECASE,
)


def extract_frame_number(filename: str, ext: str = "exr") -> int | None:
    """Extract the frame number from a filename string.

    Searches for a frame number preceding the given extension, using either a
    dot or underscore as the separator.  Returns the integer frame number, or
    ``None`` if the pattern is not found.

    Args:
        filename: Bare filename (or full path string) to inspect.
        ext: File extension to anchor the search (default ``"exr"``).

    Returns:
        Integer frame number, or ``None`` if no match.

    Examples:
        >>> extract_frame_number("shot.1001.exr")
        1001
        >>> extract_frame_number("shot_1001.exr")
        1001
        >>> extract_frame_number("shot.1001.ma", ext="ma")
        1001
        >>> extract_frame_number("shot.exr") is None
        True

    """
    pattern = re.compile(rf"[._](\d{{4,}})\.{re.escape(ext)}$", re.IGNORECASE)
    match = pattern.search(filename)
    if match:
        return int(match.group(1))
    return None


def substitute_frame(filename: str, frame: int) -> str | None:
    """Replace the frame number in a filename with a new frame number.

    Zero-padding width is preserved from the original frame token.  Returns
    ``None`` if no frame pattern is found in the filename.

    Args:
        filename: Bare filename (or full path string) containing a frame number.
        frame: Replacement frame number.

    Returns:
        Updated filename string with the new frame number, or ``None`` if the
        pattern is not found.

    Examples:
        >>> substitute_frame("shot.1001.exr", 1050)
        'shot.1050.exr'
        >>> substitute_frame("shot_1001.exr", 1050)
        'shot_1050.exr'
        >>> substitute_frame("shot.exr", 1050) is None
        True

    """
    match = FRAME_PATTERN.search(filename)
    if not match:
        return None
    frame_str = str(frame).zfill(len(match.group(1)))
    # Preserve the separator character (dot or underscore) at match.start()
    return filename[: match.start() + 1] + frame_str + "." + match.group(2)


def to_hash_pattern(filename: str, ext: str) -> str:
    """Convert a frame-numbered filename to a hash-pattern filename.

    Each digit in the frame number token is replaced with ``#``, producing the
    conventional Nuke/pipeline hash pattern (e.g. ``####`` for a four-digit
    frame number).  If no frame pattern is found the filename is returned
    unchanged.

    Args:
        filename: Bare filename (or full path string) containing a frame number.
        ext: File extension to anchor the search.

    Returns:
        Filename string with the frame number replaced by ``#`` characters.

    Examples:
        >>> to_hash_pattern("shot.1001.exr", "exr")
        'shot.####.exr'
        >>> to_hash_pattern("shot_10001.exr", "exr")
        'shot_#####.exr'
        >>> to_hash_pattern("shot.exr", "exr")
        'shot.exr'

    """
    return re.sub(
        rf"([._])(\d{{4,}})\.{re.escape(ext)}$",
        lambda m: m.group(1) + "#" * len(m.group(2)) + f".{ext}",
        filename,
        flags=re.IGNORECASE,
    )
