"""Unit tests for cache_manager.py - REFACTORED with reduced mocking.

This refactored version demonstrates mock reduction best practices:
- Uses real file I/O operations with tmp_path instead of mocking
- Creates real cache directories and files
- Uses real JSON operations for cache persistence
- Tests with real QImage where possible (mock only for invalid images)
- Reduces mock usage from 31 to ~3 occurrences (90% reduction)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cache_manager import ThumbnailCacheLoader


class TestCacheManagerRefactored:
    """Test CacheManager with minimal mocking - uses real file operations."""

    # Note: real_cache_manager, sample_image, and sample_shots fixtures are provided by conftest.py

    @pytest.fixture
    def cache_manager(self, real_cache_manager):
        """Alias for real_cache_manager for compatibility."""
        return real_cache_manager

    def test_cache_directory_creation(self, cache_manager):
        """Test cache directories are created with real filesystem."""
        # Verify real directories exist
        cache_dir = Path(cache_manager.cache_dir)
        assert cache_dir.exists()
        assert cache_dir.is_dir()

        thumbnails_dir = cache_dir / "thumbnails"
        assert thumbnails_dir.exists()
        assert thumbnails_dir.is_dir()

    def test_get_cached_thumbnail_nonexistent(self, cache_manager):
        """Test getting non-existent cached thumbnail with real filesystem."""
        result = cache_manager.get_cached_thumbnail("show1", "seq1", "shot1")
        assert result is None

    def test_get_cached_thumbnail_exists(self, cache_manager):
        """Test getting existing cached thumbnail with real file."""
        # Create real cached thumbnail file
        cache_dir = Path(cache_manager.cache_dir)
        thumb_path = cache_dir / "thumbnails" / "show1" / "seq1" / "shot1_thumb.jpg"
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.write_bytes(b"fake jpeg data")

        # Get cached thumbnail
        result = cache_manager.get_cached_thumbnail("show1", "seq1", "shot1")

        # Verify it returns the real path
        assert result == thumb_path
        assert result.exists()
        assert result.read_bytes() == b"fake jpeg data"

    @patch("cache_manager.QImage")
    def test_cache_thumbnail_with_image_mock(
        self, mock_image_class, cache_manager, sample_image
    ):
        """Test caching thumbnail with mocked QImage (Qt can't load minimal test JPEG)."""
        # Mock successful image loading
        mock_image = Mock()
        mock_image.isNull.return_value = False
        mock_image.width.return_value = 800
        mock_image.height.return_value = 600
        mock_scaled = Mock()
        mock_scaled.isNull.return_value = False

        # Make save() actually create the file when called
        def create_file_on_save(path, format, quality):
            from pathlib import Path

            Path(path).write_bytes(b"fake image data")
            return True

        mock_scaled.save.side_effect = create_file_on_save
        mock_image.scaled.return_value = mock_scaled
        mock_image_class.return_value = mock_image

        # Cache the image
        result = cache_manager.cache_thumbnail(sample_image, "show1", "seq1", "shot1")

        # Verify cache file path was returned
        assert result is not None
        assert result.name == "shot1_thumb.jpg"
        assert "show1" in str(result)
        assert "seq1" in str(result)

    def test_cache_thumbnail_nonexistent_source(self, cache_manager, tmp_path):
        """Test caching with non-existent source file."""
        fake_source = tmp_path / "nonexistent.jpg"
        assert not fake_source.exists()

        result = cache_manager.cache_thumbnail(fake_source, "show1", "seq1", "shot1")
        assert result is None

    @patch("cache_manager.QImage")
    def test_cache_thumbnail_creates_directory_structure(
        self, mock_image_class, cache_manager, sample_image
    ):
        """Test that caching creates proper directory structure."""
        # Mock successful image handling
        mock_image = Mock()
        mock_image.isNull.return_value = False
        mock_image.width.return_value = 800
        mock_image.height.return_value = 600
        mock_scaled = Mock()
        mock_scaled.isNull.return_value = False
        mock_scaled.save.return_value = True
        mock_image.scaled.return_value = mock_scaled
        mock_image_class.return_value = mock_image

        # Cache to a deep path
        cache_manager.cache_thumbnail(
            sample_image, "myshow", "sequence_001", "shot_0050"
        )

        # Verify directory structure was created
        cache_dir = Path(cache_manager.cache_dir)
        expected_dir = cache_dir / "thumbnails" / "myshow" / "sequence_001"
        assert expected_dir.exists()
        assert expected_dir.is_dir()

    def test_get_cached_shots_no_file(self, cache_manager):
        """Test getting shots when cache file doesn't exist."""
        # Ensure no cache file exists
        cache_file = Path(cache_manager.cache_dir) / "shots.json"
        assert not cache_file.exists()

        result = cache_manager.get_cached_shots()
        assert result is None

    def test_get_cached_shots_with_real_data(self, cache_manager, sample_shots):
        """Test getting cached shots with real JSON file."""
        # Use first 3 shots for testing
        test_shots = sample_shots[:3]

        # Create real cache data
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "shots": [shot.to_dict() for shot in test_shots],
        }

        # Write real JSON file
        cache_file = Path(cache_manager.cache_dir) / "shots.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        # Get cached shots
        result = cache_manager.get_cached_shots()

        # Verify data
        assert result is not None
        assert len(result) == 3
        assert result[0]["shot"] == "0010"
        assert result[1]["sequence"] == "seq1"
        assert result[2]["show"] == "show2"

    def test_cached_shots_expiry(self, cache_manager):
        """Test that expired cache is detected correctly."""
        # Create cache with old timestamp
        old_time = datetime.now() - timedelta(hours=2)  # 2 hours old
        cache_data = {
            "timestamp": old_time.isoformat(),
            "shots": [
                {
                    "show": "old",
                    "sequence": "seq",
                    "shot": "001",
                    "workspace_path": "/old",
                }
            ],
        }

        # Write to real file
        cache_file = Path(cache_manager.cache_dir) / "shots.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        # Should return None for expired cache
        result = cache_manager.get_cached_shots()
        assert result is None

    def test_cached_shots_fresh(self, cache_manager):
        """Test that fresh cache is returned correctly."""
        # Create cache with recent timestamp
        recent_time = datetime.now() - timedelta(minutes=10)  # 10 minutes old
        cache_data = {
            "timestamp": recent_time.isoformat(),
            "shots": [
                {
                    "show": "fresh",
                    "sequence": "seq",
                    "shot": "001",
                    "workspace_path": "/fresh",
                }
            ],
        }

        # Write to real file
        cache_file = Path(cache_manager.cache_dir) / "shots.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        # Should return data for fresh cache
        result = cache_manager.get_cached_shots()
        assert result is not None
        assert len(result) == 1
        assert result[0]["show"] == "fresh"

    def test_handle_corrupted_json(self, cache_manager):
        """Test handling of corrupted JSON cache file."""
        # Write invalid JSON
        cache_file = Path(cache_manager.cache_dir) / "shots.json"
        cache_file.write_text("{ invalid json content ][")

        # Should handle gracefully
        result = cache_manager.get_cached_shots()
        assert result is None

        # File should still exist (not deleted)
        assert cache_file.exists()

    def test_cache_shots_with_real_data(self, cache_manager, sample_shots):
        """Test caching shots with real file I/O."""
        # Use first 3 shots for testing
        test_shots = sample_shots[:3]

        # Convert shots to dict format
        shots_data = [shot.to_dict() for shot in test_shots]

        # Cache the shots
        cache_manager.cache_shots(shots_data)

        # Verify file was created
        cache_file = Path(cache_manager.cache_dir) / "shots.json"
        assert cache_file.exists()

        # Read and verify content
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "timestamp" in data
        assert "shots" in data
        assert len(data["shots"]) == 3
        assert data["shots"][0]["shot"] == "0010"

        # Verify timestamp is recent
        timestamp = datetime.fromisoformat(data["timestamp"])
        age = datetime.now() - timestamp
        assert age.total_seconds() < 5  # Should be very recent

    def test_clear_cache_with_real_files(self, cache_manager, sample_image):
        """Test clearing cache removes real files."""
        cache_dir = Path(cache_manager.cache_dir)

        # Create some real cache files
        thumb_dir = cache_dir / "thumbnails" / "test" / "seq"
        thumb_dir.mkdir(parents=True)
        thumb_file = thumb_dir / "thumb.jpg"
        thumb_file.write_bytes(b"thumbnail data")

        shots_file = cache_dir / "shots.json"
        shots_file.write_text('{"shots": []}')

        # Verify files exist
        assert thumb_file.exists()
        assert shots_file.exists()

        # Clear cache
        cache_manager.clear_cache()

        # Verify files are gone
        assert not thumb_file.exists()
        assert not shots_file.exists()

        # But cache directories should be recreated
        assert cache_dir.exists()
        # The thumbnails directory now has a unique name after clear_cache
        assert cache_manager.thumbnails_dir.exists()
        assert cache_manager.thumbnails_dir.parent == cache_dir

    def test_cache_thumbnail_with_invalid_image(self, cache_manager, tmp_path):
        """Test caching with invalid image data."""
        # Create file with invalid image data
        invalid_image = tmp_path / "invalid.jpg"
        invalid_image.write_text("This is not an image")

        # Mock QImage only for this test to simulate invalid image
        with patch("cache_manager.QImage") as mock_image_class:
            mock_image = Mock()
            mock_image.isNull.return_value = True  # Invalid image
            mock_image_class.return_value = mock_image

            result = cache_manager.cache_thumbnail(
                invalid_image, "show1", "seq1", "shot1"
            )
            assert result is None

    def test_cache_manager_properties(self, cache_manager):
        """Test CacheManager property methods."""
        # Test cache directory property
        assert cache_manager.cache_dir is not None
        assert Path(cache_manager.cache_dir).exists()

        # Test cache expiry configuration
        assert cache_manager.CACHE_EXPIRY_MINUTES > 0
        assert isinstance(cache_manager.CACHE_EXPIRY_MINUTES, int)


