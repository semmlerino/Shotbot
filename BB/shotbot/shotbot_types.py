"""Type definitions for ShotBot application.

This module defines TypedDict classes and other type definitions
to improve type safety across the application.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union

# Common type aliases
PathType = Union[str, Path]


class ShotData(TypedDict):
    """Type definition for shot data dictionary."""

    show: str
    sequence: str
    shot: str
    workspace_path: str


class ThreeDESceneData(TypedDict):
    """Type definition for 3DE scene data dictionary."""

    show: str
    sequence: str
    shot: str
    workspace_path: str
    user: str
    plate: str
    scene_path: str


class CacheEntry(TypedDict):
    """Type definition for cache entry data."""

    value: Any
    timestamp: float
    access_count: int
    size_bytes: Optional[int]


class LauncherData(TypedDict):
    """Type definition for launcher configuration data."""

    id: str
    name: str
    command: str
    description: Optional[str]
    icon: Optional[str]
    parameters: List[Dict[str, Any]]


class ProcessInfo(TypedDict):
    """Type definition for process information."""

    pid: int
    command: List[str]
    started_at: float
    status: str
    output: List[str]


# RefreshResult is defined as NamedTuple in shot_model.py
# Removed duplicate TypedDict definition to avoid import conflicts
