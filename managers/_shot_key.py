from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from type_definitions import Shot


def shot_key(shot: Shot) -> tuple[str, str, str]:
    """Return (show, sequence, shot) composite key."""
    return (shot.show, shot.sequence, shot.shot)


def key_from_workspace_path(workspace_path: str) -> tuple[str, str, str] | None:
    """Extract (show, sequence, shot) key from workspace path.

    Path format: /shows/{show}/shots/{seq}/{seq}_{shot}

    Args:
        workspace_path: Full workspace path

    Returns:
        Tuple key or None if path can't be parsed

    """
    path = Path(workspace_path)
    parts = path.parts

    # Find 'shots' in path and extract show/seq/shot
    try:
        shots_idx = parts.index("shots")
        show = parts[shots_idx - 1]  # Show is before 'shots'
        seq = parts[shots_idx + 1]   # Sequence is after 'shots'
        seq_shot = parts[shots_idx + 2]  # seq_shot folder
        # Extract shot from seq_shot (format: seq_shot)
        shot = seq_shot.split("_", 1)[1] if "_" in seq_shot else seq_shot
        return (show, seq, shot)
    except (ValueError, IndexError):
        return None
