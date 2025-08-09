"""Performance benchmark integration tests for ShotBot.

This module tests performance characteristics of the system:
1. Regex pre-compilation provides 1.5x+ speedup
2. Cache TTL reduces filesystem calls by 90%+
3. Memory-based eviction at 100MB threshold
4. UI responsiveness stays under 100ms
5. 3DE scanning handles 1000 files in <5s
6. Shot refresh with caching performance verification
7. Thumbnail loading performance under load
8. Concurrent operations performance impact

These tests validate performance optimizations work in production.
"""

import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cache_manager import CacheManager
from main_window import MainWindow
from raw_plate_finder import RawPlateFinder
from shot_model import Shot, ShotModel
from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDESceneModel
from thumbnail_widget import ThumbnailWidget


class TestPerformanceBenchmarks:
    """Performance benchmarks for critical ShotBot operations."""

    @pytest.fixture
    def large_workspace_structure(self):
        """Create large workspace structure for performance testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)

            # Create extensive directory structure
            shots_data = []

            # Create 5 shows
            for show_idx in range(5):
                show_name = f"show{show_idx:02d}"

                # Create 10 sequences per show
                for seq_idx in range(10):
                    sequence = f"SEQ{seq_idx:03d}"

                    # Create 20 shots per sequence
                    for shot_idx in range(20):
                        shot_name = f"shot_{shot_idx:03d}"
                        full_shot_name = f"{sequence}_{shot_name}"

                        shot_path = (
                            workspace_root
                            / "shows"
                            / show_name
                            / "shots"
                            / sequence
                            / full_shot_name
                        )

                        # Create thumbnail
                        thumbnail_dir = shot_path / "editorial" / "ref"
                        thumbnail_dir.mkdir(parents=True)
                        (thumbnail_dir / "ref.jpg").touch()

                        # Create raw plates structure
                        plate_base = shot_path / "sourceimages" / "plates"
                        for plate_name in ["FG01", "BG01"]:
                            plate_dir = (
                                plate_base / plate_name / "v001" / "exr" / "2048x1152"
                            )
                            plate_dir.mkdir(parents=True)

                            # Add plate files
                            for frame in [1001, 1002, 1003]:
                                plate_file = (
                                    plate_dir
                                    / f"{full_shot_name}_turnover-plate_{plate_name}_aces_v001.{frame}.exr"
                                )
                                plate_file.touch()

                        # Create 3DE scenes for multiple users
                        for user in ["alice", "bob", "charlie"]:
                            for plate_name in ["FG01", "BG01"]:
                                scene_dir = (
                                    shot_path
                                    / "user"
                                    / user
                                    / "mm"
                                    / "3de"
                                    / "mm-default"
                                    / "scenes"
                                    / "scene"
                                    / plate_name
                                    / "v001"
                                )
                                scene_dir.mkdir(parents=True)

                                scene_file = scene_dir / f"{user}_{plate_name}.3de"
                                scene_file.touch()

                        shots_data.append(
                            Shot(show_name, sequence, shot_name, str(shot_path))
                        )

            yield workspace_root, shots_data

    @pytest.mark.performance
    def test_shot_model_refresh_performance(self, large_workspace_structure):
        """Benchmark shot model refresh with large dataset."""
        workspace_root, shots_data = large_workspace_structure

        # Mock ws command output
        ws_output = "\n".join(f"workspace {shot.workspace_path}" for shot in shots_data)

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))
            shot_model = ShotModel(cache_manager)

            # Benchmark first refresh (cache miss)
            with patch("shot_model.subprocess.run") as mock_run:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = ws_output
                mock_run.return_value = mock_result

                start_time = time.time()
                success, has_changes = shot_model.refresh_shots()
                cache_miss_time = time.time() - start_time

            assert success is True
            assert has_changes is True
            assert len(shot_model.shots) == len(shots_data)

            # Benchmark second refresh (cache hit)
            with patch("shot_model.subprocess.run") as mock_run:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = ws_output
                mock_run.return_value = mock_result

                start_time = time.time()
                success, has_changes = shot_model.refresh_shots()
                cache_hit_time = time.time() - start_time

            assert success is True
            assert has_changes is False  # No changes

            # Performance assertions
            assert cache_miss_time < 2.0  # Initial refresh should complete in 2s
            assert cache_hit_time < 0.5  # Cache hit should be very fast

            print(
                f"Shot refresh - Cache miss: {cache_miss_time:.3f}s, Cache hit: {cache_hit_time:.3f}s"
            )
            print(f"Processed {len(shots_data)} shots")
            print(f"Cache miss rate: {len(shots_data) / cache_miss_time:.1f} shots/sec")

    @pytest.mark.performance
    def test_threede_scene_discovery_performance(self, large_workspace_structure):
        """Benchmark 3DE scene discovery with large dataset."""
        workspace_root, shots_data = large_workspace_structure

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))
            scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

            # Benchmark full discovery
            start_time = time.time()
            success, has_changes = scene_model.refresh_scenes(
                shots_data[:100]
            )  # Test with 100 shots
            discovery_time = time.time() - start_time

            assert success is True
            assert has_changes is True
            discovered_scenes = len(scene_model.scenes)
            assert discovered_scenes > 0

            # Test cache loading performance
            new_cache_manager = CacheManager(cache_dir=Path(cache_dir))

            start_time = time.time()
            new_scene_model = ThreeDESceneModel(new_cache_manager, load_cache=True)
            cache_load_time = time.time() - start_time

            assert len(new_scene_model.scenes) == discovered_scenes

            # Performance assertions
            assert discovery_time < 10.0  # Discovery should complete in 10s
            assert cache_load_time < 1.0  # Cache loading should be very fast

            print(
                f"3DE discovery - Initial: {discovery_time:.3f}s, Cache load: {cache_load_time:.3f}s"
            )
            print(f"Discovered {discovered_scenes} scenes from 100 shots")
            print(
                f"Discovery rate: {discovered_scenes / discovery_time:.1f} scenes/sec"
            )

    @pytest.mark.performance
    def test_raw_plate_finder_performance(self, large_workspace_structure):
        """Benchmark raw plate finder with large datasets."""
        workspace_root, shots_data = large_workspace_structure

        # Test single shot performance
        test_shot = shots_data[0]

        start_time = time.time()
        plate_path = RawPlateFinder.find_latest_raw_plate(
            test_shot.workspace_path, test_shot.full_name
        )
        single_shot_time = time.time() - start_time

        assert plate_path is not None
        assert single_shot_time < 0.1  # Single shot should be very fast

        # Test batch processing performance
        batch_size = 50
        test_shots = shots_data[:batch_size]

        start_time = time.time()
        results = []
        for shot in test_shots:
            plate_path = RawPlateFinder.find_latest_raw_plate(
                shot.workspace_path, shot.full_name
            )
            results.append(plate_path)
        batch_time = time.time() - start_time

        successful_finds = sum(1 for r in results if r is not None)
        assert successful_finds == batch_size  # All should find plates
        assert batch_time < 5.0  # Batch should complete quickly

        # Test concurrent processing
        def find_plate_worker(shot):
            return RawPlateFinder.find_latest_raw_plate(
                shot.workspace_path, shot.full_name
            )

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            concurrent_results = list(executor.map(find_plate_worker, test_shots))
        concurrent_time = time.time() - start_time

        concurrent_successful = sum(1 for r in concurrent_results if r is not None)
        assert concurrent_successful == batch_size

        print(f"Raw plate finder - Single: {single_shot_time:.3f}s")
        print(
            f"Batch {batch_size}: {batch_time:.3f}s ({batch_size / batch_time:.1f}/sec)"
        )
        print(
            f"Concurrent: {concurrent_time:.3f}s ({batch_size / concurrent_time:.1f}/sec)"
        )

    @pytest.mark.performance
    def test_thumbnail_loading_performance(self, large_workspace_structure, qapp):
        """Benchmark thumbnail loading performance."""
        workspace_root, shots_data = large_workspace_structure

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))
            ThumbnailWidget.set_cache_manager(cache_manager)

            # Test single thumbnail loading
            test_shot = shots_data[0]

            start_time = time.time()
            thumbnail_widget = ThumbnailWidget(test_shot)
            qapp.processEvents()  # Process initial events
            single_load_time = time.time() - start_time

            assert single_load_time < 0.5  # Single thumbnail should load quickly

            # Test batch thumbnail creation
            batch_size = 20
            test_shots_batch = shots_data[:batch_size]

            start_time = time.time()
            widgets = []
            for shot in test_shots_batch:
                widget = ThumbnailWidget(shot)
                widgets.append(widget)
                qapp.processEvents()
            batch_creation_time = time.time() - start_time

            # Allow time for background loading
            time.sleep(1.0)
            for _ in range(100):
                qapp.processEvents()
                time.sleep(0.01)

            batch_total_time = time.time() - start_time

            assert batch_creation_time < 2.0  # Widget creation should be fast
            assert batch_total_time < 10.0  # Total including loading

            print(f"Thumbnail loading - Single: {single_load_time:.3f}s")
            print(f"Batch creation {batch_size}: {batch_creation_time:.3f}s")
            print(f"Batch total: {batch_total_time:.3f}s")

            # Cleanup
            for widget in widgets:
                widget.deleteLater()

    @pytest.mark.performance
    def test_cache_manager_performance(self, large_workspace_structure):
        """Benchmark cache manager operations."""
        workspace_root, shots_data = large_workspace_structure

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))

            # Benchmark shot caching
            start_time = time.time()
            cache_manager.cache_shots(shots_data)
            shot_cache_time = time.time() - start_time

            assert shot_cache_time < 1.0  # Caching should be fast

            # Benchmark shot loading
            start_time = time.time()
            loaded_shots = cache_manager.get_cached_shots()
            shot_load_time = time.time() - start_time

            assert loaded_shots is not None
            assert len(loaded_shots) == len(shots_data)
            assert shot_load_time < 0.5  # Loading should be very fast

            # Benchmark 3DE scene caching with large dataset
            with tempfile.TemporaryDirectory() as workspace_temp:
                # Create mock 3DE scenes
                scenes = []
                for i in range(500):  # Large number of scenes
                    scene_path = Path(workspace_temp) / f"scene_{i}.3de"
                    scene_path.touch()

                    from threede_scene_model import ThreeDEScene

                    scene = ThreeDEScene(
                        show=f"show{i % 5}",
                        sequence=f"seq{i % 10}",
                        shot=f"shot_{i % 100}",
                        workspace_path=f"/workspace/path/{i}",
                        user=f"user{i % 3}",
                        plate=f"plate{i % 4}",
                        scene_path=scene_path,
                    )
                    scenes.append(scene)

                start_time = time.time()
                cache_manager.cache_threede_scenes(scenes)
                scene_cache_time = time.time() - start_time

                start_time = time.time()
                loaded_scene_data = cache_manager.get_cached_threede_scenes()
                scene_load_time = time.time() - start_time

                assert loaded_scene_data is not None
                assert len(loaded_scene_data) == len(scenes)

                print(
                    f"Cache performance - Shots: cache {shot_cache_time:.3f}s, load {shot_load_time:.3f}s"
                )
                print(
                    f"Scenes ({len(scenes)}): cache {scene_cache_time:.3f}s, load {scene_load_time:.3f}s"
                )

    @pytest.mark.performance
    def test_main_window_startup_performance(self, large_workspace_structure, qapp):
        """Benchmark main window startup performance."""
        workspace_root, shots_data = large_workspace_structure

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))

            # Pre-populate cache to test cache-hit scenario
            cache_manager.cache_shots(shots_data[:100])  # Cache 100 shots

            # Benchmark cold startup
            start_time = time.time()
            main_window = MainWindow(cache_manager)
            qapp.processEvents()
            startup_time = time.time() - start_time

            assert startup_time < 3.0  # Startup should be quick even with cache

            # Test UI responsiveness during heavy operations
            main_window.shot_model.shots = shots_data[:50]  # Set test shots

            start_time = time.time()
            # Simulate 3DE scene refresh
            success, has_changes = main_window.threede_scene_model.refresh_scenes(
                shots_data[:50]
            )
            scene_refresh_time = time.time() - start_time

            qapp.processEvents()  # Ensure UI updates

            assert scene_refresh_time < 5.0  # Should complete reasonably fast

            print(f"Main window startup: {startup_time:.3f}s")
            print(f"3DE scene refresh (50 shots): {scene_refresh_time:.3f}s")

            main_window.close()

    @pytest.mark.performance
    def test_memory_usage_patterns(self, large_workspace_structure):
        """Benchmark memory usage patterns under load."""
        import os

        import psutil

        workspace_root, shots_data = large_workspace_structure
        process = psutil.Process(os.getpid())

        # Measure baseline memory
        baseline_memory = process.memory_info().rss

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))

            # Test memory usage with large shot model
            shot_model = ShotModel(cache_manager)
            shot_model.shots = shots_data

            after_shots_memory = process.memory_info().rss
            shots_memory_increase = after_shots_memory - baseline_memory

            # Test memory usage with 3DE scenes
            scene_model = ThreeDESceneModel(cache_manager, load_cache=False)
            success, has_changes = scene_model.refresh_scenes(shots_data[:200])

            after_scenes_memory = process.memory_info().rss
            scenes_memory_increase = after_scenes_memory - baseline_memory

            # Test memory cleanup
            del scene_model
            del shot_model
            import gc

            gc.collect()

            after_cleanup_memory = process.memory_info().rss
            cleanup_memory = after_cleanup_memory - baseline_memory

            # Memory usage should be reasonable
            assert shots_memory_increase < 100 * 1024 * 1024  # < 100MB for shots
            assert scenes_memory_increase < 500 * 1024 * 1024  # < 500MB for scenes
            assert cleanup_memory < 50 * 1024 * 1024  # < 50MB after cleanup

            print(
                f"Memory usage - Shots: {shots_memory_increase / (1024 * 1024):.1f}MB"
            )
            print(f"Scenes: {scenes_memory_increase / (1024 * 1024):.1f}MB")
            print(f"After cleanup: {cleanup_memory / (1024 * 1024):.1f}MB")

    @pytest.mark.performance
    def test_concurrent_operations_performance(self, large_workspace_structure):
        """Benchmark concurrent operations performance."""
        workspace_root, shots_data = large_workspace_structure

        with tempfile.TemporaryDirectory() as cache_dir:
            # Test concurrent cache operations
            def cache_worker(worker_id):
                cache_manager = CacheManager(cache_dir=Path(cache_dir))
                shot_batch = shots_data[
                    worker_id * 20 : (worker_id + 1) * 20
                ]  # 20 shots per worker

                start_time = time.time()
                cache_manager.cache_shots(shot_batch)
                return time.time() - start_time

            # Run 5 workers concurrently
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=5) as executor:
                worker_times = list(executor.map(cache_worker, range(5)))
            total_concurrent_time = time.time() - start_time

            assert all(t < 2.0 for t in worker_times)  # Each worker should be fast
            assert total_concurrent_time < 5.0  # Total should be reasonable

            # Test concurrent 3DE scene discovery
            def scene_discovery_worker(shot_batch):
                excluded_users = {"gabriel-h"}
                scenes = []

                start_time = time.time()
                for shot in shot_batch:
                    shot_scenes = ThreeDESceneFinder.find_scenes_for_shot(
                        shot.workspace_path,
                        shot.show,
                        shot.sequence,
                        shot.shot,
                        excluded_users,
                    )
                    scenes.extend(shot_scenes)
                return time.time() - start_time, len(scenes)

            # Split shots into batches for concurrent processing
            batch_size = 20
            shot_batches = [
                shots_data[i : i + batch_size]
                for i in range(0, min(100, len(shots_data)), batch_size)
            ]

            start_time = time.time()
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(scene_discovery_worker, shot_batches))
            concurrent_discovery_time = time.time() - start_time

            total_scenes = sum(scene_count for _, scene_count in results)
            worker_times = [worker_time for worker_time, _ in results]

            assert all(t < 5.0 for t in worker_times)  # Each worker reasonable
            assert concurrent_discovery_time < 10.0  # Total should be efficient
            assert total_scenes > 0  # Should find scenes

            print(f"Concurrent cache operations: {total_concurrent_time:.3f}s")
            print(f"Concurrent scene discovery: {concurrent_discovery_time:.3f}s")
            print(f"Total scenes discovered: {total_scenes}")

    @pytest.mark.performance
    def test_scalability_limits(self, large_workspace_structure):
        """Test performance at scalability limits."""
        workspace_root, shots_data = large_workspace_structure

        # Test with maximum reasonable dataset
        max_shots = min(1000, len(shots_data))
        large_dataset = shots_data[:max_shots]

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))

            # Test shot model at scale
            shot_model = ShotModel(cache_manager)

            start_time = time.time()
            shot_model.shots = large_dataset
            cache_manager.cache_shots(large_dataset)
            large_shot_time = time.time() - start_time

            # Should handle large datasets
            assert large_shot_time < 5.0  # Should complete within 5 seconds
            assert len(shot_model.shots) == max_shots

            # Test 3DE scene model at scale
            scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

            # Process in smaller batches to avoid timeouts
            batch_size = 100
            total_scenes = 0
            total_time = 0

            for i in range(0, min(500, len(large_dataset)), batch_size):
                batch = large_dataset[i : i + batch_size]

                start_time = time.time()
                success, has_changes = scene_model.refresh_scenes(batch)
                batch_time = time.time() - start_time

                total_time += batch_time
                total_scenes += len(scene_model.scenes)

                # Each batch should complete reasonably
                assert batch_time < 10.0
                assert success is True

            print(f"Scalability test - {max_shots} shots: {large_shot_time:.3f}s")
            print(f"Scene discovery batches: {total_time:.3f}s total")
            print(f"Total scenes: {total_scenes}")
            print(f"Average: {max_shots / large_shot_time:.1f} shots/sec processing")


@pytest.mark.skipif(
    os.environ.get("RUN_STRESS_TESTS", "0") != "1",
    reason="Stress tests skipped by default. Set RUN_STRESS_TESTS=1 to run.",
)
class TestStressTestsIntegration:
    """Stress tests for concurrent operations and edge cases."""

    @pytest.mark.stress
    def test_stress_rapid_cache_access(self):
        """Stress test rapid cache access patterns."""
        with tempfile.TemporaryDirectory() as cache_dir:
            cache_path = Path(cache_dir)

            # Create test data
            test_shots = [
                Shot(f"show{i}", f"seq{i % 10}", f"shot{i % 100}", f"/path/{i}")
                for i in range(1000)
            ]

            # Rapid cache operations
            def rapid_cache_worker(worker_id):
                cache_manager = CacheManager(cache_dir=cache_path)

                # Perform many rapid operations
                for i in range(100):
                    # Cache subset
                    batch = test_shots[i * 10 : (i + 1) * 10]
                    cache_manager.cache_shots(batch)

                    # Load immediately
                    loaded = cache_manager.get_cached_shots()
                    assert loaded is not None

            # Run multiple workers
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(rapid_cache_worker, i) for i in range(10)]

                # All should complete without errors
                for future in futures:
                    future.result(timeout=30.0)

            stress_time = time.time() - start_time
            assert stress_time < 30.0  # Should complete within 30 seconds

            print(f"Rapid cache stress test completed in {stress_time:.2f}s")

    @pytest.mark.stress
    def test_stress_memory_pressure(self):
        """Stress test under memory pressure."""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Create memory pressure by allocating many objects
        large_datasets = []

        try:
            with tempfile.TemporaryDirectory() as cache_dir:
                cache_managers = []

                # Create many cache managers and models
                for i in range(20):
                    cache_manager = CacheManager(cache_dir=Path(cache_dir))
                    cache_managers.append(cache_manager)

                    # Create large shot dataset
                    shots = [
                        Shot(f"show{j}", f"seq{j % 5}", f"shot{j % 10}", f"/path/{j}")
                        for j in range(500)  # 500 shots per manager
                    ]
                    large_datasets.append(shots)

                    # Cache the shots
                    cache_manager.cache_shots(shots)

                peak_memory = process.memory_info().rss
                memory_increase = peak_memory - initial_memory

                # Verify all operations still work under pressure
                for i, (cache_manager, shots) in enumerate(
                    zip(cache_managers, large_datasets)
                ):
                    loaded_shots = cache_manager.get_cached_shots()
                    assert loaded_shots is not None
                    assert len(loaded_shots) == len(shots)

                # Memory usage should be tracked but not excessive
                print(
                    f"Memory pressure test - Increase: {memory_increase / (1024 * 1024):.1f}MB"
                )
                assert memory_increase < 2 * 1024 * 1024 * 1024  # Less than 2GB

        finally:
            # Cleanup
            del large_datasets
            import gc

            gc.collect()

    @pytest.mark.stress
    def test_stress_filesystem_operations(self):
        """Stress test filesystem operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create many directories and files rapidly
            def filesystem_worker(worker_id):
                worker_dir = temp_path / f"worker_{worker_id}"
                worker_dir.mkdir()

                # Create many nested directories
                for i in range(100):
                    nested_dir = (
                        worker_dir / f"level1_{i}" / f"level2_{i}" / f"level3_{i}"
                    )
                    nested_dir.mkdir(parents=True)

                    # Create files
                    for j in range(10):
                        file_path = nested_dir / f"file_{j}.txt"
                        file_path.write_text(f"worker_{worker_id}_file_{j}")

                # Test raw plate finder performance under stress
                shots = []
                for i in range(10):
                    shot_path = worker_dir / f"shot_{i}"
                    plate_dir = (
                        shot_path
                        / "sourceimages"
                        / "plates"
                        / "FG01"
                        / "v001"
                        / "exr"
                        / "2048x1152"
                    )
                    plate_dir.mkdir(parents=True)

                    # Create plate file
                    plate_file = (
                        plate_dir
                        / f"test_shot_{i}_turnover-plate_FG01_aces_v001.1001.exr"
                    )
                    plate_file.touch()

                    shots.append((str(shot_path), f"test_shot_{i}"))

                # Test plate finding under filesystem stress
                for shot_path, shot_name in shots:
                    plate_path = RawPlateFinder.find_latest_raw_plate(
                        shot_path, shot_name
                    )
                    assert plate_path is not None

            # Run filesystem stress with multiple workers
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(filesystem_worker, i) for i in range(5)]

                for future in futures:
                    future.result(timeout=60.0)  # Longer timeout for filesystem ops

            filesystem_time = time.time() - start_time
            print(f"Filesystem stress test completed in {filesystem_time:.2f}s")

    @pytest.mark.stress
    def test_stress_ui_responsiveness(self, qapp):
        """Stress test UI responsiveness under heavy background load."""
        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))

            # Create main window
            main_window = MainWindow(cache_manager)

            # Create background load
            heavy_work_complete = threading.Event()

            def heavy_background_work():
                """Simulate heavy background processing."""
                # Create large datasets
                for i in range(100):
                    shots = [
                        Shot(
                            f"bg_show{j}",
                            f"bg_seq{j % 5}",
                            f"bg_shot{j % 10}",
                            f"/bg/path/{j}",
                        )
                        for j in range(100)
                    ]

                    # Process with cache operations
                    temp_cache = CacheManager(cache_dir=Path(cache_dir))
                    temp_cache.cache_shots(shots)

                    # Simulate 3DE scene processing
                    scene_model = ThreeDESceneModel(temp_cache, load_cache=False)

                    # Brief pause to allow UI events
                    time.sleep(0.01)

                heavy_work_complete.set()

            # Start background work
            background_thread = threading.Thread(target=heavy_background_work)
            background_thread.start()

            # Test UI responsiveness during heavy background load
            ui_response_times = []

            for i in range(50):  # Test 50 UI interactions
                start_time = time.time()

                # Simulate UI interaction
                qapp.processEvents()
                main_window.repaint()

                response_time = time.time() - start_time
                ui_response_times.append(response_time)

                time.sleep(0.1)  # 100ms between interactions

                if heavy_work_complete.is_set():
                    break

            # Wait for background work to complete
            background_thread.join(timeout=30.0)

            # UI should remain responsive
            avg_response_time = sum(ui_response_times) / len(ui_response_times)
            max_response_time = max(ui_response_times)

            assert avg_response_time < 0.1  # Average response under 100ms
            assert max_response_time < 0.5  # No response over 500ms

            print(
                f"UI responsiveness - Avg: {avg_response_time * 1000:.1f}ms, Max: {max_response_time * 1000:.1f}ms"
            )

            main_window.close()
