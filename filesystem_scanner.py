"""FileSystemScanner module - Extracted from threede_scene_finder_optimized.py

This module handles efficient filesystem scanning operations for finding .3de files
with various optimization strategies including caching, subprocess fallback, and
progressive discovery.

Part of the Phase 2 refactoring to break down the monolithic scene finder.
"""
# pyright: reportImportCycles=false
# Import cycles are broken at runtime through lazy imports in scene_discovery_coordinator.py
# and scene_discovery_strategy.py. The module-level imports here only include standard library
# and LoggingMixin. All local imports (FilesystemCoordinator, SceneParser) are lazy or TYPE_CHECKING.

from __future__ import annotations

# Standard library imports
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

# Local application imports
from logging_mixin import LoggingMixin

if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator

    # Local application imports - TYPE_CHECKING to break import cycles
    from filesystem_coordinator import FilesystemCoordinator
    from scene_parser import SceneParser  # Import for string literal type hint


class DirectoryCache(LoggingMixin):
    """Thread-safe directory listing cache with TTL.

    Extracted from the monolithic scene finder to provide focused caching functionality.
    """

    def __init__(
        self, ttl_seconds: int = 300, enable_auto_expiry: bool = False
    ) -> None:
        """Initialize directory cache.

        Args:
            ttl_seconds: TTL for automatic expiration (only used if enable_auto_expiry=True)
            enable_auto_expiry: If True, entries expire automatically. If False, manual refresh only.
        """
        super().__init__()
        self.ttl = ttl_seconds
        self.enable_auto_expiry = enable_auto_expiry
        self.cache: dict[str, list[tuple[str, bool, bool]]] = {}
        self.timestamps: dict[str, float] = {}
        self.lock = threading.RLock()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}

    def get_listing(self, path: Path) -> list[tuple[str, bool, bool]] | None:
        """Get cached directory listing or None if not cached/expired."""
        path_str = str(path)

        with self.lock:
            if path_str in self.cache:
                # Check TTL only if auto-expiry is enabled
                if self.enable_auto_expiry:
                    if time.time() - self.timestamps[path_str] < self.ttl:
                        self.stats["hits"] += 1
                        return self.cache[path_str]
                    # Expired
                    del self.cache[path_str]
                    del self.timestamps[path_str]
                    self.stats["evictions"] += 1
                else:
                    # No auto-expiry, return cached entry
                    self.stats["hits"] += 1
                    return self.cache[path_str]

            self.stats["misses"] += 1
            return None

    def set_listing(self, path: Path, listing: list[tuple[str, bool, bool]]) -> None:
        """Cache directory listing."""
        path_str = str(path)

        with self.lock:
            self.cache[path_str] = listing
            self.timestamps[path_str] = time.time()

            # Simple cleanup: remove expired entries if cache gets large (only if auto-expiry enabled)
            if self.enable_auto_expiry and len(self.cache) > 1000:
                current_time = time.time()
                expired_keys = [
                    k
                    for k, t in self.timestamps.items()
                    if current_time - t >= self.ttl
                ]
                for key in expired_keys:
                    self.cache.pop(key, None)
                    self.timestamps.pop(key, None)
                self.stats["evictions"] += len(expired_keys)

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics."""
        with self.lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate_float = (
                (self.stats["hits"] / total_requests * 100)
                if total_requests > 0
                else 0.0
            )
            return {
                "hit_rate_percent": int(hit_rate_float),
                "total_entries": len(self.cache),
                **self.stats,
            }

    def clear_cache(self) -> int:
        """Manually clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            self.timestamps.clear()
            self.stats["evictions"] += count
            return count

    def refresh_cache(self) -> int:
        """Manually refresh the cache by clearing all entries.

        This forces fresh filesystem lookups on next access.

        Returns:
            Number of entries cleared
        """
        return self.clear_cache()


