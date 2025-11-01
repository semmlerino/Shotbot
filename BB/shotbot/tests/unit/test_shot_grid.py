"""Unit tests for shot_grid.py"""

from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent

from config import Config
from shot_grid import ShotGrid
from shot_model import Shot
from tests.fixtures.test_data import TEST_SHOTS


class TestShotGrid:
    """Test ShotGrid widget functionality."""

    @pytest.fixture
    def shot_grid(self, qapp, mock_shot_model):
        """Create a ShotGrid instance."""
        grid = ShotGrid(mock_shot_model)
        # Simulate initial refresh
        grid.refresh_shots()
        return grid

    @pytest.fixture
    def empty_grid(self, qapp, mock_shot_model_empty):
        """Create an empty shot grid."""
        grid = ShotGrid(mock_shot_model_empty)
        grid.refresh_shots()
        return grid

    def test_initialization(self, qapp, mock_shot_model):
        """Test ShotGrid initialization."""
        grid = ShotGrid(mock_shot_model)

        assert grid.shot_model == mock_shot_model
        assert grid.thumbnails == {}
        assert grid.selected_shot is None
        assert grid._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE

        # Check UI elements
        assert grid.size_slider is not None
        assert grid.size_label is not None
        assert grid.scroll_area is not None
        assert grid.container is not None
        assert grid.grid_layout is not None

    def test_refresh_shots(self, shot_grid):
        """Test refreshing shot display."""
        # Should have thumbnails for all shots
        assert len(shot_grid.thumbnails) == len(TEST_SHOTS)

        # Check thumbnails are created
        for shot in TEST_SHOTS:
            assert shot.full_name in shot_grid.thumbnails
            thumbnail = shot_grid.thumbnails[shot.full_name]
            assert thumbnail.shot == shot

    def test_refresh_shots_empty(self, empty_grid):
        """Test refreshing with no shots."""
        assert len(empty_grid.thumbnails) == 0

    def test_clear_grid(self, shot_grid):
        """Test clearing the grid."""
        assert len(shot_grid.thumbnails) > 0

        shot_grid._clear_grid()

        assert len(shot_grid.thumbnails) == 0

    def test_thumbnail_size_slider(self, shot_grid):
        """Test thumbnail size slider."""
        # Check initial values
        assert shot_grid.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE
        assert shot_grid.size_label.text() == f"{Config.DEFAULT_THUMBNAIL_SIZE}px"

        # Change size
        new_size = 200
        shot_grid.size_slider.setValue(new_size)

        assert shot_grid._thumbnail_size == new_size
        assert shot_grid.size_label.text() == f"{new_size}px"

    def test_size_limits(self, shot_grid):
        """Test thumbnail size limits."""
        assert shot_grid.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE
        assert shot_grid.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE

    def test_thumbnail_clicked_signal(self, shot_grid):
        """Test thumbnail click signal emission."""
        signal_received = []
        shot_grid.shot_selected.connect(lambda s: signal_received.append(s))

        # Get first thumbnail
        shot = TEST_SHOTS[0]
        thumbnail = shot_grid.thumbnails[shot.full_name]

        # Simulate click
        thumbnail.clicked.emit(shot)

        assert len(signal_received) == 1
        assert signal_received[0] == shot
        assert shot_grid.selected_shot == shot

    def test_thumbnail_double_clicked_signal(self, shot_grid):
        """Test thumbnail double-click signal emission."""
        signal_received = []
        shot_grid.shot_double_clicked.connect(lambda s: signal_received.append(s))

        # Get first thumbnail
        shot = TEST_SHOTS[0]
        thumbnail = shot_grid.thumbnails[shot.full_name]

        # Simulate double-click
        thumbnail.double_clicked.emit(shot)

        assert len(signal_received) == 1
        assert signal_received[0] == shot

    def test_select_shot(self, shot_grid):
        """Test selecting a shot programmatically."""
        shot = TEST_SHOTS[2]

        shot_grid.select_shot(shot)

        assert shot_grid.selected_shot == shot
        # Check thumbnail is selected
        thumbnail = shot_grid.thumbnails[shot.full_name]
        assert thumbnail._selected

    def test_select_shot_not_in_grid(self, shot_grid):
        """Test selecting a shot that's not in the grid."""
        fake_shot = Shot("fake", "999_ZZZ", "9999", "/fake/path")

        # Should not crash
        shot_grid.select_shot(fake_shot)

        # Selection should still happen even if thumbnail doesn't exist
        assert shot_grid.selected_shot == fake_shot

    def test_zoom_in(self, shot_grid):
        """Test zooming in via wheel event."""
        initial_size = shot_grid._thumbnail_size

        # Create a real wheel event
        event = QWheelEvent(
            QPoint(100, 100),
            QPoint(100, 100),
            QPoint(0, 120),  # Positive delta = zoom in
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        shot_grid.wheelEvent(event)

        expected = min(initial_size + 10, Config.MAX_THUMBNAIL_SIZE)
        assert shot_grid._thumbnail_size == expected

    def test_zoom_out(self, shot_grid):
        """Test zooming out via wheel event."""
        initial_size = shot_grid._thumbnail_size

        # Create a real wheel event
        event = QWheelEvent(
            QPoint(100, 100),
            QPoint(100, 100),
            QPoint(0, -120),  # Negative delta = zoom out
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        shot_grid.wheelEvent(event)

        expected = max(initial_size - 10, Config.MIN_THUMBNAIL_SIZE)
        assert shot_grid._thumbnail_size == expected

    def test_set_thumbnail_size(self, shot_grid):
        """Test setting thumbnail size via slider."""
        new_size = 250

        shot_grid.size_slider.setValue(new_size)

        assert shot_grid._thumbnail_size == new_size
        assert shot_grid.size_label.text() == f"{new_size}px"

    def test_get_thumbnail_size(self, shot_grid):
        """Test getting current thumbnail size."""
        shot_grid._thumbnail_size = 180

        assert shot_grid._thumbnail_size == 180

    @patch("shot_grid.QWheelEvent")
    def test_wheel_event_zoom(self, mock_wheel_event, shot_grid):
        """Test mouse wheel zoom with Ctrl."""
        # Mock wheel event with Ctrl pressed and positive delta
        event = Mock()
        event.angleDelta.return_value.y.return_value = 120  # Positive = zoom in
        event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
        event.accept = Mock()

        initial_size = shot_grid._thumbnail_size

        # Send wheel event
        shot_grid.wheelEvent(event)

        # Should zoom in
        assert shot_grid._thumbnail_size > initial_size
        event.accept.assert_called_once()

    def test_wheel_event_no_ctrl(self, shot_grid):
        """Test mouse wheel without Ctrl passes through."""
        # Create a real wheel event without Ctrl
        event = QWheelEvent(
            QPoint(100, 100),
            QPoint(100, 100),
            QPoint(0, 120),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,  # No Ctrl
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        initial_size = shot_grid._thumbnail_size

        # Send wheel event
        shot_grid.wheelEvent(event)

        # Size should not change
        assert shot_grid._thumbnail_size == initial_size

    def test_column_count_calculation(self, shot_grid):
        """Test column count calculation."""
        # Mock viewport width
        shot_grid.scroll_area.viewport = Mock()
        shot_grid.scroll_area.viewport().width.return_value = 800

        # With default thumbnail size
        shot_grid._thumbnail_size = 150
        expected_cols = 800 // (150 + Config.THUMBNAIL_SPACING)
        assert shot_grid._get_column_count() == expected_cols

    def test_column_count_minimum(self, shot_grid):
        """Test minimum column count."""
        # Mock very narrow viewport
        shot_grid.scroll_area.viewport = Mock()
        shot_grid.scroll_area.viewport().width.return_value = 50

        # Should return at least 1 column
        assert shot_grid._get_column_count() >= 1

    def test_resize_event(self, shot_grid):
        """Test grid reflows on resize."""
        # Create a real resize event
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QResizeEvent

        event = QResizeEvent(QSize(800, 600), QSize(600, 400))

        # Should trigger reflow
        with patch.object(shot_grid, "_reflow_grid") as mock_reflow:
            shot_grid.resizeEvent(event)
            mock_reflow.assert_called_once()

    def test_selection_tracking(self, shot_grid):
        """Test selection state tracking."""
        shot1 = TEST_SHOTS[0]
        shot2 = TEST_SHOTS[1]

        # Select first shot
        shot_grid._on_thumbnail_clicked(shot1)
        assert shot_grid.selected_shot == shot1

        # Select second shot
        shot_grid._on_thumbnail_clicked(shot2)
        assert shot_grid.selected_shot == shot2

        # First should be deselected
        thumbnail1 = shot_grid.thumbnails[shot1.full_name]
        thumbnail2 = shot_grid.thumbnails[shot2.full_name]
        assert not thumbnail1._selected
        assert thumbnail2._selected
