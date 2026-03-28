"""Unit tests for version_utils.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from version_utils import VersionUtils


class TestGetLatestVersionPath:
    """Tests for VersionUtils.get_latest_version_path()."""

    def test_get_latest_version_path_returns_highest(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path returns the highest version directory."""
        # Create version directories in non-sorted order
        (tmp_path / "v001").mkdir()
        (tmp_path / "v003").mkdir()
        (tmp_path / "v002").mkdir()

        result = VersionUtils.get_latest_version_path(tmp_path)

        assert result is not None
        assert result == tmp_path / "v003"
        assert result.is_dir()

    def test_get_latest_version_path_empty_dir(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path returns None for empty directory."""
        result = VersionUtils.get_latest_version_path(tmp_path)

        assert result is None

    def test_get_latest_version_path_no_version_dirs(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path returns None when no version dirs exist."""
        # Create non-version directories
        (tmp_path / "data").mkdir()
        (tmp_path / "cache").mkdir()
        (tmp_path / "regular_folder").mkdir()

        result = VersionUtils.get_latest_version_path(tmp_path)

        assert result is None

    def test_get_latest_version_path_with_string_input(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path accepts string paths."""
        (tmp_path / "v001").mkdir()
        (tmp_path / "v002").mkdir()

        result = VersionUtils.get_latest_version_path(str(tmp_path))

        assert result is not None
        assert result == tmp_path / "v002"

    def test_get_latest_version_path_with_path_input(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path accepts Path objects."""
        (tmp_path / "v001").mkdir()
        (tmp_path / "v005").mkdir()

        result = VersionUtils.get_latest_version_path(tmp_path)

        assert result is not None
        assert result == tmp_path / "v005"

    def test_get_latest_version_path_single_version(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path works with single version directory."""
        (tmp_path / "v001").mkdir()

        result = VersionUtils.get_latest_version_path(tmp_path)

        assert result is not None
        assert result == tmp_path / "v001"

    def test_get_latest_version_path_mixed_content(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path ignores non-version directories."""
        (tmp_path / "v001").mkdir()
        (tmp_path / "v003").mkdir()
        (tmp_path / "cache").mkdir()
        (tmp_path / "v002").mkdir()
        (tmp_path / "readme.txt").touch()

        result = VersionUtils.get_latest_version_path(tmp_path)

        assert result is not None
        assert result == tmp_path / "v003"

    def test_get_latest_version_path_nonexistent_path(self) -> None:
        """Test that get_latest_version_path handles nonexistent paths gracefully."""
        result = VersionUtils.get_latest_version_path("/nonexistent/path/to/directory")

        assert result is None

    def test_get_latest_version_path_returns_path_object(self, tmp_path: Path) -> None:
        """Test that get_latest_version_path returns a Path object."""
        (tmp_path / "v001").mkdir()

        result = VersionUtils.get_latest_version_path(tmp_path)

        assert isinstance(result, Path)


class TestVersionCacheExpiry:
    """Tests for version cache TTL behavior."""

    def test_version_cache_expires_after_ttl(self, tmp_path: Path) -> None:
        """Cached v001 -> v002 created -> lookup after TTL returns v002."""
        VersionUtils.clear_version_cache()

        (tmp_path / "v001").mkdir()

        with (
            patch("version_utils.time.time") as mock_vtime,
            patch("paths.validators.time.time") as mock_ptime,
        ):
            mock_vtime.return_value = 1000.0
            mock_ptime.return_value = 1000.0

            result1 = VersionUtils.find_version_directories(tmp_path)
            assert len(result1) == 1
            assert result1[0] == (1, "v001")

            # Create v002
            (tmp_path / "v002").mkdir()

            # Before TTL expires - still cached
            mock_vtime.return_value = 1050.0
            mock_ptime.return_value = 1050.0
            result2 = VersionUtils.find_version_directories(tmp_path)
            assert len(result2) == 1  # Still cached

            # After TTL expires (60s)
            mock_vtime.return_value = 1061.0
            mock_ptime.return_value = 1061.0
            result3 = VersionUtils.find_version_directories(tmp_path)
            assert len(result3) == 2
            assert result3[1] == (2, "v002")

        VersionUtils.clear_version_cache()
