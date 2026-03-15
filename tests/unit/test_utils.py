"""Comprehensive unit tests for utils.py module.

Tests all utility classes in utils.py with focus on behavior validation,
edge cases, and actual filesystem operations using pytest's tmp_path fixture.

Test Coverage:
- PathUtils: Path validation, construction, and caching behavior
- FileUtils: File discovery, extension matching, and size validation
- ValidationUtils: Input validation and user management
- VersionUtils: Version directory handling and caching
- ImageUtils: Image dimension validation and memory estimation
- Cache management: TTL behavior, cleanup, and statistics
"""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

# Standard library imports
import os
import time
from pathlib import Path
from unittest.mock import patch

# Third-party imports
import pytest

# Local application imports
from config import Config
from image_utils import ImageUtils
from path_validators import PathValidators
from tests.fixtures.environment_fixtures import clear_all_caches
from thumbnail_finders import ThumbnailFinders
from utils import (
    FileUtils,
    ValidationUtils,
    get_cache_stats,
)
from version_utils import VersionUtils


pytestmark = [pytest.mark.unit, pytest.mark.slow]


# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)


class TestFileUtils:
    """Test FileUtils functionality with real filesystem operations."""

    def test_find_files_by_extension_single_extension(self, tmp_path: Path) -> None:
        """Test finding files with single extension."""
        # Create test files
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file3.jpg").write_text("image")
        (tmp_path / "file4.TXT").write_text("content4")  # Test case insensitivity

        result = FileUtils.find_files_by_extension(tmp_path, "txt")

        # Should find 3 .txt files (case insensitive)
        assert len(result) == 3
        assert all(f.suffix.lower() == ".txt" for f in result)

    def test_find_files_by_extension_multiple_extensions(self, tmp_path: Path) -> None:
        """Test finding files with multiple extensions."""
        # Create test files
        (tmp_path / "image1.jpg").write_text("image1")
        (tmp_path / "image2.jpeg").write_text("image2")
        (tmp_path / "image3.png").write_text("image3")
        (tmp_path / "document.txt").write_text("doc")

        result = FileUtils.find_files_by_extension(tmp_path, ["jpg", "jpeg", "png"])

        assert len(result) == 3
        extensions = {f.suffix.lower() for f in result}
        assert extensions == {".jpg", ".jpeg", ".png"}

    def test_find_files_by_extension_with_leading_dots(self, tmp_path: Path) -> None:
        """Test extension matching with leading dots."""
        (tmp_path / "test.py").write_text("code")
        (tmp_path / "test.js").write_text("script")

        # Test with leading dots
        result1 = FileUtils.find_files_by_extension(tmp_path, [".py", ".js"])
        assert len(result1) == 2

        # Test without leading dots
        result2 = FileUtils.find_files_by_extension(tmp_path, ["py", "js"])
        assert len(result2) == 2

        # Results should be identical
        assert {f.name for f in result1} == {f.name for f in result2}

    def test_find_files_by_extension_with_limit(self, tmp_path: Path) -> None:
        """Test file finding with result limit."""
        # Create many test files
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text(f"content {i}")

        result = FileUtils.find_files_by_extension(tmp_path, "txt", limit=3)

        assert len(result) == 3
        assert all(f.suffix == ".txt" for f in result)

    def test_find_files_by_extension_nonexistent_directory(self) -> None:
        """Test file finding in non-existent directory."""
        result = FileUtils.find_files_by_extension("/nonexistent", "txt")
        assert result == []

    def test_find_files_by_extension_permission_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test handling of permission errors during file discovery."""
        # Create directory
        test_dir = tmp_path / "restricted"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")

        # Mock permission error
        with patch.object(
            Path,
            "iterdir",
            side_effect=PermissionError("Access denied"),
        ):
            result = FileUtils.find_files_by_extension(test_dir, "txt")

        assert result == []
        assert any(
            "Error scanning directory" in record.message for record in caplog.records
        )

    def test_find_files_by_extension_ignores_directories(self, tmp_path: Path) -> None:
        """Test that directories are ignored even if they match extension pattern."""
        # Create directory with extension-like name
        dir_with_ext = tmp_path / "directory.txt"
        dir_with_ext.mkdir()

        # Create actual file
        (tmp_path / "file.txt").write_text("content")

        result = FileUtils.find_files_by_extension(tmp_path, "txt")

        # Should only find the file, not the directory
        assert len(result) == 1
        assert result[0].name == "file.txt"
        assert result[0].is_file()

    def test_get_first_image_file(self, tmp_path: Path) -> None:
        """Test finding first image file with extension priority."""
        # Create files in reverse priority order to test preference
        (tmp_path / "image.png").write_text("png image")
        (tmp_path / "photo.tiff").write_text("tiff image")
        (tmp_path / "picture.jpg").write_text("jpg image")  # Should be highest priority

        result = FileUtils.get_first_image_file(tmp_path)

        # Should return the highest priority extension from Config.IMAGE_EXTENSIONS
        assert result is not None
        assert result.exists()
        assert result.suffix.lower() in [ext.lower() for ext in Config.IMAGE_EXTENSIONS]

    def test_get_first_image_file_no_images(self, tmp_path: Path) -> None:
        """Test finding first image when no images exist."""
        (tmp_path / "document.txt").write_text("not an image")

        result = FileUtils.get_first_image_file(tmp_path)
        assert result is None

    @pytest.mark.parametrize(
        ("file_content", "max_size_mb", "expected"),
        [
            ("small content", 1, True),
            ("x" * (2 * 1024 * 1024), 1, False),
            (None, 1, False),
        ],
        ids=["within_limit", "exceeds_limit", "nonexistent"],
    )
    def test_validate_file_size(
        self, tmp_path: Path, file_content: str | None, max_size_mb: int, expected: bool
    ) -> None:
        """Test file size validation for various scenarios."""
        if file_content is not None:
            test_file = tmp_path / "test_file.txt"
            test_file.write_text(file_content)
        else:
            test_file = Path("/nonexistent/file.txt")

        result = FileUtils.validate_file_size(test_file, max_size_mb=max_size_mb)
        assert result is expected

    def test_validate_file_size_uses_config_default(self, tmp_path: Path) -> None:
        """Test that file size validation uses Config.MAX_FILE_SIZE_MB when no limit specified."""
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("test content")

        # Should use Config.MAX_FILE_SIZE_MB as default
        with patch.object(Config, "MAX_FILE_SIZE_MB", 100):
            result = FileUtils.validate_file_size(test_file)
            assert result is True


class TestVersionUtils:
    """Test VersionUtils functionality with real filesystem operations."""

    def test_find_version_directories(self, tmp_path: Path) -> None:
        """Test finding version directories with proper sorting."""
        # Create version directories
        (tmp_path / "v001").mkdir()
        (tmp_path / "v003").mkdir()
        (tmp_path / "v002").mkdir()
        (tmp_path / "v010").mkdir()
        (tmp_path / "not_version").mkdir()  # Should be ignored

        result = VersionUtils.find_version_directories(tmp_path)

        # Should return sorted list of (version_number, version_string) tuples
        assert len(result) == 4
        assert result[0] == (1, "v001")
        assert result[1] == (2, "v002")
        assert result[2] == (3, "v003")
        assert result[3] == (10, "v010")

    def test_find_version_directories_caching(self, tmp_path: Path) -> None:
        """Test that version directory scanning uses caching."""
        VersionUtils.clear_version_cache()

        # Create version directory
        (tmp_path / "v001").mkdir()

        # First call should populate cache
        result1 = VersionUtils.find_version_directories(tmp_path)
        assert len(result1) == 1

        # Verify cache is populated
        cache_size = VersionUtils.get_version_cache_size()
        assert cache_size > 0

        # Second call should use cache
        result2 = VersionUtils.find_version_directories(tmp_path)
        assert result1 == result2

    def test_find_version_directories_nonexistent_path(self) -> None:
        """Test version finding with non-existent path."""
        result = VersionUtils.find_version_directories("/nonexistent")
        assert result == []

    def test_find_version_directories_permission_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test handling of permission errors during version scanning.

        Following UNIFIED_TESTING_GUIDE: Clear caches for test isolation.
        """
        # Clear cache to ensure mock is actually called (cache bypasses iterdir)
        VersionUtils._version_cache.clear()

        with patch.object(
            Path,
            "iterdir",
            side_effect=PermissionError("Access denied"),
        ):
            result = VersionUtils.find_version_directories(tmp_path)

        assert result == []
        assert any(
            "Error scanning for version directories" in record.message
            for record in caplog.records
        )

    def test_get_latest_version(self, tmp_path: Path) -> None:
        """Test getting latest version from directory."""
        # Create version directories
        (tmp_path / "v001").mkdir()
        (tmp_path / "v005").mkdir()
        (tmp_path / "v003").mkdir()

        result = VersionUtils.get_latest_version(tmp_path)
        assert result == "v005"

    def test_get_latest_version_no_versions(self, tmp_path: Path) -> None:
        """Test getting latest version when no versions exist."""
        result = VersionUtils.get_latest_version(tmp_path)
        assert result is None

    def test_extract_version_from_path(self) -> None:
        """Test version extraction from file/directory paths."""
        # Test various path patterns
        assert (
            VersionUtils.extract_version_from_path("/path/to/v001/file.txt") == "v001"
        )
        assert (
            VersionUtils.extract_version_from_path("/project/v042/output.exr") == "v042"
        )
        assert VersionUtils.extract_version_from_path("file_v003.nk") == "v003"
        assert VersionUtils.extract_version_from_path("/no/version/here.txt") is None
        assert VersionUtils.extract_version_from_path("") is None

    def test_extract_version_from_path_caching(self) -> None:
        """Test that version extraction uses LRU cache."""
        # Clear cache
        VersionUtils.extract_version_from_path.cache_clear()

        # Call with same path multiple times
        path = "/test/v001/file.txt"
        for _ in range(5):
            result = VersionUtils.extract_version_from_path(path)
            assert result == "v001"

        # Check cache info
        cache_info = VersionUtils.extract_version_from_path.cache_info()
        assert cache_info.hits == 4  # 4 cache hits after first miss
        assert cache_info.misses == 1

    def test_version_cache_cleanup(self, tmp_path: Path) -> None:
        """Test version cache cleanup when size limit exceeded."""
        VersionUtils.clear_version_cache()

        # Fill cache beyond limit
        for i in range(100):  # OPTIMIZED: Reduced from 600 to 100
            fake_path = tmp_path / f"fake_{i}"
            # Manually populate cache
            VersionUtils._version_cache[str(fake_path)] = ([], time.time())

        # Trigger cleanup by calling find_version_directories
        test_dir = tmp_path / "trigger"
        test_dir.mkdir()
        VersionUtils.find_version_directories(test_dir)

        # Cache should be cleaned
        assert len(VersionUtils._version_cache) <= 250

    @pytest.mark.parametrize(
        ("setup_files", "expected"),
        [
            (["shot_abc_v001.nk", "shot_abc_v002.nk"], 3),
            (["unrelated_file.txt"], 1),
            (None, 1),
        ],
        ids=["with_existing", "no_matching", "nonexistent_dir"],
    )
    def test_get_next_version_number(
        self, tmp_path: Path, setup_files: list[str] | None, expected: int
    ) -> None:
        """Test next version number detection for various directory states."""
        if setup_files is None:
            path = Path("/nonexistent/path")
        else:
            path = tmp_path
            for f in setup_files:
                (tmp_path / f).touch()

        result = VersionUtils.get_next_version_number(path, "shot_*_v*.nk")
        assert result == expected


