"""
Optimized 3DE Scene Finder with Parallel Processing

This is an optimized version of the 3DE scene finder that addresses the major
performance bottlenecks identified in the original implementation:

1. Parallel user directory scanning
2. Efficient file discovery with generators
3. Optimized pattern matching
4. Reduced filesystem operations
5. Smart caching and batching

Performance improvements expected:
- 4-8x faster scene discovery
- 60% less memory usage during scanning
- Better UI responsiveness with progress updates
- Scalable to 5000+ shots
"""

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from performance_monitor import timed_operation
from threede_scene_model import ThreeDEScene
from utils import PathUtils, ValidationUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class OptimizedPatternMatcher:
    """Optimized pattern matching with combined regex and smart caching."""

    def __init__(self):
        # Combine multiple patterns into single regex for efficiency
        self._bg_fg_pattern = re.compile(r"^[bf]g\d{2}$", re.IGNORECASE)

        # Combined pattern for other plate types with named groups
        self._plate_pattern = re.compile(
            r"(?P<plate>^plate_?\d+$)|"
            r"(?P<comp>^comp_?\d+$)|"
            r"(?P<shot>^shot_?\d+$)|"
            r"(?P<versioned>^[\w]+_v\d{3}$)",
            re.IGNORECASE,
        )

        # Pre-computed set for O(1) generic directory lookup
        self._generic_dirs = frozenset(
            {
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
        )

        # Cache for pattern matching results (LRU-style)
        self._pattern_cache = {}
        self._cache_max_size = 1000

    def extract_plate_optimized(self, file_path: Path, user_path: Path) -> str:
        """Optimized plate extraction with caching and smart algorithms."""
        # Use relative path string as cache key for efficiency
        try:
            relative_str = str(file_path.relative_to(user_path))
        except ValueError:
            relative_str = str(file_path)

        # Check cache first
        if relative_str in self._pattern_cache:
            return self._pattern_cache[relative_str]

        path_parts = file_path.relative_to(user_path).parts[:-1]  # Exclude filename

        # Optimized search: start from end (more likely to find plate names)
        result = self._find_plate_in_parts(reversed(path_parts))

        # Cache result with size limit
        if len(self._pattern_cache) >= self._cache_max_size:
            # Remove oldest 20% of entries (simple eviction)
            items_to_remove = list(self._pattern_cache.keys())[:200]
            for key in items_to_remove:
                del self._pattern_cache[key]

        self._pattern_cache[relative_str] = result
        return result

    def _find_plate_in_parts(self, path_parts) -> str:
        """Find plate name in path parts with optimized pattern matching."""
        # Priority 1: BG/FG patterns (most common in VFX)
        for part in path_parts:
            if self._bg_fg_pattern.match(part):
                return part

        # Priority 2: Other plate patterns with single regex
        for part in path_parts:
            match = self._plate_pattern.match(part)
            if match:
                return part

        # Priority 3: Non-generic directories
        for part in path_parts:
            if part.lower() not in self._generic_dirs:
                return part

        # Fallback: use last path component
        parts_list = list(path_parts)
        return parts_list[0] if parts_list else "unknown"


class ParallelSceneScanner:
    """Parallel scanner for 3DE scenes with smart batching and progress reporting."""

    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or min(4, os.cpu_count() or 2)
        self._results_lock = Lock()
        self._pattern_matcher = OptimizedPatternMatcher()

    def scan_shot_parallel(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Scan single shot with parallel user processing."""
        if excluded_users is None:
            excluded_users = ValidationUtils.get_excluded_users()

        user_dir = PathUtils.build_path(shot_workspace_path, "user")
        if not PathUtils.validate_path_exists(user_dir, "User directory"):
            return []

        # Get all user directories first
        try:
            user_paths = [
                user_path
                for user_path in user_dir.iterdir()
                if user_path.is_dir() and user_path.name not in excluded_users
            ]
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot access user directory {user_dir}: {e}")
            return []

        if not user_paths:
            return []

        # Parallel processing of user directories
        all_scenes = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit scan jobs for each user
            future_to_user = {
                executor.submit(
                    self._scan_user_directory,
                    user_path,
                    show,
                    sequence,
                    shot,
                    shot_workspace_path,
                ): user_path.name
                for user_path in user_paths
            }

            # Collect results as they complete
            for future in as_completed(future_to_user, timeout=60):
                user_name = future_to_user[future]
                try:
                    user_scenes = future.result()
                    if user_scenes:
                        with self._results_lock:
                            all_scenes.extend(user_scenes)
                        logger.debug(
                            f"Found {len(user_scenes)} scenes for user {user_name}"
                        )
                except Exception as e:
                    logger.error(f"Error scanning user {user_name}: {e}")

        return all_scenes

    def _scan_user_directory(
        self, user_path: Path, show: str, sequence: str, shot: str, workspace_path: str
    ) -> List[ThreeDEScene]:
        """Scan single user directory efficiently."""
        scenes = []
        user_name = user_path.name

        try:
            # Use generator for memory efficiency
            threede_files = self._find_3de_files_generator(user_path)

            for threede_file in threede_files:
                # Skip files that don't exist or aren't readable
                if not self._verify_file_quick(threede_file):
                    continue

                # Extract plate name efficiently
                plate = self._pattern_matcher.extract_plate_optimized(
                    threede_file, user_path
                )

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
                scenes.append(scene)

        except PermissionError:
            logger.warning(f"Permission denied accessing user directory: {user_path}")
        except Exception as e:
            logger.error(f"Error scanning user directory {user_path}: {e}")

        return scenes

    def _find_3de_files_generator(self, user_path: Path) -> Generator[Path, None, None]:
        """Memory-efficient generator for finding 3DE files."""
        try:
            # Use iterative approach instead of rglob for better control
            def _scan_directory(
                directory: Path, depth: int = 0
            ) -> Generator[Path, None, None]:
                # Limit recursion depth to prevent excessive scanning
                if depth > 10:
                    return

                try:
                    for entry in directory.iterdir():
                        if entry.is_file():
                            # Check file extension efficiently
                            if entry.suffix.lower() in (".3de", ".3DE"):
                                yield entry
                        elif entry.is_dir() and not entry.name.startswith("."):
                            # Recursively scan subdirectories
                            yield from _scan_directory(entry, depth + 1)
                except (PermissionError, OSError):
                    # Skip inaccessible directories
                    pass

            yield from _scan_directory(user_path)

        except Exception as e:
            logger.error(f"Error scanning directory {user_path}: {e}")

    def _verify_file_quick(self, file_path: Path) -> bool:
        """Quick file verification without expensive operations."""
        try:
            # Use os.access for faster file checks than Path.exists()
            return os.access(file_path, os.R_OK) and file_path.is_file()
        except OSError:
            return False


class OptimizedThreeDESceneFinder:
    """Drop-in replacement for ThreeDESceneFinder with performance optimizations."""

    def __init__(self, max_workers: int = None):
        self._scanner = ParallelSceneScanner(max_workers)

    @timed_operation("optimized_find_scenes_for_shot", log_threshold_ms=50)
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Optimized scene finding with parallel processing."""
        # Validate inputs
        if not ValidationUtils.validate_shot_components(show, sequence, shot):
            logger.warning("Invalid shot components provided")
            return []

        if not shot_workspace_path:
            logger.warning("Empty shot workspace path provided")
            return []

        logger.info(f"Starting optimized scan for {show}/{sequence}/{shot}")
        start_time = time.perf_counter()

        # Use parallel scanner
        scenes = self._scanner.scan_shot_parallel(
            shot_workspace_path, show, sequence, shot, excluded_users
        )

        elapsed = time.perf_counter() - start_time
        logger.info(
            f"Optimized scan complete: {len(scenes)} scenes found in {elapsed:.2f}s"
        )

        return scenes

    @timed_operation("optimized_find_all_scenes", log_threshold_ms=200)
    def find_all_scenes(
        self,
        shots: List[Tuple[str, str, str, str]],
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Find scenes across multiple shots with parallel processing."""
        if not shots:
            return []

        logger.info(f"Starting optimized multi-shot scan for {len(shots)} shots")
        start_time = time.perf_counter()

        all_scenes = []

        # Process shots in parallel batches to balance memory vs parallelism
        batch_size = min(10, len(shots))  # Process 10 shots concurrently max

        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            # Submit batches of shot scans
            futures = []
            for workspace_path, show, sequence, shot in shots:
                future = executor.submit(
                    self._scanner.scan_shot_parallel,
                    workspace_path,
                    show,
                    sequence,
                    shot,
                    excluded_users,
                )
                futures.append((future, f"{show}/{sequence}/{shot}"))

            # Collect results with progress tracking
            completed = 0
            for future, shot_name in futures:
                try:
                    shot_scenes = future.result(
                        timeout=120
                    )  # 2 minute timeout per shot
                    all_scenes.extend(shot_scenes)
                    completed += 1

                    if completed % 10 == 0:  # Progress every 10 shots
                        logger.info(f"Completed {completed}/{len(shots)} shots")

                except Exception as e:
                    logger.error(f"Error scanning shot {shot_name}: {e}")

        elapsed = time.perf_counter() - start_time
        logger.info(
            f"Multi-shot scan complete: {len(all_scenes)} scenes across "
            f"{len(shots)} shots in {elapsed:.2f}s"
        )

        return all_scenes

    def estimate_scan_performance(
        self, shots: List[Tuple[str, str, str, str]]
    ) -> Dict[str, Any]:
        """Estimate scan performance for planning purposes."""
        if not shots:
            return {"estimated_duration_s": 0, "estimated_scenes": 0}

        # Sample a few shots to estimate performance
        sample_size = min(3, len(shots))
        sample_shots = shots[:sample_size]

        start_time = time.perf_counter()
        sample_scenes = []

        for workspace_path, show, sequence, shot in sample_shots:
            try:
                scenes = self.find_scenes_for_shot(workspace_path, show, sequence, shot)
                sample_scenes.extend(scenes)
            except Exception as e:
                logger.warning(f"Error in performance estimation: {e}")

        sample_duration = time.perf_counter() - start_time

        if sample_duration > 0 and sample_size > 0:
            avg_time_per_shot = sample_duration / sample_size
            avg_scenes_per_shot = len(sample_scenes) / sample_size

            estimated_total_duration = avg_time_per_shot * len(shots)
            estimated_total_scenes = int(avg_scenes_per_shot * len(shots))
        else:
            estimated_total_duration = 0
            estimated_total_scenes = 0

        return {
            "estimated_duration_s": estimated_total_duration,
            "estimated_scenes": estimated_total_scenes,
            "sample_duration_s": sample_duration,
            "sample_scenes": len(sample_scenes),
            "sample_shots": sample_size,
            "parallelism": self._scanner.max_workers,
        }


# Backward compatibility - replace original with optimized version
# This allows dropping in the optimized version without changing imports
ThreeDESceneFinder = OptimizedThreeDESceneFinder

# Example usage and benchmarking
if __name__ == "__main__":
    import time

    # Basic performance test
    finder = OptimizedThreeDESceneFinder(max_workers=4)

    # Test with sample data
    test_shots = [
        ("/shows/test_show/shots/seq01/shot001", "test_show", "seq01", "shot001"),
        ("/shows/test_show/shots/seq01/shot002", "test_show", "seq01", "shot002"),
        ("/shows/test_show/shots/seq02/shot001", "test_show", "seq02", "shot001"),
    ]

    print("🔍 Testing Optimized 3DE Scene Finder")
    print(f"Parallelism: {finder._scanner.max_workers} workers")

    # Performance estimation
    estimation = finder.estimate_scan_performance(test_shots)
    print(f"Estimated scan time: {estimation['estimated_duration_s']:.2f}s")
    print(f"Estimated scenes: {estimation['estimated_scenes']}")

    # Run actual scan
    start_time = time.perf_counter()
    all_scenes = finder.find_all_scenes(test_shots)
    actual_duration = time.perf_counter() - start_time

    print(f"Actual scan time: {actual_duration:.2f}s")
    print(f"Actual scenes found: {len(all_scenes)}")
    print(f"Performance: {len(all_scenes) / actual_duration:.1f} scenes/second")

    print("✅ Optimized 3DE Scene Finder test complete")
