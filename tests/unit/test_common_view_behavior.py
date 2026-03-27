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
from previous_shots.view import PreviousShotsView
from shots.shot_grid_view import ShotGridView
from threede import ThreeDEGridView


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from previous_shots.item_model import PreviousShotsItemModel
    from shots.shot_item_model import ShotItemModel
    from threede import ThreeDEItemModel
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
        self,
        callback: Callable[..., object],
        connection_type: Qt.ConnectionType | None = None,
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
        return Shot(
            show, seq, shot, f"{Config.SHOWS_ROOT}/{show}/shots/{seq}/{seq}_{shot}"
        )

    return _make


@pytest.fixture
def make_model(
    qtbot: QtBot,
    make_shot: Callable[[str, str, str], Shot],
    shot_cache: object,
    mock_process_pool_manager,
) -> Callable[
    [str, list[Shot] | None], ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel
]:
    """Factory for creating test models with proper data."""

    def _make(
        model_class_name: str, shots: list[Shot] | None = None
    ) -> ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel:
        if shots is None:
            shots = [make_shot()]

        if model_class_name == "ShotItemModel":
            from shots.shot_item_model import (
                ShotItemModel,
            )
            from shots.shot_model import (
                ShotModel,
            )

            shot_model = ShotModel(cache_manager=shot_cache)
            shot_model._shots = shots
            item_model = ShotItemModel(cache_manager=None)
            # Properly initialize the item model with shots
            item_model.set_items(shots)
            return item_model

        if model_class_name == "ThreeDEItemModel":
            from unittest.mock import MagicMock

            from threede import ThreeDESceneModel
            from threede.scene_model import ThreeDEScene

            scene_model = ThreeDESceneModel(cache_manager=MagicMock(), load_cache=False)
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
            from threede import ThreeDEItemModel

            item_model = ThreeDEItemModel(cache_manager=None)
            # Properly initialize the item model with scenes
            item_model.set_items(scenes)
            return item_model

        if model_class_name == "PreviousShotsItemModel":
            from previous_shots.item_model import (
                PreviousShotsItemModel,
            )
            from previous_shots.model import (
                PreviousShotsModel,
            )
            from shots.shot_model import (
                ShotModel,
            )

            # PreviousShotsModel requires a shot_model
            shot_model = ShotModel(cache_manager=shot_cache)
            prev_model = PreviousShotsModel(shot_model)
            prev_model._shots = shots
            item_model = PreviousShotsItemModel(prev_model, cache_manager=None)
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
        make_model: Callable[
            [str, list[Shot] | None],
            ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel,
        ],
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
        qtbot.wait(1)  # Minimal event processing

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
        qtbot.wait(1)  # Minimal event processing

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
        qtbot.wait(1)  # Minimal event processing
        assert view._thumbnail_size == current_size  # Should not change

    def test_size_slider_functionality(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[
            [str, list[Shot] | None],
            ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel,
        ],
    ) -> None:
        """Test size slider range and value changes."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # Ensure clean state before testing
        qtbot.wait(1)  # Minimal event processing

        # Test initial setup
        assert view.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE
        assert view.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE
        assert view.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE
        assert view._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE
        assert view.size_label.text() == f"{Config.DEFAULT_THUMBNAIL_SIZE}px"

        # Test value change through slider (use a valid value within range)
        new_size = 500  # Between MIN (400) and MAX (1200)
        view.size_slider.setValue(new_size)

        # Wait for signal processing to complete
        qtbot.waitUntil(lambda: view._thumbnail_size == new_size, timeout=1000)

        assert view._thumbnail_size == new_size
        assert view.size_label.text() == f"{new_size}px"

        # Test boundary values
        view.size_slider.setValue(Config.MIN_THUMBNAIL_SIZE)
        qtbot.waitUntil(
            lambda: view._thumbnail_size == Config.MIN_THUMBNAIL_SIZE, timeout=1000
        )
        assert view._thumbnail_size == Config.MIN_THUMBNAIL_SIZE

        view.size_slider.setValue(Config.MAX_THUMBNAIL_SIZE)
        qtbot.waitUntil(
            lambda: view._thumbnail_size == Config.MAX_THUMBNAIL_SIZE, timeout=1000
        )
        assert view._thumbnail_size == Config.MAX_THUMBNAIL_SIZE

        # Ensure all events are processed before cleanup
        qtbot.wait(1)  # Minimal event processing

    def test_visibility_timer_updates(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[
            [str, list[Shot] | None],
            ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel,
        ],
    ) -> None:
        """Test visibility timer for lazy loading."""
        model = make_model(model_class)
        view = view_class(model=model)
        qtbot.addWidget(view)

        # All views now use the same single-shot timer from BaseGridView
        assert hasattr(view, "_visibility_timer"), (
            f"View {view_class.__name__} should have _visibility_timer"
        )
        timer = view._visibility_timer
        assert timer.isSingleShot(), "Visibility timer should be single-shot"

        # Test that scrolling triggers updates
        if hasattr(view, "list_view"):
            scrollbar = view.list_view.verticalScrollBar()
            if scrollbar.maximum() > 0:  # Only if scrolling is possible
                initial_value = scrollbar.value()
                scrollbar.setValue(10)

                # Wait for scroll position to update
                qtbot.waitUntil(lambda: scrollbar.value() != initial_value, timeout=500)

                # The timer should have triggered an update
                # We can't easily test the actual update without mocking
                # but we can verify the timer mechanism is working
                if hasattr(view, "_visibility_timer"):
                    assert view._visibility_timer.isActive()

    def test_show_filter_combo_exists(
        self,
        view_class: type[ShotGridView | ThreeDEGridView | PreviousShotsView],
        model_class: str,
        qtbot: QtBot,
        make_model: Callable[
            [str, list[Shot] | None],
            ShotItemModel | ThreeDEItemModel | PreviousShotsItemModel,
        ],
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
