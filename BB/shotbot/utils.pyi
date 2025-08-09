"""Type stubs for utils module."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Cache globals
_path_cache: Dict[str, Tuple[bool, float]]
_PATH_CACHE_TTL: float

def clear_all_caches() -> None: ...
def get_cache_stats() -> Dict[str, Any]: ...

class PathUtils:
    """Utilities for path construction and validation."""

    @staticmethod
    def build_path(base_path: Union[str, Path], *segments: str) -> Path: ...
    @staticmethod
    def build_thumbnail_path(
        shows_root: str, show: str, sequence: str, shot: str
    ) -> Path: ...
    @staticmethod
    def build_raw_plate_path(workspace_path: str) -> Path: ...
    @staticmethod
    def build_undistortion_path(workspace_path: str, username: str) -> Path: ...
    @staticmethod
    def build_threede_scene_path(workspace_path: str, username: str) -> Path: ...
    @staticmethod
    def validate_path_exists(
        path: Union[str, Path], description: str = ...
    ) -> bool: ...
    @staticmethod
    def _cleanup_path_cache() -> None: ...
    @staticmethod
    def batch_validate_paths(paths: List[Union[str, Path]]) -> Dict[str, bool]: ...
    @staticmethod
    def safe_mkdir(path: Union[str, Path], description: str = ...) -> bool: ...
    @staticmethod
    def discover_plate_directories(
        base_path: Union[str, Path],
    ) -> List[Tuple[str, int]]: ...

class VersionUtils:
    """Utilities for handling versioned directories and files."""

    VERSION_PATTERN: re.Pattern[str]
    _version_cache: Dict[str, Tuple[List[Tuple[int, str]], float]]

    @staticmethod
    def find_version_directories(
        base_path: Union[str, Path],
    ) -> List[Tuple[int, str]]: ...
    @staticmethod
    def _cleanup_version_cache() -> None: ...
    @staticmethod
    def get_latest_version(base_path: Union[str, Path]) -> Optional[str]: ...
    @staticmethod
    @lru_cache(maxsize=256)
    def extract_version_from_path(path: Union[str, Path]) -> Optional[str]: ...

class FileUtils:
    """Utilities for file operations and validation."""

    @staticmethod
    def find_files_by_extension(
        directory: Union[str, Path],
        extensions: Union[str, List[str]],
        limit: Optional[int] = ...,
    ) -> List[Path]: ...
    @staticmethod
    def get_first_image_file(directory: Union[str, Path]) -> Optional[Path]: ...
    @staticmethod
    def validate_file_size(
        file_path: Union[str, Path], max_size_mb: Optional[int] = ...
    ) -> bool: ...

class ImageUtils:
    """Utilities for image validation and processing."""

    @staticmethod
    def validate_image_dimensions(
        width: int,
        height: int,
        max_dimension: Optional[int] = ...,
        max_memory_mb: Optional[int] = ...,
    ) -> bool: ...
    @staticmethod
    def get_safe_dimensions_for_thumbnail(
        max_size: Optional[int] = ...,
    ) -> Tuple[int, int]: ...

class ValidationUtils:
    """Common validation utilities."""

    @staticmethod
    def validate_not_empty(
        *values: Union[str, None], names: Optional[List[str]] = ...
    ) -> bool: ...
    @staticmethod
    def validate_shot_components(show: str, sequence: str, shot: str) -> bool: ...
    @staticmethod
    def get_current_username() -> str: ...
    @staticmethod
    def get_excluded_users(additional_users: Optional[Set[str]] = ...) -> Set[str]: ...
