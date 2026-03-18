"""Unit tests for ScrubPreviewManager - coordinator for scrub preview.

Tests focus on:
- Scrub state management
- Signal emission
- Integration with PlateFrameProvider
- Frame ready/failed handling
- Shot data extraction
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QImage, QPixmap

from scrub.plate_frame_provider import PlateSource
from scrub.scrub_preview_manager import ScrubPreviewManager, ScrubState
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:

    from PySide6.QtWidgets import QApplication

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestScrubState:
    """Tests for ScrubState dataclass."""

    def test_scrub_state_creation(self) -> None:
        """Test ScrubState can be created with required fields."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/shows/show/shots/seq/shot",
            frame_start=1001,
            frame_end=1100,
        )

        assert state.shot_key == "show/seq/shot"
        assert state.workspace_path == "/shows/show/shots/seq/shot"
        assert state.frame_start == 1001
        assert state.frame_end == 1100
        assert state.current_frame == 0  # Default
        assert state.is_active is False  # Default

    def test_scrub_state_frame_count(self) -> None:
        """Test frame_count property."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
        )

        assert state.frame_count == 100  # 1100 - 1001 + 1

    def test_ratio_to_frame_at_start(self) -> None:
        """Test ratio_to_frame at 0.0 returns first frame."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
        )

        assert state.ratio_to_frame(0.0) == 1001

    def test_ratio_to_frame_at_end(self) -> None:
        """Test ratio_to_frame at 1.0 returns last frame."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
        )

        assert state.ratio_to_frame(1.0) == 1100

    def test_ratio_to_frame_at_middle(self) -> None:
        """Test ratio_to_frame at 0.5 returns middle frame."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
        )

        # 0.5 * 99 frames = 49.5 → 49 (int)
        # 1001 + 49 = 1050
        assert state.ratio_to_frame(0.5) == 1050

    def test_current_pixmap_property(self, qapp: QApplication) -> None:
        """Test current_pixmap getter and setter."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
        )

        assert state.current_pixmap is None

        pixmap = QPixmap(100, 100)
        state.current_pixmap = pixmap

        assert state.current_pixmap is pixmap


class TestScrubPreviewManagerInit:
    """Tests for ScrubPreviewManager initialization."""

    def test_initialization(self, qapp: QApplication) -> None:
        """Test manager is properly initialized."""
        manager = ScrubPreviewManager()

        assert manager._prefetch_radius == 10  # Default (increased for smoother scrubbing)
        assert manager._frame_provider is not None
        assert len(manager._scrub_states) == 0
        assert len(manager._key_to_row) == 0
        assert manager._active_index is None

    def test_initialization_with_custom_prefetch(self, qapp: QApplication) -> None:
        """Test manager with custom prefetch radius."""
        manager = ScrubPreviewManager(prefetch_radius=15)

        assert manager._prefetch_radius == 15


class TestGetScrubState:
    """Tests for get_scrub_state method."""

    def test_get_scrub_state_returns_none_for_invalid_index(
        self, qapp: QApplication
    ) -> None:
        """Test get_scrub_state returns None for invalid index."""
        manager = ScrubPreviewManager()
        result = manager.get_scrub_state(QModelIndex())
        assert result is None

    def test_get_scrub_state_returns_none_for_unknown_row(
        self, qapp: QApplication
    ) -> None:
        """Test get_scrub_state returns None for unknown row."""
        manager = ScrubPreviewManager()

        # Create a mock index
        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        result = manager.get_scrub_state(index)
        assert result is None

    def test_get_scrub_state_returns_state_for_known_row(
        self, qapp: QApplication
    ) -> None:
        """Test get_scrub_state returns state for known row."""
        manager = ScrubPreviewManager()

        # Add a state
        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            is_active=True,
        )
        manager._scrub_states[5] = state

        # Create a mock index
        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        result = manager.get_scrub_state(index)
        assert result is state


class TestIsScrubbing:
    """Tests for is_scrubbing method."""

    def test_is_scrubbing_false_for_invalid_index(
        self, qapp: QApplication
    ) -> None:
        """Test is_scrubbing returns False for invalid index."""
        manager = ScrubPreviewManager()
        assert not manager.is_scrubbing(QModelIndex())

    def test_is_scrubbing_false_when_not_active(
        self, qapp: QApplication
    ) -> None:
        """Test is_scrubbing returns False when state not active."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            is_active=False,
        )
        manager._scrub_states[5] = state

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        assert not manager.is_scrubbing(index)

    def test_is_scrubbing_true_when_active(
        self, qapp: QApplication
    ) -> None:
        """Test is_scrubbing returns True when state is active."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            is_active=True,
        )
        manager._scrub_states[5] = state

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        assert manager.is_scrubbing(index)


class TestGetCurrentFrame:
    """Tests for get_current_frame method."""

    def test_get_current_frame_returns_none_for_invalid_index(
        self, qapp: QApplication
    ) -> None:
        """Test get_current_frame returns None for invalid index."""
        manager = ScrubPreviewManager()
        assert manager.get_current_frame(QModelIndex()) is None

    def test_get_current_frame_returns_none_when_not_active(
        self, qapp: QApplication
    ) -> None:
        """Test get_current_frame returns None when not active."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            current_frame=1050,
            is_active=False,
        )
        manager._scrub_states[5] = state

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        assert manager.get_current_frame(index) is None

    def test_get_current_frame_returns_frame_when_active(
        self, qapp: QApplication
    ) -> None:
        """Test get_current_frame returns frame when active."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            current_frame=1050,
            is_active=True,
        )
        manager._scrub_states[5] = state

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        assert manager.get_current_frame(index) == 1050


class TestGetCurrentPixmap:
    """Tests for get_current_pixmap method."""

    def test_get_current_pixmap_returns_none_for_invalid_index(
        self, qapp: QApplication
    ) -> None:
        """Test get_current_pixmap returns None for invalid index."""
        manager = ScrubPreviewManager()
        assert manager.get_current_pixmap(QModelIndex()) is None

    def test_get_current_pixmap_returns_pixmap_when_active(
        self, qapp: QApplication
    ) -> None:
        """Test get_current_pixmap returns pixmap when active."""
        manager = ScrubPreviewManager()

        pixmap = QPixmap(100, 100)
        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            is_active=True,
        )
        state.current_pixmap = pixmap
        manager._scrub_states[5] = state

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        result = manager.get_current_pixmap(index)
        assert result is pixmap


class TestEndScrub:
    """Tests for end_scrub method."""

    def test_end_scrub_with_invalid_index(
        self, qapp: QApplication
    ) -> None:
        """Test end_scrub handles invalid index gracefully."""
        manager = ScrubPreviewManager()
        # Should not raise
        manager.end_scrub(QModelIndex())

    def test_end_scrub_clears_state(
        self, qapp: QApplication
    ) -> None:
        """Test end_scrub clears scrub state."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            is_active=True,
        )
        manager._scrub_states[5] = state
        manager._key_to_row["test/shot"] = 5

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        manager._active_index = index

        manager.end_scrub(index)
        process_qt_events()

        assert 5 not in manager._scrub_states
        assert "test/shot" not in manager._key_to_row
        assert manager._active_index is None

    def test_end_scrub_emits_signals(
        self, qapp: QApplication
    ) -> None:
        """Test end_scrub emits scrub_ended and request_repaint."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            is_active=True,
        )
        manager._scrub_states[5] = state

        ended_signals: list[QModelIndex] = []
        repaint_signals: list[QModelIndex] = []

        manager.scrub_ended.connect(ended_signals.append)
        manager.request_repaint.connect(repaint_signals.append)

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        manager.end_scrub(index)
        process_qt_events()

        assert len(ended_signals) == 1
        assert len(repaint_signals) == 1


class TestCleanup:
    """Tests for cleanup method."""

    def test_cleanup_clears_all_states(
        self, qapp: QApplication
    ) -> None:
        """Test cleanup clears all scrub states."""
        manager = ScrubPreviewManager()

        # Add some states
        for i in range(5):
            state = ScrubState(
                shot_key=f"test/shot{i}",
                workspace_path=f"/path{i}",
                frame_start=1001,
                frame_end=1100,
                is_active=True,
            )
            manager._scrub_states[i] = state
            manager._key_to_row[f"test/shot{i}"] = i

        manager._active_index = MagicMock(spec=QModelIndex)

        manager.cleanup()

        assert len(manager._scrub_states) == 0
        assert len(manager._key_to_row) == 0
        assert manager._active_index is None

    def test_cleanup_clears_frame_provider_caches(
        self, qapp: QApplication
    ) -> None:
        """Test cleanup clears frame provider caches."""
        manager = ScrubPreviewManager()

        # Store something in cache
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        manager._frame_provider._cache.store("test/shot", 1001, image)

        manager.cleanup()

        assert not manager._frame_provider.has_cached_frame("test/shot", 1001)


class TestOnFrameReady:
    """Tests for _on_frame_ready handler."""

    def test_on_frame_ready_updates_current_pixmap(
        self, qapp: QApplication
    ) -> None:
        """Test _on_frame_ready updates current pixmap."""
        manager = ScrubPreviewManager()

        # Set up state
        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            current_frame=1050,
            is_active=True,
        )
        manager._scrub_states[5] = state
        manager._key_to_row["test/shot"] = 5
        manager._active_index = MagicMock(spec=QModelIndex)

        # Call handler
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        manager._on_frame_ready("test/shot", 1050, image)
        process_qt_events()

        assert state.current_pixmap is not None

    def test_on_frame_ready_ignores_different_frame(
        self, qapp: QApplication
    ) -> None:
        """Test _on_frame_ready ignores frames that aren't current."""
        manager = ScrubPreviewManager()

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            current_frame=1050,  # Current frame is 1050
            is_active=True,
        )
        manager._scrub_states[5] = state
        manager._key_to_row["test/shot"] = 5

        # Call handler with different frame
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        manager._on_frame_ready("test/shot", 1055, image)  # Not current

        assert state.current_pixmap is None

    def test_on_frame_ready_ignores_unknown_shot(
        self, qapp: QApplication
    ) -> None:
        """Test _on_frame_ready ignores unknown shots."""
        manager = ScrubPreviewManager()

        # Should not raise
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        manager._on_frame_ready("unknown/shot", 1050, image)


