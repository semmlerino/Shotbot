"""Performance tests extracted from test_threede_optimization_coverage.py.

These tests measure execution time and throughput, so they belong in the
performance suite (excluded from the default test run via norecursedirs).
"""

from __future__ import annotations

import time

import pytest

from threede_scene_finder import OptimizedThreeDESceneFinder


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

        scenes = OptimizedThreeDESceneFinder.find_scenes_for_shot(
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


class TestPythonMethodPerformance:
    """Test Python-only file finding method performance."""

    def test_python_method_performance(self, tmp_path) -> None:
        """Test Python-only file finding method."""
        # Create test structure
        user_dir = tmp_path / "user"

        for user in ["artist1", "artist2", "excluded"]:
            user_path = user_dir / user
            threede_dir = user_path / "mm" / "3de" / "scenes"
            threede_dir.mkdir(parents=True)

            # Create multiple .3de files
            (threede_dir / f"{user}_bg01.3de").write_text("# BG scene")
            (threede_dir / f"{user}_fg01.3de").write_text("# FG scene")

        # Test Python method using the refactored FileSystemScanner
        from filesystem_scanner import FileSystemScanner

        scanner = FileSystemScanner()

        excluded_users = {"excluded"}
        file_pairs = scanner.find_3de_files_python_optimized(user_dir, excluded_users)

        # Should find files from artist1 and artist2, not excluded
        assert len(file_pairs) == 4  # 2 users * 2 files each

        users_found = {user for user, _ in file_pairs}
        assert "artist1" in users_found
        assert "artist2" in users_found
        assert "excluded" not in users_found
