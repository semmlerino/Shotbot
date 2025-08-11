"""Performance regression testing for ShotBot.

This module provides automated performance baselines, benchmarking,
and memory leak detection to catch performance regressions early.
"""

import gc
import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil
import pytest


@dataclass
class PerformanceMetric:
    """Represents a performance measurement."""

    name: str
    value: float
    unit: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceBaseline:
    """Performance baseline for comparison."""

    test_name: str
    metrics: Dict[str, PerformanceMetric]
    threshold_percentages: Dict[str, float] = field(default_factory=dict)

    def is_regression(self, metric_name: str, value: float) -> bool:
        """Check if a value represents a performance regression.

        Args:
            metric_name: Name of the metric
            value: Current value to check

        Returns:
            True if value is a regression
        """
        if metric_name not in self.metrics:
            return False

        baseline_value = self.metrics[metric_name].value
        threshold = self.threshold_percentages.get(metric_name, 20.0)  # 20% default

        # For time/memory metrics, higher is worse
        max_allowed = baseline_value * (1 + threshold / 100)
        return value > max_allowed


class PerformanceBenchmark:
    """Benchmark runner for performance tests."""

    def __init__(self, warmup_runs: int = 2, test_runs: int = 10):
        """Initialize benchmark runner.

        Args:
            warmup_runs: Number of warmup iterations
            test_runs: Number of test iterations
        """
        self.warmup_runs = warmup_runs
        self.test_runs = test_runs
        self.results: List[PerformanceMetric] = []

    def benchmark(self, func: Callable, *args, **kwargs) -> Dict[str, float]:
        """Benchmark a function.

        Args:
            func: Function to benchmark
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Dictionary of performance metrics
        """
        # Warmup runs
        for _ in range(self.warmup_runs):
            func(*args, **kwargs)

        # Collect garbage before measurement
        gc.collect()

        # Measure execution times
        times = []
        for _ in range(self.test_runs):
            start = time.perf_counter()
            func(*args, **kwargs)
            end = time.perf_counter()
            times.append(end - start)

        # Calculate statistics
        times.sort()
        metrics = {
            "min_time": min(times),
            "max_time": max(times),
            "mean_time": sum(times) / len(times),
            "median_time": times[len(times) // 2],
            "p95_time": times[int(len(times) * 0.95)],
            "p99_time": times[int(len(times) * 0.99)],
        }

        # Store results
        for name, value in metrics.items():
            self.results.append(PerformanceMetric(name, value, "seconds"))

        return metrics

    def benchmark_memory(self, func: Callable, *args, **kwargs) -> Dict[str, float]:
        """Benchmark memory usage of a function.

        Args:
            func: Function to benchmark
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Dictionary of memory metrics
        """
        gc.collect()

        # Start memory tracing
        tracemalloc.start()

        # Get initial memory
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Run function
        func(*args, **kwargs)

        # Get peak memory
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        final_memory = process.memory_info().rss / 1024 / 1024  # MB

        metrics = {
            "peak_memory_mb": peak / 1024 / 1024,
            "current_memory_mb": current / 1024 / 1024,
            "memory_delta_mb": final_memory - initial_memory,
        }

        # Store results
        for name, value in metrics.items():
            self.results.append(PerformanceMetric(name, value, "MB"))

        return metrics


class MemoryLeakDetector:
    """Detect memory leaks in functions and classes."""

    def __init__(self, threshold_mb: float = 10.0):
        """Initialize memory leak detector.

        Args:
            threshold_mb: Memory increase threshold in MB
        """
        self.threshold_mb = threshold_mb
        self.snapshots: List[Tuple[str, tracemalloc.Snapshot]] = []

    def check_leak(
        self, func: Callable, iterations: int = 100, *args, **kwargs
    ) -> Dict[str, Any]:
        """Check for memory leaks in a function.

        Args:
            func: Function to test
            iterations: Number of iterations
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Dictionary with leak detection results
        """
        gc.collect()
        tracemalloc.start()

        # Take initial snapshot
        snapshot1 = tracemalloc.take_snapshot()

        # Run function multiple times
        for _ in range(iterations):
            func(*args, **kwargs)

        gc.collect()

        # Take final snapshot
        snapshot2 = tracemalloc.take_snapshot()

        # Compare snapshots
        top_stats = snapshot2.compare_to(snapshot1, "lineno")

        # Calculate total memory increase
        total_increase = sum(stat.size_diff for stat in top_stats) / 1024 / 1024  # MB

        # Find top memory increases
        leaks = []
        for stat in top_stats[:10]:
            if stat.size_diff > 0:
                leaks.append(
                    {
                        "file": stat.traceback.format()[0],
                        "size_mb": stat.size_diff / 1024 / 1024,
                        "count_diff": stat.count_diff,
                    }
                )

        tracemalloc.stop()

        return {
            "has_leak": total_increase > self.threshold_mb,
            "total_increase_mb": total_increase,
            "iterations": iterations,
            "top_increases": leaks[:5],
        }

    def monitor_object_lifecycle(
        self,
        obj_factory: Callable,
        operations: List[Callable],
        cleanup: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Monitor object lifecycle for leaks.

        Args:
            obj_factory: Factory function to create object
            operations: List of operations to perform on object
            cleanup: Optional cleanup function

        Returns:
            Lifecycle analysis results
        """
        gc.collect()

        # Track object count before
        initial_objects = len(gc.get_objects())

        # Create and use object
        obj = obj_factory()

        for operation in operations:
            operation(obj)

        # Cleanup
        if cleanup:
            cleanup(obj)

        del obj
        gc.collect()

        # Check object count after
        final_objects = len(gc.get_objects())

        return {
            "objects_leaked": final_objects - initial_objects,
            "initial_count": initial_objects,
            "final_count": final_objects,
        }


@pytest.fixture
def performance_benchmark():
    """Pytest fixture for performance benchmarking."""
    return PerformanceBenchmark()


@pytest.fixture
def memory_detector():
    """Pytest fixture for memory leak detection."""
    return MemoryLeakDetector()


@pytest.mark.performance
class TestShotModelPerformance:
    """Performance tests for ShotModel."""

    def test_shot_refresh_performance(self, performance_benchmark):
        """Test performance of shot refresh operation."""
        from shot_model import ShotModel

        model = ShotModel()

        # Benchmark refresh operation
        metrics = performance_benchmark.benchmark(model.refresh_shots)

        # Assert performance thresholds
        assert metrics["median_time"] < 2.0, "Shot refresh too slow"
        assert metrics["p95_time"] < 3.0, "Shot refresh P95 too slow"

    def test_shot_model_memory_usage(self, performance_benchmark):
        """Test memory usage of shot model with large dataset."""
        from unittest.mock import patch

        from shot_model import ShotModel

        model = ShotModel()

        # Mock large shot list
        large_shot_list = [f"SHOT_{i:04d}" for i in range(10000)]

        with patch.object(model, "_parse_shot_output", return_value=large_shot_list):
            metrics = performance_benchmark.benchmark_memory(model.refresh_shots)

        # Assert memory thresholds
        assert metrics["peak_memory_mb"] < 100, "Excessive memory usage"

    def test_shot_model_memory_leak(self, memory_detector):
        """Test for memory leaks in shot model operations."""
        from shot_model import ShotModel

        def create_and_refresh():
            model = ShotModel()
            model.refresh_shots()
            model.get_shots()
            return model

        # Check for leaks
        result = memory_detector.check_leak(create_and_refresh, iterations=50)

        assert not result["has_leak"], (
            f"Memory leak detected: {result['total_increase_mb']:.2f} MB increase"
        )


@pytest.mark.performance
class TestCachePerformance:
    """Performance tests for cache manager."""

    def test_cache_lookup_performance(self, performance_benchmark):
        """Test cache lookup performance with many entries."""
        from cache_manager import CacheManager

        cache = CacheManager()

        # Populate cache with many entries
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}", ttl=300)

        # Benchmark lookup
        def lookup_operations():
            for i in range(100):
                cache.get(f"key_{i % 1000}")

        metrics = performance_benchmark.benchmark(lookup_operations)

        # Assert lookup is fast
        assert metrics["mean_time"] < 0.01, "Cache lookup too slow"

    def test_cache_memory_efficiency(self, performance_benchmark):
        """Test memory efficiency of cache with large values."""
        from cache_manager import CacheManager

        cache = CacheManager()

        # Create large cached values
        large_value = "x" * 10000  # 10KB string

        def populate_cache():
            for i in range(100):
                cache.set(f"large_{i}", large_value, ttl=300)

        metrics = performance_benchmark.benchmark_memory(populate_cache)

        # Check memory usage is reasonable
        assert metrics["memory_delta_mb"] < 10, "Cache using too much memory"

    def test_cache_expiration_performance(self, performance_benchmark):
        """Test performance of cache expiration checks."""
        import time

        from cache_manager import CacheManager

        cache = CacheManager()

        # Add many expired entries
        for i in range(1000):
            cache.set(f"expire_{i}", "value", ttl=0.001)

        time.sleep(0.002)

        # Benchmark expiration checks
        def check_expired():
            for i in range(1000):
                cache.get(f"expire_{i}")

        metrics = performance_benchmark.benchmark(check_expired)

        # Expiration checks should be fast
        assert metrics["mean_time"] < 0.1, "Expiration checks too slow"


@pytest.mark.performance
class TestFinderPerformance:
    """Performance tests for finder components."""

    def test_plate_finder_performance(self, performance_benchmark):
        """Test raw plate finder performance."""
        from unittest.mock import patch

        from raw_plate_finder import RawPlateFinder

        # Mock filesystem operations
        with patch(
            "raw_plate_finder.PathUtils.validate_path_exists", return_value=True
        ):
            with patch(
                "raw_plate_finder.PathUtils.discover_plate_directories",
                return_value=[("FG01", 0), ("BG01", 1)],
            ):
                with patch(
                    "raw_plate_finder.VersionUtils.get_latest_version",
                    return_value="v001",
                ):
                    with patch("pathlib.Path.exists", return_value=True):
                        with patch("pathlib.Path.iterdir", return_value=[]):
                            metrics = performance_benchmark.benchmark(
                                RawPlateFinder.find_latest_raw_plate,
                                "/test/path",
                                "TEST_0001",
                            )

        # Should be very fast with mocked I/O
        assert metrics["mean_time"] < 0.01, "Plate finder too slow"

    def test_threede_finder_performance(self, performance_benchmark):
        """Test 3DE scene finder performance."""
        from unittest.mock import patch

        from threede_scene_finder import ThreeDESceneFinder

        finder = ThreeDESceneFinder()

        # Mock filesystem operations
        with patch.object(finder, "_discover_users", return_value=["user1", "user2"]):
            with patch.object(finder, "_find_user_scenes", return_value=[]):
                metrics = performance_benchmark.benchmark(
                    finder.find_other_users_scenes, "/test/workspace"
                )

        # Should be fast with mocked I/O
        assert metrics["mean_time"] < 0.05, "3DE finder too slow"

    def test_threede_deduplication_performance(self, performance_benchmark):
        """Test performance of 3DE scene deduplication."""
        from threede_scene_finder import ThreeDESceneFinder
        from threede_scene_model import ThreeDEScene

        finder = ThreeDESceneFinder()

        # Create many duplicate scenes
        scenes = []
        for i in range(100):
            for j in range(5):  # 5 duplicates each
                scenes.append(
                    ThreeDEScene(
                        path=f"/path/user{j}/scene_{i:03d}.3de",
                        user=f"user{j}",
                        shot_name=f"SHOT_{i:04d}",
                        plate_name=f"plate_{i}",
                        file_size=1000 * (j + 1),
                        modified_time=time.time() - j * 3600,
                    )
                )

        # Benchmark deduplication
        metrics = performance_benchmark.benchmark(finder._deduplicate_scenes, scenes)

        # Should handle deduplication efficiently
        assert metrics["mean_time"] < 0.1, "Deduplication too slow"


@pytest.mark.performance
class TestUIPerformance:
    """Performance tests for UI components."""

    def test_grid_widget_scaling(self, qtbot, performance_benchmark):
        """Test grid widget performance with many items."""
        from shot_grid import ShotGrid

        grid = ShotGrid()
        qtbot.addWidget(grid)

        # Benchmark adding many items
        def add_many_shots():
            for i in range(100):
                grid.add_shot(f"SHOT_{i:04d}", f"/path/{i}")

        metrics = performance_benchmark.benchmark(add_many_shots)

        # Should scale well
        assert metrics["mean_time"] < 1.0, "Grid scaling poor"

    def test_thumbnail_loading_performance(self, qtbot, performance_benchmark):
        """Test thumbnail widget loading performance."""
        from unittest.mock import MagicMock, patch

        from thumbnail_widget import ThumbnailWidget

        # Mock image loading
        mock_pixmap = MagicMock()
        with patch("PySide6.QtGui.QPixmap.load", return_value=True):

            def create_thumbnails():
                widgets = []
                for i in range(50):
                    widget = ThumbnailWidget(f"SHOT_{i:04d}")
                    qtbot.addWidget(widget)
                    widgets.append(widget)
                return widgets

            metrics = performance_benchmark.benchmark(create_thumbnails)

        # Should handle many thumbnails efficiently
        assert metrics["mean_time"] < 0.5, "Thumbnail creation too slow"


class PerformanceReporter:
    """Generate performance test reports."""

    @staticmethod
    def generate_report(
        benchmarks: List[PerformanceBenchmark],
        baselines: Optional[Dict[str, PerformanceBaseline]] = None,
    ) -> str:
        """Generate performance report.

        Args:
            benchmarks: List of benchmark results
            baselines: Optional baselines for comparison

        Returns:
            Formatted report string
        """
        report = ["Performance Test Report", "=" * 50, ""]

        for benchmark in benchmarks:
            report.append("Benchmark Results:")
            report.append("-" * 30)

            for metric in benchmark.results:
                line = f"{metric.name}: {metric.value:.4f} {metric.unit}"

                # Check against baseline if available
                if baselines and metric.name in baselines:
                    baseline = baselines[metric.name]
                    if baseline.is_regression(metric.name, metric.value):
                        line += " ⚠️ REGRESSION"
                    else:
                        line += " ✓"

                report.append(line)

            report.append("")

        return "\n".join(report)

    @staticmethod
    def save_baseline(benchmark: PerformanceBenchmark, filepath: Path):
        """Save benchmark results as baseline.

        Args:
            benchmark: Benchmark with results
            filepath: Path to save baseline
        """
        import json

        baseline_data = {"timestamp": datetime.now().isoformat(), "metrics": {}}

        for metric in benchmark.results:
            baseline_data["metrics"][metric.name] = {
                "value": metric.value,
                "unit": metric.unit,
            }

        with open(filepath, "w") as f:
            json.dump(baseline_data, f, indent=2)


# CI/CD Integration
class CIPerformanceMonitor:
    """Monitor performance in CI/CD pipeline."""

    @staticmethod
    def check_regression(
        current_metrics: Dict[str, float],
        baseline_file: Path,
        threshold_percent: float = 20.0,
    ) -> Tuple[bool, List[str]]:
        """Check for performance regression against baseline.

        Args:
            current_metrics: Current performance metrics
            baseline_file: Path to baseline file
            threshold_percent: Regression threshold percentage

        Returns:
            Tuple of (has_regression, list of regressions)
        """
        import json

        if not baseline_file.exists():
            return False, ["No baseline found"]

        with open(baseline_file, "r") as f:
            baseline_data = json.load(f)

        regressions = []

        for metric_name, current_value in current_metrics.items():
            if metric_name in baseline_data["metrics"]:
                baseline_value = baseline_data["metrics"][metric_name]["value"]

                # Check if regression
                max_allowed = baseline_value * (1 + threshold_percent / 100)
                if current_value > max_allowed:
                    regressions.append(
                        f"{metric_name}: {current_value:.4f} > {max_allowed:.4f} "
                        f"(baseline: {baseline_value:.4f})"
                    )

        return len(regressions) > 0, regressions


if __name__ == "__main__":
    # Example: Run performance benchmarks
    benchmark = PerformanceBenchmark()

    # Example function to benchmark
    def example_operation():
        time.sleep(0.001)  # Simulate work
        data = list(range(1000))
        return sum(data)

    print("Running performance benchmark...")
    metrics = benchmark.benchmark(example_operation)

    print("\nPerformance Metrics:")
    for name, value in metrics.items():
        print(f"  {name}: {value:.6f} seconds")

    # Check for memory leaks
    detector = MemoryLeakDetector()
    leak_result = detector.check_leak(example_operation, iterations=100)

    print("\nMemory Leak Check:")
    print(f"  Has leak: {leak_result['has_leak']}")
    print(f"  Total increase: {leak_result['total_increase_mb']:.2f} MB")
