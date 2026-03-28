"""Tests for file discovery utilities.

Tests cover:
- safe_mkdir(): Directory creation with error handling
- find_mov_file_for_path(): MOV file discovery in version directories
- discover_plate_directories(): Plate directory pattern matching
"""

from __future__ import annotations

from pathlib import Path

import pytest

from discovery.file_discovery import (
    discover_plate_directories,
    find_mov_file_for_path,
    safe_mkdir,
)


class TestSafeMkdir:
    """Tests for safe_mkdir()."""

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        """Creates nested directories with parents=True."""
        nested = tmp_path / "a" / "b" / "c" / "d"

        result = safe_mkdir(nested)

        assert result is True
        assert nested.exists()

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Accepts string path argument."""
        new_dir = str(tmp_path / "string_path_dir")

        result = safe_mkdir(new_dir)

        assert result is True
        assert Path(new_dir).exists()


class TestFindMovFileForPath:
    """Tests for find_mov_file_for_path()."""

    def test_finds_mov_in_version_directory(self, tmp_path: Path) -> None:
        """Finds MOV file in sibling mov/ directory."""
        # Create structure: .../v001/exr/file.exr and .../v001/mov/file.mov
        version_dir = tmp_path / "publish" / "v001"
        exr_dir = version_dir / "exr"
        mov_dir = version_dir / "mov"

        exr_dir.mkdir(parents=True)
        mov_dir.mkdir()

        thumbnail = exr_dir / "thumbnail.exr"
        thumbnail.touch()
        mov_file = mov_dir / "movie.mov"
        mov_file.touch()

        result = find_mov_file_for_path(thumbnail)

        assert result is not None
        assert result.name == "movie.mov"

    def test_returns_none_no_version_directory(self, tmp_path: Path) -> None:
        """Returns None when no version directory found."""
        flat_dir = tmp_path / "flat"
        flat_dir.mkdir()
        thumbnail = flat_dir / "file.exr"
        thumbnail.touch()

        result = find_mov_file_for_path(thumbnail)

        assert result is None

    def test_returns_none_no_mov_directory(self, tmp_path: Path) -> None:
        """Returns None when mov/ directory doesn't exist."""
        version_dir = tmp_path / "v001"
        exr_dir = version_dir / "exr"
        exr_dir.mkdir(parents=True)

        thumbnail = exr_dir / "file.exr"
        thumbnail.touch()

        result = find_mov_file_for_path(thumbnail)

        assert result is None

    def test_returns_none_no_mov_files(self, tmp_path: Path) -> None:
        """Returns None when mov/ directory exists but is empty."""
        version_dir = tmp_path / "v001"
        exr_dir = version_dir / "exr"
        mov_dir = version_dir / "mov"

        exr_dir.mkdir(parents=True)
        mov_dir.mkdir()

        thumbnail = exr_dir / "file.exr"
        thumbnail.touch()

        result = find_mov_file_for_path(thumbnail)

        assert result is None

    def test_handles_uppercase_mov_extension(self, tmp_path: Path) -> None:
        """Finds files with .MOV extension."""
        version_dir = tmp_path / "v001"
        exr_dir = version_dir / "exr"
        mov_dir = version_dir / "mov"

        exr_dir.mkdir(parents=True)
        mov_dir.mkdir()

        thumbnail = exr_dir / "file.exr"
        thumbnail.touch()
        mov_file = mov_dir / "file.MOV"
        mov_file.touch()

        result = find_mov_file_for_path(thumbnail)

        assert result is not None
        assert result.name == "file.MOV"

    def test_returns_first_mov_sorted(self, tmp_path: Path) -> None:
        """Returns first MOV file when multiple exist (sorted)."""
        version_dir = tmp_path / "v001"
        exr_dir = version_dir / "exr"
        mov_dir = version_dir / "mov"

        exr_dir.mkdir(parents=True)
        mov_dir.mkdir()

        thumbnail = exr_dir / "file.exr"
        thumbnail.touch()

        # Create multiple MOV files
        (mov_dir / "b_second.mov").touch()
        (mov_dir / "a_first.mov").touch()
        (mov_dir / "c_third.mov").touch()

        result = find_mov_file_for_path(thumbnail)

        assert result is not None
        assert result.name == "a_first.mov"  # Sorted alphabetically