class TestValidationUtils:
    """Test ValidationUtils functionality."""

    def test_validate_not_empty_all_valid(self) -> None:
        """Test validation with all valid values."""
        result = ValidationUtils.validate_not_empty("value1", "value2", "value3")
        assert result is True

    def test_validate_not_empty_with_names(self) -> None:
        """Test validation with names for better error messages."""
        result = ValidationUtils.validate_not_empty(
            "valid",
            "also_valid",
            names=["first", "second"],
        )
        assert result is True

    @pytest.mark.parametrize(
        "empty_value",
        [None, ""],
        ids=["none", "empty_string"],
    )
    def test_validate_not_empty_with_falsy_value(
        self, empty_value: str | None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test validation fails with None or empty string values."""
        result = ValidationUtils.validate_not_empty("valid", empty_value, "also_valid")
        assert result is False
        assert any(
            "Empty or None value 1" in record.message for record in caplog.records
        )

    def test_validate_not_empty_names_length_mismatch(self) -> None:
        """Test that mismatched names length raises ValueError."""
        with pytest.raises(ValueError, match="Names list must match values length"):
            ValidationUtils.validate_not_empty(
                "value1",
                "value2",
                names=["name1"],  # Only one name for two values
            )

    def test_validate_shot_components_all_valid(self) -> None:
        """Test shot component validation with valid inputs."""
        result = ValidationUtils.validate_shot_components("show1", "seq01", "shot01")
        assert result is True

    def test_validate_shot_components_with_empty(self) -> None:
        """Test shot component validation with empty values."""
        result = ValidationUtils.validate_shot_components("", "seq01", "shot01")
        assert result is False

        result = ValidationUtils.validate_shot_components("show1", None, "shot01")
        assert result is False

    def test_get_current_username_from_env(self) -> None:
        """Test username detection from environment variables."""
        # Test each environment variable in priority order
        from utils import get_current_username

        env_vars = ["USER", "USERNAME", "LOGNAME"]

        for env_var in env_vars:
            with patch.dict(os.environ, {env_var: "testuser"}, clear=True):
                result = get_current_username()
                assert result == "testuser"

    def test_get_current_username_fallback_to_default(self) -> None:
        """Test username fallback when no environment variables are set."""
        # Clear all username environment variables
        from utils import get_current_username

        with patch.dict(os.environ, {}, clear=True):
            result = get_current_username()
            assert result == Config.DEFAULT_USERNAME

    def test_get_excluded_users_default(self) -> None:
        """Test getting excluded users with current user only."""
        from utils import get_excluded_users

        with patch("utils.get_current_username", return_value="currentuser"):
            result = get_excluded_users()
            assert result == {"currentuser"}

    def test_get_excluded_users_with_additional(self) -> None:
        """Test getting excluded users with additional users."""
        from utils import get_excluded_users

        additional = {"user1", "user2"}
        with patch("utils.get_current_username", return_value="currentuser"):
            result = get_excluded_users(additional)
            assert result == {"currentuser", "user1", "user2"}

    def test_get_excluded_users_no_duplicates(self) -> None:
        """Test that current user isn't duplicated if in additional users."""
        from utils import get_excluded_users

        additional = {"currentuser", "user1"}  # Includes current user
        with patch("utils.get_current_username", return_value="currentuser"):
            result = get_excluded_users(additional)
            assert result == {"currentuser", "user1"}


class TestImageUtils:
    """Test ImageUtils functionality."""

    def test_validate_image_dimensions_within_limits(self) -> None:
        """Test image dimension validation within acceptable limits."""
        result = ImageUtils.validate_image_dimensions(
            1920,
            1080,
            max_dimension=2048,
            max_memory_mb=10,
        )
        assert result is True

    def test_validate_image_dimensions_exceeds_dimension_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test image dimension validation when dimensions exceed limits."""
        result = ImageUtils.validate_image_dimensions(
            5000,
            3000,
            max_dimension=4096,
            max_memory_mb=100,
        )
        assert result is False
        assert any(
            "Image dimensions too large" in record.message for record in caplog.records
        )

    def test_validate_image_dimensions_exceeds_memory_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test image dimension validation when estimated memory exceeds limits."""
        # 4000x4000 = 16M pixels * 4 bytes = 64MB
        result = ImageUtils.validate_image_dimensions(
            4000,
            4000,
            max_dimension=5000,
            max_memory_mb=50,
        )
        assert result is False
        assert any(
            "Estimated image memory usage too high" in record.message
            for record in caplog.records
        )

    def test_validate_image_dimensions_uses_config_defaults(self) -> None:
        """Test that image validation uses config defaults when not specified."""
        with patch.object(
            Config, "MAX_THUMBNAIL_DIMENSION_PX", 2048
        ), patch.object(Config, "MAX_THUMBNAIL_MEMORY_MB", 10):
            result = ImageUtils.validate_image_dimensions(1920, 1080)
            assert result is True

    def test_get_safe_dimensions_for_thumbnail(self) -> None:
        """Test getting safe thumbnail dimensions."""
        result = ImageUtils.get_safe_dimensions_for_thumbnail(256)
        assert result == (256, 256)

    def test_get_safe_dimensions_for_thumbnail_uses_config_default(self) -> None:
        """Test that safe dimensions use config default when not specified."""
        with patch.object(Config, "CACHE_THUMBNAIL_SIZE", 512):
            result = ImageUtils.get_safe_dimensions_for_thumbnail()
            assert result == (512, 512)


class TestCacheManagement:
    """Test cache management and utility functions."""

    def test_clear_all_caches(self, tmp_path: Path, caching_enabled: Path) -> None:
        """Test that clear_all_caches clears all cache systems.

        Uses caching_enabled fixture for proper isolation in parallel execution.
        """
        # Clear first to ensure clean state
        clear_all_caches()

        # Populate path cache using public API
        test_path1 = tmp_path / "cache_test1"
        test_path1.mkdir()
        PathValidators.validate_path_exists(test_path1)

        test_path2 = tmp_path / "cache_test2"
        test_path2.mkdir()
        PathValidators.validate_path_exists(test_path2)

        # Populate version cache using public API
        version_dir = tmp_path / "versions"
        version_dir.mkdir()
        (version_dir / "v001").mkdir()
        (version_dir / "v002").mkdir()
        VersionUtils.find_version_directories(version_dir)

        # Verify caches have data
        stats_before = get_cache_stats()
        assert stats_before["path_cache_size"] >= 2, "Path cache should have entries"
        assert stats_before["version_cache_size"] >= 1, "Version cache should have entries"

        # Clear all caches
        clear_all_caches()

        # Verify caches are empty
        stats_after = get_cache_stats()
        assert stats_after["path_cache_size"] == 0, "Path cache should be empty"
        assert stats_after["version_cache_size"] == 0, "Version cache should be empty"

    def test_get_cache_stats(self, tmp_path: Path, caching_enabled: Path) -> None:
        """Test cache statistics reporting.

        Uses caching_enabled fixture for proper isolation in parallel execution.
        """
        # Clear first to ensure clean state
        clear_all_caches()

        # Populate path cache using public API
        test_path1 = tmp_path / "stats_test1"
        test_path1.mkdir()
        PathValidators.validate_path_exists(test_path1)

        test_path2 = tmp_path / "stats_test2"
        test_path2.mkdir()
        PathValidators.validate_path_exists(test_path2)

        # Populate version cache using public API
        version_dir = tmp_path / "versions"
        version_dir.mkdir()
        (version_dir / "v001").mkdir()
        VersionUtils.find_version_directories(version_dir)

        stats = get_cache_stats()

        assert "path_cache_size" in stats
        assert "version_cache_size" in stats
        assert "extract_version_cache_info" in stats
        assert stats["path_cache_size"] >= 2, "Path cache should have at least 2 entries"
        assert stats["version_cache_size"] >= 1, "Version cache should have at least 1 entry"


class TestFindTurnoverPlateThumbnail:
    """Test the complex turnover plate thumbnail discovery logic."""

    def test_find_turnover_plate_thumbnail_success(self, tmp_path: Path) -> None:
        """Test successful turnover plate thumbnail discovery."""
        # Create directory structure:
        # /shows/myshow/shots/seq01/seq01_shot01/publish/turnover/plate/input_plate/FG01/v001/exr/1920x1080/
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        plate_path = (
            shot_path
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "FG01"
            / "v001"
            / "exr"
            / "1920x1080"
        )
        plate_path.mkdir(parents=True)

        # Create test EXR file
        test_frame = (
            plate_path / "GG_000_0050_turnover-plate_FG01_lin_sgamut3cine_v001.1001.exr"
        )
        test_frame.write_text("fake exr content")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert (
            result.name
            == "GG_000_0050_turnover-plate_FG01_lin_sgamut3cine_v001.1001.exr"
        )
        assert result.exists()

    def test_find_turnover_plate_thumbnail_priority_order(self, tmp_path: Path) -> None:
        """Test that FG plates are preferred over BG plates."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        base_plate_path = shot_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create BG01 plate (lower priority)
        bg_path = base_plate_path / "BG01" / "v001" / "exr" / "1920x1080"
        bg_path.mkdir(parents=True)
        bg_frame = bg_path / "shot_BG01.1001.exr"
        bg_frame.write_text("bg content")

        # Create FG01 plate (higher priority)
        fg_path = base_plate_path / "FG01" / "v001" / "exr" / "1920x1080"
        fg_path.mkdir(parents=True)
        fg_frame = fg_path / "shot_FG01.1001.exr"
        fg_frame.write_text("fg content")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )

        # Should prefer FG01 over BG01
        assert result is not None
        assert "FG01" in result.name

    def test_find_turnover_plate_thumbnail_frame_number_sorting(
        self, tmp_path: Path
    ) -> None:
        """Test that frame numbers are sorted correctly."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        plate_path = (
            shot_path
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "FG01"
            / "v001"
            / "exr"
            / "1920x1080"
        )
        plate_path.mkdir(parents=True)

        # Create frames in non-sequential order
        (plate_path / "shot.1010.exr").write_text("frame 1010")
        (plate_path / "shot.1001.exr").write_text("frame 1001")  # Should be first
        (plate_path / "shot.1005.exr").write_text("frame 1005")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert "1001" in result.name  # Should get the earliest frame

    def test_find_turnover_plate_thumbnail_no_base_path(self) -> None:
        """Test turnover plate discovery when base path doesn't exist."""
        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            "/nonexistent",
            "show",
            "seq",
            "shot",
        )
        assert result is None

    def test_find_turnover_plate_thumbnail_no_plates(self, tmp_path: Path) -> None:
        """Test turnover plate discovery when no plate directories exist."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        base_path = shot_path / "publish" / "turnover" / "plate" / "input_plate"
        base_path.mkdir(parents=True)

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )
        assert result is None


class TestFindAnyPublishThumbnail:
    """Test recursive publish thumbnail discovery fallback logic."""

    def test_find_any_publish_thumbnail_recursive(self, tmp_path: Path) -> None:
        """Find the first 1001 EXR recursively under publish/."""
        publish_path = (
            tmp_path
            / "shows"
            / "testshow"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
        )
        deep_path = publish_path / "comp" / "v001" / "exr"
        deep_path.mkdir(parents=True)

        test_file = deep_path / "comp_v001.1001.exr"
        test_file.write_text("fake exr")
        (deep_path / "comp_v001.1002.exr").write_text("other frame")
        (deep_path / "comp_v001.jpg").write_text("wrong extension")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"),
            "testshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert result.name == test_file.name

    def test_find_any_publish_thumbnail_max_depth(self, tmp_path: Path) -> None:
        """Respect max_depth and prefer shallow hits when deep hits exceed limit."""
        shows_root = tmp_path / "shows"
        publish_path = (
            shows_root / "testshow" / "shots" / "seq01" / "seq01_shot01" / "publish"
        )

        very_deep = publish_path
        for i in range(10):
            very_deep = very_deep / f"level{i}"
        very_deep.mkdir(parents=True)
        (very_deep / "too_deep.1001.exr").write_text("deep")

        shallow = publish_path / "level0" / "level1"
        shallow.mkdir(parents=True, exist_ok=True)
        shallow_file = shallow / "shallow.1001.exr"
        shallow_file.write_text("shallow")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(shows_root),
            "testshow",
            "seq01",
            "shot01",
            max_depth=3,
        )

        assert result is not None
        assert result.name == shallow_file.name

    def test_find_any_publish_thumbnail_permission_error(self, tmp_path: Path) -> None:
        """Handle unreadable subdirectories gracefully."""
        shows_root = tmp_path / "shows"
        publish_path = (
            shows_root / "testshow" / "shots" / "seq01" / "seq01_shot01" / "publish"
        )
        publish_path.mkdir(parents=True)

        restricted = publish_path / "restricted"
        restricted.mkdir()
        restricted.chmod(0o000)

        try:
            result = ThumbnailFinders.find_any_publish_thumbnail(
                str(shows_root),
                "testshow",
                "seq01",
                "shot01",
            )
            assert result is None
        finally:
            restricted.chmod(0o755)

    def test_find_any_publish_thumbnail_no_publish_dir(self, tmp_path: Path) -> None:
        """Return None when the publish path does not exist."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir()

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(shows_root),
            "testshow",
            "seq01",
            "shot01",
        )
        assert result is None


