"""Performance benchmark tests for critical code paths."""

import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from cache_manager import CacheManager
from raw_plate_finder import RawPlateFinder
from threede_scene_model import ThreeDESceneModel
from thumbnail_widget_base import FolderOpenerWorker
from utils import PathUtils


class PerformanceMetrics:
    """Helper class to track performance metrics."""

    def __init__(self):
        self.execution_times: List[float] = []
        self.memory_usage: List[int] = []
        self.cache_hits = 0
        self.cache_misses = 0

    def measure_time(self, func, *args, **kwargs):
        """Measure execution time of a function."""
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        self.execution_times.append(elapsed)
        return result, elapsed

    def measure_memory(self, func, *args, **kwargs):
        """Measure memory usage of a function."""
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        result = func(*args, **kwargs)

        snapshot_after = tracemalloc.take_snapshot()
        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")

        total_memory = sum(stat.size_diff for stat in top_stats)
        self.memory_usage.append(total_memory)

        tracemalloc.stop()
        return result, total_memory

    def get_statistics(self) -> Dict[str, Any]:
        """Get performance statistics."""
        if self.execution_times:
            avg_time = sum(self.execution_times) / len(self.execution_times)
            max_time = max(self.execution_times)
            min_time = min(self.execution_times)
        else:
            avg_time = max_time = min_time = 0

        if self.memory_usage:
            avg_memory = sum(self.memory_usage) / len(self.memory_usage)
            max_memory = max(self.memory_usage)
        else:
            avg_memory = max_memory = 0

        cache_hit_rate = (
            self.cache_hits / (self.cache_hits + self.cache_misses)
            if (self.cache_hits + self.cache_misses) > 0
            else 0
        )

        return {
            "avg_time": avg_time,
            "max_time": max_time,
            "min_time": min_time,
            "avg_memory": avg_memory,
            "max_memory": max_memory,
            "cache_hit_rate": cache_hit_rate,
            "total_operations": len(self.execution_times),
        }


@pytest.mark.performance
class TestRawPlateFinderPerformance:
    """Performance tests for raw plate finder."""

    def setup_large_plate_structure(
        self, base_path: Path, num_plates=10, num_versions=5, num_frames=1000
    ):
        """Create a large plate directory structure for testing."""
        shot_name = "PERF_TEST_001"
        plate_base = base_path / "publish" / "turnover" / "plate" / "input_plate"

        for plate_idx in range(num_plates):
            plate_name = (
                f"FG{plate_idx:02d}" if plate_idx % 2 == 0 else f"BG{plate_idx:02d}"
            )

            for version_idx in range(num_versions):
                version = f"v{version_idx + 1:03d}"
                resolution_dir = plate_base / plate_name / version / "exr" / "4096x2160"
                resolution_dir.mkdir(parents=True)

                # Create frame files
                for frame in range(1001, 1001 + num_frames):
                    plate_file = (
                        resolution_dir
                        / f"{shot_name}_turnover-plate_{plate_name}_aces_{version}.{frame:04d}.exr"
                    )
                    plate_file.touch()

        return plate_base

    def test_plate_discovery_performance(self):
        """Test performance of plate discovery with large directory structure."""
        metrics = PerformanceMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            plate_base = self.setup_large_plate_structure(
                base, num_plates=20, num_versions=10, num_frames=100
            )

            # Measure discovery performance
            _, elapsed = metrics.measure_time(
                PathUtils.discover_plate_directories, plate_base
            )

            # Should complete quickly even with many directories
            assert elapsed < 0.5, (
                f"Plate discovery took {elapsed:.3f}s, expected < 0.5s"
            )

            # Test with pattern matching optimization
            for _ in range(100):
                _, elapsed = metrics.measure_time(
                    PathUtils.discover_plate_directories, plate_base
                )

            stats = metrics.get_statistics()
            assert stats["avg_time"] < 0.1, (
                f"Average discovery time {stats['avg_time']:.3f}s, expected < 0.1s"
            )

    def test_regex_compilation_performance(self):
        """Test that regex patterns are efficiently compiled."""
        metrics = PerformanceMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            self.setup_large_plate_structure(
                base, num_plates=5, num_versions=3, num_frames=100
            )

            shot_path = str(base)
            shot_name = "PERF_TEST_001"

            # First run (might compile patterns)
            _, first_run = metrics.measure_time(
                RawPlateFinder.find_latest_raw_plate, shot_path, shot_name
            )

            # Subsequent runs should be faster (patterns cached)
            for _ in range(10):
                _, elapsed = metrics.measure_time(
                    RawPlateFinder.find_latest_raw_plate, shot_path, shot_name
                )

            stats = metrics.get_statistics()
            # Subsequent runs should be faster than first
            assert stats["avg_time"] <= first_run, (
                "Regex caching not working effectively"
            )

    def test_memory_usage_large_directories(self):
        """Test memory usage with large directory structures."""
        metrics = PerformanceMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            self.setup_large_plate_structure(
                base, num_plates=10, num_versions=5, num_frames=500
            )

            shot_path = str(base)
            shot_name = "PERF_TEST_001"

            # Measure memory usage
            _, memory_used = metrics.measure_memory(
                RawPlateFinder.find_latest_raw_plate, shot_path, shot_name
            )

            # Memory usage should be reasonable (< 10MB for this operation)
            assert memory_used < 10 * 1024 * 1024, (
                f"Used {memory_used / 1024 / 1024:.2f}MB, expected < 10MB"
            )


