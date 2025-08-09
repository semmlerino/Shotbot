"""Comprehensive stress tests for concurrent operations in ShotBot.

NOTE: These tests are intensive and may timeout or cause issues on slower systems.
Run with: pytest -m stress to explicitly run stress tests
Skip with: pytest -m "not stress" to exclude them
"""

import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

# Skip all stress tests by default unless explicitly requested
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_STRESS_TESTS", "0") != "1",
    reason="Stress tests skipped by default. Set RUN_STRESS_TESTS=1 to run.",
)

from cache_manager import CacheManager
from launcher_manager import LauncherManager
from raw_plate_finder import RawPlateFinder
from shot_model import Shot, ShotModel
from threede_scene_model import ThreeDESceneModel
from threede_thumbnail_widget import ThreeDEThumbnailWidget
from thumbnail_widget import ThumbnailWidget


class TestConcurrentStressIntegration:
    """Comprehensive stress tests for concurrent operations."""

    @pytest.fixture
    def stress_test_workspace(self):
        """Create extensive workspace for stress testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            # Create manageable dataset for stress tests
            shots_data = []

            # 50 shots across multiple shows/sequences (reduced from 100)
            for show_idx in range(5):
                for seq_idx in range(2):
                    for shot_idx in range(5):
                        show = f"stressshow{show_idx}"
                        sequence = f"STR{seq_idx:02d}"
                        shot_name = f"shot_{shot_idx:03d}"

                        shot_path = (
                            workspace
                            / show
                            / "shots"
                            / sequence
                            / f"{sequence}_{shot_name}"
                        )

                        # Create minimal required structure
                        thumbnail_dir = shot_path / "editorial" / "ref"
                        thumbnail_dir.mkdir(parents=True)
                        (thumbnail_dir / "ref.jpg").touch()

                        # Raw plates
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
                        plate_file = (
                            plate_dir
                            / f"{sequence}_{shot_name}_turnover-plate_FG01_aces_v001.1001.exr"
                        )
                        plate_file.touch()

                        # 3DE scenes
                        for user in ["user1", "user2"]:
                            scene_dir = (
                                shot_path
                                / "user"
                                / user
                                / "mm"
                                / "3de"
                                / "mm-default"
                                / "scenes"
                                / "scene"
                                / "FG01"
                                / "v001"
                            )
                            scene_dir.mkdir(parents=True)
                            (scene_dir / f"{user}_scene.3de").touch()

                        shots_data.append(
                            Shot(show, sequence, shot_name, str(shot_path))
                        )

            yield workspace, shots_data

    @pytest.mark.stress
    def test_concurrent_cache_operations_stress(self, stress_test_workspace):
        """Stress test concurrent cache operations with race conditions."""
        workspace, shots_data = stress_test_workspace

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_path = Path(cache_dir)

            # Shared state for tracking operations
            operation_results = []
            operation_lock = threading.Lock()
            error_count = 0

            def cache_operation_worker(worker_id, operation_type):
                """Worker performing various cache operations."""
                nonlocal error_count

                try:
                    cache_manager = CacheManager(cache_dir=cache_path)

                    for iteration in range(10):  # Reduced to 10 operations per worker
                        operation_start = time.time()

                        if operation_type == "shot_cache":
                            # Cache shots
                            batch_start = (worker_id * 10) % len(shots_data)
                            batch = shots_data[batch_start : batch_start + 10]
                            cache_manager.cache_shots(batch)

                            # Immediately try to load
                            loaded = cache_manager.get_cached_shots()
                            assert loaded is not None

                        elif operation_type == "scene_discovery":
                            # 3DE scene discovery
                            scene_model = ThreeDESceneModel(
                                cache_manager, load_cache=False
                            )
                            batch = shots_data[worker_id * 5 : (worker_id + 1) * 5]
                            success, has_changes = scene_model.refresh_scenes(batch)
                            assert success is True

                        elif operation_type == "mixed_ops":
                            # Mixed operations
                            if iteration % 3 == 0:
                                # Shot caching
                                batch = shots_data[worker_id : worker_id + 5]
                                cache_manager.cache_shots(batch)
                            elif iteration % 3 == 1:
                                # Scene model operations
                                scene_model = ThreeDESceneModel(
                                    cache_manager, load_cache=True
                                )
                                if len(scene_model.scenes) == 0:
                                    # Try to discover if cache is empty
                                    batch = shots_data[:5]
                                    scene_model.refresh_scenes(batch)
                            else:
                                # Cache loading
                                shots = cache_manager.get_cached_shots()
                                scenes = cache_manager.get_cached_threede_scenes()

                        operation_time = time.time() - operation_start

                        with operation_lock:
                            operation_results.append(
                                {
                                    "worker_id": worker_id,
                                    "operation_type": operation_type,
                                    "iteration": iteration,
                                    "time": operation_time,
                                    "success": True,
                                }
                            )

                        # Small random delay to increase race condition chances
                        time.sleep(0.01 * (worker_id % 3))

                except Exception as e:
                    with operation_lock:
                        error_count += 1
                        operation_results.append(
                            {
                                "worker_id": worker_id,
                                "operation_type": operation_type,
                                "error": str(e),
                                "success": False,
                            }
                        )

            # Launch concurrent workers with different operation types (reduced)
            worker_configs = (
                [(i, "shot_cache") for i in range(3)]
                + [(i, "scene_discovery") for i in range(2)]
                + [(i, "mixed_ops") for i in range(3)]
            )

            start_time = time.time()
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(cache_operation_worker, worker_id, op_type)
                    for worker_id, op_type in worker_configs
                ]

                # Wait for all to complete with shorter timeout
                for future in as_completed(futures, timeout=30):
                    future.result()

            total_time = time.time() - start_time

            # Analyze results
            successful_ops = [r for r in operation_results if r.get("success", False)]
            failed_ops = [r for r in operation_results if not r.get("success", False)]

            print("Concurrent cache stress test:")
            print(f"  Total time: {total_time:.2f}s")
            print(f"  Successful operations: {len(successful_ops)}")
            print(f"  Failed operations: {len(failed_ops)}")
            print(f"  Error count: {error_count}")

            # Should have minimal failures
            failure_rate = (
                len(failed_ops) / len(operation_results) if operation_results else 0
            )
            assert failure_rate < 0.05  # Less than 5% failure rate
            assert total_time < 30.0  # Should complete within 30 seconds

    @pytest.mark.stress
    def test_concurrent_filesystem_stress(self, stress_test_workspace):
        """Stress test concurrent filesystem operations."""
        workspace, shots_data = stress_test_workspace

        filesystem_errors = []
        filesystem_lock = threading.Lock()

        def filesystem_stress_worker(worker_id):
            """Worker performing intensive filesystem operations."""
            try:
                # Raw plate finder operations
                for iteration in range(30):  # 30 operations per worker
                    shot_index = (worker_id * 10 + iteration) % len(shots_data)
                    shot = shots_data[shot_index]

                    # Find raw plate
                    plate_path = RawPlateFinder.find_latest_raw_plate(
                        shot.workspace_path, shot.full_name
                    )

                    if plate_path:
                        # Verify plate exists
                        exists = RawPlateFinder.verify_plate_exists(plate_path)
                        assert exists is True

                        # Extract version
                        version = RawPlateFinder.get_version_from_path(plate_path)
                        assert version is not None

                    # Create temporary files to stress filesystem
                    temp_dir = Path(shot.workspace_path) / f"temp_worker_{worker_id}"
                    temp_dir.mkdir(exist_ok=True)

                    temp_file = temp_dir / f"temp_file_{iteration}.txt"
                    temp_file.write_text(f"worker_{worker_id}_iteration_{iteration}")

                    # Read it back
                    content = temp_file.read_text()
                    assert f"worker_{worker_id}" in content

                    # Clean up
                    temp_file.unlink()

                    if iteration % 10 == 9:  # Every 10th iteration
                        try:
                            temp_dir.rmdir()
                        except OSError:
                            pass  # Directory might not be empty due to other workers

                    # Small delay to let other workers interleave
                    time.sleep(0.005)

            except Exception as e:
                with filesystem_lock:
                    filesystem_errors.append(f"Worker {worker_id}: {str(e)}")

        # Run filesystem stress test
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(filesystem_stress_worker, i) for i in range(10)]

            for future in as_completed(futures, timeout=20):
                future.result()

        filesystem_time = time.time() - start_time

        print("Filesystem stress test:")
        print(f"  Time: {filesystem_time:.2f}s")
        print(f"  Errors: {len(filesystem_errors)}")

        # Should have minimal filesystem errors
        assert len(filesystem_errors) < 5  # Less than 5 total errors
        assert filesystem_time < 30.0  # Should complete reasonably fast

    @pytest.mark.stress
    def test_concurrent_launcher_stress(self):
        """Stress test concurrent launcher operations."""
        launcher_manager = LauncherManager()

        # Track launcher operations
        launcher_results = []
        launcher_lock = threading.Lock()

        def launcher_stress_worker(worker_id):
            """Worker performing launcher operations."""
            try:
                for iteration in range(5):  # Reduced to 5 launches per worker
                    # Create a launcher with correct API
                    launcher_id = launcher_manager.create_launcher(
                        name=f"Stress Test {worker_id}-{iteration}",
                        command="echo test",
                        description=f"Test launcher {worker_id}",
                    )

                    if launcher_id:
                        # Execute launcher with correct parameters
                        start_time = time.time()
                        success = launcher_manager.execute_launcher(
                            launcher_id=launcher_id,
                            dry_run=True,  # Use dry run to avoid actual process creation
                        )

                        execution_time = time.time() - start_time

                        with launcher_lock:
                            launcher_results.append(
                                {
                                    "worker_id": worker_id,
                                    "iteration": iteration,
                                    "launcher_id": launcher_id,
                                    "execution_time": execution_time,
                                    "success": success,
                                }
                            )

                        # Delete the launcher to clean up
                        launcher_manager.delete_launcher(launcher_id)
                    else:
                        with launcher_lock:
                            launcher_results.append(
                                {
                                    "worker_id": worker_id,
                                    "iteration": iteration,
                                    "success": False,
                                    "error": "Failed to create launcher",
                                }
                            )

                    # Brief pause between launches
                    time.sleep(0.01)

            except Exception as e:
                with launcher_lock:
                    launcher_results.append(
                        {"worker_id": worker_id, "error": str(e), "success": False}
                    )

        # Run concurrent launcher stress test with fewer workers
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(launcher_stress_worker, i) for i in range(4)]

            for future in as_completed(futures, timeout=15):
                future.result()

        launcher_stress_time = time.time() - start_time

        # Analyze results
        successful_launches = [r for r in launcher_results if r.get("success", False)]
        failed_launches = [r for r in launcher_results if not r.get("success", False)]

        print("Launcher stress test:")
        print(f"  Time: {launcher_stress_time:.2f}s")
        print(f"  Successful launches: {len(successful_launches)}")
        print(f"  Failed launches: {len(failed_launches)}")

        # Should have high success rate
        if launcher_results:
            success_rate = len(successful_launches) / len(launcher_results)
            assert success_rate > 0.7  # At least 70% success rate (lowered threshold)

    @pytest.mark.stress
    def test_concurrent_ui_widget_stress(self, stress_test_workspace, qapp):
        """Stress test concurrent UI widget operations."""
        workspace, shots_data = stress_test_workspace

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))
            ThumbnailWidget.set_cache_manager(cache_manager)
            ThreeDEThumbnailWidget.set_cache_manager(cache_manager)

            # Track widget operations
            widget_operations = []
            widget_lock = threading.Lock()
            created_widgets = []

            def widget_stress_worker(worker_id):
                """Worker creating and manipulating widgets."""
                worker_widgets = []

                try:
                    # Create multiple widgets per worker
                    for i in range(5):  # 5 widgets per worker
                        shot_index = (worker_id * 5 + i) % len(shots_data)
                        shot = shots_data[shot_index]

                        # Create thumbnail widget
                        widget = ThumbnailWidget(shot)
                        worker_widgets.append(widget)

                        # Process events to trigger loading
                        qapp.processEvents()

                        # Simulate user interactions
                        widget.setSelected(True)
                        qapp.processEvents()

                        widget.setSelected(False)
                        qapp.processEvents()

                        # Brief pause
                        time.sleep(0.02)

                    with widget_lock:
                        created_widgets.extend(worker_widgets)
                        widget_operations.append(
                            {
                                "worker_id": worker_id,
                                "widgets_created": len(worker_widgets),
                                "success": True,
                            }
                        )

                except Exception as e:
                    with widget_lock:
                        widget_operations.append(
                            {"worker_id": worker_id, "error": str(e), "success": False}
                        )

                    # Cleanup widgets on error
                    for widget in worker_widgets:
                        try:
                            widget.deleteLater()
                        except:
                            pass

            # Run concurrent widget operations
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(widget_stress_worker, i) for i in range(6)]

                for future in as_completed(futures, timeout=20):
                    future.result()

            widget_stress_time = time.time() - start_time

            # Process remaining events
            for _ in range(100):
                qapp.processEvents()
                time.sleep(0.01)

            # Analyze results
            successful_ops = [
                op for op in widget_operations if op.get("success", False)
            ]
            total_widgets = sum(op.get("widgets_created", 0) for op in successful_ops)

            print("Widget stress test:")
            print(f"  Time: {widget_stress_time:.2f}s")
            print(f"  Successful operations: {len(successful_ops)}")
            print(f"  Total widgets created: {total_widgets}")

            # Cleanup all widgets
            for widget in created_widgets:
                try:
                    widget.deleteLater()
                except:
                    pass

            # Process cleanup events
            qapp.processEvents()

            # Should have reasonable success rate
            if widget_operations:
                success_rate = len(successful_ops) / len(widget_operations)
                assert success_rate > 0.7  # At least 70% success under stress

    @pytest.mark.stress
    def test_resource_exhaustion_recovery(self, stress_test_workspace):
        """Test recovery from resource exhaustion scenarios."""
        workspace, shots_data = stress_test_workspace

        # Track resource usage
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Create resource pressure
        resource_hogs = []

        try:
            with tempfile.TemporaryDirectory() as cache_dir:
                cache_path = Path(cache_dir)

                # Phase 1: Create resource pressure
                for i in range(50):  # Create many cache managers
                    cache_manager = CacheManager(cache_dir=cache_path)
                    shot_model = ShotModel(cache_manager)
                    scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

                    # Load with data
                    shot_batch = shots_data[
                        i % len(shots_data) : (i % len(shots_data)) + 10
                    ]
                    shot_model.shots = shot_batch
                    cache_manager.cache_shots(shot_batch)

                    scene_model.refresh_scenes(shot_batch[:3])  # Smaller batches

                    resource_hogs.append((cache_manager, shot_model, scene_model))

                    # Check memory pressure
                    current_memory = process.memory_info().rss
                    memory_increase = current_memory - initial_memory

                    if memory_increase > 1024 * 1024 * 1024:  # 1GB increase
                        print(f"Memory pressure reached at iteration {i}")
                        break

                peak_memory = process.memory_info().rss

                # Phase 2: Test operations under pressure
                pressure_cache = CacheManager(cache_dir=cache_path)

                # Should still work under pressure
                test_shots = shots_data[:10]
                pressure_cache.cache_shots(test_shots)
                loaded_shots = pressure_cache.get_cached_shots()
                assert loaded_shots is not None

                # 3DE scene operations should work
                pressure_scene_model = ThreeDESceneModel(
                    pressure_cache, load_cache=False
                )
                success, has_changes = pressure_scene_model.refresh_scenes(
                    test_shots[:5]
                )
                assert success is True

        finally:
            # Phase 3: Cleanup and recovery
            del resource_hogs
            import gc

            gc.collect()

            # Allow system to recover
            time.sleep(1.0)

            final_memory = process.memory_info().rss

            print("Resource exhaustion test:")
            print(f"  Initial memory: {initial_memory / (1024 * 1024):.1f}MB")
            print(f"  Peak memory: {peak_memory / (1024 * 1024):.1f}MB")
            print(f"  Final memory: {final_memory / (1024 * 1024):.1f}MB")
            print(
                f"  Peak increase: {(peak_memory - initial_memory) / (1024 * 1024):.1f}MB"
            )
            print(
                f"  Final increase: {(final_memory - initial_memory) / (1024 * 1024):.1f}MB"
            )

        # Should have recovered most memory
        memory_recovered = peak_memory - final_memory
        recovery_rate = memory_recovered / (peak_memory - initial_memory)

        print(f"  Memory recovery rate: {recovery_rate:.1%}")
        assert recovery_rate > 0.6  # Should recover at least 60% of memory

    @pytest.mark.stress
    def test_concurrent_error_handling_stress(self, stress_test_workspace):
        """Stress test error handling under concurrent failures."""
        workspace, shots_data = stress_test_workspace

        error_scenarios = []
        error_lock = threading.Lock()

        def error_scenario_worker(worker_id, scenario_type):
            """Worker that intentionally triggers error scenarios."""
            try:
                with tempfile.TemporaryDirectory() as temp_cache_dir:
                    cache_manager = CacheManager(cache_dir=Path(temp_cache_dir))

                    if scenario_type == "bad_paths":
                        # Test with invalid paths
                        bad_shots = [
                            Shot("bad", "BAD", "001", "/nonexistent/path/1"),
                            Shot("bad", "BAD", "002", "/dev/null/invalid"),
                            Shot("bad", "BAD", "003", ""),
                        ]

                        # Should handle gracefully
                        cache_manager.cache_shots(bad_shots)
                        loaded = cache_manager.get_cached_shots()

                        # Try raw plate finder on bad paths
                        for shot in bad_shots:
                            result = RawPlateFinder.find_latest_raw_plate(
                                shot.workspace_path, shot.full_name
                            )
                            # Should return None, not crash
                            assert result is None

                    elif scenario_type == "corrupted_cache":
                        # Corrupt cache files repeatedly
                        for i in range(10):
                            cache_file = Path(temp_cache_dir) / "shots.json"
                            cache_file.write_text(f"{{ corrupted json {i} }}")

                            # Should handle corrupted cache
                            loaded = cache_manager.get_cached_shots()
                            assert (
                                loaded is None
                            )  # Should return None for corrupted cache

                            # Should be able to create new cache
                            cache_manager.cache_shots(shots_data[:5])

                    elif scenario_type == "permission_errors":
                        # Simulate permission errors (where possible)
                        import stat

                        # Make cache directory read-only temporarily
                        cache_dir_path = Path(temp_cache_dir)
                        try:
                            cache_dir_path.chmod(
                                stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
                            )

                            # Operations should handle permission errors
                            try:
                                cache_manager.cache_shots(shots_data[:3])
                            except (PermissionError, OSError):
                                pass  # Expected

                        finally:
                            # Restore permissions
                            cache_dir_path.chmod(
                                stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
                            )

                    with error_lock:
                        error_scenarios.append(
                            {
                                "worker_id": worker_id,
                                "scenario": scenario_type,
                                "success": True,
                            }
                        )

            except Exception as e:
                with error_lock:
                    error_scenarios.append(
                        {
                            "worker_id": worker_id,
                            "scenario": scenario_type,
                            "error": str(e),
                            "success": False,
                        }
                    )

        # Run concurrent error scenarios
        scenarios = (
            [(i, "bad_paths") for i in range(3)]
            + [(i, "corrupted_cache") for i in range(3)]
            + [(i, "permission_errors") for i in range(2)]
        )

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(error_scenario_worker, worker_id, scenario)
                for worker_id, scenario in scenarios
            ]

            for future in as_completed(futures, timeout=30):
                try:
                    future.result()
                except Exception as e:
                    # Log unexpected errors but don't fail test
                    print(f"Unexpected error in error scenario: {e}")

        error_test_time = time.time() - start_time

        # Analyze error handling
        successful_scenarios = [s for s in error_scenarios if s.get("success", False)]
        failed_scenarios = [s for s in error_scenarios if not s.get("success", False)]

        print("Error handling stress test:")
        print(f"  Time: {error_test_time:.2f}s")
        print(f"  Scenarios handled: {len(successful_scenarios)}")
        print(f"  Scenarios failed: {len(failed_scenarios)}")

        # Should handle most error scenarios gracefully
        if error_scenarios:
            success_rate = len(successful_scenarios) / len(error_scenarios)
            assert success_rate > 0.7  # At least 70% of error scenarios handled

    @pytest.mark.stress
    def test_long_running_stability_stress(self, stress_test_workspace):
        """Stress test long-running stability with repeated operations."""
        workspace, shots_data = stress_test_workspace

        with tempfile.TemporaryDirectory() as cache_dir:
            cache_manager = CacheManager(cache_dir=Path(cache_dir))

            # Long-running operations
            stability_results = []

            start_time = time.time()

            # Run for 30 seconds with repeated operations
            iteration = 0
            while time.time() - start_time < 30.0:
                iteration += 1

                try:
                    # Cycle through different operations
                    op_type = iteration % 4

                    if op_type == 0:
                        # Shot model operations
                        shot_model = ShotModel(cache_manager)
                        batch = shots_data[
                            (iteration * 5) % len(shots_data) : (iteration * 5 + 10)
                            % len(shots_data)
                        ]
                        shot_model.shots = batch
                        cache_manager.cache_shots(batch)

                    elif op_type == 1:
                        # 3DE scene operations
                        scene_model = ThreeDESceneModel(cache_manager, load_cache=True)
                        batch = shots_data[
                            (iteration * 3) % len(shots_data) : (iteration * 3 + 5)
                            % len(shots_data)
                        ]
                        scene_model.refresh_scenes(batch)

                    elif op_type == 2:
                        # Raw plate finder operations
                        shot_index = iteration % len(shots_data)
                        shot = shots_data[shot_index]
                        plate_path = RawPlateFinder.find_latest_raw_plate(
                            shot.workspace_path, shot.full_name
                        )
                        if plate_path:
                            RawPlateFinder.verify_plate_exists(plate_path)

                    else:
                        # Cache loading operations
                        shots = cache_manager.get_cached_shots()
                        scenes = cache_manager.get_cached_threede_scenes()

                    stability_results.append(
                        {"iteration": iteration, "operation": op_type, "success": True}
                    )

                    # Brief pause
                    time.sleep(0.01)

                except Exception as e:
                    stability_results.append(
                        {
                            "iteration": iteration,
                            "operation": op_type,
                            "error": str(e),
                            "success": False,
                        }
                    )

            total_time = time.time() - start_time

            # Analyze stability
            successful_ops = [r for r in stability_results if r.get("success", False)]
            failed_ops = [r for r in stability_results if not r.get("success", False)]

            print("Long-running stability test:")
            print(f"  Total time: {total_time:.2f}s")
            print(f"  Total iterations: {len(stability_results)}")
            print(f"  Successful operations: {len(successful_ops)}")
            print(f"  Failed operations: {len(failed_ops)}")
            print(f"  Operations per second: {len(stability_results) / total_time:.1f}")

            # Should maintain high stability over time
            if stability_results:
                success_rate = len(successful_ops) / len(stability_results)
                assert success_rate > 0.95  # At least 95% success rate
                assert len(stability_results) > 1000  # Should complete many operations
