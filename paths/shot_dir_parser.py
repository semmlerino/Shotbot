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


def build_workspace_path(
    shows_root: str | Path, show: str, sequence: str, shot: str, *suffix: str
) -> Path:
    """Build standard VFX workspace path.

    Constructs: {shows_root}/{show}/shots/{sequence}/{sequence}_{shot}[/suffix...]

    Args:
        shows_root: Root shows directory.
        show: Show name (e.g. "PROJ").
        sequence: Sequence name (e.g. "sq010").
        shot: Shot identifier (e.g. "sh020").
        *suffix: Optional path components to append.

    Returns:
        Constructed workspace path as Path object.
    """
    shot_dir = f"{sequence}_{shot}"
    return Path(shows_root, show, "shots", sequence, shot_dir, *suffix)


def resolve_shows_root(shows_root: str | Path | None) -> Path:
    """Normalize shows_root to Path, defaulting to Config.Paths.SHOWS_ROOT.

    Args:
        shows_root: Root shows directory as string, Path, or None.

    Returns:
        Resolved path as Path object.
    """
    if shows_root is None:
        from config import Config

        return Path(Config.Paths.SHOWS_ROOT)
    return Path(shows_root)
