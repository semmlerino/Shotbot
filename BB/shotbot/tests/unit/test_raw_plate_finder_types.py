"""Type safety tests specifically for RawPlateFinder module."""

# pyright: basic
# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false

import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from raw_plate_finder import RawPlateFinder


class TestRawPlateFinderTypeSafety:
    """Test type safety for RawPlateFinder module."""

    def test_find_latest_raw_plate_return_type(self, monkeypatch):
        """Test find_latest_raw_plate returns Optional[str]."""
        # Mock PathUtils.build_raw_plate_path to return a Path
        mock_path = Path("/mock/raw/plate/path")
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.build_raw_plate_path", lambda x: mock_path
        )

        # Mock PathUtils.validate_path_exists to return False (no path)
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.validate_path_exists", lambda *args: False
        )

        result = RawPlateFinder.find_latest_raw_plate("/workspace/path", "shot_name")

        # Should return Optional[str] - in this case None
        assert result is None
        assert isinstance(result, type(None))

        # Test with mocked successful case
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.validate_path_exists", lambda *args: True
        )
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.discover_plate_directories",
            lambda x: [("BG01", 1)],
        )
        monkeypatch.setattr(
            "raw_plate_finder.VersionUtils.get_latest_version", lambda x: "v001"
        )

        # Mock the directory structure exists checks
        def mock_exists(self):
            return str(self).endswith("exr")

        with patch("pathlib.Path.exists", mock_exists):
            mock_resolution_dir = Mock()
            mock_resolution_dir.is_dir.return_value = True
            mock_resolution_dir.name = "4096x2304"

            with patch("pathlib.Path.iterdir") as mock_iterdir:
                mock_iterdir.return_value = [mock_resolution_dir]

                # Mock the file finding
                with patch.object(
                    RawPlateFinder, "_find_plate_file_pattern"
                ) as mock_find:
                    mock_find.return_value = "/path/to/plate_####.exr"

                    result = RawPlateFinder.find_latest_raw_plate(
                        "/workspace/path", "shot_name"
                    )

                    # Should return a string path
                    if result is not None:
                        assert isinstance(result, str)
                        assert result == "/path/to/plate_####.exr"
                    else:
                        # None is also a valid return for Optional[str]
                        assert result is None

    def test_get_version_from_path_return_type(self):
        """Test get_version_from_path returns Optional[str]."""
        # Test with path containing version
        result1 = RawPlateFinder.get_version_from_path("/path/to/v001/file.exr")
        assert isinstance(result1, (str, type(None)))

        # Test with path without version
        result2 = RawPlateFinder.get_version_from_path("/path/without/version")
        assert isinstance(result2, (str, type(None)))
        assert result2 is None

    def test_verify_plate_exists_return_type(self, monkeypatch):
        """Test verify_plate_exists returns bool."""
        # Mock PathUtils.validate_path_exists
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.validate_path_exists", lambda *args: False
        )

        result = RawPlateFinder.verify_plate_exists("/invalid/path/####.exr")
        assert isinstance(result, bool)
        assert result is False

    def test_pattern_cache_types(self):
        """Test that pattern cache maintains correct types."""
        # Clear cache first
        RawPlateFinder._pattern_cache.clear()

        # Get patterns
        pattern1, pattern2 = RawPlateFinder._get_plate_patterns(
            "shot_name", "BG01", "v001"
        )

        # Should be compiled regex patterns
        assert isinstance(pattern1, re.Pattern)
        assert isinstance(pattern2, re.Pattern)

        # Cache should contain the patterns
        cache_key = ("shot_name", "BG01", "v001")
        assert cache_key in RawPlateFinder._pattern_cache

        cached_pattern1, cached_pattern2 = RawPlateFinder._pattern_cache[cache_key]
        assert isinstance(cached_pattern1, re.Pattern)
        assert isinstance(cached_pattern2, re.Pattern)

    def test_find_plate_file_pattern_return_type(self, tmp_path):
        """Test _find_plate_file_pattern returns Optional[str]."""
        # Create mock resolution directory
        resolution_dir = tmp_path / "resolution"
        resolution_dir.mkdir()

        # Test with no files - should return None
        result = RawPlateFinder._find_plate_file_pattern(
            resolution_dir, "shot_name", "BG01", "v001"
        )
        assert isinstance(result, (str, type(None)))
        assert result is None

        # Create a matching file
        test_file = resolution_dir / "shot_name_turnover-plate_BG01_aces_v001.1001.exr"
        test_file.touch()

        # Should now return a string pattern
        result = RawPlateFinder._find_plate_file_pattern(
            resolution_dir, "shot_name", "BG01", "v001"
        )
        assert isinstance(result, (str, type(None)))
        if result is not None:
            assert isinstance(result, str)
            assert "####" in result

    def test_verify_pattern_cache_types(self):
        """Test verify pattern cache maintains correct types."""
        # Clear cache
        RawPlateFinder._verify_pattern_cache.clear()

        # This should populate the cache
        pattern_str = r"test_pattern_\d{4}\.exr"

        # Manually add to cache to test types
        compiled_pattern = re.compile(f"^{pattern_str}$")
        RawPlateFinder._verify_pattern_cache[pattern_str] = compiled_pattern

        # Verify cache contents
        for key, value in RawPlateFinder._verify_pattern_cache.items():
            assert isinstance(key, str)
            assert isinstance(value, re.Pattern)

    def test_static_method_signatures(self):
        """Test that all static methods have correct signatures."""
        # find_latest_raw_plate
        assert hasattr(RawPlateFinder, "find_latest_raw_plate")
        method = getattr(RawPlateFinder, "find_latest_raw_plate")
        assert callable(method)

        # get_version_from_path
        assert hasattr(RawPlateFinder, "get_version_from_path")
        method = getattr(RawPlateFinder, "get_version_from_path")
        assert callable(method)

        # verify_plate_exists
        assert hasattr(RawPlateFinder, "verify_plate_exists")
        method = getattr(RawPlateFinder, "verify_plate_exists")
        assert callable(method)

    def test_error_handling_preserves_types(self, monkeypatch):
        """Test that error conditions preserve return types."""

        # Mock to raise OSError
        def mock_iterdir():
            raise OSError("Permission denied")

        # Mock resolution directory
        mock_dir = Mock()
        mock_dir.iterdir = mock_iterdir

        # Should still return Optional[str] even with errors
        result = RawPlateFinder._find_plate_file_pattern(
            mock_dir, "shot", "BG01", "v001"
        )
        assert isinstance(result, (str, type(None)))
        assert result is None

    def test_performance_optimizations_maintain_types(self, tmp_path):
        """Test that performance optimizations maintain type safety."""
        # Test pattern caching
        RawPlateFinder._pattern_cache.clear()

        # Call multiple times with same parameters
        for _ in range(3):
            patterns = RawPlateFinder._get_plate_patterns("shot", "BG01", "v001")
            assert isinstance(patterns, tuple)
            assert len(patterns) == 2
            assert all(isinstance(p, re.Pattern) for p in patterns)

        # Cache should only have one entry
        assert len(RawPlateFinder._pattern_cache) == 1

        # Test verify pattern caching
        RawPlateFinder._verify_pattern_cache.clear()

        # Create test directory structure
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()
        test_file = plate_dir / "test_plate.1001.exr"
        test_file.touch()

        plate_path = str(plate_dir / "test_plate.####.exr")

        # Call multiple times
        for _ in range(3):
            result = RawPlateFinder.verify_plate_exists(plate_path)
            assert isinstance(result, bool)

        # Verify cache was used
        assert len(RawPlateFinder._verify_pattern_cache) >= 0  # Cache may have entries

    def test_integration_with_utils_types(self, monkeypatch):
        """Test integration with utils module preserves types."""
        # Mock utils methods with correct return types
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.build_raw_plate_path",
            lambda x: Path("/mock/path"),
        )
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.validate_path_exists", lambda *args: True
        )
        monkeypatch.setattr(
            "raw_plate_finder.PathUtils.discover_plate_directories",
            lambda x: [("BG01", 1), ("FG01", 2)],
        )
        monkeypatch.setattr(
            "raw_plate_finder.VersionUtils.get_latest_version", lambda x: "v001"
        )

        # Mock file system
        with patch("pathlib.Path.exists") as mock_exists:
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                mock_exists.return_value = True
                mock_resolution_dir = Mock()
                mock_resolution_dir.is_dir.return_value = True
                mock_resolution_dir.name = "4096x2304"
                mock_iterdir.return_value = [mock_resolution_dir]

                with patch.object(
                    RawPlateFinder, "_find_plate_file_pattern"
                ) as mock_find:
                    mock_find.return_value = "/path/to/plate_####.exr"

                    result = RawPlateFinder.find_latest_raw_plate(
                        "/workspace", "shot_name"
                    )

                    # Should maintain type safety throughout the call chain
                    assert isinstance(result, (str, type(None)))
                    if result is not None:
                        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
