"""FileSystemScanner module - Extracted from threede_scene_finder_optimized.py

This module handles efficient filesystem scanning operations for finding .3de files
with various optimization strategies including caching, subprocess fallback, and
progressive discovery.
"""
# pyright: reportImportCycles=false
# Import cycles are broken at runtime through lazy imports in scene_discovery_coordinator.py
# and scene_discovery_strategy.py. The module-level imports here only include standard library
# and LoggingMixin. All local imports (FilesystemCoordinator, SceneParser) are lazy or TYPE_CHECKING.

from __future__ import annotations

# Standard library imports
import os
import selectors
import subprocess
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast, final

# Local application imports
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator

    # Local application imports - TYPE_CHECKING to break import cycles
    from filesystem_coordinator import FilesystemCoordinator
    from scene_parser import SceneParser  # Import for string literal type hint


@final
class FileSystemScanner(LoggingMixin):
    """Efficient filesystem scanner for .3de files with multiple optimization strategies.

    This class encapsulates all filesystem scanning logic extracted from the monolithic
    scene finder, providing clean separation of concerns and reusable scanning capabilities.
    """

    # Workload size thresholds for strategy selection
    SMALL_WORKLOAD_THRESHOLD = 100  # Use Python-only below this

    # Maximum recursion depth for _quick_scan. Deep enough to reach .3de files
    # in typical VFX directory structures without traversing the whole tree.
    _MAX_QUICK_SCAN_DEPTH: int = 10

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

        # Thread-safe lazy initialization locks (for concurrent ThreadPoolExecutor usage)
        self._parser_lock = threading.Lock()
        self._fs_coordinator_lock = threading.Lock()

    @classmethod
    def get_cache_stats(cls) -> dict[str, int | float]:
        """Get directory cache statistics from FilesystemCoordinator."""
        from filesystem_coordinator import FilesystemCoordinator
        return FilesystemCoordinator().get_cache_stats()

    @classmethod
    def clear_cache(cls) -> int:
        """Clear directory cache.

        Delegates to FilesystemCoordinator.invalidate_all() which uses internal
        locking to prevent race conditions with concurrent cache access.

        Returns:
            Number of entries cleared.
        """
        from filesystem_coordinator import FilesystemCoordinator
        return FilesystemCoordinator().invalidate_all()

    def get_directory_listing_cached(self, path: Path) -> list[tuple[str, bool, bool]]:
        """Get directory listing with caching using FilesystemCoordinator.

        Returns list of tuples: (name, is_dir, is_file)
        """
        # Thread-safe lazy import to avoid circular dependency
        # Uses double-check locking pattern for concurrent ThreadPoolExecutor usage
        if self._fs_coordinator is None:
            with self._fs_coordinator_lock:
                # Double-check: another thread might have initialized while waiting for lock
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

        except (OSError, PermissionError):
            self.logger.warning(f"Permission denied accessing {user_dir}", exc_info=True)

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
        """Adaptive discovery that picks a strategy once based on workload size.

        This method eliminates the need for workload estimation by using adaptive discovery.
        It reads the user count from cache and selects either the Python or subprocess
        approach for the entire scan — it does not switch mid-scan.

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

        except Exception:
            self.logger.warning("Error in progressive discovery", exc_info=True)
            # Fallback to Python method
            self.logger.debug("Falling back to Python method due to error")
            files = self.find_3de_files_python_optimized(user_dir, excluded_users)

        return files

    def quick_3de_exists_check(
        self, base_paths: list[str]
    ) -> bool:
        """Optimized quick check for .3de file existence."""
        for base_path in base_paths:
            if not Path(base_path).exists():
                continue

            try:
                if self._quick_scan(Path(base_path)):
                    self.logger.debug(f"Quick check found .3de files in {base_path}")
                    return True

            except Exception as e:
                self.logger.debug(f"Error in quick check for {base_path}: {e}")
                continue

        self.logger.debug("Quick check found no .3de files")
        return False

    def _quick_scan(self, path: Path, depth: int = 0) -> bool:
        """Recursively scan for any .3de file within path up to _MAX_QUICK_SCAN_DEPTH.

        Args:
            path: Directory to scan.
            depth: Current recursion depth (starts at 0).

        Returns:
            True if at least one .3de file is found, False otherwise.

        """
        if depth > self._MAX_QUICK_SCAN_DEPTH:
            return False

        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.lower().endswith(".3de"):
                        return True
                    if (
                        entry.is_dir()
                        and entry.name not in self.EXCLUDED_DIRS
                        and self._quick_scan(Path(entry.path), depth + 1)
                    ):
                        return True
        except (OSError, PermissionError):
            pass

        return False

    def verify_scene_exists(self, scene_path: Path | None) -> bool:
        """Optimized scene existence verification."""
        if not scene_path:
            return False

        try:
            # Single check combining multiple conditions
            return (
                scene_path.is_file()
                and os.access(scene_path, os.R_OK)
                and scene_path.suffix.lower() == ".3de"
            )
        except Exception:
            self.logger.warning(
                f"Exception checking scene existence for {scene_path}; treating as missing",
                exc_info=True,
            )
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

        except (OSError, PermissionError):
            self.logger.exception(f"Error discovering shots in {show}")

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
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Generator[tuple[list[tuple[str, Path]], int, int, str], None, None]:
        """Progressive scene finder that yields batches of results.

        Args:
            shot_tuples: List of (workspace_path, show, sequence, shot) tuples
            excluded_users: Set of usernames to exclude
            batch_size: Number of files per batch
            cancel_flag: Optional callback to check if operation should be cancelled

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
            # Check for cancellation at start of each shot iteration
            if cancel_flag and cancel_flag():
                self.logger.debug("Scene discovery cancelled by user")
                return

            status_msg = f"Scanning {show}/{sequence}/{shot}"

            try:
                # Check user directory
                shot_path = Path(workspace_path)
                user_dir = shot_path / "user"

                # Check for cancellation before expensive I/O operation
                if cancel_flag and cancel_flag():
                    self.logger.debug("Scene discovery cancelled during shot scan")
                    return

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

            except Exception:
                self.logger.warning(f"Error scanning shot {workspace_path}", exc_info=True)
                # Yield empty batch to maintain progress
                yield [], current_shot_idx, total_shots, f"Error: {status_msg}"

        # Yield any remaining files in the final batch
        if current_batch:
            yield current_batch, total_shots, total_shots, "Scan complete"

    def _run_subprocess_with_streaming_read(
        self,
        cmd: list[str],
        cancel_flag: Callable[[], bool] | None,
        max_wait_time: float,
        poll_interval: float = 0.1,
    ) -> tuple[int | None, str, str, str]:
        """Run subprocess with streaming reads to avoid pipe buffer deadlock.

        This method uses selectors to read from stdout/stderr while the process runs,
        preventing deadlock when subprocess output exceeds the OS pipe buffer (~64KB).

        Args:
            cmd: Command to execute as list of arguments
            cancel_flag: Optional callback that returns True if execution should be cancelled
            max_wait_time: Maximum time to wait for command (seconds)
            poll_interval: How often to check for cancellation/timeout (seconds)

        Returns:
            Tuple of (return_code, stdout, stderr, status)
            status is "ok", "cancelled", or "timeout"
            return_code is None if cancelled or timed out

        """
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Register stdout and stderr for non-blocking reads
        sel = selectors.DefaultSelector()
        try:
            if process.stdout:
                _ = sel.register(process.stdout, selectors.EVENT_READ, "stdout")
            if process.stderr:
                _ = sel.register(process.stderr, selectors.EVENT_READ, "stderr")

            elapsed_time = 0.0

            while process.poll() is None:
                # Check cancellation
                if cancel_flag and cancel_flag():
                    self.logger.info("Subprocess cancelled by cancel_flag")
                    process.kill()
                    _ = process.wait()
                    return (None, "", "", "cancelled")

                # Check timeout
                if elapsed_time >= max_wait_time:
                    self.logger.error(
                        f"Subprocess timed out after {max_wait_time} seconds"
                    )
                    process.kill()
                    _ = process.wait()
                    return (None, "", "", "timeout")

                # Read available data (selector handles timeout for responsiveness)
                ready = sel.select(timeout=poll_interval)
                for key, _ in ready:
                    # Read available data in chunks to avoid blocking
                    # fileobj is IO[str] in text mode, read() returns str
                    data = cast("str", key.fileobj.read(8192))  # type: ignore[union-attr]
                    if data:
                        if key.data == "stdout":
                            stdout_chunks.append(data)
                        else:
                            stderr_chunks.append(data)

                elapsed_time += poll_interval

            # Process exited - drain any remaining buffered data
            for key, _ in sel.select(timeout=0):
                remaining = cast("str", key.fileobj.read())  # type: ignore[union-attr]
                if remaining:
                    if key.data == "stdout":
                        stdout_chunks.append(remaining)
                    else:
                        stderr_chunks.append(remaining)

            return (
                process.returncode,
                "".join(stdout_chunks),
                "".join(stderr_chunks),
                "ok",
            )

        finally:
            sel.close()

    def _run_find_and_parse(
        self,
        find_cmd: list[str],
        show_path: Path,
        show: str,
        excluded_users: set[str],
        cancel_flag: Callable[[], bool] | None,
        max_wait_time: float = 300.0,
    ) -> list[tuple[Path, str, str, str, str, str]] | None:
        """Run a find command with cancellation polling and return parsed results.

        Args:
            find_cmd: The find command as list of arguments
            show_path: Path to the show directory
            show: Show name
            excluded_users: Set of usernames to exclude
            cancel_flag: Optional callback that returns True if scan should be cancelled
            max_wait_time: Maximum time to wait for find command (seconds)

        Returns:
            List of tuples: (file_path, show, sequence, shot, user, plate)
            Returns None on timeout, empty list on cancellation.

        """
        # Validate parameters
        if max_wait_time <= 0:
            msg = f"max_wait_time must be positive, got {max_wait_time}"
            raise ValueError(msg)

        results: list[tuple[Path, str, str, str, str, str]] = []

        try:
            # Use streaming read to avoid pipe buffer deadlock on large outputs
            returncode, stdout, stderr, status = self._run_subprocess_with_streaming_read(
                find_cmd, cancel_flag, max_wait_time
            )

            # Handle cancellation and timeout
            if status == "cancelled":
                return []  # Return empty list on cancellation
            if status == "timeout":
                return None  # Explicit timeout signal

            if returncode == 0 and stdout:
                # Parse each found file
                for line in stdout.strip().split("\n"):
                    if not line:
                        continue

                    threede_file = Path(line)

                    # Parse the file path using the extracted parser
                    if self.parser:
                        parsed = self.parser.parse_3de_file_path(
                            threede_file, show_path, show, excluded_users
                        )

                        if parsed:
                            results.append(parsed)

            elif returncode != 0:
                self.logger.warning(
                    f"Find command failed with return code {returncode}"
                )
                if stderr:
                    self.logger.warning(f"stderr: {stderr}")

        except (FileNotFoundError, OSError):
            self.logger.warning("Error running find command", exc_info=True)

        return results

    def _ensure_parser(self) -> None:
        """Ensure the SceneParser is initialized (thread-safe lazy init).

        Uses double-check locking for concurrent ThreadPoolExecutor usage.
        Shared by find_all_3de_files_in_show_targeted and _fallback_python_search.
        """
        if self.parser is None:
            with self._parser_lock:
                if self.parser is None:
                    from scene_parser import SceneParser

                    self.parser = SceneParser()

    def _build_find_commands(
        self, shots_dir: Path
    ) -> tuple[list[str], list[str]]:
        """Build the two find commands for the dual-search strategy.

        Returns:
            Tuple of (find_cmd_user, find_cmd_publish_dirs)

        """
        # Directories to aggressively prune
        prune_dirs = [
            "render", "comp", "output", "cache", "tmp", "temp", "backup",
            "plates", "elements", "assets", "textures", "footage",
            "turnover", "reference", "editorial", "audio",
            ".git", ".svn", "__pycache__", "node_modules",
            "versions", ".backup", "old", "archive",
        ]

        prune_expr: list[str] = []
        for i, dir_name in enumerate(prune_dirs):
            if i > 0:
                prune_expr.extend(["-o"])
            prune_expr.extend(["-path", f"*/{dir_name}"])

        find_cmd_user = [
            "find", str(shots_dir),
            "(", *prune_expr, ")", "-prune",
            "-o",
            "-type", "f",
            "-path", "*/user/*",
            "(", "-name", "*.3de", "-o", "-name", "*.3DE", ")",
            "-print",
        ]

        find_cmd_publish_dirs = [
            "find", str(shots_dir),
            "-type", "d",
            "-path", "*/publish/mm",
            "-print",
        ]

        return find_cmd_user, find_cmd_publish_dirs

    def _find_shots_with_published_mm(
        self,
        find_cmd_publish_dirs: list[str],
        cancel_flag: Callable[[], bool] | None,
    ) -> set[tuple[str, str]] | None:
        """Run the publish/mm directory search and return (sequence, shot) pairs.

        Returns:
            Set of (sequence, shot) tuples found, or None if cancelled.

        """
        shots_with_published_mm: set[tuple[str, str]] = set()
        try:
            returncode, stdout, _stderr, status = self._run_subprocess_with_streaming_read(
                find_cmd_publish_dirs, cancel_flag, max_wait_time=30.0
            )

            if status == "cancelled":
                return None

            if returncode == 0 and stdout:
                for line in stdout.strip().split("\n"):
                    if not line:
                        continue
                    dir_path = Path(line)
                    try:
                        # Navigate up: mm -> publish -> SEQUENCE_SHOT -> SEQUENCE
                        shot_dir = dir_path.parent.parent.name
                        sequence = dir_path.parent.parent.parent.name

                        # Delegate to SceneParser.extract_shot_name for single source of truth
                        from scene_parser import SceneParser
                        shot = SceneParser.extract_shot_name(sequence, shot_dir)

                        if shot:
                            shots_with_published_mm.add((sequence, shot))
                            self.logger.debug(f"Found published MM for: {sequence}/{shot}")
                        else:
                            self.logger.debug(f"Skipping empty shot name from: {shot_dir}")
                    except (IndexError, AttributeError) as e:
                        self.logger.debug(f"Could not parse publish/mm path {line}: {e}")

            self.logger.info(
                f"Found {len(shots_with_published_mm)} shots with published matchmove"
            )

        except Exception:
            self.logger.warning("Error finding publish/mm directories", exc_info=True)

        return shots_with_published_mm

    def _filter_to_published_shots(
        self,
        user_results: list[tuple[Path, str, str, str, str, str]],
        shots_with_published_mm: set[tuple[str, str]],
        user_timed_out: bool,
    ) -> list[tuple[Path, str, str, str, str, str]]:
        """Filter user results to only those from shots with published matchmove.

        When no published MM directories are found (either because the show has
        none yet, or because the publish-search failed), the filter falls back to
        returning all user files unfiltered. This avoids hiding valid user work
        in early-stage shows where the publish step hasn't happened yet.

        Returns:
            Filtered list, or all user results if no published shots were found.

        """
        if shots_with_published_mm:
            results = [
                result for result in user_results
                if (result[2], result[3]) in shots_with_published_mm
            ]
            msg_prefix = "Partial results (timeout):" if user_timed_out else "Filtered"
            self.logger.info(
                f"{msg_prefix} {len(user_results)} user files to {len(results)}"
                " from shots with published MM"
            )
            return results

        self.logger.info("No publish/mm directories found - showing all user files")
        return user_results

    def _log_scan_summary(
        self,
        results: list[tuple[Path, str, str, str, str, str]],
        user_results: list[tuple[Path, str, str, str, str, str]],
        user_timed_out: bool,
        elapsed: float,
    ) -> None:
        """Log the final dual-search summary with shot statistics."""
        unique_shots: set[str] = {f"{r[2]}/{r[3]}" for r in results}
        file_count = len(results)

        self.logger.info(
            "=== COMPLETED find_all_3de_files_in_show_targeted (optimized) ==="
        )
        self.logger.info(f"  Found {file_count} .3de files in {elapsed:.2f}s")
        self.logger.info(f"  Unique shots with 3DE files: {len(unique_shots)}")

        if unique_shots:
            sample_shots = list(unique_shots)[:5]
            self.logger.debug(f"  Sample shots: {', '.join(sample_shots)}")

        if user_timed_out:
            self.logger.warning(
                f"Search incomplete (timeout): {len(user_results)} user files found,"
                f" {file_count} files from shots with published MM"
                f" ({len(unique_shots)} shots, {elapsed:.1f}s)"
            )
        else:
            self.logger.info(
                f"Dual search complete: {len(user_results)} user files found,"
                f" {file_count} files from shots with published MM"
                f" ({len(unique_shots)} shots, {elapsed:.1f}s)"
            )

    def find_all_3de_files_in_show_targeted(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[tuple[Path, str, str, str, str, str]]:
        """Find all .3de files using a dual-search strategy.

        Uses two find commands: one for user directories to collect 3DE files,
        and one for publish/mm directories to determine which shots have
        published matchmove. Results are intersected so only user files from
        shots with published MM are returned.

        Args:
            show_root: Root path for shows (e.g., '/shows')
            show: Show name
            excluded_users: Set of usernames to exclude
            cancel_flag: Optional callback that returns True if scan should be cancelled

        Returns:
            List of tuples: (file_path, show, sequence, shot, user, plate)

        """
        self._ensure_parser()

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

        excluded_users = excluded_users or set()
        start_time = time.time()
        results: list[tuple[Path, str, str, str, str, str]] = []
        user_results: list[tuple[Path, str, str, str, str, str]] = []
        user_timed_out = False

        try:
            self.logger.info("Using optimized dual-search strategy for .3de files")

            find_cmd_user, find_cmd_publish_dirs = self._build_find_commands(shots_dir)

            # Search 1: user directories — actual .3de files
            self.logger.debug(f"Search 1 (user): {' '.join(find_cmd_user)}")
            user_results_raw = self._run_find_and_parse(
                find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
            )
            user_timed_out = user_results_raw is None
            user_results = user_results_raw if user_results_raw is not None else []

            if cancel_flag and cancel_flag():
                return []

            # Search 2: publish/mm directories — which shots have published matchmove
            self.logger.debug(f"Search 2 (publish/mm dirs): {' '.join(find_cmd_publish_dirs)}")
            shots_with_mm = self._find_shots_with_published_mm(
                find_cmd_publish_dirs, cancel_flag
            )
            if shots_with_mm is None:  # cancelled
                return []

            results = self._filter_to_published_shots(
                user_results, shots_with_mm, user_timed_out
            )

            if not results:
                self.logger.info(
                    "No results from user directory search, falling back to Python-based search"
                )
                return self._fallback_python_search(shots_dir, show_path, show, excluded_users)

        except Exception:
            self.logger.exception("Error in optimized search")
            self.logger.error(f"Traceback: {traceback.format_exc()}")

        elapsed = time.time() - start_time
        self._log_scan_summary(results, user_results, user_timed_out, elapsed)

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
        self._ensure_parser()
        assert self.parser is not None

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

        except Exception:
            self.logger.exception("Error in Python fallback search")

        elapsed = time.time() - start_time
        self.logger.info(f"Python search found {file_count} files in {elapsed:.2f}s")

        return results
