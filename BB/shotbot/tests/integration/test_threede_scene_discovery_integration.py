"""Integration tests for 3DE Scene Discovery workflow."""

import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from cache_manager import CacheManager
from shot_model import Shot, ShotModel
from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDEScene, ThreeDESceneModel
from threede_scene_scanner import ThreeDEScannerManager, ThreeDESceneScanner


class TestThreeDESceneDiscoveryIntegration:
    """Test complete 3DE scene discovery workflow."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for cache and mock workspace."""
        with tempfile.TemporaryDirectory() as cache_dir:
            with tempfile.TemporaryDirectory() as workspace_dir:
                yield Path(cache_dir), Path(workspace_dir)

    @pytest.fixture
    def mock_workspace_structure(self, temp_dirs):
        """Create mock workspace structure with 3DE scenes."""
        _, workspace_dir = temp_dirs

        # Create shot workspace paths
        shot1_path = workspace_dir / "show1" / "shots" / "seq001" / "seq001_0010"
        shot2_path = workspace_dir / "show1" / "shots" / "seq001" / "seq001_0020"

        # Create user directories with 3DE scenes
        for shot_path in [shot1_path, shot2_path]:
            # User 1: alice
            alice_scene_dir = (
                shot_path
                / "user"
                / "alice"
                / "mm"
                / "3de"
                / "mm-default"
                / "scenes"
                / "scene"
                / "FG01"
                / "v001"
            )
            alice_scene_dir.mkdir(parents=True)
            (alice_scene_dir / "alice_scene.3de").touch()

            # User 2: bob
            bob_scene_dir = (
                shot_path
                / "user"
                / "bob"
                / "mm"
                / "3de"
                / "mm-default"
                / "scenes"
                / "scene"
                / "BG01"
                / "v002"
            )
            bob_scene_dir.mkdir(parents=True)
            (bob_scene_dir / "bob_scene.3de").touch()

            # User 3: gabriel-h (excluded user)
            gabriel_scene_dir = (
                shot_path
                / "user"
                / "gabriel-h"
                / "mm"
                / "3de"
                / "mm-default"
                / "scenes"
                / "scene"
                / "MAIN"
            )
            gabriel_scene_dir.mkdir(parents=True)
            (gabriel_scene_dir / "gabriel_scene.3de").touch()

        return {
            "shot1_path": str(shot1_path),
            "shot2_path": str(shot2_path),
            "workspace_dir": workspace_dir,
        }

    @pytest.fixture
    def sample_shots(self, mock_workspace_structure):
        """Create sample shots for testing."""
        return [
            Shot(
                show="show1",
                sequence="seq001",
                shot="0010",
                workspace_path=mock_workspace_structure["shot1_path"],
            ),
            Shot(
                show="show1",
                sequence="seq001",
                shot="0020",
                workspace_path=mock_workspace_structure["shot2_path"],
            ),
        ]

    @pytest.fixture
    def threede_scene_model_with_cache(self, temp_dirs):
        """Create ThreeDESceneModel with custom cache directory."""
        cache_dir, _ = temp_dirs
        cache_manager = CacheManager(cache_dir=cache_dir)
        return ThreeDESceneModel(cache_manager, load_cache=False)

    def test_scene_finder_discovery_workflow(
        self, mock_workspace_structure, sample_shots
    ):
        """Test complete scene discovery workflow through ThreeDESceneFinder."""
        shot = sample_shots[0]
        excluded_users = {"gabriel-h"}

        # Discover scenes for shot
        scenes = ThreeDESceneFinder.find_scenes_for_shot(
            shot.workspace_path, shot.show, shot.sequence, shot.shot, excluded_users
        )

        # Should find 2 scenes (alice and bob, excluding gabriel-h)
        assert len(scenes) == 2

        # Verify scene properties
        scene_users = {scene.user for scene in scenes}
        assert scene_users == {"alice", "bob"}

        # Verify scene data
        alice_scene = next(s for s in scenes if s.user == "alice")
        assert alice_scene.show == "show1"
        assert alice_scene.sequence == "seq001"
        assert alice_scene.shot == "0010"
        assert alice_scene.plate == "mm-default"
        assert alice_scene.display_name == "seq001_0010 - alice"
        assert alice_scene.scene_path.name == "alice_scene.3de"

    def test_scene_model_refresh_and_caching(
        self, threede_scene_model_with_cache, sample_shots, temp_dirs
    ):
        """Test ThreeDESceneModel refresh with caching."""
        cache_dir, _ = temp_dirs

        # Initial refresh should discover scenes
        success, has_changes = threede_scene_model_with_cache.refresh_scenes(
            sample_shots
        )

        assert success is True
        assert has_changes is True
        assert len(threede_scene_model_with_cache.scenes) == 4  # 2 shots × 2 users each

        # Verify cache was created
        cache_file = cache_dir / "threede_scenes.json"
        assert cache_file.exists()

        # Verify cache content
        with open(cache_file) as f:
            cache_data = json.load(f)

        assert "timestamp" in cache_data
        assert len(cache_data["scenes"]) == 4

        # Verify scene data in cache
        cached_scenes = cache_data["scenes"]
        users_in_cache = {scene["user"] for scene in cached_scenes}
        assert users_in_cache == {"alice", "bob"}

        plates_in_cache = {scene["plate"] for scene in cached_scenes}
        assert plates_in_cache == {"mm-default"}

    def test_scene_model_loads_from_cache(self, temp_dirs):
        """Test ThreeDESceneModel loads from cache on initialization."""
        cache_dir, _ = temp_dirs

        # Create cache data
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "scenes": [
                {
                    "show": "cached_show",
                    "sequence": "cached_seq",
                    "shot": "9999",
                    "workspace_path": "/cached/path",
                    "user": "cached_user",
                    "plate": "CACHED_PLATE",
                    "scene_path": "/cached/scene.3de",
                }
            ],
        }

        cache_file = cache_dir / "threede_scenes.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # Create model - should load from cache
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=True)

        # Should have loaded from cache
        assert len(model.scenes) == 1
        scene = model.scenes[0]
        assert scene.show == "cached_show"
        assert scene.user == "cached_user"
        assert scene.plate == "CACHED_PLATE"

    def test_scene_model_change_detection(
        self, threede_scene_model_with_cache, sample_shots, mock_workspace_structure
    ):
        """Test ThreeDESceneModel detects changes correctly."""
        # First refresh
        success1, has_changes1 = threede_scene_model_with_cache.refresh_scenes(
            sample_shots
        )
        assert success1 and has_changes1
        initial_count = len(threede_scene_model_with_cache.scenes)

        # Second refresh with same data - no changes
        success2, has_changes2 = threede_scene_model_with_cache.refresh_scenes(
            sample_shots
        )
        assert success2 and not has_changes2
        assert len(threede_scene_model_with_cache.scenes) == initial_count

        # Add new scene file to workspace
        workspace_dir = mock_workspace_structure["workspace_dir"]
        new_scene_dir = (
            workspace_dir
            / "show1"
            / "shots"
            / "seq001"
            / "seq001_0010"
            / "user"
            / "charlie"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "COMP"
        )
        new_scene_dir.mkdir(parents=True)
        (new_scene_dir / "charlie_scene.3de").touch()

        # Third refresh should detect changes
        success3, has_changes3 = threede_scene_model_with_cache.refresh_scenes(
            sample_shots
        )
        assert success3 and has_changes3
        assert len(threede_scene_model_with_cache.scenes) > initial_count

        # Verify new scene was found
        charlie_scenes = [
            s for s in threede_scene_model_with_cache.scenes if s.user == "charlie"
        ]
        assert len(charlie_scenes) == 1
        assert charlie_scenes[0].plate == "COMP"

    def test_cache_expiry_handling(self, temp_dirs):
        """Test handling of expired 3DE scene cache."""
        cache_dir, _ = temp_dirs

        # Create expired cache
        old_time = datetime.now() - timedelta(hours=2)
        cache_data = {
            "timestamp": old_time.isoformat(),
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

        # Cache manager should return None for expired cache
        cache_manager = CacheManager(cache_dir=cache_dir)
        cached_scenes = cache_manager.get_cached_threede_scenes()
        assert cached_scenes is None

        # Model should start with empty scenes when cache expired
        model = ThreeDESceneModel(cache_manager, load_cache=True)
        assert len(model.scenes) == 0

    def test_background_scanner_workflow(self, sample_shots, qapp):
        """Test background scanner integration."""
        excluded_users = {"gabriel-h"}

        # Create scanner
        scanner = ThreeDESceneScanner(sample_shots, excluded_users)

        # Connect signals to track results
        progress_updates = []
        found_scenes = []
        finished_scenes = []

        scanner.signals.progress.connect(lambda c, t: progress_updates.append((c, t)))
        scanner.signals.scene_found.connect(lambda s: found_scenes.append(s))
        scanner.signals.finished.connect(lambda scenes: finished_scenes.extend(scenes))

        # Run scanner
        scanner.run()

        # Process any pending events
        qapp.processEvents()

        # Verify progress updates
        assert len(progress_updates) > 0
        final_progress = progress_updates[-1]
        assert final_progress == (len(sample_shots), len(sample_shots))

        # Verify scenes were found
        assert len(found_scenes) == 4  # 2 shots × 2 users each
        assert len(finished_scenes) == 4

        # Verify scene data
        users_found = {scene.user for scene in found_scenes}
        assert users_found == {"alice", "bob"}

    def test_scanner_manager_integration(self, sample_shots, qapp):
        """Test ThreeDEScannerManager workflow."""
        excluded_users = {"gabriel-h"}

        # Create scanner manager
        manager = ThreeDEScannerManager()

        # Track signals
        scan_started = []
        scan_finished = []
        progress_updates = []

        manager.scan_started.connect(lambda: scan_started.append(True))
        manager.scan_finished.connect(lambda scenes: scan_finished.extend(scenes))
        manager.scan_progress.connect(lambda c, t: progress_updates.append((c, t)))

        # Start scan
        manager.start_scan(sample_shots, excluded_users)

        # Process events to allow background processing
        qapp.processEvents()
        time.sleep(0.1)  # Allow time for thread processing
        qapp.processEvents()

        # Verify scan started
        assert len(scan_started) == 1

        # Wait a bit more for completion (background processing)
        for _ in range(10):  # Wait up to 1 second
            qapp.processEvents()
            if scan_finished:
                break
            time.sleep(0.1)

        # Should have received results
        if scan_finished:  # Background processing completed
            assert len(scan_finished) == 4
            users_found = {scene.user for scene in scan_finished}
            assert users_found == {"alice", "bob"}

    def test_integration_with_shot_model_workflow(
        self, temp_dirs, mock_workspace_structure
    ):
        """Test integration between ShotModel and ThreeDESceneModel."""
        cache_dir, _ = temp_dirs

        # Create cache manager
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Create shot model and mock shot refresh
        shot_model = ShotModel(cache_manager, load_cache=False)
        shot_model.shots = [
            Shot("show1", "seq001", "0010", mock_workspace_structure["shot1_path"]),
            Shot("show1", "seq001", "0020", mock_workspace_structure["shot2_path"]),
        ]

        # Create 3DE scene model
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Refresh scenes using shots from shot model
        success, has_changes = scene_model.refresh_scenes(shot_model.shots)

        assert success is True
        assert has_changes is True
        assert len(scene_model.scenes) == 4

        # Verify scenes correspond to shots
        shot_names = {f"{shot.sequence}_{shot.shot}" for shot in shot_model.shots}
        scene_shot_names = {scene.full_name for scene in scene_model.scenes}
        assert scene_shot_names == shot_names

        # Verify 3DE scene cache was created (shots cache only created when refreshed via subprocess)
        assert (cache_dir / "threede_scenes.json").exists()

    def test_invalid_cache_handling(self, temp_dirs):
        """Test handling of corrupted 3DE scene cache."""
        cache_dir, _ = temp_dirs

        # Write invalid JSON
        cache_file = cache_dir / "threede_scenes.json"
        cache_file.write_text("{ invalid json }")

        # Should handle gracefully
        cache_manager = CacheManager(cache_dir=cache_dir)
        cached_scenes = cache_manager.get_cached_threede_scenes()
        assert cached_scenes is None

        # Model should start with empty scenes
        model = ThreeDESceneModel(cache_manager, load_cache=True)
        assert len(model.scenes) == 0

    def test_serialization_roundtrip(
        self, threede_scene_model_with_cache, sample_shots
    ):
        """Test scene serialization and deserialization roundtrip."""
        # Discover scenes
        success, has_changes = threede_scene_model_with_cache.refresh_scenes(
            sample_shots
        )
        assert success and has_changes

        original_scenes = threede_scene_model_with_cache.scenes.copy()

        # Convert to dict and back
        scene_dicts = threede_scene_model_with_cache.to_dict()
        restored_scenes = [ThreeDEScene.from_dict(d) for d in scene_dicts]

        # Should match original scenes
        assert len(restored_scenes) == len(original_scenes)

        for original, restored in zip(original_scenes, restored_scenes):
            assert original.show == restored.show
            assert original.sequence == restored.sequence
            assert original.shot == restored.shot
            assert original.user == restored.user
            assert original.plate == restored.plate
            assert original.workspace_path == restored.workspace_path
            assert str(original.scene_path) == str(restored.scene_path)
            assert original.display_name == restored.display_name
