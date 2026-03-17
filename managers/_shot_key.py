from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from type_definitions import Shot


def shot_key(shot: Shot) -> tuple[str, str, str]:
    """Return (show, sequence, shot) composite key."""
    return (shot.show, shot.sequence, shot.shot)
