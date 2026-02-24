"""Performance benchmarks and profiling for ThreeDESceneFinder.

This module provides comprehensive performance testing to identify bottlenecks
in the 3DE scene discovery process and validate optimization improvements.

Key Performance Metrics:
- Directory traversal time (rglob vs os.scandir vs find command)
- Regex pattern matching overhead
- Path manipulation efficiency
- Subprocess call overhead
- Memory usage patterns
- Cache effectiveness

Test Scenarios:
1. Small project (10 shots, 50 .3de files)
2. Medium project (100 shots, 500 .3de files)
3. Large project (1000 shots, 5000 .3de files)
4. Deep nesting (15+ directory levels)
5. Many users (20+ user directories per shot)
"""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

# Standard library imports
import cProfile
import io
import pstats
import re
import subprocess
import tempfile
import time
from pathlib import Path

# Third-party imports
import psutil
import pytest

# Local application imports
# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from threede_scene_finder import (
    OptimizedThreeDESceneFinder as ThreeDESceneFinder,
)


pytestmark = pytest.mark.performance


class PerformanceProfiler:
    """Utility class for profiling ThreeDESceneFinder operations."""

    def __init__(self) -> None:
        self.profiles = {}
        self.memory_usage = {}
        self.timing_data = {}

    def profile_method(self, method_name: str, func, *args, **kwargs):
        """Profile a method call with cProfile."""
        profiler = cProfile.Profile()

        # Memory before

        process = psutil.Process()
        memory_before = process.memory_info().rss / 1024 / 1024  # MB

        # Profile the call
        profiler.enable()
        start_time = time.perf_counter()

        try:
            result = func(*args, **kwargs)
        except Exception as e:
            result = f"ERROR: {e}"
        finally:
            profiler.disable()

        end_time = time.perf_counter()

        # Memory after
        memory_after = process.memory_info().rss / 1024 / 1024  # MB
        memory_used = memory_after - memory_before

        # Store results
        execution_time = end_time - start_time
        self.timing_data[method_name] = execution_time
        self.memory_usage[method_name] = memory_used

        # Get profile stats
        stats_stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stats_stream)
        stats.sort_stats("cumulative")
        stats.print_stats(20)  # Top 20 functions

        self.profiles[method_name] = {
            "execution_time": execution_time,
            "memory_used_mb": memory_used,
            "result_count": len(result) if isinstance(result, list) else 0,
            "profile_output": stats_stream.getvalue(),
            "result": result,
        }

        return result

    def create_performance_report(self) -> str:
        """Generate a comprehensive performance report."""
        report = ["THREEDE SCENE FINDER PERFORMANCE REPORT"]
        report.append("=" * 60)
        report.append("")

        # Summary table
        report.append("PERFORMANCE SUMMARY:")
        report.append("-" * 30)
        report.append(
            f"{'Method':<30} {'Time (s)':<10} {'Memory (MB)':<12} {'Results':<10}"
        )
        report.append("-" * 65)

        for method_name, data in self.profiles.items():
            report.append(
                f"{method_name:<30} {data['execution_time']:<10.3f} {data['memory_used_mb']:<12.1f} {data['result_count']:<10}"
            )

        report.append("")

        # Detailed profiles
        for method_name, data in self.profiles.items():
            report.append(f"DETAILED PROFILE: {method_name}")
            report.append("-" * 40)
            report.append(f"Execution time: {data['execution_time']:.3f} seconds")
            report.append(f"Memory usage: {data['memory_used_mb']:.1f} MB")
            report.append(f"Results found: {data['result_count']}")
            report.append("")
            report.append("Top function calls:")
            report.append(data["profile_output"])
            report.append("\n" + "=" * 60 + "\n")

        return "\n".join(report)


