"""Unit tests for nuke_media_detector module.

Tests detection utilities for frame ranges, colorspaces, resolutions,
and media properties from file paths.
"""

from unittest.mock import MagicMock, patch

from nuke.media_detector import NukeMediaDetector


class TestNukeMediaDetector:
    """Test media property detection methods."""

    def test_detect_frame_range_empty_path(self) -> None:
        """Test frame range detection with empty path."""
        first, last = NukeMediaDetector.detect_frame_range("")

        assert first == 1001
        assert last == 1100

    def test_detect_frame_range_nonexistent_directory(self) -> None:
        """Test frame range detection with non-existent directory."""
        first, last = NukeMediaDetector.detect_frame_range(
            "/nonexistent/path/shot_####.exr"
        )

        assert first == 1001
        assert last == 1100

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.iterdir")
    def test_detect_frame_range_with_hash_pattern(
        self, mock_iterdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test frame range detection with #### pattern."""
        # Setup mock directory that exists
        mock_exists.return_value = True

        # Create mock files with frame numbers
        mock_files = []
        for filename in [
            "shot_1001.exr",
            "shot_1050.exr",
            "shot_1100.exr",
            "other_file.txt",
        ]:
            mock_file = MagicMock()
            mock_file.name = filename
            mock_files.append(mock_file)
        mock_iterdir.return_value = mock_files

        first, last = NukeMediaDetector.detect_frame_range("/path/to/shot_####.exr")

        assert first == 1001
        assert last == 1100

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.iterdir")
    def test_detect_frame_range_with_printf_pattern(
        self, mock_iterdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test frame range detection with %04d pattern."""
        mock_exists.return_value = True

        # Use exact pattern match - %04d becomes (\d{4}) regex
        mock_files = []
        for filename in ["2001.exr", "2025.exr", "2050.exr"]:
            mock_file = MagicMock()
            mock_file.name = filename
            mock_files.append(mock_file)
        mock_iterdir.return_value = mock_files

        first, last = NukeMediaDetector.detect_frame_range("/path/to/%04d.exr")

        assert first == 2001
        assert last == 2050

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.iterdir")
    def test_detect_frame_range_no_matching_files(
        self, mock_iterdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test frame range detection when no files match pattern."""
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_file.name = "unrelated.txt"
        mock_iterdir.return_value = [mock_file]

        first, last = NukeMediaDetector.detect_frame_range("/path/to/shot_####.exr")

        assert first == 1001
        assert last == 1100

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.iterdir")
    def test_detect_frame_range_exception_handling(
        self, mock_iterdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test frame range detection handles exceptions gracefully."""
        mock_exists.return_value = True
        mock_iterdir.side_effect = OSError("Permission denied")

        first, last = NukeMediaDetector.detect_frame_range("/path/to/shot_####.exr")

        assert first == 1001
        assert last == 1100

    def test_detect_colorspace_empty_path(self) -> None:
        """Test colorspace detection with empty path."""
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace("")

        assert colorspace == "linear"
        assert raw_flag is True

    def test_detect_colorspace_linear_plates(self) -> None:
        """Test colorspace detection for linear plates."""
        test_paths = [
            "/path/to/lin_plate_v001.exr",
            "/path/to/linear_shot.exr",
            "/path/to/LIN_PLATE.EXR",
            "/path/to/LINEAR_SHOT.EXR",
        ]

        for path in test_paths:
            colorspace, raw_flag = NukeMediaDetector.detect_colorspace(path)
            assert colorspace == "linear"
            assert raw_flag is True

    def test_detect_colorspace_logc_plates(self) -> None:
        """Test colorspace detection for LogC plates."""
        test_paths = [
            "/path/to/logc_plate.exr",
            "/path/to/alexa_shot.exr",
            "/path/to/LOGC_PLATE.EXR",
            "/path/to/ALEXA_SHOT.EXR",
        ]

        for path in test_paths:
            colorspace, raw_flag = NukeMediaDetector.detect_colorspace(path)
            assert colorspace == "logc3ei800"
            assert raw_flag is False

    def test_detect_colorspace_log_plates(self) -> None:
        """Test colorspace detection for generic log plates."""
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace(
            "/path/to/log_plate.exr"
        )

        assert colorspace == "log"
        assert raw_flag is False

    def test_detect_colorspace_rec709_plates(self) -> None:
        """Test colorspace detection for Rec.709 plates."""
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace(
            "/path/to/rec709_plate.exr"
        )

        assert colorspace == "rec709"
        assert raw_flag is False

    def test_detect_colorspace_srgb_plates(self) -> None:
        """Test colorspace detection for sRGB plates."""
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace(
            "/path/to/srgb_plate.exr"
        )

        assert colorspace == "sRGB"
        assert raw_flag is False

    def test_detect_colorspace_default_fallback(self) -> None:
        """Test colorspace detection defaults to linear for unknown formats."""
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace(
            "/path/to/unknown_plate.exr"
        )

        assert colorspace == "linear"
        assert raw_flag is True

    def test_detect_resolution_empty_path(self) -> None:
        """Test resolution detection with empty path."""
        width, height = NukeMediaDetector.detect_resolution("")

        assert width == 4312
        assert height == 2304

    def test_detect_resolution_common_formats(self) -> None:
        """Test resolution detection for common formats."""
        test_cases = [
            ("/path/to/1920x1080_plate.exr", 1920, 1080),
            ("/path/to/4096x2304_shot.exr", 4096, 2304),
            ("/path/to/shot_3840x2160.exr", 3840, 2160),
            ("/path/to/2048x1556_comp.exr", 2048, 1556),
        ]

        for path, expected_width, expected_height in test_cases:
            width, height = NukeMediaDetector.detect_resolution(path)
            assert width == expected_width
            assert height == expected_height

    def test_detect_resolution_with_underscore_separator(self) -> None:
        """Test resolution detection with underscore separator."""
        width, height = NukeMediaDetector.detect_resolution(
            "/path/to/shot_2048_1556.exr"
        )

        assert width == 2048
        assert height == 1556

    def test_detect_resolution_no_match(self) -> None:
        """Test resolution detection when no pattern matches."""
        width, height = NukeMediaDetector.detect_resolution(
            "/path/to/shot_no_resolution.exr"
        )

        assert width == 4312
        assert height == 2304

    def test_detect_resolution_invalid_values(self) -> None:
        """Test resolution detection with invalid numeric values."""
        # Too small values should fall back to default
        width, height = NukeMediaDetector.detect_resolution("/path/to/shot_100x50.exr")

        assert width == 4312
        assert height == 2304

    def test_detect_resolution_out_of_range(self) -> None:
        """Test resolution detection with out-of-range values."""
        # Too large values should fall back to default
        width, height = NukeMediaDetector.detect_resolution(
            "/path/to/shot_10000x10000.exr"
        )

        assert width == 4312
        assert height == 2304

    def test_detect_resolution_sanity_check_bounds(self) -> None:
        """Test resolution detection sanity check boundaries."""
        # Test edge cases for sanity check
        test_cases = [
            ("/path/640x480.exr", 640, 480),  # Minimum valid
            ("/path/8192x4320.exr", 8192, 4320),  # Maximum valid
            ("/path/639x480.exr", 4312, 2304),  # Below minimum width
            ("/path/640x479.exr", 4312, 2304),  # Below minimum height
            ("/path/8193x4320.exr", 4312, 2304),  # Above maximum width
            ("/path/8192x4321.exr", 4312, 2304),  # Above maximum height
        ]

        for path, expected_width, expected_height in test_cases:
            width, height = NukeMediaDetector.detect_resolution(path)
            assert width == expected_width
            assert height == expected_height

    def test_detect_media_properties_comprehensive(self) -> None:
        """Test comprehensive media properties detection."""
        properties = NukeMediaDetector.detect_media_properties(
            "/path/to/lin_1920x1080_shot.exr"
        )

        # Should contain all expected keys
        expected_keys = {
            "first_frame",
            "last_frame",
            "width",
            "height",
            "colorspace",
            "raw_flag",
        }
        assert set(properties.keys()) == expected_keys

        # Check types
        assert isinstance(properties["first_frame"], int)
        assert isinstance(properties["last_frame"], int)
        assert isinstance(properties["width"], int)
        assert isinstance(properties["height"], int)
        assert isinstance(properties["colorspace"], str)
        assert isinstance(properties["raw_flag"], bool)

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.iterdir")
    def test_detect_media_properties_with_frame_detection(
        self, mock_iterdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test media properties detection with actual frame detection."""
        # Setup mock for frame range detection
        mock_exists.return_value = True
        mock_files = []
        for filename in [
            "logc_2048x1556_shot_1010.exr",
            "logc_2048x1556_shot_1020.exr",
            "logc_2048x1556_shot_1030.exr",
        ]:
            mock_file = MagicMock()
            mock_file.name = filename
            mock_files.append(mock_file)
        mock_iterdir.return_value = mock_files

        properties = NukeMediaDetector.detect_media_properties(
            "/path/to/logc_2048x1556_shot_####.exr"
        )

        assert properties["first_frame"] == 1010
        assert properties["last_frame"] == 1030
        assert properties["width"] == 2048
        assert properties["height"] == 1556
        assert properties["colorspace"] == "logc3ei800"
        assert properties["raw_flag"] is False

    def test_sanitize_shot_name_basic(self) -> None:
        """Test basic shot name sanitization."""
        sanitized = NukeMediaDetector.sanitize_shot_name("shot_001")

        assert sanitized == "shot_001"

    def test_sanitize_shot_name_with_special_chars(self) -> None:
        """Test shot name sanitization with special characters."""
        # Implementation preserves hyphens but replaces other special chars
        test_cases = [
            ("shot-001", "shot-001"),  # Hyphen preserved
            ("shot/001", "shot_001"),
            ("shot\\001", "shot_001"),
            ("shot 001", "shot_001"),
            ("shot.001", "shot_001"),
            ("shot@001", "shot_001"),
            ("shot#001", "shot_001"),
            ("shot$001", "shot_001"),
            ("shot%001", "shot_001"),
            ("shot^001", "shot_001"),
            ("shot&001", "shot_001"),
            ("shot*001", "shot_001"),
            ("shot(001)", "shot_001_"),
            ("shot[001]", "shot_001_"),
            ("shot{001}", "shot_001_"),
        ]

        for original, expected in test_cases:
            sanitized = NukeMediaDetector.sanitize_shot_name(original)
            assert sanitized == expected

    def test_sanitize_shot_name_preserves_valid_chars(self) -> None:
        """Test shot name sanitization preserves valid characters."""
        valid_name = "Shot_001_v02-final"
        sanitized = NukeMediaDetector.sanitize_shot_name(valid_name)

        # Should preserve alphanumeric, underscore, and hyphen
        assert "Shot" in sanitized
        assert "001" in sanitized
        assert "v02" in sanitized
        assert "_" in sanitized

    def test_sanitize_shot_name_empty(self) -> None:
        """Test shot name sanitization with empty string."""
        sanitized = NukeMediaDetector.sanitize_shot_name("")

        assert sanitized == ""

    def test_sanitize_shot_name_unicode(self) -> None:
        """Test shot name sanitization with unicode characters."""
        unicode_name = "shot_001_ñ_ü_é"
        sanitized = NukeMediaDetector.sanitize_shot_name(unicode_name)

        # Implementation preserves unicode chars because \w includes them
        assert sanitized == "shot_001_ñ_ü_é"
        assert "ñ" in sanitized
        assert "ü" in sanitized
        assert "é" in sanitized

    def test_colorspace_detection_case_insensitive(self) -> None:
        """Test that colorspace detection is case insensitive."""
        test_cases = [
            ("/path/LIN_plate.exr", "linear", True),
            ("/path/LINEAR_plate.exr", "linear", True),
            ("/path/LOGC_plate.exr", "logc3ei800", False),
            ("/path/ALEXA_plate.exr", "logc3ei800", False),
            ("/path/REC709_plate.exr", "rec709", False),
            ("/path/SRGB_plate.exr", "sRGB", False),
        ]

        for path, expected_colorspace, expected_raw in test_cases:
            colorspace, raw_flag = NukeMediaDetector.detect_colorspace(path)
            assert colorspace == expected_colorspace
            assert raw_flag == expected_raw

    def test_resolution_detection_regex_variations(self) -> None:
        """Test resolution detection with various regex patterns."""
        test_cases = [
            # Standard format
            ("/path/1920x1080.exr", 1920, 1080),
            # With underscores
            ("/path/1920_1080.exr", 1920, 1080),
            # Mixed in filename
            ("/shot_1920x1080_v001.exr", 1920, 1080),
            ("/shot_1920_1080_v001.exr", 1920, 1080),
            # Multiple patterns (should match first)
            ("/shot_1920x1080_2048x1556.exr", 1920, 1080),
        ]

        for path, expected_width, expected_height in test_cases:
            width, height = NukeMediaDetector.detect_resolution(path)
            assert width == expected_width
            assert height == expected_height
