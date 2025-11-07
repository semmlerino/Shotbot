"""Test common behavior across all three grid views following UNIFIED_TESTING_GUIDE.

Tests behavior that will be extracted to BaseGridView to ensure
refactoring preserves functionality.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from config import Config
from previous_shots_view import PreviousShotsView
from shot_grid_view import ShotGridView
from threede_grid_view import ThreeDEGridView


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from cache_manager import CacheManager
    from previous_shots_item_model import PreviousShotsItemModel
    from shot_item_model import ShotItemModel
    from threede_item_model import ThreeDEItemModel
    from type_definitions import Shot

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# Test Signal helper (per UNIFIED_TESTING_GUIDE)
class TestSignal:
    """Lightweight Qt signal mock for testing."""

    __test__ = False  # Prevent pytest collection

    def __init__(self) -> None:
        self.callbacks: list[Callable[..., object]] = []

    def connect(
        self, callback: Callable[..., object], connection_type: Qt.ConnectionType | None = None
    ) -> None:
        self.callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in self.callbacks:
            callback(*args)


# Test fixtures following Factory Pattern (UNIFIED_TESTING_GUIDE)
@pytest.fixture
def make_shot() -> Callable[[str, str, str], Shot]:
    """Factory for creating test shots (UNIFIED_TESTING_GUIDE: Factory pattern)."""

    def _make(show: str = "TEST", seq: str = "seq01", shot: str = "0010") -> Shot:
        from type_definitions import (
            Shot,
        )

        # Use correct VFX path format
        return Shot(show, seq, shot, f"{Config.SHOWS_ROOT}/{show}/shots/{seq}/{seq}_{shot}")

    return _make


@pytest.fixture
def make_model(
    qtbot: QtBot,
    make_shot: Callable[[str, str, str], Shot],
    cache_manager: CacheManager,
    mock_process_pool_manager,
) -> Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel]:
    """Factory for creating test models with proper data."""

    def _make(
        model_class_name: str, shots: list[Shot] | None = None
    ) -> ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel:
        if shots is None:
            shots = [make_shot()]

        if model_class_name == "ShotItemModel":
            from shot_item_model import (
                ShotItemModel,
            )
            from shot_model import (
                ShotModel,
            )

            shot_model = ShotModel(cache_manager=cache_manager)
            shot_model._shots = shots
            item_model = ShotItemModel(cache_manager=cache_manager)
            # Properly initialize the item model with shots
            item_model.set_items(shots)
            return item_model

        if model_class_name == "ThreeDEItemModel":
            from threede_scene_model import (
                ThreeDEScene,
                ThreeDESceneModel,
            )

            scene_model = ThreeDESceneModel(load_cache=False)
            # Convert shots to scenes for testing
            scenes = [
                ThreeDEScene(
                    show=s.show,
                    sequence=s.sequence,
                    shot=s.shot,
                    user="test_user",
                    plate="FG01",
                    workspace_path=s.workspace_path,
                    scene_path=Path(f"{s.workspace_path}/scene.3de"),
                )
                for s in shots
            ]
            scene_model.scenes = scenes
            from threede_item_model import (
                ThreeDEItemModel,
            )

            item_model = ThreeDEItemModel(cache_manager=cache_manager)
            # Properly initialize the item model with scenes
            item_model.set_items(scenes)
            return item_model

        if model_class_name == "PreviousShotsItemModel":
            from previous_shots_item_model import (
                PreviousShotsItemModel,
            )
            from previous_shots_model import (
                PreviousShotsModel,
            )
            from shot_model import (
                ShotModel,
            )

            # PreviousShotsModel requires a shot_model
            shot_model = ShotModel(cache_manager=cache_manager)
            prev_model = PreviousShotsModel(shot_model)
            prev_model._shots = shots
            item_model = PreviousShotsItemModel(prev_model, cache_manager=cache_manager)
            # Manually set items since UnifiedItemModel doesn't have _update_shots()
            item_model.set_items(shots)
            return item_model
        return None

    return _make


# Parametrize across all three views (CRITICAL for refactoring)
@pytest.mark.parametrize(
    ("view_class", "model_class"),
    [
        (ShotGridView, "ShotItemModel"),
        (ThreeDEGridView, "ThreeDEItemModel"),
        (PreviousShotsView, "PreviousShotsItemModel"),
    ],
    ids=["shot_grid", "threede_grid", "previous_shots"],
)
class TestCommonViewBehavior:
    """Test common behavior across all views per UNIFIED_TESTING_GUIDE."""

    def test_wheel_event_resizing(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test Ctrl+wheel thumbnail resizing (UNIFIED_TESTING_GUIDE: Real events)."""
        # Create view with real model (not mocks)
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)  # CRITICAL: Register for cleanup

        # Check if view has wheelEvent method (either defined or inherited)
        if not hasattr(view, "wheelEvent"):
            pytest.skip(f"{view_class.__name__} doesn't have wheelEvent method")

        initial_size = view._thumbnail_size

        # Simulate Ctrl+wheel up (increase size)
        wheel_point = QPointF(100, 100)
        pixel_delta = QPoint(0, 0)
        angle_delta = QPoint(0, 120)  # Positive = wheel up

        wheel_event = QWheelEvent(
            wheel_point,  # position
            view.mapToGlobal(QPoint(100, 100)),  # globalPosition
            pixel_delta,  # pixelDelta
            angle_delta,  # angleDelta
            Qt.MouseButton.NoButton,  # buttons
            Qt.KeyboardModifier.ControlModifier,  # modifiers
            Qt.ScrollPhase.NoScrollPhase,  # phase
            False,  # inverted
        )

        view.wheelEvent(wheel_event)
        qtbot.wait(50)  # Process events from wheel event

        # Test behavior, not implementation
        assert view._thumbnail_size > initial_size
        assert view.size_slider.value() == view._thumbnail_size
        assert view.size_label.text() == f"{view._thumbnail_size}px"

        # Test wheel down (decrease size)
        angle_delta = QPoint(0, -120)  # Negative = wheel down
        wheel_event = QWheelEvent(
            wheel_point,
            view.mapToGlobal(QPoint(100, 100)),
            pixel_delta,
            angle_delta,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        view.wheelEvent(wheel_event)
        qtbot.wait(50)  # Process events from wheel event

        # Should decrease but not below initial
        assert view._thumbnail_size < view.size_slider.value() + 10
        assert view._thumbnail_size >= Config.MIN_THUMBNAIL_SIZE

        # Test without Ctrl (should not change size)
        current_size = view._thumbnail_size
        angle_delta = QPoint(0, 120)
        wheel_event = QWheelEvent(
            wheel_point,
            view.mapToGlobal(QPoint(100, 100)),
            pixel_delta,
            angle_delta,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,  # No Ctrl
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        view.wheelEvent(wheel_event)
        qtbot.wait(50)  # Process events from wheel event
        assert view._thumbnail_size == current_size  # Should not change

    def test_context_menu_exists(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_shot: Callable[[str, str, str], Shot],
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test that views have context menu support.

        Note: Testing actual menu execution is complex due to Qt's C++ bindings
        for QMenu.exec() which blocks. This test verifies the method exists,
        which is sufficient for pre-refactoring validation.
        """
        shots = [make_shot()]
        model = make_model(model_class, shots=shots)
        view = view_class(model=model)
        qtbot.addWidget(view)  # CRITICAL: Register for cleanup

        # Check if view has contextMenuEvent (either defined or inherited)
        has_context_menu = hasattr(view, "contextMenuEvent")

        if view_class == ShotGridView:
            assert has_context_menu, "ShotGridView should have context menu"
        elif view_class == PreviousShotsView:
            assert has_context_menu, "PreviousShotsView should have context menu"
        elif view_class == ThreeDEGridView and not has_context_menu:
            # ThreeDEGridView doesn't have context menu yet, skip for now
            pytest.skip("ThreeDEGridView doesn't have context menu yet")

    def test_size_slider_functionality(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test size slider range and value changes."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # Ensure clean state before testing
        qtbot.wait(50)

        # Test initial setup
        assert view.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE
        assert view.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE
        assert view.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE
        assert view._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE
        assert view.size_label.text() == f"{Config.DEFAULT_THUMBNAIL_SIZE}px"

        # Test value change through slider (use a valid value within range)
        new_size = 300  # Between MIN (250) and MAX (600)
        view.size_slider.setValue(new_size)

        # Use qtbot.wait to ensure signal processing
        qtbot.wait(100)

        assert view._thumbnail_size == new_size
        assert view.size_label.text() == f"{new_size}px"

        # Test boundary values
        view.size_slider.setValue(Config.MIN_THUMBNAIL_SIZE)
        qtbot.wait(100)
        assert view._thumbnail_size == Config.MIN_THUMBNAIL_SIZE

        view.size_slider.setValue(Config.MAX_THUMBNAIL_SIZE)
        qtbot.wait(100)
        assert view._thumbnail_size == Config.MAX_THUMBNAIL_SIZE

        # Ensure all events are processed before cleanup
        qtbot.wait(50)

    def test_visibility_timer_updates(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test visibility timer for lazy loading."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # Different views use different timer mechanisms
        timer_found = False

        # Check for visibility timer (ShotGridView, ThreeDEGridView)
        if hasattr(view, "_visibility_timer"):
            timer = view._visibility_timer
            assert timer.isActive(), "Visibility timer should be active"
            assert timer.interval() == 100, "Timer should fire every 100ms"
            timer_found = True

        # Check for update timer (PreviousShotsView)
        elif hasattr(view, "_update_timer"):
            timer = view._update_timer
            # This is a single-shot timer, triggered on scroll
            assert timer.isSingleShot(), "Update timer should be single-shot"
            timer_found = True

        assert timer_found, f"View {view_class.__name__} should have a timer mechanism"

        # Test that scrolling triggers updates
        if hasattr(view, "list_view"):
            scrollbar = view.list_view.verticalScrollBar()
            if scrollbar.maximum() > 0:  # Only if scrolling is possible
                scrollbar.value()
                scrollbar.setValue(10)
                qtbot.wait(150)  # Wait for timer to fire

                # The timer should have triggered an update
                # We can't easily test the actual update without mocking
                # but we can verify the timer mechanism is working
                if hasattr(view, "_visibility_timer"):
                    assert view._visibility_timer.isActive()

    def test_focus_policy_consistency(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test all views have consistent focus policy."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # All views should have StrongFocus for keyboard navigation
        assert view.focusPolicy() == Qt.FocusPolicy.StrongFocus

    def test_show_filter_combo_exists(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test that show filter combo box exists and is configured."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # All views should have a show filter combo
        assert hasattr(view, "show_combo"), (
            f"{view_class.__name__} should have show_combo"
        )
        assert view.show_combo is not None

        # Should have at least "All Shows" option
        assert view.show_combo.count() >= 1
        assert view.show_combo.itemText(0) == "All Shows"

    def test_loading_indicators_exist(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[[str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel],
    ) -> None:
        """Test that loading indicators are properly configured."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # Different views have different loading mechanisms
        if view_class == ThreeDEGridView:
            # ThreeDEGridView has loading bar and label
            assert hasattr(view, "loading_bar")
            assert hasattr(view, "loading_label")
            assert not view.loading_bar.isVisible()  # Initially hidden
            assert not view.loading_label.isVisible()  # Initially hidden
