"""Unit tests for VersionHandlingMixin."""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path
from unittest.mock import patch

# Third-party imports
import pytest

# Local application imports
from version_mixin import VersionHandlingMixin


class ConcreteVersionClass(VersionHandlingMixin):
    """Concrete class for testing the mixin."""

    def __init__(self) -> None:
        """Initialize test class."""
        super().__init__()


class CustomPatternClass(VersionHandlingMixin):
    """Class with custom version pattern."""

    VERSION_PATTERN = re.compile(r"\.v(\d{4})\.")

    def __init__(self) -> None:
        """Initialize test class."""
        super().__init__()


class FallbackEnabledClass(VersionHandlingMixin):
    """Class with fallback patterns enabled."""

    def __init__(self) -> None:
        """Initialize test class."""
        super().__init__()
        self.use_fallback_patterns = True


class TestVersionExtraction:
    """Test version extraction functionality."""

    def test_extract_with_default_pattern(self) -> None:
        """Test version extraction using default pattern."""
        obj = ConcreteVersionClass()

        # Standard _v### format
        assert obj._extract_version(Path("file_v001.ma")) == 1
        assert obj._extract_version(Path("scene_v042.3de")) == 42
        assert obj._extract_version(Path("render_v999.exr")) == 999

        # String paths work too
        assert obj._extract_version("file_v123.txt") == 123

    def test_extract_with_custom_pattern_string(self) -> None:
        """Test extraction with custom string pattern."""
        obj = ConcreteVersionClass()
        pattern = r"\.v(\d{4})\."

        assert obj._extract_version("file.v0001.exr", pattern) == 1
        assert obj._extract_version("plate.v1234.dpx", pattern) == 1234
        assert obj._extract_version("file_v001.ma", pattern) is None  # Wrong pattern

    def test_extract_with_custom_pattern_compiled(self) -> None:
        """Test extraction with compiled pattern."""
        obj = ConcreteVersionClass()
        pattern = re.compile(r"_ver(\d{2})")

        assert obj._extract_version("file_ver01.txt", pattern) == 1
        assert obj._extract_version("scene_ver99.ma", pattern) == 99
        assert obj._extract_version("file_v001.ma", pattern) is None

    def test_extract_with_class_override(self) -> None:
        """Test extraction with class-level pattern override."""
        obj = CustomPatternClass()

        # Should use class pattern
        assert obj._extract_version("file.v0001.exr") == 1
        assert obj._extract_version("file.v9999.exr") == 9999

        # Default pattern shouldn't work
        assert obj._extract_version("file_v001.ma") is None

    def test_extract_no_version_found(self) -> None:
        """Test extraction when no version is found."""
        obj = ConcreteVersionClass()

        assert obj._extract_version(Path("file_without_version.txt")) is None
        assert obj._extract_version("no_version_here.ma") is None
        assert obj._extract_version("v_but_no_numbers.txt") is None

    def test_extract_with_fallback_patterns(self) -> None:
        """Test extraction with fallback patterns enabled."""
        obj = FallbackEnabledClass()

        # Primary pattern
        assert obj._extract_version("file_v001.ma") == 1

        # Fallback patterns
        assert obj._extract_version("file.v001.ma") == 1  # .v### format
        assert obj._extract_version("file_ver001.ma") == 1  # _ver### format
        assert obj._extract_version("plate.0001.exr") == 1  # .####. format
        assert obj._extract_version("render_001") == 1  # _### at end

    def test_extract_logging(self) -> None:
        """Test that extraction logs appropriately."""
        obj = ConcreteVersionClass()

        with patch.object(obj.logger, "debug") as mock_debug:
            version = obj._extract_version("file_v042.ma")
            assert version == 42
            mock_debug.assert_called_once()
            assert "Extracted version 42" in mock_debug.call_args[0][0]

    def test_extract_with_multiple_versions(self) -> None:
        """Test extraction with multiple version patterns in filename."""
        obj = ConcreteVersionClass()

        # Should extract first match
        assert obj._extract_version("file_v001_v002.ma") == 1
        assert (
            obj._extract_version("text_v001_file_v002.txt") == 1
        )  # Fixed pattern match


