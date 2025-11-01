"""Unit tests for 3DE scene model."""

from pathlib import Path
from unittest.mock import Mock, patch

from threede_scene_model import ThreeDEScene, ThreeDESceneModel


class TestThreeDEScene:
    """Test ThreeDEScene dataclass."""

    def test_scene_creation(self):
        """Test creating a 3DE scene."""
        scene = ThreeDEScene(
            show="test_show",
            sequence="AB_123",
            shot="0010",
            workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            user="john-d",
            plate="FG01",
            scene_path=Path("/path/to/scene.3de"),
        )

        assert scene.show == "test_show"
        assert scene.sequence == "AB_123"
        assert scene.shot == "0010"
        assert scene.user == "john-d"
        assert scene.plate == "FG01"
        assert scene.scene_path == Path("/path/to/scene.3de")

    def test_full_name_property(self):
        """Test full_name property."""
        scene = ThreeDEScene(
            show="test_show",
            sequence="AB_123",
            shot="0010",
            workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            user="john-d",
            plate="FG01",
            scene_path=Path("/path/to/scene.3de"),
        )

        assert scene.full_name == "AB_123_0010"

    def test_display_name_property(self):
        """Test display_name property."""
        scene = ThreeDEScene(
            show="test_show",
            sequence="AB_123",
            shot="0010",
            workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            user="john-d",
            plate="FG01",
            scene_path=Path("/path/to/scene.3de"),
        )

        # Display name no longer includes plate after deduplication
        assert scene.display_name == "AB_123_0010 - john-d"

    def test_thumbnail_dir_property(self):
        """Test thumbnail_dir property."""
        scene = ThreeDEScene(
            show="test_show",
            sequence="AB_123",
            shot="0010",
            workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            user="john-d",
            plate="FG01",
            scene_path=Path("/path/to/scene.3de"),
        )

        # VFX convention: shot directory is named {sequence}_{shot}
        expected = Path(
            "/shows/test_show/shots/AB_123/AB_123_0010/publish/editorial/cutref/v001/jpg/1920x1080"
        )
        assert scene.thumbnail_dir == expected

    def test_to_dict(self):
        """Test converting to dictionary."""
        scene = ThreeDEScene(
            show="test_show",
            sequence="AB_123",
            shot="0010",
            workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            user="john-d",
            plate="FG01",
            scene_path=Path("/path/to/scene.3de"),
        )

        data = scene.to_dict()
        assert data["show"] == "test_show"
        assert data["user"] == "john-d"
        assert data["plate"] == "FG01"
        assert data["scene_path"] == "/path/to/scene.3de"

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "show": "test_show",
            "sequence": "AB_123",
            "shot": "0010",
            "workspace_path": "/shows/test_show/shots/AB_123/AB_123_0010",
            "user": "john-d",
            "plate": "FG01",
            "scene_path": "/path/to/scene.3de",
        }

        scene = ThreeDEScene.from_dict(data)
        assert scene.show == "test_show"
        assert scene.user == "john-d"
        assert scene.plate == "FG01"
        assert scene.scene_path == Path("/path/to/scene.3de")


class TestThreeDESceneModel:
    """Test ThreeDESceneModel class."""

    @patch("threede_scene_model.CacheManager")
    def test_initialization(self, mock_cache_manager):
        """Test model initialization."""
        mock_cache = Mock()
        mock_cache.get_cached_threede_scenes.return_value = None
        mock_cache_manager.return_value = mock_cache

        model = ThreeDESceneModel()

        assert model.scenes == []
        # Check that current user is excluded (get from environment)
        import os

        current_user = os.environ.get("USER", "default-user")
        assert model._excluded_users == {current_user}
        mock_cache.get_cached_threede_scenes.assert_called_once()

    @patch("threede_scene_model.CacheManager")
    def test_load_from_cache(self, mock_cache_manager):
        """Test loading scenes from cache."""
        cached_data = [
            {
                "show": "test_show",
                "sequence": "AB_123",
                "shot": "0010",
                "workspace_path": "/shows/test_show/shots/AB_123/AB_123_0010",
                "user": "john-d",
                "plate": "FG01",
                "scene_path": "/path/to/scene.3de",
            }
        ]

        mock_cache = Mock()
        mock_cache.get_cached_threede_scenes.return_value = cached_data
        mock_cache_manager.return_value = mock_cache

        model = ThreeDESceneModel()

        assert len(model.scenes) == 1
        assert model.scenes[0].user == "john-d"

    @patch("threede_scene_model.CacheManager")
    @patch("threede_scene_finder.ThreeDESceneFinder")
    def test_refresh_scenes(self, mock_finder_class, mock_cache_manager):
        """Test refreshing scenes."""
        from shot_model import Shot

        # Mock cache manager
        mock_cache = Mock()
        mock_cache.get_cached_threede_scenes.return_value = None
        mock_cache_manager.return_value = mock_cache

        # Mock the finder class method
        mock_finder_class.find_all_scenes_in_shows.return_value = [
            ThreeDEScene(
                show="test_show",
                sequence="AB_123",
                shot="0010",
                workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
                user="john-d",
                plate="FG01",
                scene_path=Path("/path/to/scene.3de"),
            )
        ]

        model = ThreeDESceneModel()

        # Create test shots
        shots = [
            Shot(
                show="test_show",
                sequence="AB_123",
                shot="0010",
                workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            )
        ]

        success, has_changes = model.refresh_scenes(shots)

        assert success
        assert has_changes
        assert len(model.scenes) == 1
        assert model.scenes[0].user == "john-d"

    def test_get_scene_by_index(self):
        """Test getting scene by index."""
        model = ThreeDESceneModel()
        model.scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="AB_123",
                shot="0010",
                workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
                user="john-d",
                plate="FG01",
                scene_path=Path("/path/to/scene.3de"),
            )
        ]

        scene = model.get_scene_by_index(0)
        assert scene is not None
        assert scene.user == "john-d"

        none_scene = model.get_scene_by_index(1)
        assert none_scene is None

    def test_find_scene_by_display_name(self):
        """Test finding scene by display name."""
        model = ThreeDESceneModel()
        model.scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="AB_123",
                shot="0010",
                workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
                user="john-d",
                plate="FG01",
                scene_path=Path("/path/to/scene.3de"),
            )
        ]

        # Display name no longer includes plate after deduplication
        scene = model.find_scene_by_display_name("AB_123_0010 - john-d")
        assert scene is not None
        assert scene.user == "john-d"

        none_scene = model.find_scene_by_display_name("Invalid Name")
        assert none_scene is None
