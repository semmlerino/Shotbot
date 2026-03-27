"""Tests for frame_range_extractor.py."""

from __future__ import annotations

from pathlib import Path

from discovery.frame_range_extractor import detect_frame_range


class TestDetectFrameRange:
    """Tests for detect_frame_range function."""

    def test_detect_frame_range_basic(self, tmp_path: Path) -> None:
        """Detect frame range from files like frame.1001.exr through frame.1100.exr."""
        # Create frame files
        (tmp_path / "frame.1001.exr").write_text("fake exr")
        (tmp_path / "frame.1050.exr").write_text("fake exr")
        (tmp_path / "frame.1100.exr").write_text("fake exr")

        result = detect_frame_range(tmp_path, extension="exr")
        assert result == (1001, 1100)

    def test_detect_frame_range_default_when_empty(self, tmp_path: Path) -> None:
        """Return (1001, 1100) when directory is empty."""
        result = detect_frame_range(tmp_path, extension="exr")
        assert result == (1001, 1100)

    def test_detect_frame_range_default_when_no_matching_files(
        self, tmp_path: Path
    ) -> None:
        """Return (1001, 1100) when no files match the frame pattern."""
        # Create files that don't match the frame pattern
        (tmp_path / "image.png").write_text("fake png")
        (tmp_path / "data.txt").write_text("fake data")

        result = detect_frame_range(tmp_path, extension="exr")
        assert result == (1001, 1100)

    def test_detect_frame_range_custom_extension(self, tmp_path: Path) -> None:
        """Detect frame range with custom extension like dpx."""
        (tmp_path / "shot.0001.dpx").write_text("fake dpx")
        (tmp_path / "shot.0100.dpx").write_text("fake dpx")
        (tmp_path / "shot.0250.dpx").write_text("fake dpx")

        result = detect_frame_range(tmp_path, extension="dpx")
        assert result == (1, 250)

    def test_detect_frame_range_single_file(self, tmp_path: Path) -> None:
        """Single file returns (frame, frame) where min == max."""
        (tmp_path / "plate.5000.exr").write_text("fake exr")

        result = detect_frame_range(tmp_path, extension="exr")
        assert result == (5000, 5000)

    def test_detect_frame_range_ignores_non_files(self, tmp_path: Path) -> None:
        """Ignore subdirectories and only scan files."""
        (tmp_path / "frame.1001.exr").write_text("fake exr")
        (tmp_path / "frame.1100.exr").write_text("fake exr")

        # Create a subdirectory with matching name
        subdir = tmp_path / "frame.1050.exr"
        subdir.mkdir()

        result = detect_frame_range(tmp_path, extension="exr")
        # Should only find the two files, not the directory
        assert result == (1001, 1100)

    def test_detect_frame_range_case_insensitive_extension(
        self, tmp_path: Path
    ) -> None:
        """Extension matching is case-insensitive."""
        (tmp_path / "frame.1001.EXR").write_text("fake exr")
        (tmp_path / "frame.1050.Exr").write_text("fake exr")
        (tmp_path / "frame.1100.exr").write_text("fake exr")

        result = detect_frame_range(tmp_path, extension="exr")
        assert result == (1001, 1100)

    def test_detect_frame_range_various_padding(self, tmp_path: Path) -> None:
        """Handle frame numbers with different padding (4+ digits)."""
        (tmp_path / "plate.0001.exr").write_text("fake exr")
        (tmp_path / "plate.00100.exr").write_text("fake exr")
        (tmp_path / "plate.001000.exr").write_text("fake exr")

        result = detect_frame_range(tmp_path, extension="exr")
        assert result == (1, 1000)

    def test_detect_frame_range_nonexistent_directory(self) -> None:
        """Handle nonexistent directory gracefully, return default."""
        nonexistent = Path("/nonexistent/path/does/not/exist")
        result = detect_frame_range(nonexistent, extension="exr")
        assert result == (1001, 1100)

    def test_detect_frame_range_filters_wrong_extension(self, tmp_path: Path) -> None:
        """Ignore files with different extensions."""
        (tmp_path / "frame.1001.exr").write_text("fake exr")
        (tmp_path / "frame.1050.dpx").write_text("fake dpx")
        (tmp_path / "frame.1100.jpg").write_text("fake jpg")

        result = detect_frame_range(tmp_path, extension="exr")
        # Should only find the .exr file
        assert result == (1001, 1001)

    def test_detect_frame_range_requires_4plus_digit_frame_numbers(
        self, tmp_path: Path
    ) -> None:
        """Only match frame numbers with 4+ digits."""
        (tmp_path / "frame.1.exr").write_text("fake exr")
        (tmp_path / "frame.12.exr").write_text("fake exr")
        (tmp_path / "frame.123.exr").write_text("fake exr")
        (tmp_path / "frame.1000.exr").write_text("fake exr")
        (tmp_path / "frame.1001.exr").write_text("fake exr")

        result = detect_frame_range(tmp_path, extension="exr")
        # Should only match 1000 and 1001
        assert result == (1000, 1001)
