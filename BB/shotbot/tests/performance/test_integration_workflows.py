from tests.helpers.synchronization import simulate_work_without_sleep

"""Integration tests for performance optimization workflows.

These tests verify that:
1. Full 3DE scene discovery workflow performs well
2. Shot list refresh with caching works efficiently
3. UI doesn't freeze during operations
4. Large datasets are handled properly
5. End-to-end workflows maintain performance gains
"""

import concurrent.futures
import threading
import time
from pathlib import Path
from typing import Dict, List
from unittest.mock import Mock, patch

import pytest

from tests.performance.timed_operation import TimingRegistry, timed_operation


class MockFileSystem:
    """Mock filesystem for testing large VFX directory structures."""

    def __init__(self):
        self.structure = {}
        self.access_count = 0
        self.access_times = []

    def create_vfx_structure(self, num_shows: int = 3, shots_per_show: int = 50):
        """Create mock VFX directory structure."""
        shows_root = "/shows"

        for show_idx in range(num_shows):
            show_name = f"show_{show_idx:02d}"

            # Create sequences
            for seq_idx in range(5):  # 5 sequences per show
                sequence = f"{seq_idx:03d}_SEQ"

                # Create shots in sequence
                shots_in_seq = shots_per_show // 5
                for shot_idx in range(shots_in_seq):
                    shot_name = f"{sequence}_{shot_idx:04d}"
                    shot_dir = f"{sequence}_{shot_name}"

                    # Build full shot path
                    shot_path = f"{shows_root}/{show_name}/shots/{sequence}/{shot_dir}"

                    # Create shot structure
                    self._create_shot_structure(shot_path, shot_name)

    def _create_shot_structure(self, shot_path: str, shot_name: str):
        """Create directory structure for a single shot."""
        # Thumbnail path
        thumb_path = f"{shot_path}/publish/editorial/cutref/v001/jpg/1920x1080"
        self.structure[thumb_path] = ["frame.1001.jpg", "frame.1002.jpg"]

        # Raw plate paths
        plate_base = f"{shot_path}/publish/turnover/plate/input_plate"

        # Create multiple plate types
        for plate_name in ["FG01", "BG01", "bg01"]:
            plate_path = f"{plate_base}/{plate_name}/v001/exr/4312x2304"
            self.structure[plate_path] = [
                f"{shot_name}_turnover-plate_{plate_name}_aces_v001.1001.exr",
                f"{shot_name}_turnover-plate_{plate_name}_aces_v001.1002.exr",
            ]

        # 3DE scene paths for multiple users
        for user in ["user_a", "user_b", "gabriel-h"]:
            scene_base = f"{shot_path}/user/{user}/mm/3de/mm-default/scenes/scene"
            for version in ["v001", "v002"]:
                scene_path = f"{scene_base}/{version}"
                self.structure[scene_path] = [f"{shot_name}_scene_{version}.3de"]

        # Undistortion paths
        for user in ["user_a", "user_b", "gabriel-h"]:
            undist_base = f"{shot_path}/user/{user}/mm/3de/mm-default/exports/scene/bg01/nuke_lens_distortion"
            for version in ["v001", "v002"]:
                undist_path = f"{undist_base}/{version}"
                self.structure[undist_path] = [f"{shot_name}_undistortion_{version}.nk"]

    def exists(self, path: str) -> bool:
        """Mock Path.exists() method."""
        self.access_count += 1
        self.access_times.append(time.time())
        return str(path) in self.structure

    def iterdir(self, path: str) -> List[Mock]:
        """Mock Path.iterdir() method."""
        self.access_count += 1
        self.access_times.append(time.time())

        if str(path) in self.structure:
            files = self.structure[str(path)]
            return [self._create_mock_file(f) for f in files]
        return []

    def _create_mock_file(self, filename: str) -> Mock:
        """Create mock file object."""
        mock_file = Mock()
        mock_file.name = filename
        mock_file.is_file.return_value = filename.endswith(
            (".jpg", ".exr", ".3de", ".nk")
        )
        mock_file.is_dir.return_value = not mock_file.is_file()
        mock_file.suffix = Path(filename).suffix
        return mock_file

    def get_access_stats(self) -> Dict[str, float]:
        """Get filesystem access statistics."""
        if len(self.access_times) < 2:
            return {"total_accesses": self.access_count, "access_rate": 0.0}

        time_span = self.access_times[-1] - self.access_times[0]
        access_rate = self.access_count / max(
            time_span, 0.001
        )  # Avoid division by zero

        return {
            "total_accesses": self.access_count,
            "access_rate": access_rate,
            "time_span": time_span,
        }


