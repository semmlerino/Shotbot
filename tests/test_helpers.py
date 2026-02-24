"""Test helpers and doubles for ShotBot test suite.

Based on UNIFIED_TESTING_GUIDE_DO_NOT_DELETE.md - provides thread-safe
test doubles and helper classes for proper Qt testing without crashes.

Key Components:
    - SignalDouble: Signal test double for non-Qt objects (re-exported from fixtures)
    - process_qt_events: Process pending Qt events (preferred over qtbot.wait)
    - Factory fixtures and helpers

Note: ThreadSafeTestImage is available from tests.fixtures.doubles_library.
"""

from __future__ import annotations

# Standard library imports
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# Third-party imports
from PySide6.QtCore import QEventLoop, QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from tests.fixtures.doubles_library import ThreadSafeTestImage

# Import canonical doubles - these are the recommended implementations
from tests.fixtures.test_doubles import SignalDouble  # noqa: F401 (re-export)


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable
    from pathlib import Path


def process_qt_events(duration_ms: int = 5, iterations: int = 2) -> None:
    """Process pending Qt events.

    This helper processes Qt events in multiple iterations to ensure
    all pending events are handled. Use this instead of qtbot.wait(1)
    for event processing.

    NOTE: This does NOT flush DeferredDelete events. For end-of-test cleanup
    that includes DeferredDelete flushing, use the qt_cleanup fixture or
    call flush_deferred_deletes() explicitly after all widgets are destroyed.

    Args:
        duration_ms: Maximum time to spend processing events per iteration.
        iterations: Number of event processing rounds.

    """
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, duration_ms)


def flush_deferred_deletes() -> None:
    """Flush pending DeferredDelete events (deleteLater() calls).

    This explicitly processes all pending deleteLater() calls. Use this in
    test cleanup AFTER all widgets have been destroyed and you want to ensure
    their deletions are complete.

    WARNING: Only call this after widgets are fully disconnected from signals
    and their callbacks won't access deleted objects. Using this during mid-test
    event processing can cause segfaults.

    Example:
        widget.deleteLater()
        process_qt_events()
        flush_deferred_deletes()  # Now the widget is truly deleted

    """
    from PySide6.QtCore import QCoreApplication, QEvent

    app = QApplication.instance()
    if app is None:
        return
    # Process events first to ensure all pending operations complete
    app.processEvents()
    # Then flush deferred deletes
    try:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    except (RuntimeError, SystemError):
        # Object may have been deleted already
        pass


# SignalDouble is now imported from tests.fixtures.test_doubles (see imports above)


class MockMainWindow(QObject):
    """Mock MainWindow with real Qt signals but mocked behavior.

    This is a real Qt object so QSignalSpy will work, but with
    simplified/mocked implementation for testing.
    """

    # Real Qt signals
    extract_requested = Signal()
    file_opened = Signal(str)
    shot_selected = Signal(str)
    refresh_started = Signal()
    refresh_finished = Signal(bool)

    def __init__(self, parent=None) -> None:
        """Initialize the mock main window."""
        super().__init__(parent)

        # Mock attributes
        self.status_messages: list[str] = []
        self.current_file: str | None = None
        self.current_shot: str | None = None
        self.extraction_params = {"vram_path": "/test/path"}

    def get_extraction_params(self) -> dict[str, Any]:
        """Get extraction parameters (mocked)."""
        return self.extraction_params.copy()

    def set_extraction_params(self, params: dict[str, Any]) -> None:
        """Set extraction parameters for testing."""
        self.extraction_params = params

    def showStatusMessage(self, message: str, timeout: int = 0) -> None:
        """Show status message (mocked)."""
        self.status_messages.append(message)

    def open_file(self, filepath: str) -> None:
        """Open a file (mocked)."""
        self.current_file = filepath
        self.file_opened.emit(filepath)

    def select_shot(self, shot_name: str) -> None:
        """Select a shot (mocked)."""
        self.current_shot = shot_name
        self.shot_selected.emit(shot_name)


