"""Unit tests for ShotGrid keyboard navigation."""

import pytest
from unittest.mock import Mock, MagicMock
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from shot_grid import ShotGrid
from shot_model import Shot, ShotModel


class TestShotGridKeyboard:
    """Test keyboard navigation in ShotGrid."""

    @pytest.fixture
    def shot_model(self):
        """Create a shot model with test data."""
        model = ShotModel()
        # Create 9 test shots (3x3 grid)
        model.shots = [
            Shot("show1", "seq1", f"shot{i:03d}", f"/path/shot{i:03d}")
            for i in range(9)
        ]
        return model

    @pytest.fixture
    def shot_grid(self, qapp, shot_model, monkeypatch):
        """Create a ShotGrid instance."""
        # Mock the column count to always return 3
        grid = ShotGrid(shot_model)
        monkeypatch.setattr(grid, "_get_column_count", lambda: 3)
        
        # Create mock thumbnails
        grid.thumbnails = {
            shot.full_name: Mock() for shot in shot_model.shots
        }
        
        # Mock scroll area
        grid.scroll_area = Mock()
        grid.scroll_area.ensureWidgetVisible = Mock()
        
        return grid

    def test_right_arrow_navigation(self, shot_grid):
        """Test right arrow key navigation."""
        # Select first shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        
        # Press right arrow
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.NoModifier
        )
        
        # Mock select_shot to track calls
        shot_grid.select_shot = Mock()
        
        shot_grid.keyPressEvent(event)
        
        # Should select the next shot
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[1])

    def test_left_arrow_navigation(self, shot_grid):
        """Test left arrow key navigation."""
        # Select second shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[1]
        
        # Press left arrow
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should select the previous shot
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[0])

    def test_down_arrow_navigation(self, shot_grid):
        """Test down arrow key navigation."""
        # Select first shot (top-left)
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        
        # Press down arrow
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Down,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should select the shot below (index 3 with 3 columns)
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[3])

    def test_up_arrow_navigation(self, shot_grid):
        """Test up arrow key navigation."""
        # Select shot at index 3 (second row)
        shot_grid.selected_shot = shot_grid.shot_model.shots[3]
        
        # Press up arrow
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Up,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should select the shot above (index 0)
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[0])

    def test_home_key_navigation(self, shot_grid):
        """Test Home key navigation."""
        # Select last shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[-1]
        
        # Press Home
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Home,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should select the first shot
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[0])

    def test_end_key_navigation(self, shot_grid):
        """Test End key navigation."""
        # Select first shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        
        # Press End
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_End,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should select the last shot
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[-1])

    def test_enter_key_launches_app(self, shot_grid):
        """Test Enter key emits double-click signal."""
        # Select a shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        
        # Connect signal spy
        signal_spy = Mock()
        shot_grid.shot_double_clicked.connect(signal_spy)
        
        # Press Enter
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.keyPressEvent(event)
        
        # Should emit double-click signal
        signal_spy.assert_called_once_with(shot_grid.shot_model.shots[0])

    def test_navigation_with_no_selection(self, shot_grid):
        """Test navigation when no shot is selected."""
        # No selection
        shot_grid.selected_shot = None
        
        # Press right arrow
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should select the first shot
        shot_grid.select_shot.assert_called_once_with(shot_grid.shot_model.shots[0])

    def test_navigation_at_boundaries(self, shot_grid):
        """Test navigation at grid boundaries."""
        # Test right arrow at last item
        shot_grid.selected_shot = shot_grid.shot_model.shots[-1]
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should not move past the end
        shot_grid.select_shot.assert_not_called()
        
        # Test left arrow at first item
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should not move before the start
        shot_grid.select_shot.assert_not_called()

    def test_ensure_visible_called(self, shot_grid):
        """Test that ensureWidgetVisible is called for navigation."""
        # Select first shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        
        # Press right arrow
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.select_shot = Mock()
        shot_grid.keyPressEvent(event)
        
        # Should ensure the widget is visible
        next_shot = shot_grid.shot_model.shots[1]
        expected_widget = shot_grid.thumbnails[next_shot.full_name]
        shot_grid.scroll_area.ensureWidgetVisible.assert_called_once_with(expected_widget)

    def test_unhandled_key_passed_through(self, shot_grid):
        """Test that unhandled keys are passed to parent."""
        # Select a shot
        shot_grid.selected_shot = shot_grid.shot_model.shots[0]
        
        # Mock parent keyPressEvent
        original_super = shot_grid.__class__.__bases__[0].keyPressEvent
        shot_grid.__class__.__bases__[0].keyPressEvent = Mock()
        
        # Press an unhandled key (e.g., 'A')
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.NoModifier
        )
        
        shot_grid.keyPressEvent(event)
        
        # Should pass to parent
        shot_grid.__class__.__bases__[0].keyPressEvent.assert_called_once()
        
        # Restore original
        shot_grid.__class__.__bases__[0].keyPressEvent = original_super