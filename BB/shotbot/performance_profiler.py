#!/usr/bin/env python3
"""
ShotBot Performance Profiler

This script provides comprehensive performance analysis of ShotBot components.
Run this in the ShotBot directory with the virtual environment activated.

Usage:
    python performance_profiler.py [--component=all] [--verbose] [--output=report.json]
"""

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil


# Performance monitoring utilities
class PerformanceMonitor:
    """Utility class for measuring performance metrics."""

    def __init__(self):
        self.metrics = {}
        self.start_memory = None
        self.process = psutil.Process()

    @contextmanager
    def measure_time(self, operation_name: str):
        """Context manager for measuring execution time."""
        start_time = time.perf_counter()
        start_memory = self.process.memory_info().rss

        try:
            yield
        finally:
            end_time = time.perf_counter()
            end_memory = self.process.memory_info().rss

            duration = (end_time - start_time) * 1000  # Convert to milliseconds
            memory_delta = (end_memory - start_memory) / 1024 / 1024  # Convert to MB

            self.metrics[operation_name] = {
                "duration_ms": duration,
                "memory_delta_mb": memory_delta,
                "timestamp": datetime.now().isoformat(),
            }

    @contextmanager
    def measure_memory(self, operation_name: str):
        """Context manager for detailed memory profiling."""
        tracemalloc.start()
        start_memory = self.process.memory_info().rss

        try:
            yield
        finally:
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            end_memory = self.process.memory_info().rss

            self.metrics[f"{operation_name}_memory"] = {
                "current_mb": current / 1024 / 1024,
                "peak_mb": peak / 1024 / 1024,
                "rss_delta_mb": (end_memory - start_memory) / 1024 / 1024,
                "timestamp": datetime.now().isoformat(),
            }


# Component-specific profilers
class CacheManagerProfiler:
    """Profile cache_manager.py operations."""

    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor

    def profile_cache_operations(self, iterations: int = 1000):
        """Profile cache lookup and storage operations."""
        print(f"🔍 Profiling cache operations ({iterations} iterations)...")

        try:
            from cache_manager import CacheManager

            # Create temporary cache for testing
            with tempfile.TemporaryDirectory() as temp_dir:
                cache_manager = CacheManager(Path(temp_dir))

                # Profile cache lookups
                with self.monitor.measure_time("cache_lookup_batch"):
                    for i in range(iterations):
                        _ = cache_manager.get_cached_thumbnail(
                            "test_show", "seq01", f"shot_{i:03d}"
                        )

                # Profile memory usage reporting
                with self.monitor.measure_time("memory_reporting"):
                    for _ in range(100):
                        _ = cache_manager.get_memory_usage()

                # Profile cache validation
                with self.monitor.measure_memory("cache_validation"):
                    _ = cache_manager.validate_cache()

                print("✓ Cache operations profiled")

        except ImportError as e:
            print(f"❌ Failed to import cache_manager: {e}")
        except Exception as e:
            print(f"❌ Cache profiling failed: {e}")


class SceneFinderProfiler:
    """Profile threede_scene_finder.py operations."""

    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor

    def profile_regex_patterns(self, iterations: int = 10000):
        """Profile regex pattern compilation and matching performance."""
        print(f"🔍 Profiling regex patterns ({iterations} iterations)...")

        try:
            # Test patterns from 3DE scene finder
            patterns = [
                r"^[bf]g\d{2}$",
                r"^plate_?\d+$",
                r"^comp_?\d+$",
                r"^shot_?\d+$",
                r"^[\w]+_v\d{3}$",
            ]

            # Test compilation time
            with self.monitor.measure_time("regex_compilation"):
                compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

            # Test matching performance
            test_strings = [
                "bg01",
                "fg02",
                "plate_01",
                "comp01",
                "shot_010",
                "element_v001",
                "nomatch",
            ]

            with self.monitor.measure_time("regex_matching"):
                for _ in range(iterations):
                    for test_str in test_strings:
                        for pattern in compiled_patterns:
                            _ = pattern.match(test_str)

            print("✓ Regex patterns profiled")

        except Exception as e:
            print(f"❌ Regex profiling failed: {e}")

    def profile_path_operations(self, iterations: int = 1000):
        """Profile common path operations."""
        print(f"🔍 Profiling path operations ({iterations} iterations)...")

        # Create test paths typical of VFX pipeline
        test_paths = [
            "/shows/test_show/shots/seq01/shot001",
            "/shows/another_show/shots/seq02/shot002/user/testuser/mm/3de/scenes",
            "/shows/big_show/shots/vfx_seq/vfx_shot_0010/publish/editorial/cutref/v001",
            "/shows/complex/shots/action_seq/action_010/user/artist/mm/3de/mm-default/exports/scene/bg01",
        ]

        # Test Path() creation and operations
        with self.monitor.measure_time("path_creation"):
            for _ in range(iterations):
                for path_str in test_paths:
                    path_obj = Path(path_str)
                    _ = path_obj.name
                    _ = path_obj.parent
                    _ = path_obj.parts
                    _ = str(path_obj)

        # Test relative path operations (common in scene finder)
        base_path = Path("/shows/test_show/shots/seq01/shot001/user/testuser")
        test_files = [
            base_path / "mm/3de/scenes/bg01_v001.3de",
            base_path / "mm/3de/exports/scene/fg01/tracking.3de",
            base_path / "work/3de/comp01.3DE",
        ]

        with self.monitor.measure_time("relative_path_ops"):
            for _ in range(iterations):
                for file_path in test_files:
                    try:
                        _ = file_path.relative_to(base_path)
                        _ = file_path.parts
                    except ValueError:
                        _ = file_path.parent.name

        print("✓ Path operations profiled")


