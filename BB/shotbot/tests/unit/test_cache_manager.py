"""Unit tests for cache_manager.py"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cache_manager import CacheManager, ThumbnailCacheLoader


class TestCacheManager:
    """Test CacheManager class."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def cache_manager(self, temp_cache_dir):
        """Create CacheManager with temporary directory."""
        return CacheManager(cache_dir=temp_cache_dir)

    def test_ensure_cache_dirs(self, cache_manager, temp_cache_dir):
        """Test cache directory creation."""
        assert (temp_cache_dir / "thumbnails").exists()

    def test_get_cached_thumbnail_not_exists(self, cache_manager):
        """Test getting non-existent cached thumbnail."""
        result = cache_manager.get_cached_thumbnail("show1", "seq1", "shot1")
        assert result is None

    def test_get_cached_thumbnail_exists(self, cache_manager, temp_cache_dir):
        """Test getting existing cached thumbnail."""
        # Create cached thumbnail
        cache_path = (
            temp_cache_dir / "thumbnails" / "show1" / "seq1" / "shot1_thumb.jpg"
        )
        cache_path.parent.mkdir(parents=True)
        cache_path.touch()

        result = cache_manager.get_cached_thumbnail("show1", "seq1", "shot1")
        assert result == cache_path

    @patch("cache_manager.QPixmap")
    def test_cache_thumbnail_success(
        self, mock_pixmap_class, cache_manager, temp_cache_dir
    ):
        """Test successful thumbnail caching."""
        # Setup mock
        mock_pixmap = Mock()
        mock_pixmap.isNull.return_value = False
        mock_pixmap.width.return_value = 800  # Valid size
        mock_pixmap.height.return_value = 600  # Valid size
        mock_scaled = Mock()
        mock_scaled.isNull.return_value = False  # Scaling succeeded
        mock_scaled.save.return_value = True
        mock_pixmap.scaled.return_value = mock_scaled
        mock_pixmap_class.return_value = mock_pixmap

        # Create source file
        source = temp_cache_dir / "source.jpg"
        source.touch()

        result = cache_manager.cache_thumbnail(source, "show1", "seq1", "shot1")
        expected_path = (
            temp_cache_dir / "thumbnails" / "show1" / "seq1" / "shot1_thumb.jpg"
        )

        assert result == expected_path
        mock_scaled.save.assert_called_once_with(str(expected_path), "JPEG", 85)

    @patch("cache_manager.QPixmap")
    def test_cache_thumbnail_invalid_image(
        self, mock_pixmap_class, cache_manager, temp_cache_dir
    ):
        """Test caching invalid thumbnail."""
        # Setup mock for invalid image
        mock_pixmap = Mock()
        mock_pixmap.isNull.return_value = True
        mock_pixmap_class.return_value = mock_pixmap

        source = temp_cache_dir / "invalid.jpg"
        source.touch()

        result = cache_manager.cache_thumbnail(source, "show1", "seq1", "shot1")
        assert result is None

    def test_cache_thumbnail_source_not_exists(self, cache_manager, temp_cache_dir):
        """Test caching non-existent source."""
        source = temp_cache_dir / "nonexistent.jpg"
        result = cache_manager.cache_thumbnail(source, "show1", "seq1", "shot1")
        assert result is None

    def test_get_cached_shots_no_file(self, cache_manager):
        """Test getting shots when cache file doesn't exist."""
        result = cache_manager.get_cached_shots()
        assert result is None

    def test_get_cached_shots_valid(self, cache_manager, temp_cache_dir):
        """Test getting valid cached shots."""
        shots_data = {
            "timestamp": datetime.now().isoformat(),
            "shots": [
                {
                    "show": "show1",
                    "sequence": "seq1",
                    "shot": "0010",
                    "workspace_path": "/path/1",
                },
                {
                    "show": "show1",
                    "sequence": "seq1",
                    "shot": "0020",
                    "workspace_path": "/path/2",
                },
            ],
        }

        with open(temp_cache_dir / "shots.json", "w") as f:
            json.dump(shots_data, f)

        result = cache_manager.get_cached_shots()
        assert len(result) == 2
        assert result[0]["shot"] == "0010"

    def test_get_cached_shots_expired(self, cache_manager, temp_cache_dir):
        """Test getting expired cached shots."""
        old_time = datetime.now() - timedelta(hours=1)
        shots_data = {
            "timestamp": old_time.isoformat(),
            "shots": [
                {
                    "show": "show1",
                    "sequence": "seq1",
                    "shot": "0010",
                    "workspace_path": "/path",
                }
            ],
        }

        with open(temp_cache_dir / "shots.json", "w") as f:
            json.dump(shots_data, f)

        result = cache_manager.get_cached_shots()
        assert result is None

    def test_get_cached_shots_invalid_json(self, cache_manager, temp_cache_dir):
        """Test handling invalid JSON in cache file."""
        with open(temp_cache_dir / "shots.json", "w") as f:
            f.write("invalid json")

        result = cache_manager.get_cached_shots()
        assert result is None

    def test_cache_shots(self, cache_manager, temp_cache_dir):
        """Test caching shots."""
        shots = [
            {
                "show": "show1",
                "sequence": "seq1",
                "shot": "0010",
                "workspace_path": "/path/1",
            },
            {
                "show": "show1",
                "sequence": "seq1",
                "shot": "0020",
                "workspace_path": "/path/2",
            },
        ]

        cache_manager.cache_shots(shots)

        assert (temp_cache_dir / "shots.json").exists()

        with open(temp_cache_dir / "shots.json", "r") as f:
            data = json.load(f)

        assert "timestamp" in data
        assert data["shots"] == shots

    def test_clear_cache(self, cache_manager, temp_cache_dir):
        """Test clearing cache."""
        # Create some cache files
        (temp_cache_dir / "thumbnails" / "test").mkdir(parents=True)
        (temp_cache_dir / "thumbnails" / "test" / "thumb.jpg").touch()
        (temp_cache_dir / "shots.json").touch()

        cache_manager.clear_cache()

        # Thumbnails should be gone but directory recreated
        assert (temp_cache_dir / "thumbnails").exists()
        assert not (temp_cache_dir / "thumbnails" / "test").exists()
        assert not (temp_cache_dir / "shots.json").exists()


