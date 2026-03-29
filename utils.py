"""Common utilities for ShotBot application."""

from __future__ import annotations

# Standard library imports
import getpass
import warnings
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtCore import SignalInstance

# Local application imports
from config import Config
from logging_mixin import get_module_logger


# Performance monitoring removed - was using archived module

# Set up logger for this module
logger = get_module_logger(__name__)

# Import path validation internals needed by this module (not re-exported)
from paths.validators import PathValidators
from paths.validators import get_cache_stats as get_path_cache_stats
from version_utils import VersionUtils  # used in get_cache_stats(); not re-exported


__all__ = [
    "FileUtils",
    "ValidationUtils",
    "safe_disconnect",
]


def get_cache_stats() -> dict[str, object]:
    """Get statistics about current cache usage."""
    stats: dict[str, object] = {
        **get_path_cache_stats(),  # Get path cache stats from path_validators
        "version_cache_size": VersionUtils.get_version_cache_size(),
        "extract_version_cache_info": VersionUtils.extract_version_from_path.cache_info(),
    }
    return stats


def normalize_plate_id(plate_id: str | None) -> str | None:
    """Normalize plate ID to canonical uppercase form.

    VFX convention uses uppercase (PL01, FG01, BG02), but filesystems
    may contain lowercase directories (pl01, fg01). This normalizes
    for consistent logging and comparison while preserving filesystem
    case for path operations.

    Args:
        plate_id: Plate identifier (e.g., "PL01", "pl01", "FG01")

    Returns:
        Normalized uppercase plate ID, or None if input is None/empty

    Examples:
        >>> normalize_plate_id("pl01")
        "PL01"
        >>> normalize_plate_id("  pl01  ")
        "PL01"
        >>> normalize_plate_id("")
        None
        >>> normalize_plate_id(None)
        None

    """
    if plate_id is None:
        return None

    # Strip whitespace and validate non-empty
    plate_id = plate_id.strip()
    if not plate_id:
        return None

    return plate_id.upper()


def find_path_case_insensitive(base_path: Path, plate_id: str) -> Path | None:
    """Find plate directory with case-insensitive fallback.

    Linux filesystems are case-sensitive, but VFX pipelines may have
    inconsistent casing (PL01/ vs pl01/). Try normalized uppercase first,
    then fall back to lowercase if not found.

    Args:
        base_path: Directory containing plate subdirectories (must exist)
        plate_id: Plate identifier (any case)

    Returns:
        Path to existing plate directory, or None if not found

    """
    # Validate base path exists
    if not base_path.exists():
        logger.warning(f"Base path does not exist: {base_path}")
        return None

    if not base_path.is_dir():
        logger.warning(f"Base path is not a directory: {base_path}")
        return None

    # Try normalized uppercase (VFX standard)
    normalized = normalize_plate_id(plate_id)
    if normalized:
        path = base_path / normalized
        if path.exists():
            return path

    # Fallback: try lowercase (legacy/non-standard)
    lowercase_path = base_path / plate_id.lower()
    if lowercase_path.exists():
        return lowercase_path

    # Fallback: try original case
    original_path = base_path / plate_id
    if original_path.exists():
        return original_path

    return None


def safe_disconnect(*signals: SignalInstance) -> None:
    """Safely disconnect all receivers from the given signals.

    Calls disconnect() on each signal, suppressing errors that occur when a
    signal has no connections or the underlying Qt object has already been
    deleted.

    Args:
        *signals: One or more Qt signal instances to disconnect.

    """
    for signal in signals:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                _ = signal.disconnect()
        except (RuntimeError, TypeError, AttributeError):
            pass


