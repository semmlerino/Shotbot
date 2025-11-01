"""Test colorspace and raw flag detection for Nuke script generation."""

from nuke_script_generator import NukeScriptGenerator


class TestNukeColorspaceDetection:
    """Test colorspace and raw flag detection logic."""

    def test_linear_plate_detection(self):
        """Test detection of linear plates."""
        # Test various linear plate paths
        test_cases = [
            "/shows/test/plate_lin_sgamut3cine.%04d.exr",
            "/path/to/linear/plate.%04d.exr",
            "/shows/jack_ryan/FG01_lin_v001.%04d.exr",
        ]

        for path in test_cases:
            colorspace, use_raw = NukeScriptGenerator._detect_colorspace(path)
            assert colorspace == "linear", f"Failed for {path}"
            assert use_raw is True, f"Raw flag should be True for {path}"

    def test_log_plate_detection(self):
        """Test detection of log plates."""
        # LogC/Alexa plates
        colorspace, use_raw = NukeScriptGenerator._detect_colorspace(
            "/shows/test/plate_logc_alexa.%04d.exr"
        )
        assert colorspace == "logc3ei800"
        assert use_raw is False

        # Generic log plates
        colorspace, use_raw = NukeScriptGenerator._detect_colorspace(
            "/shows/test/plate_log.%04d.exr"
        )
        assert colorspace == "log"
        assert use_raw is False

    def test_display_colorspace_detection(self):
        """Test detection of display-referred colorspaces."""
        # Rec709
        colorspace, use_raw = NukeScriptGenerator._detect_colorspace(
            "/shows/test/plate_rec709.%04d.exr"
        )
        assert colorspace == "rec709"
        assert use_raw is False

        # sRGB
        colorspace, use_raw = NukeScriptGenerator._detect_colorspace(
            "/shows/test/plate_srgb.%04d.exr"
        )
        assert colorspace == "sRGB"
        assert use_raw is False

    def test_default_colorspace(self):
        """Test default colorspace for unknown patterns."""
        # Unknown pattern should default to linear raw
        colorspace, use_raw = NukeScriptGenerator._detect_colorspace(
            "/shows/test/some_plate.%04d.exr"
        )
        assert colorspace == "linear"
        assert use_raw is True

        # Empty path should also default to linear raw
        colorspace, use_raw = NukeScriptGenerator._detect_colorspace("")
        assert colorspace == "linear"
        assert use_raw is True

    def test_generated_script_raw_flag(self, tmp_path):
        """Test that raw flag is correctly set in generated scripts."""
        # Create test plates
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        # Create dummy EXR file
        plate_file = plate_dir / "test_lin_plate.1001.exr"
        plate_file.write_text("dummy")

        # Generate script for linear plate
        linear_path = str(plate_dir / "test_lin_plate.%04d.exr")
        script_path = NukeScriptGenerator.create_plate_script(linear_path, "test_shot")

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Check for correct raw flag
        assert "raw true" in content
        assert 'colorspace "linear"' in content

        # Clean up
        import os

        os.unlink(script_path)

    def test_generated_script_format(self, tmp_path):
        """Test that format string doesn't include square_pixels."""
        # Create test plate
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test.1001.exr"
        plate_file.write_text("dummy")

        plate_path = str(plate_dir / "test.%04d.exr")
        script_path = NukeScriptGenerator.create_plate_script(plate_path, "test_shot")

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Format should end with shot_name_format, not square_pixels
        assert '"4312 2304 0 0 4312 2304 1 test_shot_format"' in content
        assert "square_pixels" not in content

        # Clean up
        import os

        os.unlink(script_path)