class ShotModelProfiler:
    """Profile shot_model.py operations."""

    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor

    def profile_model_operations(self):
        """Profile shot model initialization and operations."""
        print("🔍 Profiling shot model operations...")

        try:
            from shot_model import Shot, ShotModel

            # Profile model initialization
            with self.monitor.measure_time("shot_model_init"):
                # Initialize without loading cache to avoid filesystem dependencies
                ShotModel(load_cache=False)

            # Create test shots
            test_shots = []
            for i in range(100):
                shot = Shot(
                    show=f"test_show_{i // 20}",
                    sequence=f"seq_{i // 10:02d}",
                    shot=f"shot_{i:03d}",
                    workspace_path=f"/shows/test_show_{i // 20}/shots/seq_{i // 10:02d}/shot_{i:03d}",
                )
                test_shots.append(shot)

            # Profile shot operations
            with self.monitor.measure_time("shot_dict_conversion"):
                shot_dicts = [shot.to_dict() for shot in test_shots]

            with self.monitor.measure_time("shot_from_dict"):
                [Shot.from_dict(shot_dict) for shot_dict in shot_dicts]

            # Profile change detection (set operations)
            old_shot_data = {
                (shot.full_name, shot.workspace_path) for shot in test_shots[:80]
            }
            new_shot_data = {
                (shot.full_name, shot.workspace_path) for shot in test_shots[20:]
            }

            with self.monitor.measure_time("change_detection"):
                for _ in range(1000):
                    _ = old_shot_data != new_shot_data
                    _ = old_shot_data - new_shot_data  # Removed shots
                    _ = new_shot_data - old_shot_data  # Added shots

            print("✓ Shot model operations profiled")

        except ImportError as e:
            print(f"❌ Failed to import shot_model: {e}")
        except Exception as e:
            print(f"❌ Shot model profiling failed: {e}")


class ConfigProfiler:
    """Profile config.py access patterns."""

    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor

    def profile_config_access(self, iterations: int = 10000):
        """Profile configuration attribute access performance."""
        print(f"🔍 Profiling config access ({iterations} iterations)...")

        try:
            from config import Config

            # Profile frequent config accesses
            with self.monitor.measure_time("config_attribute_access"):
                for _ in range(iterations):
                    _ = Config.DEFAULT_THUMBNAIL_SIZE
                    _ = Config.CACHE_EXPIRY_MINUTES
                    _ = Config.MAX_THUMBNAIL_THREADS
                    _ = Config.SHOWS_ROOT
                    _ = Config.APPS
                    _ = Config.THUMBNAIL_SPACING
                    _ = Config.GRID_COLUMNS

            print("✓ Config access profiled")

        except ImportError as e:
            print(f"❌ Failed to import config: {e}")
        except Exception as e:
            print(f"❌ Config profiling failed: {e}")


