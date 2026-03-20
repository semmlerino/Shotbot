"""Unit tests for ThreeDELatestFinder."""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
# Local application imports
from threede import ThreeDELatestFinder


class TestFindLatestThreeDEScene:
    """Test find_latest_scene method."""

    def test_find_latest_across_plates(self, tmp_path: Path) -> None:
        """Test finding latest across different plate directories."""
        workspace = tmp_path / "workspace"
        base_3de = (
            workspace
            / "user"
            / "artist"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )

        # Create different plate directories
        fg_dir = base_3de / "FG01"
        fg_dir.mkdir(parents=True)
        (fg_dir / "track_v002.3de").touch()
        (fg_dir / "track_v004.3de").touch()

        bg_dir = base_3de / "BG01"
        bg_dir.mkdir(parents=True)
        (bg_dir / "track_v001.3de").touch()

        pl_dir = base_3de / "PL01"
        pl_dir.mkdir(parents=True)
        (pl_dir / "track_v006.3de").touch()  # Highest version

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "track_v006.3de"
        assert "PL01" in str(latest.parent)

    def test_special_3de_directory_structure(self, tmp_path: Path) -> None:
        """Test that 3DE's unique directory structure is handled correctly."""
        workspace = tmp_path / "workspace"

        # Correct structure
        correct_path = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "FG01"
        )
        correct_path.mkdir(parents=True)
        (correct_path / "track_v001.3de").touch()

        # Incorrect structure (like Maya's)
        wrong_path = workspace / "user" / "john" / "3de" / "scenes"
        wrong_path.mkdir(parents=True)
        (wrong_path / "track_v002.3de").touch()  # Should not be found

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "track_v001.3de"
        # Should only find file in correct structure


class TestFindAllThreeDEScenes:
    """Test find_all_scenes static method."""

    def test_find_all_across_plates(self, tmp_path: Path) -> None:
        """Test finding files across different plates."""
        workspace = tmp_path / "workspace"
        base_3de = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )

        # FG01 plate
        fg_dir = base_3de / "FG01"
        fg_dir.mkdir(parents=True)
        (fg_dir / "track_v001.3de").touch()

        # BG01 plate
        bg_dir = base_3de / "BG01"
        bg_dir.mkdir(parents=True)
        (bg_dir / "track_v001.3de").touch()

        # PL01 plate
        pl_dir = base_3de / "PL01"
        pl_dir.mkdir(parents=True)
        (pl_dir / "track_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 3
        # Files from all plates should be found
        parent_dirs = [s.parent.name for s in all_scenes]
        assert "FG01" in parent_dirs
        assert "BG01" in parent_dirs
        assert "PL01" in parent_dirs


class TestVersionPattern:
    """Test 3DE-specific version pattern."""

    def test_version_extraction(self, tmp_path: Path) -> None:
        """Test version extraction from 3DE files."""
        finder = ThreeDELatestFinder()

        # Test 3DE file
        threede_file = tmp_path / "track_v042.3de"
        threede_file.touch()
        assert finder._extract_version(threede_file) == 42

        # Test non-matching file
        other_file = tmp_path / "track.3de"
        other_file.touch()
        assert finder._extract_version(other_file) is None


class TestPlateHandling:
    """Test plate-specific functionality."""

    def test_standard_plate_names(self, tmp_path: Path) -> None:
        """Test handling of standard VFX plate names."""
        workspace = tmp_path / "workspace"
        base_3de = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )

        # Standard plate names
        plates = ["FG01", "FG02", "BG01", "BG02", "PL01", "BC01", "MP01"]
        for plate in plates:
            plate_dir = base_3de / plate
            plate_dir.mkdir(parents=True)
            (plate_dir / f"track_{plate}_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == len(plates)
        # All plates should be represented
        parent_names = {s.parent.name for s in all_scenes}
        assert parent_names == set(plates)

    def test_non_standard_plate_names(self, tmp_path: Path) -> None:
        """Test handling of non-standard plate names."""
        workspace = tmp_path / "workspace"
        base_3de = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )

        # Non-standard names
        plate_dir = base_3de / "CustomPlate"
        plate_dir.mkdir(parents=True)
        (plate_dir / "track_v001.3de").touch()

        # Numeric plate name
        num_dir = base_3de / "001"
        num_dir.mkdir(parents=True)
        (num_dir / "track_v001.3de").touch()

        finder = ThreeDELatestFinder()
        all_scenes = finder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 2
        # Should handle any directory name as plate


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_deeply_nested_plates(self, tmp_path: Path) -> None:
        """Test with nested plate structures."""
        workspace = tmp_path / "workspace"
        base_3de = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )

        # Create nested structure (shouldn't happen but test robustness)
        nested = base_3de / "FG01" / "subfolder"
        nested.mkdir(parents=True)
        (nested / "track_v001.3de").touch()  # Should not be found (too deep)

        # Regular file
        regular = base_3de / "BG01"
        regular.mkdir(parents=True)
        (regular / "track_v002.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        # Should only find files at correct depth
        assert len(all_scenes) == 1
        assert all_scenes[0].name == "track_v002.3de"

    def test_symlinks_in_structure(self, tmp_path: Path) -> None:
        """Test handling of symlinks in 3DE directory structure."""
        workspace = tmp_path / "workspace"
        real_3de = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "FG01"
        )
        real_3de.mkdir(parents=True)
        (real_3de / "track_v001.3de").touch()

        # Create symlink from another user
        link_base = (
            workspace
            / "user"
            / "alice"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )
        link_base.mkdir(parents=True)
        symlink = link_base / "FG01"
        symlink.symlink_to(real_3de)

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        # Should find files through both paths
        assert len(all_scenes) >= 1

    def test_special_characters_in_filenames(self, tmp_path: Path) -> None:
        """Test handling of special characters in filenames."""
        workspace = tmp_path / "workspace"
        threede_scenes = (
            workspace
            / "user"
            / "john-doe"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "FG-01"
        )
        threede_scenes.mkdir(parents=True)

        # Special characters in filename
        (threede_scenes / "track-final_v001.3de").touch()
        (threede_scenes / "shot_010_track_v002.3de").touch()

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "shot_010_track_v002.3de"
