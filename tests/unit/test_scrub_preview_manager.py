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

    @pytest.mark.parametrize(
        ("ratio", "expected_frame"),
        [
            pytest.param(0.0, 1001, id="start"),
            pytest.param(1.0, 1100, id="end"),
            pytest.param(0.5, 1050, id="middle"),  # 0.5 * 99 = 49.5 → 49; 1001 + 49 = 1050
        ],
    )
    def test_ratio_to_frame(self, ratio: float, expected_frame: int) -> None:
        """Test ratio_to_frame maps 0.0→start, 1.0→end, 0.5→middle frame."""
        state = ScrubState(
            shot_key="show/seq/shot",
            workspace_path="/path",
            frame_start=1001,
            frame_end=1100,
        )

        assert state.ratio_to_frame(ratio) == expected_frame

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


class TestInvalidIndexReturnsNone:
    """Tests that all query methods return None/False for invalid index."""

    @pytest.mark.parametrize(
        ("method_name", "expected"),
        [
            pytest.param("get_scrub_state", None, id="get_scrub_state"),
            pytest.param("is_scrubbing", False, id="is_scrubbing"),
            pytest.param("get_current_frame", None, id="get_current_frame"),
            pytest.param("get_current_pixmap", None, id="get_current_pixmap"),
        ],
    )
    def test_returns_none_for_invalid_index(
        self, qapp: QApplication, method_name: str, expected: object
    ) -> None:
        """Test each query method returns None/False for an invalid QModelIndex."""
        manager = ScrubPreviewManager()
        result = getattr(manager, method_name)(QModelIndex())
        assert result == expected


class TestGetScrubState:
    """Tests for get_scrub_state method."""

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


class TestInactiveStateReturnsDefault:
    """Tests that query methods return inactive values when state is not active."""

    @pytest.mark.parametrize(
        ("method_name", "expected"),
        [
            pytest.param("is_scrubbing", False, id="is_scrubbing_when_not_active"),
            pytest.param("get_current_frame", None, id="get_current_frame_when_not_active"),
        ],
    )
    def test_returns_default_when_not_active(
        self, qapp: QApplication, method_name: str, expected: object
    ) -> None:
        """Test each method returns its default when state is present but not active."""
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

        assert getattr(manager, method_name)(index) == expected


class TestIsScrubbing:
    """Tests for is_scrubbing method."""

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
        """Test end_scrub clears scrub state and emits scrub_ended and request_repaint."""
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

        ended_signals: list[QModelIndex] = []
        repaint_signals: list[QModelIndex] = []
        manager.scrub_ended.connect(ended_signals.append)
        manager.request_repaint.connect(repaint_signals.append)

        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5

        manager._active_index = index

        manager.end_scrub(index)
        process_qt_events()

        assert 5 not in manager._scrub_states
        assert "test/shot" not in manager._key_to_row
        assert manager._active_index is None
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

    @pytest.mark.parametrize(
        ("shot_key", "frame", "desc"),
        [
            pytest.param("test/shot", 1055, "different_frame"),
            pytest.param("unknown/shot", 1050, "unknown_shot"),
        ],
    )
    def test_on_frame_ready_ignores_non_current(
        self, qapp: QApplication, shot_key: str, frame: int, desc: str
    ) -> None:
        """Test _on_frame_ready ignores frames that aren't current or shots unknown."""
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
        manager._key_to_row["test/shot"] = 5

        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        manager._on_frame_ready(shot_key, frame, image)  # Should not raise or update

        assert state.current_pixmap is None


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

    @pytest.mark.parametrize(
        ("show", "sequence", "shot_name", "expected_key"),
        [
            pytest.param("myshow", "sq010", "sh0010", "myshow/sq010/sh0010", id="shot_object"),
            pytest.param("show", "seq", "shot", "show/seq/shot", id="fallback_naming"),
        ],
    )
    def test_get_shot_key(
        self,
        qapp: QApplication,
        show: str,
        sequence: str,
        shot_name: str,
        expected_key: str,
    ) -> None:
        """Test _get_shot_key extracts key from Shot-like object."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.show = show
        shot.sequence = sequence
        shot.shot = shot_name

        key = manager._get_shot_key(shot)
        assert key == expected_key

    @pytest.mark.parametrize(
        ("workspace_path", "expected"),
        [
            pytest.param("/shows/myshow/shots/sq010/sh0010", "/shows/myshow/shots/sq010/sh0010", id="with_path"),
            pytest.param("", "", id="empty_path"),
        ],
    )
    def test_get_workspace_path(
        self, qapp: QApplication, workspace_path: str, expected: str
    ) -> None:
        """Test _get_workspace_path extracts workspace_path from Shot-like object."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.workspace_path = workspace_path

        path = manager._get_workspace_path(shot)
        assert path == expected

    @pytest.mark.parametrize(
        ("frame_start", "frame_end", "expected_start", "expected_end"),
        [
            pytest.param(1001, 1100, 1001, 1100, id="with_range"),
            pytest.param(None, None, None, None, id="none_range"),
        ],
    )
    def test_get_frame_range(
        self,
        qapp: QApplication,
        frame_start: int | None,
        frame_end: int | None,
        expected_start: int | None,
        expected_end: int | None,
    ) -> None:
        """Test _get_frame_range extracts range or returns None if absent."""
        manager = ScrubPreviewManager()

        shot = MagicMock()
        shot.frame_start = frame_start
        shot.frame_end = frame_end

        start, end = manager._get_frame_range(shot)
        assert start == expected_start
        assert end == expected_end


class TestUpdateScrubPosition:
    """Tests for update_scrub_position method."""

    def test_update_scrub_position_no_op_for_missing_state(
        self, qapp: QApplication
    ) -> None:
        """Test update_scrub_position handles invalid index or missing state gracefully."""
        manager = ScrubPreviewManager()

        # Invalid index should not raise
        manager.update_scrub_position(QModelIndex(), 0.5)

        # Valid index with no registered state should also not raise
        index = MagicMock(spec=QModelIndex)
        index.isValid.return_value = True
        index.row.return_value = 5
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


