"""Unit tests for ScrubFrameCache - thread-safe LRU cache for scrub preview frames.

Tests focus on:
- Basic store/retrieve operations
- LRU eviction at shot and frame levels
- Thread safety guarantees
- QPixmap main thread enforcement
- Concurrent access patterns
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QImage

from scrub_frame_cache import ScrubFrameCache


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

pytestmark = [pytest.mark.unit, pytest.mark.qt]


def make_test_image(color: int = 0xFF0000FF) -> QImage:
    """Create a simple test QImage with specified ARGB color."""
    img = QImage(100, 100, QImage.Format.Format_ARGB32)
    img.fill(color)
    return img


class TestBasicOperations:
    """Basic functionality tests (single-threaded)."""

    def test_store_and_retrieve_image(self, qapp: QApplication) -> None:
        """Test basic store/retrieve cycle."""
        cache = ScrubFrameCache()
        image = make_test_image()

        cache.store("show/seq/shot1", 1001, image)

        assert cache.has_frame("show/seq/shot1", 1001)
        retrieved = cache.get_image("show/seq/shot1", 1001)
        assert retrieved is not None
        assert not retrieved.isNull()

    def test_get_image_nonexistent_shot(self, qapp: QApplication) -> None:
        """Test get_image returns None for missing shot."""
        cache = ScrubFrameCache()
        result = cache.get_image("nonexistent/shot", 1001)
        assert result is None

    def test_get_image_nonexistent_frame(self, qapp: QApplication) -> None:
        """Test get_image returns None for missing frame in existing shot."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())

        result = cache.get_image("show/seq/shot1", 9999)
        assert result is None

    def test_has_frame_returns_correct_value(self, qapp: QApplication) -> None:
        """Test has_frame returns True for cached, False for missing."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())

        assert cache.has_frame("show/seq/shot1", 1001)
        assert not cache.has_frame("show/seq/shot1", 1002)
        assert not cache.has_frame("show/seq/shot2", 1001)

    def test_get_pixmap_converts_from_image(self, qapp: QApplication) -> None:
        """Test QImage to QPixmap conversion on main thread."""
        cache = ScrubFrameCache()
        image = make_test_image()

        cache.store("show/seq/shot1", 1001, image)
        pixmap = cache.get_pixmap("show/seq/shot1", 1001)

        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.width() == 100

    def test_get_pixmap_caches_result(self, qapp: QApplication) -> None:
        """Test that pixmap is cached after first conversion."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())

        # First retrieval creates pixmap
        _ = cache.get_pixmap("show/seq/shot1", 1001)
        stats1 = cache.get_stats()
        assert stats1["total_pixmaps"] == 1

        # Second retrieval uses cached pixmap
        _ = cache.get_pixmap("show/seq/shot1", 1001)
        stats2 = cache.get_stats()
        assert stats2["total_pixmaps"] == 1  # Still 1, not 2

    def test_get_pixmap_nonexistent_returns_none(self, qapp: QApplication) -> None:
        """Test get_pixmap returns None for missing key."""
        cache = ScrubFrameCache()
        result = cache.get_pixmap("nonexistent", 1001)
        assert result is None

    def test_get_cached_frames(self, qapp: QApplication) -> None:
        """Test getting list of cached frame numbers."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot1", 1003, make_test_image())

        frames = cache.get_cached_frames("show/seq/shot1")
        assert set(frames) == {1001, 1002, 1003}

    def test_get_cached_frames_empty_shot(self, qapp: QApplication) -> None:
        """Test get_cached_frames returns empty list for unknown shot."""
        cache = ScrubFrameCache()
        frames = cache.get_cached_frames("nonexistent")
        assert frames == []

    def test_get_stats_returns_correct_counts(self, qapp: QApplication) -> None:
        """Test cache statistics."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot2", 1001, make_test_image())
        _ = cache.get_pixmap("show/seq/shot1", 1001)

        stats = cache.get_stats()
        assert stats["shot_count"] == 2
        assert stats["total_frames"] == 3
        assert stats["total_pixmaps"] == 1

    def test_clear_shot_removes_all_frames(self, qapp: QApplication) -> None:
        """Test clearing a single shot's frames."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot2", 1001, make_test_image())
        _ = cache.get_pixmap("show/seq/shot1", 1001)

        cache.clear_shot("show/seq/shot1")

        assert not cache.has_frame("show/seq/shot1", 1001)
        assert not cache.has_frame("show/seq/shot1", 1002)
        assert cache.has_frame("show/seq/shot2", 1001)
        stats = cache.get_stats()
        assert stats["shot_count"] == 1
        assert stats["total_frames"] == 1

    def test_clear_all_removes_everything(self, qapp: QApplication) -> None:
        """Test clearing all cached frames."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot2", 1001, make_test_image())
        _ = cache.get_pixmap("show/seq/shot1", 1001)

        cache.clear_all()

        assert not cache.has_frame("show/seq/shot1", 1001)
        assert not cache.has_frame("show/seq/shot2", 1001)
        stats = cache.get_stats()
        assert stats["shot_count"] == 0
        assert stats["total_frames"] == 0
        assert stats["total_pixmaps"] == 0


