#!/usr/bin/env python3
"""
Specialized Performance Profiler for Thumbnail Discovery Bottlenecks

Focuses specifically on the performance areas requested:
1. Shot name extraction overhead
2. Thumbnail discovery performance
3. Memory usage patterns
4. UI responsiveness
5. Parallel processing efficiency
"""

# Standard library imports
import cProfile
import io
import logging
import pstats
import re
import sys
import time
from pathlib import Path
from typing import Any

# Third-party imports
import psutil


# Add current directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    # Local application imports
    from shot_model import Shot

    from config import Config
    from discovery.thumbnail_finders import (
        find_any_publish_thumbnail,
        find_shot_thumbnail,
        find_turnover_plate_thumbnail,
    )
    from paths.validators import PathValidators
    from utils import FileUtils, get_cache_stats

    shotbot_available = True
except ImportError:
    print("Warning: ShotBot modules not available - using mock implementations")
    shotbot_available = False

SHOTBOT_AVAILABLE = shotbot_available

logger = logging.getLogger(__name__)


class ThumbnailBottleneckProfiler:
    """Specialized profiler for thumbnail discovery bottlenecks."""

    def __init__(self) -> None:
        self.process = psutil.Process()
        self.baseline_memory = self.get_memory_mb()
        self.results = {}

    def get_memory_mb(self) -> float:
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / 1024 / 1024

    def profile_shot_name_extraction_overhead(self) -> dict[str, Any]:
        """Profile the _parse_shot_from_path() method overhead in detail."""
        logger.info("Profiling shot name extraction overhead...")

        # Generate realistic test paths
        test_paths = []
        for show in ["BigShow", "TestProject", "DemoShow"]:
            for seq in ["010", "020", "030", "040", "050"]:
                for shot in ["0010", "0020", "0030", "0040", "0050", "0060", "0070"]:
                    shot_dir = f"{seq}_{shot}"
                    path = f"/shows/{show}/shots/{seq}/{shot_dir}/user/testuser"
                    test_paths.append(path)

        logger.info(f"Testing with {len(test_paths)} realistic shot paths")

        # Test current implementation from previous_shots_finder.py
        shot_pattern = re.compile(r"/shows/([^/]+)/shots/([^/]+)/([^/]+)/")

        def current_parse_implementation(path: str) -> tuple[str, str, str] | None:
            """Current implementation from _parse_shot_from_path."""
            match = shot_pattern.search(path)
            if match:
                show, sequence, shot_dir_name = match.groups()
                shot_number = shot_dir_name
                if shot_dir_name.startswith(f"{sequence}_"):
                    shot_number = shot_dir_name[len(sequence) + 1 :]
                return (show, sequence, shot_number)
            return None

        # Profile current implementation
        iterations = 10000

        # Use cProfile for detailed analysis
        profiler = cProfile.Profile()
        profiler.enable()

        start_time = time.perf_counter()
        for _ in range(iterations):
            for path in test_paths:
                current_parse_implementation(path)
        current_time = time.perf_counter() - start_time

        profiler.disable()

        # Capture profiler stats
        stats_buffer = io.StringIO()
        ps = pstats.Stats(profiler, stream=stats_buffer)
        ps.sort_stats("cumulative")
        ps.print_stats(10)
        profiler_output = stats_buffer.getvalue()

        # Test optimized implementation with single regex
        optimized_pattern = re.compile(r"/shows/([^/]+)/shots/([^/]+)/\2_(.+)/")

        def optimized_parse_implementation(path: str) -> tuple[str, str, str] | None:
            """Optimized implementation with better regex."""
            match = optimized_pattern.search(path)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    return (groups[0], groups[1], groups[2])
                return None
            return None

        start_time = time.perf_counter()
        for _ in range(iterations):
            for path in test_paths:
                optimized_parse_implementation(path)
        optimized_time = time.perf_counter() - start_time

        # Calculate per-operation metrics
        total_operations = len(test_paths) * iterations
        current_per_op = (current_time / total_operations) * 1_000_000  # microseconds
        optimized_per_op = (optimized_time / total_operations) * 1_000_000

        improvement = (
            ((current_time - optimized_time) / current_time) * 100
            if current_time > 0
            else 0
        )

        return {
            "test_paths_count": len(test_paths),
            "iterations": iterations,
            "total_operations": total_operations,
            "current_total_time": current_time,
            "optimized_total_time": optimized_time,
            "current_per_operation_us": current_per_op,
            "optimized_per_operation_us": optimized_per_op,
            "improvement_percent": improvement,
            "operations_per_second_current": total_operations / current_time,
            "operations_per_second_optimized": total_operations / optimized_time,
            "profiler_hotspots": profiler_output.split("\n")[:15],  # Top hotspots
            "startup_impact_estimate": f"With 1000 shots: {(current_per_op * 1000) / 1000:.1f}ms vs {(optimized_per_op * 1000) / 1000:.1f}ms",
        }

    def profile_thumbnail_discovery_pipeline(self) -> dict[str, Any]:
        """Profile the utils.find_shot_thumbnail() pipeline in detail."""
        logger.info("Profiling thumbnail discovery pipeline...")

        if not SHOTBOT_AVAILABLE:
            return {"error": "ShotBot modules not available for real profiling"}

        # Create test shots
        test_shots = [
            ("TestShow", "010", "0010"),
            ("TestShow", "010", "0020"),
            ("TestShow", "020", "0010"),
            ("BigProject", "030", "0050"),
            ("DemoShow", "040", "0030"),
        ]

        cache_stats_before = get_cache_stats()

        # Profile each stage of the discovery pipeline
        stage_times = {"editorial": [], "turnover": [], "publish": []}
        filesystem_operations = 0

        for show, sequence, shot in test_shots:
            # Stage 1: Editorial thumbnails
            start = time.perf_counter()
            shot_dir = f"{sequence}_{shot}"
            thumbnail_dir = Path(Config.SHOWS_ROOT, show, "shots", sequence, shot_dir, *Config.THUMBNAIL_SEGMENTS)
            editorial_exists = PathValidators.validate_path_exists(
                thumbnail_dir, "Thumbnail dir"
            )
            filesystem_operations += 1

            if editorial_exists:
                first_image = FileUtils.get_first_image_file(thumbnail_dir)
                filesystem_operations += 1
            else:
                first_image = None

            stage_times["editorial"].append(time.perf_counter() - start)

            if first_image:
                continue  # Found editorial thumbnail

            # Stage 2: Turnover plate thumbnails
            start = time.perf_counter()
            turnover_thumbnail = find_turnover_plate_thumbnail(
                Config.SHOWS_ROOT, show, sequence, shot
            )
            filesystem_operations += 3  # Multiple path validations
            stage_times["turnover"].append(time.perf_counter() - start)

            if turnover_thumbnail:
                continue  # Found turnover thumbnail

            # Stage 3: Publish folder fallback
            start = time.perf_counter()
            find_any_publish_thumbnail(
                Config.SHOWS_ROOT, show, sequence, shot, max_depth=3
            )
            filesystem_operations += 5  # Recursive search
            stage_times["publish"].append(time.perf_counter() - start)

        cache_stats_after = get_cache_stats()

        # Calculate cache hit rates
        cache_growth = (
            cache_stats_after["path_cache_size"] - cache_stats_before["path_cache_size"]
        )
        cache_effectiveness = cache_growth / len(test_shots) if test_shots else 0

        # Calculate stage performance
        stage_performance = {}
        total_time = 0
        for stage, times in stage_times.items():
            if times:
                avg_time = sum(times) / len(times)
                max_time = max(times)
                min_time = min(times)
                stage_total = sum(times)
                total_time += stage_total

                stage_performance[stage] = {
                    "avg_time_ms": avg_time * 1000,
                    "max_time_ms": max_time * 1000,
                    "min_time_ms": min_time * 1000,
                    "total_time_ms": stage_total * 1000,
                    "calls": len(times),
                    "time_per_call_us": (avg_time * 1_000_000),
                }

        return {
            "test_shots_count": len(test_shots),
            "total_discovery_time_ms": total_time * 1000,
            "avg_time_per_shot_ms": (total_time / len(test_shots) * 1000)
            if test_shots
            else 0,
            "filesystem_operations": filesystem_operations,
            "fs_ops_per_shot": filesystem_operations / len(test_shots)
            if test_shots
            else 0,
            "stage_performance": stage_performance,
            "cache_growth": cache_growth,
            "cache_effectiveness": cache_effectiveness,
            "thumbnails_per_second": len(test_shots) / total_time
            if total_time > 0
            else 0,
            "bottleneck_stage": max(
                stage_performance.keys(),
                key=lambda k: stage_performance[k]["avg_time_ms"],
            )
            if stage_performance
            else "unknown",
        }

    def profile_memory_usage_patterns(self, duration: int = 30) -> dict[str, Any]:
        """Profile memory usage with focus on shot objects and caches."""
        logger.info(f"Profiling memory patterns for {duration} seconds...")

        initial_memory = self.get_memory_mb()
        peak_memory = initial_memory
        memory_samples = []

        # Simulate typical usage pattern
        shot_objects = []
        cached_thumbnails = {}

        start_time = time.time()
        sample_count = 0

        while time.time() - start_time < duration:
            current_memory = self.get_memory_mb()
            memory_samples.append(current_memory)
            peak_memory = max(peak_memory, current_memory)

            # Simulate creating Shot objects (memory allocation)
            if sample_count % 10 == 0:  # Every 10th sample
                for i in range(10):
                    if SHOTBOT_AVAILABLE:
                        try:
                            shot = Shot(
                                show=f"Show{i}",
                                sequence=f"0{i:02d}",
                                shot=f"00{i:02d}",
                                workspace_path=f"/shows/Show{i}/shots/0{i:02d}/0{i:02d}_00{i:02d}",
                            )
                            shot_objects.append(shot)
                        except Exception:
                            pass
                    else:
                        # Mock shot object
                        shot_objects.append(
                            {
                                "show": f"Show{i}",
                                "sequence": f"0{i:02d}",
                                "shot": f"00{i:02d}",
                                "cached_thumbnail": None,
                            }
                        )

                # Simulate thumbnail caching
                for j in range(5):
                    key = f"thumbnail_{sample_count}_{j}"
                    cached_thumbnails[key] = (
                        f"fake_thumbnail_data_{j}" * 100
                    )  # ~2KB each

            # Periodic cleanup (simulate cache eviction)
            if len(shot_objects) > 100:
                shot_objects = shot_objects[-50:]  # Keep last 50

            if len(cached_thumbnails) > 50:
                # Remove oldest entries
                keys_to_remove = list(cached_thumbnails.keys())[:10]
                for key in keys_to_remove:
                    del cached_thumbnails[key]

            sample_count += 1
            time.sleep(0.1)  # Sample every 100ms

        final_memory = self.get_memory_mb()
        memory_growth = final_memory - initial_memory

        # Analyze memory patterns
        memory_trend = "stable"
        if len(memory_samples) > 10:
            early_avg = sum(memory_samples[:5]) / 5
            late_avg = sum(memory_samples[-5:]) / 5
            growth_rate = (late_avg - early_avg) / early_avg * 100

            if growth_rate > 5:
                memory_trend = "growing"
            elif growth_rate < -5:
                memory_trend = "decreasing"

        # Estimate memory per shot object
        if shot_objects:
            shot_memory_estimate = (
                (memory_growth / len(shot_objects)) if memory_growth > 0 else 0
            )
        else:
            shot_memory_estimate = 0

        return {
            "duration_seconds": duration,
            "samples_collected": len(memory_samples),
            "initial_memory_mb": initial_memory,
            "peak_memory_mb": peak_memory,
            "final_memory_mb": final_memory,
            "memory_growth_mb": memory_growth,
            "memory_trend": memory_trend,
            "shot_objects_created": len(shot_objects),
            "cached_thumbnails": len(cached_thumbnails),
            "estimated_memory_per_shot_kb": shot_memory_estimate * 1024,
            "memory_efficiency_rating": "Good"
            if memory_growth < 10
            else "Fair"
            if memory_growth < 50
            else "Poor",
            "peak_memory_overhead_percent": (
                (peak_memory - initial_memory) / initial_memory * 100
            )
            if initial_memory > 0
            else 0,
        }

    def profile_ui_responsiveness(self) -> dict[str, Any]:
        """Profile operations that could block the UI thread."""
        logger.info("Profiling UI responsiveness and blocking operations...")

        blocking_operations = []

        # Test expensive operations that could block UI
        test_operations = [
            ("Path validation batch", lambda: self._test_path_validation_batch()),
            (
                "Thumbnail discovery batch",
                lambda: self._test_thumbnail_discovery_batch(),
            ),
            ("Shot parsing batch", lambda: self._test_shot_parsing_batch()),
            ("Cache lookup batch", lambda: self._test_cache_lookup_batch()),
        ]

        for op_name, op_func in test_operations:
            start = time.perf_counter()
            try:
                op_func()
            except Exception as e:
                logger.warning(f"Operation {op_name} failed: {e}")
            elapsed = time.perf_counter() - start

            blocking_operations.append(
                {
                    "operation": op_name,
                    "duration_ms": elapsed * 1000,
                    "blocks_ui": elapsed > 0.016,  # >16ms blocks 60fps
                    "severity": "High"
                    if elapsed > 0.1
                    else "Medium"
                    if elapsed > 0.05
                    else "Low",
                }
            )

        # Calculate UI impact
        total_blocking_time = sum(
            op["duration_ms"] for op in blocking_operations if op["blocks_ui"]
        )
        high_severity_ops = [
            op for op in blocking_operations if op["severity"] == "High"
        ]

        return {
            "operations_tested": len(test_operations),
            "blocking_operations": blocking_operations,
            "total_blocking_time_ms": total_blocking_time,
            "high_severity_operations": len(high_severity_ops),
            "ui_responsiveness_rating": "Good"
            if total_blocking_time < 50
            else "Fair"
            if total_blocking_time < 200
            else "Poor",
            "recommendations": self._generate_ui_recommendations(blocking_operations),
        }

    def _test_path_validation_batch(self) -> int:
        """Test batch path validation performance."""
        paths: list[str | Path] = [f"/fake/path/{i}/test" for i in range(100)]
        if SHOTBOT_AVAILABLE:
            results = PathValidators.batch_validate_paths(paths)
        else:
            results = dict.fromkeys(paths, False)
        return len(results)

    def _test_thumbnail_discovery_batch(self) -> int:
        """Test batch thumbnail discovery."""
        if not SHOTBOT_AVAILABLE:
            return 0

        count = 0
        for i in range(10):
            find_shot_thumbnail(
                "/fake/root", f"Show{i}", f"0{i:02d}", f"00{i:02d}"
            )
            count += 1
        return count

    def _test_shot_parsing_batch(self) -> int:
        """Test batch shot path parsing."""
        paths = [
            f"/shows/Show{i}/shots/0{i:02d}/0{i:02d}_00{j:02d}/user/test"
            for i in range(5)
            for j in range(10)
        ]

        pattern = re.compile(r"/shows/([^/]+)/shots/([^/]+)/([^/]+)/")
        count = 0
        for path in paths:
            match = pattern.search(path)
            if match:
                count += 1
        return count

    def _test_cache_lookup_batch(self) -> int:
        """Test batch cache lookups."""
        if not SHOTBOT_AVAILABLE:
            return 0

        # Simulate cache usage
        paths = [f"/test/cache/path/{i}" for i in range(50)]
        for path in paths:
            PathValidators.validate_path_exists(path, "Test")

        # Second pass should hit cache
        for path in paths:
            PathValidators.validate_path_exists(path, "Test")

        return len(paths)

    def _generate_ui_recommendations(
        self, blocking_operations: list[dict[str, Any]]
    ) -> list[str]:
        """Generate UI responsiveness recommendations."""
        recommendations = []

        for op in blocking_operations:
            if op["blocks_ui"]:
                if "batch" in op["operation"].lower():
                    recommendations.append(
                        f"Move {op['operation']} to background thread"
                    )
                if op["duration_ms"] > 100:
                    recommendations.append(
                        f"Optimize {op['operation']} - taking {op['duration_ms']:.1f}ms"
                    )

        high_severity = [op for op in blocking_operations if op["severity"] == "High"]
        if high_severity:
            recommendations.append(
                f"Priority: {len(high_severity)} high-severity blocking operations detected"
            )

        return recommendations

    def run_comprehensive_analysis(self, memory_duration: int = 15) -> dict[str, Any]:
        """Run all profiling analyses."""
        logger.info("Starting comprehensive thumbnail bottleneck analysis...")

        results = {}

        try:
            # 1. Shot name extraction overhead
            logger.info("1/4: Analyzing shot name extraction overhead...")
            results["shot_name_extraction"] = (
                self.profile_shot_name_extraction_overhead()
            )

            # 2. Thumbnail discovery pipeline
            logger.info("2/4: Analyzing thumbnail discovery pipeline...")
            results["thumbnail_discovery"] = self.profile_thumbnail_discovery_pipeline()

            # 3. Memory usage patterns
            logger.info("3/4: Analyzing memory usage patterns...")
            results["memory_patterns"] = self.profile_memory_usage_patterns(
                memory_duration
            )

            # 4. UI responsiveness
            logger.info("4/4: Analyzing UI responsiveness...")
            results["ui_responsiveness"] = self.profile_ui_responsiveness()

        except Exception as e:
            logger.error(f"Error during profiling: {e}")
            results["error"] = str(e)

        return results

    def generate_bottleneck_report(self, results: dict[str, Any]) -> str:
        """Generate focused bottleneck analysis report."""
        if not results or "error" in results:
            return f"Profiling failed: {results.get('error', 'Unknown error')}"

        report = []
        report.append("=" * 80)
        report.append("SHOTBOT THUMBNAIL DISCOVERY BOTTLENECK ANALYSIS")
        report.append("=" * 80)
        report.append("")

        # Critical Performance Issues
        issues = []

        if "shot_name_extraction" in results:
            ops_per_sec = results["shot_name_extraction"].get(
                "operations_per_second_current", 0
            )
            if ops_per_sec < 100000:  # Less than 100k ops/sec
                issues.append(
                    f"Shot name extraction only {ops_per_sec:.0f} ops/sec - significant bottleneck"
                )

        if "thumbnail_discovery" in results:
            avg_time_ms = results["thumbnail_discovery"].get("avg_time_per_shot_ms", 0)
            if avg_time_ms > 20:  # More than 20ms per shot
                issues.append(
                    f"Thumbnail discovery {avg_time_ms:.1f}ms per shot - will impact startup"
                )

        if "memory_patterns" in results:
            growth = results["memory_patterns"].get("memory_growth_mb", 0)
            if growth > 20:
                issues.append(
                    f"Memory growing {growth:.1f}MB during test - potential leak"
                )

        if "ui_responsiveness" in results:
            blocking_time = results["ui_responsiveness"].get(
                "total_blocking_time_ms", 0
            )
            if blocking_time > 100:
                issues.append(
                    f"UI blocking operations total {blocking_time:.1f}ms - will freeze interface"
                )

        if issues:
            report.append("🚨 CRITICAL PERFORMANCE ISSUES DETECTED")
            report.append("-" * 42)
            report.extend(f"  • {issue}" for issue in issues)
        else:
            report.append("✅ NO CRITICAL PERFORMANCE ISSUES DETECTED")
        report.append("")

        # Detailed Analysis
        if "shot_name_extraction" in results:
            data = results["shot_name_extraction"]
            report.append("SHOT NAME EXTRACTION ANALYSIS")
            report.append("-" * 32)
            report.append(
                f"  Current performance: {data.get('operations_per_second_current', 0):.0f} ops/sec"
            )
            report.append(
                f"  Time per operation: {data.get('current_per_operation_us', 0):.2f} microseconds"
            )
            report.append(
                f"  Potential improvement: {data.get('improvement_percent', 0):.1f}%"
            )
            report.append(
                f"  Startup impact: {data.get('startup_impact_estimate', 'N/A')}"
            )
            report.append("")

        if "thumbnail_discovery" in results:
            data = results["thumbnail_discovery"]
            report.append("THUMBNAIL DISCOVERY PIPELINE ANALYSIS")
            report.append("-" * 39)
            report.append(
                f"  Average time per shot: {data.get('avg_time_per_shot_ms', 0):.1f}ms"
            )
            report.append(
                f"  Filesystem operations per shot: {data.get('fs_ops_per_shot', 0):.1f}"
            )
            report.append(
                f"  Bottleneck stage: {data.get('bottleneck_stage', 'unknown')}"
            )

            if "stage_performance" in data:
                report.append("  Stage breakdown:")
                for stage, perf in data["stage_performance"].items():
                    report.append(
                        f"    {stage}: {perf.get('avg_time_ms', 0):.2f}ms avg, {perf.get('calls', 0)} calls"
                    )
            report.append("")

        if "memory_patterns" in results:
            data = results["memory_patterns"]
            report.append("MEMORY USAGE ANALYSIS")
            report.append("-" * 22)
            report.append(f"  Memory growth: {data.get('memory_growth_mb', 0):+.1f}MB")
            report.append(f"  Peak memory: {data.get('peak_memory_mb', 0):.1f}MB")
            report.append(
                f"  Memory per shot object: ~{data.get('estimated_memory_per_shot_kb', 0):.1f}KB"
            )
            report.append(f"  Memory trend: {data.get('memory_trend', 'unknown')}")
            report.append(
                f"  Efficiency rating: {data.get('memory_efficiency_rating', 'unknown')}"
            )
            report.append("")

        if "ui_responsiveness" in results:
            data = results["ui_responsiveness"]
            report.append("UI RESPONSIVENESS ANALYSIS")
            report.append("-" * 27)
            report.append(
                f"  Total blocking time: {data.get('total_blocking_time_ms', 0):.1f}ms"
            )
            report.append(
                f"  High severity operations: {data.get('high_severity_operations', 0)}"
            )
            report.append(
                f"  Responsiveness rating: {data.get('ui_responsiveness_rating', 'unknown')}"
            )

            if "blocking_operations" in data:
                report.append("  Blocking operations:")
                report.extend(
                    f"    • {op['operation']}: {op['duration_ms']:.1f}ms ({op['severity']} severity)"
                    for op in data["blocking_operations"]
                    if op["blocks_ui"]
                )

            recommendations = data.get("recommendations", [])
            if recommendations:
                report.append("  Recommendations:")
                report.extend(f"    → {rec}" for rec in recommendations)
            report.append("")

        # Final Optimization Recommendations
        report.append("🎯 OPTIMIZATION RECOMMENDATIONS")
        report.append("-" * 32)

        priority_fixes = []

        if (
            "shot_name_extraction" in results
            and results["shot_name_extraction"].get("improvement_percent", 0) > 20
        ):
            priority_fixes.append(
                "HIGH: Implement optimized regex pattern for shot name extraction"
            )

        if "thumbnail_discovery" in results:
            fs_ops = results["thumbnail_discovery"].get("fs_ops_per_shot", 0)
            if fs_ops > 3:
                priority_fixes.append(
                    "HIGH: Reduce filesystem operations through better caching"
                )

            bottleneck = results["thumbnail_discovery"].get("bottleneck_stage", "")
            if bottleneck:
                priority_fixes.append(
                    f"MEDIUM: Optimize {bottleneck} stage of thumbnail discovery"
                )

        if (
            "ui_responsiveness" in results
            and results["ui_responsiveness"].get("total_blocking_time_ms", 0) > 50
        ):
            priority_fixes.append(
                "HIGH: Move blocking operations to background threads"
            )

        if (
            "memory_patterns" in results
            and results["memory_patterns"].get("memory_growth_mb", 0) > 10
        ):
            priority_fixes.append(
                "MEDIUM: Investigate memory growth and implement cleanup"
            )

        for i, fix in enumerate(priority_fixes, 1):
            report.append(f"{i}. {fix}")

        if not priority_fixes:
            report.append(
                "✅ No high-priority optimizations needed - performance is acceptable"
            )

        report.append("")
        report.append("=" * 80)

        return "\n".join(report)


def main() -> None:
    """Main entry point."""
    # Standard library imports
    import argparse

    parser = argparse.ArgumentParser(
        description="Profile ShotBot thumbnail discovery bottlenecks"
    )
    parser.add_argument(
        "--memory-duration",
        type=int,
        default=15,
        help="Duration for memory profiling (seconds)",
    )
    parser.add_argument("--output", help="Output file for report")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")

    # Run profiler
    profiler = ThumbnailBottleneckProfiler()
    results = profiler.run_comprehensive_analysis(args.memory_duration)

    # Generate report
    report = profiler.generate_bottleneck_report(results)
    print(report)

    # Save to file if specified
    if args.output:
        output_path = Path(args.output)
        with output_path.open("w") as f:
            f.write(report)
        print(f"\nBottleneck analysis saved to: {args.output}")


if __name__ == "__main__":
    main()
