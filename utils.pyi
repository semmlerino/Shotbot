"""Type stubs for utils module."""

# Standard library imports
import re
from functools import lru_cache
from pathlib import Path

# Third-party imports
from PySide6.QtCore import SignalInstance

def safe_disconnect(*signals: SignalInstance) -> None: ...
def get_cache_stats() -> dict[str, int | str | float]: ...
def get_current_username() -> str: ...
def get_excluded_users(additional_users: set[str] | None = ...) -> set[str]: ...
def normalize_plate_id(plate_id: str | None) -> str | None: ...
def find_path_case_insensitive(base_path: Path, plate_id: str) -> Path | None: ...

class VersionUtils:
    """Utilities for handling versioned directories and files."""

    VERSION_PATTERN: re.Pattern[str]
    _version_cache: dict[str, tuple[list[tuple[int, str]], float]]

    @staticmethod
    def find_version_directories(
        base_path: str | Path,
    ) -> list[tuple[int, str]]: ...
    @staticmethod
    def _cleanup_version_cache() -> None: ...
    @staticmethod
    def get_latest_version(base_path: str | Path) -> str | None: ...
    @staticmethod
    @lru_cache(maxsize=256)
    def extract_version_from_path(path: str | Path) -> str | None: ...
    @staticmethod
    def get_next_version_number(directory: str | Path, pattern: str) -> int: ...

class FileUtils:
    """Utilities for file operations and validation."""

    @staticmethod
    def find_files_by_extension(
        directory: str | Path,
        extensions: str | list[str],
        limit: int | None = ...,
    ) -> list[Path]: ...
    @staticmethod
    def get_first_image_file(directory: str | Path) -> Path | None: ...
    @staticmethod
    def validate_file_size(
        file_path: str | Path,
        max_size_mb: int | None = ...,
    ) -> bool: ...

class ImageUtils:
    """Utilities for image validation and processing."""

    @staticmethod
    def validate_image_dimensions(
        width: int,
        height: int,
        max_dimension: int | None = ...,
        max_memory_mb: int | None = ...,
    ) -> bool: ...
    @staticmethod
    def get_safe_dimensions_for_thumbnail(
        max_size: int | None = ...,
    ) -> tuple[int, int]: ...
    @staticmethod
    def is_image_too_large_for_thumbnail(
        size: object,  # QSize or compatible object with width()/height()
        max_dimension: int,
    ) -> bool: ...
    @staticmethod
    def extract_frame_from_mov(
        mov_path: Path,
        output_path: Path | None = ...,
    ) -> Path | None: ...

class ValidationUtils:
    """Common validation utilities."""

    @staticmethod
    def validate_not_empty(
        *values: str | None,
        names: list[str] | None = ...,
    ) -> bool: ...
    @staticmethod
    def validate_shot_components(show: str, sequence: str, shot: str) -> bool: ...
    @staticmethod
    def get_current_username() -> str: ...
    @staticmethod
    def get_excluded_users(additional_users: set[str] | None = ...) -> set[str]: ...
