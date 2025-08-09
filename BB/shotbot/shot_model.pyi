"""Type stubs for shot_model module."""

import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from cache_manager import CacheManager

class RefreshResult(NamedTuple):
    """Result of shot refresh operation."""

    success: bool
    has_changes: bool

class Shot:
    """Represents a single shot."""

    show: str
    sequence: str
    shot: str
    workspace_path: str

    def __init__(
        self, show: str, sequence: str, shot: str, workspace_path: str
    ) -> None: ...
    @property
    def full_name(self) -> str: ...
    @property
    def thumbnail_dir(self) -> Path: ...
    def get_thumbnail_path(self) -> Optional[Path]: ...
    def to_dict(self) -> Dict[str, str]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> Shot: ...

class ShotModel:
    """Manages shot data and parsing."""

    shots: List[Shot]
    cache_manager: CacheManager
    _parse_pattern: re.Pattern[str]

    def __init__(
        self, cache_manager: Optional[CacheManager] = ..., load_cache: bool = ...
    ) -> None: ...
    def _load_from_cache(self) -> bool: ...
    def refresh_shots(self) -> RefreshResult: ...
    def _parse_ws_output(self, output: str) -> List[Shot]: ...
    def get_shot_by_index(self, index: int) -> Optional[Shot]: ...
    def find_shot_by_name(self, full_name: str) -> Optional[Shot]: ...
