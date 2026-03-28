"""Event filter for scrub preview hover tracking.

This module provides an event filter that tracks mouse movement over
thumbnail items in a QListView, enabling scrubbing through plate frames.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Final

from PySide6.QtCore import QEvent, QModelIndex, QObject, QRect, QTimer, Signal
from shiboken6 import isValid
from typing_extensions import override


if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QListView


logger = logging.getLogger(__name__)


class ScrubEventFilter(QObject):
    """Event filter that tracks mouse movement for scrub preview.

    Installed on a QListView's viewport to track hover over thumbnails
    and emit signals for scrub preview activation/updates.

    Signals:
        scrub_started: Emitted when scrub begins (index, item_rect)
        scrub_position_changed: Emitted when mouse moves (index, x_ratio 0.0-1.0)
        scrub_ended: Emitted when scrub ends (index)
    """

    scrub_started: ClassVar[Signal] = Signal(QModelIndex, QRect)  # index, item_rect
    scrub_position_changed: ClassVar[Signal] = Signal(
        QModelIndex, float
    )  # index, x_ratio
    scrub_ended: ClassVar[Signal] = Signal(QModelIndex)  # index

    # Delay before scrub starts (prevents accidental activation)
    _HOVER_DELAY_MS: Final[int] = 300

    def __init__(
        self,
        view: QListView,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the scrub event filter.

        Args:
            view: The QListView to track mouse events on
            parent: Parent QObject

        """
        super().__init__(parent)
        self._view: QListView = view
        self._current_index: QModelIndex | None = None
        self._current_rect: QRect | None = None
        self._is_scrubbing: bool = False
        self._hover_pending: bool = False

        # Timer for hover delay
        self._hover_timer: QTimer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        _ = self._hover_timer.timeout.connect(self._on_hover_timer_expired)

        # Pending index for hover timer
        self._pending_index: QModelIndex | None = None
        self._pending_rect: QRect | None = None

    @override
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Filter events on the viewport.

        Args:
            obj: Object that received the event
            event: The event

        Returns:
            True if event was handled, False to pass to next filter

        """
        # Guard against access to deleted C++ objects during teardown
        if not isValid(self._view):
            return False

        if obj is not self._view.viewport():
            return False

        event_type = event.type()

        if event_type == QEvent.Type.MouseMove:
            self._handle_mouse_move(event)  # type: ignore[arg-type]
        elif event_type == QEvent.Type.Leave:
            self._handle_leave()
        elif event_type == QEvent.Type.Wheel:
            # Cancel scrub on scroll
            self._cancel_scrub()

        # Don't consume events - let them propagate normally
        return False

    def _handle_mouse_move(self, event: QMouseEvent) -> None:
        """Handle mouse move event.

        Args:
            event: Mouse event

        """
        pos = event.position().toPoint()
        index = self._view.indexAt(pos)

        if not index.isValid():
            # Mouse not over any item
            self._cancel_scrub()
            return

        # Get the item rect
        item_rect = self._view.visualRect(index)
        if not item_rect.isValid() or not item_rect.contains(pos):
            self._cancel_scrub()
            return

        # Check if we're over a new item
        if self._current_index is None or index != self._current_index:
            # New item - start hover delay
            self._start_hover_delay(index, item_rect)
        elif self._is_scrubbing:
            # Same item, already scrubbing - update position
            x_ratio = self._calculate_x_ratio(pos.x(), item_rect)
            self.scrub_position_changed.emit(index, x_ratio)

    def _handle_leave(self) -> None:
        """Handle mouse leaving the viewport."""
        self._cancel_scrub()

    def _start_hover_delay(self, index: QModelIndex, rect: QRect) -> None:
        """Start the hover delay timer for a new item.

        Args:
            index: Index of the item being hovered
            rect: Visual rect of the item

        """
        # If already scrubbing a different item, end that scrub first
        if self._is_scrubbing and self._current_index is not None:
            self.scrub_ended.emit(self._current_index)
            self._is_scrubbing = False

        # Cancel any pending hover
        self._hover_timer.stop()

        # Store pending hover info
        self._pending_index = index
        self._pending_rect = rect
        self._hover_pending = True

        # Start timer
        self._hover_timer.start(self._HOVER_DELAY_MS)

    def _on_hover_timer_expired(self) -> None:
        """Handle hover delay timer expiration - start scrubbing."""
        if not self._hover_pending or self._pending_index is None:
            return

        # Guard against access to deleted C++ objects during teardown
        if not isValid(self._view):
            self._hover_pending = False
            self._pending_index = None
            self._pending_rect = None
            return

        # Verify mouse is still over the same item
        cursor_pos = self._view.viewport().mapFromGlobal(
            self._view.viewport().cursor().pos()
        )
        current_index = self._view.indexAt(cursor_pos)

        if not current_index.isValid() or current_index != self._pending_index:
            # Mouse moved away during delay
            self._hover_pending = False
            self._pending_index = None
            self._pending_rect = None
            return

        # Start scrubbing
        self._current_index = self._pending_index
        self._current_rect = self._pending_rect
        self._is_scrubbing = True
        self._hover_pending = False
        self._pending_index = None

        if self._current_rect is not None:
            self.scrub_started.emit(self._current_index, self._current_rect)

            # Emit initial position
            x_ratio = self._calculate_x_ratio(cursor_pos.x(), self._current_rect)
            self.scrub_position_changed.emit(self._current_index, x_ratio)

    def _cancel_scrub(self) -> None:
        """Cancel any active or pending scrub."""
        # Cancel hover timer
        self._hover_timer.stop()
        self._hover_pending = False
        self._pending_index = None
        self._pending_rect = None

        # End active scrub
        if self._is_scrubbing and self._current_index is not None:
            self.scrub_ended.emit(self._current_index)

        self._is_scrubbing = False
        self._current_index = None
        self._current_rect = None

    def _calculate_x_ratio(self, mouse_x: int, rect: QRect) -> float:
        """Calculate horizontal position ratio within item rect.

        Args:
            mouse_x: Mouse X coordinate
            rect: Item rectangle

        Returns:
            Ratio from 0.0 (left edge) to 1.0 (right edge)

        """
        if rect.width() <= 0:
            return 0.5

        relative_x = mouse_x - rect.left()
        ratio = relative_x / rect.width()

        # Clamp to 0.0-1.0
        return max(0.0, min(1.0, ratio))

    @property
    def is_scrubbing(self) -> bool:
        """Check if currently scrubbing.

        Returns:
            True if actively scrubbing

        """
        return self._is_scrubbing

    @property
    def current_index(self) -> QModelIndex | None:
        """Get the currently scrubbed item index.

        Returns:
            Current index or None if not scrubbing

        """
        return self._current_index

    def stop(self) -> None:
        """Stop the event filter and clean up."""
        self._cancel_scrub()
        self._hover_timer.stop()
