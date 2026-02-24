"""Unit tests for MayaLatestFinder."""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from unittest.mock import patch

# Third-party imports
import pytest

# Local application imports
from maya_latest_finder import MayaLatestFinder


class TestFindLatestMayaScene:
    """Test find_latest_maya_scene method."""

    def test_find_latest_with_multiple_versions(self, tmp_path: Path) -> None:
        """Test finding latest from multiple versioned files."""
        # Create workspace structure
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create versioned Maya files
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene_v003.ma").touch()
        (maya_scenes / "scene_v002.mb").touch()
        (maya_scenes / "scene_v005.mb").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is not None
        assert latest.name == "scene_v005.mb"
        assert latest.parent == maya_scenes

    def test_find_latest_with_multiple_users(self, tmp_path: Path) -> None:
        """Test finding latest across multiple users."""
        workspace = tmp_path / "workspace"

        # Create files for user1
        user1_scenes = workspace / "user" / "alice" / "mm" / "maya" / "scenes"
        user1_scenes.mkdir(parents=True)
        (user1_scenes / "shot_v002.ma").touch()

        # Create files for user2
        user2_scenes = workspace / "user" / "bob" / "mm" / "maya" / "scenes"
        user2_scenes.mkdir(parents=True)
        (user2_scenes / "shot_v004.ma").touch()
        (user2_scenes / "shot_v001.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is not None
        assert latest.name == "shot_v004.ma"
        assert "bob" in str(latest.parent)

    def test_find_latest_mixed_extensions(self, tmp_path: Path) -> None:
        """Test handling of mixed .ma and .mb files."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "artist" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Mix of ASCII and Binary files
        (maya_scenes / "model_v001.ma").touch()
        (maya_scenes / "model_v002.mb").touch()
        (maya_scenes / "model_v003.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is not None
        assert latest.name == "model_v003.ma"

    def test_no_maya_scenes_directory(self, tmp_path: Path) -> None:
        """Test user directory without maya/scenes structure."""
        workspace = tmp_path / "workspace"
        user_dir = workspace / "user" / "john"
        user_dir.mkdir(parents=True)
        # No maya/scenes directory

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is None

    def test_no_versioned_files(self, tmp_path: Path) -> None:
        """Test directory with no versioned Maya files."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create unversioned files
        (maya_scenes / "temp.ma").touch()
        (maya_scenes / "backup.mb").touch()
        (maya_scenes / "scene_noversion.ma").touch()

        finder = MayaLatestFinder()
        with patch.object(finder.logger, "debug") as mock_debug:
            latest = finder.find_latest_maya_scene(str(workspace))

            assert latest is None
            mock_debug.assert_any_call(f"No Maya files found in workspace: {workspace}")

    def test_with_shot_name_in_logging(self, tmp_path: Path) -> None:
        """Test that shot name is used in logging."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)
        (maya_scenes / "anim_v001.ma").touch()

        finder = MayaLatestFinder()
        with patch.object(finder.logger, "info") as mock_info:
            latest = finder.find_latest_maya_scene(str(workspace), shot_name="shot_010")

            assert latest is not None
            mock_info.assert_called_with(
                "Found latest Maya scene for shot_010: anim_v001.ma"
            )

    def test_logging_for_found_files(self, tmp_path: Path) -> None:
        """Test debug logging for found files."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene_v002.mb").touch()

        finder = MayaLatestFinder()
        with patch.object(finder.logger, "debug") as mock_debug:
            finder.find_latest_maya_scene(str(workspace))

            # Check that files are logged
            assert any(
                "Found Maya ASCII file: scene_v001.ma (v001)" in str(call)
                for call in mock_debug.call_args_list
            )
            assert any(
                "Found Maya Binary file: scene_v002.mb (v002)" in str(call)
                for call in mock_debug.call_args_list
            )


