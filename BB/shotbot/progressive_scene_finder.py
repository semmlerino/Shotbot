"""Progressive 3DE scene finder with generator-based architecture.

This module provides a memory-efficient, cancellable scene discovery system
that yields results progressively for responsive UI updates.
"""

import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator, List, Optional, Set, Tuple

from config import Config
from threede_scene_model import ThreeDEScene
from utils import PathUtils, ValidationUtils

logger = logging.getLogger(__name__)


@dataclass
class ScanProgress:
    """Progress information for scene scanning."""

    total_directories: int = 0
    scanned_directories: int = 0
    total_files: int = 0
    scanned_files: int = 0
    scenes_found: int = 0
    current_path: str = ""
    eta_seconds: float = 0.0
    scan_rate: float = 0.0  # files per second

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_directories > 0:
            return (self.scanned_directories / self.total_directories) * 100
        return 0.0

    def estimate_eta(self) -> float:
        """Estimate time remaining in seconds."""
        if self.scan_rate > 0 and self.total_files > self.scanned_files:
            remaining = self.total_files - self.scanned_files
            return remaining / self.scan_rate
        return 0.0


class DirectoryCache:
    """Cache for directory traversal to avoid repeated filesystem access."""

    def __init__(self, max_size: int = 1000):
        self.cache: dict[str, List[Path]] = {}
        self.access_order = deque(maxlen=max_size)
        self.max_size = max_size

    def get(self, directory: Path) -> Optional[List[Path]]:
        """Get cached directory contents."""
        key = str(directory)
        if key in self.cache:
            # Move to end (most recently used)
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None

    def put(self, directory: Path, contents: List[Path]) -> None:
        """Cache directory contents."""
        key = str(directory)

        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size and key not in self.cache:
            if self.access_order:
                oldest = self.access_order.popleft()
                del self.cache[oldest]

        self.cache[key] = contents
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()
        self.access_order.clear()


