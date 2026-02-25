"""Unit tests for ThreeDELatestFinder."""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from unittest.mock import patch

# Third-party imports
import pytest

# Local application imports
from threede_latest_finder import ThreeDELatestFinder


class TestFindLatestThreeDEScene:
    """Test find_latest_threede_scene method."""

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
        latest = finder.find_latest_threede_scene(str(workspace))

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
        latest = finder.find_latest_threede_scene(str(workspace))

        assert latest is not None
        assert latest.name == "track_v001.3de"
        # Should only find file in correct structure

    def test_no_plate_directories(self, tmp_path: Path) -> None:
        """Test 3DE structure without plate subdirectories."""
        workspace = tmp_path / "workspace"
        threede_base = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )
        threede_base.mkdir(parents=True)
        # No plate subdirectories created

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_threede_scene(str(workspace))

        assert latest is None

    def test_with_shot_name_in_logging(self, tmp_path: Path) -> None:
        """Test that shot name is used in logging."""
        workspace = tmp_path / "workspace"
        threede_scenes = (
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
        threede_scenes.mkdir(parents=True)
        (threede_scenes / "track_v001.3de").touch()

        finder = ThreeDELatestFinder()
        with patch.object(finder.logger, "info") as mock_info:
            latest = finder.find_latest_threede_scene(
                str(workspace), shot_name="shot_010"
            )

            assert latest is not None
            mock_info.assert_called_with(
                "Found latest 3DE scene for shot_010: track_v001.3de"
            )

    def test_logging_for_found_files(self, tmp_path: Path) -> None:
        """Test debug logging for found files."""
        workspace = tmp_path / "workspace"
        threede_scenes = (
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
        threede_scenes.mkdir(parents=True)
        (threede_scenes / "track_v001.3de").touch()
        (threede_scenes / "track_v002.3de").touch()

        finder = ThreeDELatestFinder()
        with patch.object(finder.logger, "debug") as mock_debug:
            finder.find_latest_threede_scene(str(workspace))

            # Check that files are logged
            assert any(
                "Found 3DE file: track_v001.3de (v001)" in str(call)
                for call in mock_debug.call_args_list
            )
            assert any(
                "Found 3DE file: track_v002.3de (v002)" in str(call)
                for call in mock_debug.call_args_list
            )


class TestFindAllThreeDEScenes:
    """Test find_all_threede_scenes static method."""

    def test_find_all_basic(self, tmp_path: Path) -> None:
        """Test finding all 3DE scene files."""
        workspace = tmp_path / "workspace"
        threede_scenes = (
            workspace
            / "user"
            / "artist"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "FG01"
        )
        threede_scenes.mkdir(parents=True)

        # Create various 3DE files
        (threede_scenes / "track_v001.3de").touch()
        (threede_scenes / "track_v002.3de").touch()
        (threede_scenes / "solve_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

        assert len(all_scenes) == 3
        assert all(scene.suffix == ".3de" for scene in all_scenes)

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

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

        assert len(all_scenes) == 3
        # Files from all plates should be found
        parent_dirs = [s.parent.name for s in all_scenes]
        assert "FG01" in parent_dirs
        assert "BG01" in parent_dirs
        assert "PL01" in parent_dirs

    def test_find_all_multiple_users(self, tmp_path: Path) -> None:
        """Test finding files across multiple users."""
        workspace = tmp_path / "workspace"

        # User 1 - Add version numbers for files to be included
        user1_scenes = (
            workspace
            / "user"
            / "alice"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "FG01"
        )
        user1_scenes.mkdir(parents=True)
        (user1_scenes / "alice_track_v001.3de").touch()

        # User 2 - Add version numbers for files to be included
        user2_scenes = (
            workspace
            / "user"
            / "bob"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
            / "BG01"
        )
        user2_scenes.mkdir(parents=True)
        (user2_scenes / "bob_track_v002.3de").touch()
        (user2_scenes / "bob_solve_v003.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

        assert len(all_scenes) == 3
        scene_names = [s.name for s in all_scenes]
        assert "alice_track_v001.3de" in scene_names
        assert "bob_track_v002.3de" in scene_names
        assert "bob_solve_v003.3de" in scene_names



class TestVersionPattern:
    """Test 3DE-specific version pattern."""

    def test_version_pattern_matches_3de_files(self) -> None:
        """Test pattern matches .3de files correctly."""
        finder = ThreeDELatestFinder()

        # Should match
        assert finder.VERSION_PATTERN.search("track_v001.3de") is not None
        assert finder.VERSION_PATTERN.search("solve_v999.3de") is not None

        # Should not match
        assert finder.VERSION_PATTERN.search("track_v001.txt") is None
        assert finder.VERSION_PATTERN.search("track.3de") is None
        assert finder.VERSION_PATTERN.search("v001_track.3de") is None
        assert finder.VERSION_PATTERN.search("track_v001.ma") is None  # Wrong extension

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

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

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
        all_scenes = finder.find_all_threede_scenes(str(workspace))

        assert len(all_scenes) == 2
        # Should handle any directory name as plate

    def test_empty_plate_directories(self, tmp_path: Path) -> None:
        """Test handling of empty plate directories."""
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

        # Empty plate directory
        empty_plate = base_3de / "FG01"
        empty_plate.mkdir(parents=True)

        # Plate with files
        active_plate = base_3de / "BG01"
        active_plate.mkdir(parents=True)
        (active_plate / "track_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].parent.name == "BG01"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_mixed_case_extensions(self, tmp_path: Path) -> None:
        """Test handling of mixed case file extensions."""
        workspace = tmp_path / "workspace"
        threede_scenes = (
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
        threede_scenes.mkdir(parents=True)

        # Mixed case extensions (should match if filesystem is case-insensitive)
        (threede_scenes / "track_v001.3de").touch()
        (threede_scenes / "track_v002.3DE").touch()  # Uppercase
        (threede_scenes / "track_v003.3De").touch()  # Mixed

        finder = ThreeDELatestFinder()
        all_scenes = finder.find_all_threede_scenes(str(workspace))

        # At least lowercase should be found
        assert len(all_scenes) >= 1

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

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

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

        all_scenes = ThreeDELatestFinder.find_all_threede_scenes(str(workspace))

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
        latest = finder.find_latest_threede_scene(str(workspace))

        assert latest is not None
        assert latest.name == "shot_010_track_v002.3de"


class TestPerformance:
    """Test performance-related scenarios."""

    @pytest.mark.slow
    def test_many_plates_performance(self, tmp_path: Path) -> None:
        """Test performance with many plate directories."""
        # Standard library imports
        import time

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

        # Create many plate directories
        for i in range(50):
            plate_dir = base_3de / f"PLATE{i:02d}"
            plate_dir.mkdir(parents=True)
            (plate_dir / f"track_v{i + 1:03d}.3de").touch()

        finder = ThreeDELatestFinder()
        start = time.time()
        latest = finder.find_latest_threede_scene(str(workspace))
        elapsed = time.time() - start

        assert latest is not None
        assert latest.name == "track_v050.3de"
        # Should complete quickly even with many plates
        assert elapsed < 2.0

    @pytest.mark.slow
    def test_many_files_per_plate_performance(self, tmp_path: Path) -> None:
        """Test performance with many files in each plate."""
        # Standard library imports
        import time

        workspace = tmp_path / "workspace"
        threede_scenes = (
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
        threede_scenes.mkdir(parents=True)

        # Create many versioned files in single plate
        for i in range(100):
            (threede_scenes / f"track_v{i + 1:03d}.3de").touch()

        finder = ThreeDELatestFinder()
        start = time.time()
        latest = finder.find_latest_threede_scene(str(workspace))
        elapsed = time.time() - start

        assert latest is not None
        assert latest.name == "track_v100.3de"
        assert elapsed < 1.0
