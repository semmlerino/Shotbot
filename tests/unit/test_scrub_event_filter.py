"""Unit tests for ScrubEventFilter - viewport hover tracking for scrub preview.

Tests focus on:
- Event filter installation and basic operation
- Hover delay behavior
- X-ratio calculation
- Scrub state transitions
- Signal emissions
- Edge cases (scroll during scrub, rapid item changes)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QListView, QWidget

from scrub.scrub_event_filter import ScrubEventFilter
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

pytestmark = [pytest.mark.unit, pytest.mark.qt]


@pytest.fixture
def mock_view(qapp: QApplication) -> QListView:
    """Create a mock QListView for testing."""
    view = QListView()
    view.resize(400, 400)
    view.show()
    process_qt_events()
    return view


@pytest.fixture
def scrub_filter(mock_view: QListView) -> ScrubEventFilter:
    """Create a ScrubEventFilter for testing."""
    filter_obj = ScrubEventFilter(view=mock_view)
    mock_view.viewport().installEventFilter(filter_obj)
    return filter_obj


class TestScrubEventFilterInit:
    """Tests for ScrubEventFilter initialization."""

    def test_initialization_with_parent(
        self, mock_view: QListView, qapp: QApplication
    ) -> None:
        """Test filter with explicit parent."""
        parent = QWidget()
        filter_obj = ScrubEventFilter(view=mock_view, parent=parent)

        assert filter_obj.parent() is parent

    def test_hover_timer_is_single_shot(self, mock_view: QListView) -> None:
        """Test hover timer is single-shot."""
        filter_obj = ScrubEventFilter(view=mock_view)
        assert filter_obj._hover_timer.isSingleShot()


class TestEventFiltering:
    """Tests for event filtering behavior."""

    def test_filter_ignores_non_viewport_events(
        self, scrub_filter: ScrubEventFilter, mock_view: QListView
    ) -> None:
        """Test filter ignores events not from viewport."""
        other_widget = QWidget()
        event = QEvent(QEvent.Type.MouseMove)

        result = scrub_filter.eventFilter(other_widget, event)

        assert result is False

    def test_filter_handles_viewport_mouse_move(
        self, scrub_filter: ScrubEventFilter, mock_view: QListView
    ) -> None:
        """Test filter processes mouse move on viewport."""
        viewport = mock_view.viewport()

        # Create mouse move event
        pos = QPoint(100, 100).toPointF()
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            pos,
            pos,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )

        # Should not consume event
        result = scrub_filter.eventFilter(viewport, event)
        assert result is False

    def test_filter_handles_leave_event(
        self, scrub_filter: ScrubEventFilter, mock_view: QListView
    ) -> None:
        """Test filter processes leave event."""
        viewport = mock_view.viewport()
        event = QEvent(QEvent.Type.Leave)

        result = scrub_filter.eventFilter(viewport, event)

        assert result is False

    def test_filter_cancels_scrub_on_wheel(
        self, scrub_filter: ScrubEventFilter, mock_view: QListView
    ) -> None:
        """Test wheel event cancels active scrub."""
        # Manually set scrubbing state
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = QModelIndex()

        viewport = mock_view.viewport()
        event = QEvent(QEvent.Type.Wheel)

        scrub_filter.eventFilter(viewport, event)

        assert not scrub_filter._is_scrubbing


class TestXRatioCalculation:
    """Tests for x-ratio calculation."""

    def test_x_ratio_at_left_edge(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test x-ratio is 0.0 at left edge."""
        rect = QRect(100, 50, 200, 100)
        ratio = scrub_filter._calculate_x_ratio(100, rect)
        assert ratio == pytest.approx(0.0)

    def test_x_ratio_at_right_edge(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test x-ratio is 1.0 at right edge."""
        rect = QRect(100, 50, 200, 100)
        ratio = scrub_filter._calculate_x_ratio(300, rect)
        assert ratio == pytest.approx(1.0)

    def test_x_ratio_at_center(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test x-ratio is 0.5 at center."""
        rect = QRect(100, 50, 200, 100)
        ratio = scrub_filter._calculate_x_ratio(200, rect)
        assert ratio == pytest.approx(0.5)

    def test_x_ratio_clamped_below_zero(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test x-ratio is clamped to 0.0 if mouse is left of rect."""
        rect = QRect(100, 50, 200, 100)
        ratio = scrub_filter._calculate_x_ratio(50, rect)
        assert ratio == 0.0

    def test_x_ratio_clamped_above_one(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test x-ratio is clamped to 1.0 if mouse is right of rect."""
        rect = QRect(100, 50, 200, 100)
        ratio = scrub_filter._calculate_x_ratio(350, rect)
        assert ratio == 1.0

    def test_x_ratio_with_zero_width_rect(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test x-ratio returns 0.5 for zero-width rect."""
        rect = QRect(100, 50, 0, 100)
        ratio = scrub_filter._calculate_x_ratio(100, rect)
        assert ratio == 0.5


class TestHoverDelayBehavior:
    """Tests for hover delay behavior."""

    def test_start_hover_delay_sets_pending_state(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test starting hover delay sets pending state."""
        index = QModelIndex()
        rect = QRect(0, 0, 200, 100)

        scrub_filter._start_hover_delay(index, rect)

        assert scrub_filter._hover_pending is True
        assert scrub_filter._pending_index == index
        assert scrub_filter._pending_rect == rect
        assert scrub_filter._hover_timer.isActive()

    def test_start_hover_delay_ends_previous_scrub(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test starting new hover delay ends previous scrub."""
        # Set up existing scrub state
        old_index = QModelIndex()
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = old_index

        # Track signal emission
        ended_signals: list[QModelIndex] = []
        scrub_filter.scrub_ended.connect(ended_signals.append)

        # Start new hover delay
        new_index = QModelIndex()
        rect = QRect(0, 0, 200, 100)
        scrub_filter._start_hover_delay(new_index, rect)
        process_qt_events()

        assert not scrub_filter._is_scrubbing
        assert len(ended_signals) == 1

    def test_start_hover_delay_stops_previous_timer(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test starting new hover delay stops previous timer."""
        index1 = QModelIndex()
        rect = QRect(0, 0, 200, 100)

        scrub_filter._start_hover_delay(index1, rect)
        assert scrub_filter._hover_timer.isActive()

        # Start another hover
        index2 = QModelIndex()
        scrub_filter._start_hover_delay(index2, rect)

        # Timer should still be active but for new index
        assert scrub_filter._hover_timer.isActive()
        assert scrub_filter._pending_index == index2


class TestCancelScrub:
    """Tests for cancel scrub behavior."""

    def test_cancel_scrub_stops_timer(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test cancel_scrub stops hover timer."""
        scrub_filter._hover_timer.start(1000)
        scrub_filter._cancel_scrub()
        assert not scrub_filter._hover_timer.isActive()

    def test_cancel_scrub_clears_pending_state(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test cancel_scrub clears pending state."""
        scrub_filter._hover_pending = True
        scrub_filter._pending_index = QModelIndex()
        scrub_filter._pending_rect = QRect(0, 0, 100, 100)

        scrub_filter._cancel_scrub()

        assert not scrub_filter._hover_pending
        assert scrub_filter._pending_index is None
        assert scrub_filter._pending_rect is None

    def test_cancel_scrub_emits_ended_signal(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test cancel_scrub emits scrub_ended when scrubbing."""
        current_index = QModelIndex()
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = current_index

        ended_signals: list[QModelIndex] = []
        scrub_filter.scrub_ended.connect(ended_signals.append)

        scrub_filter._cancel_scrub()
        process_qt_events()

        assert len(ended_signals) == 1

    def test_cancel_scrub_clears_scrub_state(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test cancel_scrub clears scrub state."""
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = QModelIndex()
        scrub_filter._current_rect = QRect(0, 0, 100, 100)

        scrub_filter._cancel_scrub()

        assert not scrub_filter._is_scrubbing
        assert scrub_filter._current_index is None
        assert scrub_filter._current_rect is None

    def test_cancel_scrub_no_signal_if_not_scrubbing(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test cancel_scrub doesn't emit if not scrubbing."""
        scrub_filter._is_scrubbing = False
        scrub_filter._current_index = None

        ended_signals: list[QModelIndex] = []
        scrub_filter.scrub_ended.connect(ended_signals.append)

        scrub_filter._cancel_scrub()
        process_qt_events()

        assert len(ended_signals) == 0


class TestProperties:
    """Tests for properties."""

    def test_is_scrubbing_property(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test is_scrubbing property returns correct state."""
        assert not scrub_filter.is_scrubbing

        scrub_filter._is_scrubbing = True
        assert scrub_filter.is_scrubbing

    def test_current_index_property(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test current_index property returns correct value."""
        assert scrub_filter.current_index is None

        index = QModelIndex()
        scrub_filter._current_index = index
        assert scrub_filter.current_index == index


class TestStopMethod:
    """Tests for stop() method."""

    def test_stop_cancels_scrub(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test stop() cancels active scrub."""
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = QModelIndex()

        scrub_filter.stop()

        assert not scrub_filter._is_scrubbing
        assert scrub_filter._current_index is None

    def test_stop_stops_timer(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test stop() stops hover timer."""
        scrub_filter._hover_timer.start(1000)

        scrub_filter.stop()

        assert not scrub_filter._hover_timer.isActive()


class TestSignals:
    """Tests for signal definitions."""

    def test_scrub_started_signal_exists(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test scrub_started signal is properly defined."""
        assert hasattr(scrub_filter, "scrub_started")

    def test_scrub_position_changed_signal_exists(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test scrub_position_changed signal is properly defined."""
        assert hasattr(scrub_filter, "scrub_position_changed")

    def test_scrub_ended_signal_exists(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test scrub_ended signal is properly defined."""
        assert hasattr(scrub_filter, "scrub_ended")


class TestHandleMouseMoveIntegration:
    """Integration tests for mouse move handling."""

    def test_mouse_move_over_invalid_index_cancels_scrub(
        self, scrub_filter: ScrubEventFilter, mock_view: QListView
    ) -> None:
        """Test mouse move over empty area cancels scrub."""
        # Set up scrubbing state
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = QModelIndex()

        # Create mouse event
        pos = QPoint(100, 100).toPointF()
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            pos,
            pos,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )

        # Mock indexAt to return invalid index
        with patch.object(mock_view, "indexAt", return_value=QModelIndex()):
            scrub_filter._handle_mouse_move(event)

        assert not scrub_filter._is_scrubbing

    def test_mouse_leave_cancels_scrub(
        self, scrub_filter: ScrubEventFilter, mock_view: QListView
    ) -> None:
        """Test mouse leave cancels active scrub."""
        # Set up scrubbing state
        scrub_filter._is_scrubbing = True
        scrub_filter._current_index = QModelIndex()

        scrub_filter._handle_leave()

        assert not scrub_filter._is_scrubbing


class TestEdgeCases:
    """Tests for edge cases."""

    def test_rapid_index_changes(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test rapid changes between items work correctly."""
        rect = QRect(0, 0, 200, 100)

        # Rapidly switch between items
        for _ in range(5):
            index = QModelIndex()
            scrub_filter._start_hover_delay(index, rect)

        # Should only have one pending
        assert scrub_filter._hover_pending
        assert scrub_filter._hover_timer.isActive()

    def test_cancel_during_hover_delay(
        self, scrub_filter: ScrubEventFilter
    ) -> None:
        """Test canceling during hover delay clears properly."""
        index = QModelIndex()
        rect = QRect(0, 0, 200, 100)

        scrub_filter._start_hover_delay(index, rect)
        assert scrub_filter._hover_timer.isActive()

        scrub_filter._cancel_scrub()

        assert not scrub_filter._hover_timer.isActive()
        assert not scrub_filter._hover_pending

    def test_cleanup_on_view_destruction(
        self, qapp: QApplication
    ) -> None:
        """Test filter cleanup when view is destroyed."""
        view = QListView()
        view.show()
        process_qt_events()

        filter_obj = ScrubEventFilter(view=view)
        view.viewport().installEventFilter(filter_obj)

        # Start a hover delay
        filter_obj._hover_timer.start(1000)
        filter_obj._is_scrubbing = True

        # Clean up via stop()
        filter_obj.stop()

        assert not filter_obj._hover_timer.isActive()
        assert not filter_obj._is_scrubbing
