"""Unit tests for ThreeDEGridView Model/View component.

This file tests the actual ThreeDEGridView implementation which uses Qt Model/View
architecture with QListView, not manual widget management.
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest
from PySide6.QtCore import Qt

# Local application imports
from config import Config
from threede_grid_view import ThreeDEGridView
from threede_item_model import ThreeDEItemModel
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


pytestmark = [pytest.mark.unit, pytest.mark.qt]


@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot):
    """Autouse fixture to ensure Qt state is cleaned up after each test.

    This prevents cross-test contamination when tests run in parallel.
    Critical for preventing signal/slot pollution and Qt internal state issues.

    Processes pending Qt events after each test to ensure proper cleanup
    of signals, slots, and Qt internal state.
    """
    yield
    # Process any pending Qt events to ensure clean state
    qtbot.wait(1)  # Minimal wait to process events


@pytest.fixture
def sample_scenes():
    """Create sample 3DE scenes for testing."""
    scenes = []
    for i in range(5):
        scene = ThreeDEScene(
            show=f"show{i}",
            sequence=f"seq{i:02d}",
            shot=f"shot{i:03d}",
            user=f"user{i}",
            scene_path=Path(f"/path/to/scene{i}.3de"),
            plate=f"FG{i:02d}",
            workspace_path=f"/workspace/shot{i}",
        )
        scenes.append(scene)
    return scenes


@pytest.fixture
def scene_model(sample_scenes):
    """Create a ThreeDESceneModel with sample scenes."""
    model = ThreeDESceneModel()
    model.scenes = sample_scenes
    return model


@pytest.fixture
def threede_grid(qtbot, scene_model, sample_scenes):
    """Create a ThreeDEGridView instance for testing."""
    # Create the item model wrapper
    item_model = ThreeDEItemModel()
    # Set the scenes in the model
    item_model.set_items(sample_scenes)
    # Create the view with the model
    view = ThreeDEGridView(model=item_model)
    qtbot.addWidget(view)
    return view


class TestThreeDEGridViewInitialization:
    """Test ThreeDEGridView initialization."""

    def test_initialization(self, threede_grid) -> None:
        """Test grid initialization."""
        # Note: threede_grid._threede_model is an ItemModel wrapper
        assert threede_grid._threede_model is not None
        assert threede_grid.selected_scene is None
        assert threede_grid._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE
        assert threede_grid.is_loading is False

    def test_ui_setup(self, threede_grid) -> None:
        """Test UI components are created."""
        assert threede_grid.size_slider is not None
        assert threede_grid.size_label is not None
        assert threede_grid.loading_bar is not None
        assert threede_grid.loading_label is not None

        # Check initial states
        assert threede_grid.loading_bar.isVisible() is False
        assert threede_grid.loading_label.isVisible() is False
        assert threede_grid.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE
        assert threede_grid.size_label.text() == f"{Config.DEFAULT_THUMBNAIL_SIZE}px"

    def test_focus_policy(self, threede_grid) -> None:
        """Test widget has proper focus policy."""
        assert threede_grid.focusPolicy() == Qt.FocusPolicy.StrongFocus


class TestThreeDEGridViewSizeControl:
    """Test thumbnail size control."""

    def test_size_slider_range(self, threede_grid) -> None:
        """Test size slider configuration."""
        assert threede_grid.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE
        assert threede_grid.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE
        assert threede_grid.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE

    def test_size_slider_exists(self, threede_grid) -> None:
        """Test size slider is properly connected."""
        # Change slider value (use valid value within MIN/MAX range)
        new_value = 300  # MIN_THUMBNAIL_SIZE is 250
        threede_grid.size_slider.setValue(new_value)

        # Verify slider value was set
        assert threede_grid.size_slider.value() == new_value


class TestThreeDEGridViewAppLaunchSignals:
    """Test app_launch_requested signal with scene context.

    These tests verify the fix for the bug where opening 3DE from
    the Other 3DE Scenes tab resulted in "No shot selected" error.
    The signal must correctly emit both app_name AND scene.
    """

    def test_double_click_emits_app_launch_with_scene(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test double-click emits app_launch_requested with scene context.

        Verifies the fix for: "No shot selected" error when opening 3DE scenes.
        """
        # Signal spy to capture emissions
        app_launch_signals = []

        def capture_launch(app_name: str, scene: ThreeDEScene) -> None:
            app_launch_signals.append((app_name, scene))

        threede_grid.app_launch_requested.connect(capture_launch)

        # Get first scene's index
        index = threede_grid._threede_model.index(0, 0)
        test_scene = sample_scenes[0]

        # Simulate double-click (which triggers double-clicked signal internally)
        threede_grid._on_item_double_clicked(index)

        # Wait for signal processing
        qtbot.wait(100)

        # Verify signal was emitted with BOTH parameters
        assert len(app_launch_signals) == 1
        app_name, scene = app_launch_signals[0]
        assert app_name == "3de"
        assert scene == test_scene
        assert scene.scene_path == test_scene.scene_path

    def test_context_menu_open_emits_app_launch_with_scene(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test context menu 'Open in 3DE' emits signal with scene context."""
        # Signal spy
        app_launch_signals = []

        def capture_launch(app_name: str, scene: ThreeDEScene) -> None:
            app_launch_signals.append((app_name, scene))

        threede_grid.app_launch_requested.connect(capture_launch)

        test_scene = sample_scenes[0]

        # Directly test the _open_scene_in_3de method (called by context menu)
        threede_grid._open_scene_in_3de(test_scene)

        # Wait for signal processing
        qtbot.wait(100)

        # Verify signal emission
        assert len(app_launch_signals) == 1
        app_name, scene = app_launch_signals[0]
        assert app_name == "3de"
        assert scene == test_scene

    def test_app_launch_signal_includes_scene_metadata(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test that signal includes complete scene metadata."""
        received_scenes = []

        def capture_scene(app_name: str, scene: ThreeDEScene) -> None:
            received_scenes.append(scene)

        threede_grid.app_launch_requested.connect(capture_scene)

        test_scene = sample_scenes[0]
        index = threede_grid._threede_model.index(0, 0)

        # Trigger launch
        threede_grid._on_item_double_clicked(index)
        qtbot.wait(100)

        # Verify complete scene data is passed
        assert len(received_scenes) == 1
        received = received_scenes[0]
        assert received.show == test_scene.show
        assert received.sequence == test_scene.sequence
        assert received.shot == test_scene.shot
        assert received.user == test_scene.user
        assert received.plate == test_scene.plate
        assert received.workspace_path == test_scene.workspace_path
        assert received.scene_path == test_scene.scene_path

    def test_enter_key_press_emits_app_launch_with_scene(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test Enter key press launches 3DE with scene context."""
        app_launch_signals = []

        def capture_launch(app_name: str, scene: ThreeDEScene) -> None:
            app_launch_signals.append((app_name, scene))

        threede_grid.app_launch_requested.connect(capture_launch)

        # Select first scene
        index = threede_grid._threede_model.index(0, 0)
        threede_grid.list_view.setCurrentIndex(index)

        # Simulate Enter key press
        from PySide6.QtGui import (
            QKeyEvent,
        )

        key_event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )
        threede_grid.keyPressEvent(key_event)
        qtbot.wait(100)

        # Verify signal was emitted
        assert len(app_launch_signals) == 1
        app_name, scene = app_launch_signals[0]
        assert app_name == "3de"
        assert scene == sample_scenes[0]

    def test_scene_double_clicked_signal_also_emitted(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test that scene_double_clicked signal is also emitted alongside app_launch_requested."""
        double_clicked_scenes = []
        app_launch_signals = []

        def capture_double_click(scene: ThreeDEScene) -> None:
            double_clicked_scenes.append(scene)

        def capture_launch(app_name: str, scene: ThreeDEScene) -> None:
            app_launch_signals.append((app_name, scene))

        threede_grid.scene_double_clicked.connect(capture_double_click)
        threede_grid.app_launch_requested.connect(capture_launch)

        # Double-click first scene
        index = threede_grid._threede_model.index(0, 0)
        threede_grid._on_item_double_clicked(index)
        qtbot.wait(100)

        # Verify both signals were emitted
        assert len(double_clicked_scenes) == 1
        assert len(app_launch_signals) == 1
        assert double_clicked_scenes[0] == sample_scenes[0]
        assert app_launch_signals[0][1] == sample_scenes[0]