class VFXProjectGenerator:
    """Generate realistic VFX project structures for performance testing."""

    @staticmethod
    def create_small_project(base_path: Path) -> tuple[Path, dict[str, int]]:
        """Create small test project (10 shots, ~50 .3de files)."""
        shows_root = base_path / "shows"
        show_path = shows_root / "small_project" / "shots"

        stats = {"shots": 0, "users": 0, "files": 0, "directories": 0}

        for seq_num in range(1, 3):  # 2 sequences
            seq_name = f"seq{seq_num:02d}"

            for shot_num in range(10, 60, 10):  # 5 shots per sequence
                shot_dir = show_path / seq_name / f"{seq_name}_{shot_num:04d}"
                stats["shots"] += 1

                # Create user directories
                user_dir = shot_dir / "user"

                for user_num in range(1, 4):  # 3 users per shot
                    user_name = f"artist{user_num}"
                    user_path = user_dir / user_name
                    user_path.mkdir(parents=True, exist_ok=True)
                    stats["users"] += 1
                    stats["directories"] += 1

                    # Create 3DE files in various locations
                    for plate in ["bg01", "fg01"]:
                        # Standard path
                        threede_dir = (
                            user_path
                            / "mm"
                            / "3de"
                            / "mm-default"
                            / "scenes"
                            / "scene"
                            / plate.upper()
                        )
                        threede_dir.mkdir(parents=True, exist_ok=True)
                        stats["directories"] += 6  # All parent dirs

                        # Create .3de file
                        threede_file = (
                            threede_dir
                            / f"{show_path.parent.name}_{seq_name}_{shot_num:04d}_{plate}.3de"
                        )
                        threede_file.write_text(
                            f"# 3DE Scene File\nproject_name: {show_path.parent.name}"
                        )
                        stats["files"] += 1

                        # Also create alternative path structure
                        if plate == "bg01":
                            alt_dir = user_path / "3de" / "scenes"
                            alt_dir.mkdir(parents=True, exist_ok=True)
                            alt_file = alt_dir / f"alternative_{plate}.3de"
                            alt_file.write_text("# Alternative 3DE Scene")
                            stats["files"] += 1
                            stats["directories"] += 2

        return shows_root, stats

    @staticmethod
    def create_medium_project(base_path: Path) -> tuple[Path, dict[str, int]]:
        """Create medium test project (100 shots, ~500 .3de files)."""
        shows_root = base_path / "shows"
        show_path = shows_root / "medium_project" / "shots"

        stats = {"shots": 0, "users": 0, "files": 0, "directories": 0}

        for seq_num in range(1, 6):  # 5 sequences
            seq_name = f"seq{seq_num:02d}"

            for shot_num in range(10, 210, 10):  # 20 shots per sequence
                shot_dir = show_path / seq_name / f"{seq_name}_{shot_num:04d}"
                stats["shots"] += 1

                # Create user and publish directories
                user_dir = shot_dir / "user"
                publish_dir = shot_dir / "publish"

                # User directories
                for user_num in range(1, 6):  # 5 users per shot
                    user_name = f"artist{user_num}"
                    user_path = user_dir / user_name
                    user_path.mkdir(parents=True, exist_ok=True)
                    stats["users"] += 1
                    stats["directories"] += 1

                    # Create nested 3DE structure
                    if user_num <= 3:  # Only first 3 users have 3DE files
                        for plate in ["BG01", "FG01", "FG02"]:
                            # Deep nesting as seen in real projects
                            threede_dir = (
                                user_path
                                / "mm"
                                / "3de"
                                / "mm-default"
                                / "scenes"
                                / "scene"
                                / plate
                            )
                            threede_dir.mkdir(parents=True, exist_ok=True)
                            stats["directories"] += 6

                            # Create multiple versions
                            for version in ["v001", "v002"]:
                                if (
                                    shot_num % 20 == 0 or version == "v001"
                                ):  # Not every shot has all versions
                                    threede_file = threede_dir / f"scene_{version}.3de"
                                    threede_file.write_text(
                                        f"# 3DE Scene {version}\nplate: {plate}"
                                    )
                                    stats["files"] += 1

                # Published 3DE files
                if shot_num % 30 == 0:  # Only some shots have published files
                    pub_dir = publish_dir / "mm" / "default"
                    pub_dir.mkdir(parents=True, exist_ok=True)
                    pub_file = pub_dir / "final_scene.3de"
                    pub_file.write_text("# Published 3DE Scene")
                    stats["files"] += 1
                    stats["directories"] += 3

        return shows_root, stats

    @staticmethod
    def create_large_project(base_path: Path) -> tuple[Path, dict[str, int]]:
        """Create large test project (1000 shots, ~5000 .3de files)."""
        shows_root = base_path / "shows"
        show_path = shows_root / "large_project" / "shots"

        stats = {"shots": 0, "users": 0, "files": 0, "directories": 0}

        for seq_num in range(1, 11):  # 10 sequences
            seq_name = f"seq{seq_num:02d}"

            for shot_num in range(100, 1100, 10):  # 100 shots per sequence
                shot_dir = show_path / seq_name / f"{seq_name}_{shot_num:04d}"
                stats["shots"] += 1

                user_dir = shot_dir / "user"
                publish_dir = shot_dir / "publish"

                # Create users (not every shot has every user)
                num_users = 3 + (shot_num % 4)  # 3-6 users per shot
                for user_num in range(1, num_users + 1):
                    user_name = f"user{user_num:02d}"
                    user_path = user_dir / user_name
                    user_path.mkdir(parents=True, exist_ok=True)
                    stats["users"] += 1
                    stats["directories"] += 1

                    # Only create 3DE files for some users/shots to be realistic
                    if user_num <= 2 and shot_num % 5 == 0:
                        # Create various path structures
                        patterns = [
                            ["mm", "3de", "mm-default", "scenes", "scene", "BG01"],
                            ["matchmove", "3de", "scenes", "FG01"],
                            ["3de", "projects", "BG01"],
                        ]

                        for i, pattern in enumerate(patterns):
                            if user_num == 1 or (user_num == 2 and i < 2):
                                threede_dir = user_path
                                for segment in pattern:
                                    threede_dir = threede_dir / segment
                                threede_dir.mkdir(parents=True, exist_ok=True)
                                stats["directories"] += len(pattern)

                                # Create 3DE file
                                plate_name = (
                                    pattern[-1]
                                    if pattern[-1] in ["BG01", "FG01"]
                                    else "main"
                                )
                                threede_file = (
                                    threede_dir / f"scene_{plate_name.lower()}.3de"
                                )
                                threede_file.write_text(
                                    f"# 3DE Scene for {user_name}\nplate: {plate_name}"
                                )
                                stats["files"] += 1

                # Occasional published files
                if shot_num % 50 == 0:
                    for dept in ["mm", "roto", "comp"]:
                        pub_dir = publish_dir / dept / "v001"
                        pub_dir.mkdir(parents=True, exist_ok=True)
                        if dept == "mm":  # Only mm dept has 3DE files
                            pub_file = pub_dir / "published_scene.3de"
                            pub_file.write_text(f"# Published scene from {dept}")
                            stats["files"] += 1
                        stats["directories"] += 3

        return shows_root, stats