class TestLRUEviction:
    """Test LRU eviction behavior at shot and frame levels."""

    def test_frame_eviction_when_limit_exceeded(self, qapp: QApplication) -> None:
        """Test oldest frame is evicted when per-shot limit is reached."""
        cache = ScrubFrameCache(max_frames_per_shot=3, max_shots=10)

        # Store 3 frames (at limit)
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot1", 1003, make_test_image())

        assert cache.has_frame("show/seq/shot1", 1001)
        assert cache.has_frame("show/seq/shot1", 1002)
        assert cache.has_frame("show/seq/shot1", 1003)

        # Store 4th frame - should evict 1001 (oldest)
        cache.store("show/seq/shot1", 1004, make_test_image())

        assert not cache.has_frame("show/seq/shot1", 1001)
        assert cache.has_frame("show/seq/shot1", 1002)
        assert cache.has_frame("show/seq/shot1", 1003)
        assert cache.has_frame("show/seq/shot1", 1004)

    def test_accessing_frame_moves_to_end_of_lru(self, qapp: QApplication) -> None:
        """Test that accessing a frame makes it less likely to be evicted."""
        cache = ScrubFrameCache(max_frames_per_shot=3, max_shots=10)

        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot1", 1003, make_test_image())

        # Access 1001 - moves it to end (most recently used)
        _ = cache.get_image("show/seq/shot1", 1001)

        # Store 4th frame - should evict 1002 (now oldest)
        cache.store("show/seq/shot1", 1004, make_test_image())

        assert cache.has_frame("show/seq/shot1", 1001)  # Was accessed, not evicted
        assert not cache.has_frame("show/seq/shot1", 1002)  # Evicted
        assert cache.has_frame("show/seq/shot1", 1003)
        assert cache.has_frame("show/seq/shot1", 1004)

    def test_shot_eviction_when_limit_exceeded(self, qapp: QApplication) -> None:
        """Test oldest shot is evicted when shot limit is reached."""
        cache = ScrubFrameCache(max_frames_per_shot=10, max_shots=2)

        # Store frames in 2 shots (at limit)
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot2", 1001, make_test_image())

        assert cache.has_frame("show/seq/shot1", 1001)
        assert cache.has_frame("show/seq/shot2", 1001)

        # Store frame in 3rd shot - should evict shot1 (oldest)
        cache.store("show/seq/shot3", 1001, make_test_image())

        assert not cache.has_frame("show/seq/shot1", 1001)  # Shot evicted
        assert cache.has_frame("show/seq/shot2", 1001)
        assert cache.has_frame("show/seq/shot3", 1001)

    def test_accessing_shot_moves_to_end_of_lru(self, qapp: QApplication) -> None:
        """Test that accessing a shot makes it less likely to be evicted."""
        cache = ScrubFrameCache(max_frames_per_shot=10, max_shots=2)

        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot2", 1001, make_test_image())

        # Access shot1 - moves it to end (most recently used)
        _ = cache.get_image("show/seq/shot1", 1001)

        # Store frame in 3rd shot - should evict shot2 (now oldest)
        cache.store("show/seq/shot3", 1001, make_test_image())

        assert cache.has_frame("show/seq/shot1", 1001)  # Was accessed, not evicted
        assert not cache.has_frame("show/seq/shot2", 1001)  # Evicted
        assert cache.has_frame("show/seq/shot3", 1001)

    def test_store_same_frame_updates_not_counts_twice(
        self, qapp: QApplication
    ) -> None:
        """Test storing same frame again doesn't count as new frame."""
        cache = ScrubFrameCache(max_frames_per_shot=3, max_shots=10)

        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot1", 1003, make_test_image())

        # Update existing frame - should NOT evict anything
        cache.store("show/seq/shot1", 1001, make_test_image(0xFFFF0000))

        # All original frames should still exist
        assert cache.has_frame("show/seq/shot1", 1001)
        assert cache.has_frame("show/seq/shot1", 1002)
        assert cache.has_frame("show/seq/shot1", 1003)

    def test_pixmap_cache_invalidated_on_frame_eviction(
        self, qapp: QApplication
    ) -> None:
        """Test that pixmap cache is cleared when frame is evicted."""
        cache = ScrubFrameCache(max_frames_per_shot=3, max_shots=10)

        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot1", 1003, make_test_image())

        # Create pixmap for frame 1001
        _ = cache.get_pixmap("show/seq/shot1", 1001)
        stats = cache.get_stats()
        assert stats["total_pixmaps"] == 1

        # Access frames 1002 and 1003 to make them "more recent" than 1001
        # (get_pixmap internally calls get_image which moves frame to end of LRU)
        _ = cache.get_image("show/seq/shot1", 1002)
        _ = cache.get_image("show/seq/shot1", 1003)

        # Now 1001 is oldest, so adding 1004 evicts 1001
        cache.store("show/seq/shot1", 1004, make_test_image())

        stats = cache.get_stats()
        assert stats["total_pixmaps"] == 0


