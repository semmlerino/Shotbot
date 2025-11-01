"""Unit tests for 3DE scene finder."""

from pathlib import Path
from unittest.mock import Mock, patch

from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDEScene


class TestThreeDESceneFinder:
    """Test ThreeDESceneFinder utility class."""

    def test_find_scenes_for_shot_no_user_dir(self):
        """Test when user directory doesn't exist."""
        with patch("threede_scene_finder.Path") as mock_path_class:
            mock_user_dir = Mock()
            mock_user_dir.exists.return_value = False

            mock_path_class.return_value.__truediv__.return_value = mock_user_dir

        scenes = ThreeDESceneFinder.find_scenes_for_shot(
            "/shows/test/shots/AB_123/AB_123_0010",
            "test_show",
            "AB_123",
            "0010",
            {"gabriel-h"},
        )

        assert scenes == []

    def test_find_scenes_for_shot_with_scenes(self):
        """Test finding scenes successfully."""
        # Create mock user with proper rglob
        mock_user = Mock()
        mock_user.is_dir.return_value = True
        mock_user.name = "john-d"

        # Create mock scene file
        mock_scene_file = Mock(spec=Path)
        mock_scene_file.relative_to.return_value = Path("BG01/subfolder/scene.3de")
        mock_scene_file.parent.name = "subfolder"
        mock_user.rglob.return_value = [mock_scene_file]

        # Create mock user directory
        mock_user_dir = Mock()
        mock_user_dir.iterdir.return_value = [mock_user]

        with patch(
            "threede_scene_finder.PathUtils.validate_path_exists", return_value=True
        ), patch(
            "threede_scene_finder.PathUtils.build_path", return_value=mock_user_dir
        ), patch(
            "threede_scene_finder.ThreeDESceneFinder.verify_scene_exists",
            return_value=True,
        ), patch(
            "threede_scene_finder.ThreeDESceneFinder.extract_plate_from_path",
            return_value="BG01",
        ):
            scenes = ThreeDESceneFinder.find_scenes_for_shot(
                "/shows/test/shots/AB_123/AB_123_0010",
                "test_show",
                "AB_123",
                "0010",
                {"gabriel-h"},
            )

            assert len(scenes) == 1
            assert scenes[0].user == "john-d"
            assert scenes[0].plate == "BG01"
            assert scenes[0].show == "test_show"
            assert scenes[0].sequence == "AB_123"
            assert scenes[0].shot == "0010"

    def test_find_scenes_excludes_users(self):
        """Test that excluded users are skipped."""
        with patch("threede_scene_finder.Path") as mock_path_class:
            # Create mock user paths
            mock_excluded_user = Mock()
            mock_excluded_user.is_dir.return_value = True
            mock_excluded_user.name = "gabriel-h"

            mock_included_user = Mock()
            mock_included_user.is_dir.return_value = True
            mock_included_user.name = "john-d"

            # Setup scene base for included user
            mock_scene_file = Mock(spec=Path)
            mock_scene_file.relative_to.return_value = Path("FG01/scene.3de")

            mock_scene_base = Mock()
            mock_scene_base.exists.return_value = True
            mock_scene_base.rglob.return_value = [mock_scene_file]

            # Mock the path construction for included user
            mock_mm = Mock()
            mock_3de = Mock()
            mock_mm_default = Mock()
            mock_scenes = Mock()

            mock_included_user.__truediv__ = Mock(
                side_effect=lambda x: {
                    "mm": mock_mm,
                }.get(x, Mock())
            )

            mock_mm.__truediv__ = Mock(
                side_effect=lambda x: {
                    "3de": mock_3de,
                }.get(x, Mock())
            )

            mock_3de.__truediv__ = Mock(
                side_effect=lambda x: {
                    "mm-default": mock_mm_default,
                }.get(x, Mock())
            )

            mock_mm_default.__truediv__ = Mock(
                side_effect=lambda x: {
                    "scenes": mock_scenes,
                }.get(x, Mock())
            )

            mock_scenes.__truediv__ = Mock(
                side_effect=lambda x: {
                    "scene": mock_scene_base,
                }.get(x, Mock())
            )

            # Create mock user directory
            mock_user_dir = Mock()
            mock_user_dir.exists.return_value = True
            mock_user_dir.iterdir.return_value = [
                mock_excluded_user,
                mock_included_user,
            ]

            # Setup Path mock
            mock_path_class.return_value.__truediv__.return_value = mock_user_dir

        scenes = ThreeDESceneFinder.find_scenes_for_shot(
            "/shows/test/shots/AB_123/AB_123_0010",
            "test_show",
            "AB_123",
            "0010",
            {"gabriel-h"},
        )

        # Should only find scenes from john-d, not gabriel-h
        assert all(scene.user != "gabriel-h" for scene in scenes)

    def test_find_scenes_permission_error(self):
        """Test handling permission errors."""
        with patch("threede_scene_finder.Path") as mock_path_class:
            mock_user_dir = Mock()
            mock_user_dir.exists.return_value = True
            mock_user_dir.iterdir.side_effect = PermissionError("Access denied")

            mock_path_class.return_value.__truediv__.return_value = mock_user_dir

        scenes = ThreeDESceneFinder.find_scenes_for_shot(
            "/shows/test/shots/AB_123/AB_123_0010",
            "test_show",
            "AB_123",
            "0010",
            {"gabriel-h"},
        )

        assert scenes == []

    def test_find_all_scenes(self):
        """Test finding scenes for multiple shots."""
        shots = [
            ("/shows/test/shots/AB_123/AB_123_0010", "test_show", "AB_123", "0010"),
            ("/shows/test/shots/AB_123/AB_123_0020", "test_show", "AB_123", "0020"),
        ]

        with patch.object(ThreeDESceneFinder, "find_scenes_for_shot") as mock_find:
            mock_find.return_value = []

            scenes = ThreeDESceneFinder.find_all_scenes(shots, {"gabriel-h"})

            assert mock_find.call_count == 2
            assert scenes == []

    def test_verify_scene_exists(self):
        """Test verifying scene file exists."""
        with patch("threede_scene_finder.os.access") as mock_access, patch(
            "threede_scene_finder.PathUtils.validate_path_exists", return_value=True
        ):
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_path.is_file.return_value = True
            mock_path.suffix.lower.return_value = ".3de"
            mock_access.return_value = True

            result = ThreeDESceneFinder.verify_scene_exists(mock_path)
            assert result is True

    def test_verify_scene_not_exists(self):
        """Test verifying non-existent scene file."""
        mock_path = Mock()
        mock_path.exists.return_value = False

        result = ThreeDESceneFinder.verify_scene_exists(mock_path)
        assert result is False

    def test_verify_scene_not_file(self):
        """Test verifying path that exists but is not a file."""
        with patch("threede_scene_finder.os.access"):
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_path.is_file.return_value = False

            result = ThreeDESceneFinder.verify_scene_exists(mock_path)
            assert result is False

    def test_verify_scene_no_read_permission(self):
        """Test verifying file without read permission."""
        with patch("threede_scene_finder.os.access") as mock_access:
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_path.is_file.return_value = True
            mock_access.return_value = False  # No read permission

            result = ThreeDESceneFinder.verify_scene_exists(mock_path)
            assert result is False

    def test_verify_scene_exception(self):
        """Test handling exceptions in verify_scene_exists."""
        mock_path = Mock()
        mock_path.exists.side_effect = PermissionError("Access denied")

        result = ThreeDESceneFinder.verify_scene_exists(mock_path)
        assert result is False

    def test_find_scenes_generic_exception(self):
        """Test handling generic exceptions."""
        with patch("threede_scene_finder.Path") as mock_path_class:
            mock_user_dir = Mock()
            mock_user_dir.exists.return_value = True
            mock_user_dir.iterdir.side_effect = RuntimeError("Something went wrong")

            mock_path_class.return_value.__truediv__.return_value = mock_user_dir

        scenes = ThreeDESceneFinder.find_scenes_for_shot(
            "/shows/test/shots/AB_123/AB_123_0010",
            "test_show",
            "AB_123",
            "0010",
            {"gabriel-h"},
        )

        assert scenes == []

    def test_find_scenes_single_part_path(self):
        """Test handling 3DE files with single-part relative paths."""
        # Create mock user with proper rglob
        mock_user = Mock()
        mock_user.is_dir.return_value = True
        mock_user.name = "john-d"

        # Create mock scene file directly in scene base (single part path)
        mock_scene_file = Mock(spec=Path)
        # Only one part in relative path - "scene.3de"
        mock_scene_file.relative_to.return_value = Path("scene.3de")
        # Parent directory would be used as plate name
        mock_parent = Mock()
        mock_parent.name = "custom_plate"
        mock_scene_file.parent = mock_parent
        mock_user.rglob.return_value = [mock_scene_file]

        # Create mock user directory
        mock_user_dir = Mock()
        mock_user_dir.iterdir.return_value = [mock_user]

        with patch(
            "threede_scene_finder.PathUtils.validate_path_exists", return_value=True
        ), patch(
            "threede_scene_finder.PathUtils.build_path", return_value=mock_user_dir
        ), patch(
            "threede_scene_finder.ThreeDESceneFinder.verify_scene_exists",
            return_value=True,
        ), patch(
            "threede_scene_finder.ThreeDESceneFinder.extract_plate_from_path",
            return_value="custom_plate",
        ):
            scenes = ThreeDESceneFinder.find_scenes_for_shot(
                "/shows/test/shots/AB_123/AB_123_0010",
                "test_show",
                "AB_123",
                "0010",
                set(),
            )

            assert len(scenes) == 1
            assert scenes[0].plate == "custom_plate"  # Should use parent.name
            assert scenes[0].user == "john-d"

    def test_find_scenes_ignores_non_directories(self):
        """Test that non-directory entries in user dir are ignored."""
        with patch("threede_scene_finder.Path") as mock_path_class:
            # Create mock file (not directory)
            mock_file = Mock()
            mock_file.is_dir.return_value = False

            # Create mock user directory
            mock_user = Mock()
            mock_user.is_dir.return_value = True
            mock_user.name = "john-d"

            mock_user_dir = Mock()
            mock_user_dir.exists.return_value = True
            mock_user_dir.iterdir.return_value = [mock_file, mock_user]

            # Setup scene base to not exist for the user
            mock_scene_base = Mock()
            mock_scene_base.exists.return_value = False

            # Mock path construction
            mock_user.__truediv__ = Mock(
                return_value=Mock(
                    __truediv__=Mock(
                        return_value=Mock(
                            __truediv__=Mock(
                                return_value=Mock(
                                    __truediv__=Mock(
                                        return_value=Mock(
                                            __truediv__=Mock(
                                                return_value=mock_scene_base
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )

            mock_path_class.return_value.__truediv__.return_value = mock_user_dir

        scenes = ThreeDESceneFinder.find_scenes_for_shot(
            "/shows/test/shots/AB_123/AB_123_0010",
            "test_show",
            "AB_123",
            "0010",
            set(),
        )

        # Should skip the file and process only the directory
        assert scenes == []

    def test_find_all_scenes_with_results(self):
        """Test find_all_scenes with actual results."""
        shots = [
            ("/shows/test/shots/AB_123/AB_123_0010", "test_show", "AB_123", "0010"),
            ("/shows/test/shots/AB_123/AB_123_0020", "test_show", "AB_123", "0020"),
        ]

        with patch.object(ThreeDESceneFinder, "find_scenes_for_shot") as mock_find:
            scene1 = ThreeDEScene(
                show="test_show",
                sequence="AB_123",
                shot="0010",
                workspace_path="/shows/test/shots/AB_123/AB_123_0010",
                user="john-d",
                plate="FG01",
                scene_path=Path("/path/to/scene1.3de"),
            )
            scene2 = ThreeDEScene(
                show="test_show",
                sequence="AB_123",
                shot="0020",
                workspace_path="/shows/test/shots/AB_123/AB_123_0020",
                user="jane-s",
                plate="BG01",
                scene_path=Path("/path/to/scene2.3de"),
            )

            mock_find.side_effect = [[scene1], [scene2]]

            scenes = ThreeDESceneFinder.find_all_scenes(shots, {"gabriel-h"})

            assert len(scenes) == 2
            assert scenes[0] == scene1
            assert scenes[1] == scene2