class TestFindLatestByVersion:
    """Test finding latest file by version."""

    def test_find_latest_basic(self) -> None:
        """Test finding latest from versioned files."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v005.ma"),
            Path("file_v003.ma"),
            Path("file_v002.ma"),
        ]

        latest = obj._find_latest_by_version(files)
        assert latest == Path("file_v005.ma")

    @pytest.mark.parametrize(
        "files",
        [
            [],
            [Path("file_without_version.ma"), Path("another_file.txt")],
        ],
        ids=["empty_list", "no_versioned_files"],
    )
    def test_find_latest_returns_none(self, files: list[Path]) -> None:
        """Test that None is returned when no versioned files."""
        obj = ConcreteVersionClass()
        assert obj._find_latest_by_version(files) is None

    def test_find_latest_no_versioned_files_logging(self) -> None:
        """Test logging when no versioned files found."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_without_version.ma"),
            Path("another_file.txt"),
        ]

        with patch.object(obj.logger, "debug") as mock_debug:
            result = obj._find_latest_by_version(files)
            assert result is None
            mock_debug.assert_called()
            assert "No versioned files found" in mock_debug.call_args[0][0]

    def test_find_latest_mixed_files(self) -> None:
        """Test with mix of versioned and unversioned files."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("no_version.ma"),
            Path("file_v003.ma"),
            Path("also_no_version.txt"),
        ]

        latest = obj._find_latest_by_version(files)
        assert latest == Path("file_v003.ma")

    def test_find_latest_custom_pattern(self) -> None:
        """Test finding latest with custom pattern."""
        obj = ConcreteVersionClass()
        files = [
            Path("file.v0001.exr"),
            Path("file.v0010.exr"),
            Path("file.v0005.exr"),
        ]

        pattern = r"\.v(\d{4})\."
        latest = obj._find_latest_by_version(files, pattern)
        assert latest == Path("file.v0010.exr")

    def test_find_latest_logging(self) -> None:
        """Test that finding latest logs appropriately."""
        obj = ConcreteVersionClass()
        files = [Path("file_v001.ma"), Path("file_v002.ma")]

        with patch.object(obj.logger, "info") as mock_info:
            latest = obj._find_latest_by_version(files)
            assert latest == Path("file_v002.ma")
            mock_info.assert_called_once()
            assert (
                "Found latest version: file_v002.ma (v002)" in mock_info.call_args[0][0]
            )


class TestFindEarliestByVersion:
    """Test finding earliest file by version."""

    def test_find_earliest_basic(self) -> None:
        """Test finding earliest from versioned files."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v005.ma"),
            Path("file_v001.ma"),
            Path("file_v003.ma"),
        ]

        earliest = obj._find_earliest_by_version(files)
        assert earliest == Path("file_v001.ma")

    @pytest.mark.parametrize(
        "files",
        [
            [],
            [Path("no_version.ma")],
        ],
        ids=["empty_list", "no_versioned"],
    )
    def test_find_earliest_returns_none(self, files: list[Path]) -> None:
        """Test that None is returned when no versioned files."""
        obj = ConcreteVersionClass()
        assert obj._find_earliest_by_version(files) is None

    def test_find_earliest_logging(self) -> None:
        """Test that finding earliest logs appropriately."""
        obj = ConcreteVersionClass()
        files = [Path("file_v002.ma"), Path("file_v001.ma")]

        with patch.object(obj.logger, "info") as mock_info:
            earliest = obj._find_earliest_by_version(files)
            assert earliest == Path("file_v001.ma")
            mock_info.assert_called_once()
            assert (
                "Found earliest version: file_v001.ma (v001)"
                in mock_info.call_args[0][0]
            )


