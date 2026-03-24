"""Canonical shot directory name parser.

All code that needs to extract a shot identifier from a directory name
like ``{sequence}_{shot}`` should call :func:`parse_shot_from_dir` instead
of reimplementing the logic.
"""

from __future__ import annotations

from pathlib import Path


def parse_shot_from_dir(sequence: str, shot_dir: str) -> str:
    """Extract the shot identifier from a shot directory name.

    The directory convention is ``{sequence}_{shot}``.  The algorithm:
    1. If *shot_dir* starts with ``{sequence}_``, strip that prefix.
    2. Otherwise fall back to ``rsplit("_", 1)`` (last underscore).
    3. If there is no underscore at all, return *shot_dir* unchanged.

    Args:
        sequence: Sequence name (e.g. ``"SQ010"``).
        shot_dir: Shot directory name (e.g. ``"SQ010_0010"``).

    Returns:
        Shot identifier string (e.g. ``"0010"``).
    """
    prefix = f"{sequence}_"
    if shot_dir.startswith(prefix):
        return shot_dir[len(prefix) :]
    parts = shot_dir.rsplit("_", 1)
    return parts[1] if len(parts) == 2 else shot_dir


def parse_workspace_path(workspace_path: str) -> tuple[str, str, str] | None:
    """Extract (show, sequence, shot) from a workspace path.

    Expected path format: ``…/shows/{show}/shots/{sequence}/{sequence}_{shot}``.

    Args:
        workspace_path: Full workspace path.

    Returns:
        ``(show, sequence, shot)`` tuple, or *None* if the path cannot be parsed.
    """
    path = Path(workspace_path)
    parts = path.parts

    try:
        shots_idx = parts.index("shots")
        show = parts[shots_idx - 1]
        sequence = parts[shots_idx + 1]
        shot_dir = parts[shots_idx + 2]
        shot = parse_shot_from_dir(sequence, shot_dir)
        return (show, sequence, shot)
    except (ValueError, IndexError):
        return None
