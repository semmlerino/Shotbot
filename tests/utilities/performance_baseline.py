#!/usr/bin/env python3
"""Performance baseline establishment for finder modules.

This script measures and records baseline performance metrics for
the various finder classes to ensure performance doesn't degrade
over time.
"""

# Standard library imports
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Local application imports
from maya_latest_finder import MayaLatestFinder
from shot_model import Shot
from targeted_shot_finder import TargetedShotsFinder
from threede_latest_finder import ThreeDELatestFinder


def measure_performance(
    name: str, func: Callable[[], Any], iterations: int = 10
) -> dict[str, float]:
    """Measure performance of a function.

    Args:
        name: Name of the test
        func: Function to test
        iterations: Number of iterations to run

    Returns:
        Dictionary with performance metrics

    """
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append(end - start)

    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    return {
        "name": name,
        "avg_ms": avg_time * 1000,
        "min_ms": min_time * 1000,
        "max_ms": max_time * 1000,
        "iterations": iterations,
    }


def create_test_workspace(
    path: Path, num_users: int = 5, files_per_user: int = 10
) -> None:
    """Create a test workspace structure.

    Args:
        path: Root path for workspace
        num_users: Number of user directories to create
        files_per_user: Number of files per user

    """
    for i in range(num_users):
        # Maya structure
        maya_scenes = path / "user" / f"user_{i:03d}" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True, exist_ok=True)

        for j in range(files_per_user):
            (maya_scenes / f"scene_v{j + 1:03d}.ma").touch()

        # 3DE structure
        for plate in ["PL01", "PL02", "FG01"]:
            threede_path = (
                path
                / "user"
                / f"user_{i:03d}"
                / "mm"
                / "3de"
                / "mm-default"
                / "scenes"
                / "scene"
                / plate
            )
            threede_path.mkdir(parents=True, exist_ok=True)

            for j in range(files_per_user):
                (threede_path / f"track_v{j + 1:03d}.3de").touch()


def test_maya_finder_performance() -> dict[str, float]:
    """Test MayaLatestFinder performance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        create_test_workspace(workspace, num_users=10, files_per_user=20)

        def find_latest():
            finder = MayaLatestFinder()
            return finder.find_latest_maya_scene(str(workspace))

        return measure_performance("MayaLatestFinder.find_latest", find_latest)


def test_maya_find_all_performance() -> dict[str, float]:
    """Test MayaLatestFinder.find_all performance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        create_test_workspace(workspace, num_users=10, files_per_user=20)

        def find_all():
            return MayaLatestFinder.find_all_maya_scenes(str(workspace))

        return measure_performance("MayaLatestFinder.find_all", find_all)


def test_threede_finder_performance() -> dict[str, float]:
    """Test ThreeDELatestFinder performance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        create_test_workspace(workspace, num_users=10, files_per_user=20)

        def find_latest():
            finder = ThreeDELatestFinder()
            return finder.find_latest_threede_scene(str(workspace))

        return measure_performance("ThreeDELatestFinder.find_latest", find_latest)


def test_threede_find_all_performance() -> dict[str, float]:
    """Test ThreeDELatestFinder.find_all performance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        create_test_workspace(workspace, num_users=10, files_per_user=20)

        def find_all():
            return ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

        return measure_performance("ThreeDELatestFinder.find_all", find_all)


def test_targeted_finder_performance() -> dict[str, float]:
    """Test TargetedShotsFinder performance with mocked subprocess."""
    # Mock the subprocess calls for consistent performance testing

    def find_targeted():
        with patch("targeted_shot_finder.subprocess.run") as mock_run:
            # Mock find command output
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "\n".join(
                [
                    f"/test/shows/show{i}/shots/seq{j:02d}/seq{j:02d}_{k:04d}/user/testuser"
                    for i in range(3)
                    for j in range(5)
                    for k in range(10)
                ]
            )
            mock_run.return_value = mock_result

            finder = TargetedShotsFinder(username="testuser")

            # Create mock active shots
            active_shots = [
                Shot(
                    show=f"show{i}",
                    sequence=f"seq{j:02d}",
                    shot=f"{k:04d}",
                    workspace_path=f"/test/shows/show{i}/shots/seq{j:02d}/seq{j:02d}_{k:04d}",
                )
                for i in range(3)
                for j in range(2)
                for k in range(5)
            ]

            # Extract shows and find shots
            shows = finder.extract_shows_from_active_shots(active_shots)

            with tempfile.TemporaryDirectory() as tmpdir:
                shows_root = Path(tmpdir) / "shows"
                for show in shows:
                    (shows_root / show / "shots").mkdir(parents=True)

                return list(finder.find_user_shots_in_shows(shows, shows_root))

    return measure_performance(
        "TargetedShotsFinder.find_targeted", find_targeted, iterations=5
    )


def main() -> None:
    """Run all performance tests and display results."""
    print("=" * 70)
    print("PERFORMANCE BASELINE ESTABLISHMENT")
    print("=" * 70)
    print()

    # Run all tests
    results = []

    print("Testing MayaLatestFinder...")
    results.append(test_maya_finder_performance())
    results.append(test_maya_find_all_performance())

    print("Testing ThreeDELatestFinder...")
    results.append(test_threede_finder_performance())
    results.append(test_threede_find_all_performance())

    print("Testing TargetedShotsFinder...")
    results.append(test_targeted_finder_performance())

    print()
    print("=" * 70)
    print("PERFORMANCE BASELINES")
    print("=" * 70)
    print()

    # Display results in a table
    print(f"{'Test Name':<40} {'Avg (ms)':>10} {'Min (ms)':>10} {'Max (ms)':>10}")
    print("-" * 70)

    for result in results:
        print(
            f"{result['name']:<40} "
            f"{result['avg_ms']:>10.2f} "
            f"{result['min_ms']:>10.2f} "
            f"{result['max_ms']:>10.2f}"
        )

    print()
    print("BASELINE TARGETS:")
    print("-" * 70)

    # Define performance targets
    targets = {
        "MayaLatestFinder.find_latest": 50.0,  # 50ms for finding latest
        "MayaLatestFinder.find_all": 100.0,  # 100ms for finding all
        "ThreeDELatestFinder.find_latest": 75.0,  # 75ms (more complex structure)
        "ThreeDELatestFinder.find_all": 150.0,  # 150ms for all 3DE files
        "TargetedShotsFinder.find_targeted": 200.0,  # 200ms with subprocess
    }

    print(f"{'Test Name':<40} {'Target (ms)':>12} {'Actual (ms)':>12} {'Status':>10}")
    print("-" * 70)

    all_pass = True
    for result in results:
        name = result["name"]
        target = targets.get(name, 100.0)
        actual = result["avg_ms"]
        status = "✓ PASS" if actual <= target else "✗ FAIL"

        if actual > target:
            all_pass = False

        print(f"{name:<40} {target:>12.2f} {actual:>12.2f} {status:>10}")

    print()
    if all_pass:
        print("✓ All performance tests passed baseline targets!")
    else:
        print("✗ Some tests exceeded baseline targets. Consider optimization.")

    print()
    print("NOTE: These baselines are for reference. Actual performance")
    print("depends on filesystem, hardware, and system load.")


if __name__ == "__main__":
    main()
