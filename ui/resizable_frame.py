"""Resizable frame widget with bottom drag handle.

This module provides a ResizableFrame widget that wraps any child widget
with a draggable bottom resize handle, allowing users to vertically resize
the content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from typing_extensions import override


if TYPE_CHECKING:
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QMouseEvent


@final
class ResizableFrame(QWidget):
    """A frame with a draggable bottom edge for vertical resizing.

    Wraps any child widget and adds a resize handle at the bottom.
    The handle is subtle (6px) with hover highlighting using the accent color.

    Signals:
        height_changed: Emitted when drag ends with the new height value.
            Connect to this to persist the height to settings.
    """

    height_changed = Signal(int)

    def __init__(
        self,
        child_widget: QWidget,
        min_height: int = 60,
        max_height: int = 400,
        initial_height: int = 120,
        accent_color: str = "#888",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the resizable frame.

        Args:
            child_widget: The widget to wrap with resize capability.
            min_height: Minimum allowed height for the child widget.
            max_height: Maximum allowed height for the child widget.
            initial_height: Starting height for the child widget.
            accent_color: Color for the resize handle highlight on hover.
            parent: Parent widget.

        """
        super().__init__(parent)
        self._child = child_widget
        self._min_height = min_height
        self._max_height = max_height
        self._accent_color = accent_color
        self._dragging = False
        self._drag_start_y: float = 0
        self._drag_start_height = 0

        self._setup_ui(initial_height)

    def _setup_ui(self, initial_height: int) -> None:
        """Set up the UI with child widget and resize handle.

        Args:
            initial_height: Initial height for the child widget.

        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Child widget
        self._child.setParent(self)
        layout.addWidget(self._child)

        # Resize handle (subtle 6px bar at bottom)
        self._handle = QWidget()
        self._handle.setFixedHeight(6)
        self._handle.setCursor(Qt.CursorShape.SizeVerCursor)
        self._handle.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
                border-top: 1px solid #333;
            }}
            QWidget:hover {{
                background-color: {self._accent_color}40;
                border-top: 1px solid {self._accent_color};
            }}
        """)
        self._handle.setMouseTracking(True)
        layout.addWidget(self._handle)

        # Install event filter for drag handling
        self._handle.installEventFilter(self)

        # Set initial height (clamp to min/max)
        clamped_height = max(self._min_height, min(self._max_height, initial_height))
        self._child.setFixedHeight(clamped_height)
        self.setFixedHeight(clamped_height + 6)  # +6 for handle

    @override
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle mouse events on resize handle.

        Args:
            obj: The object that received the event.
            event: The event to process.

        Returns:
            True if event was handled, False to pass to default handler.

        """
        if obj is self._handle:
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event: QMouseEvent = event  # type: ignore[assignment]
                if mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._dragging = True
                    self._drag_start_y = mouse_event.globalPosition().y()
                    self._drag_start_height = self._child.height()
                    return True

            elif event.type() == QEvent.Type.MouseMove:
                if self._dragging:
                    mouse_event = event  # type: ignore[assignment]
                    delta = mouse_event.globalPosition().y() - self._drag_start_y
                    new_height = int(self._drag_start_height + delta)
                    new_height = max(
                        self._min_height, min(self._max_height, new_height)
                    )
                    self._child.setFixedHeight(new_height)
                    self.setFixedHeight(new_height + 6)
                    return True

            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._dragging:
                    self._dragging = False
                    self.height_changed.emit(self._child.height())
                    return True

        return super().eventFilter(obj, event)

    def set_height(self, height: int) -> None:
        """Programmatically set the content height.

        Args:
            height: The desired height (will be clamped to min/max).

        """
        clamped = max(self._min_height, min(self._max_height, height))
        self._child.setFixedHeight(clamped)
        self.setFixedHeight(clamped + 6)

    def content_height(self) -> int:
        """Get the current content height.

        Returns:
            The current height of the child widget.

        """
        return self._child.height()

    @property
    def min_height(self) -> int:
        """Get the minimum allowed height."""
        return self._min_height

    @property
    def max_height(self) -> int:
        """Get the maximum allowed height."""
        return self._max_height