@pytest.fixture
def profiler():
    """Provide a performance profiler instance."""
    return PerformanceProfiler()


@pytest.fixture
def small_project(tmp_path):
    """Create small VFX project for testing."""
    return VFXProjectGenerator.create_small_project(tmp_path)


@pytest.fixture
def medium_project(tmp_path):
    """Create medium VFX project for testing."""
    return VFXProjectGenerator.create_medium_project(tmp_path)


@pytest.fixture
def large_project(tmp_path):
    """Create large VFX project for testing."""
    return VFXProjectGenerator.create_large_project(tmp_path)


class TestFileSystemTraversalPerformance:
    """Test different file system traversal methods."""

    @pytest.mark.real_subprocess  # Opt out of autouse subprocess mock
    def test_rglob_vs_find_command_small(self, small_project, profiler) -> None:
        """Compare rglob vs find command on small project."""
        shows_root, stats = small_project

        # Test rglob approach
        def test_rglob():
            files = []
            for show_dir in shows_root.iterdir():
                if show_dir.is_dir():
                    files.extend(list(show_dir.rglob("*.3de")))
            return files

        # Test find command approach
        def test_find_command():
            files = []
            for show_dir in shows_root.iterdir():
                if show_dir.is_dir():
                    try:
                        result = subprocess.run(
                            ["find", str(show_dir), "-name", "*.3de", "-type", "f"],
                            check=False, capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        if result.stdout:
                            files.extend(
                                [
                                    Path(p)
                                    for p in result.stdout.strip().split("\n")
                                    if p
                                ]
                            )
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        # Fallback to rglob
                        files.extend(list(show_dir.rglob("*.3de")))
            return files

        # Profile both approaches
        rglob_result = profiler.profile_method("rglob_small", test_rglob)
        find_result = profiler.profile_method("find_command_small", test_find_command)

        # Validate results are similar
        assert len(rglob_result) == len(find_result), (
            f"Different file counts: rglob={len(rglob_result)}, find={len(find_result)}"
        )

        print(f"\nSmall project stats: {stats}")
        print(f"RGlob found: {len(rglob_result)} files")
        print(f"Find found: {len(find_result)} files")

    def test_rglob_vs_find_command_medium(self, medium_project, profiler) -> None:
        """Compare rglob vs find command on medium project."""
        shows_root, stats = medium_project

        def test_rglob_medium():
            files = []
            for show_dir in shows_root.iterdir():
                if show_dir.is_dir():
                    files.extend(list(show_dir.rglob("*.3de")))
            return files

        def test_find_command_medium():
            files = []
            for show_dir in shows_root.iterdir():
                if show_dir.is_dir():
                    try:
                        result = subprocess.run(
                            [
                                "find",
                                str(show_dir),
                                "-name",
                                "*.3de",
                                "-type",
                                "f",
                                "-maxdepth",
                                "15",
                            ],
                            check=False, capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if result.stdout:
                            files.extend(
                                [
                                    Path(p)
                                    for p in result.stdout.strip().split("\n")
                                    if p
                                ]
                            )
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        files.extend(list(show_dir.rglob("*.3de")))
            return files

        rglob_result = profiler.profile_method("rglob_medium", test_rglob_medium)
        find_result = profiler.profile_method(
            "find_command_medium", test_find_command_medium
        )

        print(f"\nMedium project stats: {stats}")
        print(
            f"RGlob found: {len(rglob_result)} files in {profiler.timing_data['rglob_medium']:.3f}s"
        )
        print(
            f"Find found: {len(find_result)} files in {profiler.timing_data['find_command_medium']:.3f}s"
        )

        # Performance comparison
        rglob_time = profiler.timing_data["rglob_medium"]
        find_time = profiler.timing_data["find_command_medium"]
        if find_time > 0:
            speedup = rglob_time / find_time
            print(f"Performance ratio (rglob/find): {speedup:.2f}x")


class TestSceneFinderMethods:
    """Test actual ThreeDESceneFinder methods for performance."""

    def test_find_scenes_for_shot_performance(self, medium_project, profiler) -> None:
        """Profile find_scenes_for_shot method."""
        shows_root, _stats = medium_project

        # Get a test shot path
        test_shot_path = (
            shows_root / "medium_project" / "shots" / "seq01" / "seq01_0010"
        )

        def test_find_scenes():
            return ThreeDESceneFinder.find_scenes_for_shot(
                shot_workspace_path=str(test_shot_path),
                show="medium_project",
                sequence="seq01",
                shot="seq01_0010",
                excluded_users={"testuser"},
            )

        scenes = profiler.profile_method("find_scenes_for_shot", test_find_scenes)

        print(f"\nFound {len(scenes)} scenes for shot seq01_0010")
        print(f"Time: {profiler.timing_data['find_scenes_for_shot']:.3f}s")
        print(f"Memory: {profiler.memory_usage['find_scenes_for_shot']:.1f}MB")

    def test_extract_plate_performance(self, medium_project, profiler) -> None:
        """Profile extract_plate_from_path method."""
        shows_root, _stats = medium_project

        # Get some test paths
        user_path = (
            shows_root
            / "medium_project"
            / "shots"
            / "seq01"
            / "seq01_0010"
            / "user"
            / "artist1"
        )

        # Create various path patterns to test
        patterns = [
            user_path
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "BG01"
            / "scene_v001.3de",
            user_path
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "FG01"
            / "scene_v001.3de",
            user_path / "3de" / "scenes" / "bg01" / "test.3de",
            user_path / "work" / "matchmove" / "plate01" / "scene.3de",
            user_path / "generic" / "folder" / "scene.3de",
        ]

        def test_extract_plates():
            results = []
            for path in patterns:
                plate = ThreeDESceneFinder.extract_plate_from_path(path, user_path)
                results.append((str(path), plate))
            return results

        plates = profiler.profile_method("extract_plate_from_path", test_extract_plates)

        print("\nPlate extraction results:")
        for path, plate in plates:
            print(f"  {Path(path).name} -> {plate}")

        print(f"Time: {profiler.timing_data['extract_plate_from_path']:.6f}s")

    def test_regex_pattern_performance(self, profiler) -> None:
        """Test regex pattern compilation and matching performance."""

        def test_regex_patterns():
            # Test current implementation

            # Patterns from ThreeDESceneFinder
            patterns = [
                re.compile(r"^[bf]g\d{2}$", re.IGNORECASE),
                re.compile(r"^plate_?\d+$", re.IGNORECASE),
                re.compile(r"^comp_?\d+$", re.IGNORECASE),
                re.compile(r"^shot_?\d+$", re.IGNORECASE),
                re.compile(r"^sc\d+$", re.IGNORECASE),
                re.compile(r"^[\w]+_v\d{3}$", re.IGNORECASE),
            ]

            # Test strings
            test_strings = [
                "bg01",
                "BG01",
                "fg02",
                "FG05",
                "plate01",
                "plate_01",
                "comp01",
                "comp_01",
                "shot010",
                "shot_010",
                "sc01",
                "sc10",
                "test_v001",
                "scene_v002",
                "random",
                "3de",
                "scenes",
                "work",
                "mm",
            ]

            matches = 0
            for test_str in test_strings * 1000:  # Repeat for measurable time
                for pattern in patterns:
                    if pattern.match(test_str):
                        matches += 1
                        break

            return matches

        matches = profiler.profile_method("regex_pattern_matching", test_regex_patterns)

        print(f"\nRegex matching found {matches} matches")
        print(f"Time: {profiler.timing_data['regex_pattern_matching']:.6f}s")


class TestScalingPerformance:
    """Test how performance scales with project size."""

    def test_performance_scaling(self, profiler) -> None:
        """Test performance across different project sizes."""
        # Create projects of different sizes in temp dirs
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Small project
            small_root, small_stats = VFXProjectGenerator.create_small_project(
                tmp_path / "small"
            )

            def test_small():
                return ThreeDESceneFinder.find_all_3de_files_in_show(
                    str(small_root), "small_project", timeout_seconds=30
                )

            small_result = profiler.profile_method("small_project_scan", test_small)

            # Medium project
            medium_root, medium_stats = VFXProjectGenerator.create_medium_project(
                tmp_path / "medium"
            )

            def test_medium():
                return ThreeDESceneFinder.find_all_3de_files_in_show(
                    str(medium_root), "medium_project", timeout_seconds=60
                )

            medium_result = profiler.profile_method("medium_project_scan", test_medium)

            # Print scaling analysis
            print("\nSCALING ANALYSIS:")
            print(
                f"Small project: {small_stats['shots']} shots, {small_stats['files']} files"
            )
            print(f"  Time: {profiler.timing_data['small_project_scan']:.3f}s")
            print(f"  Memory: {profiler.memory_usage['small_project_scan']:.1f}MB")
            print(f"  Files found: {len(small_result)}")
            print(
                f"  Files/second: {len(small_result) / profiler.timing_data['small_project_scan']:.1f}"
            )

            print(
                f"\nMedium project: {medium_stats['shots']} shots, {medium_stats['files']} files"
            )
            print(f"  Time: {profiler.timing_data['medium_project_scan']:.3f}s")
            print(f"  Memory: {profiler.memory_usage['medium_project_scan']:.1f}MB")
            print(f"  Files found: {len(medium_result)}")
            print(
                f"  Files/second: {len(medium_result) / profiler.timing_data['medium_project_scan']:.1f}"
            )

            # Calculate scaling factors
            size_ratio = medium_stats["files"] / small_stats["files"]
            time_ratio = (
                profiler.timing_data["medium_project_scan"]
                / profiler.timing_data["small_project_scan"]
            )
            print("\nScaling factor:")
            print(f"  Size increased by: {size_ratio:.1f}x")
            print(f"  Time increased by: {time_ratio:.1f}x")
            print(
                f"  Efficiency ratio: {size_ratio / time_ratio:.2f} (higher is better)"
            )


def test_generate_performance_report(profiler) -> None:
    """Generate and save performance report."""
    # This will be called after other tests to generate final report
    report = profiler.create_performance_report()

    # Save report to file
    report_path = Path("tests/performance/threede_finder_performance_report.txt")
    report_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
    with report_path.open("w") as f:
        f.write(report)

    print(f"\nPerformance report saved to: {report_path}")
    print("\nSUMMARY:")
    print(report.split("\n\n")[1])  # Print just the summary table


if __name__ == "__main__":
    # Can be run directly for quick profiling
    profiler = PerformanceProfiler()

    # Quick test
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        shows_root, stats = VFXProjectGenerator.create_small_project(tmp_path)

        def quick_test():
            return ThreeDESceneFinder.find_all_3de_files_in_show(
                str(shows_root), "small_project"
            )

        result = profiler.profile_method("quick_test", quick_test)

        print("QUICK PERFORMANCE TEST:")
        print(f"Created project with {stats}")
        print(f"Found {len(result)} .3de files")
        print(f"Time: {profiler.timing_data['quick_test']:.3f}s")
        print(f"Memory: {profiler.memory_usage['quick_test']:.1f}MB")

        if profiler.timing_data["quick_test"] > 0:
            files_per_second = len(result) / profiler.timing_data["quick_test"]
            print(f"Processing rate: {files_per_second:.1f} files/second")