class TestSortFilesByVersion:
    """Test version-based file sorting."""

    def test_sort_ascending(self) -> None:
        """Test sorting files in ascending order."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v003.ma"),
            Path("file_v001.ma"),
            Path("file_v002.ma"),
        ]

        sorted_files = obj._sort_files_by_version(files)
        assert sorted_files == [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("file_v003.ma"),
        ]

    def test_sort_descending(self) -> None:
        """Test sorting files in descending order."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v003.ma"),
            Path("file_v001.ma"),
            Path("file_v002.ma"),
        ]

        sorted_files = obj._sort_files_by_version(files, reverse=True)
        assert sorted_files == [
            Path("file_v003.ma"),
            Path("file_v002.ma"),
            Path("file_v001.ma"),
        ]

    def test_sort_with_unversioned(self) -> None:
        """Test sorting with unversioned files."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v002.ma"),
            Path("no_version.ma"),
            Path("file_v001.ma"),
            Path("another.txt"),
        ]

        sorted_files = obj._sort_files_by_version(files)
        # Versioned files first, then unversioned alphabetically
        assert sorted_files == [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("another.txt"),
            Path("no_version.ma"),
        ]

    def test_sort_empty_list(self) -> None:
        """Test sorting empty list."""
        obj = ConcreteVersionClass()
        assert obj._sort_files_by_version([]) == []

    def test_sort_all_unversioned(self) -> None:
        """Test sorting when all files are unversioned."""
        obj = ConcreteVersionClass()
        files = [
            Path("zebra.txt"),
            Path("apple.txt"),
            Path("banana.txt"),
        ]

        sorted_files = obj._sort_files_by_version(files)
        # Should be alphabetically sorted
        assert sorted_files == [
            Path("apple.txt"),
            Path("banana.txt"),
            Path("zebra.txt"),
        ]


class TestGetVersionRange:
    """Test version range extraction."""

    def test_get_range_basic(self) -> None:
        """Test getting version range from files."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v005.ma"),
            Path("file_v003.ma"),
        ]

        min_v, max_v = obj._get_version_range(files)
        assert min_v == 1
        assert max_v == 5

    def test_get_range_single_file(self) -> None:
        """Test range with single file."""
        obj = ConcreteVersionClass()
        files = [Path("file_v042.ma")]

        min_v, max_v = obj._get_version_range(files)
        assert min_v == 42
        assert max_v == 42

    def test_get_range_no_versioned(self) -> None:
        """Test range with no versioned files."""
        obj = ConcreteVersionClass()
        files = [Path("no_version.ma")]

        result = obj._get_version_range(files)
        assert result is None  # Implementation returns None, not tuple

    def test_get_range_empty_list(self) -> None:
        """Test range with empty list."""
        obj = ConcreteVersionClass()
        result = obj._get_version_range([])
        assert result is None  # Implementation returns None, not tuple

    def test_get_range_mixed_files(self) -> None:
        """Test range with mixed versioned/unversioned files."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v010.ma"),
            Path("no_version.ma"),
            Path("file_v020.ma"),
        ]

        min_v, max_v = obj._get_version_range(files)
        assert min_v == 10
        assert max_v == 20


class TestFilterByVersionRange:
    """Test version range filtering."""

    def test_filter_basic_range(self) -> None:
        """Test filtering files by version range."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("file_v003.ma"),
            Path("file_v004.ma"),
            Path("file_v005.ma"),
        ]

        filtered = obj._filter_by_version_range(files, min_version=2, max_version=4)
        assert len(filtered) == 3
        assert Path("file_v002.ma") in filtered
        assert Path("file_v003.ma") in filtered
        assert Path("file_v004.ma") in filtered

    def test_filter_min_only(self) -> None:
        """Test filtering with only minimum version."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("file_v003.ma"),
        ]

        filtered = obj._filter_by_version_range(files, min_version=2)
        assert len(filtered) == 2
        assert Path("file_v002.ma") in filtered
        assert Path("file_v003.ma") in filtered

    def test_filter_max_only(self) -> None:
        """Test filtering with only maximum version."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("file_v003.ma"),
        ]

        filtered = obj._filter_by_version_range(files, max_version=2)
        assert len(filtered) == 2
        assert Path("file_v001.ma") in filtered
        assert Path("file_v002.ma") in filtered

    def test_filter_no_range(self) -> None:
        """Test filtering with no range specified."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
        ]

        # Should return all files
        filtered = obj._filter_by_version_range(files)
        assert filtered == files

    def test_filter_empty_list(self) -> None:
        """Test filtering empty list."""
        obj = ConcreteVersionClass()
        assert obj._filter_by_version_range([]) == []

    def test_filter_excludes_unversioned(self) -> None:
        """Test that unversioned files are excluded."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("no_version.ma"),
            Path("file_v002.ma"),
        ]

        filtered = obj._filter_by_version_range(files, min_version=1)
        assert len(filtered) == 2
        assert Path("no_version.ma") not in filtered


