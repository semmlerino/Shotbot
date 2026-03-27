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
from PySide6.QtTest import QSignalSpy, QTest

# Local application imports
from config import Config
from tests.test_helpers import process_qt_events
from threede import ThreeDEGridView, ThreeDEItemModel, ThreeDESceneModel
from type_definitions import ThreeDEScene


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
    from unittest.mock import MagicMock

    model = ThreeDESceneModel(cache_manager=MagicMock())
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


class TestThreeDEGridViewFilters:
    """Test ThreeDE-specific filter widgets."""

    def test_artist_filter_combo_exists(self, threede_grid) -> None:
        """Test artist filter combo is created with the default option."""
        assert hasattr(threede_grid, "artist_combo")
        assert threede_grid.artist_combo.currentText() == "All Artists"
        assert threede_grid.artist_combo.count() == 1

    def test_populate_artist_filter_from_scene_model(
        self, threede_grid, scene_model
    ) -> None:
        """Test artist filter is populated from the scene model."""
        threede_grid.populate_artist_filter(scene_model)

        assert threede_grid.artist_combo.count() == 6
        assert threede_grid.artist_combo.itemText(0) == "All Artists"
        assert threede_grid.artist_combo.itemText(1) == "user0"
        assert threede_grid.artist_combo.itemText(5) == "user4"

    @pytest.mark.allow_dialogs
    def test_artist_filter_change_emits_signal(self, threede_grid, scene_model) -> None:
        """Test changing the artist filter emits the selected artist name."""
        threede_grid.populate_artist_filter(scene_model)

        signal_spy = QSignalSpy(threede_grid.artist_filter_requested)
        threede_grid.artist_combo.setCurrentText("user3")

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "user3"

    @pytest.mark.allow_dialogs
    def test_artist_filter_all_artists_emits_empty_string(
        self, threede_grid, scene_model
    ) -> None:
        """Test selecting 'All Artists' clears the artist filter."""
        threede_grid.populate_artist_filter(scene_model)
        threede_grid.artist_combo.setCurrentText("user2")

        signal_spy = QSignalSpy(threede_grid.artist_filter_requested)
        threede_grid.artist_combo.setCurrentText("All Artists")

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == ""


class TestThreeDEGridViewSizeControl:
    """Test thumbnail size control."""

    def test_size_slider_range(self, threede_grid) -> None:
        """Test size slider configuration."""
        assert threede_grid.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE
        assert threede_grid.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE
        assert threede_grid.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE

    def test_size_slider_exists(self, threede_grid) -> None:
        """Test size slider is properly connected."""
        # Change slider value (use valid value within MIN=400, MAX=1200 range)
        new_value = 500
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
        try:
            # Get first scene's index
            index = threede_grid._threede_model.index(0, 0)
            test_scene = sample_scenes[0]

            # Simulate double-click and wait for app_launch_requested signal
            with qtbot.waitSignal(threede_grid.app_launch_requested, timeout=1000):
                threede_grid._on_item_double_clicked(index)

            # Verify signal was emitted with BOTH parameters
            assert len(app_launch_signals) == 1
            app_name, scene = app_launch_signals[0]
            assert app_name == "3de"
            assert scene == test_scene
            assert scene.scene_path == test_scene.scene_path
        finally:
            try:
                threede_grid.app_launch_requested.disconnect(capture_launch)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted

    def test_context_menu_open_emits_app_launch_with_scene(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test context menu 'Open in 3DE' emits signal with scene context."""
        # Signal spy
        app_launch_signals = []

        def capture_launch(app_name: str, scene: ThreeDEScene) -> None:
            app_launch_signals.append((app_name, scene))

        threede_grid.app_launch_requested.connect(capture_launch)
        try:
            test_scene = sample_scenes[0]

            # Directly test the _open_scene_in_3de method and wait for signal
            with qtbot.waitSignal(threede_grid.app_launch_requested, timeout=1000):
                threede_grid._open_scene_in_3de(test_scene)

            # Verify signal emission
            assert len(app_launch_signals) == 1
            app_name, scene = app_launch_signals[0]
            assert app_name == "3de"
            assert scene == test_scene
        finally:
            try:
                threede_grid.app_launch_requested.disconnect(capture_launch)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted

    def test_app_launch_signal_includes_scene_metadata(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test that signal includes complete scene metadata."""
        received_scenes = []

        def capture_scene(app_name: str, scene: ThreeDEScene) -> None:
            received_scenes.append(scene)

        threede_grid.app_launch_requested.connect(capture_scene)
        try:
            test_scene = sample_scenes[0]
            index = threede_grid._threede_model.index(0, 0)

            # Trigger launch and wait for signal
            with qtbot.waitSignal(threede_grid.app_launch_requested, timeout=1000):
                threede_grid._on_item_double_clicked(index)

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
        finally:
            try:
                threede_grid.app_launch_requested.disconnect(capture_scene)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted

    def test_enter_key_press_emits_app_launch_with_scene(
        self, threede_grid, sample_scenes, qtbot
    ) -> None:
        """Test Enter key press launches 3DE with scene context."""
        app_launch_signals = []

        def capture_launch(app_name: str, scene: ThreeDEScene) -> None:
            app_launch_signals.append((app_name, scene))

        threede_grid.app_launch_requested.connect(capture_launch)
        try:
            # Select first scene
            index = threede_grid._threede_model.index(0, 0)
            threede_grid.list_view.setCurrentIndex(index)

            # Show widget and focus list_view (QAction requires visible widget)
            threede_grid.show()
            threede_grid.list_view.setFocus()
            process_qt_events()

            # Simulate Enter key press via QTest on list_view (QAction is scoped there)
            with qtbot.waitSignal(threede_grid.app_launch_requested, timeout=1000):
                QTest.keyPress(threede_grid.list_view, Qt.Key.Key_Return)

            # Verify signal was emitted
            assert len(app_launch_signals) == 1
            app_name, scene = app_launch_signals[0]
            assert app_name == "3de"
            assert scene == sample_scenes[0]
        finally:
            try:
                threede_grid.app_launch_requested.disconnect(capture_launch)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted

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
        try:
            # Double-click first scene and wait for signals
            index = threede_grid._threede_model.index(0, 0)
            with qtbot.waitSignal(threede_grid.app_launch_requested, timeout=1000):
                threede_grid._on_item_double_clicked(index)

            # Verify both signals were emitted
            assert len(double_clicked_scenes) == 1
            assert len(app_launch_signals) == 1
            assert double_clicked_scenes[0] == sample_scenes[0]
            assert app_launch_signals[0][1] == sample_scenes[0]
        finally:
            try:
                threede_grid.scene_double_clicked.disconnect(capture_double_click)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted
            try:
                threede_grid.app_launch_requested.disconnect(capture_launch)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted
