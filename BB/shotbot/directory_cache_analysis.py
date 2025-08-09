#!/usr/bin/env python3
"""
Directory Operations and Cache Performance Analysis for ShotBot

Analyzes directory traversal, path validation caching, and memory usage patterns
to identify optimization opportunities.
"""

import sys
import tempfile
import time
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from utils import PathUtils, VersionUtils, clear_all_caches, get_cache_stats


class DirectoryCacheAnalyzer:
    """Analyzer for directory operations and caching performance."""

    def __init__(self):
        self.test_data_root = None
        self.results = {
            "path_validation": {},
            "directory_traversal": {},
            "cache_efficiency": {},
            "memory_patterns": {},
            "optimization_opportunities": [],
        }

    def setup_test_directory_structure(self) -> Path:
        """Create realistic VFX directory structure for testing."""
        print("Setting up test directory structure...")

        base_temp = Path(tempfile.mkdtemp(prefix="shotbot_dir_perf_"))
        self.test_data_root = base_temp

        # Create VFX-like directory structure
        shows_dir = base_temp / "shows" / "test_show" / "shots"

        # Create multiple sequences and shots
        sequences = ["SEQ01", "SEQ02", "SEQ03"]
        shots = ["001", "002", "003", "004", "005"]
        users = ["user1", "user2", "user3", "user4", "user5"]

        total_files = 0
        total_dirs = 0

        for seq in sequences:
            for shot in shots:
                shot_name = f"{seq}_{shot}"
                shot_dir = shows_dir / seq / shot_name

                # Create standard VFX directories
                dirs_to_create = [
                    shot_dir / "user",
                    shot_dir / "elements" / "plates" / "raw",
                    shot_dir / "work" / "comp" / "nuke" / "scenes",
                    shot_dir / "work" / "comp" / "nuke" / "scripts",
                    shot_dir / "work" / "matchmove" / "3de",
                    shot_dir / "work" / "roto" / "silhouette",
                    shot_dir / "output" / "comp" / "main",
                    shot_dir / "output" / "elements",
                ]

                for dir_path in dirs_to_create:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    total_dirs += 1

                # Create user directories with various structures
                for user in users:
                    user_dir = shot_dir / "user" / user
                    user_dir.mkdir(parents=True, exist_ok=True)
                    total_dirs += 1

                    # Create varied 3DE directory structures
                    threede_paths = [
                        user_dir / "mm" / "3de" / "scenes",
                        user_dir / "matchmove" / "scenes",
                        user_dir / "work" / "3de",
                        user_dir / "tracking" / "3de" / "exports",
                    ]

                    for path in threede_paths:
                        path.mkdir(parents=True, exist_ok=True)
                        total_dirs += 1

                        # Create .3de files with different naming patterns
                        files_to_create = [
                            path / f"{shot_name}_track_v001.3de",
                            path / f"bg01_{shot_name}_v002.3de",
                            path / "fg01_comp_v001.3de",
                            path / "plate_main_v003.3de",
                        ]

                        for file_path in files_to_create:
                            file_path.touch()
                            total_files += 1

                # Create raw plate structure with versions
                plate_base = shot_dir / "elements" / "plates" / "raw"
                for plate in ["BG01", "FG01", "bg01", "fg02"]:
                    for version in ["v001", "v002", "v003"]:
                        version_dir = plate_base / plate / version / "exr" / "4312x2304"
                        version_dir.mkdir(parents=True, exist_ok=True)
                        total_dirs += 1

                        # Create test EXR files with various color spaces
                        color_spaces = ["aces", "lin_sgamut3cine", "rec709"]
                        for cs in color_spaces:
                            for frame in range(1001, 1011):  # 10 frames
                                exr_file = (
                                    version_dir
                                    / f"{shot_name}_turnover-plate_{plate}_{cs}_{version}.{frame:04d}.exr"
                                )
                                exr_file.touch()
                                total_files += 1

        print(f"Created test structure: {total_dirs} directories, {total_files} files")
        return base_temp

    def analyze_path_validation_performance(self):
        """Analyze PathUtils.validate_path_exists performance with caching."""
        print("\n1. PATH VALIDATION PERFORMANCE ANALYSIS")
        print("-" * 60)

        if not self.test_data_root:
            self.setup_test_directory_structure()

        # Collect various types of paths for testing
        all_paths = list(self.test_data_root.rglob("*"))

        # Categorize paths
        existing_files = [str(p) for p in all_paths if p.is_file()][:100]
        existing_dirs = [str(p) for p in all_paths if p.is_dir()][:100]
        non_existent_paths = [str(p) + "_missing" for p in all_paths[:50]]

        test_paths = existing_files + existing_dirs + non_existent_paths

        print(
            f"Testing {len(test_paths)} paths ({len(existing_files)} files, {len(existing_dirs)} dirs, {len(non_existent_paths)} missing)"
        )

        # Test 1: Cold cache performance
        clear_all_caches()
        start_time = time.perf_counter()
        for path in test_paths:
            PathUtils.validate_path_exists(path)
        cold_cache_time = time.perf_counter() - start_time

        cache_stats_after_cold = get_cache_stats()

        # Test 2: Warm cache performance
        start_time = time.perf_counter()
        for path in test_paths:
            PathUtils.validate_path_exists(path)
        warm_cache_time = time.perf_counter() - start_time

        cache_stats_after_warm = get_cache_stats()

        # Test 3: Batch validation performance
        clear_all_caches()
        start_time = time.perf_counter()
        batch_results = PathUtils.batch_validate_paths(test_paths)
        batch_time = time.perf_counter() - start_time

        # Test 4: Partial cache hit scenario (50% cached)
        clear_all_caches()
        # Pre-populate cache with 50% of paths
        for path in test_paths[: len(test_paths) // 2]:
            PathUtils.validate_path_exists(path)

        start_time = time.perf_counter()
        for path in test_paths:
            PathUtils.validate_path_exists(path)
        partial_cache_time = time.perf_counter() - start_time

        # Calculate metrics
        cache_speedup = cold_cache_time / warm_cache_time if warm_cache_time > 0 else 0
        batch_speedup = cold_cache_time / batch_time if batch_time > 0 else 0
        per_path_cold = cold_cache_time * 1000 / len(test_paths)  # ms per path
        per_path_warm = warm_cache_time * 1000 / len(test_paths)  # ms per path

        self.results["path_validation"] = {
            "paths_tested": len(test_paths),
            "cold_cache_time_ms": cold_cache_time * 1000,
            "warm_cache_time_ms": warm_cache_time * 1000,
            "batch_time_ms": batch_time * 1000,
            "partial_cache_time_ms": partial_cache_time * 1000,
            "cache_speedup": cache_speedup,
            "batch_speedup": batch_speedup,
            "per_path_cold_ms": per_path_cold,
            "per_path_warm_ms": per_path_warm,
            "cache_size_after_cold": cache_stats_after_cold["path_cache_size"],
            "cache_size_after_warm": cache_stats_after_warm["path_cache_size"],
        }

        print(
            f"Cold cache (first time): {cold_cache_time * 1000:.1f} ms ({per_path_cold:.3f} ms/path)"
        )
        print(
            f"Warm cache (cached): {warm_cache_time * 1000:.1f} ms ({per_path_warm:.3f} ms/path)"
        )
        print(f"Batch validation: {batch_time * 1000:.1f} ms")
        print(f"Partial cache hit: {partial_cache_time * 1000:.1f} ms")
        print(f"Cache speedup: {cache_speedup:.1f}x")
        print(f"Batch speedup: {batch_speedup:.1f}x")
        print(f"Cache size: {cache_stats_after_warm['path_cache_size']} entries")

        # Identify optimization opportunities
        if cache_speedup > 3:
            self.results["optimization_opportunities"].append(
                {
                    "category": "path_caching",
                    "impact": "high",
                    "description": f"Path caching provides {cache_speedup:.1f}x speedup",
                    "recommendation": "Increase cache TTL from 30s to 300s for better hit rates",
                }
            )

        if per_path_cold > 1.0:  # > 1ms per path validation
            self.results["optimization_opportunities"].append(
                {
                    "category": "path_validation_overhead",
                    "impact": "medium",
                    "description": f"Path validation takes {per_path_cold:.1f}ms per path when uncached",
                    "recommendation": "Use batch validation for multiple paths",
                }
            )

    def analyze_directory_traversal_performance(self):
        """Analyze rglob and iterdir performance patterns."""
        print("\n2. DIRECTORY TRAVERSAL PERFORMANCE")
        print("-" * 60)

        if not self.test_data_root:
            self.setup_test_directory_structure()

        test_shot_dir = (
            self.test_data_root
            / "shows"
            / "test_show"
            / "shots"
            / "SEQ01"
            / "SEQ01_001"
        )

        # Test 1: rglob patterns (used in 3DE scene discovery)
        traversal_tests = [
            ("*.3de", "3DE files"),
            ("*.exr", "EXR files"),
            ("*", "All files"),
            ("v*", "Version directories"),
        ]

        traversal_results = {}

        for pattern, description in traversal_tests:
            start_time = time.perf_counter()
            results = list(test_shot_dir.rglob(pattern))
            elapsed = time.perf_counter() - start_time

            traversal_results[pattern] = {
                "time_ms": elapsed * 1000,
                "results_count": len(results),
                "description": description,
            }

            print(
                f"{description:20} ({pattern:10}): {elapsed * 1000:6.1f} ms ({len(results):4d} results)"
            )

        # Test 2: Compare iterdir + rglob vs direct rglob
        user_dir = test_shot_dir / "user"

        # Method 1: Direct rglob from user directory
        start_time = time.perf_counter()
        direct_results = list(user_dir.rglob("*.3de"))
        direct_time = time.perf_counter() - start_time

        # Method 2: iterdir then rglob (current approach in ThreeDESceneFinder)
        start_time = time.perf_counter()
        iterdir_results = []
        for user_path in user_dir.iterdir():
            if user_path.is_dir():
                iterdir_results.extend(user_path.rglob("*.3de"))
        iterdir_time = time.perf_counter() - start_time

        # Test 3: Deep directory nesting impact
        deep_paths = []
        for path in test_shot_dir.rglob("*"):
            if path.is_dir():
                depth = len(path.relative_to(test_shot_dir).parts)
                deep_paths.append((path, depth))

        max_depth = max(depth for _, depth in deep_paths)
        avg_depth = sum(depth for _, depth in deep_paths) / len(deep_paths)

        traversal_results.update(
            {
                "direct_rglob": {
                    "time_ms": direct_time * 1000,
                    "results_count": len(direct_results),
                },
                "iterdir_rglob": {
                    "time_ms": iterdir_time * 1000,
                    "results_count": len(iterdir_results),
                },
                "max_depth": max_depth,
                "avg_depth": avg_depth,
                "total_directories": len([p for p, _ in deep_paths]),
            }
        )

        self.results["directory_traversal"] = traversal_results

        print("\nDirectory traversal comparison:")
        print(
            f"Direct rglob: {direct_time * 1000:.1f} ms ({len(direct_results)} results)"
        )
        print(
            f"iterdir+rglob: {iterdir_time * 1000:.1f} ms ({len(iterdir_results)} results)"
        )
        print(f"Directory structure: max depth {max_depth}, avg depth {avg_depth:.1f}")

        # Optimization recommendations
        if iterdir_time > direct_time * 1.5:
            self.results["optimization_opportunities"].append(
                {
                    "category": "directory_traversal",
                    "impact": "medium",
                    "description": f"Direct rglob is {iterdir_time / direct_time:.1f}x faster than iterdir+rglob",
                    "recommendation": "Replace iterdir+rglob with direct rglob in ThreeDESceneFinder",
                }
            )

    def analyze_version_caching_performance(self):
        """Analyze VersionUtils caching effectiveness."""
        print("\n3. VERSION DIRECTORY CACHING ANALYSIS")
        print("-" * 60)

        if not self.test_data_root:
            self.setup_test_directory_structure()

        # Find all directories that contain version subdirectories
        plate_dirs = []
        for path in self.test_data_root.rglob("raw/*"):
            if path.is_dir() and any(
                child.is_dir() and child.name.startswith("v")
                for child in path.iterdir()
            ):
                plate_dirs.append(path)

        print(f"Testing version caching on {len(plate_dirs)} directories")

        # Test 1: Cold version cache
        clear_all_caches()
        start_time = time.perf_counter()
        cold_results = []
        for vdir in plate_dirs:
            result = VersionUtils.find_version_directories(vdir)
            cold_results.append(len(result))
        cold_time = time.perf_counter() - start_time

        # Test 2: Warm version cache
        start_time = time.perf_counter()
        warm_results = []
        for vdir in plate_dirs:
            result = VersionUtils.find_version_directories(vdir)
            warm_results.append(len(result))
        warm_time = time.perf_counter() - start_time

        # Test 3: get_latest_version performance
        start_time = time.perf_counter()
        latest_versions = []
        for vdir in plate_dirs:
            latest = VersionUtils.get_latest_version(vdir)
            latest_versions.append(latest)
        latest_time = time.perf_counter() - start_time

        # Test 4: extract_version_from_path (LRU cached)
        version_paths = [
            str(path)
            for path in self.test_data_root.rglob("v*")
            if path.is_dir() and path.name.startswith("v")
        ][:50]

        start_time = time.perf_counter()
        extracted_versions = []
        for path in version_paths:
            version = VersionUtils.extract_version_from_path(path)
            extracted_versions.append(version)
        extract_time = time.perf_counter() - start_time

        lru_cache_info = VersionUtils.extract_version_from_path.cache_info()

        version_cache_speedup = cold_time / warm_time if warm_time > 0 else 0
        total_versions_found = sum(cold_results)

        self.results["cache_efficiency"]["version_operations"] = {
            "directories_tested": len(plate_dirs),
            "cold_time_ms": cold_time * 1000,
            "warm_time_ms": warm_time * 1000,
            "latest_time_ms": latest_time * 1000,
            "extract_time_ms": extract_time * 1000,
            "cache_speedup": version_cache_speedup,
            "total_versions_found": total_versions_found,
            "lru_cache_info": {
                "hits": lru_cache_info.hits,
                "misses": lru_cache_info.misses,
                "currsize": lru_cache_info.currsize,
                "maxsize": lru_cache_info.maxsize,
            },
        }

        print("Version directory scanning:")
        print(
            f"  Cold cache: {cold_time * 1000:.1f} ms ({total_versions_found} versions found)"
        )
        print(f"  Warm cache: {warm_time * 1000:.1f} ms")
        print(f"  Cache speedup: {version_cache_speedup:.1f}x")
        print(f"  Latest version lookup: {latest_time * 1000:.1f} ms")
        print(f"  Path version extraction: {extract_time * 1000:.1f} ms")
        print(
            f"  LRU cache: {lru_cache_info.hits} hits, {lru_cache_info.misses} misses"
        )

        if version_cache_speedup > 5:
            self.results["optimization_opportunities"].append(
                {
                    "category": "version_caching",
                    "impact": "medium",
                    "description": f"Version caching provides {version_cache_speedup:.1f}x speedup",
                    "recommendation": "Consider longer cache TTL for version directories (currently 30s)",
                }
            )

    def analyze_memory_and_cache_growth(self):
        """Analyze memory usage patterns and cache growth."""
        print("\n4. MEMORY AND CACHE GROWTH ANALYSIS")
        print("-" * 60)

        # Test cache growth under realistic load
        test_paths = [
            f"/fake/path/{i}/subdir/{j}" for i in range(100) for j in range(10)
        ]

        # Memory tracking (simplified without psutil)
        import resource

        # Measure cache growth
        clear_all_caches()
        initial_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        # Populate path cache gradually
        cache_sizes = []
        memory_usage = []

        for i in range(0, len(test_paths), 50):
            batch = test_paths[i : i + 50]
            for path in batch:
                PathUtils.validate_path_exists(path)

            cache_stats = get_cache_stats()
            current_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

            cache_sizes.append(cache_stats["path_cache_size"])
            memory_usage.append(current_memory - initial_memory)

        # Test cache cleanup behavior
        clear_all_caches()

        # Fill cache beyond cleanup threshold (1000 entries)
        large_path_set = [f"/test/cache/cleanup/{i}" for i in range(1500)]
        for path in large_path_set:
            PathUtils.validate_path_exists(path)

        cache_stats_before_cleanup = get_cache_stats()

        # Trigger cleanup by adding more paths
        additional_paths = [f"/test/trigger/cleanup/{i}" for i in range(100)]
        for path in additional_paths:
            PathUtils.validate_path_exists(path)

        cache_stats_after_cleanup = get_cache_stats()

        self.results["memory_patterns"] = {
            "cache_growth_pattern": "linear"
            if len(set(cache_sizes)) > len(cache_sizes) // 2
            else "stepped",
            "max_cache_size_tested": max(cache_sizes) if cache_sizes else 0,
            "memory_per_cache_entry_kb": (max(memory_usage) / max(cache_sizes))
            if (cache_sizes and max(cache_sizes) > 0)
            else 0,
            "cleanup_triggered": cache_stats_before_cleanup["path_cache_size"]
            > cache_stats_after_cleanup["path_cache_size"],
            "cache_size_before_cleanup": cache_stats_before_cleanup["path_cache_size"],
            "cache_size_after_cleanup": cache_stats_after_cleanup["path_cache_size"],
        }

        print("Cache growth analysis:")
        print(
            f"  Max cache size tested: {max(cache_sizes) if cache_sizes else 0} entries"
        )
        print(
            f"  Growth pattern: {self.results['memory_patterns']['cache_growth_pattern']}"
        )
        if memory_usage:
            avg_memory_per_entry = (
                sum(memory_usage) / sum(cache_sizes) if sum(cache_sizes) > 0 else 0
            )
            print(f"  Memory per entry: ~{avg_memory_per_entry:.1f} KB")

        print("Cache cleanup behavior:")
        print(
            f"  Before cleanup: {cache_stats_before_cleanup['path_cache_size']} entries"
        )
        print(
            f"  After cleanup: {cache_stats_after_cleanup['path_cache_size']} entries"
        )
        print(
            f"  Cleanup triggered: {self.results['memory_patterns']['cleanup_triggered']}"
        )

    def estimate_real_world_impact(self):
        """Estimate real-world performance impact."""
        print("\n5. REAL-WORLD PERFORMANCE IMPACT")
        print("-" * 60)

        # Based on our measurements, estimate typical scenarios
        scenarios = [
            {
                "name": "Shot list refresh (50 shots)",
                "path_validations": 50 * 10,  # 10 path checks per shot
                "rglob_operations": 50 * 3,  # 3 users per shot
                "version_lookups": 50 * 2,  # 2 version checks per shot
            },
            {
                "name": "Large 3DE scene discovery (200 shots)",
                "path_validations": 200 * 15,  # More paths checked
                "rglob_operations": 200 * 5,  # 5 users per shot
                "version_lookups": 200 * 1,  # Less version checking
            },
            {
                "name": "Single shot deep analysis",
                "path_validations": 50,
                "rglob_operations": 5,
                "version_lookups": 10,
            },
        ]

        # Performance estimates based on measurements
        path_validation_ms = self.results["path_validation"].get(
            "per_path_cold_ms", 1.0
        )
        rglob_ms = 10.0  # Estimate from typical rglob operations
        version_lookup_ms = 2.0  # Estimate from version operations

        print("Estimated performance impact (worst case - cold caches):")
        for scenario in scenarios:
            path_time = scenario["path_validations"] * path_validation_ms
            rglob_time = scenario["rglob_operations"] * rglob_ms
            version_time = scenario["version_lookups"] * version_lookup_ms
            total_time = path_time + rglob_time + version_time

            print(f"\n{scenario['name']}:")
            print(f"  Path validation: {path_time:.0f} ms")
            print(f"  Directory scanning: {rglob_time:.0f} ms")
            print(f"  Version operations: {version_time:.0f} ms")
            print(f"  TOTAL: {total_time:.0f} ms ({total_time / 1000:.1f}s)")

            if total_time > 5000:
                print(
                    f"  ⚠️  SIGNIFICANT: {total_time / 1000:.1f}s delay from directory operations"
                )
            elif total_time > 1000:
                print("  ⚡ MODERATE: Noticeable delay from directory operations")
            else:
                print("  ✅ ACCEPTABLE: Minimal directory operation overhead")

    def generate_optimization_recommendations(self):
        """Generate comprehensive optimization recommendations."""
        print("\n6. OPTIMIZATION RECOMMENDATIONS")
        print("-" * 60)

        print("Priority optimizations based on analysis:")

        # Sort optimization opportunities by impact
        high_impact = [
            op
            for op in self.results["optimization_opportunities"]
            if op["impact"] == "high"
        ]
        medium_impact = [
            op
            for op in self.results["optimization_opportunities"]
            if op["impact"] == "medium"
        ]

        print(f"\nHIGH IMPACT ({len(high_impact)} opportunities):")
        for i, op in enumerate(high_impact, 1):
            print(f"  {i}. {op['description']}")
            print(f"     → {op['recommendation']}")

        print(f"\nMEDIUM IMPACT ({len(medium_impact)} opportunities):")
        for i, op in enumerate(medium_impact, 1):
            print(f"  {i}. {op['description']}")
            print(f"     → {op['recommendation']}")

        print("\nGeneral recommendations:")
        print("  1. Increase path cache TTL from 30s to 300s for production use")
        print("  2. Implement batch path validation for multiple operations")
        print(
            "  3. Consider using os.scandir() instead of iterdir() for large directories"
        )
        print("  4. Pre-populate caches during application startup")
        print("  5. Monitor cache hit rates in production logs")

    def cleanup(self):
        """Clean up test data."""
        if self.test_data_root:
            import shutil

            try:
                shutil.rmtree(self.test_data_root)
                print(f"\nCleaned up test directory: {self.test_data_root}")
            except Exception as e:
                print(f"\nWarning: Could not clean up {self.test_data_root}: {e}")

    def run_full_analysis(self):
        """Run complete directory and cache analysis."""
        print("SHOTBOT DIRECTORY & CACHE PERFORMANCE ANALYSIS")
        print("=" * 80)

        try:
            self.analyze_path_validation_performance()
            self.analyze_directory_traversal_performance()
            self.analyze_version_caching_performance()
            self.analyze_memory_and_cache_growth()
            self.estimate_real_world_impact()
            self.generate_optimization_recommendations()

        finally:
            self.cleanup()

        return self.results


def main():
    """Run directory and cache performance analysis."""
    analyzer = DirectoryCacheAnalyzer()
    results = analyzer.run_full_analysis()

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE - Directory and cache performance profiled")
    print("=" * 80)


if __name__ == "__main__":
    main()