class TestMainThreadAssertion:
    """Test QPixmap main thread enforcement."""

    def test_get_pixmap_raises_on_worker_thread(self, qapp: QApplication) -> None:
        """Test that get_pixmap raises RuntimeError from worker thread."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())

        error_raised: list[str] = []

        def worker_attempt() -> None:
            try:
                _ = cache.get_pixmap("show/seq/shot1", 1001)
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
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())

        result: list[bool] = []

        def worker_access() -> None:
            retrieved = cache.get_image("show/seq/shot1", 1001)
            result.append(retrieved is not None)

        thread = threading.Thread(target=worker_access)
        thread.start()
        thread.join(timeout=5.0)

        assert result[0] is True

    def test_store_allowed_from_worker_thread(self, qapp: QApplication) -> None:
        """Test that store works from any thread."""
        cache = ScrubFrameCache()
        stored: list[bool] = []

        def worker_store() -> None:
            try:
                image = make_test_image()
                cache.store("show/seq/shot1", 1001, image)
                stored.append(True)
            except Exception:
                stored.append(False)

        thread = threading.Thread(target=worker_store)
        thread.start()
        thread.join(timeout=5.0)

        assert stored[0] is True
        assert cache.has_frame("show/seq/shot1", 1001)

    def test_has_frame_allowed_from_worker_thread(self, qapp: QApplication) -> None:
        """Test that has_frame works from any thread."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())

        results: list[tuple[bool, bool]] = []

        def worker_check() -> None:
            exists = cache.has_frame("show/seq/shot1", 1001)
            not_exists = cache.has_frame("show/seq/shot1", 9999)
            results.append((exists, not_exists))

        thread = threading.Thread(target=worker_check)
        thread.start()
        thread.join(timeout=5.0)

        assert results[0] == (True, False)


