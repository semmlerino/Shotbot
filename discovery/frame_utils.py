"""Frame number extraction and manipulation utilities.

This module consolidates frame-number parsing patterns found across the
discovery and scrub packages into a single authoritative location.
"""

from __future__ import annotations

import re

from fileseq import (
    FileSeqException,  # pyright: ignore[reportPrivateImportUsage]
    FileSequence,  # pyright: ignore[reportPrivateImportUsage]
)


# Regex fallback for filename patterns fileseq doesn't handle (e.g. underscore separator).
# Matches: name.1001.exr  name_1001.exr
# Group 1: frame digits (4+), Group 2: extension
_FRAME_PATTERN: re.Pattern[str] = re.compile(
    r"[._](\d{4,})\.(exr|ma|mb)$",
    re.IGNORECASE,
)

# Public alias — kept for callers that import FRAME_PATTERN directly (plate_finders.py).
FRAME_PATTERN = _FRAME_PATTERN


def extract_frame_number(filename: str, ext: str = "exr") -> int | None:
    """Extract the frame number from a filename string.

    Args:
        filename: Bare filename (or full path string) to inspect.
        ext: File extension to anchor the search (default ``"exr"``).

    Returns:
        Integer frame number, or ``None`` if no match.

    """
    try:
        seq = FileSequence(filename)
        frame_set = seq.frameSet()
        if frame_set is not None and seq.extension().lstrip(".").lower() == ext.lower():
            return int(frame_set.start())
    except FileSeqException:
        pass
    # Fallback: underscore separator or unrecognised pattern
    pattern = re.compile(rf"[._](\d{{4,}})\.{re.escape(ext)}$", re.IGNORECASE)
    match = pattern.search(filename)
    return int(match.group(1)) if match else None


def substitute_frame(filename: str, frame: int) -> str | None:
    """Replace the frame number in a filename with a new frame number.

    Zero-padding width is preserved.  Returns ``None`` if no frame pattern found.

    Args:
        filename: Bare filename containing a frame number.
        frame: Replacement frame number.

    Returns:
        Updated filename with the new frame number, or ``None``.

    """
    try:
        seq = FileSequence(filename)
        if seq.frameSet() is not None:
            return seq.frame(frame)
    except FileSeqException:
        pass
    # Fallback: underscore separator
    match = _FRAME_PATTERN.search(filename)
    if not match:
        return None
    frame_str = str(frame).zfill(len(match.group(1)))
    return filename[: match.start() + 1] + frame_str + "." + match.group(2)


def to_hash_pattern(filename: str, ext: str) -> str:
    """Convert a frame-numbered filename to a hash-pattern filename (``####``).

    Each digit in the frame number token is replaced with ``#``.  If no frame
    pattern is found the filename is returned unchanged.

    Args:
        filename: Bare filename containing a frame number.
        ext: File extension to anchor the search.

    Returns:
        Filename with the frame number replaced by ``#`` characters.

    """
    try:
        seq = FileSequence(filename)
        frame_set = seq.frameSet()
        if frame_set is not None:
            num_hashes = len(str(int(frame_set.start())))
            return seq.basename() + "#" * num_hashes + seq.extension()
    except FileSeqException:
        pass
    # Fallback: underscore separator
    return re.sub(
        rf"([._])(\d{{4,}})\.{re.escape(ext)}$",
        lambda m: m.group(1) + "#" * len(m.group(2)) + f".{ext}",
        filename,
        flags=re.IGNORECASE,
    )
