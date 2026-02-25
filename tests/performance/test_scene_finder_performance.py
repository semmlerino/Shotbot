"""Performance benchmarks for ThreeDESceneFinder.

Tests with meaningful time budgets (assert elapsed < X) live here.
Exploratory profiling and traversal-strategy comparisons were removed
as they benchmark implementation choices, not enforce correctness budgets.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from threede_scene_finder import (
    OptimizedThreeDESceneFinder as ThreeDESceneFinder,
)


pytestmark = pytest.mark.performance


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

                user_dir = shot_dir / "user"

                for user_num in range(1, 4):  # 3 users per shot
                    user_name = f"artist{user_num}"
                    user_path = user_dir / user_name
                    user_path.mkdir(parents=True, exist_ok=True)
                    stats["users"] += 1
                    stats["directories"] += 1

                    for plate in ["bg01", "fg01"]:
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
                        stats["directories"] += 6

                        threede_file = (
                            threede_dir
                            / f"{show_path.parent.name}_{seq_name}_{shot_num:04d}_{plate}.3de"
                        )
                        threede_file.write_text(
                            f"# 3DE Scene File\nproject_name: {show_path.parent.name}"
                        )
                        stats["files"] += 1

        return shows_root, stats


@pytest.fixture
def small_project(tmp_path):
    """Create small VFX project for testing."""
    return VFXProjectGenerator.create_small_project(tmp_path)


class TestSceneFinderBudgets:
    """Performance tests that enforce time budgets."""

    def test_find_scenes_for_shot_within_budget(self, small_project) -> None:
        """find_scenes_for_shot completes within 2 seconds on a small project."""
        shows_root, _stats = small_project

        test_shot_path = (
            shows_root / "small_project" / "shots" / "seq01" / "seq01_0010"
        )

        start = time.perf_counter()
        ThreeDESceneFinder.find_scenes_for_shot(
            shot_workspace_path=str(test_shot_path),
            show="small_project",
            sequence="seq01",
            shot="seq01_0010",
            excluded_users=set(),
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"find_scenes_for_shot too slow: {elapsed:.3f}s > 2.0s"

    def test_find_all_3de_files_within_budget(self, small_project) -> None:
        """find_all_3de_files_in_show completes within 5 seconds on a small project."""
        shows_root, _stats = small_project

        start = time.perf_counter()
        ThreeDESceneFinder.find_all_3de_files_in_show(
            str(shows_root), "small_project"
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"find_all_3de_files_in_show too slow: {elapsed:.3f}s > 5.0s"