class FileUtils:
    """Utilities for file operations and validation."""

    @staticmethod
    def find_files_by_extension(
        directory: str | Path,
        extensions: str | list[str],
        limit: int | None = None,
    ) -> list[Path]:
        """Find files with specific extensions in a directory.

        This method performs optimized file discovery with early termination
        when limits are reached and uses set-based lookups for extension
        matching to achieve O(1) performance per file check.

        Args:
            directory: Directory path to search. Accepts both string paths
                and pathlib.Path objects for flexibility.
            extensions: File extension(s) to match. Can be a single extension
                string like "jpg" or ".jpg", or a list of extensions like
                ["jpg", "jpeg", "png"]. Leading dots are optional and normalized.
            limit: Maximum number of matching files to return. If None,
                returns all matching files. Used for performance optimization
                in large directories.

        Returns:
            list[Path]: List of pathlib.Path objects for all matching files.
                Returns empty list if directory doesn't exist or no matches found.
                Results are ordered by directory iteration order (not sorted).

        Raises:
            No exceptions are raised. Permission errors and OS errors are
            caught and logged as warnings, returning partial results.

        Examples:
            Single extension search:
                >>> files = FileUtils.find_files_by_extension("/tmp", "txt")
                >>> assert all(f.suffix == ".txt" for f in files)

            Multiple extensions with limit:
                >>> images = FileUtils.find_files_by_extension(
                ...     Path("/images"), ["jpg", "jpeg", "png"], limit=10
                ... )
                >>> assert len(images) <= 10

            Type-safe directory handling:
                >>> from pathlib import Path
                >>> path_obj = Path("/some/directory")
                >>> string_path = "/some/directory"
                >>> # Both work identically due to str | Path type
                >>> files1 = FileUtils.find_files_by_extension(path_obj, "py")
                >>> files2 = FileUtils.find_files_by_extension(string_path, "py")

        Performance:
            - O(n) time complexity where n is number of files in directory
            - Early termination when limit is reached reduces actual runtime
            - Set-based extension lookup provides O(1) extension matching
            - Path validation uses TTL caching to avoid repeated stat calls

        """
        if not PathValidators.validate_path_exists(directory, "Search directory"):
            return []

        # Normalize extensions to set for O(1) lookup
        if isinstance(extensions, str):
            extensions = [extensions]

        normalized_extensions: set[str] = set()
        for ext in extensions:
            normalized_ext = ext if ext.startswith(".") else "." + ext
            normalized_extensions.add(normalized_ext.lower())

        dir_path = Path(directory) if isinstance(directory, str) else directory
        matching_files: list[Path] = []

        try:
            # Use iterdir() but with early termination optimization
            for file_path in dir_path.iterdir():
                # Check is_file() first as it's usually faster than suffix check
                if (
                    file_path.is_file()
                    and file_path.suffix.lower() in normalized_extensions
                ):
                    matching_files.append(file_path)
                    # Early termination if limit reached
                    if limit and len(matching_files) >= limit:
                        break
        except (OSError, PermissionError):
            logger.warning(f"Error scanning directory {dir_path}", exc_info=True)

        return matching_files

    @staticmethod
    def get_first_image_file(
        directory: str | Path,
        allow_fallback: bool = True,
    ) -> Path | None:
        """Get the first image file found in a directory.

        Args:
            directory: Directory to search
            allow_fallback: If True, will check heavy formats (EXR, TIFF) as fallback

        Returns:
            Path to first image file or None if none found

        """
        # First try lightweight preferred extensions
        for ext in Config.FileDiscovery.THUMBNAIL_EXTENSIONS:
            files = FileUtils.find_files_by_extension(directory, ext, limit=1)
            if files:
                return files[0]

        # If no lightweight formats found and fallback allowed, try heavy formats
        if allow_fallback and hasattr(Config, "THUMBNAIL_FALLBACK_EXTENSIONS"):
            for ext in Config.FileDiscovery.THUMBNAIL_FALLBACK_EXTENSIONS:
                files = FileUtils.find_files_by_extension(directory, ext, limit=1)
                if files:
                    file_path = files[0]
                    logger.debug(
                        f"Using fallback {ext} file as thumbnail: {file_path.name}",
                    )
                    # Return regardless of size — cache_manager handles resizing
                    return file_path

        return None


def get_current_username() -> str:
    """Get the current username from environment.

    Returns:
        Current username, falling back to Config.DEFAULT_USERNAME if not found

    """
    from config import is_mock_mode

    # In mock mode, always use the default username to match production data
    if is_mock_mode():
        logger.debug(
            f"Mock mode: using production username '{Config.DEFAULT_USERNAME}'"
        )
        return Config.DEFAULT_USERNAME

    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        logger.debug(
            f"getpass.getuser() failed, using default: {Config.DEFAULT_USERNAME}",
        )
        return Config.DEFAULT_USERNAME


def get_excluded_users(additional_users: set[str] | None = None) -> set[str]:
    """Get set of users to exclude from searches.

    Automatically excludes the current user and any additional specified users.

    Args:
        additional_users: Additional users to exclude beyond current user

    Returns:
        Set of usernames to exclude

    """
    excluded = {get_current_username()}

    if additional_users:
        excluded.update(additional_users)

    logger.debug(f"Excluding users: {excluded}")
    return excluded


class ValidationUtils:
    """Common validation utilities."""

    @staticmethod
    def validate_not_empty(
        *values: str | None,
        names: list[str] | None = None,
    ) -> bool:
        """Validate that values are not None or empty strings.

        Args:
            *values: Values to validate
            names: Optional names for logging (must match length of values)

        Returns:
            True if all values are non-empty, False otherwise

        """
        if names and len(names) != len(values):
            msg = "Names list must match values length"
            raise ValueError(msg)

        for i, value in enumerate(values):
            if not value:
                name = names[i] if names else f"value {i}"
                logger.warning(f"Empty or None {name}")
                return False

        return True

    @staticmethod
    def validate_shot_components(show: str, sequence: str, shot: str) -> bool:
        """Validate shot component strings.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            True if all components are valid, False otherwise

        """
        return ValidationUtils.validate_not_empty(
            show,
            sequence,
            shot,
            names=["show", "sequence", "shot"],
        )
