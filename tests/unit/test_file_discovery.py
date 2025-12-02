"""Tests for FileDiscovery utilities.

Tests cover:
- safe_mkdir(): Directory creation with error handling
- find_mov_file_for_path(): MOV file discovery in version directories
- discover_plate_directories(): Plate directory pattern matching
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def file_discovery():
    """Import FileDiscovery at runtime to avoid circular import."""
    from file_discovery import FileDiscovery

    return FileDiscovery


class TestSafeMkdir:
    """Tests for FileDiscovery.safe_mkdir()."""

    def test_creates_directory_successfully(self, tmp_path: Path, file_discovery: type) -> None:
        """Successfully creates directory and returns True."""
        new_dir = tmp_path / "new_directory"

        result = file_discovery.safe_mkdir(new_dir)

        assert result is True
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_creates_nested_directories(self, tmp_path: Path, file_discovery: type) -> None:
        """Creates nested directories with parents=True."""
        nested = tmp_path / "a" / "b" / "c" / "d"

        result = file_discovery.safe_mkdir(nested)

        assert result is True
        assert nested.exists()

    def test_returns_true_for_existing_directory(self, tmp_path: Path, file_discovery: type) -> None:
        """Returns True for already existing directory (exist_ok=True)."""
        existing = tmp_path / "existing"
        existing.mkdir()

        result = file_discovery.safe_mkdir(existing)

        assert result is True

    def test_returns_false_on_empty_path(self, file_discovery: type) -> None:
        """Returns False for empty path."""
        result = file_discovery.safe_mkdir("")

        assert result is False

    def test_accepts_string_path(self, tmp_path: Path, file_discovery: type) -> None:
        """Accepts string path argument."""
        new_dir = str(tmp_path / "string_path_dir")

        result = file_discovery.safe_mkdir(new_dir)

        assert result is True
        assert Path(new_dir).exists()


class TestFindMovFileForPath:
    """Tests for FileDiscovery.find_mov_file_for_path()."""

    def test_finds_mov_in_version_directory(self, tmp_path: Path, file_discovery: type) -> None:
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

        result = file_discovery.find_mov_file_for_path(thumbnail)

        assert result is not None
        assert result.name == "movie.mov"

    def test_returns_none_no_version_directory(self, tmp_path: Path, file_discovery: type) -> None:
        """Returns None when no version directory found."""
        flat_dir = tmp_path / "flat"
        flat_dir.mkdir()
        thumbnail = flat_dir / "file.exr"
        thumbnail.touch()

        result = file_discovery.find_mov_file_for_path(thumbnail)

        assert result is None

    def test_returns_none_no_mov_directory(self, tmp_path: Path, file_discovery: type) -> None:
        """Returns None when mov/ directory doesn't exist."""
        version_dir = tmp_path / "v001"
        exr_dir = version_dir / "exr"
        exr_dir.mkdir(parents=True)

        thumbnail = exr_dir / "file.exr"
        thumbnail.touch()

        result = file_discovery.find_mov_file_for_path(thumbnail)

        assert result is None

    def test_returns_none_no_mov_files(self, tmp_path: Path, file_discovery: type) -> None:
        """Returns None when mov/ directory exists but is empty."""
        version_dir = tmp_path / "v001"
        exr_dir = version_dir / "exr"
        mov_dir = version_dir / "mov"

        exr_dir.mkdir(parents=True)
        mov_dir.mkdir()

        thumbnail = exr_dir / "file.exr"
        thumbnail.touch()

        result = file_discovery.find_mov_file_for_path(thumbnail)

        assert result is None

    def test_handles_uppercase_mov_extension(self, tmp_path: Path, file_discovery: type) -> None:
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

        result = file_discovery.find_mov_file_for_path(thumbnail)

        assert result is not None
        assert result.name == "file.MOV"

    def test_returns_first_mov_sorted(self, tmp_path: Path, file_discovery: type) -> None:
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

        result = file_discovery.find_mov_file_for_path(thumbnail)

        assert result is not None
        assert result.name == "a_first.mov"  # Sorted alphabetically