@pytest.mark.performance
class TestCachePerformance:
    """Performance tests for caching system."""

    def test_cache_hit_performance(self):
        """Test cache hit performance."""
        cache_manager = CacheManager()
        metrics = PerformanceMetrics()

        # Prepare test data
        test_data = [{"id": i, "data": f"test_{i}" * 100} for i in range(1000)]

        # Cache the data
        cache_manager.cache_threede_scenes(test_data)

        # Measure cache retrieval performance
        for _ in range(100):
            result, elapsed = metrics.measure_time(
                cache_manager.get_threede_scenes_from_cache
            )
            if result:
                metrics.cache_hits += 1
            else:
                metrics.cache_misses += 1

        stats = metrics.get_statistics()

        # Cache hits should be very fast
        assert stats["avg_time"] < 0.01, (
            f"Cache retrieval took {stats['avg_time']:.3f}s, expected < 0.01s"
        )
        assert stats["cache_hit_rate"] > 0.95, (
            f"Cache hit rate {stats['cache_hit_rate']:.2%}, expected > 95%"
        )

    def test_cache_ttl_performance(self):
        """Test cache TTL refresh performance."""
        cache_manager = CacheManager()
        metrics = PerformanceMetrics()

        test_data = [{"id": i, "data": f"test_{i}"} for i in range(100)]

        # Test TTL refresh performance
        for _ in range(50):
            cache_manager.cache_threede_scenes(test_data)
            _, elapsed = metrics.measure_time(
                cache_manager.get_threede_scenes_from_cache
            )

        stats = metrics.get_statistics()

        # TTL operations should be fast
        assert stats["avg_time"] < 0.005, (
            f"TTL operations took {stats['avg_time']:.3f}s, expected < 0.005s"
        )


@pytest.mark.performance
class TestFolderOpenerPerformance:
    """Performance tests for non-blocking folder opener."""

    def test_concurrent_folder_opening_performance(self, qtbot):
        """Test performance of concurrent folder opening."""
        from PySide6.QtCore import QThreadPool

        metrics = PerformanceMetrics()
        thread_pool = QThreadPool.globalInstance()

        with tempfile.TemporaryDirectory() as tmpdir:
            folders = []
            for i in range(20):
                folder = Path(tmpdir) / f"folder_{i}"
                folder.mkdir()
                folders.append(str(folder))

            # Mock the actual opening to measure overhead
            with patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", return_value=True
            ):
                start = time.perf_counter()

                workers = []
                for folder in folders:
                    worker = FolderOpenerWorker(folder)
                    workers.append(worker)
                    thread_pool.start(worker)

                # Wait for completion
                thread_pool.waitForDone(5000)

                elapsed = time.perf_counter() - start

            # Should handle 20 concurrent operations efficiently
            assert elapsed < 2.0, (
                f"Concurrent opening took {elapsed:.2f}s, expected < 2.0s"
            )

            # Average time per operation
            avg_per_operation = elapsed / len(folders)
            assert avg_per_operation < 0.2, (
                f"Average per operation {avg_per_operation:.3f}s, expected < 0.2s"
            )

    def test_ui_responsiveness_during_folder_opening(self, qtbot):
        """Test that UI remains responsive during folder opening."""
        from PySide6.QtCore import QThreadPool, QTimer

        ui_updates = []

        def ui_update():
            ui_updates.append(time.perf_counter())

        # Set up timer to simulate UI updates
        timer = QTimer()
        timer.timeout.connect(ui_update)
        timer.start(50)  # Update every 50ms

        with tempfile.TemporaryDirectory() as tmpdir:
            # Simulate slow folder opening
            def slow_open(url):
                time.sleep(0.2)
                return True

            with patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", side_effect=slow_open
            ):
                worker = FolderOpenerWorker(tmpdir)

                start = time.perf_counter()
                QThreadPool.globalInstance().start(worker)

                # Let UI run for a bit
                qtbot.wait(500)

                QThreadPool.globalInstance().waitForDone(1000)

        timer.stop()

        # Check that UI updates happened regularly
        assert len(ui_updates) > 5, "UI was blocked during folder opening"

        # Check update intervals
        if len(ui_updates) > 1:
            intervals = [
                ui_updates[i + 1] - ui_updates[i] for i in range(len(ui_updates) - 1)
            ]
            avg_interval = sum(intervals) / len(intervals)
            # Should be close to 50ms
            assert 0.04 < avg_interval < 0.08, (
                f"UI update interval {avg_interval:.3f}s, expected ~0.05s"
            )


