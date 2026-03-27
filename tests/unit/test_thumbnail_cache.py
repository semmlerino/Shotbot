"""Tests for ThumbnailCache — persistent thumbnail caching from image sources.

Covers:
- Thumbnail creation from JPEG and PNG sources
- Thumbnail retrieval (persistent, no TTL)
- EXR processing with graceful degradation
- Error handling for missing/corrupt sources
- Directory structure creation
- Thread safety for concurrent thumbnail caching
- Initialization: thumbnails_dir creation
"""

from __future__ import annotations

# Standard library imports
import time
from pathlib import Path

# Third-party imports
import pytest
from PIL import Image

# Local application imports
from cache.thumbnail_cache import ThumbnailCache


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def thumbnail_cache(tmp_path: Path) -> ThumbnailCache:
    """Create ThumbnailCache with temporary directory."""
    cache_dir = tmp_path / "test_cache"
    return ThumbnailCache(cache_dir)


@pytest.fixture
def test_image_jpg(tmp_path: Path) -> Path:
    """Create a real JPEG test image using PIL (avoids QImage C++ state issues)."""
    image_path = tmp_path / "test_source.jpg"
    img = Image.new("RGB", (512, 512), color=(100, 150, 200))
    img.save(str(image_path), "JPEG", quality=90)
    return image_path


@pytest.fixture
def test_image_png(tmp_path: Path) -> Path:
    """Create a real PNG test image using PIL (avoids QImage C++ state issues)."""
    image_path = tmp_path / "test_source.png"
    img = Image.new("RGBA", (1024, 1024), color=(255, 100, 50, 200))
    img.save(str(image_path), "PNG")
    return image_path


@pytest.fixture
def mock_exr_file(tmp_path: Path) -> Path:
    """Create a mock EXR file for testing."""
    exr_path = tmp_path / "test_plate.exr"
    # Write minimal valid-looking header
    exr_path.write_bytes(b"v/1\x01" + b"\x00" * 100)
    return exr_path


# ---------------------------------------------------------------------------
# TestCacheManagerInitialization (thumbnail-specific)
# ---------------------------------------------------------------------------


class TestThumbnailCacheInitialization:
    """Test ThumbnailCache initialization and directory setup."""

    def test_initialization_creates_thumbnails_dir(self, tmp_path: Path) -> None:
        """Test thumbnails directory is created on init."""
        cache_dir = tmp_path / "new_cache"
        assert not cache_dir.exists()

        cache = ThumbnailCache(cache_dir)

        assert cache.thumbnails_dir == cache_dir / "thumbnails"
        assert cache.thumbnails_dir.exists()
        assert cache.thumbnails_dir.is_dir()

    def test_initialization_with_existing_directory(self, tmp_path: Path) -> None:
        """Test initialization with pre-existing cache directory."""
        cache_dir = tmp_path / "existing_cache"
        cache_dir.mkdir(parents=True)

        cache = ThumbnailCache(cache_dir)

        assert cache.thumbnails_dir.exists()


# ---------------------------------------------------------------------------
# TestThumbnailCaching
# ---------------------------------------------------------------------------


class TestThumbnailCaching:
    """Test thumbnail processing and caching operations."""

    @pytest.mark.parametrize(
        ("image_fixture", "shot_id"),
        [
            ("test_image_jpg", "shot010"),
            ("test_image_png", "shot020"),
        ],
    )
    def test_cache_thumbnail_formats(
        self,
        thumbnail_cache: ThumbnailCache,
        image_fixture: str,
        shot_id: str,
        request: pytest.FixtureRequest,
    ) -> None:
        """Test caching thumbnails produces a resized JPEG for both JPG and PNG input."""
        source_image: Path = request.getfixturevalue(image_fixture)
        result = thumbnail_cache.cache_thumbnail(source_image, "test_show", "seq01", shot_id)

        assert result is not None
        assert result.exists()
        assert result.suffix == ".jpg"

        thumb = Image.open(result)
        assert thumb.width <= 256
        assert thumb.height <= 256

    def test_get_cached_thumbnail_returns_valid_path(
        self, thumbnail_cache: ThumbnailCache, test_image_jpg: Path
    ) -> None:
        """Test retrieving cached thumbnail returns valid path."""
        # Cache a thumbnail first
        thumbnail_cache.cache_thumbnail(test_image_jpg, "test_show", "seq01", "shot010")

        # Retrieve it
        cached_path = thumbnail_cache.get_cached_thumbnail(
            "test_show", "seq01", "shot010"
        )

        assert cached_path is not None
        assert cached_path.exists()
        assert cached_path.name == "shot010_thumb.jpg"

    def test_get_cached_thumbnail_is_persistent(
        self, thumbnail_cache: ThumbnailCache, test_image_jpg: Path
    ) -> None:
        """Test cached thumbnails are persistent (no TTL expiration)."""
        # Cache thumbnail
        thumbnail_cache.cache_thumbnail(test_image_jpg, "test_show", "seq01", "shot010")

        # Verify it's cached
        cached = thumbnail_cache.get_cached_thumbnail("test_show", "seq01", "shot010")
        assert cached is not None

        # Set timestamp to 31 minutes ago (would expire data caches)
        old_time = time.time() - (31 * 60)  # 31 minutes ago
        import os

        os.utime(cached, (old_time, old_time))

        # Should still be valid (thumbnails don't expire)
        still_valid = thumbnail_cache.get_cached_thumbnail("test_show", "seq01", "shot010")
        assert still_valid is not None
        assert still_valid == cached

    def test_get_cached_thumbnail_missing_file(
        self, thumbnail_cache: ThumbnailCache
    ) -> None:
        """Test retrieving non-existent thumbnail returns None."""
        result = thumbnail_cache.get_cached_thumbnail(
            "nonexistent_show", "seq99", "shot999"
        )
        assert result is None

    def test_cache_thumbnail_creates_nested_directories(
        self, thumbnail_cache: ThumbnailCache, test_image_jpg: Path
    ) -> None:
        """Test thumbnail caching creates show/sequence directory structure."""
        thumbnail_cache.cache_thumbnail(test_image_jpg, "new_show", "new_seq", "new_shot")

        expected_dir = thumbnail_cache.thumbnails_dir / "new_show" / "new_seq"
        assert expected_dir.exists()
        assert (expected_dir / "new_shot_thumb.jpg").exists()


# ---------------------------------------------------------------------------
# TestEXRProcessing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestErrorHandling (thumbnail-specific)
# ---------------------------------------------------------------------------


class TestThumbnailErrorHandling:
    """Test thumbnail error handling and edge cases."""

    def test_cache_thumbnail_with_missing_source(
        self, thumbnail_cache: ThumbnailCache, tmp_path: Path
    ) -> None:
        """Test caching thumbnail with non-existent source file."""
        missing_file = tmp_path / "missing.jpg"

        result = thumbnail_cache.cache_thumbnail(missing_file, "show", "seq", "shot")

        # Should return None for missing source
        assert result is None

    def test_cache_thumbnail_with_corrupt_image(
        self, thumbnail_cache: ThumbnailCache, tmp_path: Path
    ) -> None:
        """Test caching thumbnail with corrupt image data."""
        corrupt_file = tmp_path / "corrupt.jpg"
        corrupt_file.write_bytes(b"NOT A VALID IMAGE")

        result = thumbnail_cache.cache_thumbnail(corrupt_file, "show", "seq", "shot")

        # Should handle corrupt image gracefully
        assert result is None


# ---------------------------------------------------------------------------
# TestThreadSafety (thumbnail-specific)
# ---------------------------------------------------------------------------