class TestConcurrentAccess:
    """Test concurrent read/write operations."""

    def test_concurrent_stores_to_same_shot(self, qapp: QApplication) -> None:
        """Test multiple threads storing frames to same shot concurrently."""
        cache = ScrubFrameCache(max_frames_per_shot=100, max_shots=10)
        num_threads = 10
        frames_per_thread = 10
        errors: list[Exception] = []

        def store_frames(thread_id: int) -> None:
            try:
                for i in range(frames_per_thread):
                    frame_num = thread_id * 1000 + i
                    cache.store("show/seq/shot1", frame_num, make_test_image())
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=store_frames, args=(tid,))
            for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0, f"Errors during concurrent stores: {errors}"
        stats = cache.get_stats()
        assert stats["total_frames"] == num_threads * frames_per_thread

    def test_concurrent_stores_to_different_shots(self, qapp: QApplication) -> None:
        """Test multiple threads storing frames to different shots."""
        cache = ScrubFrameCache(max_frames_per_shot=20, max_shots=20)
        num_threads = 10
        frames_per_thread = 5
        errors: list[Exception] = []

        def store_frames(thread_id: int) -> None:
            try:
                shot_key = f"show/seq/shot{thread_id}"
                for i in range(frames_per_thread):
                    cache.store(shot_key, 1000 + i, make_test_image())
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=store_frames, args=(tid,))
            for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0
        stats = cache.get_stats()
        assert stats["shot_count"] == num_threads
        assert stats["total_frames"] == num_threads * frames_per_thread

    def test_concurrent_reads_while_writing(self, qapp: QApplication) -> None:
        """Test simultaneous reads while other threads write."""
        cache = ScrubFrameCache(max_frames_per_shot=50, max_shots=10)
        num_writers = 3
        num_readers = 5
        operations_per_thread = 30
        errors: list[Exception] = []

        # Pre-populate
        for i in range(20):
            cache.store("show/seq/shot1", 1000 + i, make_test_image())

        def writer(writer_id: int) -> None:
            try:
                for i in range(operations_per_thread):
                    cache.store("show/seq/shot1", 2000 + writer_id * 100 + i, make_test_image())
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(operations_per_thread):
                    for i in range(20):
                        _ = cache.get_image("show/seq/shot1", 1000 + i)
                        _ = cache.has_frame("show/seq/shot1", 1000 + i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(wid,)) for wid in range(num_writers)
        ]
        threads.extend(threading.Thread(target=reader) for _ in range(num_readers))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert len(errors) == 0, f"Errors: {errors}"

    def test_concurrent_clear_shot(self, qapp: QApplication) -> None:
        """Test clear_shot is thread-safe during concurrent access."""
        cache = ScrubFrameCache(max_frames_per_shot=100, max_shots=10)
        errors: list[Exception] = []

        # Pre-populate
        for i in range(50):
            cache.store("show/seq/shot1", 1000 + i, make_test_image())

        def reader() -> None:
            try:
                for _ in range(100):
                    _ = cache.get_image("show/seq/shot1", 1025)
                    _ = cache.has_frame("show/seq/shot1", 1025)
            except Exception as e:
                errors.append(e)

        def clearer() -> None:
            try:
                import time
                time.sleep(0.001)
                cache.clear_shot("show/seq/shot1")
            except Exception as e:
                errors.append(e)

        reader_threads = [threading.Thread(target=reader) for _ in range(5)]
        clearer_thread = threading.Thread(target=clearer)

        for t in reader_threads:
            t.start()
        clearer_thread.start()

        for t in reader_threads:
            t.join(timeout=10.0)
        clearer_thread.join(timeout=5.0)

        assert len(errors) == 0


