from __future__ import annotations

from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
)


if TYPE_CHECKING:
    from type_definitions import Shot, ShotDict, ThreeDEScene, ThreeDESceneDict


# Incremental merging support
class ShotMergeResult(NamedTuple):
    """Result of incremental shot merge operation."""

    updated_shots: list[ShotDict]  # All shots (kept + new)
    new_shots: list[ShotDict]  # Just new additions
    removed_shots: list[ShotDict]  # No longer in fresh data
    has_changes: bool  # Any changes detected


class SceneMergeResult(NamedTuple):
    """Result of incremental scene merge operation."""

    updated_scenes: list[ThreeDESceneDict]  # All scenes (kept + new)
    new_scenes: list[ThreeDESceneDict]  # Just new additions
    stale_scenes: list[
        ThreeDESceneDict
    ]  # In cache but not in current scan (retained within retention window)
    has_changes: bool  # Any changes detected
    pruned_count: int = 0  # Scenes removed due to age-based pruning


class LatestFileCacheResult(NamedTuple):
    """Tri-state result for latest file cache lookup.

    Attributes:
        status: "hit" (file found), "not_found" (confirmed no file within TTL),
                "miss" (no entry, expired, or file deleted)
        path: The cached file path (only set for "hit" status)
    """

    status: Literal["hit", "not_found", "miss"]
    path: Path | None = None


def get_shot_key(shot: ShotDict) -> tuple[str, str, str]:
    """Get composite unique key for shot.

    Uses (show, sequence, shot) tuple instead of full_name to ensure
    global uniqueness across all shows.

    Args:
        shot: Shot dictionary with show, sequence, shot fields

    Returns:
        Tuple of (show, sequence, shot) for use as dict key

    """
    return (shot["show"], shot["sequence"], shot["shot"])


def shot_to_dict(shot: ShotDict | Shot) -> ShotDict:
    """Convert Shot object or ShotDict to ShotDict.

    Args:
        shot: Shot object with to_dict() method or ShotDict

    Returns:
        ShotDict with all required fields

    """
    if isinstance(shot, dict):
        return shot
    # shot is a Shot instance — call to_dict() directly
    return shot.to_dict()


def get_scene_key(scene: ThreeDESceneDict) -> tuple[str, str, str]:
    """Get composite unique key for scene.

    Uses (show, sequence, shot) tuple for shot-level deduplication.
    This aligns with the current deduplication strategy where only one
    scene per shot is kept (selected by mtime and plate priority).

    Args:
        scene: Scene dictionary with show, sequence, shot fields

    Returns:
        Tuple of (show, sequence, shot) for use as dict key

    """
    return (scene["show"], scene["sequence"], scene["shot"])


def scene_to_dict(scene: ThreeDESceneDict | ThreeDEScene) -> ThreeDESceneDict:
    """Convert ThreeDEScene object or dict to ThreeDESceneDict.

    Args:
        scene: ThreeDEScene object with to_dict() method or ThreeDESceneDict

    Returns:
        ThreeDESceneDict with all required fields

    """
    if isinstance(scene, dict):
        return scene
    # scene is a ThreeDEScene instance — call to_dict() directly
    return scene.to_dict()
