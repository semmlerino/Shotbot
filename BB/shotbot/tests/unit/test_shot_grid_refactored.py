"""Unit tests for shot_grid.py - REFACTORED with reduced mocking.

This refactored version demonstrates mock reduction best practices:
- Uses real ShotModel instead of Mock()
- Creates real Shot objects for testing
- Uses qtbot for proper widget lifecycle management
- Tests real Qt widget behavior instead of mocked methods
- Reduces mock usage from 11 to ~2 occurrences (82% reduction)
"""

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QResizeEvent, QWheelEvent

from config import Config
from shot_grid import ShotGrid
from shot_model import Shot


class TestShotGridRefactored:
    """Test ShotGrid with minimal mocking - uses real widgets and models."""

    # Note: real_shot_model and empty_shot_model fixtures are now provided by conftest.py

    @pytest.fixture
    def shot_grid(self, qtbot, real_shot_model, sample_shots):
        """Create a real ShotGrid instance with test data."""
        # Override with 4 specific test shots for these tests
        real_shot_model.shots = [
            Shot(
                "testshow",
                "101_ABC",
                "0010",
                "/shows/testshow/shots/101_ABC/101_ABC_0010",
            ),
            Shot(
                "testshow",
                "101_ABC",
                "0020",
                "/shows/testshow/shots/101_ABC/101_ABC_0020",
            ),
            Shot(
                "testshow",
                "102_XYZ",
                "0030",
                "/shows/testshow/shots/102_XYZ/102_XYZ_0030",
            ),
            Shot(
                "othershow",
                "201_FOO",
                "0040",
                "/shows/othershow/shots/201_FOO/201_FOO_0040",
            ),
        ]

        grid = ShotGrid(real_shot_model)
        qtbot.addWidget(grid)

        # Refresh to populate thumbnails
        grid.refresh_shots()

        return grid

    @pytest.fixture
    def empty_grid(self, qtbot, empty_shot_model):
        """Create an empty shot grid with real widgets."""
        grid = ShotGrid(empty_shot_model)
        qtbot.addWidget(grid)
        grid.refresh_shots()

        return grid

    def test_initialization_with_real_widgets(self, qtbot, real_shot_model):
        """Test ShotGrid initialization with real Qt widgets."""
        grid = ShotGrid(real_shot_model)
        qtbot.addWidget(grid)

        # Verify real widget properties
        assert grid.shot_model == real_shot_model
        assert isinstance(grid.thumbnails, dict)
        assert grid.selected_shot is None
        assert grid._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE

        # Check real UI elements exist and are widgets
        assert grid.size_slider is not None
        assert grid.size_label is not None
        assert grid.scroll_area is not None
        assert grid.container is not None
        assert grid.grid_layout is not None

        # Verify slider configuration
        assert grid.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE
        assert grid.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE
        assert grid.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE

    def test_refresh_shots_with_real_data(self, shot_grid, real_shot_model):
        """Test refreshing shot display with real model and widgets."""
        # Should have thumbnails for all shots
        assert len(shot_grid.thumbnails) == len(real_shot_model.shots)

        # Check thumbnails are created for real shots
        for shot in real_shot_model.shots:
            assert shot.full_name in shot_grid.thumbnails
            thumbnail = shot_grid.thumbnails[shot.full_name]
            assert thumbnail.shot == shot
            # Verify it's a real widget
            assert thumbnail.parent() is not None

    def test_refresh_empty_grid_real(self, empty_grid):
        """Test refreshing with no shots using real empty model."""
        assert len(empty_grid.thumbnails) == 0
        # Verify grid is truly empty
        assert empty_grid.grid_layout.count() == 0

    def test_clear_grid_with_real_widgets(self, shot_grid):
        """Test clearing the grid removes real widgets."""
        initial_count = len(shot_grid.thumbnails)
        assert initial_count > 0

        # Clear the grid
        shot_grid._clear_grid()

        # Verify all thumbnails removed
        assert len(shot_grid.thumbnails) == 0
        assert shot_grid.grid_layout.count() == 0

    def test_thumbnail_size_slider_real_interaction(self, qtbot, shot_grid):
        """Test thumbnail size slider with real Qt interactions."""
        # Check initial values
        assert shot_grid.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE
        assert shot_grid.size_label.text() == f"{Config.DEFAULT_THUMBNAIL_SIZE}px"

        # Change size using real slider
        new_size = 200
        shot_grid.size_slider.setValue(new_size)

        # Verify real updates
        assert shot_grid._thumbnail_size == new_size
        assert shot_grid.size_label.text() == f"{new_size}px"

        # Test limits
        shot_grid.size_slider.setValue(Config.MAX_THUMBNAIL_SIZE + 100)
        assert shot_grid.size_slider.value() == Config.MAX_THUMBNAIL_SIZE

        shot_grid.size_slider.setValue(Config.MIN_THUMBNAIL_SIZE - 50)
        assert shot_grid.size_slider.value() == Config.MIN_THUMBNAIL_SIZE

    def test_thumbnail_clicked_signal_with_real_qt(
        self, qtbot, shot_grid, real_shot_model
    ):
        """Test thumbnail click signal emission with real Qt signals."""
        shot = real_shot_model.shots[0]
        thumbnail = shot_grid.thumbnails[shot.full_name]

        # Spy on the real signal
        with qtbot.waitSignal(shot_grid.shot_selected, timeout=1000) as blocker:
            # Emit the signal from real thumbnail
            thumbnail.clicked.emit(shot)

        # Verify signal data
        assert blocker.args[0] == shot
        assert shot_grid.selected_shot == shot
        assert thumbnail._selected is True

    def test_thumbnail_double_clicked_real_signal(
        self, qtbot, shot_grid, real_shot_model
    ):
        """Test thumbnail double-click with real Qt signal."""
        shot = real_shot_model.shots[1]
        thumbnail = shot_grid.thumbnails[shot.full_name]

        # Spy on the double-click signal
        with qtbot.waitSignal(shot_grid.shot_double_clicked, timeout=1000) as blocker:
            thumbnail.double_clicked.emit(shot)

        assert blocker.args[0] == shot

    def test_select_shot_programmatically(self, shot_grid, real_shot_model):
        """Test selecting a shot programmatically with real widgets."""
        shot = real_shot_model.shots[2]

        # Select the shot
        shot_grid.select_shot(shot)

        # Verify selection
        assert shot_grid.selected_shot == shot

        # Check thumbnail is visually selected
        thumbnail = shot_grid.thumbnails[shot.full_name]
        assert thumbnail._selected is True

        # Verify other thumbnails are not selected
        for other_shot in real_shot_model.shots:
            if other_shot != shot:
                other_thumb = shot_grid.thumbnails[other_shot.full_name]
                assert other_thumb._selected is False

    def test_select_nonexistent_shot(self, shot_grid):
        """Test selecting a shot that's not in the grid."""
        # Create a shot that doesn't exist in the grid
        fake_shot = Shot("fake", "999_ZZZ", "9999", "/fake/path")

        # Should not crash
        shot_grid.select_shot(fake_shot)

        # Selection should still update
        assert shot_grid.selected_shot == fake_shot

        # No thumbnail should be selected
        for thumbnail in shot_grid.thumbnails.values():
            assert thumbnail._selected is False

    def test_wheel_zoom_with_real_event(self, qtbot, shot_grid):
        """Test mouse wheel zoom with real Qt wheel events."""
        initial_size = shot_grid._thumbnail_size

        # Create real wheel event for zoom in
        zoom_in_event = QWheelEvent(
            QPoint(100, 100),
            QPoint(100, 100),
            QPoint(0, 120),  # Positive delta
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,  # Ctrl pressed
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        # Send event
        shot_grid.wheelEvent(zoom_in_event)

        # Verify zoom in
        expected = min(initial_size + 10, Config.MAX_THUMBNAIL_SIZE)
        assert shot_grid._thumbnail_size == expected

        # Create zoom out event
        zoom_out_event = QWheelEvent(
            QPoint(100, 100),
            QPoint(100, 100),
            QPoint(0, -120),  # Negative delta
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        # Send event
        shot_grid.wheelEvent(zoom_out_event)

        # Verify zoom out
        expected = max(expected - 10, Config.MIN_THUMBNAIL_SIZE)
        assert shot_grid._thumbnail_size == expected

    def test_wheel_without_ctrl_passthrough(self, shot_grid):
        """Test mouse wheel without Ctrl doesn't zoom."""
        initial_size = shot_grid._thumbnail_size

        # Create wheel event without Ctrl
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

        shot_grid.wheelEvent(event)

        # Size should not change
        assert shot_grid._thumbnail_size == initial_size

    def test_column_count_calculation_real_viewport(self, shot_grid):
        """Test column count calculation with real viewport."""
        # Get actual viewport width
        viewport_width = shot_grid.scroll_area.viewport().width()

        # Calculate expected columns
        expected_cols = max(
            1, viewport_width // (shot_grid._thumbnail_size + Config.THUMBNAIL_SPACING)
        )
        actual_cols = shot_grid._get_column_count()

        # Should match calculation
        assert actual_cols == expected_cols
        assert actual_cols >= 1  # Always at least 1 column

    def test_resize_event_triggers_reflow(self, qtbot, shot_grid):
        """Test resize event with real Qt resize event."""
        # Track if reflow was called
        reflow_called = False
        original_reflow = shot_grid._reflow_grid

        def track_reflow():
            nonlocal reflow_called
            reflow_called = True
            original_reflow()

        shot_grid._reflow_grid = track_reflow

        # Create and send real resize event
        event = QResizeEvent(QSize(800, 600), QSize(600, 400))
        shot_grid.resizeEvent(event)

        # Verify reflow was triggered
        assert reflow_called

    def test_selection_state_management(self, shot_grid, real_shot_model):
        """Test selection state management with real shots."""
        shot1 = real_shot_model.shots[0]
        shot2 = real_shot_model.shots[1]

        # Select first shot
        shot_grid._on_thumbnail_clicked(shot1)
        assert shot_grid.selected_shot == shot1
        thumbnail1 = shot_grid.thumbnails[shot1.full_name]
        assert thumbnail1._selected is True

        # Select second shot
        shot_grid._on_thumbnail_clicked(shot2)
        assert shot_grid.selected_shot == shot2
        thumbnail2 = shot_grid.thumbnails[shot2.full_name]
        assert thumbnail2._selected is True

        # First should be deselected
        assert thumbnail1._selected is False

    def test_grid_reflow_on_size_change(self, qtbot, shot_grid):
        """Test grid reflows when thumbnail size changes."""
        # Change thumbnail size
        original_size = shot_grid._thumbnail_size
        new_size = original_size + 50

        # Track reflow
        reflow_count = 0
        original_reflow = shot_grid._reflow_grid

        def count_reflow():
            nonlocal reflow_count
            reflow_count += 1
            original_reflow()

        shot_grid._reflow_grid = count_reflow

        # Change size via slider
        shot_grid.size_slider.setValue(new_size)

        # Verify reflow happened
        assert reflow_count > 0
        assert shot_grid._thumbnail_size == new_size

    def test_empty_grid_displays_correctly(self, empty_grid):
        """Test empty grid displays correctly with no shots."""
        # Grid should be empty
        assert len(empty_grid.thumbnails) == 0
        assert empty_grid.grid_layout.count() == 0

        # Selected shot should be None
        assert empty_grid.selected_shot is None

        # Size controls should still work
        assert empty_grid.size_slider.isEnabled()
        new_size = 200
        empty_grid.size_slider.setValue(new_size)
        assert empty_grid._thumbnail_size == new_size
