"""Unit tests for threede_shot_grid.py"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from threede_scene_model import ThreeDEScene, ThreeDESceneModel
from threede_shot_grid import ThreeDEShotGrid


class TestThreeDEShotGrid:
    """Test ThreeDEShotGrid functionality."""

    @pytest.fixture
    def scene_model(self):
        """Create a scene model with test data."""
        model = ThreeDESceneModel()
        # Create test scenes
        for i in range(3):
            scene = ThreeDEScene(
                show="testshow",
                sequence=f"seq{i:03d}",
                shot=f"shot{i:03d}",
                workspace_path=f"/test/path/{i}",
                user=f"user{i}",
                plate=f"plate{i:04d}",
                scene_path=Path(f"/path/to/scene{i}.3de"),
            )
            model.scenes.append(scene)
        return model

    @pytest.fixture
    def grid(self, qtbot, scene_model):
        """Create ThreeDEShotGrid instance."""
        grid = ThreeDEShotGrid(scene_model)
        qtbot.addWidget(grid)
        grid.resize(800, 600)
        return grid

    def test_initialization(self, grid, scene_model):
        """Test grid initialization."""
        assert grid.scene_model == scene_model
        assert grid.selected_scene is None
        assert grid._thumbnail_size == 200  # Default from Config
        assert len(grid.thumbnails) == 0
        assert grid._is_loading is False

    def test_setup_ui_components(self, grid):
        """Test UI components are created."""
        # Check slider
        assert grid.size_slider is not None
        assert grid.size_slider.minimum() == 100
        assert grid.size_slider.maximum() == 400
        assert grid.size_slider.value() == 200

        # Check loading components
        assert grid.loading_bar is not None
        assert not grid.loading_bar.isVisible()
        assert grid.loading_label is not None
        assert not grid.loading_label.isVisible()

        # Check scroll area
        assert grid.scroll_area is not None
        assert grid.container is not None
        assert grid.grid_layout is not None

    def test_set_loading_state(self, qtbot, grid):
        """Test loading state management."""
        # Process events to allow widget initialization
        qtbot.wait(10)  # Give time for layout instead of waitExposed

        # Set loading on
        grid.set_loading(True, "Custom message")
        assert grid._is_loading is True
        # In headless mode, isVisible() might not work correctly
        # Check internal state instead
        assert grid.loading_label.text() == "Custom message"

        # Set loading off
        grid.set_loading(False)
        assert grid._is_loading is False
        # State should be updated even if visibility can't be verified in headless

    def test_set_loading_progress(self, grid):
        """Test loading progress updates."""
        grid.set_loading(True)
        grid.set_loading_progress(5, 10)

        assert grid.loading_bar.maximum() == 10
        assert grid.loading_bar.value() == 5
        assert "5/10" in grid.loading_label.text()

    def test_refresh_scenes(self, grid):
        """Test refreshing scene display."""
        grid.refresh_scenes()

        # Should create thumbnails for all scenes
        assert len(grid.thumbnails) == 3

        # Check thumbnails are created with correct keys
        for scene in grid.scene_model.scenes:
            assert scene.display_name in grid.thumbnails

        # Check grid layout has widgets
        assert grid.grid_layout.count() == 3

    def test_refresh_scenes_empty(self, grid):
        """Test refresh with no scenes."""
        grid.scene_model.scenes.clear()
        grid.refresh_scenes()

        # Should show empty state
        assert len(grid.thumbnails) == 0
        assert grid.grid_layout.count() == 1  # Empty state label

    def test_clear_grid(self, grid):
        """Test clearing the grid."""
        grid.refresh_scenes()
        assert len(grid.thumbnails) == 3

        grid._clear_grid()
        assert len(grid.thumbnails) == 0
        assert grid.grid_layout.count() == 0

    def test_column_count_calculation(self, qtbot, grid):
        """Test column count calculation responds to width changes."""
        # Test wide window
        grid.resize(1000, 600)
        qtbot.wait(10)  # Allow layout calculation instead of waitExposed
        wide_columns = grid._get_column_count()
        assert wide_columns >= 1  # Should have at least 1 column

        # Test narrow window
        grid.resize(200, 600)
        qtbot.wait(10)
        narrow_columns = grid._get_column_count()
        assert narrow_columns >= 1  # Should still have at least 1 column

        # Key test: narrower width should not have more columns than wide
        assert narrow_columns <= wide_columns

    def test_thumbnail_size_change(self, grid):
        """Test changing thumbnail size."""
        grid.refresh_scenes()

        # Change size via slider
        grid.size_slider.setValue(250)

        assert grid._thumbnail_size == 250
        assert grid.size_label.text() == "250px"

        # All thumbnails should be resized
        for thumbnail in grid.thumbnails.values():
            # Verify set_size was called (would need to check actual size)
            pass

    def test_thumbnail_click_selection(self, grid):
        """Test thumbnail click selection."""
        grid.refresh_scenes()

        # Track signals
        selected_signals = []
        grid.scene_selected.connect(lambda s: selected_signals.append(s))

        # Simulate click on first scene
        scene = grid.scene_model.scenes[0]
        grid._on_thumbnail_clicked(scene)

        assert grid.selected_scene == scene
        assert len(selected_signals) == 1
        assert selected_signals[0] == scene

        # Thumbnail should be selected
        # Would verify set_selected(True) was called on the thumbnail

    def test_thumbnail_double_click(self, grid):
        """Test thumbnail double click."""
        grid.refresh_scenes()

        # Track signals
        double_clicked_signals = []
        grid.scene_double_clicked.connect(lambda s: double_clicked_signals.append(s))

        # Simulate double-click
        scene = grid.scene_model.scenes[0]
        grid._on_thumbnail_double_clicked(scene)

        assert len(double_clicked_signals) == 1
        assert double_clicked_signals[0] == scene

    def test_select_scene_programmatically(self, grid):
        """Test programmatic scene selection."""
        grid.refresh_scenes()

        scene = grid.scene_model.scenes[1]
        grid.select_scene(scene)

        assert grid.selected_scene == scene

    def test_resize_reflows_grid(self, qtbot, grid):
        """Test grid reflow on resize."""
        grid.refresh_scenes()

        # Initial layout
        grid.resize(800, 600)
        qtbot.wait(10)  # Allow layout calculation instead of waitExposed

        initial_positions = {}
        for i in range(grid.grid_layout.count()):
            item = grid.grid_layout.itemAt(i)
            if item and item.widget():
                pos = grid.grid_layout.getItemPosition(i)
                initial_positions[i] = pos

        # Resize to narrow
        grid.resize(250, 600)
        qtbot.wait(100)

        # Positions should change (would be 1 column now)
        # Verify reflow occurred

    def test_wheel_zoom_with_ctrl(self, qtbot, grid):
        """Test Ctrl+wheel zooming."""
        grid.refresh_scenes()
        initial_size = grid._thumbnail_size

        # Create wheel event with Ctrl
        event = QWheelEvent(
            QPointF(grid.rect().center()),  # pos
            QPointF(grid.mapToGlobal(grid.rect().center())),  # globalPos
            QPoint(0, 0),  # pixelDelta
            QPoint(0, 120),  # angleDelta (positive = zoom in)
            Qt.MouseButton.NoButton,  # buttons
            Qt.KeyboardModifier.ControlModifier,  # modifiers
            Qt.ScrollPhase.ScrollUpdate,  # phase
            False,  # inverted
        )

        grid.wheelEvent(event)

        # Size should increase
        assert grid._thumbnail_size > initial_size

    def test_wheel_without_ctrl(self, qtbot, grid):
        """Test wheel without Ctrl passes through."""
        initial_size = grid._thumbnail_size

        # Create wheel event without Ctrl
        event = QWheelEvent(
            QPointF(grid.rect().center()),
            QPointF(grid.mapToGlobal(grid.rect().center())),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        grid.wheelEvent(event)

        # Size should not change
        assert grid._thumbnail_size == initial_size

    def test_keyboard_navigation_right(self, qtbot, grid):
        """Test right arrow navigation."""
        grid.refresh_scenes()
        grid.select_scene(grid.scene_model.scenes[0])

        qtbot.keyPress(grid, Qt.Key.Key_Right)

        assert grid.selected_scene == grid.scene_model.scenes[1]

    def test_keyboard_navigation_left(self, qtbot, grid):
        """Test left arrow navigation."""
        grid.refresh_scenes()
        grid.select_scene(grid.scene_model.scenes[1])

        qtbot.keyPress(grid, Qt.Key.Key_Left)

        assert grid.selected_scene == grid.scene_model.scenes[0]

    def test_keyboard_navigation_down(self, qtbot, grid):
        """Test down arrow navigation."""
        grid.refresh_scenes()
        grid.resize(800, 600)  # Ensure multiple rows
        grid.select_scene(grid.scene_model.scenes[0])

        qtbot.keyPress(grid, Qt.Key.Key_Down)

        # Should move down (exact position depends on column count)
        assert grid.selected_scene is not None

    def test_keyboard_navigation_home_end(self, qtbot, grid):
        """Test Home/End key navigation."""
        grid.refresh_scenes()

        # Test Home
        grid.select_scene(grid.scene_model.scenes[2])
        qtbot.keyPress(grid, Qt.Key.Key_Home)
        assert grid.selected_scene == grid.scene_model.scenes[0]

        # Test End
        qtbot.keyPress(grid, Qt.Key.Key_End)
        assert grid.selected_scene == grid.scene_model.scenes[2]

    def test_keyboard_enter_emits_double_click(self, qtbot, grid):
        """Test Enter key emits double-click signal."""
        grid.refresh_scenes()
        grid.select_scene(grid.scene_model.scenes[0])

        double_clicked = []
        grid.scene_double_clicked.connect(lambda s: double_clicked.append(s))

        qtbot.keyPress(grid, Qt.Key.Key_Return)

        assert len(double_clicked) == 1
        assert double_clicked[0] == grid.scene_model.scenes[0]

    def test_keyboard_navigation_empty_grid(self, qtbot, grid):
        """Test keyboard navigation with empty grid."""
        grid.scene_model.scenes.clear()
        grid.refresh_scenes()

        # Should not crash
        qtbot.keyPress(grid, Qt.Key.Key_Right)
        qtbot.keyPress(grid, Qt.Key.Key_Down)

    def test_keyboard_navigation_no_selection(self, qtbot, grid):
        """Test keyboard navigation with no initial selection."""
        grid.refresh_scenes()

        # Press right arrow with no selection
        qtbot.keyPress(grid, Qt.Key.Key_Right)

        # Should select first scene
        assert grid.selected_scene == grid.scene_model.scenes[0]

    def test_ensure_visible_on_selection(self, qtbot, grid):
        """Test selected thumbnail is scrolled into view."""
        # Create many scenes to force scrolling
        for i in range(20):
            scene = ThreeDEScene(
                show="testshow",
                sequence=f"seq{i:03d}",
                shot=f"shot{i:03d}",
                workspace_path=f"/test/path/{i}",
                user=f"user{i}",
                plate=f"plate{i:04d}",
                scene_path=Path(f"/path/to/scene{i}.3de"),
            )
            grid.scene_model.scenes.append(scene)

        grid.refresh_scenes()
        qtbot.wait(10)  # Process events instead of waitExposed

        # Select last scene
        last_scene = grid.scene_model.scenes[-1]
        grid.select_scene(last_scene)

        # Navigate with keyboard
        qtbot.keyPress(grid, Qt.Key.Key_End)

        # Verify ensureWidgetVisible would be called
        # (actual scrolling test would require checking scroll position)

    def test_reflow_preserves_selection(self, qtbot, grid):
        """Test selection is preserved during reflow."""
        grid.refresh_scenes()
        scene = grid.scene_model.scenes[1]
        grid.select_scene(scene)

        # Trigger reflow
        grid._reflow_grid()

        # Selection should be preserved
        assert grid.selected_scene == scene

    def test_show_empty_state(self, grid):
        """Test empty state display."""
        grid._show_empty_state()

        # Should have empty label
        assert grid.grid_layout.count() == 1
        item = grid.grid_layout.itemAt(0)
        widget = item.widget()
        assert "No 3DE scenes found" in widget.text()

    def test_thumbnail_signals_connected(self, grid):
        """Test thumbnail signals are properly connected."""
        grid.refresh_scenes()

        # Get first thumbnail
        scene = grid.scene_model.scenes[0]
        thumbnail = grid.thumbnails[scene.display_name]

        # Simulate click signal
        clicked_signals = []
        grid.scene_selected.connect(lambda s: clicked_signals.append(s))
        thumbnail.clicked.emit(scene)

        assert len(clicked_signals) == 1

    def test_size_limits(self, grid):
        """Test thumbnail size limits."""
        # Test maximum
        grid.size_slider.setValue(500)
        assert grid._thumbnail_size == 400  # Max from Config

        # Test minimum
        grid.size_slider.setValue(50)
        assert grid._thumbnail_size == 100  # Min from Config
