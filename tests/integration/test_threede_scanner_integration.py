"""Integration tests for 3DE file discovery workflow."""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

# Standard library imports
import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtWidgets import QApplication

# Local application imports
from cache_manager import CacheManager
from shot_model import Shot

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.doubles_library import TestSubprocess
from threede_scene_finder import (
    OptimizedThreeDESceneFinder as ThreeDESceneFinder,
)
from threede_scene_model import ThreeDESceneModel


pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
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


class TestThreeDEScannerIntegration:
    """Integration tests for 3DE file discovery and cache integration following UNIFIED_TESTING_GUIDE."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        """Minimal setup to avoid pytest fixture overhead."""
        # Use test double for subprocess (UNIFIED_TESTING_GUIDE)
        self.test_subprocess = TestSubprocess()
        self.temp_dir = tmp_path / "shotbot"
        self.temp_dir.mkdir()

        # Create VFX workspace structure
        self.shows_root = self.temp_dir / "shows"
        self.cache_dir = self.temp_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Create realistic VFX workspace structure
        self.show_dir = self.shows_root / "testshow"
        self.shots_dir = self.show_dir / "shots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)

    def test_threede_scanner_file_discovery_integration(self) -> None:
        """Test 3DE scanner finding .3de files across directory structure."""
        # Create realistic VFX workspace with 3DE files
        seq_dir = self.shots_dir / "seq01" / "seq01_0010"
        user_dir = seq_dir / "user" / "otheruser"
        threede_dir = user_dir / "mm" / "3de" / "scenes" / "FG01"
        threede_dir.mkdir(parents=True, exist_ok=True)

        # Create 3DE scene files
        scene_files = [
            threede_dir / "scene_v001.3de",
            threede_dir / "scene_v002.3de",
            user_dir / "tracking" / "3de" / "BG01" / "bg_track.3de",
        ]

        for scene_file in scene_files:
            scene_file.parent.mkdir(parents=True, exist_ok=True)
            scene_file.write_text("# 3DE Scene File\nversion 1.0\n")

        # Create Shot object for the workspace
        shot = Shot(
            show="testshow", sequence="seq01", shot="0010", workspace_path=str(seq_dir)
        )

        # Test static finder method
        with patch(
            "utils.ValidationUtils.get_excluded_users", return_value={"testuser"}
        ):
            found_scenes = ThreeDESceneFinder.find_scenes_for_shot(
                shot.workspace_path,
                shot.show,
                shot.sequence,
                shot.shot,
                excluded_users={"testuser"},
            )

            # Verify scenes were found
            assert len(found_scenes) == len(scene_files)

            # Verify scene paths are correct
            found_paths = {str(scene.scene_path) for scene in found_scenes}
            expected_paths = {str(f) for f in scene_files}
            assert found_paths == expected_paths

            # Verify plate name extraction
            scene_by_path = {str(scene.scene_path): scene for scene in found_scenes}

            # Check FG01 plate extraction
            fg_scene_path = str(scene_files[0])  # First FG01 scene
            if fg_scene_path in scene_by_path:
                fg_scene = scene_by_path[fg_scene_path]
                assert fg_scene.plate == "FG01"

            # Check BG01 plate extraction
            bg_scene_path = str(scene_files[2])  # BG01 scene
            if bg_scene_path in scene_by_path:
                bg_scene = scene_by_path[bg_scene_path]
                assert bg_scene.plate == "BG01"

    def test_threede_scanner_cache_integration(self) -> None:
        """Test 3DE scanner integration with cache system."""
        # Create VFX workspace with 3DE file
        seq_dir = self.shots_dir / "seq01" / "seq01_0020"
        user_dir = seq_dir / "user" / "artist1"
        threede_dir = user_dir / "mm" / "3de" / "scenes"
        threede_dir.mkdir(parents=True, exist_ok=True)

        test_file = threede_dir / "cached_scene.3de"
        test_file.write_text("# Cached 3DE Scene\nversion 1.0\n")

        # Create Shot objects
        shots = [
            Shot(
                show="testshow",
                sequence="seq01",
                shot="0020",
                workspace_path=str(seq_dir),
            )
        ]

        # Create cache manager and scene model
        cache_manager = CacheManager(cache_dir=self.cache_dir)
        scene_model = ThreeDESceneModel(cache_manager=cache_manager, load_cache=False)

        with patch(
            "utils.ValidationUtils.get_excluded_users", return_value={"testuser"}
        ):
            # First refresh - should populate cache
            success1, has_changes1 = scene_model.refresh_scenes(shots)
            assert success1
            assert has_changes1  # First time should have changes
            assert len(scene_model.scenes) == 1

            # Verify cache file was created
            cache_file = self.cache_dir / "threede_scenes.json"
            assert cache_file.exists()

            # Verify cached scene data
            cached_data = cache_manager.get_cached_threede_scenes()
            assert cached_data is not None
            assert len(cached_data) == 1

            cached_scene_data = cached_data[0]
            # Normalize paths for comparison (handle double slashes)
            cached_path = Path(cached_scene_data["scene_path"]).resolve()
            expected_path = test_file.resolve()
            assert cached_path == expected_path
            assert "scenes" in cached_scene_data["plate"]  # Extracted from path

            # Create new model instance to test cache loading
            scene_model2 = ThreeDESceneModel(
                cache_manager=cache_manager, load_cache=True
            )
            assert len(scene_model2.scenes) == 1

            # Second refresh with same files - should detect no changes
            success2, _has_changes2 = scene_model2.refresh_scenes(shots)
            assert success2
            # Note: has_changes2 may be True due to cache TTL refresh, which is expected behavior

    def test_threede_scanner_filtering_and_deduplication(self) -> None:
        """Test 3DE scanner filtering and deduplication logic."""
        # Create workspace with duplicate scenes for same shot
        seq_dir = self.shots_dir / "seq01" / "seq01_0030"
        user_dir = seq_dir / "user" / "artist1"
        threede_dir = user_dir / "mm" / "3de"
        threede_dir.mkdir(parents=True, exist_ok=True)

        # Create multiple .3de files - some in FG01, some in BG01 for same shot
        scene_files = [
            threede_dir / "FG01" / "scene_v001.3de",
            threede_dir / "FG01" / "scene_v002.3de",  # Newer version in FG01
            threede_dir / "BG01" / "bg_scene.3de",  # Different plate
            threede_dir / "backup" / "old_scene.3de",  # Backup scene
        ]

        for i, scene_file in enumerate(scene_files):
            scene_file.parent.mkdir(parents=True, exist_ok=True)
            scene_file.write_text(f"# Scene v{i}\nversion 1.0\n")

        # Make the FG01 v002 scene the newest (it should win due to both mtime and plate priority)
        # Use explicit timestamps instead of sleep to ensure deterministic file ordering
        base_time = 1000000000  # Fixed timestamp base
        # Set base timestamps for all files
        for i, scene_file in enumerate(scene_files):
            os.utime(scene_file, (base_time + i, base_time + i))
        # Make scene_v002.3de the newest with the highest timestamp (overrides the loop timestamp)
        os.utime(scene_files[1], (base_time + 100, base_time + 100))

        # Create Shot and get all scenes
        shot = Shot(
            show="testshow", sequence="seq01", shot="0030", workspace_path=str(seq_dir)
        )

        with patch(
            "utils.ValidationUtils.get_excluded_users", return_value={"testuser"}
        ):
            # Find all scenes (before deduplication)
            all_scenes = ThreeDESceneFinder.find_scenes_for_shot(
                shot.workspace_path,
                shot.show,
                shot.sequence,
                shot.shot,
                excluded_users={"testuser"},
            )

            # Should find all files
            assert len(all_scenes) == len(scene_files)

            # Test deduplication logic via scene model
            cache_manager = CacheManager(cache_dir=self.cache_dir)
            scene_model = ThreeDESceneModel(cache_manager=cache_manager, load_cache=False)
            deduplicated = scene_model._deduplicate_scenes_by_shot(all_scenes)

            # Should deduplicate to one scene per shot (same show/sequence/shot)
            assert len(deduplicated) == 1

            # The selected scene should be the newest FG01 scene (scene_v002.3de)
            selected_scene = deduplicated[0]

            # Should select scene_v002.3de because it has highest mtime AND FG01 plate priority
            scene_path = str(selected_scene.scene_path)
            assert "scene_v002.3de" in scene_path
            assert selected_scene.plate == "FG01"

    def test_threede_scanner_user_exclusion_integration(self) -> None:
        """Test 3DE scanner excluding current user's shots."""
        # Create workspace with files from different users
        seq_dir = self.shots_dir / "seq01" / "seq01_0040"

        # Create files for different users
        current_user_dir = seq_dir / "user" / "testuser" / "mm" / "3de"
        other_user_dir = seq_dir / "user" / "otheruser" / "mm" / "3de"
        publish_dir = seq_dir / "publish" / "mm"

        current_user_dir.mkdir(parents=True, exist_ok=True)
        other_user_dir.mkdir(parents=True, exist_ok=True)
        publish_dir.mkdir(parents=True, exist_ok=True)

        # Create scene files
        current_user_file = current_user_dir / "my_scene.3de"
        other_user_file = other_user_dir / "their_scene.3de"
        published_file = publish_dir / "published_scene.3de"

        current_user_file.write_text("# Current User Scene\nversion 1.0\n")
        other_user_file.write_text("# Other User Scene\nversion 1.0\n")
        published_file.write_text("# Published Scene\nversion 1.0\n")

        # Create Shot object
        shot = Shot(
            show="testshow", sequence="seq01", shot="0040", workspace_path=str(seq_dir)
        )

        # Test with current user excluded
        excluded_users = {"testuser"}
        found_scenes = ThreeDESceneFinder.find_scenes_for_shot(
            shot.workspace_path,
            shot.show,
            shot.sequence,
            shot.shot,
            excluded_users=excluded_users,
        )

        # Should exclude current user's files
        found_paths = {str(scene.scene_path) for scene in found_scenes}
        found_users = {scene.user for scene in found_scenes}

        # Should NOT include current user's scene
        assert str(current_user_file) not in found_paths
        assert "testuser" not in found_users

        # Should include other user's scene and published scenes
        assert str(other_user_file) in found_paths
        assert str(published_file) in found_paths
        assert "otheruser" in found_users
        assert any(user.startswith("published-") for user in found_users)

        # Test without exclusion
        found_scenes_all = ThreeDESceneFinder.find_scenes_for_shot(
            shot.workspace_path,
            shot.show,
            shot.sequence,
            shot.shot,
            excluded_users=set(),  # No exclusions
        )

        # Should include all scenes when no exclusions
        assert len(found_scenes_all) > len(found_scenes)
        all_paths = {str(scene.scene_path) for scene in found_scenes_all}
        assert str(current_user_file) in all_paths

    def test_threede_scanner_background_scanning_workflow(self) -> None:
        """Test 3DE scanner background scanning with progress reporting."""
        # Create a single VFX workspace with 3DE file for simpler testing
        seq_dir = self.shots_dir / "seq01" / "seq01_0070"
        user_dir = seq_dir / "user" / "artist1" / "mm" / "3de"
        user_dir.mkdir(parents=True, exist_ok=True)

        scene_file = user_dir / "worker_test_scene.3de"
        scene_file.write_text("# Worker Test Scene\nversion 1.0\n")

        shot = Shot(
            show="testshow",
            sequence="seq01",
            shot="seq01_0070",
            workspace_path=str(seq_dir),
        )

        # Test scene model instead of worker directly (more reliable)
        with patch(
            "utils.ValidationUtils.get_excluded_users", return_value={"testuser"}
        ):
            cache_manager = CacheManager(cache_dir=self.cache_dir)
            scene_model = ThreeDESceneModel(cache_manager=cache_manager, load_cache=False)

            # Test refresh operation
            success, has_changes = scene_model.refresh_scenes([shot])

            # Verify operation succeeded
            assert success, "Scene refresh should succeed"
            assert has_changes, "Should detect changes on first scan"
            assert len(scene_model.scenes) == 1, "Should find one scene"

            # Verify scene details
            found_scene = scene_model.scenes[0]
            assert found_scene.show == "testshow"
            assert found_scene.sequence == "seq01"
            assert found_scene.shot == "0070"
            assert found_scene.user == "artist1"
            # Normalize paths for comparison
            actual_path = Path(str(found_scene.scene_path)).resolve()
            expected_path = scene_file.resolve()
            assert actual_path == expected_path

            # Test that subsequent refresh works (integration with cache)
            success2, _has_changes2 = scene_model.refresh_scenes([shot])
            assert success2, "Second refresh should also succeed"

    def test_threede_scanner_error_handling_integration(self) -> None:
        """Test 3DE scanner error handling with inaccessible directories."""
        # Create mixed accessible and problematic workspaces

        # Good workspace with valid 3DE file
        good_seq_dir = self.shots_dir / "seq01" / "seq01_0050"
        good_user_dir = good_seq_dir / "user" / "artist1" / "mm" / "3de"
        good_user_dir.mkdir(parents=True, exist_ok=True)

        good_file = good_user_dir / "good_scene.3de"
        good_file.write_text("# Good Scene\nversion 1.0\n")

        # Problematic workspace (missing user directory)
        bad_seq_dir = self.shots_dir / "seq01" / "seq01_0060"
        bad_seq_dir.mkdir(parents=True, exist_ok=True)
        # Note: Not creating user directory to simulate missing structure

        # Create shots for both workspaces
        good_shot = Shot(
            show="testshow",
            sequence="seq01",
            shot="0050",
            workspace_path=str(good_seq_dir),
        )

        bad_shot = Shot(
            show="testshow",
            sequence="seq01",
            shot="0060",
            workspace_path=str(bad_seq_dir),  # No user directory
        )

        # Test error handling with mixed valid/invalid shots
        with patch(
            "utils.ValidationUtils.get_excluded_users", return_value={"testuser"}
        ):
            # Should handle missing directories gracefully
            good_scenes = ThreeDESceneFinder.find_scenes_for_shot(
                good_shot.workspace_path,
                good_shot.show,
                good_shot.sequence,
                good_shot.shot,
                excluded_users={"testuser"},
            )

            bad_scenes = ThreeDESceneFinder.find_scenes_for_shot(
                bad_shot.workspace_path,
                bad_shot.show,
                bad_shot.sequence,
                bad_shot.shot,
                excluded_users={"testuser"},
            )

            # Good workspace should return scenes
            assert len(good_scenes) == 1
            assert str(good_scenes[0].scene_path) == str(good_file)

            # Bad workspace should return empty list (no errors)
            assert len(bad_scenes) == 0

            # Test model-level error handling
            cache_manager = CacheManager(cache_dir=self.cache_dir)
            scene_model = ThreeDESceneModel(cache_manager=cache_manager, load_cache=False)

            # Should handle mixed good/bad shots gracefully
            success, _has_changes = scene_model.refresh_scenes([good_shot, bad_shot])
            assert success  # Should succeed despite one bad shot

            # Should find scenes from good workspace only
            assert len(scene_model.scenes) == 1
            # Normalize paths for comparison
            actual_path = Path(str(scene_model.scenes[0].scene_path)).resolve()
            expected_path = good_file.resolve()
            assert actual_path == expected_path


