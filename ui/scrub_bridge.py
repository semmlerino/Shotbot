"""Bridge class encapsulating scrub preview setup and teardown.

ScrubPreviewBridge owns the ScrubPreviewManager and ScrubEventFilter
objects, wiring them together and connecting callbacks from the host view.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from scrub.scrub_event_filter import ScrubEventFilter
from scrub.scrub_preview_manager import ScrubPreviewManager


if TYPE_CHECKING:
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import QListView, QWidget

    from ui.base_thumbnail_delegate import BaseThumbnailDelegate


class ScrubPreviewBridge:
    """Encapsulates scrub preview wiring between manager, event filter, and view.

    The bridge owns both the ScrubPreviewManager and the ScrubEventFilter,
    sets up all signal connections, and exposes a ``manager`` property so
    delegates can call ``set_scrub_manager()``.
    """

    def __init__(self, parent: QWidget) -> None:
        """Initialise the bridge with a parent widget for QObject ownership.

        Args:
            parent: The host view widget (becomes QObject parent of managed objects).

        """
        self._parent: QWidget = parent
        self._manager: ScrubPreviewManager | None = None
        self._event_filter: ScrubEventFilter | None = None

    @property
    def manager(self) -> ScrubPreviewManager | None:
        """Return the active ScrubPreviewManager, or None if not yet set up."""
        return self._manager

    def setup(
        self,
        list_view: QListView,
        delegate: BaseThumbnailDelegate,
        on_repaint_needed: Callable[[QModelIndex], None],
        on_scrub_started: Callable[[QModelIndex], None] | None = None,
        on_scrub_ended: Callable[[QModelIndex], None] | None = None,
    ) -> None:
        """Initialise the scrub preview system and wire all signals.

        Sets up event filter on the list view's viewport and connects
        signals for Netflix-style hover scrubbing through plate frames.

        Args:
            list_view: The QListView whose viewport receives mouse events.
            delegate: The item delegate; receives the manager via set_scrub_manager().
            on_repaint_needed: Called with a QModelIndex when a frame changes.
            on_scrub_started: Optional callback when scrub begins on an index.
            on_scrub_ended: Optional callback when scrub ends on an index.

        """
        # Create scrub preview manager
        self._manager = ScrubPreviewManager(self._parent)

        # Enable mouse tracking so viewport receives MouseMove events during hover
        # (Without this, MouseMove only fires when a mouse button is pressed)
        list_view.viewport().setMouseTracking(True)

        # Create event filter and install on viewport
        self._event_filter = ScrubEventFilter(list_view, self._parent)
        list_view.viewport().installEventFilter(self._event_filter)

        # Connect event filter signals to manager
        _ = self._event_filter.scrub_started.connect(self._manager.start_scrub)  # pyright: ignore[reportAny]
        _ = self._event_filter.scrub_position_changed.connect(
            self._manager.update_scrub_position  # pyright: ignore[reportAny]
        )
        _ = self._event_filter.scrub_ended.connect(self._manager.end_scrub)  # pyright: ignore[reportAny]

        # Connect manager signals for view updates
        _ = self._manager.request_repaint.connect(on_repaint_needed)
        if on_scrub_started is not None:
            _ = self._manager.scrub_started.connect(on_scrub_started)
        if on_scrub_ended is not None:
            _ = self._manager.scrub_ended.connect(on_scrub_ended)

        # Pass manager to delegate for rendering
        delegate.set_scrub_manager(self._manager)

    def cleanup(self) -> None:
        """Tear down scrub preview resources.

        Clears internal references so objects can be garbage-collected.
        Qt parent ownership handles the actual destruction.
        """
        self._event_filter = None
        self._manager = None