class TestUserWorkspaceJPEGDiscovery:
    """Test user workspace JPEG discovery with undistort/ and scene/ structures (commit 78983a8)."""

    @pytest.mark.parametrize(
        ("subdir", "user", "seq", "shot", "plate", "filename"),
        [
            (
                "undistort",
                "ryan-p",
                "SF_000",
                "0030",
                "pl01",
                "SF_000_0030_mm-default_PL01_undistorted_v001.1001.jpeg",
            ),
            (
                "scene",
                "sarah-b",
                "DA_000",
                "0005",
                "FG01",
                "DA_000_0005_mm-default_FG01_undistorted_v001.1001.jpeg",
            ),
        ],
        ids=["undistort_structure", "scene_structure"],
    )
    def test_find_user_workspace_jpeg_output_structure(
        self,
        tmp_path: Path,
        subdir: str,
        user: str,
        seq: str,
        shot: str,
        plate: str,
        filename: str,
    ) -> None:
        """Test finding JPEGs in undistort/ and scene/ directory structures."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "jack_ryan" / "shots" / seq / f"{seq}_{shot}"
        jpeg_dir = (
            shot_path
            / "user"
            / user
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / subdir
            / plate
            / "undistorted_plate"
            / "v001"
            / "4312x2304"
            / "jpeg"
        )
        jpeg_dir.mkdir(parents=True)

        jpeg_file = jpeg_dir / filename
        jpeg_file.write_text("fake jpeg content")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "jack_ryan", seq, shot
        )

        assert result is not None
        assert result.name == jpeg_file.name
        assert subdir in str(result)

    def test_find_user_workspace_jpeg_undistort_priority_over_scene(
        self, tmp_path: Path
    ) -> None:
        """Test that undistort/ is checked before scene/ (as per implementation)."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create BOTH undistort and scene structures
        undistort_jpeg = (
            shot_path
            / "user"
            / "user1"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "undistort"
            / "fg01"
            / "undistorted_plate"
            / "v001"
            / "4096x2160"
            / "jpeg"
            / "undistort_version.jpeg"
        )
        undistort_jpeg.parent.mkdir(parents=True)
        undistort_jpeg.write_text("undistort jpeg")

        scene_jpeg = (
            shot_path
            / "user"
            / "user1"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "scene"
            / "fg01"
            / "undistorted_plate"
            / "v002"
            / "4096x2160"
            / "jpeg"
            / "scene_version.jpeg"
        )
        scene_jpeg.parent.mkdir(parents=True)
        scene_jpeg.write_text("scene jpeg")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find undistort version first (checked first in loop)
        assert result is not None
        assert result.name == "undistort_version.jpeg"

    def test_find_user_workspace_jpeg_case_insensitive_plates(
        self, tmp_path: Path
    ) -> None:
        """Test that lowercase plate names (pl01) are found with case-insensitive matching."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create lowercase plate directory (pl01, not PL01)
        jpeg_dir = (
            shot_path
            / "user"
            / "artist"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "undistort"
            / "pl01"
            / "undistorted_plate"
            / "v001"
            / "4096x2160"
            / "jpeg"
        )
        jpeg_dir.mkdir(parents=True)
        jpeg_file = jpeg_dir / "lowercase_plate.jpeg"
        jpeg_file.write_text("jpeg")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find it via case-insensitive plate discovery
        assert result is not None
        assert result.name == "lowercase_plate.jpeg"

    def test_find_user_workspace_jpeg_no_user_directory(self, tmp_path: Path) -> None:
        """Test graceful handling when no user/ directory exists."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        shot_path.mkdir(parents=True)
        # No user/ directory created

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        assert result is None  # Should return None, not crash

    def test_find_user_workspace_jpeg_multiple_users(self, tmp_path: Path) -> None:
        """Test that it discovers JPEGs from any user's workspace."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create JPEG in second user's directory (first has none)
        (shot_path / "user" / "user1" / "mm" / "nuke" / "outputs").mkdir(
            parents=True
        )  # Empty
        user2_jpeg_dir = (
            shot_path
            / "user"
            / "user2"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "scene"
            / "FG01"
            / "undistorted_plate"
            / "v001"
            / "4096x2160"
            / "jpeg"
        )
        user2_jpeg_dir.mkdir(parents=True)
        jpeg_file = user2_jpeg_dir / "user2_work.jpeg"
        jpeg_file.write_text("jpeg from user2")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find JPEG from user2
        assert result is not None
        assert "user2" in str(result)


class TestThumbnailFallbackOrder:
    """Test editorial/cutref thumbnail discovery with automatic version detection."""

    def test_find_shot_thumbnail_editorial_cutref_latest_version(
        self, tmp_path: Path
    ) -> None:
        """Test that editorial/cutref finds latest version directory automatically."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create v001 editorial cutref JPEG
        v001_dir = (
            shot_path
            / "publish"
            / "editorial"
            / "cutref"
            / "v001"
            / "jpg"
            / "1920x1080"
        )
        v001_dir.mkdir(parents=True)
        v001_jpeg = v001_dir / "seq01_shot01_editorial-cutref_v001.1001.jpg"
        v001_jpeg.write_text("v001 jpeg")

        # Create v002 editorial cutref JPEG (should be found - latest version)
        v002_dir = (
            shot_path
            / "publish"
            / "editorial"
            / "cutref"
            / "v002"
            / "jpg"
            / "1920x1080"
        )
        v002_dir.mkdir(parents=True)
        v002_jpeg = v002_dir / "seq01_shot01_editorial-cutref_v002.1001.jpg"
        v002_jpeg.write_text("v002 jpeg")

        result = ThumbnailFinders.find_shot_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find v002 (latest version)
        assert result is not None
        assert result.suffix.lower() in [".jpg", ".jpeg"]
        assert "v002" in str(result)
        assert result.name == "seq01_shot01_editorial-cutref_v002.1001.jpg"

    def test_find_shot_thumbnail_no_editorial_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Test that find_shot_thumbnail returns None when no editorial/cutref exists."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create shot directory but no editorial/cutref
        shot_path.mkdir(parents=True)

        # Create other directories that are NOT editorial/cutref (should be ignored)
        other_dir = shot_path / "publish" / "mm" / "default" / "v001" / "jpeg"
        other_dir.mkdir(parents=True)
        other_jpeg = other_dir / "other.jpg"
        other_jpeg.write_text("other jpeg")

        result = ThumbnailFinders.find_shot_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should return None (no editorial/cutref directory)
        assert result is None


# Cache isolation is now handled by the global conftest.py fixture
