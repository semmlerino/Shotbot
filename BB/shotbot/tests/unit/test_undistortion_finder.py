"""Unit tests for undistortion finder."""

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