class TestStoreInvalidatesPixmap:
    """Test that updating a frame invalidates cached pixmap."""

    def test_store_invalidates_existing_pixmap(self, qapp: QApplication) -> None:
        """Test that storing same frame invalidates cached pixmap."""
        cache = ScrubFrameCache()

        # Store and get pixmap
        image1 = make_test_image(0xFF0000FF)  # Blue
        cache.store("show/seq/shot1", 1001, image1)
        _ = cache.get_pixmap("show/seq/shot1", 1001)

        stats = cache.get_stats()
        assert stats["total_pixmaps"] == 1

        # Update same frame
        image2 = make_test_image(0xFFFF0000)  # Red
        cache.store("show/seq/shot1", 1001, image2)

        # Pixmap should be invalidated
        stats = cache.get_stats()
        assert stats["total_pixmaps"] == 0

    def test_store_different_frame_preserves_other_pixmaps(
        self, qapp: QApplication
    ) -> None:
        """Test storing different frame doesn't affect other pixmaps."""
        cache = ScrubFrameCache()

        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        _ = cache.get_pixmap("show/seq/shot1", 1001)

        stats = cache.get_stats()
        assert stats["total_pixmaps"] == 1

        # Store different frame
        cache.store("show/seq/shot1", 1003, make_test_image())

        # Pixmap for 1001 should still exist
        stats = cache.get_stats()
        assert stats["total_pixmaps"] == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_shot_key(self, qapp: QApplication) -> None:
        """Test handling of empty shot key."""
        cache = ScrubFrameCache()
        cache.store("", 1001, make_test_image())

        assert cache.has_frame("", 1001)
        assert cache.get_image("", 1001) is not None

    def test_zero_frame_number(self, qapp: QApplication) -> None:
        """Test handling of frame number 0."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 0, make_test_image())

        assert cache.has_frame("show/seq/shot1", 0)
        assert cache.get_image("show/seq/shot1", 0) is not None

    def test_negative_frame_number(self, qapp: QApplication) -> None:
        """Test handling of negative frame numbers."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", -1, make_test_image())

        assert cache.has_frame("show/seq/shot1", -1)
        assert cache.get_image("show/seq/shot1", -1) is not None

    def test_very_large_frame_number(self, qapp: QApplication) -> None:
        """Test handling of very large frame numbers."""
        cache = ScrubFrameCache()
        large_frame = 999999999
        cache.store("show/seq/shot1", large_frame, make_test_image())

        assert cache.has_frame("show/seq/shot1", large_frame)

    def test_cache_with_min_limits(self, qapp: QApplication) -> None:
        """Test cache with minimum possible limits."""
        cache = ScrubFrameCache(max_frames_per_shot=1, max_shots=1)

        cache.store("show/seq/shot1", 1001, make_test_image())
        assert cache.has_frame("show/seq/shot1", 1001)

        # Second frame evicts first
        cache.store("show/seq/shot1", 1002, make_test_image())
        assert not cache.has_frame("show/seq/shot1", 1001)
        assert cache.has_frame("show/seq/shot1", 1002)

        # Second shot evicts first
        cache.store("show/seq/shot2", 1001, make_test_image())
        assert not cache.has_frame("show/seq/shot1", 1002)
        assert cache.has_frame("show/seq/shot2", 1001)

    def test_clear_shot_nonexistent(self, qapp: QApplication) -> None:
        """Test clear_shot on nonexistent shot doesn't raise."""
        cache = ScrubFrameCache()
        cache.clear_shot("nonexistent")  # Should not raise

    def test_clear_all_on_empty_cache(self, qapp: QApplication) -> None:
        """Test clear_all on empty cache doesn't raise."""
        cache = ScrubFrameCache()
        cache.clear_all()  # Should not raise

        stats = cache.get_stats()
        assert stats["shot_count"] == 0
