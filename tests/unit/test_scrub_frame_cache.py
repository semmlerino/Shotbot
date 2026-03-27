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

from scrub.scrub_frame_cache import ScrubFrameCache


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

    @pytest.mark.parametrize(
        ("method", "shot_key", "frame", "pre_store"),
        [
            pytest.param("get_image", "nonexistent/shot", 1001, False, id="get_image_nonexistent_shot"),
            pytest.param("get_image", "show/seq/shot1", 9999, True, id="get_image_nonexistent_frame"),
            pytest.param("get_pixmap", "nonexistent", 1001, False, id="get_pixmap_nonexistent"),
        ],
    )
    def test_get_returns_none_for_missing(
        self, qapp: QApplication, method: str, shot_key: str, frame: int, pre_store: bool
    ) -> None:
        """Test get_image and get_pixmap return None for missing shot or frame."""
        cache = ScrubFrameCache()
        if pre_store:
            cache.store("show/seq/shot1", 1001, make_test_image())
        result = getattr(cache, method)(shot_key, frame)
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

    def test_get_cached_frames(self, qapp: QApplication) -> None:
        """Test getting list of cached frame numbers."""
        cache = ScrubFrameCache()
        cache.store("show/seq/shot1", 1001, make_test_image())
        cache.store("show/seq/shot1", 1002, make_test_image())
        cache.store("show/seq/shot1", 1003, make_test_image())

        frames = cache.get_cached_frames("show/seq/shot1")
        assert set(frames) == {1001, 1002, 1003}

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

    def test_worker_thread_ops_allowed(self, qapp: QApplication) -> None:
        """Test that store, get_image, and has_frame all work from worker threads."""
        cache = ScrubFrameCache()

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                # store
                image = make_test_image()
                cache.store("show/seq/shot1", 1001, image)
                results.append("stored")

                # get_image
                retrieved = cache.get_image("show/seq/shot1", 1001)
                results.append("get_image_ok" if retrieved is not None else "get_image_fail")

                # has_frame
                exists = cache.has_frame("show/seq/shot1", 1001)
                not_exists = cache.has_frame("show/seq/shot1", 9999)
                results.append("has_frame_ok" if (exists and not not_exists) else "has_frame_fail")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5.0)

        assert len(errors) == 0, f"Worker thread errors: {errors}"
        assert results == ["stored", "get_image_ok", "has_frame_ok"]
        assert cache.has_frame("show/seq/shot1", 1001)


class TestConcurrentAccess:
    """Test concurrent read/write operations."""

    def test_concurrent_store_read_clear_is_threadsafe(self, qapp: QApplication) -> None:
        """5 threads doing store+read+clear_shot in a loop on shared cache — no errors."""
        cache = ScrubFrameCache(max_frames_per_shot=100, max_shots=20)
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            shot_key = f"show/seq/shot{thread_id}"
            try:
                for i in range(20):
                    frame_num = 1000 + i
                    cache.store(shot_key, frame_num, make_test_image())
                    _ = cache.get_image(shot_key, frame_num)
                    _ = cache.has_frame(shot_key, frame_num)
                    cache.clear_shot(shot_key)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"


class TestStoreInvalidatesPixmap:
    """Test that updating a frame invalidates cached pixmap."""

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

    @pytest.mark.parametrize(
        ("shot_key", "frame"),
        [
            pytest.param("", 1001, id="empty_shot_key"),
            pytest.param("show/seq/shot1", 0, id="zero_frame_number"),
            pytest.param("show/seq/shot1", -1, id="negative_frame_number"),
            pytest.param("show/seq/shot1", 999999999, id="very_large_frame_number"),
        ],
    )
    def test_boundary_key_and_frame(
        self, qapp: QApplication, shot_key: str, frame: int
    ) -> None:
        """Test handling of boundary shot keys and frame numbers."""
        cache = ScrubFrameCache()
        cache.store(shot_key, frame, make_test_image())

        assert cache.has_frame(shot_key, frame)
        assert cache.get_image(shot_key, frame) is not None

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