class ProgressiveSceneFinder:
    """Progressive 3DE scene finder with cancellation support."""

    # Class-level compiled patterns (same as original)
    import re

    _BG_FG_PATTERN = re.compile(r"^[bf]g\d{2}$", re.IGNORECASE)
    _PLATE_PATTERNS = [
        re.compile(r"^[bf]g\d{2}$", re.IGNORECASE),
        re.compile(r"^plate_?\d+$", re.IGNORECASE),
        re.compile(r"^comp_?\d+$", re.IGNORECASE),
        re.compile(r"^shot_?\d+$", re.IGNORECASE),
        re.compile(r"^sc\d+$", re.IGNORECASE),
        re.compile(r"^[\w]+_v\d{3}$", re.IGNORECASE),
    ]
    _GENERIC_DIRS = {
        "3de",
        "scenes",
        "scene",
        "mm",
        "matchmove",
        "tracking",
        "work",
        "wip",
        "exports",
        "user",
        "files",
        "data",
    }

    def __init__(
        self, batch_size: int = 10, yield_interval: float = 0.05, use_cache: bool = True
    ):
        """Initialize the progressive finder.

        Args:
            batch_size: Number of scenes to collect before yielding
            yield_interval: Minimum time between yields (seconds)
            use_cache: Whether to use directory caching
        """
        self.batch_size = batch_size
        self.yield_interval = yield_interval
        self.use_cache = use_cache
        self.dir_cache = DirectoryCache() if use_cache else None
        self._cancelled = False
        self._start_time = 0.0
        self._files_scanned = 0
        self._last_yield_time = 0.0

    def cancel(self) -> None:
        """Cancel the current scanning operation."""
        self._cancelled = True

    def reset(self) -> None:
        """Reset the finder state."""
        self._cancelled = False
        self._start_time = time.time()
        self._files_scanned = 0
        self._last_yield_time = 0.0
        if self.dir_cache:
            self.dir_cache.clear()

    def find_scenes_progressive(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: Optional[Set[str]] = None,
    ) -> Generator[Tuple[List[ThreeDEScene], ScanProgress], None, None]:
        """Progressively find 3DE scenes for a shot.

        Yields:
            Tuple of (batch of scenes, progress info)
        """
        self.reset()

        # Validate inputs
        if not ValidationUtils.validate_shot_components(show, sequence, shot):
            logger.warning("Invalid shot components provided")
            return

        if not shot_workspace_path:
            logger.warning("Empty shot workspace path provided")
            return

        # Get excluded users
        if excluded_users is None:
            excluded_users = ValidationUtils.get_excluded_users()

        user_dir = PathUtils.build_path(shot_workspace_path, "user")

        if not PathUtils.validate_path_exists(user_dir, "User directory"):
            logger.warning(f"User directory does not exist: {user_dir}")
            return

        # Initialize progress tracking
        progress = ScanProgress()
        progress.current_path = str(user_dir)

        # Count total directories for progress estimation
        try:
            all_user_dirs = [
                d
                for d in user_dir.iterdir()
                if d.is_dir() and d.name not in excluded_users
            ]
            progress.total_directories = len(all_user_dirs)
        except Exception as e:
            logger.error(f"Error counting directories: {e}")
            all_user_dirs = []

        logger.info(
            f"Progressive scan starting: {progress.total_directories} users to scan"
        )

        # Process each user directory
        scene_batch: List[ThreeDEScene] = []

        for user_path in all_user_dirs:
            if self._cancelled:
                logger.info("Scan cancelled by user")
                break

            user_name = user_path.name
            progress.current_path = str(user_path)

            # Scan this user's directory
            for scene in self._scan_user_directory(
                user_path, user_name, show, sequence, shot, shot_workspace_path
            ):
                if self._cancelled:
                    break

                scene_batch.append(scene)
                progress.scenes_found += 1
                self._files_scanned += 1

                # Calculate scan rate
                elapsed = time.time() - self._start_time
                if elapsed > 0:
                    progress.scan_rate = self._files_scanned / elapsed

                # Yield batch if ready
                if len(scene_batch) >= self.batch_size:
                    if self._should_yield():
                        progress.scanned_directories += 1
                        progress.eta_seconds = progress.estimate_eta()
                        yield scene_batch.copy(), progress
                        scene_batch.clear()
                        self._last_yield_time = time.time()

            progress.scanned_directories += 1

        # Yield any remaining scenes
        if scene_batch and not self._cancelled:
            progress.eta_seconds = 0  # Done
            yield scene_batch, progress

    def _should_yield(self) -> bool:
        """Check if enough time has passed to yield."""
        return (time.time() - self._last_yield_time) >= self.yield_interval

    def _scan_user_directory(
        self,
        user_path: Path,
        user_name: str,
        show: str,
        sequence: str,
        shot: str,
        workspace_path: str,
    ) -> Generator[ThreeDEScene, None, None]:
        """Scan a single user directory for 3DE files.

        Yields:
            Individual ThreeDEScene objects as found
        """
        try:
            # Use cache if available
            if self.dir_cache:
                threede_files = self._get_cached_3de_files(user_path)
            else:
                threede_files = list(user_path.rglob("*.3de"))

            for threede_file in threede_files:
                if self._cancelled:
                    break

                # Skip if not accessible
                if not self._verify_scene_exists(threede_file):
                    continue

                # Extract plate info
                plate = self._extract_plate_from_path(threede_file, user_path)

                # Create scene object
                scene = ThreeDEScene(
                    show=show,
                    sequence=sequence,
                    shot=shot,
                    workspace_path=workspace_path,
                    user=user_name,
                    plate=plate,
                    scene_path=threede_file,
                )

                yield scene

        except PermissionError:
            logger.warning(f"Permission denied accessing {user_name} directory")
        except Exception as e:
            logger.error(f"Error scanning user {user_name}: {e}")

    def _get_cached_3de_files(self, directory: Path) -> List[Path]:
        """Get 3DE files with caching."""
        cached = self.dir_cache.get(directory)
        if cached is not None:
            return [f for f in cached if f.suffix.lower() == ".3de"]

        # Scan and cache
        try:
            all_files = list(directory.rglob("*"))
            self.dir_cache.put(directory, all_files)
            return [f for f in all_files if f.suffix.lower() == ".3de"]
        except Exception as e:
            logger.debug(f"Error caching directory {directory}: {e}")
            return []

    def _verify_scene_exists(self, scene_path: Path) -> bool:
        """Quick verification that scene file exists."""
        try:
            return scene_path.is_file() and os.access(scene_path, os.R_OK)
        except (OSError, PermissionError):
            return False

    def _extract_plate_from_path(self, file_path: Path, user_path: Path) -> str:
        """Extract plate identifier (same logic as original)."""
        try:
            relative_path = file_path.relative_to(user_path)
            path_parts = relative_path.parts

            # Check for BG/FG patterns
            for part in path_parts[:-1]:
                if self._BG_FG_PATTERN.match(part):
                    return part

            # Check other patterns
            for part in path_parts[:-1]:
                for pattern in self._PLATE_PATTERNS:
                    if pattern.match(part):
                        return part

            # Find non-generic directory
            for part in reversed(path_parts[:-1]):
                if part.lower() not in self._GENERIC_DIRS:
                    return part

            return file_path.parent.name

        except ValueError:
            return file_path.parent.name


