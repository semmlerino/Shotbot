"""Thread-safe thumbnail cache separating QImage (thread-safe) from QPixmap (main thread only).

This module provides a thread-safe thumbnail caching system that ensures QPixmap
operations only happen on the main Qt thread while allowing QImage processing
in background threads.
"""

from __future__ import annotations

# Standard library imports
import logging
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker, Qt, QThread
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication


if TYPE_CHECKING:
    # Standard library imports
    from pathlib import Path

logger = logging.getLogger(__name__)


class ThreadSafeThumbnailCache:
    """Thread-safe thumbnail cache with proper QPixmap/QImage separation.

    This cache ensures that:
    - QImage objects (thread-safe) are used for storage and background processing
    - QPixmap objects (main thread only) are only created when needed for display
    - Main thread assertions prevent accidental QPixmap creation in worker threads
    """

    def __init__(self) -> None:
        """Initialize thread-safe thumbnail cache."""
        super().__init__()
        self._image_cache: dict[str, QImage] = {}  # QImage (thread-safe)
        self._pixmap_cache: dict[str, QPixmap] = {}  # QPixmap (main thread only)
        self._cache_lock = QMutex()

    def _assert_main_thread(self, operation: str) -> None:
        """Assert that QPixmap operations only happen on main thread.

        Args:
            operation: Description of the operation being performed

        Raises:
            RuntimeError: If called from a worker thread
        """
        app = QApplication.instance()
        if app is None:
            # No Qt application, skip check
            return

        main_thread = app.thread()
        current = QThread.currentThread()

        if current != main_thread:
            thread_name = getattr(current, "objectName", lambda: str(current))()
            raise RuntimeError(
                f"QPixmap {operation} attempted from worker thread '{thread_name}'. "
                "QPixmap operations must only happen on the main Qt thread. "
                "Use QImage for thread-safe image processing."
            )

    def store_image(self, key: str, image: QImage) -> None:
        """Store a QImage in the cache (thread-safe).

        Args:
            key: Cache key for the image
            image: QImage object to cache
        """
        with QMutexLocker(self._cache_lock):
            self._image_cache[key] = image
            # Clear corresponding pixmap cache to force regeneration
            if key in self._pixmap_cache:
                del self._pixmap_cache[key]

    def store_from_path(self, key: str, path: Path) -> bool:
        """Load and store an image from file path using QImage (thread-safe).

        Args:
            key: Cache key for the image
            path: Path to image file

        Returns:
            True if image was loaded and cached successfully, False otherwise
        """
        try:
            # Use QImage which is thread-safe for loading
            image = QImage(str(path))
            if image.isNull():
                logger.debug(f"Failed to load image from {path}")
                return False

            self.store_image(key, image)
            return True

        except Exception as e:
            logger.debug(f"Error loading image from {path}: {e}")
            return False

    def get_pixmap(self, key: str) -> QPixmap | None:
        """Get QPixmap for display (main thread only).

        This method ensures that QPixmap creation only happens on the main thread.

        Args:
            key: Cache key to look up

        Returns:
            QPixmap if available, None if not found

        Raises:
            RuntimeError: If called from a worker thread
        """
        self._assert_main_thread("get_pixmap")

        with QMutexLocker(self._cache_lock):
            # Check pixmap cache first
            if key in self._pixmap_cache:
                return self._pixmap_cache[key]

            # Convert from QImage if available
            if key in self._image_cache:
                image = self._image_cache[key]
                pixmap = QPixmap.fromImage(image)
                self._pixmap_cache[key] = pixmap
                return pixmap

        return None

    def get_image(self, key: str) -> QImage | None:
        """Get QImage for processing (thread-safe).

        Args:
            key: Cache key to look up

        Returns:
            QImage if available, None if not found
        """
        with QMutexLocker(self._cache_lock):
            return self._image_cache.get(key)

    def has_image(self, key: str) -> bool:
        """Check if image exists in cache (thread-safe).

        Args:
            key: Cache key to check

        Returns:
            True if image exists in cache, False otherwise
        """
        with QMutexLocker(self._cache_lock):
            return key in self._image_cache

    def remove(self, key: str) -> None:
        """Remove image from cache (thread-safe).

        Args:
            key: Cache key to remove
        """
        with QMutexLocker(self._cache_lock):
            _ = self._image_cache.pop(key, None)
            _ = self._pixmap_cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached images (thread-safe)."""
        with QMutexLocker(self._cache_lock):
            self._image_cache.clear()
            self._pixmap_cache.clear()

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics (thread-safe).

        Returns:
            Dictionary with cache size information
        """
        with QMutexLocker(self._cache_lock):
            return {
                "image_count": len(self._image_cache),
                "pixmap_count": len(self._pixmap_cache),
                "total_count": len(self._image_cache),  # Images are the source of truth
            }


def create_thread_safe_pixmap(
    path: Path, size: tuple[int, int] | None = None
) -> QPixmap | None:
    """Create a QPixmap safely from a file path with main thread assertion.

    This function ensures QPixmap creation only happens on the main thread
    and provides proper error handling.

    Args:
        path: Path to image file
        size: Optional (width, height) to scale the pixmap

    Returns:
        QPixmap if successful, None if failed or called from worker thread
    """
    try:
        # Assert main thread before any QPixmap operations
        app = QApplication.instance()
        if app is not None:
            main_thread = app.thread()
            current = QThread.currentThread()

            if current != main_thread:
                thread_name = getattr(current, "objectName", lambda: str(current))()
                logger.error(
                    f"create_thread_safe_pixmap called from worker thread '{thread_name}'. "
                     "Use QImage.load() instead for thread-safe image loading."
                )
                return None

        # Safe to create QPixmap on main thread
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None

        # Scale if size requested
        if size is not None:
            width, height = size
            pixmap = pixmap.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        return pixmap

    except Exception as e:
        logger.debug(f"Error creating pixmap from {path}: {e}")
        return None


if __name__ == "__main__":
    # Demo the thread-safe cache
    # Standard library imports
    import sys

    # Third-party imports
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    # Create cache
    cache = ThreadSafeThumbnailCache()

    # Test with a dummy image
    test_image = QImage(100, 100, QImage.Format.Format_ARGB32)
    test_image.fill(0xFF0000FF)  # Blue

    # Store in cache
    cache.store_image("test", test_image)

    # Retrieve as pixmap (main thread)
    pixmap = cache.get_pixmap("test")
    print(f"Retrieved pixmap: {pixmap is not None}")

    # Get stats
    stats = cache.get_stats()
    print(f"Cache stats: {stats}")

    print("Thread-safe thumbnail cache demo complete")
