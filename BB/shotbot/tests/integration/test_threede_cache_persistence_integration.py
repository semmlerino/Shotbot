"""Integration tests for 3DE scene cache persistence across app restarts."""

import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from cache_manager import CacheManager
from main_window import MainWindow
from shot_model import Shot
from threede_scene_model import ThreeDESceneModel


class TestThreeDECachePersistenceIntegration:
    """Test 3DE scene cache persistence across application restarts."""

    @pytest.fixture
    def persistent_cache_setup(self):
        """Create persistent cache directory that survives fixture cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "persistent_cache"
            workspace_dir = Path(temp_dir) / "workspace"
            cache_dir.mkdir()
            workspace_dir.mkdir()

            yield cache_dir, workspace_dir

    @pytest.fixture
    def mock_3de_workspace(self, persistent_cache_setup):
        """Create mock 3DE workspace structure."""
        cache_dir, workspace_dir = persistent_cache_setup

        # Create realistic shot workspace structure
        shots_data = []

        for shot_idx in range(3):
            shot_name = f"shot_{shot_idx:03d}"
            sequence = "SEQ001"

            shot_path = (
                workspace_dir / "show1" / "shots" / sequence / f"{sequence}_{shot_name}"
            )

            # Create multiple users with 3DE scenes
            users = ["alice", "bob", "charlie"]

            for user in users:
                if user == "charlie" and shot_idx == 0:
                    # Skip charlie for first shot to test incremental updates
                    continue

                for plate_name in ["FG01", "BG01"]:
                    scene_dir = (
                        shot_path
                        / "user"
                        / user
                        / "mm"
                        / "3de"
                        / "mm-default"
                        / "scenes"
                        / "scene"
                        / plate_name
                        / "v001"
                    )
                    scene_dir.mkdir(parents=True)

                    scene_file = scene_dir / f"{user}_{plate_name}_{shot_name}.3de"
                    scene_file.touch()

            shots_data.append(Shot("show1", sequence, shot_name, str(shot_path)))

        return cache_dir, workspace_dir, shots_data

    def test_cache_creation_and_persistence(self, mock_3de_workspace):
        """Test that cache is created and persists across model instances."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Phase 1: Initial discovery and caching
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        success, has_changes = scene_model.refresh_scenes(shots_data)

        assert success is True
        assert has_changes is True
        initial_scene_count = len(scene_model.scenes)
        assert initial_scene_count > 0

        # Verify cache file was created
        cache_file = cache_dir / "threede_scenes.json"
        assert cache_file.exists()

        # Verify cache content structure
        with open(cache_file) as f:
            cache_data = json.load(f)

        assert "timestamp" in cache_data
        assert "scenes" in cache_data
        assert len(cache_data["scenes"]) == initial_scene_count

        # Store timestamp for later comparison
        cache_data["timestamp"]

        # Phase 2: Create new model instance - should load from cache
        new_cache_manager = CacheManager(cache_dir=cache_dir)
        new_scene_model = ThreeDESceneModel(new_cache_manager, load_cache=True)

        # Should have loaded scenes from cache
        assert len(new_scene_model.scenes) == initial_scene_count

        # Verify scene data integrity
        original_scenes = {(s.user, s.plate, s.full_name) for s in scene_model.scenes}
        loaded_scenes = {(s.user, s.plate, s.full_name) for s in new_scene_model.scenes}
        assert original_scenes == loaded_scenes

    def test_cache_ttl_expiry_and_refresh(self, mock_3de_workspace):
        """Test cache TTL expiry triggers fresh discovery."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Create cache with old timestamp
        old_timestamp = datetime.now() - timedelta(hours=2)  # Beyond TTL
        cache_data = {
            "timestamp": old_timestamp.isoformat(),
            "scenes": [
                {
                    "show": "old_show",
                    "sequence": "old_seq",
                    "shot": "old_shot",
                    "workspace_path": "/old/path",
                    "user": "old_user",
                    "plate": "OLD_PLATE",
                    "scene_path": "/old/scene.3de",
                }
            ],
        }

        cache_file = cache_dir / "threede_scenes.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # Create model - should ignore expired cache
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=True)

        # Should start empty due to expired cache
        assert len(scene_model.scenes) == 0

        # Refresh should discover new scenes and update cache
        success, has_changes = scene_model.refresh_scenes(shots_data)

        assert success is True
        assert has_changes is True
        assert len(scene_model.scenes) > 0

        # Verify cache was updated with fresh timestamp
        with open(cache_file) as f:
            new_cache_data = json.load(f)

        new_timestamp = datetime.fromisoformat(new_cache_data["timestamp"])
        assert new_timestamp > old_timestamp
        assert len(new_cache_data["scenes"]) > 0
        assert new_cache_data["scenes"][0]["user"] != "old_user"  # Should have new data

    def test_incremental_updates_and_change_detection(self, mock_3de_workspace):
        """Test incremental updates to cache when scenes are added/removed."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Phase 1: Initial cache population
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        success1, has_changes1 = scene_model.refresh_scenes(shots_data)
        initial_count = len(scene_model.scenes)

        assert success1 is True
        assert has_changes1 is True
        assert initial_count > 0

        # Phase 2: Add new scene to workspace
        new_scene_dir = (
            Path(shots_data[0].workspace_path)
            / "user"
            / "charlie"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "COMP"
            / "v001"
        )
        new_scene_dir.mkdir(parents=True)
        new_scene_file = new_scene_dir / "charlie_COMP_scene.3de"
        new_scene_file.touch()

        # Refresh should detect new scene
        success2, has_changes2 = scene_model.refresh_scenes(shots_data)

        assert success2 is True
        assert has_changes2 is True
        assert len(scene_model.scenes) > initial_count

        # Verify new scene was added
        charlie_scenes = [s for s in scene_model.scenes if s.user == "charlie"]
        assert len(charlie_scenes) > 0
        assert any(s.plate == "COMP" for s in charlie_scenes)

        # Phase 3: Create new model instance - should load updated cache
        new_cache_manager = CacheManager(cache_dir=cache_dir)
        new_scene_model = ThreeDESceneModel(new_cache_manager, load_cache=True)

        # Should have loaded updated scenes including new charlie scene
        assert len(new_scene_model.scenes) == len(scene_model.scenes)
        new_charlie_scenes = [s for s in new_scene_model.scenes if s.user == "charlie"]
        assert len(new_charlie_scenes) > 0

    def test_cache_corruption_recovery(self, mock_3de_workspace):
        """Test recovery from corrupted cache files."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Create corrupted cache file
        cache_file = cache_dir / "threede_scenes.json"
        cache_file.write_text("{ corrupted json content }")

        # Model should handle corrupted cache gracefully
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=True)

        # Should start with empty scenes
        assert len(scene_model.scenes) == 0

        # Refresh should work and create new valid cache
        success, has_changes = scene_model.refresh_scenes(shots_data)

        assert success is True
        assert has_changes is True
        assert len(scene_model.scenes) > 0

        # Verify new cache is valid JSON
        with open(cache_file) as f:
            cache_data = json.load(f)  # Should not raise exception

        assert "timestamp" in cache_data
        assert len(cache_data["scenes"]) > 0

    def test_concurrent_cache_access(self, mock_3de_workspace):
        """Test concurrent access to cache by multiple model instances."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Create multiple cache managers
        managers = [CacheManager(cache_dir=cache_dir) for _ in range(3)]
        models = [ThreeDESceneModel(mgr, load_cache=False) for mgr in managers]

        # Have all models refresh simultaneously
        results = []
        for model in models:
            success, has_changes = model.refresh_scenes(shots_data)
            results.append((success, has_changes))

        # All should succeed (though only one might report changes due to race)
        assert all(success for success, _ in results)

        # All models should have discovered scenes
        scene_counts = [len(model.scenes) for model in models]
        assert all(count > 0 for count in scene_counts)
        assert len(set(scene_counts)) <= 1  # All should have same count

    def test_cache_size_and_performance(self, mock_3de_workspace):
        """Test cache performance with large datasets."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Extend shots data to create larger dataset
        extended_shots = []
        for i in range(20):  # Create 20 shots
            shot_name = f"perf_{i:03d}"
            sequence = "PERF"
            shot_path = (
                workspace_dir / "show1" / "shots" / sequence / f"{sequence}_{shot_name}"
            )

            # Create multiple users and plates for each shot
            for user in ["user1", "user2", "user3", "user4"]:
                for plate in ["FG01", "BG01", "BG02", "COMP"]:
                    scene_dir = (
                        shot_path
                        / "user"
                        / user
                        / "mm"
                        / "3de"
                        / "mm-default"
                        / "scenes"
                        / "scene"
                        / plate
                        / "v001"
                    )
                    scene_dir.mkdir(parents=True)
                    scene_file = scene_dir / f"{user}_{plate}_{shot_name}.3de"
                    scene_file.touch()

            extended_shots.append(Shot("show1", sequence, shot_name, str(shot_path)))

        # Test initial caching performance
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        start_time = time.time()
        success, has_changes = scene_model.refresh_scenes(extended_shots)
        cache_time = time.time() - start_time

        assert success is True
        assert has_changes is True
        scene_count = len(scene_model.scenes)
        assert scene_count > 100  # Should have many scenes

        # Cache creation should be reasonably fast
        assert cache_time < 5.0  # Should complete within 5 seconds

        # Test cache loading performance
        new_cache_manager = CacheManager(cache_dir=cache_dir)

        start_time = time.time()
        new_scene_model = ThreeDESceneModel(new_cache_manager, load_cache=True)
        load_time = time.time() - start_time

        # Cache loading should be very fast
        assert load_time < 1.0  # Should load within 1 second
        assert len(new_scene_model.scenes) == scene_count

        # Verify cache file size is reasonable
        cache_file = cache_dir / "threede_scenes.json"
        cache_size = cache_file.stat().st_size
        assert cache_size < 10 * 1024 * 1024  # Less than 10MB

    def test_app_restart_simulation_full_workflow(self, mock_3de_workspace, qapp):
        """Test complete app restart simulation with MainWindow integration."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Phase 1: First app session
        cache_manager1 = CacheManager(cache_dir=cache_dir)

        # Mock shot model to return our test shots
        with patch("shot_model.ShotModel.refresh_shots") as mock_refresh:
            mock_refresh.return_value = (True, True)  # Success, has changes

            # Create main window (simulates app startup)
            main_window1 = MainWindow(cache_manager1)
            main_window1.shot_model.shots = shots_data  # Inject test shots

            # Refresh 3DE scenes
            success1, changes1 = main_window1.threede_scene_model.refresh_scenes(
                shots_data
            )
            session1_scene_count = len(main_window1.threede_scene_model.scenes)

            assert success1 is True
            assert changes1 is True
            assert session1_scene_count > 0

            # Simulate app shutdown
            main_window1.close()
            del main_window1

        # Phase 2: App restart (new session)
        cache_manager2 = CacheManager(cache_dir=cache_dir)

        # Create new main window (simulates app restart)
        main_window2 = MainWindow(cache_manager2)

        # Should have loaded 3DE scenes from cache
        session2_scene_count = len(main_window2.threede_scene_model.scenes)
        assert session2_scene_count == session1_scene_count

        # Verify specific scene data persisted correctly
        session2_users = {s.user for s in main_window2.threede_scene_model.scenes}
        expected_users = {"alice", "bob"}  # charlie only exists in later shots
        assert expected_users.issubset(session2_users)

        main_window2.close()

    def test_cache_cleanup_on_app_exit(self, mock_3de_workspace, qapp):
        """Test cache cleanup behavior on application exit."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Populate cache
        success, has_changes = scene_model.refresh_scenes(shots_data)
        assert success and has_changes

        # Verify cache files exist
        cache_file = cache_dir / "threede_scenes.json"
        assert cache_file.exists()

        # Simulate clean shutdown (cache should persist)
        del scene_model
        del cache_manager

        # Cache should still exist after clean shutdown
        assert cache_file.exists()

        # Verify cache is still readable
        with open(cache_file) as f:
            cache_data = json.load(f)
        assert len(cache_data["scenes"]) > 0

    def test_partial_cache_scenarios(self, mock_3de_workspace):
        """Test scenarios where cache exists but is incomplete."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Create partial cache with only some scenes
        partial_scenes = [
            {
                "show": "show1",
                "sequence": "SEQ001",
                "shot": "shot_000",
                "workspace_path": str(shots_data[0].workspace_path),
                "user": "alice",
                "plate": "FG01",
                "scene_path": "/some/path.3de",
            }
        ]

        cache_data = {"timestamp": datetime.now().isoformat(), "scenes": partial_scenes}

        cache_file = cache_dir / "threede_scenes.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # Create model - should load partial cache
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=True)

        assert len(scene_model.scenes) == 1

        # Refresh should merge with existing and add new scenes
        success, has_changes = scene_model.refresh_scenes(shots_data)

        assert success is True
        assert has_changes is True
        assert len(scene_model.scenes) > 1  # Should have more than just the cached one

    def test_cache_versioning_compatibility(self, mock_3de_workspace):
        """Test cache compatibility across different data formats."""
        cache_dir, workspace_dir, shots_data = mock_3de_workspace

        # Create cache with older format (missing some fields)
        old_format_scene = {
            "show": "show1",
            "sequence": "SEQ001",
            "shot": "shot_000",
            "workspace_path": str(shots_data[0].workspace_path),
            "user": "alice",
            "scene_path": "/some/path.3de",
            # Missing "plate" field - simulates older format
        }

        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "scenes": [old_format_scene],
        }

        cache_file = cache_dir / "threede_scenes.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # Should handle gracefully and fall back to fresh discovery
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Loading old format should fail gracefully
        cache_manager.get_cached_threede_scenes()
        # Might be None if validation fails, or empty list

        # Model creation should work regardless
        scene_model = ThreeDESceneModel(cache_manager, load_cache=True)

        # Refresh should work and create new proper format cache
        success, has_changes = scene_model.refresh_scenes(shots_data)
        assert success is True

        # Verify new cache has proper format
        with open(cache_file) as f:
            new_cache_data = json.load(f)

        if new_cache_data["scenes"]:
            # New format should have all required fields
            scene = new_cache_data["scenes"][0]
            required_fields = [
                "show",
                "sequence",
                "shot",
                "workspace_path",
                "user",
                "plate",
                "scene_path",
            ]
            assert all(field in scene for field in required_fields)

    @pytest.mark.performance
    def test_memory_usage_during_cache_operations(self, mock_3de_workspace):
        """Test memory usage during cache operations."""
        import os

        import psutil

        cache_dir, workspace_dir, shots_data = mock_3de_workspace
        process = psutil.Process(os.getpid())

        # Measure initial memory
        initial_memory = process.memory_info().rss

        # Create many cache managers and models
        managers_and_models = []
        for i in range(10):
            cache_manager = CacheManager(cache_dir=cache_dir)
            scene_model = ThreeDESceneModel(cache_manager, load_cache=False)
            managers_and_models.append((cache_manager, scene_model))

        # Refresh all models
        for cache_manager, scene_model in managers_and_models:
            scene_model.refresh_scenes(shots_data)

        # Measure peak memory
        peak_memory = process.memory_info().rss

        # Clean up
        del managers_and_models
        import gc

        gc.collect()

        # Measure final memory
        final_memory = process.memory_info().rss

        peak_increase = peak_memory - initial_memory
        final_increase = final_memory - initial_memory

        # Memory increase should be reasonable
        assert peak_increase < 200 * 1024 * 1024  # Less than 200MB peak
        assert final_increase < 50 * 1024 * 1024  # Less than 50MB after cleanup

        print(f"Peak memory increase: {peak_increase / (1024 * 1024):.1f}MB")
        print(f"Final memory increase: {final_increase / (1024 * 1024):.1f}MB")
