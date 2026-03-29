"""Unit tests for VersionHandlingMixin."""

from __future__ import annotations

# Standard library imports
import logging
import re
from pathlib import Path

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

    def test_extract_logging(self, caplog) -> None:
        """Test that extraction logs appropriately."""
        obj = ConcreteVersionClass()

        with caplog.at_level(logging.DEBUG, logger="version_mixin"):
            version = obj._extract_version("file_v042.ma")
        assert version == 42
        assert any("Extracted version 42" in r.message for r in caplog.records)

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
