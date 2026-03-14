from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import types as _types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias, cast


if TYPE_CHECKING:
    from type_definitions import ShotDict, ThreeDESceneDict

logger = logging.getLogger(__name__)

# Type alias for JSON data (used for runtime validation) - Python 3.11 compatible
JSONValue: TypeAlias = (
    dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None
)

# File locking configuration (enabled by default, opt-out via environment variable)
# Disable with: SHOTBOT_FILE_LOCKING=disabled
FILE_LOCKING_ENABLED = os.getenv("SHOTBOT_FILE_LOCKING", "enabled").lower() != "disabled"

# Check if fcntl is available (not on Windows)
# Import as optional module to avoid type errors
_fcntl: _types.ModuleType | None
try:
    import fcntl as _fcntl_module
    _fcntl = _fcntl_module
except ImportError:
    _fcntl = None


@contextlib.contextmanager
def file_lock(cache_file: Path):
    """Context manager for advisory file lock on cache operations.

    Only acquires lock if FILE_LOCKING_ENABLED is True and fcntl is available.
    Uses a separate .lock file to avoid conflicts with the actual cache file.

    Args:
        cache_file: The cache file being protected (lock file will be {cache_file}.lock)

    Yields:
        None - lock is held for the duration of the context

    """
    if not FILE_LOCKING_ENABLED or _fcntl is None:
        # File locking disabled or unavailable - just yield
        yield
        return

    lock_file = cache_file.with_suffix(cache_file.suffix + ".lock")
    lock_fd = None
    try:
        # Ensure parent directory exists
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Open/create lock file
        lock_fd = lock_file.open("w")

        # Acquire exclusive lock (blocks until available)
        _fcntl.flock(lock_fd.fileno(), _fcntl.LOCK_EX)  # pyright: ignore[reportAny]
        logger.debug(f"Acquired file lock: {lock_file}")

        yield

    except OSError:
        # Log but don't fail - fall back to no locking
        logger.warning(f"Failed to acquire file lock {lock_file}", exc_info=True)
        yield

    finally:
        if lock_fd is not None:
            try:
                # Release lock and close file
                # Note: _fcntl is guaranteed non-None here (early return if None)
                _fcntl.flock(lock_fd.fileno(), _fcntl.LOCK_UN)  # pyright: ignore[reportAny]
                lock_fd.close()
                logger.debug(f"Released file lock: {lock_file}")
            except OSError:
                logger.warning("Failed to release file lock", exc_info=True)


def read_json_cache(
    cache_file: Path, cache_ttl: timedelta, check_ttl: bool = True
) -> list[ShotDict | ThreeDESceneDict] | None:
    """Read and validate JSON cache file.

    Args:
        cache_file: Path to cache file
        cache_ttl: Maximum age before the cache is considered expired
        check_ttl: Whether to check TTL expiration (default True)

    Returns:
        Cached data or None if not found/expired/invalid

    """
    def _is_valid_dict_list(data: list[JSONValue]) -> bool:
        """Return True if data is empty or all elements are dicts."""
        if data and not all(isinstance(item, dict) for item in data):
            logger.warning(
                f"Invalid cache format: expected list of dicts in {cache_file}"
            )
            return False
        return True

    if not cache_file.exists():
        return None

    try:
        # Check TTL (if enabled)
        if check_ttl:
            age = datetime.now(tz=UTC) - datetime.fromtimestamp(
                cache_file.stat().st_mtime, tz=UTC
            )
            if age > cache_ttl:
                logger.debug(f"Cache expired: {cache_file}")
                return None

        # Read JSON - returns JSONValue which we validate at runtime
        with cache_file.open(encoding="utf-8") as f:
            raw_data: JSONValue = cast("JSONValue", json.load(f))

        # Validate structure through runtime checks and type narrowing
        if isinstance(raw_data, list):
            # Direct list format - validate ALL elements are dicts (not just first)
            # Uses generator for early exit on first non-dict
            if not _is_valid_dict_list(raw_data):
                return None
            return cast("list[ShotDict | ThreeDESceneDict]", raw_data)

        if isinstance(raw_data, dict):
            # Handle wrapped format: {"data": [...], "cached_at": "..."}
            # Try nested keys: data.data, data.shots, data.scenes
            result: JSONValue = next(
                (raw_data[k] for k in ("data", "shots", "scenes") if k in raw_data),
                None,
            )

            if result is None:
                logger.warning(
                    f"Unknown cache schema in {cache_file}: "
                    f"no 'data', 'shots', or 'scenes' key found"
                )
                return None

            if isinstance(result, list):
                if not _is_valid_dict_list(result):
                    return None
                return cast("list[ShotDict | ThreeDESceneDict]", result)
            return None

        logger.warning(
            f"Unexpected cache format: {cache_file}, type: {type(raw_data)}"
        )
        return None

    except (OSError, json.JSONDecodeError, ValueError):
        logger.exception(f"Failed to read cache file {cache_file}")
        return None


def atomic_json_write(
    path: Path,
    payload: object,
    *,
    indent: int | None,
    fsync: bool,
) -> None:
    """Write *payload* as JSON to *path* atomically using a temp file + os.replace().

    Raises on error — callers are responsible for exception handling and logging.

    Args:
        path: Destination file path (parent directory must already exist)
        payload: JSON-serializable data to write
        indent: JSON indentation level (None = compact, 2 = pretty)
        fsync: If True, flush and fsync before the atomic rename

    """
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=indent)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        # Atomic rename (POSIX guarantees atomicity on same filesystem)
        _ = Path(temp_path).replace(path)
    except Exception:
        # Clean up temp file on error
        with contextlib.suppress(OSError):
            Path(temp_path).unlink()
        raise


def write_json_cache(cache_file: Path, data: object) -> bool:
    """Write data to JSON cache file atomically.

    Args:
        cache_file: Path to cache file
        data: Data to cache

    Returns:
        True if write succeeded, False on error

    """
    try:
        # Ensure directory exists
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Simple format with metadata
        cache_data = {
            "data": data,
            "cached_at": datetime.now(tz=UTC).isoformat(),
        }

        # Atomic write: write to temp file, then rename
        # os.replace() is atomic on POSIX, ensuring readers see either old or new file, never partial
        atomic_json_write(cache_file, cache_data, indent=None, fsync=True)
        logger.debug(f"Cached data to: {cache_file}")
        return True

    except (OSError, TypeError, ValueError):
        logger.exception(f"Failed to write cache file {cache_file}")
        return False
