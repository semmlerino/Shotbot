"""Qt widget test doubles.

Classes:
    TestQtWidget: Test double for Qt widget testing
    ThreadSafeTestImage: Thread-safe test double for QPixmap using QImage

Functions:
    simulate_work_without_sleep: Simulate CPU work without blocking the event loop
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QColor, QImage


if TYPE_CHECKING:
    from collections.abc import Callable


def simulate_work_without_sleep(duration_ms: int = 10) -> None:
    """Simulate work without blocking the thread.

    Busy-waits for the given duration to simulate CPU work without
    using time.sleep() which can cause Qt event loop issues.

    Args:
        duration_ms: Duration in milliseconds to simulate work.

    """
    start = time.perf_counter()
    target = start + (duration_ms / 1000.0)
    while time.perf_counter() < target:
        time.sleep(0)  # Yield to other threads


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


class TestQtWidget:
    """Test double for Qt widget testing without Mock.

    Tracks signal emissions and widget state changes without using Mock.
    Compatible with qtbot fixture for proper Qt testing.

    Example usage:
        def test_widget_behavior(qtbot):
            widget = TestQtWidget()

            # Simulate user interaction
            widget.emit_signal("clicked")
            widget.set_state("enabled", True)

            # Verify behavior
            assert widget.signals == [("clicked", ())]
            assert widget.state["enabled"] is True

            # Use with qtbot for timing
            qtbot.wait(1)  # Minimal event processing
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test widget."""
        self.signals: list[tuple[str, tuple[Any, ...]]] = []
        self.state: dict[str, Any] = {
            "visible": True,
            "enabled": True,
            "geometry": (0, 0, 100, 100),
            "text": "",
            "selected": False,
        }
        self.connections: dict[str, list[Callable[..., Any]]] = defaultdict(list)
        self.properties: dict[str, Any] = {}
        self.method_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def emit_signal(self, signal_name: str, *args: Any) -> None:
        """Emit a signal and track it.

        Args:
            signal_name: Name of the signal
            *args: Signal arguments

        """
        self.signals.append((signal_name, args))

        # Call connected slots
        for callback in self.connections.get(signal_name, []):
            callback(*args)

    def connect(self, signal_name: str, callback: Callable[..., Any]) -> None:
        """Connect a callback to a signal."""
        self.connections[signal_name].append(callback)

    def disconnect(self, signal_name: str, callback: Callable[..., Any] | None = None) -> None:
        """Disconnect callback(s) from a signal."""
        if callback:
            if callback in self.connections[signal_name]:
                self.connections[signal_name].remove(callback)
        else:
            self.connections[signal_name].clear()

    def set_state(self, key: str, value: Any) -> None:
        """Set widget state value."""
        self.state[key] = value
        # Emit state change signal
        self.emit_signal("stateChanged", key, value)

    def get_state(self, key: str) -> Any:
        """Get widget state value."""
        return self.state.get(key)

    def setProperty(self, name: str, value: Any) -> None:
        """Set a Qt property."""
        self.properties[name] = value

    def property(self, name: str) -> Any:
        """Get a Qt property."""
        return self.properties.get(name)

    def call_method(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Track method calls on the widget."""
        self.method_calls.append((method_name, args, kwargs))

        # Simulate some common method behaviors
        if method_name == "show":
            self.set_state("visible", True)
        elif method_name == "hide":
            self.set_state("visible", False)
        elif method_name == "setEnabled":
            self.set_state("enabled", args[0] if args else True)
        elif method_name == "setText" and args:
            self.set_state("text", args[0])

        return None  # Most Qt methods return None

    def reset(self) -> None:
        """Reset all tracking for a fresh test."""
        self.signals.clear()
        self.connections.clear()
        self.method_calls.clear()
        self.state = {
            "visible": True,
            "enabled": True,
            "geometry": (0, 0, 100, 100),
            "text": "",
            "selected": False,
        }

    def get_signal_count(self, signal_name: str) -> int:
        """Get count of emissions for a specific signal."""
        return sum(1 for name, _ in self.signals if name == signal_name)