class OverallProfiler:
    """Main profiler coordinator."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.monitor = PerformanceMonitor()
        self.setup_logging()

    def setup_logging(self):
        """Configure logging for profiling."""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(
            level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    def profile_imports(self):
        """Profile module import times."""
        print("🔍 Profiling module imports...")

        modules_to_test = [
            "config",
            "utils",
            "cache_manager",
            "shot_model",
            "threede_scene_finder",
            "launcher_manager",
        ]

        import_times = {}
        for module in modules_to_test:
            start_time = time.perf_counter()
            try:
                __import__(module)
                import_time = (time.perf_counter() - start_time) * 1000
                import_times[module] = import_time
                print(f"  {module:20s}: {import_time:6.2f}ms")
            except ImportError as e:
                import_times[module] = -1  # Failed
                print(f"  {module:20s}: FAILED - {e}")

        self.monitor.metrics["import_times"] = import_times
        print("✓ Module imports profiled")

    def run_full_profile(self):
        """Run comprehensive performance profiling."""
        print("🚀 Starting ShotBot Performance Profiling")
        print("=" * 50)

        # System info
        print(f"Python version: {sys.version}")
        print(f"Platform: {sys.platform}")
        print(f"CPU count: {os.cpu_count()}")
        print(
            f"Available memory: {psutil.virtual_memory().total / 1024 / 1024 / 1024:.1f} GB"
        )
        print()

        # Profile imports
        self.profile_imports()
        print()

        # Profile individual components
        try:
            config_profiler = ConfigProfiler(self.monitor)
            config_profiler.profile_config_access()
            print()

            scene_profiler = SceneFinderProfiler(self.monitor)
            scene_profiler.profile_regex_patterns()
            scene_profiler.profile_path_operations()
            print()

            shot_profiler = ShotModelProfiler(self.monitor)
            shot_profiler.profile_model_operations()
            print()

            cache_profiler = CacheManagerProfiler(self.monitor)
            cache_profiler.profile_cache_operations()
            print()

        except Exception as e:
            print(f"❌ Profiling error: {e}")
            if self.verbose:
                import traceback

                traceback.print_exc()

    def generate_report(self, output_file: Optional[str] = None):
        """Generate performance report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "python_version": sys.version,
            "platform": sys.platform,
            "cpu_count": os.cpu_count(),
            "memory_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            "metrics": self.monitor.metrics,
        }

        if output_file:
            with open(output_file, "w") as f:
                json.dump(report, f, indent=2)
            print(f"📊 Performance report saved to: {output_file}")

        # Print summary
        print("\n" + "=" * 50)
        print("📈 PERFORMANCE SUMMARY")
        print("=" * 50)

        # Key metrics summary
        key_metrics = [
            ("config_attribute_access", "Config Access"),
            ("regex_compilation", "Regex Compilation"),
            ("regex_matching", "Regex Matching"),
            ("path_creation", "Path Operations"),
            ("shot_model_init", "Shot Model Init"),
            ("change_detection", "Change Detection"),
            ("cache_lookup_batch", "Cache Lookups"),
        ]

        for metric_key, display_name in key_metrics:
            if metric_key in self.monitor.metrics:
                duration = self.monitor.metrics[metric_key]["duration_ms"]
                print(f"{display_name:20s}: {duration:8.2f}ms")

        return report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ShotBot Performance Profiler")
    parser.add_argument(
        "--component",
        default="all",
        choices=["all", "cache", "scenes", "shots", "config"],
        help="Component to profile",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--output", help="Output file for performance report (JSON format)"
    )

    args = parser.parse_args()

    profiler = OverallProfiler(verbose=args.verbose)

    try:
        profiler.run_full_profile()
        profiler.generate_report(args.output)

        print("\n✅ Performance profiling completed successfully!")

        # Performance recommendations based on results
        print("\n" + "=" * 50)
        print("🎯 OPTIMIZATION RECOMMENDATIONS")
        print("=" * 50)

        metrics = profiler.monitor.metrics

        # Config access performance
        if "config_attribute_access" in metrics:
            config_time = metrics["config_attribute_access"]["duration_ms"]
            if config_time > 50:  # More than 50ms for 10k accesses
                print("⚠️  Config access is slower than expected")
                print(
                    "   Recommendation: Consider caching frequently accessed config values"
                )

        # Regex performance
        if "regex_matching" in metrics:
            regex_time = metrics["regex_matching"]["duration_ms"]
            if regex_time > 200:  # More than 200ms for 10k iterations
                print("⚠️  Regex matching performance could be improved")
                print(
                    "   Recommendation: Combine patterns or use more efficient algorithms"
                )

        # Path operations
        if "path_creation" in metrics:
            path_time = metrics["path_creation"]["duration_ms"]
            if path_time > 100:  # More than 100ms for 1k operations
                print("⚠️  Path operations are expensive")
                print(
                    "   Recommendation: Cache Path objects or use string operations where possible"
                )

        # Cache operations
        if "cache_lookup_batch" in metrics:
            cache_time = metrics["cache_lookup_batch"]["duration_ms"]
            if cache_time > 500:  # More than 500ms for 1k lookups
                print("⚠️  Cache lookups are slower than expected")
                print(
                    "   Recommendation: Optimize cache data structure or reduce lock contention"
                )

        if not any("⚠️" in line for line in []):
            print("✅ All measured operations are performing within acceptable ranges!")

    except Exception as e:
        print(f"❌ Profiling failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
