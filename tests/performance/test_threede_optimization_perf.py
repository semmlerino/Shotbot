"""Performance tests extracted from test_threede_optimization_coverage.py.

These tests measure execution time and throughput, so they belong in the
performance suite (excluded from the default test run via norecursedirs).
"""

from __future__ import annotations

import time

import pytest

from threede.scene_discovery_coordinator import (
    SceneDiscoveryCoordinator as OptimizedThreeDESceneFinder,
)


pytestmark = [pytest.mark.performance, pytest.mark.slow]


class TestPerformanceRegression:
    """Test for performance regressions in optimized implementation."""

    def test_performance_baseline(self, tmp_path) -> None:
        """Test that optimized version meets performance baselines."""
        # Create medium-sized test structure
        shot_path = tmp_path / "performance_test"
        user_dir = shot_path / "user"

        # Create realistic structure (10 users, 3 files each)
        for user_i in range(10):
            user_path = user_dir / f"artist{user_i:02d}"

            for plate in ["bg01", "fg01", "comp01"]:
                threede_dir = user_path / "mm" / "3de" / "scenes" / plate.upper()
                threede_dir.mkdir(parents=True)
                (threede_dir / f"scene_{plate}.3de").write_text(f"# Scene {plate}")

        # Performance test
        start_time = time.perf_counter()

        scenes = OptimizedThreeDESceneFinder().find_scenes_for_shot(
            shot_workspace_path=str(shot_path),
            show="perf_show",
            sequence="perf_seq",
            shot="perf_shot",
            excluded_users=set(),
        )

        execution_time = time.perf_counter() - start_time

        # Performance expectations
        assert len(scenes) == 30  # 10 users * 3 files each
        assert execution_time < 0.1, (
            f"Performance regression: {execution_time:.4f}s > 0.1s"
        )

        # Files per second rate
        files_per_second = (
            len(scenes) / execution_time if execution_time > 0 else float("inf")
        )
        assert files_per_second > 300, (
            f"Processing rate too slow: {files_per_second:.1f} files/sec"
        )
