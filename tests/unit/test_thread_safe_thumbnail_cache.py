"""Thread-safe thumbnail cache tests with concurrency focus.

Tests for ThreadSafeThumbnailCache focusing on:
- Thread safety guarantees (locks, atomic operations)
- Race condition scenarios (concurrent reads/writes)
- Cache eviction under concurrent access
- Memory management and cleanup
- Integration with Qt event loop

Following patterns from:
- test_threading_utils.py (concurrent progress tracking)
- test_thread_safety_regression.py (stress tests)
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QColor, QImage, QPixmap

from tests.test_helpers import simulate_work_without_sleep
from thread_safe_thumbnail_cache import (
    ThreadSafeThumbnailCache,
    create_thread_safe_pixmap,
)


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestBasicOperations:
    """Basic functionality tests (single-threaded)."""

    def test_store_and_retrieve_image(self, qapp: QApplication) -> None:
        """Test basic store/retrieve cycle."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor(255, 0, 0))

        cache.store_image("test_key", image)

        assert cache.has_image("test_key")
        retrieved = cache.get_image("test_key")
        assert retrieved is not None
        assert not retrieved.isNull()

    def test_store_from_path(self, qapp: QApplication, tmp_path: Path) -> None:
        """Test loading and caching from file path."""
        image_path = tmp_path / "test.png"
        image = QImage(50, 50, QImage.Format.Format_RGB32)
        image.fill(QColor(0, 255, 0))
        image.save(str(image_path))

        cache = ThreadSafeThumbnailCache()
        result = cache.store_from_path("path_key", image_path)

        assert result is True
        assert cache.has_image("path_key")

    def test_store_from_invalid_path(self, qapp: QApplication, tmp_path: Path) -> None:
        """Test loading from non-existent path returns False."""
        cache = ThreadSafeThumbnailCache()
        result = cache.store_from_path("invalid_key", tmp_path / "nonexistent.png")

        assert result is False
        assert not cache.has_image("invalid_key")

    def test_get_pixmap_converts_from_image(self, qapp: QApplication) -> None:
        """Test QImage to QPixmap conversion on main thread."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor(0, 0, 255))

        cache.store_image("convert_key", image)
        pixmap = cache.get_pixmap("convert_key")

        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.width() == 100

    def test_get_pixmap_caches_result(self, qapp: QApplication) -> None:
        """Test that pixmap is cached after first conversion."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor(128, 128, 128))

        cache.store_image("cache_key", image)

        # First retrieval creates pixmap
        _ = cache.get_pixmap("cache_key")
        stats1 = cache.get_stats()
        assert stats1["pixmap_count"] == 1

        # Second retrieval uses cached pixmap
        _ = cache.get_pixmap("cache_key")
        stats2 = cache.get_stats()
        assert stats2["pixmap_count"] == 1  # Still 1, not 2

    def test_get_pixmap_nonexistent_key(self, qapp: QApplication) -> None:
        """Test get_pixmap returns None for missing key."""
        cache = ThreadSafeThumbnailCache()
        result = cache.get_pixmap("nonexistent")
        assert result is None

    def test_get_image_nonexistent_key(self, qapp: QApplication) -> None:
        """Test get_image returns None for missing key."""
        cache = ThreadSafeThumbnailCache()
        result = cache.get_image("nonexistent")
        assert result is None

    def test_get_stats_returns_correct_counts(self, qapp: QApplication) -> None:
        """Test cache statistics."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(50, 50, QImage.Format.Format_RGB32)

        cache.store_image("key1", image)
        cache.store_image("key2", image)
        _ = cache.get_pixmap("key1")  # Convert one to pixmap

        stats = cache.get_stats()
        assert stats["image_count"] == 2
        assert stats["pixmap_count"] == 1
        assert stats["total_count"] == 2

    def test_clear_removes_all_entries(self, qapp: QApplication) -> None:
        """Test clearing the cache."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(50, 50, QImage.Format.Format_RGB32)

        cache.store_image("key1", image)
        cache.store_image("key2", image)
        _ = cache.get_pixmap("key1")

        cache.clear()

        assert not cache.has_image("key1")
        assert not cache.has_image("key2")
        stats = cache.get_stats()
        assert stats["total_count"] == 0
        assert stats["pixmap_count"] == 0

    def test_remove_single_key(self, qapp: QApplication) -> None:
        """Test removing a single key."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(50, 50, QImage.Format.Format_RGB32)

        cache.store_image("keep", image)
        cache.store_image("remove", image)

        cache.remove("remove")

        assert cache.has_image("keep")
        assert not cache.has_image("remove")

    def test_remove_nonexistent_key_no_error(self, qapp: QApplication) -> None:
        """Test removing non-existent key doesn't raise error."""
        cache = ThreadSafeThumbnailCache()
        cache.remove("nonexistent")  # Should not raise


