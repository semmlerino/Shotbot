from tests.helpers.synchronization import process_qt_events

"""Comprehensive edge case tests for cache manager.

Tests edge cases including:
- Cache directory deletion during operation
- Disk full scenarios
- Permission errors
- Concurrent access patterns
- Memory limit enforcement
- Cache corruption recovery
"""

import shutil
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cache_manager import CacheManager, ThumbnailCacheLoader


class TestCacheDirectoryDeletion:
    """Test cache behavior when directory is deleted during operation."""

    def test_cache_recovers_from_deleted_directory(self, tmp_path):
        """Test that cache manager recovers when cache directory is deleted."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create initial thumbnail
        source_image = self._create_test_image(tmp_path / "test.jpg")
        result = manager.cache_thumbnail(source_image, "show1", "seq1", "shot1")
        assert result is not None
        assert result.exists()

        # Delete the entire cache directory
        shutil.rmtree(manager.thumbnails_dir)
        assert not manager.thumbnails_dir.exists()

        # Try to cache another thumbnail - should recover
        source_image2 = self._create_test_image(tmp_path / "test2.jpg")
        result2 = manager.cache_thumbnail(source_image2, "show1", "seq1", "shot2")
        assert result2 is not None
        assert result2.exists()
        assert manager.thumbnails_dir.exists()

    def test_get_cached_thumbnail_recreates_missing_directory(self, tmp_path):
        """Test that get_cached_thumbnail recreates missing directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Delete the thumbnails directory
        shutil.rmtree(manager.thumbnails_dir)

        # get_cached_thumbnail should handle missing directory gracefully
        result = manager.get_cached_thumbnail("show1", "seq1", "shot1")
        assert result is None  # No cached thumbnail
        assert manager.thumbnails_dir.exists()  # Directory recreated

    def test_clear_cache_atomic_operation(self, tmp_path):
        """Test that clear_cache is atomic and doesn't leave a window of failure."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create some cached data
        source_image = self._create_test_image(tmp_path / "test.jpg")
        manager.cache_thumbnail(source_image, "show1", "seq1", "shot1")

        # Clear cache should be atomic
        old_dir = manager.thumbnails_dir
        manager.clear_cache()

        # New directory should exist immediately
        assert manager.thumbnails_dir.exists()
        # Old directory should be gone (or in process of deletion)
        assert manager.thumbnails_dir != old_dir

    def test_concurrent_access_during_deletion(self, tmp_path):
        """Test concurrent cache operations during directory deletion."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create test images
        images = []
        for i in range(5):
            img_path = tmp_path / f"test{i}.jpg"
            self._create_test_image(img_path)
            images.append(img_path)

        errors = []
        results = []
        lock = threading.Lock()  # Coordinate deletion operations

        def cache_operation(index):
            try:
                # Random operations
                if index % 5 == 0:
                    # Clear cache (safer than rmtree)
                    manager.clear_cache()
                elif index % 3 == 1:
                    # Cache thumbnail
                    result = manager.cache_thumbnail(
                        images[index % len(images)],
                        f"show{index}",
                        f"seq{index}",
                        f"shot{index}",
                    )
                    with lock:
                        results.append(result)
                else:
                    # Get cached thumbnail
                    result = manager.get_cached_thumbnail(
                        f"show{index}", f"seq{index}", f"shot{index}"
                    )
                    with lock:
                        results.append(result)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Run concurrent operations
        threads = []
        for i in range(20):
            t = threading.Thread(target=cache_operation, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should handle all operations without crashes
        assert len(errors) == 0, f"Errors occurred: {errors}"
        # Directory should exist after all operations
        assert manager.thumbnails_dir.exists()

    def _create_test_image(self, path: Path) -> Path:
        """Create a minimal test image file."""
        # Create a simple 10x10 QImage
        image = QImage(10, 10, QImage.Format.Format_RGB32)
        image.fill(0xFF0000)  # Fill with red
        image.save(str(path), "JPEG")
        return path


class TestDiskSpaceErrors:
    """Test cache behavior under disk space constraints."""

    @patch("cache_manager.QImage.save")
    def test_cache_handles_disk_full(self, mock_save, tmp_path):
        """Test cache behavior when disk is full."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Simulate disk full error
        mock_save.return_value = False

        source_image = tmp_path / "test.jpg"
        self._create_test_image(source_image)

        # Should handle gracefully
        result = manager.cache_thumbnail(source_image, "show1", "seq1", "shot1")
        assert result is None

    @patch("pathlib.Path.mkdir")
    def test_cache_handles_permission_denied(self, mock_mkdir, tmp_path):
        """Test cache behavior with permission errors."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Simulate permission denied
        mock_mkdir.side_effect = PermissionError("Permission denied")

        source_image = tmp_path / "test.jpg"
        self._create_test_image(source_image)

        # Should handle gracefully - fallback to temp directory
        manager.cache_thumbnail(source_image, "show1", "seq1", "shot1")
        # Result depends on fallback success
        # The important thing is no crash

    def _create_test_image(self, path: Path) -> Path:
        """Create a minimal test image file."""
        image = QImage(10, 10, QImage.Format.Format_RGB32)
        image.fill(0x00FF00)  # Fill with green
        image.save(str(path), "JPEG")
        return path


class TestMemoryManagement:
    """Test cache memory management and eviction."""

    def test_memory_limit_enforcement(self, tmp_path):
        """Test that cache enforces memory limits."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Create manager with very small memory limit (1KB)
        manager = CacheManager(cache_dir=cache_dir)
        manager._max_memory_bytes = 1024  # 1KB limit

        # Create larger images that will exceed limit
        for i in range(10):
            source_image = tmp_path / f"test{i}.jpg"
            # Create a larger image
            image = QImage(100, 100, QImage.Format.Format_RGB32)
            image.fill(0x0000FF)  # Fill with blue
            image.save(str(source_image), "JPEG", 95)  # High quality = larger file

            manager.cache_thumbnail(source_image, "show1", f"seq{i}", f"shot{i}")

        # Memory usage should be under limit due to eviction
        assert manager._memory_usage_bytes <= manager._max_memory_bytes

        # Some thumbnails should have been evicted
        existing_count = sum(
            1 for p in manager.thumbnails_dir.rglob("*.jpg") if p.exists()
        )
        assert existing_count < 10  # Not all thumbnails should exist

    def test_eviction_removes_oldest_first(self, tmp_path):
        """Test that eviction removes oldest thumbnails first."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        manager = CacheManager(cache_dir=cache_dir)
        manager._max_memory_bytes = 5000  # Small limit

        # Create thumbnails with time delays
        cached_paths = []
        for i in range(5):
            source_image = tmp_path / f"test{i}.jpg"
            image = QImage(50, 50, QImage.Format.Format_RGB32)
            image.fill(i * 50)  # Different colors
            image.save(str(source_image), "JPEG")

            result = manager.cache_thumbnail(
                source_image, "show1", f"seq{i}", f"shot{i}"
            )
            cached_paths.append(result)
            process_qt_events(
                QApplication.instance(), 100
            )  # Small delay to ensure different mtimes

        # Force eviction by adding more
        for i in range(5, 10):
            source_image = tmp_path / f"test{i}.jpg"
            image = QImage(50, 50, QImage.Format.Format_RGB32)
            image.save(str(source_image), "JPEG")
            manager.cache_thumbnail(source_image, "show1", f"seq{i}", f"shot{i}")

        # Check that oldest were evicted
        for i, path in enumerate(cached_paths[:2]):  # First 2 should be evicted
            assert not path.exists(), f"Old thumbnail {i} should be evicted"


class TestCacheValidation:
    """Test cache validation and consistency checks."""

    def test_validate_cache_fixes_orphaned_files(self, tmp_path):
        """Test that validation detects and handles orphaned files."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create an orphaned file (not tracked in memory)
        orphan_dir = manager.thumbnails_dir / "orphan" / "seq"
        orphan_dir.mkdir(parents=True)
        orphan_file = orphan_dir / "orphan_thumb.jpg"

        image = QImage(10, 10, QImage.Format.Format_RGB32)
        image.save(str(orphan_file), "JPEG")

        # Validate should detect the orphan
        result = manager.validate_cache()
        assert result["orphaned_files"] > 0
        assert result["issues_fixed"] > 0

    def test_validate_cache_fixes_missing_files(self, tmp_path):
        """Test that validation handles tracked files that don't exist."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Manually add a non-existent file to tracking
        fake_path = manager.thumbnails_dir / "fake" / "seq" / "fake_thumb.jpg"
        manager._cached_thumbnails[str(fake_path)] = 1000
        manager._memory_usage_bytes += 1000

        # Validate should fix the inconsistency
        result = manager.validate_cache()
        assert result["invalid_entries"] > 0
        assert str(fake_path) not in manager._cached_thumbnails

    def test_periodic_validation_in_get_cached_thumbnail(self, tmp_path):
        """Test that get_cached_thumbnail performs periodic validation."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Set short validation interval for testing
        manager._validation_interval_minutes = 0.001  # Very short interval

        # First call should trigger validation
        with patch.object(manager, "validate_cache") as mock_validate:
            mock_validate.return_value = {"issues_fixed": 0}

            # Wait a tiny bit to exceed interval
            process_qt_events(QApplication.instance(), 100)

            manager.get_cached_thumbnail("show1", "seq1", "shot1")
            mock_validate.assert_called_once()


class TestAtomicOperations:
    """Test atomic file operations."""

    def test_thumbnail_write_is_atomic(self, tmp_path):
        """Test that thumbnail writes use atomic operations."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        source_image = tmp_path / "test.jpg"
        image = QImage(10, 10, QImage.Format.Format_RGB32)
        image.save(str(source_image), "JPEG")

        # Patch to verify temp file is used
        original_replace = Path.replace
        temp_files_used = []

        def track_replace(self, target):
            temp_files_used.append(str(self))
            return original_replace(self, target)

        with patch.object(Path, "replace", track_replace):
            manager.cache_thumbnail(source_image, "show1", "seq1", "shot1")

        # Verify a temp file was used (contains .tmp_ in name)
        assert len(temp_files_used) > 0
        assert ".tmp_" in temp_files_used[0]

    def test_cache_file_write_is_atomic(self, tmp_path):
        """Test that cache file writes are atomic."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Cache some shots
        shots = [
            {"show": "show1", "seq": f"seq{i}", "shot": f"shot{i}"} for i in range(5)
        ]

        # Patch to verify temp file is used
        original_replace = Path.replace
        temp_files_used = []

        def track_replace(self, target):
            temp_files_used.append(str(self))
            return original_replace(self, target)

        with patch.object(Path, "replace", track_replace):
            manager.cache_shots(shots)

        # Verify a temp file was used
        assert len(temp_files_used) > 0
        assert ".tmp" in temp_files_used[0]


class TestConcurrentAccess:
    """Test concurrent access patterns."""

    def test_concurrent_cache_operations(self, tmp_path):
        """Test multiple threads performing cache operations simultaneously."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create test images
        images = []
        for i in range(10):
            img_path = tmp_path / f"test{i}.jpg"
            image = QImage(20, 20, QImage.Format.Format_RGB32)
            image.fill(i * 25)
            image.save(str(img_path), "JPEG")
            images.append(img_path)

        results = []
        errors = []

        def worker(index):
            try:
                # Mix of operations
                if index % 4 == 0:
                    # Cache thumbnail
                    result = manager.cache_thumbnail(
                        images[index % len(images)],
                        f"show{index}",
                        f"seq{index}",
                        f"shot{index}",
                    )
                    results.append(("cache", result))
                elif index % 4 == 1:
                    # Get cached thumbnail
                    result = manager.get_cached_thumbnail(
                        f"show{index - 1}", f"seq{index - 1}", f"shot{index - 1}"
                    )
                    results.append(("get", result))
                elif index % 4 == 2:
                    # Clear cache
                    manager.clear_cache()
                    results.append(("clear", None))
                else:
                    # Validate cache
                    result = manager.validate_cache()
                    results.append(("validate", result))
            except Exception as e:
                errors.append((index, str(e)))

        # Run many concurrent operations
        threads = []
        for i in range(50):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should complete without errors
        assert len(errors) == 0, f"Errors occurred: {errors}"
        # Cache directory should still exist
        assert manager.thumbnails_dir.exists()

    def test_thumbnail_loader_thread_safety(self, qtbot, tmp_path):
        """Test ThumbnailCacheLoader with QThreadPool."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create test images
        images = []
        for i in range(5):
            img_path = tmp_path / f"test{i}.jpg"
            image = QImage(30, 30, QImage.Format.Format_RGB32)
            image.fill(0xFF00FF)  # Magenta
            image.save(str(img_path), "JPEG")
            images.append(img_path)

        # Create multiple loaders
        loaders = []
        for i, img_path in enumerate(images):
            loader = ThumbnailCacheLoader(
                manager, img_path, f"show{i}", f"seq{i}", f"shot{i}"
            )
            loaders.append(loader)

        # Run all loaders concurrently
        pool = QThreadPool.globalInstance()
        for loader in loaders:
            pool.start(loader)

        # Wait for completion
        pool.waitForDone(5000)  # 5 second timeout

        # All thumbnails should be cached
        for i in range(len(images)):
            cached = manager.get_cached_thumbnail(f"show{i}", f"seq{i}", f"shot{i}")
            assert cached is not None
            assert cached.exists()


class TestErrorRecovery:
    """Test error recovery mechanisms."""

    def test_recovery_from_corrupted_cache_file(self, tmp_path):
        """Test recovery from corrupted JSON cache files."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create corrupted shots cache file
        manager.shots_cache_file.write_text("{ corrupted json ][")

        # Should handle gracefully
        shots = manager.get_cached_shots()
        assert shots is None  # Returns None for corrupted data

        # Should be able to write new data
        new_shots = [{"show": "show1", "seq": "seq1", "shot": "shot1"}]
        manager.cache_shots(new_shots)

        # Should be able to read the new data
        cached = manager.get_cached_shots()
        assert cached is not None
        assert cached == new_shots  # Returns list directly, not dict

    def test_recovery_from_partial_write(self, tmp_path):
        """Test recovery from partial/interrupted writes."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        manager = CacheManager(cache_dir=cache_dir)

        # Create a partial temp file (simulating interrupted write)
        temp_file = manager.shots_cache_file.with_suffix(".tmp")
        temp_file.write_text('{"partial": ')

        # Cache operation should clean up and succeed
        shots = [{"show": "show1", "seq": "seq1", "shot": "shot1"}]
        manager.cache_shots(shots)

        # Temp file should be gone
        assert not temp_file.exists()
        # Real file should exist and be valid
        assert manager.shots_cache_file.exists()
        cached = manager.get_cached_shots()
        assert cached == shots  # Returns list directly, not dict

    def test_ensure_cache_directory_fallback(self, tmp_path):
        """Test ensure_cache_directory fallback mechanism."""
        cache_dir = tmp_path / "cache"
        # Don't create the directory

        # Create manager normally first
        manager = CacheManager(cache_dir=cache_dir)

        # Now simulate permission errors
        with patch.object(Path, "mkdir") as mock_mkdir:
            # Simulate all attempts failing to trigger fallback
            mock_mkdir.side_effect = PermissionError("Permission denied")

            # Try to ensure directory when mkdir fails
            try:
                manager._ensure_cache_dirs()
            except Exception:
                pass  # Expected to fail after max retries

            # The fallback mechanism should have changed the directory
            # Note: Due to our implementation, it will try tempfile.mkdtemp
            # which should work even if Path.mkdir is mocked

        # Directory should exist (either original or fallback)
        result = manager.ensure_cache_directory()
        assert result is True
        # Should have a working directory
        assert manager.thumbnails_dir.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