class ImagePool:
    """Reuse ThreadSafeTestImage instances for performance.

    Creating QImage objects has some overhead, so this pool
    allows reusing instances in tests that create many images.
    """

    def __init__(self) -> None:
        """Initialize the image pool."""
        self._pool: list[ThreadSafeTestImage] = []
        self._created_count = 0
        self._reused_count = 0

    def get_test_image(
        self, width: int = 100, height: int = 100
    ) -> ThreadSafeTestImage:
        """Get a test image from the pool or create a new one."""
        # Try to find a matching size in the pool
        for i, image in enumerate(self._pool):
            if image.width() == width and image.height() == height:
                self._pool.pop(i)
                image.fill()  # Reset to white
                self._reused_count += 1
                return image

        # Create new image if none available
        self._created_count += 1
        return ThreadSafeTestImage(width, height)

    def return_image(self, image: ThreadSafeTestImage) -> None:
        """Return an image to the pool for reuse."""
        if len(self._pool) < 10:  # Limit pool size
            self._pool.append(image)

    def get_stats(self) -> dict[str, int]:
        """Get pool statistics."""
        return {
            "created": self._created_count,
            "reused": self._reused_count,
            "pool_size": len(self._pool),
        }

    def clear(self) -> None:
        """Clear the pool."""
        self._pool.clear()


class TestCacheData:
    """Test data generator for cache-related tests."""

    @staticmethod
    def create_shot_data(count: int = 3) -> list[dict[str, Any]]:
        """Create test shot data."""
        return [
            {
                "show": f"test_show_{i}",
                "sequence": f"seq{i:03d}",
                "shot": f"shot{i:04d}",
                "workspace_path": f"/test/path/show_{i}/seq{i:03d}/shot{i:04d}",
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
            for i in range(count)
        ]

    @staticmethod
    def create_scene_data(count: int = 2) -> list[dict[str, Any]]:
        """Create test 3DE scene data."""
        return [
            {
                "path": f"/test/3de/scene_{i}.3de",
                "plate_name": f"plate_{i}",
                "user": f"user_{i}",
                "mtime": datetime.now(tz=UTC).timestamp(),
                "size": 1024 * (i + 1),
            }
            for i in range(count)
        ]

    @staticmethod
    def create_cache_file(cache_dir: Path, filename: str, data: Any) -> Path:
        """Create a cache file with test data."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / filename

        with cache_file.open("w") as f:
            json.dump(data, f, indent=2)

        return cache_file

    @staticmethod
    def create_test_image_file(
        filepath: Path, width: int = 100, height: int = 100
    ) -> Path:
        """Create a test image file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Create a simple QImage and save it
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor(100, 150, 200))  # Light blue
        image.save(str(filepath), "PNG")

        return filepath


def create_test_shot(
    show: str = "test", seq: str = "seq001", shot: str = "shot0010"
) -> dict[str, str]:
    """Factory function for creating test shot dictionaries."""
    return {
        "show": show,
        "sequence": seq,
        "shot": shot,
        "workspace_path": f"/shows/{show}/{seq}/{shot}",
    }


def create_test_process_result(
    success: bool = True, output: str = "Test output"
) -> tuple[bool, str]:
    """Factory function for process result tuples."""
    return success, output


def with_thread_safe_images(test_func: Callable) -> Callable:
    """Decorator to ensure thread-safe image usage in tests.

    Automatically patches QPixmap creation to use ThreadSafeTestImage
    in the decorated test function.
    """
    # Standard library imports
    from unittest.mock import (
        patch,
    )

    def wrapper(*args, **kwargs):
        with patch("PySide6.QtGui.QPixmap", ThreadSafeTestImage):
            return test_func(*args, **kwargs)

    wrapper.__name__ = test_func.__name__
    wrapper.__doc__ = test_func.__doc__
    return wrapper