class ShowWideProgressiveFinder:
    """Progressive finder for show-wide scene discovery."""

    def __init__(self, finder: Optional[ProgressiveSceneFinder] = None):
        """Initialize with an optional finder instance."""
        self.finder = finder or ProgressiveSceneFinder()
        self._cancelled = False

    def cancel(self) -> None:
        """Cancel the current operation."""
        self._cancelled = True
        self.finder.cancel()

    def find_all_scenes_progressive(
        self, user_shots: List[Any], excluded_users: Optional[Set[str]] = None
    ) -> Generator[Tuple[List[ThreeDEScene], ScanProgress], None, None]:
        """Progressively find scenes across all shots in shows.

        Args:
            user_shots: User's assigned shots
            excluded_users: Users to exclude

        Yields:
            Tuple of (batch of scenes, progress info)
        """
        if not user_shots:
            logger.info("No user shots provided for show-wide search")
            return

        # Check if enabled
        if hasattr(Config, "SHOW_SEARCH_ENABLED") and not Config.SHOW_SEARCH_ENABLED:
            logger.info("Show-wide search disabled")
            # Fall back to user's shots only
            for shot in user_shots:
                if self._cancelled:
                    break
                yield from self.finder.find_scenes_progressive(
                    shot.workspace_path,
                    shot.show,
                    shot.sequence,
                    shot.shot,
                    excluded_users,
                )
            return

        # Extract shows to search
        shows_to_search = set()
        show_roots = set()

        for shot in user_shots:
            shows_to_search.add(shot.show)
            workspace_parts = Path(shot.workspace_path).parts
            if "shows" in workspace_parts:
                shows_idx = workspace_parts.index("shows")
                show_root = "/".join(workspace_parts[: shows_idx + 1])
                show_roots.add(show_root)

        if not show_roots:
            configured_roots = getattr(Config, "SHOW_ROOT_PATHS", ["/shows"])
            show_roots = set(configured_roots)

        # Discover and scan all shots
        total_progress = ScanProgress()

        for show_root in show_roots:
            if self._cancelled:
                break

            for show in shows_to_search:
                if self._cancelled:
                    break

                # Discover shots in show
                all_shots = self._discover_all_shots_in_show(show_root, show)

                if not all_shots:
                    continue

                total_progress.total_directories += len(all_shots)

                # Scan each shot progressively
                for workspace_path, show_name, sequence, shot in all_shots:
                    if self._cancelled:
                        break

                    # Scan this shot
                    for batch, progress in self.finder.find_scenes_progressive(
                        workspace_path, show_name, sequence, shot, excluded_users
                    ):
                        if self._cancelled:
                            break

                        # Aggregate progress
                        total_progress.scenes_found += len(batch)
                        total_progress.scanned_directories += 1
                        total_progress.current_path = progress.current_path
                        total_progress.scan_rate = progress.scan_rate

                        yield batch, total_progress

    def _discover_all_shots_in_show(
        self, show_root: str, show: str
    ) -> List[Tuple[str, str, str, str]]:
        """Discover all shots in a show."""
        shots = []
        show_path = Path(show_root) / show / "shots"

        if not show_path.exists():
            return shots

        try:
            max_shots = getattr(Config, "MAX_SHOTS_PER_SHOW", 1000)
            shot_count = 0

            for sequence_dir in show_path.iterdir():
                if not sequence_dir.is_dir():
                    continue

                if sequence_dir.name.startswith("."):
                    continue

                for shot_dir in sequence_dir.iterdir():
                    if not shot_dir.is_dir():
                        continue

                    user_dir = shot_dir / "user"
                    if user_dir.exists():
                        shots.append(
                            (str(shot_dir), show, sequence_dir.name, shot_dir.name)
                        )
                        shot_count += 1

                        if shot_count >= max_shots:
                            return shots

        except Exception as e:
            logger.error(f"Error discovering shots: {e}")

        return shots
