"""Qt widget test doubles.

Classes:
    ThreadSafeTestImage: Thread-safe test double for QPixmap using QImage

Functions:
    simulate_work_without_sleep: Simulate CPU work without blocking the event loop
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage

from tests.fixtures.process_doubles import simulate_work_without_sleep  # noqa: F401


class ThreadSafeTestImage:
    """Thread-safe test double for QPixmap using QImage internally.

    Critical for avoiding Qt threading violations in tests.
    QPixmap is NOT thread-safe and causes fatal errors in worker threads.
    QImage IS thread-safe and should be used instead.
    """

    def __init__(self, width: int = 100, height: int = 100) -> None:
        """Create a thread-safe test image."""
        # Use QImage which is thread-safe, unlike QPixmap
        self._image = QImage(width, height, QImage.Format.Format_RGB32)
        self._width = width
        self._height = height
        self._image.fill(QColor(255, 255, 255))  # White by default

    def fill(self, color: QColor | None = None) -> None:
        """Fill the image with a color."""
        if color is None:
            color = QColor(255, 255, 255)
        self._image.fill(color)

    def scaled(self, width: int, height: int) -> ThreadSafeTestImage:
        """Scale the image."""
        new_image = ThreadSafeTestImage(width, height)
        new_image._image = self._image.scaled(width, height)
        return new_image

    def size(self) -> tuple[int, int]:
        """Get image size as tuple."""
        return (self._width, self._height)

    def save(self, path: str) -> bool:
        """Save image to file."""
        return self._image.save(str(path))

    def isNull(self) -> bool:
        """Check if image is null."""
        return self._image.isNull()

    def sizeInBytes(self) -> int:
        """Get size in bytes."""
        return self._image.sizeInBytes()