class TestDiscoverPlateDirectories:
    """Tests for FileDiscovery.discover_plate_directories()."""

    def test_discovers_fg_plates(self, tmp_path: Path, file_discovery: type) -> None:
        """Discovers FG## directories."""
        (tmp_path / "FG01").mkdir()
        (tmp_path / "FG02").mkdir()

        result = file_discovery.discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert "FG01" in plate_names
        assert "FG02" in plate_names

    def test_discovers_bg_plates(self, tmp_path: Path, file_discovery: type) -> None:
        """Discovers BG## directories."""
        (tmp_path / "BG01").mkdir()

        result = file_discovery.discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert "BG01" in plate_names

    @pytest.mark.parametrize("plate_name", ["EL01", "COMP01", "PL01", "FG99", "BG42"])
    def test_discovers_all_plate_types(
        self, tmp_path: Path, plate_name: str, file_discovery: type
    ) -> None:
        """Discovers all standard plate types."""
        (tmp_path / plate_name).mkdir()

        result = file_discovery.discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert plate_name in plate_names

    def test_case_insensitive_matching(self, tmp_path: Path, file_discovery: type) -> None:
        """Matches plate names case-insensitively."""
        (tmp_path / "bg01").mkdir()
        (tmp_path / "BG02").mkdir()
        (tmp_path / "Bg03").mkdir()

        result = file_discovery.discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert len(plate_names) == 3
        assert "bg01" in plate_names
        assert "BG02" in plate_names
        assert "Bg03" in plate_names

    def test_skips_non_plate_directories(self, tmp_path: Path, file_discovery: type) -> None:
        """Skips directories that don't match plate patterns."""
        (tmp_path / "FG01").mkdir()  # Valid
        (tmp_path / "reference").mkdir()  # Invalid
        (tmp_path / "backup").mkdir()  # Invalid
        (tmp_path / "notes").mkdir()  # Invalid

        result = file_discovery.discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert len(plate_names) == 1
        assert "FG01" in plate_names
        assert "reference" not in plate_names

    def test_skips_files(self, tmp_path: Path, file_discovery: type) -> None:
        """Only considers directories, not files."""
        (tmp_path / "FG01").mkdir()  # Directory
        (tmp_path / "FG02").touch()  # File - should be skipped

        result = file_discovery.discover_plate_directories(tmp_path)

        plate_names = [name for name, _ in result]
        assert "FG01" in plate_names
        assert "FG02" not in plate_names

    def test_returns_empty_for_nonexistent_path(
        self, tmp_path: Path, file_discovery: type
    ) -> None:
        """Returns empty list for non-existent path."""
        nonexistent = tmp_path / "does_not_exist"

        result = file_discovery.discover_plate_directories(nonexistent)

        assert result == []

    def test_sorted_by_priority(self, tmp_path: Path, file_discovery: type) -> None:
        """Results are sorted by priority (lower number = higher priority)."""
        # Create plates with different priorities
        (tmp_path / "FG01").mkdir()  # Typically highest priority
        (tmp_path / "BG01").mkdir()  # Typically second priority
        (tmp_path / "EL01").mkdir()  # Typically lower priority

        result = file_discovery.discover_plate_directories(tmp_path)

        # Verify sorted order - actual priorities from Config.TURNOVER_PLATE_PRIORITY
        # The first result should have the lowest priority number
        if len(result) > 1:
            priorities = [priority for _, priority in result]
            assert priorities == sorted(priorities)

    def test_returns_tuples_with_priority(self, tmp_path: Path, file_discovery: type) -> None:
        """Returns list of (plate_name, priority) tuples."""
        (tmp_path / "FG01").mkdir()

        result = file_discovery.discover_plate_directories(tmp_path)

        assert len(result) == 1
        plate_name, priority = result[0]
        assert plate_name == "FG01"
        assert isinstance(priority, (int, float))

    def test_accepts_string_path(self, tmp_path: Path, file_discovery: type) -> None:
        """Accepts string path argument."""
        (tmp_path / "BG01").mkdir()

        result = file_discovery.discover_plate_directories(str(tmp_path))

        plate_names = [name for name, _ in result]
        assert "BG01" in plate_names