class TestOnFrameFailed:
    """Tests for _on_frame_failed handler."""

    def test_on_frame_failed_logs_error(
        self, qapp: QApplication
    ) -> None:
        """Test _on_frame_failed logs the error."""
        manager = ScrubPreviewManager()

        # Should not raise
        manager._on_frame_failed("test/shot", 1050, "Test error")


class TestShotDataExtraction:
    """Tests for shot data extraction methods."""

    def test_get_shot_key_with_shot_object(
        self, qapp: QApplication
    ) -> None:
        """Test _get_shot_key extracts key from Shot-like object."""
        manager = ScrubPreviewManager()

        # Mock a Shot-like object
        shot = MagicMock()
        shot.show = "myshow"
        shot.sequence = "sq010"
        shot.shot = "sh0010"

        key = manager._get_shot_key(shot)
        assert key == "myshow/sq010/sh0010"

    def test_get_shot_key_fallback(
        self, qapp: QApplication
    ) -> None:
        """Test _get_shot_key works with protocol-conforming object."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.show = "show"
        shot.sequence = "seq"
        shot.shot = "shot"
        key = manager._get_shot_key(shot)
        assert key == "show/seq/shot"

    def test_get_workspace_path_with_shot_object(
        self, qapp: QApplication
    ) -> None:
        """Test _get_workspace_path extracts path from Shot-like object."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.workspace_path = "/shows/myshow/shots/sq010/sh0010"

        path = manager._get_workspace_path(shot)
        assert path == "/shows/myshow/shots/sq010/sh0010"

    def test_get_workspace_path_returns_empty_for_missing(
        self, qapp: QApplication
    ) -> None:
        """Test _get_workspace_path returns empty string if workspace_path is empty."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.workspace_path = ""
        path = manager._get_workspace_path(shot)
        assert path == ""

    def test_get_frame_range_with_shot_object(
        self, qapp: QApplication
    ) -> None:
        """Test _get_frame_range extracts range from Shot-like object."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.frame_start = 1001
        shot.frame_end = 1100

        start, end = manager._get_frame_range(shot)
        assert start == 1001
        assert end == 1100

    def test_get_frame_range_returns_none_for_missing(
        self, qapp: QApplication
    ) -> None:
        """Test _get_frame_range returns None if frame_start/frame_end are None."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.frame_start = None
        shot.frame_end = None
        start, end = manager._get_frame_range(shot)
        assert start is None
        assert end is None


class TestUpdateScrubPosition:
    """Tests for update_scrub_position method."""

    def test_update_scrub_position_with_invalid_index(
        self, qapp: QApplication
    ) -> None:
        """Test update_scrub_position handles invalid index."""
        manager = ScrubPreviewManager()
        # Should not raise
        manager.update_scrub_position(QModelIndex(), 0.5)

    def test_update_scrub_position_with_no_state(
        self, qapp: QApplication
    ) -> None:
        """Test update_scrub_position handles missing state."""
        manager = ScrubPreviewManager()

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        # Should not raise
        manager.update_scrub_position(index, 0.5)

    def test_update_scrub_position_updates_current_frame(
        self, qapp: QApplication
    ) -> None:
        """Test update_scrub_position updates current frame."""
        manager = ScrubPreviewManager()

        from pathlib import Path

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            current_frame=1001,
            is_active=True,
            plate_source=PlateSource(
                source_path=Path("/test/plate.mov"),
                source_type="mov",
                frame_start=1001,
                frame_end=1100,
            ),
        )
        manager._scrub_states[5] = state

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        manager.update_scrub_position(index, 0.5)

        # Should have updated to middle frame
        assert state.current_frame == 1050

    def test_update_scrub_position_no_change_if_same_frame(
        self, qapp: QApplication
    ) -> None:
        """Test update_scrub_position returns early if same frame."""
        manager = ScrubPreviewManager()

        from pathlib import Path

        state = ScrubState(
            shot_key="test/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
            current_frame=1050,  # Already at middle
            is_active=True,
            plate_source=PlateSource(
                source_path=Path("/test/plate.mov"),
                source_type="mov",
                frame_start=1001,
                frame_end=1100,
            ),
        )
        manager._scrub_states[5] = state

        # Pre-cache the frame to avoid triggering extraction
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        manager._frame_provider._cache.store("test/shot", 1050, image)

        # Track extraction calls
        extract_calls: list[int] = []

        def mock_extract(key: str, source: PlateSource, frame: int) -> None:
            extract_calls.append(frame)

        manager._frame_provider.extract_frame = mock_extract  # type: ignore[method-assign]

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        # Update to same frame
        manager.update_scrub_position(index, 0.5)

        # Should not have called extract (same frame)
        assert len(extract_calls) == 0