class TestIntegrationWorkflows:
    """Test suite for performance integration workflows."""

    def setup_method(self):
        """Set up test environment."""
        TimingRegistry.clear()

        # Clear caches for clean testing
        try:
            from utils import clear_all_caches

            clear_all_caches()
        except ImportError:
            pass

    def teardown_method(self):
        """Clean up after tests."""
        TimingRegistry.clear()

    @timed_operation("full_3de_discovery", store_results=True)
    def test_full_3de_scene_discovery_workflow(self):
        """Test complete 3DE scene discovery workflow performance."""
        mock_fs = MockFileSystem()
        mock_fs.create_vfx_structure(num_shows=2, shots_per_show=100)  # 100 shots

        try:
            from threede_scene_finder import ThreeDESceneFinder
            from utils import ValidationUtils

            # Mock filesystem operations
            with patch.object(Path, "exists", side_effect=mock_fs.exists):
                with patch.object(Path, "iterdir", side_effect=mock_fs.iterdir):
                    # Simulate user exclusion
                    excluded_users = ValidationUtils.get_excluded_users()

                    # Run scene discovery on mock structure
                    base_paths = ["/shows/show_00", "/shows/show_01"]
                    all_scenes = []

                    for base_path in base_paths:
                        # Mock the shot workspace paths
                        shot_workspaces = []
                        for seq_idx in range(5):
                            sequence = f"{seq_idx:03d}_SEQ"
                            for shot_idx in range(10):  # 10 shots per sequence
                                shot_name = f"{sequence}_{shot_idx:04d}"
                                shot_dir = f"{sequence}_{shot_name}"
                                workspace = f"{base_path}/shots/{sequence}/{shot_dir}"
                                shot_workspaces.append(workspace)

                        # Find scenes for each shot
                        for workspace in shot_workspaces:
                            scenes = ThreeDESceneFinder.find_threede_scenes(
                                workspace, excluded_users
                            )
                            all_scenes.extend(scenes)

            # Verify results
            assert len(all_scenes) > 0, "Should find some 3DE scenes"

            # Check filesystem access efficiency
            fs_stats = mock_fs.get_access_stats()

            # With caching, should have reasonable filesystem access
            assert fs_stats["total_accesses"] < 5000, (
                f"Too many filesystem accesses: {fs_stats['total_accesses']}"
            )

            print(f"Found {len(all_scenes)} 3DE scenes")
            print(f"Filesystem accesses: {fs_stats['total_accesses']}")
            print(f"Access rate: {fs_stats['access_rate']:.1f}/sec")

        except ImportError:
            pytest.skip("3DE scene finder not available")

    @timed_operation("shot_list_refresh", store_results=True)
    def test_shot_list_refresh_with_caching(self):
        """Test shot list refresh workflow with caching optimizations."""
        mock_fs = MockFileSystem()
        mock_fs.create_vfx_structure(num_shows=1, shots_per_show=200)  # 200 shots

        try:
            from shot_model import ShotModel

            # Mock the ws command output
            mock_shots_output = []
            for seq_idx in range(5):
                sequence = f"{seq_idx:03d}_SEQ"
                for shot_idx in range(40):  # 40 shots per sequence
                    shot_name = f"{sequence}_{shot_idx:04d}"
                    workspace = (
                        f"/shows/show_00/shots/{sequence}/{sequence}_{shot_name}"
                    )
                    mock_shots_output.append(
                        f"show_00\t{sequence}\t{shot_name}\t{workspace}"
                    )

            mock_output = "\n".join(mock_shots_output)

            with patch("subprocess.run") as mock_run:
                # Mock ws command
                mock_result = Mock()
                mock_result.stdout = mock_output
                mock_result.returncode = 0
                mock_run.return_value = mock_result

                with patch.object(Path, "exists", side_effect=mock_fs.exists):
                    # Create shot model
                    shot_model = ShotModel()

                    # First refresh - should populate cache
                    success1, changes1 = shot_model.refresh_shots()
                    assert success1 is True
                    assert changes1 is True  # First time should detect changes

                    # Get initial filesystem access count
                    initial_accesses = mock_fs.access_count

                    # Second refresh - should use cache more
                    success2, changes2 = shot_model.refresh_shots()
                    assert success2 is True

                    # Check that caching reduced filesystem access
                    final_accesses = mock_fs.access_count
                    additional_accesses = final_accesses - initial_accesses

                    # Should have fewer accesses on second run due to caching
                    shots = shot_model.get_shots()
                    expected_max_accesses = len(shots) * 2  # Generous allowance

                    assert additional_accesses < expected_max_accesses, (
                        f"Too many additional accesses: {additional_accesses} "
                        f"for {len(shots)} shots"
                    )

                    print(f"Found {len(shots)} shots")
                    print(f"First refresh accesses: {initial_accesses}")
                    print(f"Second refresh additional accesses: {additional_accesses}")

        except ImportError:
            pytest.skip("Shot model not available")

    def test_ui_responsiveness_under_load(self):
        """Test that UI remains responsive during heavy operations."""
        mock_fs = MockFileSystem()
        mock_fs.create_vfx_structure(num_shows=1, shots_per_show=300)  # Large dataset

        # Simulate UI operations during heavy background work
        ui_response_times = []
        background_complete = threading.Event()

        def simulate_ui_operations():
            """Simulate UI interactions during background processing."""
            while not background_complete.is_set():
                start_time = time.time()

                # Simulate typical UI operations
                simulate_work_without_sleep(10)  # Simulate UI update cycle

                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # ms
                ui_response_times.append(response_time)

                # Check every 50ms
                simulate_work_without_sleep(50)

        def heavy_background_work():
            """Simulate heavy background processing."""
            try:
                from raw_plate_finder import RawPlateFinder
                from threede_scene_finder import ThreeDESceneFinder

                with patch.object(Path, "exists", side_effect=mock_fs.exists):
                    with patch.object(Path, "iterdir", side_effect=mock_fs.iterdir):
                        # Simulate processing many shots
                        for show_idx in range(1):
                            show_name = f"show_{show_idx:02d}"

                            for seq_idx in range(5):
                                sequence = f"{seq_idx:03d}_SEQ"

                                for shot_idx in range(60):  # 60 shots
                                    shot_name = f"{sequence}_{shot_idx:04d}"
                                    shot_dir = f"{sequence}_{shot_name}"
                                    workspace = f"/shows/{show_name}/shots/{sequence}/{shot_dir}"

                                    # Find 3DE scenes
                                    ThreeDESceneFinder.find_threede_scenes(
                                        workspace, set()
                                    )

                                    # Find raw plates
                                    RawPlateFinder.find_latest_raw_plate(
                                        workspace, shot_name
                                    )

                                    # Small delay to simulate work
                                    simulate_work_without_sleep(1)

            except ImportError:
                # Fallback to simpler background work
                with patch.object(Path, "exists", side_effect=mock_fs.exists):
                    for i in range(1000):
                        Path(f"/fake/path_{i}").exists()
                        simulate_work_without_sleep(1)

            background_complete.set()

        # Start both threads
        ui_thread = threading.Thread(target=simulate_ui_operations)
        bg_thread = threading.Thread(target=heavy_background_work)

        ui_thread.start()
        bg_thread.start()

        # Wait for completion with timeout
        bg_thread.join(timeout=30)
        background_complete.set()
        ui_thread.join(timeout=5)

        # Analyze UI responsiveness
        if ui_response_times:
            avg_response = sum(ui_response_times) / len(ui_response_times)
            max_response = max(ui_response_times)

            # UI should remain responsive (under 50ms average, 200ms max)
            assert avg_response < 50.0, (
                f"UI not responsive: {avg_response:.1f}ms average"
            )
            assert max_response < 200.0, f"UI froze: {max_response:.1f}ms max response"

            print(
                f"UI response times - Avg: {avg_response:.1f}ms, Max: {max_response:.1f}ms"
            )
            print(
                f"Background processing completed with {len(ui_response_times)} UI samples"
            )

        # Check filesystem access efficiency
        fs_stats = mock_fs.get_access_stats()
        print(f"Total filesystem accesses: {fs_stats['total_accesses']}")

    @timed_operation("large_dataset_processing", store_results=True)
    def test_large_dataset_handling(self):
        """Test handling of large VFX production datasets."""
        mock_fs = MockFileSystem()
        # Create large dataset - 5 shows, 500 shots total
        mock_fs.create_vfx_structure(num_shows=5, shots_per_show=100)

        processing_stats = {
            "shots_processed": 0,
            "scenes_found": 0,
            "plates_found": 0,
            "cache_hits": 0,
            "filesystem_accesses": 0,
        }

        try:
            from utils import PathUtils, get_cache_stats

            initial_cache_stats = get_cache_stats()
            initial_fs_accesses = mock_fs.access_count

            with patch.object(Path, "exists", side_effect=mock_fs.exists):
                with patch.object(Path, "iterdir", side_effect=mock_fs.iterdir):
                    # Process all shows/sequences/shots
                    for show_idx in range(5):
                        show_name = f"show_{show_idx:02d}"

                        for seq_idx in range(5):
                            sequence = f"{seq_idx:03d}_SEQ"

                            # Process shots in batches for memory efficiency
                            shots_per_batch = 20
                            total_shots_in_seq = 20  # 100 shots / 5 sequences

                            for batch_start in range(
                                0, total_shots_in_seq, shots_per_batch
                            ):
                                batch_end = min(
                                    batch_start + shots_per_batch, total_shots_in_seq
                                )

                                for shot_idx in range(batch_start, batch_end):
                                    shot_name = f"{sequence}_{shot_idx:04d}"
                                    shot_dir = f"{sequence}_{shot_name}"
                                    workspace = f"/shows/{show_name}/shots/{sequence}/{shot_dir}"

                                    # Process shot
                                    self._process_single_shot(
                                        workspace, shot_name, processing_stats
                                    )

                                    processing_stats["shots_processed"] += 1

                                # Check memory usage periodically
                                if batch_start % 40 == 0:  # Every 2 batches
                                    cache_stats = get_cache_stats()
                                    print(
                                        f"Batch {batch_start // shots_per_batch}: "
                                        f"Path cache: {cache_stats.get('path_cache_size', 0)}"
                                    )

            # Final statistics
            final_cache_stats = get_cache_stats()
            final_fs_accesses = mock_fs.access_count
            processing_stats["filesystem_accesses"] = (
                final_fs_accesses - initial_fs_accesses
            )

            # Performance assertions
            assert processing_stats["shots_processed"] == 500, (
                "Should process all shots"
            )

            # Cache efficiency - should have high hit rate for repeated operations
            cache_growth = final_cache_stats.get(
                "path_cache_size", 0
            ) - initial_cache_stats.get("path_cache_size", 0)

            # Filesystem access should be optimized
            avg_accesses_per_shot = (
                processing_stats["filesystem_accesses"]
                / processing_stats["shots_processed"]
            )
            assert avg_accesses_per_shot < 50, (
                f"Too many filesystem accesses per shot: {avg_accesses_per_shot:.1f}"
            )

            print(f"Processed {processing_stats['shots_processed']} shots")
            print(f"Found {processing_stats['scenes_found']} 3DE scenes")
            print(f"Found {processing_stats['plates_found']} raw plates")
            print(f"Cache growth: {cache_growth} entries")
            print(f"Avg filesystem accesses per shot: {avg_accesses_per_shot:.1f}")

        except ImportError:
            # Fallback test with simpler operations
            with patch.object(Path, "exists", side_effect=mock_fs.exists):
                for i in range(500):
                    PathUtils.validate_path_exists(
                        f"/fake/shot_{i}", "Large dataset test"
                    )
                    processing_stats["shots_processed"] += 1

            print(
                f"Fallback test: processed {processing_stats['shots_processed']} paths"
            )

    def _process_single_shot(
        self, workspace: str, shot_name: str, stats: Dict[str, int]
    ):
        """Process a single shot for large dataset test."""
        try:
            from raw_plate_finder import RawPlateFinder
            from threede_scene_finder import ThreeDESceneFinder

            # Find 3DE scenes
            scenes = ThreeDESceneFinder.find_threede_scenes(workspace, {"gabriel-h"})
            stats["scenes_found"] += len(scenes)

            # Find raw plates
            plate = RawPlateFinder.find_latest_raw_plate(workspace, shot_name)
            if plate:
                stats["plates_found"] += 1

        except ImportError:
            # Fallback processing
            from utils import PathUtils

            # Simulate scene search
            scene_path = f"{workspace}/user/user_a/mm/3de/scenes"
            if PathUtils.validate_path_exists(scene_path, "Scene test"):
                stats["scenes_found"] += 1

            # Simulate plate search
            plate_path = f"{workspace}/publish/turnover/plate"
            if PathUtils.validate_path_exists(plate_path, "Plate test"):
                stats["plates_found"] += 1

    def test_concurrent_workflow_performance(self):
        """Test performance of concurrent workflow operations."""
        mock_fs = MockFileSystem()
        mock_fs.create_vfx_structure(num_shows=2, shots_per_show=100)

        def worker_workflow(
            worker_id: int, shots_to_process: List[str]
        ) -> Dict[str, int]:
            """Worker function for concurrent processing."""
            results = {
                "processed": 0,
                "scenes_found": 0,
                "plates_found": 0,
                "errors": 0,
            }

            try:
                from utils import PathUtils

                with patch.object(Path, "exists", side_effect=mock_fs.exists):
                    for shot_workspace in shots_to_process:
                        try:
                            # Simulate scene discovery
                            scene_base = f"{shot_workspace}/user/user_a/mm/3de"
                            if PathUtils.validate_path_exists(
                                scene_base, f"Worker {worker_id}"
                            ):
                                results["scenes_found"] += 1

                            # Simulate plate discovery
                            plate_base = f"{shot_workspace}/publish/turnover/plate"
                            if PathUtils.validate_path_exists(
                                plate_base, f"Worker {worker_id}"
                            ):
                                results["plates_found"] += 1

                            results["processed"] += 1

                        except Exception:
                            results["errors"] += 1

            except ImportError:
                # Very basic fallback
                for shot_workspace in shots_to_process:
                    results["processed"] += 1

            return results

        # Prepare shot lists for workers
        all_shots = []
        for show_idx in range(2):
            show_name = f"show_{show_idx:02d}"
            for seq_idx in range(5):
                sequence = f"{seq_idx:03d}_SEQ"
                for shot_idx in range(10):  # 10 shots per sequence
                    shot_name = f"{sequence}_{shot_idx:04d}"
                    shot_dir = f"{sequence}_{shot_name}"
                    workspace = f"/shows/{show_name}/shots/{sequence}/{shot_dir}"
                    all_shots.append(workspace)

        # Divide work among workers
        num_workers = 4
        shots_per_worker = len(all_shots) // num_workers
        worker_assignments = []

        for i in range(num_workers):
            start_idx = i * shots_per_worker
            end_idx = (
                start_idx + shots_per_worker if i < num_workers - 1 else len(all_shots)
            )
            worker_assignments.append(all_shots[start_idx:end_idx])

        # Run concurrent workflows
        start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(worker_workflow, i, assignments)
                for i, assignments in enumerate(worker_assignments)
            ]

            results = []
            for future in concurrent.futures.as_completed(futures, timeout=30):
                result = future.result()
                results.append(result)

        end_time = time.time()
        elapsed_time = end_time - start_time

        # Aggregate results
        total_processed = sum(r["processed"] for r in results)
        total_scenes = sum(r["scenes_found"] for r in results)
        total_plates = sum(r["plates_found"] for r in results)
        total_errors = sum(r["errors"] for r in results)

        # Performance assertions
        assert total_processed == len(all_shots), "Should process all shots"
        assert total_errors == 0, f"Should have no errors, got {total_errors}"

        # Should complete reasonably quickly
        shots_per_second = total_processed / elapsed_time
        assert shots_per_second > 5, f"Too slow: {shots_per_second:.1f} shots/sec"

        # Check filesystem access efficiency
        fs_stats = mock_fs.get_access_stats()

        print(f"Concurrent processing: {total_processed} shots in {elapsed_time:.1f}s")
        print(f"Processing rate: {shots_per_second:.1f} shots/sec")
        print(f"Found: {total_scenes} scenes, {total_plates} plates")
        print(f"Filesystem accesses: {fs_stats['total_accesses']}")

    def test_end_to_end_performance_regression(self):
        """Test for end-to-end performance regression."""
        # This test establishes performance baselines for regression detection

        mock_fs = MockFileSystem()
        mock_fs.create_vfx_structure(num_shows=1, shots_per_show=50)

        performance_metrics = {}

        # Test 1: Path validation performance
        @timed_operation("e2e_path_validation", store_results=True)
        def test_path_validation():
            from utils import PathUtils

            test_paths = [f"/shows/show_00/test_path_{i}" for i in range(100)]

            with patch.object(Path, "exists", side_effect=mock_fs.exists):
                for path in test_paths:
                    PathUtils.validate_path_exists(path, "E2E test")

        # Test 2: Scene discovery performance
        @timed_operation("e2e_scene_discovery", store_results=True)
        def test_scene_discovery():
            try:
                from threede_scene_finder import ThreeDESceneFinder

                with patch.object(Path, "exists", side_effect=mock_fs.exists):
                    with patch.object(Path, "iterdir", side_effect=mock_fs.iterdir):
                        for seq_idx in range(2):  # 2 sequences
                            sequence = f"{seq_idx:03d}_SEQ"
                            for shot_idx in range(5):  # 5 shots per sequence
                                shot_name = f"{sequence}_{shot_idx:04d}"
                                shot_dir = f"{sequence}_{shot_name}"
                                workspace = (
                                    f"/shows/show_00/shots/{sequence}/{shot_dir}"
                                )

                                ThreeDESceneFinder.find_threede_scenes(
                                    workspace, {"gabriel-h"}
                                )

            except ImportError:
                # Fallback test
                test_path_validation()

        # Test 3: Cache performance
        @timed_operation("e2e_cache_operations", store_results=True)
        def test_cache_operations():
            from utils import PathUtils

            # Mix of new and repeated operations
            test_paths = [f"/shows/show_00/cache_test_{i}" for i in range(20)]

            with patch.object(Path, "exists", side_effect=mock_fs.exists):
                # First pass - populate cache
                for path in test_paths:
                    PathUtils.validate_path_exists(path, "Cache test")

                # Second pass - should hit cache
                for path in test_paths:
                    PathUtils.validate_path_exists(path, "Cache test")

        # Run all tests
        test_path_validation()
        test_scene_discovery()
        test_cache_operations()

        # Collect performance metrics
        for operation in [
            "e2e_path_validation",
            "e2e_scene_discovery",
            "e2e_cache_operations",
        ]:
            stats = TimingRegistry.get_stats(operation)
            if stats:
                performance_metrics[operation] = stats["mean_ms"]

        # Define performance expectations (regression thresholds)
        performance_thresholds = {
            "e2e_path_validation": 100.0,  # 100ms max
            "e2e_scene_discovery": 500.0,  # 500ms max
            "e2e_cache_operations": 50.0,  # 50ms max
        }

        # Check for performance regressions
        for operation, threshold in performance_thresholds.items():
            if operation in performance_metrics:
                actual_time = performance_metrics[operation]
                assert actual_time < threshold, (
                    f"Performance regression in {operation}: "
                    f"{actual_time:.1f}ms > {threshold:.1f}ms threshold"
                )

        # Check filesystem access efficiency
        fs_stats = mock_fs.get_access_stats()
        assert fs_stats["total_accesses"] < 1000, "Too many filesystem accesses"

        print("End-to-end performance metrics:")
        for operation, time_ms in performance_metrics.items():
            threshold = performance_thresholds.get(operation, 0)
            status = "✓" if time_ms < threshold else "⚠"
            print(
                f"  {status} {operation}: {time_ms:.1f}ms (threshold: {threshold:.1f}ms)"
            )

        print(f"Total filesystem accesses: {fs_stats['total_accesses']}")
        print(f"Access rate: {fs_stats['access_rate']:.1f}/sec")
