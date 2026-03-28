"""Edge case tests for EXR thumbnail handling.

Tests handling of corrupted files, permission errors, unusual formats,
and other exceptional conditions that may occur in production.
"""

from __future__ import annotations

# Standard library imports
import os
import stat
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
# Lazy imports to avoid Qt initialization at module level
# from PySide6.QtCore import QCoreApplication
# from cache_manager import CacheManager
from paths.validators import PathValidators
from utils import FileUtils


try:
    # Third-party imports
    from PIL import Image
except ImportError:
    Image = None

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
]


# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)


# Module-level fixture to handle lazy imports
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and ThumbnailCache components after test setup."""
    global CacheManager, QCoreApplication  # noqa: PLW0603
    # Third-party imports
    from PySide6.QtCore import (
        QCoreApplication,
    )

    # Local application imports
    from cache.thumbnail_cache import (
        ThumbnailCache as CacheManager,
    )


class TestCorruptedFiles:
    """Test handling of corrupted or invalid EXR files."""

    def test_corrupted_exr_header(self, tmp_path) -> None:
        """Corrupted EXR header should be handled gracefully."""
        bad_exr = tmp_path / "corrupted.exr"
        bad_exr.write_bytes(b"NOT_AN_EXR_HEADER" + b"x" * 100)

        cache_manager = CacheManager(tmp_path / "cache")

        # Should not crash, return None
        result = cache_manager.cache_thumbnail(
            bad_exr, show="test", sequence="seq", shot="0010"
        )

        assert result is None or isinstance(result, Path)

    def test_empty_exr_file(self, tmp_path) -> None:
        """Empty file should be handled without crash."""
        # Use .jpg instead of .exr (EXR no longer supported for thumbnails)
        empty_jpg = tmp_path / "empty.jpg"
        empty_jpg.touch()  # Creates empty file

        result = FileUtils.get_first_image_file(tmp_path, allow_fallback=True)
        assert result == empty_jpg  # Found the file

        # Cache manager should handle empty file
        cache_manager = CacheManager(tmp_path / "cache")
        cached = cache_manager.cache_thumbnail(
            empty_jpg, show="test", sequence="seq", shot="0010"
        )

        # Should handle gracefully (return None or empty cache)
        assert cached is None or cached.stat().st_size == 0

    def test_truncated_exr_file(self, tmp_path) -> None:
        """Truncated EXR file should not crash the application."""
        truncated = tmp_path / "truncated.exr"
        # Write partial EXR magic number
        truncated.write_bytes(b"\x76\x2f\x31")  # Incomplete EXR header

        cache_manager = CacheManager(tmp_path / "cache")

        # Test behavior: should handle gracefully without crashing
        result = cache_manager.cache_thumbnail(
            truncated, show="test", sequence="seq", shot="0010"
        )

        # Should return None for corrupted file, not crash
        assert result is None


class TestPermissionErrors:
    """Test handling of file permission issues."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix-specific permissions")
    def test_no_read_permission(self, tmp_path) -> None:
        """Files without read permission should be handled."""
        # Use .jpg instead of .exr (EXR no longer supported for thumbnails)
        protected_jpg = tmp_path / "protected.jpg"
        protected_jpg.write_bytes(b"JPG" + b"x" * 100)

        # Remove read permission
        protected_jpg.chmod(stat.S_IWRITE)

        try:
            result = FileUtils.get_first_image_file(tmp_path, allow_fallback=True)
            # The function finds the file but cache_manager would fail to read it
            # Testing that the function doesn't crash is the behavior we care about
            assert result is not None  # Function completes without error
        finally:
            # Restore permissions for cleanup
            protected_jpg.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_directory_no_execute_permission(self, tmp_path) -> None:
        """Directory without execute permission should be handled."""
        if os.name == "nt":
            pytest.skip("Unix-specific permissions")

        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        test_file = restricted_dir / "test.exr"
        test_file.touch()

        # Remove execute permission (can't list directory)
        restricted_dir.chmod(stat.S_IREAD | stat.S_IWRITE)

        try:
            # PathUtils should handle permission errors gracefully
            result = PathValidators.validate_path_exists(test_file, "Test file")
            # Should return False when can't access due to permissions
            assert result is False
        except PermissionError:
            # If permission error occurs, that's also acceptable behavior
            pass
        finally:
            # Restore permissions
            restricted_dir.chmod(stat.S_IRWXU)

    def test_cache_dir_not_writable(self, tmp_path) -> None:
        """Cache directory without write permission raises OSError on init."""
        cache_dir = tmp_path / "readonly_cache"
        cache_dir.mkdir()

        if os.name != "nt":
            # Make read-only
            cache_dir.chmod(stat.S_IREAD | stat.S_IEXEC)

        try:
            # _ensure_cache_dirs re-raises OSError so callers can detect failure
            with pytest.raises(OSError, match="Permission denied"):
                CacheManager(cache_dir)
        finally:
            if os.name != "nt":
                cache_dir.chmod(stat.S_IRWXU)


