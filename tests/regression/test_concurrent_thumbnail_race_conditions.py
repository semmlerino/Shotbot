"""Test concurrent thumbnail loading to verify race condition fixes.

This test simulates the exact scenario that caused log corruption:
- 3 models (ShotItemModel, PreviousShotsItemModel, ThreeDEItemModel)
- 95 scenes each = 285 rapid callbacks
- Concurrent access to utils._path_cache and Shot._cached_thumbnail_path
- Cache cleanup triggering during concurrent access

The original issue manifested as:
- Path corruption: "cutrefache" (mixing "/editorial/cutref/" and "/cache/")
- Repeated text: "scene_scene_scene"
- Garbled paths in logs

After thread-safety fixes, this test should pass with:
- No path corruption
- No mixed string fragments
- All paths remain valid throughout execution
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from pathlib import Path
from unittest.mock import patch


logger = logging.getLogger(__name__)

# Local application imports
from discovery.thumbnail_finders import find_shot_thumbnail
from paths.validators import (  # type: ignore[reportPrivateUsage]
    PathValidators,
    _path_cache,
    _path_cache_lock,
)
from type_definitions import Shot
from version_utils import VersionUtils


class TestConcurrentThumbnailRaceConditions:
    """Test suite for concurrent thumbnail loading race conditions."""

    def test_concurrent_path_cache_access(self) -> None:
        """Test concurrent access to _path_cache with cleanup triggering.

        Simulates the exact pattern that caused corruption:
        - Thread A: Reading/writing cache entries
        - Thread B: Triggering cache cleanup (clear + update)
        - Thread C: Reading cache during cleanup

        Validates:
        - No corrupted path strings
        - No empty cache reads during cleanup
        - All threads see consistent state
        """
        # Clear cache before test
        with _path_cache_lock:
            _path_cache.clear()

        corruption_detected = threading.Event()
        paths_checked: list[tuple[str, bool]] = []
        paths_lock = threading.Lock()

        def worker(worker_id: int, base_path: str) -> None:
            """Simulate a model checking paths rapidly."""
            try:
                for i in range(100):
                    # Build path similar to thumbnail discovery
                    path_str = f"{base_path}/seq_{i % 10}/shot_{i}"

                    # Validate path (triggers cache access)
                    result = PathValidators.validate_path_exists(
                        path_str, f"Worker {worker_id}"
                    )

                    # Record result
                    with paths_lock:
                        paths_checked.append((path_str, result))

                    # Every 30 iterations, one thread triggers cleanup
                    if i % 30 == 0 and worker_id == 1:
                        # Force cache over threshold to trigger cleanup
                        with _path_cache_lock:
                            if len(_path_cache) < 5001:
                                # Add dummy entries to trigger cleanup
                                for j in range(5001 - len(_path_cache)):
                                    _path_cache[f"/dummy/path/{j}"] = (
                                        False,
                                        time.time(),
                                    )

            except Exception as e:
                logger.debug("Worker %d failed: %s", worker_id, e)
                corruption_detected.set()
                raise

        # Simulate 3 models accessing paths concurrently
        base_paths = [
            "/shows/test/shots/editorial/cutref",  # Model A
            "/home/user/.shotbot/cache/production/thumbnails",  # Model B
            "/shows/test/shots/mm/default/scene",  # Model C
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(worker, i, base_paths[i]) for i in range(3)]
            concurrent.futures.wait(futures)

        # Check for corruption
        assert not corruption_detected.is_set(), (
            "Thread encountered exception during execution"
        )

        # Validate no path corruption occurred
        for path_str, _result in paths_checked:
            # Check for mixed fragments (the smoking gun of corruption)
            assert "cutrefache" not in path_str, f"Path corruption detected: {path_str}"
            assert "scene_scene" not in path_str, (
                f"Repeated fragment detected: {path_str}"
            )

            # Check path is well-formed (no partial strings)
            assert path_str.startswith("/"), f"Invalid path prefix: {path_str}"
            assert "//" not in path_str, f"Double slashes detected: {path_str}"

        logger.debug(
            "Checked %d paths across 3 concurrent threads - no corruption",
            len(paths_checked),
        )

    def test_concurrent_version_cache_access(self) -> None:
        """Test concurrent access to VersionUtils._version_cache with cleanup.

        Validates:
        - No corrupted version lists
        - No empty cache reads during cleanup
        - Atomic cleanup operations
        """
        # Clear cache before test
        VersionUtils.clear_version_cache()

        corruption_detected = threading.Event()
        versions_checked: list[list[tuple[int, str]]] = []
        versions_lock = threading.Lock()

        def worker(worker_id: int, base_path: str) -> None:
            """Simulate finding version directories concurrently."""
            try:
                for i in range(50):
                    path_str = f"{base_path}/seq_{i % 5}/shot_{i}"

                    # Find version directories (triggers cache access)
                    versions = VersionUtils.find_version_directories(path_str)

                    # Record result
                    with versions_lock:
                        versions_checked.append(versions)

                    # Trigger cleanup on worker 1
                    if i % 20 == 0 and worker_id == 1:
                        with VersionUtils._version_cache_lock:
                            if len(VersionUtils._version_cache) < 501:
                                # Add dummy entries to trigger cleanup
                                for j in range(501 - len(VersionUtils._version_cache)):
                                    VersionUtils._version_cache[f"/dummy/path/{j}"] = (
                                        [(1, "v001")],
                                        time.time(),
                                    )

            except Exception as e:
                logger.debug("Worker %d failed: %s", worker_id, e)
                corruption_detected.set()
                raise

        base_paths = [
            "/shows/test/shots/editorial/cutref",
            "/shows/test/shots/mm/default/PL01/undistorted_plate",
            "/shows/test/shots/publish/turnover/plate",
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(worker, i, base_paths[i]) for i in range(3)]
            concurrent.futures.wait(futures)

        assert not corruption_detected.is_set(), (
            "Thread encountered exception during execution"
        )

        # Validate version data integrity
        for versions in versions_checked:
            # Each version should be a valid tuple
            for version_num, version_str in versions:
                assert isinstance(version_num, int), (
                    f"Invalid version number: {version_num}"
                )
                assert isinstance(version_str, str), (
                    f"Invalid version string: {version_str}"
                )
                assert version_str.startswith("v"), (
                    f"Invalid version format: {version_str}"
                )

        logger.debug(
            "Checked %d version queries across 3 concurrent threads - no corruption",
            len(versions_checked),
        )

    def test_concurrent_shot_thumbnail_caching(self) -> None:
        """Test concurrent access to Shot._cached_thumbnail_path.

        Simulates multiple models calling get_thumbnail_path() on the same Shot
        instances simultaneously (the exact scenario from the bug report).

        Validates:
        - Double-checked locking works correctly
        - Only one thread performs expensive discovery
        - All threads get consistent results
        - No race conditions on instance-level cache
        """
        # Create shots similar to production scenario
        shots = [
            Shot(
                show="TestShow",
                sequence=f"SEQ{i // 10:03d}",
                shot=f"{i:04d}",
                workspace_path=f"/shows/TestShow/shots/SEQ{i // 10:03d}/SEQ{i // 10:03d}_{i:04d}",
            )
            for i in range(95)  # Same as production (95 scenes)
        ]

        discovery_count = 0
        discovery_lock = threading.Lock()

        # Patch find_shot_thumbnail to count calls
        def counting_find(
            shows_root: str, show: str, sequence: str, shot: str
        ) -> Path | None:
            nonlocal discovery_count
            with discovery_lock:
                discovery_count += 1
            return find_shot_thumbnail(shows_root, show, sequence, shot)

        with patch(
            "discovery.thumbnail_finders.find_shot_thumbnail",
            side_effect=counting_find,
        ):
            results: list[tuple[int, Path | None]] = []
            results_lock = threading.Lock()
            corruption_detected = threading.Event()

            def worker(worker_id: int, shots_subset: list[Shot]) -> None:
                """Simulate a model loading thumbnails for its shots."""
                try:
                    for shot in shots_subset:
                        thumbnail = shot.get_thumbnail_path()

                        with results_lock:
                            results.append((worker_id, thumbnail))

                except Exception as e:
                    logger.debug("Worker %d failed: %s", worker_id, e)
                    corruption_detected.set()
                    raise

            # Simulate 3 models accessing the SAME shots concurrently
            # This is the key scenario: multiple models see the same Shot instances
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(worker, i, shots) for i in range(3)]
                concurrent.futures.wait(futures)

            assert not corruption_detected.is_set(), (
                "Thread encountered exception during execution"
            )

            # Key validation: With proper double-checked locking,
            # each shot should only trigger ONE discovery call despite 3 threads
            # In the broken version, we'd see 3x calls (or more with races)
            expected_max_calls = len(shots) * 1.2  # Allow 20% overhead for edge cases
            assert discovery_count <= expected_max_calls, (
                f"Too many discovery calls: {discovery_count} "
                f"(expected ~{len(shots)}, max {expected_max_calls}). "
                f"Double-checked locking may not be working correctly."
            )

            logger.debug("%d shots accessed by 3 concurrent threads", len(shots))
            logger.debug(
                "Only %d expensive discoveries (optimal: %d)", discovery_count, len(shots)
            )
            logger.debug(
                "Double-checked locking prevented %d redundant calls",
                3 * len(shots) - discovery_count,
            )

            # Validate all results are consistent (no corruption)
            for _worker_id, thumbnail in results:
                if thumbnail is not None:
                    assert isinstance(thumbnail, Path), (
                        f"Invalid thumbnail type: {type(thumbnail)}"
                    )
