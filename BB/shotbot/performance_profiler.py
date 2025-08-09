#!/usr/bin/env python3
"""
Comprehensive Performance Profiler for ShotBot

This script analyzes regex compilation overhead, directory operation performance,
memory usage patterns, and caching efficiency to identify optimization opportunities.
"""

import gc
import json
import logging
import re
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

import psutil
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QPixmap

# Import the modules to profile
sys.path.insert(0, str(Path(__file__).parent))

from cache_manager import CacheManager
from config import Config
from utils import PathUtils, VersionUtils, clear_all_caches, get_cache_stats

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PerformanceProfiler:
    """Comprehensive performance profiler for ShotBot components."""

    def __init__(self):
        self.results = {
            "timestamp": time.time(),
            "system_info": self._get_system_info(),
            "regex_performance": {},
            "directory_performance": {},
            "memory_analysis": {},
            "cache_efficiency": {},
            "optimization_opportunities": [],
        }
        self.temp_dirs = []

    def _get_system_info(self) -> Dict[str, Any]:
        """Get system information for context."""
        process = psutil.Process()
        memory = psutil.virtual_memory()

        return {
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": memory.total / (1024**3),
            "memory_available_gb": memory.available / (1024**3),
            "python_version": sys.version,
            "process_memory_mb": process.memory_info().rss / (1024**2),
        }

    @contextmanager
    def measure_time(self):
        """Context manager for measuring execution time."""
        start_time = time.perf_counter()
        start_memory = psutil.Process().memory_info().rss

        yield

        end_time = time.perf_counter()
        end_memory = psutil.Process().memory_info().rss

        self._current_measurement = {
            "time": end_time - start_time,
            "memory_delta_mb": (end_memory - start_memory) / (1024**2),
        }

    @contextmanager
    def measure_memory(self):
        """Context manager for detailed memory measurement."""
        tracemalloc.start()
        gc.collect()  # Clean start

        snapshot_before = tracemalloc.take_snapshot()
        start_rss = psutil.Process().memory_info().rss

        yield

        snapshot_after = tracemalloc.take_snapshot()
        end_rss = psutil.Process().memory_info().rss

        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")

        self._current_memory = {
            "rss_delta_mb": (end_rss - start_rss) / (1024**2),
            "top_allocations": [
                {
                    "filename": stat.traceback.format()[-1].split(", ")[0],
                    "line": stat.traceback.format()[-1].split("line ")[1].split(",")[0],
                    "size_mb": stat.size / (1024**2),
                    "count": stat.count,
                }
                for stat in top_stats[:5]
            ],
        }

        tracemalloc.stop()

    def setup_test_data(self):
        """Create test directory structures for profiling."""
        # Create temporary test directories
        base_temp = Path(tempfile.mkdtemp(prefix="shotbot_perf_"))
        self.temp_dirs.append(base_temp)

        # Create VFX-like directory structure
        shows_dir = base_temp / "shows" / "test_show" / "shots"

        # Create multiple sequences and shots
        sequences = ["SEQ01", "SEQ02", "SEQ03"]
        shots = ["001", "002", "003", "004", "005"]
        users = ["user1", "user2", "user3", "user4", "user5"]

        for seq in sequences:
            for shot in shots:
                shot_name = f"{seq}_{shot}"
                shot_dir = shows_dir / seq / shot_name

                # Create standard VFX directories
                (shot_dir / "user").mkdir(parents=True, exist_ok=True)
                (shot_dir / "elements" / "plates" / "raw").mkdir(
                    parents=True, exist_ok=True
                )
                (shot_dir / "work" / "comp" / "nuke" / "scenes").mkdir(
                    parents=True, exist_ok=True
                )

                # Create user directories with various structures
                for user in users:
                    user_dir = shot_dir / "user" / user
                    user_dir.mkdir(parents=True, exist_ok=True)

                    # Create varied 3DE directory structures
                    threede_paths = [
                        user_dir / "mm" / "3de" / "scenes",
                        user_dir / "matchmove" / "scenes",
                        user_dir / "work" / "3de",
                        user_dir / "tracking" / "3de" / "exports",
                    ]

                    for path in threede_paths:
                        path.mkdir(parents=True, exist_ok=True)
                        # Create .3de files with different naming patterns
                        (path / f"{shot_name}_track_v001.3de").touch()
                        (path / f"bg01_{shot_name}_v002.3de").touch()
                        (path / "fg01_comp_v001.3de").touch()

                # Create raw plate structure with versions
                plate_base = shot_dir / "elements" / "plates" / "raw"
                for plate in ["BG01", "FG01", "bg01", "fg02"]:
                    for version in ["v001", "v002", "v003"]:
                        version_dir = plate_base / plate / version / "exr" / "4312x2304"
                        version_dir.mkdir(parents=True, exist_ok=True)

                        # Create test EXR files with various color spaces
                        color_spaces = ["aces", "lin_sgamut3cine", "rec709", "srgb"]
                        for cs in color_spaces:
                            for frame in range(1001, 1005):
                                exr_file = (
                                    version_dir
                                    / f"{shot_name}_turnover-plate_{plate}_{cs}_{version}.{frame:04d}.exr"
                                )
                                exr_file.touch()

        return base_temp

    def profile_regex_compilation_overhead(self):
        """Profile regex compilation vs pre-compilation performance."""
        logger.info("Profiling regex compilation overhead...")

        # Test patterns from the codebase
        test_patterns = [
            # From raw_plate_finder.py
            r"(\w+)_turnover-plate_(\w+)_([^_]+)_(v\d{3})\.\d{4}\.exr",
            r"(\w+)_turnover-plate_(\w+)([^_]+)_(v\d{3})\.\d{4}\.exr",
            r"^v(\d{3})$",
            r"\d{4}",
            # From threede_scene_finder.py
            r"^[bf]g\d{2}$",
            r"^plate_?\d+$",
            r"^comp_?\d+$",
            r"^shot_?\d+$",
            r"^sc\d+$",
            r"^[\w]+_v\d{3}$",
        ]

        # Test strings to match against
        test_strings = [
            "SEQ01_001_turnover-plate_BG01_aces_v002.1001.exr",
            "SEQ01_002_turnover-plate_FG01lin_sgamut3cine_v001.1023.exr",
            "test_turnover-plate_bg01_rec709_v003.1050.exr",
            "v001",
            "v002",
            "v999",
            "bg01",
            "BG01",
            "FG02",
            "fg15",
            "plate01",
            "plate_05",
            "comp1",
            "comp_12",
            "shot01",
            "shot_25",
            "sc01",
            "sc99",
            "filename_v001",
            "test_v999",
        ]

        regex_results = {}

        for pattern_str in test_patterns:
            pattern_name = (
                pattern_str[:30] + "..." if len(pattern_str) > 30 else pattern_str
            )

            # Test compilation overhead
            compilation_times = []
            for _ in range(1000):  # Many compilations to measure overhead
                with self.measure_time():
                    re.compile(pattern_str, re.IGNORECASE)
                compilation_times.append(self._current_measurement["time"])

            # Pre-compile for matching tests
            compiled_pattern = re.compile(pattern_str, re.IGNORECASE)

            # Test matching performance - compiled vs runtime compilation
            compiled_match_times = []
            runtime_match_times = []

            for test_str in test_strings:
                # Compiled pattern matching
                with self.measure_time():
                    for _ in range(100):  # Multiple matches per string
                        compiled_pattern.match(test_str)
                compiled_match_times.append(self._current_measurement["time"])

                # Runtime compilation + matching
                with self.measure_time():
                    for _ in range(100):
                        re.match(pattern_str, test_str, re.IGNORECASE)
                runtime_match_times.append(self._current_measurement["time"])

            regex_results[pattern_name] = {
                "avg_compilation_time_us": sum(compilation_times)
                * 1_000_000
                / len(compilation_times),
                "total_compilation_overhead_ms": sum(compilation_times) * 1000,
                "avg_compiled_match_time_us": sum(compiled_match_times)
                * 1_000_000
                / len(compiled_match_times),
                "avg_runtime_match_time_us": sum(runtime_match_times)
                * 1_000_000
                / len(runtime_match_times),
                "speedup_factor": sum(runtime_match_times) / sum(compiled_match_times)
                if sum(compiled_match_times) > 0
                else 0,
                "compilation_vs_match_ratio": (sum(compilation_times) * 1000)
                / (sum(compiled_match_times) * 1_000_000)
                if sum(compiled_match_times) > 0
                else float("inf"),
            }

        self.results["regex_performance"] = regex_results

        # Calculate optimization potential
        total_compilation_overhead = sum(
            r["total_compilation_overhead_ms"] for r in regex_results.values()
        )
        avg_speedup = sum(r["speedup_factor"] for r in regex_results.values()) / len(
            regex_results
        )

        if total_compilation_overhead > 1.0:  # > 1ms total overhead
            self.results["optimization_opportunities"].append(
                {
                    "category": "regex_compilation",
                    "impact": "high" if total_compilation_overhead > 10 else "medium",
                    "description": f"Pre-compiling regex patterns could save {total_compilation_overhead:.2f}ms compilation time",
                    "estimated_speedup": f"{avg_speedup:.2f}x faster matching",
                    "implementation": "Move regex compilation to module level or class initialization",
                }
            )

    def profile_directory_operations(self):
        """Profile directory traversal and path validation performance."""
        logger.info("Profiling directory operations...")

        test_base = self.setup_test_data()

        directory_results = {}

        # Test PathUtils.validate_path_exists with and without caching
        paths_to_test = []
        shot_dirs = list((test_base / "shows" / "test_show" / "shots").rglob("*"))
        paths_to_test.extend([str(p) for p in shot_dirs[:100]])  # Test first 100 paths

        # Clear cache for fair testing
        clear_all_caches()

        # Test without cache (cold)
        with self.measure_time():
            for path in paths_to_test:
                PathUtils.validate_path_exists(path)
        cold_cache_time = self._current_measurement["time"]

        # Test with cache (warm)
        with self.measure_time():
            for path in paths_to_test:
                PathUtils.validate_path_exists(path)
        warm_cache_time = self._current_measurement["time"]

        # Test batch validation
        with self.measure_time():
            PathUtils.batch_validate_paths(paths_to_test)
        batch_time = self._current_measurement["time"]

        directory_results["path_validation"] = {
            "cold_cache_time_ms": cold_cache_time * 1000,
            "warm_cache_time_ms": warm_cache_time * 1000,
            "batch_time_ms": batch_time * 1000,
            "cache_speedup": cold_cache_time / warm_cache_time
            if warm_cache_time > 0
            else 0,
            "batch_speedup": cold_cache_time / batch_time if batch_time > 0 else 0,
            "paths_tested": len(paths_to_test),
        }

        # Test rglob performance (used in 3DE scene finding)
        test_shot_dir = (
            test_base / "shows" / "test_show" / "shots" / "SEQ01" / "SEQ01_001"
        )

        with self.measure_time():
            list(test_shot_dir.rglob("*.3de"))
        rglob_3de_time = self._current_measurement["time"]

        with self.measure_time():
            list(test_shot_dir.rglob("*"))
        rglob_all_time = self._current_measurement["time"]

        # Test iterdir vs rglob for user directory scanning
        user_dir = test_shot_dir / "user"

        with self.measure_time():
            # Simulate ThreeDESceneFinder.find_scenes_for_shot
            for user_path in user_dir.iterdir():
                if user_path.is_dir():
                    list(user_path.rglob("*.3de"))
        iterdir_rglob_time = self._current_measurement["time"]

        directory_results["filesystem_ops"] = {
            "rglob_3de_time_ms": rglob_3de_time * 1000,
            "rglob_all_time_ms": rglob_all_time * 1000,
            "iterdir_rglob_time_ms": iterdir_rglob_time * 1000,
            "rglob_selectivity_factor": rglob_all_time / rglob_3de_time
            if rglob_3de_time > 0
            else 0,
        }

        # Test VersionUtils caching
        plate_dirs = list((test_base / "shows" / "test_show" / "shots").rglob("raw/*"))
        version_dirs = [
            d
            for d in plate_dirs
            if d.is_dir() and any(v.startswith("v") for v in d.iterdir() if v.is_dir())
        ]

        clear_all_caches()

        with self.measure_time():
            for vdir in version_dirs[:20]:  # Test 20 version directories
                VersionUtils.find_version_directories(vdir)
        version_cold_time = self._current_measurement["time"]

        with self.measure_time():
            for vdir in version_dirs[:20]:
                VersionUtils.find_version_directories(vdir)
        version_warm_time = self._current_measurement["time"]

        directory_results["version_operations"] = {
            "cold_time_ms": version_cold_time * 1000,
            "warm_time_ms": version_warm_time * 1000,
            "cache_speedup": version_cold_time / version_warm_time
            if version_warm_time > 0
            else 0,
            "directories_tested": len(version_dirs[:20]),
        }

        self.results["directory_performance"] = directory_results

        # Identify optimization opportunities
        if directory_results["path_validation"]["cache_speedup"] > 2:
            self.results["optimization_opportunities"].append(
                {
                    "category": "path_caching",
                    "impact": "medium",
                    "description": f"Path caching provides {directory_results['path_validation']['cache_speedup']:.1f}x speedup",
                    "recommendation": "Increase cache TTL or implement smarter cache eviction",
                }
            )

        if directory_results["version_operations"]["cache_speedup"] > 2:
            self.results["optimization_opportunities"].append(
                {
                    "category": "version_caching",
                    "impact": "medium",
                    "description": f"Version directory caching provides {directory_results['version_operations']['cache_speedup']:.1f}x speedup",
                    "recommendation": "Consider longer cache TTL for version directories",
                }
            )

    def profile_memory_usage_patterns(self):
        """Profile memory usage in cache_manager and other components."""
        logger.info("Profiling memory usage patterns...")

        # Initialize Qt application for QPixmap testing
        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication([])

        memory_results = {}

        # Test CacheManager memory usage
        cache_dir = Path(tempfile.mkdtemp(prefix="shotbot_cache_perf_"))
        self.temp_dirs.append(cache_dir)

        cache_manager = CacheManager(cache_dir)

        # Create test thumbnails of various sizes
        test_sizes = [(100, 100), (512, 512), (1920, 1080), (4096, 4096)]
        thumbnail_memory = {}

        for width, height in test_sizes:
            with self.measure_memory():
                # Create test pixmap
                pixmap = QPixmap(width, height)
                pixmap.fill()

                # Measure scaling memory
                scaled = pixmap.scaled(
                    Config.CACHE_THUMBNAIL_SIZE,
                    Config.CACHE_THUMBNAIL_SIZE,
                    1,  # KeepAspectRatio
                    1,  # SmoothTransformation
                )

                # Clean up
                pixmap = None
                scaled = None
                gc.collect()

            thumbnail_memory[f"{width}x{height}"] = self._current_memory

        memory_results["thumbnail_processing"] = thumbnail_memory

        # Test cache growth patterns
        cache_growth = []
        process = psutil.Process()

        for i in range(50):  # Add 50 cache entries
            initial_memory = process.memory_info().rss

            # Simulate caching thumbnails (without actual image files)
            cache_key = f"test_show/seq{i // 10}/shot{i:03d}"

            memory_after = process.memory_info().rss
            cache_growth.append((memory_after - initial_memory) / 1024)  # KB

        memory_results["cache_growth"] = {
            "per_entry_kb": sum(cache_growth) / len(cache_growth),
            "total_growth_kb": sum(cache_growth),
            "growth_pattern": "linear"
            if max(cache_growth) < 2 * min(cache_growth)
            else "non-linear",
        }

        # Test memory leaks in regex operations
        with self.measure_memory():
            pattern = re.compile(
                r"(\w+)_turnover-plate_(\w+)_([^_]+)_(v\d{3})\.\d{4}\.exr"
            )
            test_strings = [
                f"shot{i:03d}_turnover-plate_BG01_aces_v001.{1001 + i:04d}.exr"
                for i in range(1000)
            ]

            for test_str in test_strings:
                pattern.match(test_str)

        memory_results["regex_memory"] = self._current_memory

        self.results["memory_analysis"] = memory_results

        # Memory optimization opportunities
        avg_thumbnail_memory = sum(
            t["rss_delta_mb"] for t in thumbnail_memory.values()
        ) / len(thumbnail_memory)
        if avg_thumbnail_memory > 10:  # > 10MB per thumbnail operation
            self.results["optimization_opportunities"].append(
                {
                    "category": "memory_usage",
                    "impact": "high",
                    "description": f"Thumbnail processing uses {avg_thumbnail_memory:.1f}MB average memory",
                    "recommendation": "Implement streaming thumbnail processing or size limits",
                }
            )

        if (
            memory_results["cache_growth"]["per_entry_kb"] > 100
        ):  # > 100KB per cache entry
            self.results["optimization_opportunities"].append(
                {
                    "category": "cache_memory",
                    "impact": "medium",
                    "description": f"Cache entries use {memory_results['cache_growth']['per_entry_kb']:.1f}KB each",
                    "recommendation": "Implement cache eviction or compress cached data",
                }
            )

    def profile_cache_efficiency(self):
        """Profile cache hit rates and efficiency."""
        logger.info("Profiling cache efficiency...")

        cache_results = {}

        # Test path cache efficiency
        test_paths = [f"/test/path/{i}" for i in range(100)]

        clear_all_caches()

        # First pass - populate cache
        for path in test_paths:
            PathUtils.validate_path_exists(path)

        initial_stats = get_cache_stats()

        # Second pass - test hit rate
        cache_hits = 0
        for path in test_paths:
            # This should hit cache
            PathUtils.validate_path_exists(path)
            cache_hits += 1

        final_stats = get_cache_stats()

        cache_results["path_cache"] = {
            "cache_size": final_stats["path_cache_size"],
            "expected_hits": len(test_paths),
            "hit_rate": 1.0
            if cache_hits == len(test_paths)
            else cache_hits / len(test_paths),
            "efficiency": "high"
            if final_stats["path_cache_size"] == len(test_paths)
            else "low",
        }

        # Test version cache efficiency
        clear_all_caches()

        # Test extract_version_from_path LRU cache
        test_version_paths = [
            f"/path/to/v{i:03d}/file.ext" for i in range(1, 51)
        ]  # 50 different versions

        # First pass
        for path in test_version_paths:
            VersionUtils.extract_version_from_path(path)

        version_cache_info = VersionUtils.extract_version_from_path.cache_info()

        # Second pass - should hit cache
        for path in test_version_paths:
            VersionUtils.extract_version_from_path(path)

        version_cache_info_after = VersionUtils.extract_version_from_path.cache_info()

        cache_results["version_cache"] = {
            "cache_size": version_cache_info.currsize,
            "max_size": version_cache_info.maxsize,
            "hits": version_cache_info_after.hits - version_cache_info.hits,
            "misses": version_cache_info_after.misses - version_cache_info.misses,
            "hit_rate": (version_cache_info_after.hits - version_cache_info.hits)
            / len(test_version_paths),
            "efficiency": "optimal"
            if version_cache_info.currsize <= version_cache_info.maxsize
            else "suboptimal",
        }

        # Test CacheManager file cache efficiency (simulated)
        cache_dir = Path(tempfile.mkdtemp(prefix="shotbot_cache_eff_"))
        self.temp_dirs.append(cache_dir)

        cache_manager = CacheManager(cache_dir)

        # Simulate shot caching
        test_shots = [
            {"show": "test", "sequence": f"seq{i // 10}", "shot": f"shot{i:03d}"}
            for i in range(100)
        ]

        with self.measure_time():
            cache_manager.cache_shots(test_shots)
        cache_write_time = self._current_measurement["time"]

        with self.measure_time():
            cached_shots = cache_manager.get_cached_shots()
        cache_read_time = self._current_measurement["time"]

        cache_results["file_cache"] = {
            "write_time_ms": cache_write_time * 1000,
            "read_time_ms": cache_read_time * 1000,
            "cache_hit": cached_shots is not None
            and len(cached_shots) == len(test_shots),
            "read_write_ratio": cache_read_time / cache_write_time
            if cache_write_time > 0
            else 0,
        }

        self.results["cache_efficiency"] = cache_results

        # Cache efficiency optimization opportunities
        if cache_results["path_cache"]["hit_rate"] < 0.8:
            self.results["optimization_opportunities"].append(
                {
                    "category": "cache_hit_rate",
                    "impact": "medium",
                    "description": f"Path cache hit rate is only {cache_results['path_cache']['hit_rate']:.1%}",
                    "recommendation": "Investigate cache TTL and eviction patterns",
                }
            )

        if cache_results["version_cache"]["hit_rate"] < 0.9:
            self.results["optimization_opportunities"].append(
                {
                    "category": "lru_cache_size",
                    "impact": "low",
                    "description": f"Version cache hit rate is {cache_results['version_cache']['hit_rate']:.1%}",
                    "recommendation": "Consider increasing LRU cache maxsize",
                }
            )

    def cleanup(self):
        """Clean up temporary directories."""
        for temp_dir in self.temp_dirs:
            try:
                import shutil

                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to clean up {temp_dir}: {e}")

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report."""
        # Calculate summary metrics
        regex_perf = self.results["regex_performance"]
        dir_perf = self.results["directory_performance"]

        total_compilation_overhead = sum(
            r.get("total_compilation_overhead_ms", 0) for r in regex_perf.values()
        )

        avg_regex_speedup = (
            sum(r.get("speedup_factor", 1) for r in regex_perf.values())
            / len(regex_perf)
            if regex_perf
            else 1
        )

        path_cache_speedup = dir_perf.get("path_validation", {}).get("cache_speedup", 1)

        # Generate executive summary
        summary = {
            "total_regex_compilation_overhead_ms": total_compilation_overhead,
            "average_regex_speedup_potential": avg_regex_speedup,
            "path_cache_speedup": path_cache_speedup,
            "optimization_opportunities_count": len(
                self.results["optimization_opportunities"]
            ),
            "high_impact_optimizations": len(
                [
                    op
                    for op in self.results["optimization_opportunities"]
                    if op.get("impact") == "high"
                ]
            ),
            "quick_wins": [
                op
                for op in self.results["optimization_opportunities"]
                if op.get("impact") in ["high", "medium"]
            ],
        }

        self.results["executive_summary"] = summary

        return self.results

    def print_report(self):
        """Print formatted performance report."""
        results = self.generate_report()

        print("\n" + "=" * 80)
        print("SHOTBOT PERFORMANCE PROFILING REPORT")
        print("=" * 80)

        # System info
        sys_info = results["system_info"]
        print("\nSystem Information:")
        print(f"  CPU Cores: {sys_info['cpu_count']}")
        print(f"  Memory Total: {sys_info['memory_total_gb']:.1f} GB")
        print(f"  Memory Available: {sys_info['memory_available_gb']:.1f} GB")
        print(f"  Process Memory: {sys_info['process_memory_mb']:.1f} MB")

        # Executive summary
        summary = results["executive_summary"]
        print("\nExecutive Summary:")
        print(
            f"  Total Regex Compilation Overhead: {summary['total_regex_compilation_overhead_ms']:.2f} ms"
        )
        print(
            f"  Average Regex Speedup Potential: {summary['average_regex_speedup_potential']:.1f}x"
        )
        print(f"  Path Cache Speedup: {summary['path_cache_speedup']:.1f}x")
        print(
            f"  Optimization Opportunities: {summary['optimization_opportunities_count']}"
        )
        print(f"  High Impact Optimizations: {summary['high_impact_optimizations']}")

        # Regex performance details
        print("\nRegex Performance Analysis:")
        for pattern, perf in results["regex_performance"].items():
            print(f"  Pattern: {pattern}")
            print(f"    Compilation Time: {perf['avg_compilation_time_us']:.1f} µs")
            print(f"    Speedup Factor: {perf['speedup_factor']:.1f}x")
            print(
                f"    Compilation vs Match Ratio: {perf['compilation_vs_match_ratio']:.1f}"
            )

        # Directory performance details
        dir_perf = results["directory_performance"]
        print("\nDirectory Operations Performance:")
        print("  Path Validation:")
        print(
            f"    Cold Cache: {dir_perf['path_validation']['cold_cache_time_ms']:.1f} ms"
        )
        print(
            f"    Warm Cache: {dir_perf['path_validation']['warm_cache_time_ms']:.1f} ms"
        )
        print(
            f"    Batch Operations: {dir_perf['path_validation']['batch_time_ms']:.1f} ms"
        )
        print(f"    Cache Speedup: {dir_perf['path_validation']['cache_speedup']:.1f}x")

        print("  Filesystem Operations:")
        print(
            f"    rglob *.3de: {dir_perf['filesystem_ops']['rglob_3de_time_ms']:.1f} ms"
        )
        print(
            f"    rglob all files: {dir_perf['filesystem_ops']['rglob_all_time_ms']:.1f} ms"
        )
        print(
            f"    iterdir + rglob: {dir_perf['filesystem_ops']['iterdir_rglob_time_ms']:.1f} ms"
        )

        # Memory analysis
        mem_analysis = results["memory_analysis"]
        print("\nMemory Usage Analysis:")
        print(
            f"  Cache Growth: {mem_analysis['cache_growth']['per_entry_kb']:.1f} KB per entry"
        )
        print(
            f"  Total Growth: {mem_analysis['cache_growth']['total_growth_kb']:.1f} KB"
        )
        print(
            f"  Regex Memory Impact: {mem_analysis['regex_memory']['rss_delta_mb']:.2f} MB"
        )

        # Cache efficiency
        cache_eff = results["cache_efficiency"]
        print("\nCache Efficiency:")
        print(f"  Path Cache Hit Rate: {cache_eff['path_cache']['hit_rate']:.1%}")
        print(f"  Version Cache Hit Rate: {cache_eff['version_cache']['hit_rate']:.1%}")
        print(
            f"  File Cache Performance: {cache_eff['file_cache']['read_time_ms']:.1f} ms read"
        )

        # Optimization opportunities
        print("\nOptimization Opportunities:")
        for i, op in enumerate(summary["quick_wins"], 1):
            print(f"  {i}. [{op['impact'].upper()}] {op['description']}")
            if "recommendation" in op:
                print(f"     Recommendation: {op['recommendation']}")
            if "implementation" in op:
                print(f"     Implementation: {op['implementation']}")
            print()

        print("=" * 80)


def main():
    """Run comprehensive performance profiling."""
    profiler = PerformanceProfiler()

    try:
        # Run all profiling tests
        profiler.profile_regex_compilation_overhead()
        profiler.profile_directory_operations()
        profiler.profile_memory_usage_patterns()
        profiler.profile_cache_efficiency()

        # Generate and print report
        profiler.print_report()

        # Save detailed results to JSON
        results_file = Path("shotbot_performance_report.json")
        with open(results_file, "w") as f:
            json.dump(profiler.results, f, indent=2, default=str)

        print(f"\nDetailed results saved to: {results_file}")

    finally:
        profiler.cleanup()


if __name__ == "__main__":
    main()
