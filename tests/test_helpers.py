"""Test helpers and doubles for ShotBot test suite.

Based on UNIFIED_TESTING_GUIDE_DO_NOT_DELETE.md - provides thread-safe
test doubles and helper classes for proper Qt testing without crashes.

Key Components:
    - ThreadSafeTestImage: QPixmap replacement for worker threads
    - SignalDouble: Signal test double for non-Qt objects
    - TestProcessPoolManager: Subprocess test double
    - Factory fixtures and helpers
"""

from __future__ import annotations

# Standard library imports
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# Third-party imports
from PySide6.QtCore import QEventLoop, QObject, QSize, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable
    from pathlib import Path


class ThreadSafeTestImage:
    """Thread-safe test double for QPixmap using QImage internally.

    QPixmap is not thread-safe and can only be used in the main GUI thread.
    QImage is thread-safe and can be used in any thread. This class provides
    a QPixmap-like interface while using QImage internally for thread safety.

    Based on Qt's canonical threading pattern for image operations.
    """

    def __init__(self, width: int = 100, height: int = 100) -> None:
        """Create a thread-safe test image."""
        # Use QImage which is thread-safe, unlike QPixmap
        self._image = QImage(width, height, QImage.Format.Format_RGB32)
        self._width = width
        self._height = height
        self._image.fill(QColor(255, 255, 255))  # Fill with white by default

    def fill(self, color: QColor | None = None) -> None:
        """Fill the image with a color."""
        if color is None:
            color = QColor(255, 255, 255)
        self._image.fill(color)

    def isNull(self) -> bool:
        """Check if the image is null."""
        return self._image.isNull()

    def sizeInBytes(self) -> int:
        """Return the size of the image in bytes."""
        return self._image.sizeInBytes()

    def size(self) -> QSize:
        """Return the size of the image."""
        return QSize(self._width, self._height)

    def width(self) -> int:
        """Return the width of the image."""
        return self._width

    def height(self) -> int:
        """Return the height of the image."""
        return self._height

    def to_qimage(self) -> QImage:
        """Get the underlying QImage for conversion to QPixmap in main thread."""
        return self._image


def process_qt_events(duration_ms: int = 5, iterations: int = 2) -> None:
    """Process pending Qt events without relying on qtbot.wait()."""
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, duration_ms)


class SignalDouble:
    """Lightweight signal test double for non-Qt objects.

    Use this instead of trying to use QSignalSpy on Mock objects,
    which will crash. This provides a simple interface for testing
    signal emissions and connections.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize the test signal."""
        self.emissions: list[tuple[Any, ...]] = []
        self.callbacks: list[Callable] = []

    def emit(self, *args) -> None:
        """Emit the signal with arguments."""
        self.emissions.append(args)
        for callback in self.callbacks:
            try:
                callback(*args)
            except Exception as e:
                print(f"SignalDouble callback error: {e}")

    def connect(self, callback: Callable) -> None:
        """Connect a callback to the signal."""
        self.callbacks.append(callback)

    def disconnect(self, callback: Callable | None = None) -> None:
        """Disconnect a callback or all callbacks."""
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)

    @property
    def was_emitted(self) -> bool:
        """Check if the signal was emitted at least once."""
        return len(self.emissions) > 0

    @property
    def emit_count(self) -> int:
        """Get the number of times the signal was emitted."""
        return len(self.emissions)

    def get_last_emission(self) -> tuple[Any, ... | None]:
        """Get the arguments from the last emission."""
        if self.emissions:
            return self.emissions[-1]
        return None

    def clear(self) -> None:
        """Clear emission history."""
        self.emissions.clear()


class TestProcessPoolManager:
    """Test double for ProcessPoolManager - replaces subprocess calls.

    Provides predictable behavior for testing without actual subprocess
    execution. Tracks commands and provides configurable outputs.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize the test process pool."""
        self.commands: list[str] = []
        self.outputs: list[str] = ["workspace /test/path"]
        self.command_completed = SignalDouble()
        self.command_failed = SignalDouble()
        self.should_fail = False
        self.failure_message = "Test failure"
        # Simple cache implementation for testing
        self._cache: dict[str, tuple[str, float]] = {}  # command -> (output, timestamp)
        # Standard library imports
        import time

        self._time = time

    def execute_workspace_command(self, command: str, **kwargs) -> str:
        """Execute a workspace command (mocked).

        Returns:
            str: Command output (matches real ProcessPoolManager interface)

        Raises:
            Exception: When should_fail is True (matches real ProcessPoolManager behavior)
        """
        cache_ttl = kwargs.get("cache_ttl", 0)

        # Check cache if TTL > 0
        if cache_ttl > 0 and command in self._cache:
            cached_output, cached_time = self._cache[command]
            if self._time.time() - cached_time < cache_ttl:
                # Return cached result without executing command
                return cached_output

        # Execute command (not cached or cache expired)
        self.commands.append(command)

        if self.should_fail:
            self.command_failed.emit(command, self.failure_message)
            # Match real ProcessPoolManager behavior - raise exception on failure
            if "timed out" in self.failure_message.lower():
                raise TimeoutError(self.failure_message)
            raise RuntimeError(self.failure_message)

        output = self.outputs[0] if self.outputs else ""

        # Cache the result if TTL > 0
        if cache_ttl > 0:
            self._cache[command] = (output, self._time.time())

        self.command_completed.emit(command, output)
        return output

    def execute_command(self, command: str, **kwargs) -> tuple[bool, str]:
        """Execute a general command (mocked)."""
        self.commands.append(command)

        if self.should_fail:
            self.command_failed.emit(command, self.failure_message)
            return False, self.failure_message

        output = self.outputs[0] if self.outputs else ""
        self.command_completed.emit(command, output)
        return True, output

    def set_outputs(self, *outputs: str) -> None:
        """Set the outputs to return for commands."""
        self.outputs = list(outputs)

    def set_should_fail(self, should_fail: bool, message: str = "Test failure") -> None:
        """Configure the manager to fail on next command."""
        self.should_fail = should_fail
        self.failure_message = message

    def get_executed_commands(self) -> list[str]:
        """Get the list of executed commands."""
        return self.commands.copy()

    def clear(self) -> None:
        """Clear command history."""
        self.commands.clear()
        self.command_completed.clear()
        self.command_failed.clear()
        self._cache.clear()

    def invalidate_cache(self, command: str) -> None:
        """Invalidate cache for a specific command (test double implementation)."""
        if command in self._cache:
            del self._cache[command]

    @classmethod
    def get_instance(cls) -> TestProcessPoolManager:
        """Get a singleton instance (for compatibility)."""
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance


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