class TestMainThreadAssertion:
    """Test QPixmap main thread enforcement."""

    def test_get_pixmap_raises_on_worker_thread(self, qapp: QApplication) -> None:
        """Test that get_pixmap raises RuntimeError from worker thread."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        cache.store_image("test", image)

        error_raised: list[str] = []

        def worker_attempt() -> None:
            try:
                _ = cache.get_pixmap("test")
            except RuntimeError as e:
                error_raised.append(str(e))

        thread = threading.Thread(target=worker_attempt)
        thread.start()
        thread.join(timeout=5.0)

        assert len(error_raised) == 1
        assert "QPixmap" in error_raised[0]
        assert "worker thread" in error_raised[0]

    def test_get_image_allowed_from_worker_thread(self, qapp: QApplication) -> None:
        """Test that get_image works from any thread."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor(128, 128, 128))
        cache.store_image("test", image)

        result: list[bool] = []

        def worker_access() -> None:
            retrieved = cache.get_image("test")
            result.append(retrieved is not None)

        thread = threading.Thread(target=worker_access)
        thread.start()
        thread.join(timeout=5.0)

        assert result[0] is True

    def test_store_image_allowed_from_worker_thread(self, qapp: QApplication) -> None:
        """Test that store_image works from any thread."""
        cache = ThreadSafeThumbnailCache()
        stored: list[bool] = []

        def worker_store() -> None:
            try:
                image = QImage(50, 50, QImage.Format.Format_RGB32)
                image.fill(QColor(200, 100, 50))
                cache.store_image("worker_stored", image)
                stored.append(True)
            except Exception:
                stored.append(False)

        thread = threading.Thread(target=worker_store)
        thread.start()
        thread.join(timeout=5.0)

        assert stored[0] is True
        assert cache.has_image("worker_stored")

    def test_has_image_allowed_from_worker_thread(self, qapp: QApplication) -> None:
        """Test that has_image works from any thread."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(50, 50, QImage.Format.Format_RGB32)
        cache.store_image("exists", image)

        results: list[tuple[bool, bool]] = []

        def worker_check() -> None:
            exists = cache.has_image("exists")
            not_exists = cache.has_image("not_exists")
            results.append((exists, not_exists))

        thread = threading.Thread(target=worker_check)
        thread.start()
        thread.join(timeout=5.0)

        assert results[0] == (True, False)

    def test_create_thread_safe_pixmap_returns_none_from_worker(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """Test helper function returns None from worker thread."""
        image_path = tmp_path / "test.png"
        image = QImage(50, 50, QImage.Format.Format_RGB32)
        image.fill(QColor(100, 100, 100))
        image.save(str(image_path))

        result: list[QPixmap | None] = []

        def worker_attempt() -> None:
            pixmap = create_thread_safe_pixmap(image_path)
            result.append(pixmap)

        thread = threading.Thread(target=worker_attempt)
        thread.start()
        thread.join(timeout=5.0)

        assert result[0] is None

    def test_create_thread_safe_pixmap_works_on_main_thread(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """Test helper function works on main thread."""
        image_path = tmp_path / "test.png"
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor(50, 100, 150))
        image.save(str(image_path))

        pixmap = create_thread_safe_pixmap(image_path)

        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.width() == 100

    def test_create_thread_safe_pixmap_with_scaling(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """Test helper function scales pixmap correctly."""
        image_path = tmp_path / "test.png"
        image = QImage(200, 200, QImage.Format.Format_RGB32)
        image.fill(QColor(75, 125, 175))
        image.save(str(image_path))

        pixmap = create_thread_safe_pixmap(image_path, size=(50, 50))

        assert pixmap is not None
        assert not pixmap.isNull()
        # Should be scaled (aspect ratio maintained)
        assert pixmap.width() <= 50
        assert pixmap.height() <= 50


class TestConcurrentAccess:
    """Test concurrent read/write operations."""

    def test_concurrent_image_stores(self, qapp: QApplication) -> None:
        """Test multiple threads storing images concurrently."""
        cache = ThreadSafeThumbnailCache()
        num_threads = 10
        images_per_thread = 50
        errors: list[Exception] = []

        def store_images(thread_id: int) -> None:
            try:
                for i in range(images_per_thread):
                    key = f"thread_{thread_id}_image_{i}"
                    image = QImage(20, 20, QImage.Format.Format_RGB32)
                    image.fill(QColor(thread_id * 20, i * 5, 128))
                    cache.store_image(key, image)
            except Exception as e:
                errors.append(e)

        threads = []
        for tid in range(num_threads):
            t = threading.Thread(target=store_images, args=(tid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0, f"Errors during concurrent stores: {errors}"
        stats = cache.get_stats()
        assert stats["image_count"] == num_threads * images_per_thread

    def test_concurrent_reads_and_writes(self, qapp: QApplication) -> None:
        """Test simultaneous reads while other threads write."""
        cache = ThreadSafeThumbnailCache()
        num_writers = 5
        num_readers = 10
        operations_per_thread = 30
        errors: list[tuple[str, int, Exception]] = []

        # Pre-populate some keys
        for i in range(20):
            image = QImage(10, 10, QImage.Format.Format_RGB32)
            cache.store_image(f"initial_{i}", image)

        def writer(writer_id: int) -> None:
            try:
                for i in range(operations_per_thread):
                    key = f"writer_{writer_id}_{i}"
                    image = QImage(10, 10, QImage.Format.Format_RGB32)
                    cache.store_image(key, image)
            except Exception as e:
                errors.append(("writer", writer_id, e))

        def reader(reader_id: int) -> None:
            try:
                for i in range(operations_per_thread):
                    key = f"initial_{i % 20}"
                    _ = cache.get_image(key)
                    _ = cache.has_image(key)
            except Exception as e:
                errors.append(("reader", reader_id, e))

        threads = [
            threading.Thread(target=writer, args=(wid,)) for wid in range(num_writers)
        ]
        threads.extend(
            threading.Thread(target=reader, args=(rid,)) for rid in range(num_readers)
        )

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert len(errors) == 0, f"Errors: {errors}"

    def test_concurrent_has_image_checks(self, qapp: QApplication) -> None:
        """Test concurrent has_image() calls are thread-safe."""
        cache = ThreadSafeThumbnailCache()

        # Store some images
        for i in range(50):
            image = QImage(10, 10, QImage.Format.Format_RGB32)
            cache.store_image(f"key_{i}", image)

        results: list[list[bool]] = []
        errors: list[Exception] = []

        def check_existence(thread_id: int) -> None:
            try:
                local_results = []
                for i in range(50):
                    exists = cache.has_image(f"key_{i}")
                    local_results.append(exists)
                results.append(local_results)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=check_existence, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0
        # All threads should see the same state
        for thread_results in results:
            assert all(thread_results)  # All should be True

    def test_concurrent_get_stats(self, qapp: QApplication) -> None:
        """Test get_stats is thread-safe during modifications."""
        cache = ThreadSafeThumbnailCache()
        num_threads = 10
        operations_per_thread = 50
        stats_results: list[dict[str, int]] = []
        errors: list[Exception] = []

        def modifier(thread_id: int) -> None:
            try:
                for i in range(operations_per_thread):
                    key = f"t{thread_id}_i{i}"
                    image = QImage(10, 10, QImage.Format.Format_RGB32)
                    cache.store_image(key, image)
                    if i % 10 == 0:
                        stats = cache.get_stats()
                        # Stats should be internally consistent
                        assert stats["total_count"] == stats["image_count"]
                        stats_results.append(stats)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=modifier, args=(i,)) for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert len(errors) == 0
        # All stat snapshots should be internally consistent
        for stats in stats_results:
            assert stats["total_count"] == stats["image_count"]


class TestRaceConditionScenarios:
    """Test specific race condition patterns."""

    def test_store_same_key_from_multiple_threads(self, qapp: QApplication) -> None:
        """Test multiple threads updating the same key concurrently."""
        cache = ThreadSafeThumbnailCache()
        key = "contested_key"
        num_threads = 20
        updates_per_thread = 100
        errors: list[Exception] = []

        def update_key(thread_id: int) -> None:
            try:
                for _ in range(updates_per_thread):
                    image = QImage(10, 10, QImage.Format.Format_RGB32)
                    # Use thread_id as a color to identify which thread wrote last
                    image.fill(QColor(thread_id, thread_id, thread_id))
                    cache.store_image(key, image)
            except Exception as e:
                errors.append(e)

        threads = []
        for tid in range(num_threads):
            t = threading.Thread(target=update_key, args=(tid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0
        # Should have exactly one image (last write wins)
        stats = cache.get_stats()
        assert stats["image_count"] == 1
        assert cache.has_image(key)

    def test_pixmap_cache_invalidation_on_image_update(
        self, qapp: QApplication
    ) -> None:
        """Test that pixmap cache is properly invalidated on image update."""
        cache = ThreadSafeThumbnailCache()
        key = "pixmap_race"

        # Store initial image
        initial_image = QImage(100, 100, QImage.Format.Format_RGB32)
        initial_image.fill(QColor(255, 0, 0))  # Red
        cache.store_image(key, initial_image)

        # Get pixmap (should cache it)
        pixmap1 = cache.get_pixmap(key)
        assert pixmap1 is not None

        stats_before = cache.get_stats()
        assert stats_before["pixmap_count"] == 1

        # Update image from worker thread
        update_done = threading.Event()

        def update_image() -> None:
            new_image = QImage(100, 100, QImage.Format.Format_RGB32)
            new_image.fill(QColor(0, 255, 0))  # Green
            cache.store_image(key, new_image)
            update_done.set()

        thread = threading.Thread(target=update_image)
        thread.start()
        update_done.wait(timeout=5.0)
        thread.join()

        # Pixmap cache should be invalidated
        stats_after = cache.get_stats()
        assert stats_after["pixmap_count"] == 0  # Pixmap was cleared

        # Getting pixmap again should create new one from updated image
        pixmap2 = cache.get_pixmap(key)
        assert pixmap2 is not None

    def test_remove_while_reading(self, qapp: QApplication) -> None:
        """Test removing a key while other threads are reading it."""
        cache = ThreadSafeThumbnailCache()
        num_readers = 10
        read_iterations = 50
        errors: list[Exception] = []

        # Populate cache
        for i in range(50):
            image = QImage(10, 10, QImage.Format.Format_RGB32)
            cache.store_image(f"key_{i}", image)

        def reader() -> None:
            try:
                for _ in range(read_iterations):
                    for i in range(50):
                        _ = cache.get_image(f"key_{i}")
                        # Result may be None if removed - that's OK
            except Exception as e:
                errors.append(e)

        def remover() -> None:
            try:
                # Remove keys while readers are active
                time.sleep(0.001)  # Let readers start
                for i in range(0, 50, 2):  # Remove even keys
                    cache.remove(f"key_{i}")
            except Exception as e:
                errors.append(e)

        reader_threads = [threading.Thread(target=reader) for _ in range(num_readers)]
        remover_thread = threading.Thread(target=remover)

        for t in reader_threads:
            t.start()
        remover_thread.start()

        for t in reader_threads:
            t.join(timeout=15.0)
        remover_thread.join(timeout=5.0)

        # No exceptions should occur
        assert len(errors) == 0, f"Errors during concurrent remove: {errors}"

    def test_store_and_remove_same_key_concurrently(
        self, qapp: QApplication
    ) -> None:
        """Test storing and removing the same key from different threads."""
        cache = ThreadSafeThumbnailCache()
        key = "contested"
        num_iterations = 100
        errors: list[Exception] = []

        def storer() -> None:
            try:
                for _ in range(num_iterations):
                    image = QImage(10, 10, QImage.Format.Format_RGB32)
                    cache.store_image(key, image)
                    simulate_work_without_sleep(1)
            except Exception as e:
                errors.append(e)

        def remover() -> None:
            try:
                for _ in range(num_iterations):
                    cache.remove(key)
                    simulate_work_without_sleep(1)
            except Exception as e:
                errors.append(e)

        store_thread = threading.Thread(target=storer)
        remove_thread = threading.Thread(target=remover)

        store_thread.start()
        remove_thread.start()

        store_thread.join(timeout=10.0)
        remove_thread.join(timeout=10.0)

        assert len(errors) == 0


class TestCacheEvictionUnderConcurrency:
    """Test cache clear/remove during concurrent access."""

    def test_clear_during_concurrent_writes(self, qapp: QApplication) -> None:
        """Test clearing cache while writers are active."""
        cache = ThreadSafeThumbnailCache()
        num_writers = 5
        writes_per_thread = 100
        num_clears = 10
        errors: list[tuple[str, Exception]] = []

        def writer(writer_id: int) -> None:
            try:
                for i in range(writes_per_thread):
                    key = f"w{writer_id}_i{i}"
                    image = QImage(10, 10, QImage.Format.Format_RGB32)
                    cache.store_image(key, image)
            except Exception as e:
                errors.append(("writer", e))

        def clearer() -> None:
            try:
                for _ in range(num_clears):
                    time.sleep(0.005)  # Brief delay between clears
                    cache.clear()
            except Exception as e:
                errors.append(("clearer", e))

        writers = [threading.Thread(target=writer, args=(i,)) for i in range(num_writers)]
        clearer_thread = threading.Thread(target=clearer)

        for w in writers:
            w.start()
        clearer_thread.start()

        for w in writers:
            w.join(timeout=15.0)
        clearer_thread.join(timeout=5.0)

        assert len(errors) == 0, f"Errors: {errors}"

    def test_clear_during_concurrent_reads(self, qapp: QApplication) -> None:
        """Test clearing cache while readers are active."""
        cache = ThreadSafeThumbnailCache()
        num_readers = 10
        reads_per_thread = 100
        errors: list[Exception] = []

        # Pre-populate
        for i in range(50):
            image = QImage(10, 10, QImage.Format.Format_RGB32)
            cache.store_image(f"key_{i}", image)

        def reader() -> None:
            try:
                for _ in range(reads_per_thread):
                    for i in range(50):
                        _ = cache.get_image(f"key_{i}")
                        _ = cache.has_image(f"key_{i}")
            except Exception as e:
                errors.append(e)

        def clearer() -> None:
            try:
                time.sleep(0.002)
                cache.clear()
            except Exception as e:
                errors.append(e)

        reader_threads = [threading.Thread(target=reader) for _ in range(num_readers)]
        clearer_thread = threading.Thread(target=clearer)

        for t in reader_threads:
            t.start()
        clearer_thread.start()

        for t in reader_threads:
            t.join(timeout=15.0)
        clearer_thread.join(timeout=5.0)

        assert len(errors) == 0


class TestMemoryManagement:
    """Test memory cleanup and leak prevention."""

    def test_remove_clears_both_caches(self, qapp: QApplication) -> None:
        """Test remove() clears both image and pixmap caches."""
        cache = ThreadSafeThumbnailCache()
        image = QImage(100, 100, QImage.Format.Format_RGB32)

        cache.store_image("key", image)
        _ = cache.get_pixmap("key")  # Create pixmap entry

        stats_before = cache.get_stats()
        assert stats_before["image_count"] == 1
        assert stats_before["pixmap_count"] == 1

        cache.remove("key")

        stats_after = cache.get_stats()
        assert stats_after["image_count"] == 0
        assert stats_after["pixmap_count"] == 0

    def test_store_image_invalidates_pixmap(self, qapp: QApplication) -> None:
        """Test that updating an image invalidates cached pixmap."""
        cache = ThreadSafeThumbnailCache()

        image1 = QImage(100, 100, QImage.Format.Format_RGB32)
        image1.fill(QColor(255, 0, 0))
        cache.store_image("key", image1)
        _ = cache.get_pixmap("key")

        stats = cache.get_stats()
        assert stats["pixmap_count"] == 1

        # Update image
        image2 = QImage(100, 100, QImage.Format.Format_RGB32)
        image2.fill(QColor(0, 255, 0))
        cache.store_image("key", image2)

        stats = cache.get_stats()
        assert stats["pixmap_count"] == 0  # Pixmap invalidated

    def test_large_cache_handles_many_entries(self, qapp: QApplication) -> None:
        """Test cache handles large number of entries."""
        cache = ThreadSafeThumbnailCache()
        num_entries = 500

        # Store many images
        for i in range(num_entries):
            image = QImage(10, 10, QImage.Format.Format_RGB32)
            cache.store_image(f"key_{i}", image)

        stats = cache.get_stats()
        assert stats["image_count"] == num_entries

        # Clear should free all
        cache.clear()
        stats = cache.get_stats()
        assert stats["total_count"] == 0

    def test_overwrite_existing_key_frees_old_image(
        self, qapp: QApplication
    ) -> None:
        """Test that overwriting a key replaces the old image."""
        cache = ThreadSafeThumbnailCache()

        # Store initial image
        image1 = QImage(50, 50, QImage.Format.Format_RGB32)
        image1.fill(QColor(255, 0, 0))
        cache.store_image("key", image1)

        # Overwrite with new image
        image2 = QImage(100, 100, QImage.Format.Format_RGB32)
        image2.fill(QColor(0, 255, 0))
        cache.store_image("key", image2)

        # Should still have only 1 entry
        stats = cache.get_stats()
        assert stats["image_count"] == 1

        # Should get the new image
        retrieved = cache.get_image("key")
        assert retrieved is not None
        assert retrieved.width() == 100  # New image dimensions


class TestStressConditions:
    """Stress tests under high load."""

    def test_high_contention_stress(self, qapp: QApplication) -> None:
        """Test cache under extreme concurrent access."""
        cache = ThreadSafeThumbnailCache()
        num_threads = 30
        operations_per_thread = 100
        errors: list[tuple[int, Exception]] = []

        def mixed_operations(thread_id: int) -> None:
            try:
                for i in range(operations_per_thread):
                    op = i % 4
                    key = f"stress_{thread_id}_{i % 20}"
                    if op == 0:
                        image = QImage(5, 5, QImage.Format.Format_RGB32)
                        cache.store_image(key, image)
                    elif op == 1:
                        _ = cache.get_image(key)
                    elif op == 2:
                        _ = cache.has_image(key)
                    else:
                        cache.remove(key)
            except Exception as e:
                errors.append((thread_id, e))

        threads = []
        for tid in range(num_threads):
            t = threading.Thread(target=mixed_operations, args=(tid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30.0)

        assert len(errors) == 0, f"Stress test errors: {errors}"

    def test_executor_pool_pattern(self, qapp: QApplication) -> None:
        """Test using ThreadPoolExecutor like production code."""
        cache = ThreadSafeThumbnailCache()
        num_workers = 8
        tasks_per_worker = 30
        results: list[str] = []

        def cache_task(task_id: int) -> str:
            """Simulate a cache task."""
            key = f"task_{task_id}"
            image = QImage(10, 10, QImage.Format.Format_RGB32)
            image.fill(QColor(task_id % 256, 128, 64))
            cache.store_image(key, image)

            # Read it back
            if cache.has_image(key):
                img = cache.get_image(key)
                if img is not None:
                    return f"success_{task_id}"
            return f"fail_{task_id}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(cache_task, i)
                for i in range(num_workers * tasks_per_worker)
            ]
            results.extend(
                future.result()
                for future in concurrent.futures.as_completed(futures, timeout=30.0)
            )

        success_count = sum(1 for r in results if r.startswith("success"))
        assert success_count == num_workers * tasks_per_worker

    def test_rapid_store_clear_cycle(self, qapp: QApplication) -> None:
        """Test rapid store/clear cycles for stability."""
        cache = ThreadSafeThumbnailCache()
        cycles = 50
        entries_per_cycle = 20

        for cycle in range(cycles):
            # Store entries
            for i in range(entries_per_cycle):
                image = QImage(10, 10, QImage.Format.Format_RGB32)
                cache.store_image(f"cycle_{cycle}_key_{i}", image)

            # Verify entries exist
            stats = cache.get_stats()
            assert stats["image_count"] == entries_per_cycle

            # Clear
            cache.clear()
            stats = cache.get_stats()
            assert stats["image_count"] == 0

    @pytest.mark.parametrize("iteration", range(5))
    def test_race_detection_repeated(
        self, iteration: int, qapp: QApplication
    ) -> None:
        """Run race condition test multiple times to catch intermittent issues."""
        cache = ThreadSafeThumbnailCache()
        key = "race_key"
        num_threads = 10
        iterations_per_thread = 50
        errors: list[Exception] = []

        barrier = threading.Barrier(num_threads)

        def contestant(thread_id: int) -> None:
            try:
                barrier.wait(timeout=5.0)  # Synchronize start
                for _ in range(iterations_per_thread):
                    image = QImage(5, 5, QImage.Format.Format_RGB32)
                    cache.store_image(key, image)
                    _ = cache.get_image(key)
                    _ = cache.has_image(key)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=contestant, args=(i,)) for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert len(errors) == 0, f"Race condition detected in iteration {iteration}: {errors}"
