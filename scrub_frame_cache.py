"""Thread-safe LRU cache for scrub preview frames.

This module provides a thread-safe caching system for plate scrub preview frames.
It maintains separate storage for QImage (thread-safe) and QPixmap (main thread only)
with LRU eviction at both shot and frame levels.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

from PySide6.QtCore import QMutex, QMutexLocker, QThread
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication


if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ScrubFrameCache:
    """Thread-safe LRU cache for scrub preview frames.

    This cache provides:
    - Two-level LRU eviction: per-shot and per-frame
    - Thread-safe QImage storage for background loading
    - Main-thread-only QPixmap access for display
    - Configurable limits on frames per shot and total shots

    The cache uses shot keys (e.g., "show/sequence/shot") as primary keys,
    with frame numbers as secondary keys within each shot.
    """

    def __init__(
        self,
        max_frames_per_shot: int = 20,
        max_shots: int = 20,
    ) -> None:
        """Initialize scrub frame cache.

        Args:
            max_frames_per_shot: Maximum frames to cache per shot (LRU eviction)
            max_shots: Maximum shots to keep in cache (LRU eviction)
        """
        self._max_frames_per_shot: int = max_frames_per_shot
        self._max_shots: int = max_shots

        # Primary cache: shot_key -> OrderedDict[frame_num -> QImage]
        # OrderedDict maintains LRU order (most recent at end)
        self._image_cache: OrderedDict[str, OrderedDict[int, QImage]] = OrderedDict()

        # Pixmap cache: shot_key -> dict[frame_num -> QPixmap]
        # Only populated on main thread when get_pixmap is called
        self._pixmap_cache: dict[str, dict[int, QPixmap]] = {}

        self._lock: QMutex = QMutex()

    def _assert_main_thread(self, operation: str) -> None:
        """Assert that QPixmap operations only happen on main thread.

        Args:
            operation: Description of the operation being performed

        Raises:
            RuntimeError: If called from a worker thread
        """
        app = QApplication.instance()
        if app is None:
            return

        main_thread = app.thread()
        current = QThread.currentThread()

        if current != main_thread:
            thread_name = getattr(current, "objectName", lambda: str(current))()
            raise RuntimeError(
                f"QPixmap {operation} attempted from worker thread '{thread_name}'. "
                "QPixmap operations must only happen on the main Qt thread."
            )

    def _evict_oldest_shot(self) -> None:
        """Evict the oldest (least recently used) shot from cache.

        Must be called with lock held.
        """
        if self._image_cache:
            # OrderedDict.popitem(last=False) removes the oldest item
            oldest_key, _ = self._image_cache.popitem(last=False)
            # Also remove from pixmap cache
            _ = self._pixmap_cache.pop(oldest_key, None)
            logger.debug(f"Evicted oldest shot from scrub cache: {oldest_key}")

    def _evict_oldest_frame(self, shot_key: str) -> None:
        """Evict the oldest frame from a shot's frame cache.

        Must be called with lock held.

        Args:
            shot_key: Key identifying the shot
        """
        if shot_key in self._image_cache:
            frame_cache = self._image_cache[shot_key]
            if frame_cache:
                oldest_frame, _ = frame_cache.popitem(last=False)
                # Also remove from pixmap cache
                if shot_key in self._pixmap_cache:
                    _ = self._pixmap_cache[shot_key].pop(oldest_frame, None)
                logger.debug(f"Evicted oldest frame {oldest_frame} from {shot_key}")

    def store(self, shot_key: str, frame: int, image: QImage) -> None:
        """Store a frame image in the cache (thread-safe).

        Args:
            shot_key: Unique key for the shot (e.g., "show/sequence/shot")
            frame: Frame number
            image: QImage to cache
        """
        with QMutexLocker(self._lock):
            # Create shot entry if needed
            if shot_key not in self._image_cache:
                # Check if we need to evict a shot
                if len(self._image_cache) >= self._max_shots:
                    self._evict_oldest_shot()
                self._image_cache[shot_key] = OrderedDict()
                self._pixmap_cache[shot_key] = {}

            frame_cache = self._image_cache[shot_key]

            # Check if we need to evict a frame (only if this is a new frame)
            if frame not in frame_cache and len(frame_cache) >= self._max_frames_per_shot:
                self._evict_oldest_frame(shot_key)

            # Store the image (this moves it to end of OrderedDict = most recent)
            frame_cache[frame] = image
            # Move to end to mark as recently used
            frame_cache.move_to_end(frame)

            # Move shot to end (most recently used)
            self._image_cache.move_to_end(shot_key)

            # Invalidate corresponding pixmap (will be regenerated on demand)
            if shot_key in self._pixmap_cache:
                _ = self._pixmap_cache[shot_key].pop(frame, None)

    def get_image(self, shot_key: str, frame: int) -> QImage | None:
        """Get a cached QImage (thread-safe).

        Args:
            shot_key: Unique key for the shot
            frame: Frame number

        Returns:
            QImage if cached, None otherwise
        """
        with QMutexLocker(self._lock):
            if shot_key not in self._image_cache:
                return None

            frame_cache = self._image_cache[shot_key]
            if frame not in frame_cache:
                return None

            # Mark as recently used
            frame_cache.move_to_end(frame)
            self._image_cache.move_to_end(shot_key)

            return frame_cache[frame]

    def get_pixmap(self, shot_key: str, frame: int) -> QPixmap | None:
        """Get a cached QPixmap for display (main thread only).

        Converts from QImage if needed.

        Args:
            shot_key: Unique key for the shot
            frame: Frame number

        Returns:
            QPixmap if cached, None otherwise

        Raises:
            RuntimeError: If called from a worker thread
        """
        self._assert_main_thread("get_pixmap")

        with QMutexLocker(self._lock):
            # Check pixmap cache first
            if shot_key in self._pixmap_cache:
                pixmap = self._pixmap_cache[shot_key].get(frame)
                if pixmap is not None:
                    return pixmap

            # Convert from QImage if available
            if shot_key in self._image_cache:
                frame_cache = self._image_cache[shot_key]
                if frame in frame_cache:
                    image = frame_cache[frame]
                    pixmap = QPixmap.fromImage(image)

                    # Cache the pixmap
                    if shot_key not in self._pixmap_cache:
                        self._pixmap_cache[shot_key] = {}
                    self._pixmap_cache[shot_key][frame] = pixmap

                    # Mark as recently used
                    frame_cache.move_to_end(frame)
                    self._image_cache.move_to_end(shot_key)

                    return pixmap

        return None

    def has_frame(self, shot_key: str, frame: int) -> bool:
        """Check if a frame is cached (thread-safe).

        Args:
            shot_key: Unique key for the shot
            frame: Frame number

        Returns:
            True if frame is in cache
        """
        with QMutexLocker(self._lock):
            if shot_key not in self._image_cache:
                return False
            return frame in self._image_cache[shot_key]

    def get_cached_frames(self, shot_key: str) -> list[int]:
        """Get list of cached frame numbers for a shot (thread-safe).

        Args:
            shot_key: Unique key for the shot

        Returns:
            List of frame numbers currently cached for this shot
        """
        with QMutexLocker(self._lock):
            if shot_key not in self._image_cache:
                return []
            return list(self._image_cache[shot_key].keys())

    def clear_shot(self, shot_key: str) -> None:
        """Clear all cached frames for a shot (thread-safe).

        Args:
            shot_key: Unique key for the shot to clear
        """
        with QMutexLocker(self._lock):
            _ = self._image_cache.pop(shot_key, None)
            _ = self._pixmap_cache.pop(shot_key, None)

    def clear_all(self) -> None:
        """Clear all cached frames (thread-safe)."""
        with QMutexLocker(self._lock):
            self._image_cache.clear()
            self._pixmap_cache.clear()

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics (thread-safe).

        Returns:
            Dictionary with cache size information
        """
        with QMutexLocker(self._lock):
            total_frames = sum(len(frames) for frames in self._image_cache.values())
            total_pixmaps = sum(len(frames) for frames in self._pixmap_cache.values())
            return {
                "shot_count": len(self._image_cache),
                "total_frames": total_frames,
                "total_pixmaps": total_pixmaps,
                "max_shots": self._max_shots,
                "max_frames_per_shot": self._max_frames_per_shot,
            }


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    # Create cache with small limits for testing
    cache = ScrubFrameCache(max_frames_per_shot=3, max_shots=2)

    # Create test images
    def make_test_image(color: int) -> QImage:
        img = QImage(100, 100, QImage.Format.Format_ARGB32)
        img.fill(color)
        return img

    # Test basic storage
    cache.store("show/seq/shot1", 1001, make_test_image(0xFF0000FF))
    cache.store("show/seq/shot1", 1002, make_test_image(0xFF00FF00))
    cache.store("show/seq/shot1", 1003, make_test_image(0xFFFF0000))

    print(f"After 3 frames: {cache.get_stats()}")

    # Test frame eviction
    cache.store("show/seq/shot1", 1004, make_test_image(0xFFFFFFFF))
    print(f"After 4th frame (should evict oldest): {cache.get_stats()}")
    print(f"Frame 1001 still cached: {cache.has_frame('show/seq/shot1', 1001)}")
    print(f"Frame 1004 cached: {cache.has_frame('show/seq/shot1', 1004)}")

    # Test shot eviction
    cache.store("show/seq/shot2", 2001, make_test_image(0xFFAAAAAA))
    cache.store("show/seq/shot3", 3001, make_test_image(0xFFBBBBBB))
    print(f"After 3rd shot (should evict oldest): {cache.get_stats()}")

    # Test pixmap retrieval (main thread)
    pixmap = cache.get_pixmap("show/seq/shot2", 2001)
    print(f"Got pixmap: {pixmap is not None}")

    print("Scrub frame cache demo complete")
