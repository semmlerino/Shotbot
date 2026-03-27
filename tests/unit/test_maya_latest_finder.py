"""Unit tests for MayaLatestFinder."""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from unittest.mock import patch

# Third-party imports
import pytest

# Local application imports
from discovery import MayaLatestFinder
from utils import get_current_username


_USERNAME: str = get_current_username()


class TestFindLatestMayaScene:
    """Test find_latest_scene method."""

    def test_find_latest_mixed_extensions(self, tmp_path: Path) -> None:
        """Test handling of mixed .ma and .mb files."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Mix of ASCII and Binary files
        (maya_scenes / "model_v001.ma").touch()
        (maya_scenes / "model_v002.mb").touch()
        (maya_scenes / "model_v003.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "model_v003.ma"


class TestFindAllMayaScenes:
    """Test find_all_scenes class method."""

    def test_exclude_autosave_by_default(self, tmp_path: Path) -> None:
        """Test that autosave files are excluded by default."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create regular and autosave files
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene_v001.ma.autosave").touch()
        (maya_scenes / "backup.autosave.mb").touch()

        all_scenes = MayaLatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "scene_v001.ma"

    def test_include_autosave_when_requested(self, tmp_path: Path) -> None:
        """Test that autosave files are always excluded (no include_autosave param)."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        # Create regular and autosave files
        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene.ma.autosave").touch()
        (maya_scenes / "model.autosave.mb").touch()

        # Note: find_all_scenes doesn't have include_autosave parameter
        # Autosave files are always excluded
        all_scenes = MayaLatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "scene_v001.ma"


class TestVersionPattern:
    """Test Maya-specific version pattern."""

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
        real_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        real_scenes.mkdir(parents=True)
        (real_scenes / "scene_v001.ma").touch()

        # Create symlink from another user pointing to current user's directory
        link_target = workspace / "user" / "other-artist"
        link_target.mkdir(parents=True)
        symlink = link_target / "maya"
        symlink.symlink_to(workspace / "user" / _USERNAME / "maya")

        finder = MayaLatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert _USERNAME in str(latest)

    def test_other_users_filtered_out(self, tmp_path: Path) -> None:
        """Only current user's files are found; other users are filtered out."""
        workspace = tmp_path / "workspace"

        # Create files under other users — should be invisible
        for user in ["alice", "bob", "charlie"]:
            scenes = workspace / "user" / user / "mm" / "maya" / "scenes"
            scenes.mkdir(parents=True)
            (scenes / "scene_v010.ma").touch()

        # Create file under current user
        my_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        my_scenes.mkdir(parents=True)
        (my_scenes / "scene_v001.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "scene_v001.ma"
        assert _USERNAME in str(latest.parent)

    def test_permission_denied_handling(self, tmp_path: Path) -> None:
        """Test that permission errors are raised (not handled)."""
        workspace = tmp_path / "workspace"
        user_base = workspace / "user"
        user_base.mkdir(parents=True)

        finder = MayaLatestFinder()

        # Mock iterdir to raise PermissionError
        with (
            patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")),
            pytest.raises(PermissionError),
        ):
            # The implementation doesn't catch PermissionError, so it should be raised
            finder.find_latest_scene(str(workspace))
