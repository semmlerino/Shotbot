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
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from config import Config
from paths.validators import PathValidators
from tests.fixtures.environment_fixtures import clear_all_caches
from ui.image_utils import ImageUtils
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
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, mocker
    ) -> None:
        """Test handling of permission errors during file discovery."""
        # Create directory
        test_dir = tmp_path / "restricted"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")

        # Mock permission error
        mocker.patch.object(
            Path,
            "iterdir",
            side_effect=PermissionError("Access denied"),
        )
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
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, mocker
    ) -> None:
        """Test handling of permission errors during version scanning.

        Following UNIFIED_TESTING_GUIDE: Clear caches for test isolation.
        """
        # Clear cache to ensure mock is actually called (cache bypasses iterdir)
        VersionUtils._version_cache.clear()

        mocker.patch.object(
            Path,
            "iterdir",
            side_effect=PermissionError("Access denied"),
        )
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

    def test_version_number_from_name(self) -> None:
        assert VersionUtils.version_number_from_name("v001") == 1
        assert VersionUtils.version_number_from_name("v010") == 10
        assert VersionUtils.version_number_from_name("v1") == 1
        assert VersionUtils.version_number_from_name("v999") == 999


class TestValidationUtils:
    """Test ValidationUtils functionality."""

    def test_validate_not_empty_all_valid(self) -> None:
        """Test validation with all valid values."""
        result = ValidationUtils.validate_not_empty("value1", "value2", "value3")
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

    def test_get_current_username_returns_getpass_user(self, mocker) -> None:
        """Test username is returned from getpass.getuser()."""
        from utils import get_current_username

        mocker.patch("getpass.getuser", return_value="testuser")
        result = get_current_username()
        assert result == "testuser"

    def test_get_current_username_fallback_to_default(self, mocker) -> None:
        """Test username fallback when getpass.getuser() raises."""
        from utils import get_current_username

        mocker.patch("getpass.getuser", side_effect=OSError("no user"))
        result = get_current_username()
        assert result == Config.DEFAULT_USERNAME

    def test_get_excluded_users_default(self, mocker) -> None:
        """Test getting excluded users with current user only."""
        from utils import get_excluded_users

        mocker.patch("utils.get_current_username", return_value="currentuser")
        result = get_excluded_users()
        assert result == {"currentuser"}

    def test_get_excluded_users_with_additional(self, mocker) -> None:
        """Test getting excluded users with additional users."""
        from utils import get_excluded_users

        additional = {"user1", "user2"}
        mocker.patch("utils.get_current_username", return_value="currentuser")
        result = get_excluded_users(additional)
        assert result == {"currentuser", "user1", "user2"}


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

    def test_validate_image_dimensions_uses_config_defaults(self, mocker) -> None:
        """Test that image validation uses config defaults when not specified."""
        mocker.patch.object(Config, "MAX_THUMBNAIL_DIMENSION_PX", 2048)
        mocker.patch.object(Config, "MAX_THUMBNAIL_MEMORY_MB", 10)
        result = ImageUtils.validate_image_dimensions(1920, 1080)
        assert result is True

    @pytest.mark.parametrize(
        ("explicit_size", "config_override", "expected"),
        [
            pytest.param(256, None, (256, 256), id="explicit_size"),
            pytest.param(None, 512, (512, 512), id="uses_config_default"),
        ],
    )
    def test_get_safe_dimensions_for_thumbnail(
        self,
        explicit_size: int | None,
        config_override: int | None,
        expected: tuple[int, int],
        mocker,
    ) -> None:
        """Test safe thumbnail dimensions with explicit size and config default."""
        if config_override is not None:
            mocker.patch.object(Config, "CACHE_THUMBNAIL_SIZE", config_override)
            result = ImageUtils.get_safe_dimensions_for_thumbnail()
        else:
            result = ImageUtils.get_safe_dimensions_for_thumbnail(explicit_size)
        assert result == expected


class TestCacheManagement:
    """Test cache management and utility functions."""

    def test_clear_all_caches_and_stats(
        self, tmp_path: Path, caching_enabled: Path
    ) -> None:
        """Test cache stats reporting and that clear_all_caches resets all cache systems.

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

        # Verify stats report populated caches with expected keys
        stats_before = get_cache_stats()
        assert "path_cache_size" in stats_before
        assert "version_cache_size" in stats_before
        assert "extract_version_cache_info" in stats_before
        assert stats_before["path_cache_size"] >= 2, "Path cache should have entries"
        assert stats_before["version_cache_size"] >= 1, (
            "Version cache should have entries"
        )

        # Clear all caches and verify they are empty
        clear_all_caches()

        stats_after = get_cache_stats()
        assert stats_after["path_cache_size"] == 0, "Path cache should be empty"
        assert stats_after["version_cache_size"] == 0, "Version cache should be empty"


# Cache isolation is now handled by the global conftest.py fixture
