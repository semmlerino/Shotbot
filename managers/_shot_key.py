from __future__ import annotations

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
    from paths.shot_dir_parser import parse_workspace_path

    return parse_workspace_path(workspace_path)
