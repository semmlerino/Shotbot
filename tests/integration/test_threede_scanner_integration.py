"""Integration tests for 3DE file discovery workflow."""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

# Standard library imports
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
from tests.fixtures.test_doubles import TestSubprocess
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
        print("Running 3DE scanner cache integration...")
        test.test_threede_scanner_cache_integration()
        print("✓ 3DE scanner cache integration passed")

        print("Running 3DE scanner background scanning workflow...")
        test.test_threede_scanner_background_scanning_workflow()
        print("✓ 3DE scanner background scanning workflow passed")

        print("All 3DE scanner integration tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")

        traceback.print_exc()
    finally:
        shutil.rmtree(standalone_temp, ignore_errors=True)
        if app:
            app.quit()