class TestThumbnailCacheLoader:
    """Test ThumbnailCacheLoader class."""

    @pytest.fixture
    def mock_cache_manager(self):
        """Create mock cache manager."""
        return Mock(spec=CacheManager)

    def test_thumbnail_cache_loader_init(self, mock_cache_manager):
        """Test ThumbnailCacheLoader initialization."""
        source_path = Path("/source/image.jpg")
        loader = ThumbnailCacheLoader(
            mock_cache_manager, source_path, "show1", "seq1", "shot1"
        )

        assert loader.cache_manager == mock_cache_manager
        assert loader.source_path == source_path
        assert loader.show == "show1"
        assert loader.sequence == "seq1"
        assert loader.shot == "shot1"

    def test_thumbnail_cache_loader_run_success(self, mock_cache_manager):
        """Test successful thumbnail caching in background."""
        source_path = Path("/source/image.jpg")
        cache_path = Path("/cache/thumb.jpg")

        mock_cache_manager.cache_thumbnail.return_value = cache_path

        loader = ThumbnailCacheLoader(
            mock_cache_manager, source_path, "show1", "seq1", "shot1"
        )

        # Track signal emissions
        emitted = []
        loader.signals.loaded.connect(lambda *args: emitted.append(args))

        loader.run()

        mock_cache_manager.cache_thumbnail.assert_called_once_with(
            source_path, "show1", "seq1", "shot1"
        )
        assert len(emitted) == 1
        assert emitted[0] == ("show1", "seq1", "shot1", cache_path)

    def test_thumbnail_cache_loader_run_failure(self, mock_cache_manager):
        """Test failed thumbnail caching."""
        source_path = Path("/source/image.jpg")

        mock_cache_manager.cache_thumbnail.return_value = None

        loader = ThumbnailCacheLoader(
            mock_cache_manager, source_path, "show1", "seq1", "shot1"
        )

        # Track signal emissions
        emitted = []
        loader.signals.loaded.connect(lambda *args: emitted.append(args))

        loader.run()

        mock_cache_manager.cache_thumbnail.assert_called_once()
        assert len(emitted) == 0  # No signal should be emitted on failure