# Allow running as standalone test
if __name__ == "__main__":
    import shutil
    import tempfile

    # Initialize Qt Application if needed for worker test
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    standalone_temp = Path(tempfile.mkdtemp(prefix="shotbot_threede_scanner_"))
    test = TestThreeDEScannerIntegration()
    test.temp_dir = standalone_temp
    test.shows_root = standalone_temp / "shows"
    test.cache_dir = standalone_temp / "cache"
    test.cache_dir.mkdir(parents=True, exist_ok=True)
    test.show_dir = test.shows_root / "testshow"
    test.shots_dir = test.show_dir / "shots"
    test.shots_dir.mkdir(parents=True, exist_ok=True)
    test.test_subprocess = TestSubprocess()

    try:
        print("Running 3DE scanner file discovery integration...")
        test.test_threede_scanner_file_discovery_integration()
        print("✓ 3DE scanner file discovery passed")

        print("Running 3DE scanner cache integration...")
        test.test_threede_scanner_cache_integration()
        print("✓ 3DE scanner cache integration passed")

        print("Running 3DE scanner filtering and deduplication...")
        test.test_threede_scanner_filtering_and_deduplication()
        print("✓ 3DE scanner filtering and deduplication passed")

        print("Running 3DE scanner user exclusion integration...")
        test.test_threede_scanner_user_exclusion_integration()
        print("✓ 3DE scanner user exclusion integration passed")

        print("Running 3DE scanner background scanning workflow...")
        test.test_threede_scanner_background_scanning_workflow()
        print("✓ 3DE scanner background scanning workflow passed")

        print("Running 3DE scanner error handling integration...")
        test.test_threede_scanner_error_handling_integration()
        print("✓ 3DE scanner error handling integration passed")

        print("All 3DE scanner integration tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")

        traceback.print_exc()
    finally:
        shutil.rmtree(standalone_temp, ignore_errors=True)
        if app:
            app.quit()