class TestDiscoverPlateDirectories:
    """Tests for discover_plate_directories()."""

    def test_discovers_fg_plates(self, tmp_path: Path) -> None:
        """Discovers FG## directories."""
        (tmp_path / "FG01").mkdir()
        (tmp_path / "FG02").mkdir()

        result = discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert "FG01" in plate_names
        assert "FG02" in plate_names

    def test_discovers_bg_plates(self, tmp_path: Path) -> None:
        """Discovers BG## directories."""
        (tmp_path / "BG01").mkdir()

        result = discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert "BG01" in plate_names

    @pytest.mark.parametrize("plate_name", ["EL01", "COMP01", "PL01", "FG99", "BG42"])
    def test_discovers_all_plate_types(self, tmp_path: Path, plate_name: str) -> None:
        """Discovers all standard plate types."""
        (tmp_path / plate_name).mkdir()

        result = discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert plate_name in plate_names

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Matches plate names case-insensitively."""
        (tmp_path / "bg01").mkdir()
        (tmp_path / "BG02").mkdir()
        (tmp_path / "Bg03").mkdir()

        result = discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert len(plate_names) == 3
        assert "bg01" in plate_names
        assert "BG02" in plate_names
        assert "Bg03" in plate_names

    def test_skips_non_plate_directories(self, tmp_path: Path) -> None:
        """Skips directories that don't match plate patterns."""
        (tmp_path / "FG01").mkdir()  # Valid
        (tmp_path / "reference").mkdir()  # Invalid
        (tmp_path / "backup").mkdir()  # Invalid
        (tmp_path / "notes").mkdir()  # Invalid

        result = discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert len(plate_names) == 1
        assert "FG01" in plate_names
        assert "reference" not in plate_names

    def test_skips_files(self, tmp_path: Path) -> None:
        """Only considers directories, not files."""
        (tmp_path / "FG01").mkdir()  # Directory
        (tmp_path / "FG02").touch()  # File - should be skipped

        result = discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert "FG01" in plate_names
        assert "FG02" not in plate_names

    def test_returns_empty_for_nonexistent_path(self, tmp_path: Path) -> None:
        """Returns empty list for non-existent path."""
        nonexistent = tmp_path / "does_not_exist"

        result = discover_plate_directories(nonexistent)

        assert result == []

    def test_sorted_by_priority(self, tmp_path: Path) -> None:
        """Results are sorted by priority (lower number = higher priority)."""
        # Create plates with different priorities
        (tmp_path / "FG01").mkdir()  # Typically highest priority
        (tmp_path / "BG01").mkdir()  # Typically second priority
        (tmp_path / "EL01").mkdir()  # Typically lower priority

        result = discover_plate_directories(tmp_path)

        # Verify sorted order - actual priorities from Config.TURNOVER_PLATE_PRIORITY
        # The first result should have the lowest priority number
        if len(result) > 1:
            priorities = [priority for _, priority in result]
            assert priorities == sorted(priorities)

    def test_returns_tuples_with_priority(self, tmp_path: Path) -> None:
        """Returns list of (plate_name, priority) tuples."""
        (tmp_path / "FG01").mkdir()

        result = discover_plate_directories(tmp_path)

        assert len(result) == 1
        plate_name, priority = result[0]
        assert plate_name == "FG01"
        assert isinstance(priority, (int, float))

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Accepts string path argument."""
        (tmp_path / "BG01").mkdir()

        result = discover_plate_directories(str(tmp_path))

        plate_names = [name for name, _ in result]
        assert "BG01" in plate_names