class TestGroupFilesByVersion:
    """Test grouping files by version number."""

    def test_group_by_version_basic(self) -> None:
        """Test basic grouping by version number."""
        obj = ConcreteVersionClass()
        files = [
            Path("shot_010_v001.ma"),
            Path("shot_020_v001.ma"),
            Path("shot_010_v002.ma"),
            Path("shot_020_v002.ma"),
        ]

        groups = obj._group_files_by_version(files)
        assert len(groups) == 2
        assert 1 in groups
        assert 2 in groups
        assert len(groups[1]) == 2  # Two v001 files
        assert len(groups[2]) == 2  # Two v002 files

    def test_group_by_version_mixed(self) -> None:
        """Test grouping with different version numbers."""
        obj = ConcreteVersionClass()
        files = [
            Path("char_model_v001.ma"),
            Path("char_model_v002.ma"),
            Path("char_rig_v001.ma"),
            Path("env_layout_v003.ma"),
        ]

        groups = obj._group_files_by_version(files)
        assert len(groups) == 3
        assert 1 in groups
        assert 2 in groups
        assert 3 in groups
        assert len(groups[1]) == 2  # char_model_v001 and char_rig_v001
        assert len(groups[2]) == 1  # char_model_v002
        assert len(groups[3]) == 1  # env_layout_v003

    def test_group_excludes_unversioned(self) -> None:
        """Test that unversioned files are excluded."""
        obj = ConcreteVersionClass()
        files = [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("no_version.ma"),
            Path("another_no_version.txt"),
        ]

        groups = obj._group_files_by_version(files)
        assert len(groups) == 2  # Only v001 and v002
        assert 1 in groups
        assert 2 in groups
        assert len(groups[1]) == 1
        assert len(groups[2]) == 1

    def test_group_empty_list(self) -> None:
        """Test grouping empty list."""
        obj = ConcreteVersionClass()
        groups = obj._group_files_by_version([])
        assert groups == {}

    def test_group_single_file(self) -> None:
        """Test grouping single file."""
        obj = ConcreteVersionClass()
        files = [Path("file_v001.ma")]

        groups = obj._group_files_by_version(files)
        assert len(groups) == 1
        assert 1 in groups
        assert groups[1] == [Path("file_v001.ma")]

    def test_group_preserves_path_objects(self) -> None:
        """Test that grouping preserves Path objects."""
        obj = ConcreteVersionClass()
        files = [Path("/full/path/file_v001.ma")]

        groups = obj._group_files_by_version(files)
        assert 1 in groups
        assert isinstance(groups[1][0], Path)
        assert groups[1][0] == Path("/full/path/file_v001.ma")


class TestClassInheritance:
    """Test class inheritance and pattern overrides."""

    def test_pattern_override_inheritance(self) -> None:
        """Test that pattern overrides work correctly."""
        obj = CustomPatternClass()

        # Custom pattern should work
        assert obj._extract_version("file.v0001.exr") == 1

        # Default pattern should not work
        assert obj._extract_version("file_v001.ma") is None

    def test_fallback_patterns_attribute(self) -> None:
        """Test fallback patterns attribute."""
        obj = FallbackEnabledClass()

        # Should use fallback patterns
        assert obj._extract_version("file.v001.ma") == 1  # Fallback pattern
        assert obj._extract_version("file_ver001.ma") == 1  # Another fallback

    def test_mixin_with_logging(self) -> None:
        """Test that mixin includes logging."""
        obj = ConcreteVersionClass()
        assert hasattr(obj, "logger")
        assert obj.logger is not None