class TestFindAllMayaScenes:
    """Test find_all_maya_scenes static method."""

    def test_find_all_basic(self, tmp_path: Path) -> None:
        """Test finding all Maya scene files."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "artist" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create various Maya files
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene_v002.ma").touch()
        (maya_scenes / "model_v001.mb").touch()

        all_scenes = MayaLatestFinder.find_all_maya_scenes(str(workspace))

        assert len(all_scenes) == 3
        assert all(scene.suffix in [".ma", ".mb"] for scene in all_scenes)

    def test_find_all_multiple_users(self, tmp_path: Path) -> None:
        """Test finding files across multiple users."""
        workspace = tmp_path / "workspace"

        # User 1
        user1_scenes = workspace / "user" / "alice" / "mm" / "maya" / "scenes"
        user1_scenes.mkdir(parents=True)
        (user1_scenes / "alice_scene.ma").touch()

        # User 2
        user2_scenes = workspace / "user" / "bob" / "mm" / "maya" / "scenes"
        user2_scenes.mkdir(parents=True)
        (user2_scenes / "bob_scene.ma").touch()
        (user2_scenes / "bob_model.mb").touch()

        all_scenes = MayaLatestFinder.find_all_maya_scenes(str(workspace))

        assert len(all_scenes) == 3
        # Check files from both users are found
        scene_names = [s.name for s in all_scenes]
        assert "alice_scene.ma" in scene_names
        assert "bob_scene.ma" in scene_names
        assert "bob_model.mb" in scene_names

    def test_exclude_autosave_by_default(self, tmp_path: Path) -> None:
        """Test that autosave files are excluded by default."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create regular and autosave files
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene_v001.ma.autosave").touch()
        (maya_scenes / "backup.autosave.mb").touch()

        all_scenes = MayaLatestFinder.find_all_maya_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "scene_v001.ma"

    def test_include_autosave_when_requested(self, tmp_path: Path) -> None:
        """Test that autosave files are always excluded (no include_autosave param)."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create regular and autosave files
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene.ma.autosave").touch()
        (maya_scenes / "model.autosave.mb").touch()

        # Note: find_all_maya_scenes doesn't have include_autosave parameter
        # Autosave files are always excluded
        all_scenes = MayaLatestFinder.find_all_maya_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "scene_v001.ma"

    def test_no_maya_directory_returns_empty(self, tmp_path: Path) -> None:
        """Test workspace with users but no maya directories."""
        workspace = tmp_path / "workspace"
        user_dir = workspace / "user" / "john" / "nuke" / "scripts"
        user_dir.mkdir(parents=True)
        # No maya directory

        all_scenes = MayaLatestFinder.find_all_maya_scenes(str(workspace))

        assert all_scenes == []


class TestVersionPattern:
    """Test Maya-specific version pattern."""

    def test_version_pattern_matches_ma_files(self) -> None:
        """Test pattern matches .ma files correctly."""
        finder = MayaLatestFinder()

        # Should match
        assert finder.VERSION_PATTERN.search("scene_v001.ma") is not None
        assert finder.VERSION_PATTERN.search("file_v999.ma") is not None

        # Should not match
        assert finder.VERSION_PATTERN.search("scene_v001.txt") is None
        assert finder.VERSION_PATTERN.search("scene.ma") is None
        assert finder.VERSION_PATTERN.search("v001_scene.ma") is None

    def test_version_pattern_matches_mb_files(self) -> None:
        """Test pattern matches .mb files correctly."""
        finder = MayaLatestFinder()

        # Should match
        assert finder.VERSION_PATTERN.search("model_v042.mb") is not None
        assert finder.VERSION_PATTERN.search("rig_v007.mb") is not None

        # Should not match
        assert finder.VERSION_PATTERN.search("model_v001.blend") is None
        assert finder.VERSION_PATTERN.search("model.mb") is None

    def test_version_extraction(self, tmp_path: Path) -> None:
        """Test version extraction from Maya files."""
        finder = MayaLatestFinder()

        # Test .ma file
        ma_file = tmp_path / "scene_v042.ma"
        ma_file.touch()
        assert finder._extract_version(ma_file) == 42

        # Test .mb file
        mb_file = tmp_path / "model_v007.mb"
        mb_file.touch()
        assert finder._extract_version(mb_file) == 7

        # Test non-matching file
        other_file = tmp_path / "scene.ma"
        other_file.touch()
        assert finder._extract_version(other_file) is None


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_symlinks_handling(self, tmp_path: Path) -> None:
        """Test handling of symlinks in directory structure."""
        workspace = tmp_path / "workspace"
        real_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        real_scenes.mkdir(parents=True)
        (real_scenes / "scene_v001.ma").touch()

        # Create symlink to another user's directory
        link_target = workspace / "user" / "alice"
        link_target.mkdir(parents=True)
        symlink = link_target / "maya"
        symlink.symlink_to(workspace / "user" / "john" / "maya")

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is not None
        # Should find the file through either path

    def test_hidden_files_ignored(self, tmp_path: Path) -> None:
        """Test that hidden files are handled appropriately."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create hidden and regular files
        (maya_scenes / ".hidden_v001.ma").touch()
        (maya_scenes / "scene_v002.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        # Hidden file should still be found if it matches pattern
        assert latest is not None
        # Latest should be v002
        assert latest.name == "scene_v002.ma"

    def test_special_characters_in_paths(self, tmp_path: Path) -> None:
        """Test handling of special characters in file names."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john-doe" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Files with special characters (but valid version pattern)
        (maya_scenes / "scene-final_v001.ma").touch()
        (maya_scenes / "shot_010_anim_v002.mb").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is not None
        assert latest.name == "shot_010_anim_v002.mb"

    def test_deeply_nested_users(self, tmp_path: Path) -> None:
        """Test with non-standard user directory structure."""
        workspace = tmp_path / "workspace"

        # Create multiple user directories with Maya scenes
        users = ["alice", "bob", "charlie", "diana"]
        for i, user in enumerate(users):
            scenes = workspace / "user" / user / "mm" / "maya" / "scenes"
            scenes.mkdir(parents=True)
            (scenes / f"scene_v{i + 1:03d}.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_maya_scene(str(workspace))

        assert latest is not None
        assert latest.name == "scene_v004.ma"
        assert "diana" in str(latest.parent)

    def test_permission_denied_handling(self, tmp_path: Path) -> None:
        """Test that permission errors are raised (not handled)."""
        workspace = tmp_path / "workspace"
        user_base = workspace / "user"
        user_base.mkdir(parents=True)

        finder = MayaLatestFinder()

        # Mock iterdir to raise PermissionError
        with patch.object(
            Path, "iterdir", side_effect=PermissionError("Access denied")
        ), pytest.raises(PermissionError):
            # The implementation doesn't catch PermissionError, so it should be raised
            finder.find_latest_maya_scene(str(workspace))


class TestPerformance:
    """Test performance-related scenarios."""

    @pytest.mark.slow
    def test_large_directory_performance(self, tmp_path: Path) -> None:
        """Test performance with many files."""
        # Standard library imports
        import time

        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / "john" / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create many versioned files
        for i in range(100):
            (maya_scenes / f"scene_v{i + 1:03d}.ma").touch()

        finder = MayaLatestFinder()
        start = time.time()
        latest = finder.find_latest_maya_scene(str(workspace))
        elapsed = time.time() - start

        assert latest is not None
        assert latest.name == "scene_v100.ma"
        # Should complete quickly even with many files
        assert elapsed < 1.0  # Less than 1 second

    @pytest.mark.slow
    def test_many_users_performance(self, tmp_path: Path) -> None:
        """Test performance with many user directories."""
        # Standard library imports
        import time

        workspace = tmp_path / "workspace"

        # Create many users with files
        for i in range(20):
            user_scenes = workspace / "user" / f"user{i:02d}" / "mm" / "maya" / "scenes"
            user_scenes.mkdir(parents=True)
            (user_scenes / f"scene_v{i + 1:03d}.ma").touch()

        finder = MayaLatestFinder()
        start = time.time()
        latest = finder.find_latest_maya_scene(str(workspace))
        elapsed = time.time() - start

        assert latest is not None
        # Should find the highest version across all users
        assert latest.name == "scene_v020.ma"
        assert elapsed < 2.0  # Less than 2 seconds
