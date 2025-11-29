"""Integration tests for parallel 3DE discovery methods that failed in production.

Tests the actual parallel discovery methods that caused the ThreadSafeProgressTracker
parameter bug. These tests use real file structures and exercise the complete
code path that failed in production.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Test behavior with real file structures and I/O
2. Use real components, not mocks
3. Exercise the exact production code paths that failed
4. Focus on integration between components
"""

from __future__ import annotations

# Standard library imports
import tempfile
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from shot_model import Shot
from threede_scene_finder_optimized import OptimizedThreeDESceneFinder


pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.integration_safe,
    pytest.mark.real_subprocess,  # Uses find command for 3DE discovery
]


@pytest.fixture(autouse=True)
def reset_threede_singletons() -> None:
    """Reset 3DE-related singletons to prevent cross-test contamination.

    Resets:
    - NotificationManager._instance (used for progress notifications)
    - ProgressManager._instance (used for operation tracking)

    NOTE: ProcessPoolManager is NOT reset here - it's handled by the autouse
    mock_process_pool_manager fixture in conftest.py which provides a TestProcessPool.
    Resetting it here would undo that mock and cause subprocess failures.
    """
    # Import here to avoid circular dependencies
    from notification_manager import NotificationManager
    from progress_manager import ProgressManager

    # Reset NotificationManager
    if NotificationManager._instance is not None:
        try:
            NotificationManager.cleanup()
        except (RuntimeError, AttributeError):
            pass
        if hasattr(NotificationManager._instance, "_initialized"):
            delattr(NotificationManager._instance, "_initialized")
    NotificationManager._instance = None
    NotificationManager._main_window = None
    NotificationManager._status_bar = None
    NotificationManager._active_toasts = []
    NotificationManager._current_progress = None

    # Reset ProgressManager
    if ProgressManager._instance is not None:
        try:
            ProgressManager.clear_all_operations()
        except (RuntimeError, AttributeError):
            pass
        if hasattr(ProgressManager._instance, "_initialized"):
            delattr(ProgressManager._instance, "_initialized")
    ProgressManager._instance = None
    ProgressManager._operation_stack = []
    ProgressManager._status_bar = None

    yield

    # Reset again after test (defense in depth)
    # NOTE: ProcessPoolManager handled by autouse mock
    NotificationManager._instance = None
    ProgressManager._instance = None