@pytest.mark.performance
class Test3DEScenePerformance:
    """Performance tests for 3DE scene operations."""

    def test_deduplication_performance(self):
        """Test performance of scene deduplication."""
        from threede_scene_model import ThreeDEScene

        model = ThreeDESceneModel()
        metrics = PerformanceMetrics()

        # Create many duplicate scenes
        scenes = []
        for shot_idx in range(100):
            shot_name = f"TST_{shot_idx:03d}"
            for user_idx in range(5):
                for plate in ["FG01", "BG01", "BG02"]:
                    scene = ThreeDEScene(
                        show="testshow",
                        sequence="TST",
                        shot=f"{shot_idx:03d}",
                        workspace_path=f"/shows/testshow/shots/{shot_name}",
                        user=f"user{user_idx}",
                        plate=plate,
                        scene_path=Path(
                            f"/tmp/scene_{shot_idx}_{user_idx}_{plate}.3de"
                        ),
                    )
                    scenes.append(scene)

        # Measure deduplication performance
        _, elapsed = metrics.measure_time(model._deduplicate_scenes_by_shot, scenes)

        # Should handle 1500 scenes efficiently
        assert elapsed < 0.5, f"Deduplication took {elapsed:.3f}s, expected < 0.5s"

        # Check memory efficiency
        _, memory_used = metrics.measure_memory(
            model._deduplicate_scenes_by_shot, scenes
        )

        # Memory usage should be reasonable
        assert memory_used < 5 * 1024 * 1024, (
            f"Used {memory_used / 1024 / 1024:.2f}MB, expected < 5MB"
        )

    def test_cache_persistence_performance(self):
        """Test performance of cache persistence operations."""
        model = ThreeDESceneModel()
        metrics = PerformanceMetrics()

        # Create test scenes
        scenes = []
        for i in range(200):
            scene = ThreeDEScene(
                show="testshow",
                sequence="TST",
                shot=f"{i:03d}",
                workspace_path=f"/shows/testshow/shots/TST_{i:03d}",
                user="testuser",
                plate="BG01",
                scene_path=Path(f"/tmp/scene_{i}.3de"),
            )
            scenes.append(scene)

        model.scenes = scenes

        # Measure cache write performance
        _, write_elapsed = metrics.measure_time(
            model.cache_manager.cache_threede_scenes, model.to_dict()
        )

        assert write_elapsed < 0.1, (
            f"Cache write took {write_elapsed:.3f}s, expected < 0.1s"
        )

        # Measure cache read performance
        _, read_elapsed = metrics.measure_time(
            model.cache_manager.get_threede_scenes_from_cache
        )

        assert read_elapsed < 0.05, (
            f"Cache read took {read_elapsed:.3f}s, expected < 0.05s"
        )


def run_performance_suite():
    """Run all performance tests and generate a report."""
    import json

    results = {}

    # Run each test class
    test_classes = [
        TestRawPlateFinderPerformance,
        TestCachePerformance,
        TestFolderOpenerPerformance,
        Test3DEScenePerformance,
    ]

    for test_class in test_classes:
        class_name = test_class.__name__
        results[class_name] = {}

        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                try:
                    method = getattr(instance, method_name)
                    method()
                    results[class_name][method_name] = "PASSED"
                except AssertionError as e:
                    results[class_name][method_name] = f"FAILED: {str(e)}"
                except Exception as e:
                    results[class_name][method_name] = f"ERROR: {str(e)}"

    # Save results
    with open("performance_report.json", "w") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    # Run performance tests directly
    results = run_performance_suite()
    print("Performance Test Results:")
    for class_name, tests in results.items():
        print(f"\n{class_name}:")
        for test_name, result in tests.items():
            print(f"  {test_name}: {result}")