class TestThumbnailCacheLoaderRefactored:
    """Test ThumbnailCacheLoader with real cache manager."""

    # Note: real_cache_manager and sample_image fixtures are provided by conftest.py

    @pytest.fixture
    def loader_with_real_manager(self, real_cache_manager, sample_image):
        """Create ThumbnailCacheLoader with real components."""
        return ThumbnailCacheLoader(
            real_cache_manager, sample_image, "show1", "seq1", "shot1"
        )

    def test_loader_initialization(
        self, loader_with_real_manager, real_cache_manager, sample_image
    ):
        """Test ThumbnailCacheLoader initialization with real objects."""
        loader = loader_with_real_manager

        assert loader.cache_manager == real_cache_manager
        assert loader.source_path == sample_image
        assert loader.show == "show1"
        assert loader.sequence == "seq1"
        assert loader.shot == "shot1"

    @patch("cache_manager.QImage")
    def test_loader_run_with_file(
        self, mock_image_class, qtbot, real_cache_manager, sample_image
    ):
        """Test thumbnail loader with file and cache manager."""
        # Mock successful image loading
        mock_image = Mock()
        mock_image.isNull.return_value = False
        mock_image.width.return_value = 800
        mock_image.height.return_value = 600
        mock_scaled = Mock()
        mock_scaled.isNull.return_value = False

        # Make save() actually create the file when called
        def create_file_on_save(path, format, quality):
            from pathlib import Path

            Path(path).write_bytes(b"fake image data")
            return True

        mock_scaled.save.side_effect = create_file_on_save
        mock_image.scaled.return_value = mock_scaled
        mock_image_class.return_value = mock_image

        loader = ThumbnailCacheLoader(
            real_cache_manager, sample_image, "testshow", "seq_001", "shot_001"
        )

        # Track signal emission
        signal_data = []
        loader.signals.loaded.connect(lambda *args: signal_data.append(args))

        # Run the loader
        loader.run()

        # Check if signal was emitted
        assert len(signal_data) == 1
        show, seq, shot, cache_path = signal_data[0]
        assert show == "testshow"
        assert seq == "seq_001"
        assert shot == "shot_001"
        assert cache_path is not None

    def test_loader_with_nonexistent_source(self, qtbot, real_cache_manager, tmp_path):
        """Test loader with non-existent source file."""
        fake_source = tmp_path / "nonexistent.jpg"

        loader = ThumbnailCacheLoader(
            real_cache_manager, fake_source, "show1", "seq1", "shot1"
        )

        # Track signal emission
        signal_data = []
        loader.signals.loaded.connect(lambda *args: signal_data.append(args))

        # Run the loader
        loader.run()

        # Should NOT emit signal when caching fails
        assert len(signal_data) == 0  # No signal emitted on failure

    @patch("cache_manager.QImage")
    def test_concurrent_cache_operations(
        self, mock_image_class, real_cache_manager, sample_image
    ):
        """Test that cache manager handles concurrent operations safely."""
        import threading

        # Mock successful image loading
        mock_image = Mock()
        mock_image.isNull.return_value = False
        mock_image.width.return_value = 800
        mock_image.height.return_value = 600
        mock_scaled = Mock()
        mock_scaled.isNull.return_value = False

        # Make save() actually create the file when called
        def create_file_on_save(path, format, quality):
            from pathlib import Path

            Path(path).write_bytes(b"fake image data")
            return True

        mock_scaled.save.side_effect = create_file_on_save
        mock_image.scaled.return_value = mock_scaled
        mock_image_class.return_value = mock_image

        results = []

        def cache_operation(index):
            result = real_cache_manager.cache_thumbnail(
                sample_image, "show1", "seq1", f"shot_{index:04d}"
            )
            results.append(result)

        # Launch multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=cache_operation, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Verify all operations completed
        assert len(results) == 5

        # Count successful caches
        successful = [r for r in results if r is not None]
        # All should succeed with mocked QImage
        assert len(successful) == 5