class FileSystemScanner(LoggingMixin):
    """Efficient filesystem scanner for .3de files with multiple optimization strategies.

    This class encapsulates all filesystem scanning logic extracted from the monolithic
    scene finder, providing clean separation of concerns and reusable scanning capabilities.
    """

    # Class-level cache (shared across instances) - manual refresh only
    _dir_cache = DirectoryCache(ttl_seconds=300, enable_auto_expiry=False)

    # Workload size thresholds for strategy selection
    SMALL_WORKLOAD_THRESHOLD = 100  # Use Python-only below this
    MEDIUM_WORKLOAD_THRESHOLD = 1000  # Use optimized find above this
    CONCURRENT_THRESHOLD = 2000  # Use concurrent processing above this

    # Common excluded directories
    EXCLUDED_DIRS: ClassVar[set[str]] = {
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".cache",
        ".tmp",
        "temp",
        "tmp",
    }

    def __init__(self) -> None:
        """Initialize FileSystemScanner."""
        super().__init__()
        # Lazy imports to avoid circular dependencies - imported at runtime
        self._fs_coordinator: FilesystemCoordinator | None = None
        self.parser: SceneParser | None = None

    @classmethod
    def get_cache_stats(cls) -> dict[str, int]:
        """Get directory cache statistics."""
        return cls._dir_cache.get_stats()

    @classmethod
    def clear_cache(cls) -> None:
        """Clear directory cache."""
        cls._dir_cache.cache.clear()
        cls._dir_cache.timestamps.clear()

    @classmethod
    def refresh_cache(cls) -> int:
        """Manually refresh the directory cache.

        Returns:
            Number of cache entries cleared
        """
        return cls._dir_cache.refresh_cache()

    def get_directory_listing_cached(self, path: Path) -> list[tuple[str, bool, bool]]:
        """Get directory listing with caching using FilesystemCoordinator.

        Returns list of tuples: (name, is_dir, is_file)
        """
        # Lazy import to avoid circular dependency
        if self._fs_coordinator is None:
            from filesystem_coordinator import FilesystemCoordinator

            self._fs_coordinator = FilesystemCoordinator()

        # Use FilesystemCoordinator for shared caching across workers
        raw_listing = self._fs_coordinator.get_directory_listing(path)

        # Convert Path objects to the expected tuple format
        listing: list[tuple[str, bool, bool]] = []
        for item in raw_listing:
            try:
                # Determine if directory or file
                is_dir = item.is_dir()
                is_file = item.is_file()
                listing.append((item.name, is_dir, is_file))
            except (OSError, PermissionError):
                # Skip items we can't stat
                continue

        # Also update the old cache for backward compatibility
        self._dir_cache.set_listing(path, listing)

        return listing

    def find_3de_files_python_optimized(
        self, user_dir: Path, excluded_users: set[str] | None
    ) -> list[tuple[str, Path]]:
        """Optimized Python-based .3de file discovery.

        Returns list of (username, file_path) tuples.
        """
        files: list[tuple[str, Path]] = []

        try:
            # Use cached directory listing
            user_entries = self.get_directory_listing_cached(user_dir)

            self.logger.debug(
                f"Scanning user dir: {user_dir}, found {len(user_entries)} entries"
            )

            for entry_name, is_dir, _ in user_entries:
                if is_dir and (
                    excluded_users is None or entry_name not in excluded_users
                ):
                    user_path = user_dir / entry_name
                    self.logger.debug(
                        f"Searching for .3de files in user directory: {user_path}"
                    )

                    # Use rglob for finding .3de files (proven fastest in profiling)
                    try:
                        # Process both extensions efficiently
                        found_count = 0
                        for ext in ("*.3de", "*.3DE"):
                            for threede_file in user_path.rglob(ext):
                                if threede_file.is_file():
                                    files.append((entry_name, threede_file))
                                    found_count += 1
                                    self.logger.debug(
                                        f"Found .3de file: {threede_file}"
                                    )

                        if found_count > 0:
                            self.logger.info(
                                f"Found {found_count} .3de files for user {entry_name}"
                            )
                    except (OSError, PermissionError) as e:
                        self.logger.warning(
                            f"Permission denied accessing {user_path}: {e}"
                        )
                        continue

        except (OSError, PermissionError) as e:
            self.logger.warning(f"Permission denied accessing {user_dir}: {e}")

        return files

    def find_3de_files_subprocess_optimized(
        self, user_dir: Path, excluded_users: set[str] | None
    ) -> list[tuple[str, Path]]:
        """Optimized subprocess-based .3de file discovery for large workloads."""
        files: list[tuple[str, Path]] = []

        try:
            # Build exclusion patterns for find command
            exclusions: list[str] = []
            if excluded_users:
                for excluded_user in excluded_users:
                    exclusions.extend(["-not", "-path", f"*/{excluded_user}/*"])

            # Single optimized find command
            cmd = [
                "find",
                str(user_dir),
                "-maxdepth",
                "10",  # Reasonable depth limit
                "-type",
                "f",
                "(",
                "-name",
                "*.3de",
                "-o",
                "-name",
                "*.3DE",
                ")",
                *exclusions,
            ]

            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout:
                for file_path_str in result.stdout.strip().split("\n"):
                    if file_path_str:
                        file_path = Path(file_path_str)
                        try:
                            # Extract username from path
                            relative_path = file_path.relative_to(user_dir)
                            if relative_path.parts:
                                username = relative_path.parts[0]
                                if (
                                    excluded_users is None
                                    or username not in excluded_users
                                ):
                                    files.append((username, file_path))
                        except ValueError:
                            # File not under user_dir, skip
                            continue

        except (
            subprocess.TimeoutExpired,
            subprocess.SubprocessError,
            FileNotFoundError,
        ):
            # Fallback to Python method
            self.logger.debug("Subprocess method failed, falling back to Python")
            return self.find_3de_files_python_optimized(user_dir, excluded_users)
        except (OSError, PermissionError):
            self.logger.debug(f"Permission denied accessing {user_dir}")

        return files

    def find_3de_files_progressive(
        self, user_dir: Path, excluded_users: set[str] | None
    ) -> list[tuple[str, Path]]:
        """Progressive discovery that starts with Python method and adapts based on findings.

        This method eliminates the need for workload estimation by using adaptive discovery.
        It starts with the Python approach and switches strategies if needed.

        Args:
            user_dir: User directory to search
            excluded_users: Set of usernames to exclude

        Returns:
            List of (username, file_path) tuples
        """
        files: list[tuple[str, Path]] = []

        try:
            # Use cached directory listing to get user count quickly
            user_entries = self.get_directory_listing_cached(user_dir)
            user_count = sum(1 for _, is_dir, _ in user_entries if is_dir)

            # Adaptive strategy based on user count (no double traversal)
            if user_count <= self.SMALL_WORKLOAD_THRESHOLD:
                # Small workload: use Python approach
                self.logger.debug(f"Using Python method for {user_count} users")
                files = self.find_3de_files_python_optimized(user_dir, excluded_users)
            else:
                # Larger workload: use subprocess approach
                self.logger.debug(f"Using subprocess method for {user_count} users")
                files = self.find_3de_files_subprocess_optimized(
                    user_dir, excluded_users
                )

        except Exception as e:
            self.logger.warning(f"Error in progressive discovery: {e}")
            # Fallback to Python method
            self.logger.debug("Falling back to Python method due to error")
            files = self.find_3de_files_python_optimized(user_dir, excluded_users)

        return files

    def quick_3de_exists_check(
        self, base_paths: list[str], _timeout_seconds: int = 15
    ) -> bool:
        """Optimized quick check for .3de file existence."""

        for base_path in base_paths:
            if not os.path.exists(base_path):
                continue

            try:
                base_path_obj = Path(base_path)

                # Use os.scandir for efficient directory traversal
                def quick_scan(path: Path, depth: int = 0) -> bool:
                    if depth > 10:  # Reasonable depth limit
                        return False

                    try:
                        with os.scandir(path) as entries:
                            for entry in entries:
                                if (
                                    entry.is_file()
                                    and entry.name.lower().endswith(".3de")
                                ) or (
                                    (
                                        entry.is_dir()
                                        and entry.name not in self.EXCLUDED_DIRS
                                    )
                                    and quick_scan(Path(entry.path), depth + 1)
                                ):
                                    return True
                    except (OSError, PermissionError):
                        pass

                    return False

                if quick_scan(base_path_obj):
                    self.logger.debug(f"Quick check found .3de files in {base_path}")
                    return True

            except Exception as e:
                self.logger.debug(f"Error in quick check for {base_path}: {e}")
                continue

        self.logger.debug("Quick check found no .3de files")
        return False

    def verify_scene_exists(self, scene_path: Path) -> bool:
        """Optimized scene existence verification."""
        if not scene_path:
            return False

        try:
            # Single check combining multiple conditions
            return (
                scene_path.is_file()
                and os.access(scene_path, os.R_OK)
                and scene_path.suffix.lower() in [".3de"]
            )
        except Exception:
            return False

    def discover_all_shots_in_show(
        self, show_root: str, show: str
    ) -> list[tuple[str, str, str, str]]:
        """Discover all shots in a show by scanning the filesystem.

        Args:
            show_root: Root path for shows (e.g., '/shows')
            show: Show name

        Returns:
            List of tuples (workspace_path, show, sequence, shot)
        """
        shots: list[tuple[str, str, str, str]] = []
        show_path = Path(show_root) / show

        if not show_path.exists():
            self.logger.warning(f"Show path does not exist: {show_path}")
            return shots

        # Look for shots directory
        shots_dir = show_path / "shots"
        if not shots_dir.exists():
            self.logger.warning(f"No shots directory found for show {show}")
            return shots

        try:
            # Iterate through sequence directories
            for sequence_dir in shots_dir.iterdir():
                if not sequence_dir.is_dir():
                    continue

                sequence = sequence_dir.name

                # Iterate through shot directories
                for shot_dir in sequence_dir.iterdir():
                    if not shot_dir.is_dir():
                        continue

                    shot_name = shot_dir.name
                    workspace_path = str(shot_dir)

                    # Basic validation - check if it looks like a shot directory
                    # Could have user/, publish/, or other standard directories
                    shots.append((workspace_path, show, sequence, shot_name))

            self.logger.info(f"Discovered {len(shots)} shots in show {show}")

        except (OSError, PermissionError) as e:
            self.logger.error(f"Error discovering shots in {show}: {e}")

        return shots

    def estimate_scan_size(
        self,
        shot_tuples: list[tuple[str, str, str, str]],
        excluded_users: set[str] | None = None,
    ) -> tuple[int, int]:
        """Estimate the size of a scan operation.

        Args:
            shot_tuples: List of (workspace_path, show, sequence, shot) tuples
            excluded_users: Set of usernames to exclude

        Returns:
            Tuple of (estimated_users, estimated_files)
        """
        if not shot_tuples:
            return 0, 0

        total_estimated_users = 0
        total_estimated_files = 0

        for workspace_path, _, _, _ in shot_tuples:
            try:
                shot_path = Path(workspace_path)
                user_dir = shot_path / "user"

                if not user_dir.exists():
                    continue

                # Count user directories
                user_count = 0
                with os.scandir(user_dir) as entries:
                    for entry in entries:
                        if entry.is_dir() and (
                            excluded_users is None or entry.name not in excluded_users
                        ):
                            user_count += 1

                total_estimated_users += user_count
                # Estimate 2-3 files per user on average
                total_estimated_files += user_count * 3

            except (OSError, PermissionError):
                # Use fallback estimate for inaccessible directories
                total_estimated_files += 10

        return total_estimated_users, total_estimated_files

    def find_all_scenes_progressive(
        self,
        shot_tuples: list[tuple[str, str, str, str]],
        excluded_users: set[str] | None = None,
        batch_size: int = 10,
    ) -> Generator[tuple[list[tuple[str, Path]], int, int, str], None, None]:
        """Progressive scene finder that yields batches of results.

        Args:
            shot_tuples: List of (workspace_path, show, sequence, shot) tuples
            excluded_users: Set of usernames to exclude
            batch_size: Number of files per batch

        Yields:
            Tuple of (file_batch, current_shot, total_shots, status_message)
            Where file_batch is list of (username, file_path) tuples
        """
        if not shot_tuples:
            return

        total_shots = len(shot_tuples)
        current_batch: list[tuple[str, Path]] = []

        for current_shot_idx, (workspace_path, show, sequence, shot) in enumerate(
            shot_tuples, 1
        ):
            status_msg = f"Scanning {show}/{sequence}/{shot}"

            try:
                # Check user directory
                shot_path = Path(workspace_path)
                user_dir = shot_path / "user"

                if user_dir.exists():
                    # Find files for this shot using progressive discovery
                    file_pairs = self.find_3de_files_progressive(
                        user_dir, excluded_users
                    )
                    current_batch.extend(file_pairs)

                # Yield batch when it reaches the target size
                if len(current_batch) >= batch_size:
                    yield current_batch, current_shot_idx, total_shots, status_msg
                    current_batch = []
                else:
                    # Yield empty batch with progress update
                    yield [], current_shot_idx, total_shots, status_msg

            except Exception as e:
                self.logger.warning(f"Error scanning shot {workspace_path}: {e}")
                # Yield empty batch to maintain progress
                yield [], current_shot_idx, total_shots, f"Error: {status_msg}"

        # Yield any remaining files in the final batch
        if current_batch:
            yield current_batch, total_shots, total_shots, "Scan complete"

    def find_all_3de_files_in_show_targeted(
        self, show_root: str, show: str, excluded_users: set[str] | None = None
    ) -> list[tuple[Path, str, str, str, str, str]]:
        """Find all .3de files using a single efficient search.

        Uses a single find command to locate all .3de files in user and publish
        directories, avoiding unnecessary iteration through empty shot directories.

        Args:
            show_root: Root path for shows (e.g., '/shows')
            show: Show name
            excluded_users: Set of usernames to exclude

        Returns:
            List of tuples: (file_path, show, sequence, shot, user, plate)
        """
        # Standard library imports
        import subprocess
        import traceback

        # Lazy import to avoid circular dependency
        if self.parser is None:
            from scene_parser import SceneParser

            self.parser = SceneParser()

        self.logger.info(
            "=== STARTING find_all_3de_files_in_show_targeted (optimized) ==="
        )
        self.logger.info(f"  show_root: {show_root}")
        self.logger.info(f"  show: {show}")

        show_path = Path(show_root) / show
        shots_dir = show_path / "shots"

        if not shots_dir.exists():
            self.logger.warning(f"No shots directory found: {shots_dir}")
            return []

        results: list[tuple[Path, str, str, str, str, str]] = []
        excluded_users = excluded_users or set()

        start_time = time.time()
        file_count = 0
        parsed_count = 0
        unique_shots: set[str] = set()

        try:
            self.logger.info("Using single-search strategy to find all .3de files")

            # Build optimized find command for network filesystems
            # Use -prune to skip directories we don't need, reducing network traversal
            find_cmd = [
                "find",
                str(shots_dir),
                # Prune directories that definitely won't have 3DE files
                "(",
                "-path",
                "*/render",
                "-o",
                "-path",
                "*/comp",
                "-o",
                "-path",
                "*/output",
                "-o",
                "-path",
                "*/cache",
                "-o",
                "-path",
                "*/tmp",
                "-o",
                "-path",
                "*/temp",
                "-o",
                "-path",
                "*/backup",
                ")",
                "-prune",
                "-o",
                # Look for .3de files in user and publish directories
                "-type",
                "f",
                "(",
                "-path",
                "*/user/*",
                "-o",
                "-path",
                "*/publish/*",
                ")",
                "(",
                "-name",
                "*.3de",
                "-o",
                "-name",
                "*.3DE",
                ")",
                "-print",
            ]

            self.logger.debug(f"Running find command: {' '.join(find_cmd)}")

            try:
                # Run find command with longer timeout for network filesystems
                result = subprocess.run(
                    find_cmd,
                    check=False, capture_output=True,
                    text=True,
                    timeout=300,  # 300 second timeout for large network directories
                )

                if result.returncode == 0 and result.stdout:
                    # Process each found file
                    for line in result.stdout.strip().split("\n"):
                        if not line:
                            continue

                        file_count += 1
                        threede_file = Path(line)

                        # Log progress
                        if file_count <= 5 or file_count % 50 == 0:
                            elapsed = time.time() - start_time
                            self.logger.info(
                                (f"Progress: Found {file_count} .3de files, "
                                f"parsed {parsed_count} valid scenes from {len(unique_shots)} shots "
                                f"({elapsed:.1f}s)")
                            )

                        # Parse the file path using the extracted parser
                        parsed = self.parser.parse_3de_file_path(
                            threede_file, show_path, show, excluded_users
                        )

                        if parsed:
                            results.append(parsed)
                            parsed_count += 1

                            # Track unique shots
                            _, _, sequence, shot, _, _ = parsed
                            unique_shots.add(f"{sequence}/{shot}")

                            if parsed_count <= 3:
                                self.logger.debug(
                                    f"  Parsed: {threede_file.relative_to(show_path)}"
                                )

                elif result.returncode != 0:
                    self.logger.warning(
                        f"Find command failed with return code {result.returncode}"
                    )
                    self.logger.warning(f"stderr: {result.stderr}")
                    # Fall back to Python-based search
                    self.logger.info("Falling back to Python-based search")
                    return self._fallback_python_search(
                        shots_dir, show_path, show, excluded_users
                    )

            except subprocess.TimeoutExpired:
                self.logger.error("Find command timed out after 300 seconds")
                self.logger.info("Falling back to Python-based search")
                return self._fallback_python_search(
                    shots_dir, show_path, show, excluded_users
                )
            except FileNotFoundError:
                self.logger.warning(
                    "'find' command not available, using Python-based search"
                )
                return self._fallback_python_search(
                    shots_dir, show_path, show, excluded_users
                )

        except Exception as e:
            self.logger.error(f"Error in optimized search: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")

        elapsed = time.time() - start_time
        self.logger.info(
            "=== COMPLETED find_all_3de_files_in_show_targeted (optimized) ==="
        )
        self.logger.info(f"  Found {file_count} .3de files in {elapsed:.2f}s")
        self.logger.info(f"  Parsed {parsed_count} valid scenes")
        self.logger.info(f"  Unique shots with 3DE files: {len(unique_shots)}")

        # Log sample of unique shots
        if unique_shots:
            sample_shots = list(unique_shots)[:5]
            self.logger.debug(f"  Sample shots: {', '.join(sample_shots)}")

        return results

    def _fallback_python_search(
        self,
        shots_dir: Path,
        show_path: Path,
        show: str,
        excluded_users: set[str] | None,
    ) -> list[tuple[Path, str, str, str, str, str]]:
        """Fallback Python-based search when find command is not available.

        This uses a more efficient approach than the original by using
        glob patterns directly on the shots directory.
        """
        # Lazy import to avoid circular dependency
        if self.parser is None:
            from scene_parser import SceneParser

            self.parser = SceneParser()

        results: list[tuple[Path, str, str, str, str, str]] = []
        excluded_users = excluded_users or set()

        self.logger.info("Using Python-based fallback search")
        start_time = time.time()
        file_count = 0

        try:
            # Search for .3de files in user directories
            for pattern in ["*/*/user/**/*.3de", "*/*/user/**/*.3DE"]:
                for threede_file in shots_dir.glob(pattern):
                    file_count += 1
                    parsed = self.parser.parse_3de_file_path(
                        threede_file, show_path, show, excluded_users
                    )
                    if parsed:
                        results.append(parsed)

            # Search for .3de files in publish directories
            for pattern in ["*/*/publish/**/*.3de", "*/*/publish/**/*.3DE"]:
                for threede_file in shots_dir.glob(pattern):
                    file_count += 1
                    parsed = self.parser.parse_3de_file_path(
                        threede_file, show_path, show, excluded_users
                    )
                    if parsed:
                        results.append(parsed)

        except Exception as e:
            self.logger.error(f"Error in Python fallback search: {e}")

        elapsed = time.time() - start_time
        self.logger.info(f"Python search found {file_count} files in {elapsed:.2f}s")

        return results
