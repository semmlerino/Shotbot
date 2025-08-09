"""Unit tests for raw plate finder."""

from raw_plate_finder import RawPlateFinder
from utils import VersionUtils


class TestRawPlateFinder:
    """Test the raw plate finder utility."""

    def test_find_latest_raw_plate_no_base_path(self, tmp_path):
        """Test when base path doesn't exist."""
        result = RawPlateFinder.find_latest_raw_plate(
            str(tmp_path / "nonexistent"), "108_CHV_0015"
        )
        assert result is None

    def test_find_latest_raw_plate_no_versions(self, tmp_path):
        """Test when base path exists but no version directories."""
        # Create base path
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "bg01"
        base.mkdir(parents=True)

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), "108_CHV_0015")
        assert result is None

    def test_find_latest_raw_plate_single_version(self, tmp_path):
        """Test finding raw plate with single version."""
        shot_name = "108_CHV_0015"

        # Create directory structure with v002
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "bg01"
        version_dir = base / "v002"
        resolution_dir = version_dir / "exr" / "4042x2274"
        resolution_dir.mkdir(parents=True)

        # Create an actual plate file for discovery
        plate_file = (
            resolution_dir / f"{shot_name}_turnover-plate_bg01_aces_v002.1001.exr"
        )
        plate_file.touch()

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)
        expected = str(
            resolution_dir / f"{shot_name}_turnover-plate_bg01_aces_v002.####.exr"
        )
        assert result == expected

    def test_find_latest_raw_plate_multiple_versions(self, tmp_path):
        """Test finding latest version among multiple."""
        shot_name = "108_CHV_0015"

        # Create directory structure with multiple versions
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "bg01"

        # Create v001, v002, v005 (not sequential)
        for version in ["v001", "v002", "v005"]:
            resolution_dir = base / version / "exr" / "4042x2274"
            resolution_dir.mkdir(parents=True)
            # Create an actual plate file for discovery
            plate_file = (
                resolution_dir
                / f"{shot_name}_turnover-plate_bg01_aces_{version}.1001.exr"
            )
            plate_file.touch()

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)

        # Should find v005 (latest)
        expected_dir = base / "v005" / "exr" / "4042x2274"
        expected = str(
            expected_dir / f"{shot_name}_turnover-plate_bg01_aces_v005.####.exr"
        )
        assert result == expected

    def test_find_latest_raw_plate_no_exr_directory(self, tmp_path):
        """Test when version exists but no exr directory."""
        shot_name = "108_CHV_0015"

        # Create directory structure without exr dir
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "bg01"
        version_dir = base / "v002"
        version_dir.mkdir(parents=True)

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)
        assert result is None

    def test_find_latest_raw_plate_no_resolution_directory(self, tmp_path):
        """Test when exr exists but no resolution directory."""
        shot_name = "108_CHV_0015"

        # Create directory structure without resolution dir
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "bg01"
        exr_dir = base / "v002" / "exr"
        exr_dir.mkdir(parents=True)

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)
        assert result is None

    def test_find_latest_raw_plate_multiple_resolutions(self, tmp_path):
        """Test with multiple resolution directories."""
        shot_name = "108_CHV_0015"

        # Create directory structure with multiple resolutions
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "bg01"
        exr_dir = base / "v002" / "exr"

        # Create multiple resolution directories
        for res in ["4042x2274", "2021x1137", "1920x1080"]:
            res_dir = exr_dir / res
            res_dir.mkdir(parents=True)
            # Create an actual plate file for discovery
            plate_file = res_dir / f"{shot_name}_turnover-plate_bg01_aces_v002.1001.exr"
            plate_file.touch()

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)

        # Should use the first resolution found (order may vary)
        assert result is not None
        assert "####.exr" in result
        assert shot_name in result

    def test_get_version_from_path(self):
        """Test extracting version from path."""
        path = "/shows/test/108_CHV_0015_turnover-plate_bg01_aces_v002.1001.exr"
        result = RawPlateFinder.get_version_from_path(path)
        assert result == "v002"

        # Test with #### pattern
        path = "/shows/test/108_CHV_0015_turnover-plate_bg01_aces_v005.####.exr"
        result = RawPlateFinder.get_version_from_path(path)
        assert result == "v005"

    def test_get_version_from_path_invalid(self):
        """Test extracting version from invalid path."""
        # Path without version pattern
        path = "/shows/test/some_file.exr"
        result = RawPlateFinder.get_version_from_path(path)
        assert result is None

    def test_verify_plate_exists_no_pattern(self):
        """Test verify with no #### pattern."""
        result = RawPlateFinder.verify_plate_exists("/path/without/pattern.exr")
        assert result is False

        result = RawPlateFinder.verify_plate_exists(None)
        assert result is False

    def test_verify_plate_exists_common_frame(self, tmp_path):
        """Test verify with common frame number."""
        # Create a file with frame 1001
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        frame_file = plate_dir / "shot_v001.1001.exr"
        frame_file.write_text("dummy")

        plate_path = str(plate_dir / "shot_v001.####.exr")
        result = RawPlateFinder.verify_plate_exists(plate_path)
        assert result is True

    def test_verify_plate_exists_pattern_match(self, tmp_path):
        """Test verify by pattern matching."""
        # Create a file with non-common frame number
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        frame_file = plate_dir / "shot_v001.1234.exr"
        frame_file.write_text("dummy")

        plate_path = str(plate_dir / "shot_v001.####.exr")
        result = RawPlateFinder.verify_plate_exists(plate_path)
        assert result is True

    def test_verify_plate_exists_no_frames(self, tmp_path):
        """Test verify when no frames exist."""
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_path = str(plate_dir / "shot_v001.####.exr")
        result = RawPlateFinder.verify_plate_exists(plate_path)
        assert result is False

    def test_version_pattern_matching(self):
        """Test the version pattern regex."""
        pattern = VersionUtils.VERSION_PATTERN

        # Valid versions
        assert pattern.match("v001") is not None
        assert pattern.match("v002") is not None
        assert pattern.match("v999") is not None

        # Invalid versions
        assert pattern.match("v1") is None
        assert pattern.match("v0001") is None
        assert pattern.match("version001") is None
        assert pattern.match("001") is None

    def test_find_latest_raw_plate_fg01(self, tmp_path):
        """Test finding FG01 plate instead of bg01."""
        shot_name = "GF_256_0760"

        # Create directory structure with FG01 plate
        base = tmp_path / "publish" / "turnover" / "plate" / "input_plate" / "FG01"
        version_dir = base / "v001"
        resolution_dir = version_dir / "exr" / "4312x2304"
        resolution_dir.mkdir(parents=True)

        # Create an actual plate file with lin_sgamut3cine color space
        plate_file = (
            resolution_dir
            / f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v001.1001.exr"
        )
        plate_file.touch()

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)
        expected = str(
            resolution_dir
            / f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v001.####.exr"
        )
        assert result == expected

    def test_find_latest_raw_plate_priority(self, tmp_path):
        """Test plate priority selection (BG01 over FG01)."""
        shot_name = "108_CHV_0015"

        # Create both FG01 and BG01 plates
        for plate_name in ["FG01", "BG01"]:
            base = (
                tmp_path / "publish" / "turnover" / "plate" / "input_plate" / plate_name
            )
            version_dir = base / "v001"
            resolution_dir = version_dir / "exr" / "4042x2274"
            resolution_dir.mkdir(parents=True)

            # Create actual plate files
            plate_file = (
                resolution_dir
                / f"{shot_name}_turnover-plate_{plate_name}_aces_v001.1001.exr"
            )
            plate_file.touch()

        result = RawPlateFinder.find_latest_raw_plate(str(tmp_path), shot_name)

        # Should prefer BG01 over FG01 based on priority
        assert result is not None
        assert "BG01" in result  # BG01 has higher priority
        assert "FG01" not in result