class TestUnusualFormats:
    """Test handling of unusual or edge-case file formats."""

    @pytest.mark.parametrize(
        ("filename", "content"),
        [
            # Use .jpg instead of .exr (EXR no longer supported for thumbnails)
            ("UPPERCASE.JPG", b"JPG"),
            ("mixed.JpG", b"JPG"),
            ("with spaces.jpg", b"JPG"),
            ("unicode_文件.jpg", b"JPG"),
            (".hidden.jpg", b"JPG"),
            ("very_long_filename_" + "x" * 200 + ".jpg", b"JPG"),
        ],
    )
    def test_unusual_filenames(self, tmp_path, filename, content) -> None:
        """Various unusual filenames should be handled."""
        file_path = tmp_path / filename
        try:
            file_path.write_bytes(content)
        except OSError:
            pytest.skip(f"Filesystem doesn't support filename: {filename}")

        result = FileUtils.get_first_image_file(tmp_path, allow_fallback=True)

        # Should find the file regardless of unusual name
        assert result is not None
        assert result.name.lower().endswith((".jpg", ".jpeg"))

    def test_symlink_to_exr(self, tmp_path) -> None:
        """Symlinks to image files should work."""
        if os.name == "nt":
            pytest.skip("Symlink test requires Unix")

        # Use .jpg instead of .exr (EXR no longer supported for thumbnails)
        # Create actual JPG
        real_jpg = tmp_path / "real" / "file.jpg"
        real_jpg.parent.mkdir()
        real_jpg.write_bytes(b"JPG" + b"x" * 100)

        # Create symlink
        link_jpg = tmp_path / "link.jpg"
        link_jpg.symlink_to(real_jpg)

        result = FileUtils.get_first_image_file(tmp_path, allow_fallback=True)
        assert result == link_jpg

        # Cache manager should handle symlink
        cache_manager = CacheManager(tmp_path / "cache")
        cached = cache_manager.cache_thumbnail(
            link_jpg, show="test", sequence="seq", shot="0010"
        )

        # Should process the linked file
        assert cached is None or isinstance(cached, Path)

    def test_very_deep_directory_structure(self, tmp_path) -> None:
        """Very deep directory structures should be handled."""
        # Use .jpg instead of .exr (EXR no longer supported for thumbnails)
        # Create deep path
        deep_path = tmp_path
        for i in range(50):  # 50 levels deep
            deep_path = deep_path / f"level_{i}"

        deep_path.mkdir(parents=True)
        jpg_file = deep_path / "deep.jpg"
        jpg_file.write_bytes(b"JPG")

        # Should handle deep paths
        assert PathValidators.validate_path_exists(jpg_file, "Deep file")

        result = FileUtils.get_first_image_file(deep_path, allow_fallback=True)
        assert result == jpg_file

    @pytest.mark.skipif(os.name == "nt", reason="Unix-specific")
    def test_unix_special_device_files(self, tmp_path) -> None:
        """Special device files should not be processed as images."""
        # Create a named pipe (FIFO)
        fifo_path = tmp_path / "fake.exr"
        os.mkfifo(fifo_path)

        try:
            result = FileUtils.get_first_image_file(tmp_path, allow_fallback=True)
            # Should either skip or handle gracefully
            assert result is None or not stat.S_ISFIFO(result.stat().st_mode)
        finally:
            fifo_path.unlink()
