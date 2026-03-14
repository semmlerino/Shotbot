from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast, final

from PySide6.QtCore import QMutex, QMutexLocker

from cache._json_store import atomic_json_write
from cache.types import LatestFileCacheResult
from logging_mixin import LoggingMixin


LATEST_FILES_TTL_MINUTES = 5


@final
class LatestFileCache(LoggingMixin):
    """Latest Maya/3DE file path cache with TTL."""

    def __init__(self, cache_dir: Path) -> None:
        super().__init__()
        self._lock = QMutex()
        self._latest_files_ttl = timedelta(minutes=LATEST_FILES_TTL_MINUTES)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.latest_files_cache_file = cache_dir / "latest_files.json"

    def cache_latest_file(
        self,
        workspace_path: str,
        file_type: str,
        file_path: Path | None,
    ) -> None:
        """Cache the latest file path for a workspace."""
        with QMutexLocker(self._lock):
            cache_data = self._read_latest_files_cache() or {}

            key = f"{workspace_path}:{file_type}"

            cache_data[key] = {
                "path": str(file_path) if file_path else None,
                "cached_at": datetime.now(tz=UTC).timestamp(),
            }

            _ = self._write_latest_files_cache(cache_data)
        if file_path:
            self.logger.debug(f"Cached latest {file_type} file: {file_path.name}")
        else:
            self.logger.debug(f"Cached 'not found' for {file_type} in {workspace_path}")

    def get_latest_file_cache_result(
        self, workspace_path: str, file_type: str
    ) -> LatestFileCacheResult:
        """Get cached latest file with tri-state semantics.

        Returns:
            LatestFileCacheResult with:
            - status="miss": no entry, expired, or file deleted since caching
            - status="not_found": within TTL, confirmed nothing exists
            - status="hit": within TTL, file exists -> includes path
        """
        cache_data = self._read_latest_files_cache()
        if cache_data is None:
            return LatestFileCacheResult("miss")

        key = f"{workspace_path}:{file_type}"
        entry = cache_data.get(key)
        if entry is None:
            return LatestFileCacheResult("miss")

        # Check TTL
        cached_at_raw = entry.get("cached_at", 0.0)
        if isinstance(cached_at_raw, (int, float)):
            cached_at = float(cached_at_raw)
        else:
            cached_at = 0.0
        age = datetime.now(tz=UTC).timestamp() - cached_at
        if age > self._latest_files_ttl.total_seconds():
            self.logger.debug(f"Latest file cache expired for {key}")
            return LatestFileCacheResult("miss")

        # Within TTL — check the cached value
        path_str = entry.get("path")
        if path_str and isinstance(path_str, str):
            cached_path = Path(path_str)
            if cached_path.exists():
                self.logger.debug(f"Latest file cache hit: {cached_path.name}")
                return LatestFileCacheResult("hit", cached_path)
            self.logger.debug(f"Cached file no longer exists: {path_str}")
            return LatestFileCacheResult("miss")

        # path is None -> confirmed "not found" within TTL
        return LatestFileCacheResult("not_found")

    def clear_latest_files_cache(self, workspace_path: str | None = None) -> None:
        """Clear the latest files cache.

        Args:
            workspace_path: If provided, only clear cache for this workspace.
                          If None, clear entire cache.

        """
        if workspace_path is None:
            # Clear entire cache
            if self.latest_files_cache_file.exists():
                self.latest_files_cache_file.unlink()
                self.logger.debug("Cleared all latest files cache")
        else:
            # Clear only entries for this workspace
            cache_data = self._read_latest_files_cache()
            if cache_data:
                keys_to_remove = [
                    k for k in cache_data if k.startswith(f"{workspace_path}:")
                ]
                for key in keys_to_remove:
                    del cache_data[key]
                _ = self._write_latest_files_cache(cache_data)
                self.logger.debug(
                    f"Cleared latest files cache for workspace: {workspace_path}"
                )

    def _read_latest_files_cache(self) -> dict[str, dict[str, object]] | None:
        """Read the latest files cache from disk.

        Returns:
            Cache data as dict or None if not found

        """
        if not self.latest_files_cache_file.exists():
            return None

        try:
            with self.latest_files_cache_file.open(encoding="utf-8") as f:
                data: object = json.load(f)  # pyright: ignore[reportAny]
            if isinstance(data, dict):
                return cast("dict[str, dict[str, object]]", data)
            return None
        except Exception:
            self.logger.exception("Failed to read latest files cache")
            return None

    def _write_latest_files_cache(
        self,
        data: dict[str, dict[str, object]],
    ) -> bool:
        """Write the latest files cache to disk.

        Args:
            data: Cache data to write

        Returns:
            True if successful, False otherwise

        """
        try:
            atomic_json_write(
                self.latest_files_cache_file, data, indent=2, fsync=False
            )
            return True
        except Exception:
            self.logger.exception("Failed to write latest files cache")
            return False

    def shutdown(self) -> None:
        """Shutdown stub (no-op)."""


def make_default_latest_file_cache(base_dir: Path | None = None) -> LatestFileCache:
    """Create a LatestFileCache using the env-resolved default directory."""
    from cache._dir_resolver import resolve_default_cache_dir
    resolved = base_dir if base_dir is not None else resolve_default_cache_dir()
    resolved.mkdir(parents=True, exist_ok=True)
    return LatestFileCache(resolved)
