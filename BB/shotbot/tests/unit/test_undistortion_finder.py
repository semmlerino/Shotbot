"""Unit tests for undistortion finder."""

from pathlib import Path
from unittest.mock import patch

from undistortion_finder import UndistortionFinder


class TestUndistortionFinder:
    """Test the undistortion finder utility."""

    def test_find_latest_undistortion_no_base_path(self, tmp_path):
        """Test when base path doesn't exist."""
        result = UndistortionFinder.find_latest_undistortion(
            str(tmp_path / "nonexistent"), "108_CHV_0015"
        )
        assert result is None

    def test_find_latest_undistortion_no_versions(self, tmp_path):
        """Test when base path exists but no version directories."""
        # Create base path
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        base.mkdir(parents=True)

        result = UndistortionFinder.find_latest_undistortion(
            str(tmp_path), "108_CHV_0015"
        )
        assert result is None

    def test_find_latest_undistortion_single_version(self, tmp_path):
        """Test finding undistortion with single version."""
        shot_name = "108_CHV_0015"

        # Create directory structure with v001
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v001"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
        shot_dir.mkdir(parents=True)

        # Create the .nk file
        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v001.nk"
        nk_file.write_text("# Nuke script")

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result == nk_file

    def test_find_latest_undistortion_multiple_versions(self, tmp_path):
        """Test finding latest version among multiple."""
        shot_name = "108_CHV_0015"

        # Create directory structure with multiple versions
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )

        # Create v001, v003, v006 (not sequential)
        for version in ["v001", "v003", "v006"]:
            version_dir = base / version
            shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
            shot_dir.mkdir(parents=True)

            nk_file = shot_dir / f"{shot_name}_mm_default_LD_{version}.nk"
            nk_file.write_text(f"# Nuke script {version}")

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)

        # Should find v006 (latest)
        expected_path = (
            base
            / "v006"
            / f"{shot_name}_turnover-plate_bg01_aces_v002"
            / f"{shot_name}_mm_default_LD_v006.nk"
        )
        assert result == expected_path

    def test_find_latest_undistortion_missing_nk_file(self, tmp_path):
        """Test when version directory exists but .nk file is missing."""
        shot_name = "108_CHV_0015"

        # Create directory structure without .nk file
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v001"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
        shot_dir.mkdir(parents=True)

        # Don't create the .nk file

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result is None

    def test_find_latest_undistortion_invalid_version_dirs(self, tmp_path):
        """Test with directories that don't match version pattern."""
        shot_name = "108_CHV_0015"

        # Create base path with non-version directories
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        base.mkdir(parents=True)

        # Create invalid version directories
        (base / "version1").mkdir()
        (base / "test").mkdir()
        (base / "v1").mkdir()  # Wrong format (should be v001)

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result is None

    def test_get_version_from_path(self, tmp_path):
        """Test extracting version from path."""
        # Create a mock path
        path = tmp_path / "nuke_lens_distortion" / "v006" / "shot_dir" / "file.nk"
        path.parent.parent.mkdir(parents=True)

        result = UndistortionFinder.get_version_from_path(path)
        assert result == "v006"

    def test_get_version_from_path_invalid(self, tmp_path):
        """Test extracting version from invalid path."""
        # Path without proper version directory
        path = tmp_path / "some_dir" / "file.nk"

        result = UndistortionFinder.get_version_from_path(path)
        assert result is None

    def test_find_latest_undistortion_fg01_plate(self, tmp_path):
        """Test finding undistortion with FG01 plate."""
        shot_name = "GF_256_0020"

        # Create directory structure with FG01 instead of bg01
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "FG01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v001"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v001"
        shot_dir.mkdir(parents=True)

        # Create the .nk file
        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v001.nk"
        nk_file.write_text("# Nuke script for FG01")

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result == nk_file

    def test_find_latest_undistortion_prefer_fg_over_bg(self, tmp_path):
        """Test that FG01 is preferred over BG01 when both exist."""
        shot_name = "test_shot"

        # Create both FG01 and BG01 versions
        for plate_type in ["FG01", "BG01"]:
            base = (
                tmp_path
                / "user"
                / "gabriel-h"
                / "mm"
                / "3de"
                / "mm-default"
                / "exports"
                / "scene"
                / plate_type
                / "nuke_lens_distortion"
            )
            version_dir = base / "v001"
            shot_dir = (
                version_dir / f"{shot_name}_turnover-plate_{plate_type}_aces_v001"
            )
            shot_dir.mkdir(parents=True)

            nk_file = shot_dir / f"{shot_name}_mm_default_LD_v001.nk"
            nk_file.write_text(f"# Nuke script for {plate_type}")

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)

        # Should prefer FG01 over BG01
        assert result is not None
        assert "FG01" in str(result)
        assert "BG01" not in str(result)

    def test_find_latest_undistortion_flexible_colorspace(self, tmp_path):
        """Test finding undistortion with different colorspace patterns."""
        shot_name = "test_shot"

        # Create structure with non-standard colorspace
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "FG01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v002"
        # Different colorspace pattern: lin_sgamut3cine instead of aces
        shot_dir = version_dir / f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v003"
        shot_dir.mkdir(parents=True)

        # Create the .nk file
        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v002.nk"
        nk_file.write_text("# Nuke script with custom colorspace")

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result == nk_file

    def test_version_pattern_matching(self):
        """Test the version pattern regex."""
        pattern = UndistortionFinder.VERSION_PATTERN

        # Valid versions
        assert pattern.match("v001") is not None
        assert pattern.match("v006") is not None
        assert pattern.match("v999") is not None

        # Invalid versions
        assert pattern.match("v1") is None
        assert pattern.match("v0001") is None
        assert pattern.match("version001") is None
        assert pattern.match("001") is None

    def test_integration_with_script_generator(self, tmp_path):
        """Test integration with NukeScriptGenerator workflow."""
        shot_name = "test_shot_integration"

        # Create realistic undistortion file structure
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v003"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
        shot_dir.mkdir(parents=True)

        # Create realistic undistortion script content
        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v003.nk"
        nk_file.write_text("""# Nuke undistortion script v003
Root {
 inputs 0
 name test_shot_undistortion
}

LensDistortion {
 inputs 0
 serializeKnob ""
 model_card "3DE4 Anamorphic - Degree 6"
 name LensDistortion1
 selected true
}""")

        # Find undistortion file
        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result == nk_file

        # Verify version extraction works
        version = UndistortionFinder.get_version_from_path(result)
        assert version == "v003"

        # Test integration with NukeScriptGenerator (mock to avoid dependency)
        from nuke_script_generator import NukeScriptGenerator

        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            "",
            str(result),
            shot_name,  # Empty plate path, undistortion only
        )

        assert script_path is not None
        assert Path(script_path).exists()

        # Verify undistortion path is in generated script
        with open(script_path, "r") as f:
            content = f.read()

        assert str(result) in content
        assert "test_shot_integration_comp" in content

        # Cleanup
        Path(script_path).unlink()

    def test_find_undistortion_with_custom_username(self, tmp_path):
        """Test finding undistortion with custom username."""
        shot_name = "test_custom_user"
        custom_user = "jane-d"

        # Create structure for custom user
        base = (
            tmp_path
            / "user"
            / custom_user
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v004"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
        shot_dir.mkdir(parents=True)

        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v004.nk"
        nk_file.write_text("# Custom user undistortion script")

        # Find with custom username
        result = UndistortionFinder.find_latest_undistortion(
            str(tmp_path), shot_name, custom_user
        )
        assert result == nk_file

    def test_find_undistortion_with_none_username(self, tmp_path):
        """Test finding undistortion with None username (uses default)."""
        shot_name = "test_default_user"

        # Create structure for default user
        base = (
            tmp_path
            / "user"
            / "gabriel-h"  # Default username from Config
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v005"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
        shot_dir.mkdir(parents=True)

        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v005.nk"
        nk_file.write_text("# Default user undistortion script")

        # Find with None username (should use default)
        result = UndistortionFinder.find_latest_undistortion(
            str(tmp_path), shot_name, None
        )
        assert result == nk_file

    def test_find_undistortion_path_validation_integration(self, tmp_path):
        """Test path validation integration."""
        shot_name = "test_validation"

        # Test with non-existent workspace path
        result = UndistortionFinder.find_latest_undistortion(
            "/non/existent/workspace", shot_name
        )
        assert result is None

        # Test with valid workspace but no undistortion structure
        valid_workspace = tmp_path / "valid_workspace"
        valid_workspace.mkdir()

        result = UndistortionFinder.find_latest_undistortion(
            str(valid_workspace), shot_name
        )
        assert result is None

    @patch("undistortion_finder.Path.exists")
    def test_path_validation_mock_integration(self, mock_exists, tmp_path):
        """Test integration with path validation."""
        shot_name = "test_mock_validation"

        # Mock path existence check to return False
        mock_exists.return_value = False

        result = UndistortionFinder.find_latest_undistortion(str(tmp_path), shot_name)
        assert result is None

        # Verify path existence was checked
        mock_exists.assert_called()

    def test_undistortion_finder_error_handling(self, tmp_path):
        """Test error handling in UndistortionFinder."""

        # Test with empty shot name
        UndistortionFinder.find_latest_undistortion(str(tmp_path), "", "gabriel-h")
        # Should handle gracefully without crashing

        # Test with very long shot name
        long_shot_name = "a" * 1000
        UndistortionFinder.find_latest_undistortion(
            str(tmp_path), long_shot_name, "gabriel-h"
        )
        # Should handle gracefully without crashing

    def test_undistortion_finder_concurrent_access(self, tmp_path):
        """Test UndistortionFinder under concurrent access scenarios."""
        import threading

        shot_name = "test_concurrent"
        results = []

        # Create undistortion file
        base = (
            tmp_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v001"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_bg01_aces_v002"
        shot_dir.mkdir(parents=True)

        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v001.nk"
        nk_file.write_text("# Concurrent access test")

        def find_undistortion():
            result = UndistortionFinder.find_latest_undistortion(
                str(tmp_path), shot_name
            )
            results.append(result)

        # Launch multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=find_undistortion)
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Verify all threads got the same result
        assert len(results) == 5
        assert all(result == nk_file for result in results)
