"""Integration tests for 3DE scene deduplication and caching functionality."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from cache_manager import CacheManager
from shot_model import Shot
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


class TestThreeDEDeduplicationIntegration:
    """Integration tests for the complete 3DE deduplication workflow."""

    def setup_method(self):
        """Set up test environment with fresh cache."""
        # Use temporary directory for cache to avoid interfering with real cache
        self.temp_dir = Path(tempfile.mkdtemp())

        # Create cache manager with temporary directory
        self.cache_manager = CacheManager(cache_dir=self.temp_dir)

        # Create model with our cache manager
        self.model = ThreeDESceneModel(self.cache_manager, load_cache=False)

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_deduplication_workflow(self):
        """Test complete workflow: discovery -> deduplication -> caching -> reload."""
        # Create test shots
        shots = [
            Shot("show_a", "seq_01", "0010", "/shows/show_a/shots/seq_01/0010"),
            Shot("show_a", "seq_01", "0020", "/shows/show_a/shots/seq_01/0020"),
        ]

        # Mock scene discovery to return multiple scenes per shot
        discovered_scenes = [
            # Shot 0010 - multiple scenes (should be deduplicated)
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/shows/show_a/shots/seq_01/0010",
                user="artist1",
                plate="FG01",
                scene_path=self._mock_scene_path("scene1_fg.3de", 2000.0),
            ),
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/shows/show_a/shots/seq_01/0010",
                user="artist2",
                plate="BG01",
                scene_path=self._mock_scene_path("scene2_bg.3de", 1500.0),
            ),
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/shows/show_a/shots/seq_01/0010",
                user="artist3",
                plate="FG01",
                scene_path=self._mock_scene_path(
                    "scene3_fg_old.3de", 1000.0
                ),  # Older FG01
            ),
            # Shot 0020 - single scene (should be kept as-is)
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0020",
                workspace_path="/shows/show_a/shots/seq_01/0020",
                user="artist4",
                plate="BG01",
                scene_path=self._mock_scene_path("scene4_bg.3de", 1800.0),
            ),
        ]

        # Mock the finder
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = discovered_scenes

            # Step 1: Refresh scenes (discovery + deduplication + caching)
            success, has_changes = self.model.refresh_scenes(shots)

            assert success
            assert has_changes

            # Step 2: Verify deduplication worked correctly
            assert len(self.model.scenes) == 2  # One scene per shot

            # Verify shot 0010 has the newest FG01 scene (artist1, mtime=2000.0)
            shot_0010_scene = next(s for s in self.model.scenes if s.shot == "0010")
            assert shot_0010_scene.user == "artist1"
            assert shot_0010_scene.plate == "FG01"
            assert shot_0010_scene.scene_path.name == "scene1_fg.3de"

            # Verify shot 0020 has its only scene
            shot_0020_scene = next(s for s in self.model.scenes if s.shot == "0020")
            assert shot_0020_scene.user == "artist4"
            assert shot_0020_scene.plate == "BG01"
            assert shot_0020_scene.scene_path.name == "scene4_bg.3de"

    def test_cache_persistence_across_app_restarts(self):
        """Test that deduplication results persist across application restarts."""
        # Create test data
        shots = [Shot("test_show", "seq_01", "0010", "/path/to/shot")]

        original_scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path/to/shot",
                user="user1",
                plate="FG01",
                scene_path=self._mock_scene_path("scene1.3de", 2000.0),
            ),
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path/to/shot",
                user="user2",
                plate="BG01",
                scene_path=self._mock_scene_path("scene2.3de", 1000.0),
            ),
        ]

        # First application run: discover and cache scenes
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = original_scenes

            success, has_changes = self.model.refresh_scenes(shots)
            assert success and has_changes
            assert len(self.model.scenes) == 1
            assert self.model.scenes[0].user == "user1"  # FG01 preferred over BG01

        # Simulate application restart: create new model instance
        model2 = ThreeDESceneModel(self.cache_manager, load_cache=True)

        # Verify scenes were loaded from cache
        assert len(model2.scenes) == 1
        assert model2.scenes[0].user == "user1"
        assert model2.scenes[0].plate == "FG01"
        assert model2.scenes[0].scene_path.name == "scene1.3de"

        # Verify the data is identical
        original_scene = self.model.scenes[0]
        cached_scene = model2.scenes[0]

        assert original_scene.show == cached_scene.show
        assert original_scene.sequence == cached_scene.sequence
        assert original_scene.shot == cached_scene.shot
        assert original_scene.user == cached_scene.user
        assert original_scene.plate == cached_scene.plate
        assert str(original_scene.scene_path) == str(cached_scene.scene_path)

    def test_priority_selection_edge_cases(self):
        """Test priority selection with various edge cases."""
        shots = [Shot("test_show", "seq_01", "0010", "/path")]

        # Create scenes with mixed priority scenarios
        scenes = [
            # Same plate, different mtimes
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user1",
                plate="FG01",
                scene_path=self._mock_scene_path("old_fg.3de", 1000.0),
            ),
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user2",
                plate="FG01",
                scene_path=self._mock_scene_path("new_fg.3de", 3000.0),
            ),
            # Different plate, newer mtime
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user3",
                plate="BG01",
                scene_path=self._mock_scene_path("newer_bg.3de", 2000.0),
            ),
            # File that doesn't exist
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user4",
                plate="FG02",
                scene_path=self._mock_scene_path_error("missing.3de"),
            ),
        ]

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = scenes

            success, has_changes = self.model.refresh_scenes(shots)
            assert success and has_changes
            assert len(self.model.scenes) == 1

            # Should select the newest FG01 (user2, mtime=3000.0)
            selected = self.model.scenes[0]
            assert selected.user == "user2"
            assert selected.plate == "FG01"
            assert selected.scene_path.name == "new_fg.3de"

    def test_empty_discovery_caching(self):
        """Test that empty discovery results are properly cached."""
        shots = [Shot("empty_show", "seq_01", "0010", "/path")]

        # Mock finder to return empty results
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = []

            # First refresh - should cache empty results
            success, has_changes = self.model.refresh_scenes(shots)
            assert success
            assert len(self.model.scenes) == 0

            # Create new model to test cache persistence
            model2 = ThreeDESceneModel(self.cache_manager, load_cache=True)
            assert len(model2.scenes) == 0

            # Second refresh should detect no changes (cached empty results)
            success2, has_changes2 = model2.refresh_scenes(shots)
            assert success2
            assert not has_changes2  # No changes from empty to empty

    def test_scene_changes_detection(self):
        """Test that scene changes are properly detected."""
        shots = [Shot("test_show", "seq_01", "0010", "/path")]

        initial_scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user1",
                plate="FG01",
                scene_path=self._mock_scene_path("scene1.3de", 1000.0),
            )
        ]

        # First refresh - initial data
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = initial_scenes

            success, has_changes = self.model.refresh_scenes(shots)
            assert success and has_changes
            assert len(self.model.scenes) == 1
            assert self.model.scenes[0].user == "user1"

        # Second refresh - same data, should detect no changes
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = initial_scenes

            success, has_changes = self.model.refresh_scenes(shots)
            assert success
            assert not has_changes  # Same data

        # Third refresh - new scene added, should detect changes
        updated_scenes = initial_scenes + [
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user2",
                plate="BG01",
                scene_path=self._mock_scene_path("scene2.3de", 2000.0),
            )
        ]

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = updated_scenes

            success, has_changes = self.model.refresh_scenes(shots)
            assert success and has_changes
            # Should still have only 1 scene after deduplication, but now the newer one
            assert len(self.model.scenes) == 1
            assert self.model.scenes[0].user == "user2"  # Newer BG01 beats older FG01

    def _mock_scene_path(self, filename: str, mtime: float) -> Mock:
        """Create a mock Path object with specified mtime."""
        mock_path = Mock(spec=Path)
        mock_path.name = filename
        mock_path.__str__ = Mock(return_value=f"/path/to/{filename}")

        mock_stat = Mock()
        mock_stat.st_mtime = mtime
        mock_path.stat.return_value = mock_stat

        return mock_path

    def _mock_scene_path_error(self, filename: str) -> Mock:
        """Create a mock Path object that raises OSError on stat()."""
        mock_path = Mock(spec=Path)
        mock_path.name = filename
        mock_path.__str__ = Mock(return_value=f"/path/to/{filename}")
        mock_path.stat.side_effect = OSError("File not found")

        return mock_path

    def test_concurrent_operations_simulation(self):
        """Test behavior under simulated concurrent operations."""
        shots = [Shot("test_show", "seq_01", "0010", "/path")]

        scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user1",
                plate="FG01",
                scene_path=self._mock_scene_path("scene.3de", 1000.0),
            )
        ]

        # Simulate multiple rapid refresh operations
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = scenes

            results = []
            for i in range(5):
                success, has_changes = self.model.refresh_scenes(shots)
                results.append((success, has_changes))

            # First should detect changes, rest should not
            assert results[0] == (True, True)  # Initial discovery
            for i in range(1, 5):
                assert results[i] == (True, False)  # No changes on subsequent calls

            # Model should remain consistent
            assert len(self.model.scenes) == 1
            assert self.model.scenes[0].user == "user1"