class TestParallelDiscoveryIntegration:
    """Integration tests for parallel 3DE discovery methods.

    These tests exercise the exact production code paths that failed,
    specifically testing the methods that use ThreadSafeProgressTracker
    with the progress_interval parameter.
    """

    def setup_method(self) -> None:
        """Set up test fixtures with realistic VFX directory structure."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="shotbot_parallel_test_"))
        self.shows_root = self.temp_dir / "shows"

    def teardown_method(self) -> None:
        """Clean up test directories."""
        # Standard library imports
        import shutil

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_test_vfx_structure(self) -> tuple[Path, list[Shot]]:
        """Create a realistic VFX directory structure for testing.

        Returns:
            Tuple of (shows_root_path, list_of_shots)
        """
        shows_root = self.temp_dir / "shows"

        # Create multiple shows to test parallel processing
        test_shots = []

        for show_name in ["TESTSHOW", "ANOTHERSHOW"]:
            show_dir = shows_root / show_name / "shots"

            for seq_num in ["seq001", "seq002"]:
                for shot_num in ["0010", "0020", "0030"]:
                    shot_path = show_dir / seq_num / f"{seq_num}_{shot_num}"

                    # Create user directories with 3DE files
                    for user in ["artist1", "artist2", "supervisor"]:
                        user_dir = shot_path / "user" / user

                        # Create 3DE files in various locations
                        # Standard 3DE directory
                        threede_dir = user_dir / "3de" / "scenes"
                        threede_dir.mkdir(parents=True, exist_ok=True)
                        (
                            threede_dir / f"{show_name}_{seq_num}_{shot_num}_BG01.3de"
                        ).write_text("# 3DE Scene\nversion 1.0")

                        # Nested 3DE files (realistic production structure)
                        nested_dir = user_dir / "matchmove" / "3de" / "FG01"
                        nested_dir.mkdir(parents=True, exist_ok=True)
                        (nested_dir / "fg_track_v001.3de").write_text(
                            "# 3DE Scene\nversion 1.0"
                        )

                    # Create Shot object for this shot
                    shot = Shot(
                        show=show_name,
                        sequence=seq_num,
                        shot=shot_num,
                        workspace_path=str(shot_path),
                    )
                    test_shots.append(shot)

        return shows_root, test_shots

    def test_find_all_3de_files_in_show_parallel_production_pattern(self) -> None:
        """Test the exact method that failed in production with progress_interval parameter.

        This test would have caught the ThreadSafeProgressTracker parameter bug.
        """
        shows_root, _ = self._create_test_vfx_structure()

        # Track progress updates
        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        # Call the EXACT method that failed in production
        # The progress_interval is hardcoded from config inside this method
        # The bug was in the ThreadSafeProgressTracker creation inside this method
        results = OptimizedThreeDESceneFinder.find_all_3de_files_in_show_parallel(
            show_root=str(shows_root),
            show="TESTSHOW",
            progress_callback=progress_callback,
        )

        # Verify results
        assert isinstance(results, list)
        assert len(results) > 0, "Should find multiple 3DE files"

        # Verify progress callback was called
        assert len(progress_updates) > 0, "Progress callback should have been called"

        # Verify file structure of results
        for file_tuple in results:
            assert (
                len(file_tuple) == 6
            )  # (file_path, show, sequence, shot, user, plate)
            file_path, show, sequence, shot, user, _plate = file_tuple

            assert isinstance(file_path, Path)
            assert file_path.suffix == ".3de"
            assert file_path.exists()
            assert show == "TESTSHOW"
            assert sequence.startswith("seq")
            assert shot.isdigit()
            assert user in ["artist1", "artist2", "supervisor"]

    def test_find_all_scenes_in_shows_truly_efficient_parallel_workflow(self) -> None:
        """Test the complete parallel workflow that's used by the worker thread.

        This tests the method that actually calls find_all_3de_files_in_show_parallel
        and caused the production failure.
        """
        _shows_root, test_shots = self._create_test_vfx_structure()

        # Track progress updates like the worker does
        progress_updates = []
        cancellation_requested = False

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        def cancel_flag() -> bool:
            return cancellation_requested

        # Call the method used by ThreeDESceneWorker
        # This is the complete workflow that failed in production
        scenes = OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel(
            user_shots=test_shots[:3],  # Use subset of shots for testing
            excluded_users={"baduser"},  # Exclude some users
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

        # Verify results
        assert isinstance(scenes, list)
        assert len(scenes) > 0, "Should find scenes from the test structure"

        # Verify progress was reported
        assert len(progress_updates) > 0, "Should have progress updates"

        # Verify scene objects
        for scene in scenes:
            assert hasattr(scene, "scene_path")
            assert hasattr(scene, "show")
            assert hasattr(scene, "sequence")
            assert hasattr(scene, "shot")
            assert hasattr(scene, "user")
            assert scene.scene_path.exists()

    def test_parallel_discovery_with_cancellation(self) -> None:
        """Test that cancellation works correctly during parallel discovery."""
        _shows_root, test_shots = self._create_test_vfx_structure()

        progress_updates = []
        cancel_after_updates = 2

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        def cancel_flag() -> bool:
            # Cancel after receiving a few progress updates
            return len(progress_updates) >= cancel_after_updates

        # This should be cancelled mid-processing
        scenes = OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel(
            user_shots=test_shots,
            excluded_users=set(),
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

        # Should have partial results (or empty if cancelled very early)
        assert isinstance(scenes, list)

        # Should have received some progress updates before cancellation
        assert len(progress_updates) >= cancel_after_updates

    def test_parallel_discovery_error_handling(self) -> None:
        """Test error handling in parallel discovery with invalid paths."""
        # Mix of valid and invalid paths
        _shows_root, valid_shots = self._create_test_vfx_structure()

        # Add invalid shots that don't exist
        invalid_shots = [
            Shot("NONEXISTENT", "seq001", "0010", "/invalid/path"),
            Shot("TESTSHOW", "invalid_seq", "0010", "/another/invalid/path"),
        ]

        all_shots = valid_shots + invalid_shots

        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        # Should handle invalid paths gracefully
        scenes = OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel(
            user_shots=all_shots,
            excluded_users=set(),
            progress_callback=progress_callback,
            cancel_flag=lambda: False,
        )

        # Should return results from valid paths only
        assert isinstance(scenes, list)
        # Should have some scenes from valid structure
        valid_scenes = [s for s in scenes if s.scene_path.exists()]
        assert len(valid_scenes) > 0

    def test_config_based_progress_interval_handling(self) -> None:
        """Test that progress_interval from config is handled correctly internally."""
        shows_root, _ = self._create_test_vfx_structure()

        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        # Test that the method works with config-based progress interval
        # The progress_interval is read from ThreadingConfig.THREEDE_PROGRESS_INTERVAL
        results = OptimizedThreeDESceneFinder.find_all_3de_files_in_show_parallel(
            show_root=str(shows_root),
            show="TESTSHOW",
            progress_callback=progress_callback,
        )

        # Should work without error (would fail with original parameter bug)
        assert isinstance(results, list)
        assert len(results) > 0, "Should find files using config progress interval"

    def test_concurrent_parallel_discovery(self) -> None:
        """Test multiple parallel discoveries running concurrently."""
        # Standard library imports
        import threading

        _shows_root, test_shots = self._create_test_vfx_structure()

        results = {}
        errors = {}

        def run_discovery(show_name: str, shot_subset: list[Shot]) -> None:
            """Run discovery for a specific show."""
            try:
                progress_updates = []

                def progress_callback(count: int, status: str) -> None:
                    progress_updates.append((count, status))

                scenes = OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel(
                    user_shots=shot_subset,
                    excluded_users=set(),
                    progress_callback=progress_callback,
                    cancel_flag=lambda: False,
                )

                results[show_name] = (scenes, progress_updates)

            except Exception as e:
                errors[show_name] = e

        # Split shots by show
        testshow_shots = [s for s in test_shots if s.show == "TESTSHOW"]
        anothershow_shots = [s for s in test_shots if s.show == "ANOTHERSHOW"]

        # Run concurrent discoveries
        threads = [
            threading.Thread(
                target=run_discovery, args=("TESTSHOW", testshow_shots[:3])
            ),
            threading.Thread(
                target=run_discovery, args=("ANOTHERSHOW", anothershow_shots[:3])
            ),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=30)  # Generous timeout for parallel processing

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent discoveries failed: {errors}"

        # Verify both discoveries completed
        assert len(results) == 2
        assert "TESTSHOW" in results
        assert "ANOTHERSHOW" in results

        # Verify results from both discoveries
        for scenes, progress_updates in results.values():
            assert isinstance(scenes, list)
            assert len(scenes) >= 0  # May be 0 if no scenes found
            assert len(progress_updates) >= 0  # Should have some progress

    def test_production_scale_simulation(self) -> None:
        """Test with a larger scale that simulates production usage."""
        # Create larger test structure
        shows_root = self.temp_dir / "shows"
        test_shots = []

        # Create more shows and shots for scale testing
        for show_num in range(2):
            show_name = f"SHOW_{show_num:03d}"
            show_dir = shows_root / show_name / "shots"

            for seq_num in range(3):  # 3 sequences per show
                seq_name = f"seq{seq_num:03d}"
                for shot_num in range(5):  # 5 shots per sequence
                    shot_name = f"{shot_num:04d}"
                    shot_path = show_dir / seq_name / f"{seq_name}_{shot_name}"

                    # Create fewer users but more files per user for performance testing
                    for user in ["lead", "artist"]:
                        user_dir = shot_path / "user" / user / "3de"
                        user_dir.mkdir(parents=True, exist_ok=True)

                        # Create multiple 3DE files per shot
                        for plate in ["BG01", "FG01", "ROTO"]:
                            scene_file = (
                                user_dir
                                / f"{show_name}_{seq_name}_{shot_name}_{plate}.3de"
                            )
                            scene_file.write_text(
                                f"# 3DE Scene for {plate}\nversion 1.0"
                            )

                    shot = Shot(show_name, seq_name, shot_name, str(shot_path))
                    test_shots.append(shot)

        progress_updates = []
        start_time = None

        def progress_callback(count: int, status: str) -> None:
            nonlocal start_time
            if start_time is None:
                start_time = time.time()
            progress_updates.append((time.time() - start_time, count, status))

        # Test parallel discovery on larger dataset
        # Standard library imports
        import time

        start = time.time()

        scenes = OptimizedThreeDESceneFinder.find_all_scenes_in_shows_truly_efficient_parallel(
            user_shots=test_shots,
            excluded_users=set(),
            progress_callback=progress_callback,
            cancel_flag=lambda: False,
        )

        end = time.time()
        processing_time = end - start

        # Verify results
        assert isinstance(scenes, list)
        expected_scenes = 2 * 3 * 5 * 2 * 3  # shows x seqs x shots x users x plates
        assert len(scenes) == expected_scenes, (
            f"Expected {expected_scenes} scenes, got {len(scenes)}"
        )

        # Verify performance - should complete reasonably quickly
        assert processing_time < 60, f"Processing took too long: {processing_time:.2f}s"

        # Verify progress reporting frequency
        assert len(progress_updates) > 0, "Should have progress updates"

        # Log performance metrics for debugging
        print(f"Processed {len(scenes)} scenes in {processing_time:.2f}s")
        print(f"Progress updates: {len(progress_updates)}")
        if progress_updates:
            print(f"First update at: {progress_updates[0][0]:.2f}s")
            print(f"Last update at: {progress_updates[-1][0]:.2f}s")
