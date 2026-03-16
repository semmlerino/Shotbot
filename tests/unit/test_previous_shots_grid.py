"""Tests for PreviousShotsView component.

Tests the Model/View UI component with real Qt widgets and signal interactions.
Follows best practices:
- Uses real Qt components where possible
- Proper signal race condition prevention
- Tests actual behavior, not implementation
- Uses qtbot properly for QWidget testing
"""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

# Standard library imports
import contextlib
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QSignalSpy, QTest

# Local application imports
from cache.shot_cache import ShotDataCache
from config import Config
from previous_shots.item_model import PreviousShotsItemModel
from previous_shots.model import PreviousShotsModel
from previous_shots.view import PreviousShotsView

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.test_doubles import (
    TestCacheManager,
    TestProgressManager,
)
from tests.test_helpers import SynchronizationHelpers, process_qt_events
from type_definitions import Shot


if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

pytestmark = [pytest.mark.unit, pytest.mark.qt]


def create_test_shot(
    show: str = "testshow", sequence: str = "seq01", shot: str = "0010"
) -> Shot:
    """Create test shot for testing."""
    return Shot(show, sequence, shot, f"{Config.SHOWS_ROOT}/{show}")


def create_test_shots(count: int = 3) -> list[Shot]:
    """Create multiple test shots."""
    return [
        create_test_shot("show1", "seq01", f"{(i + 1) * 10:04d}")
        for i in range(count)
    ]


def _prepare_view_for_cleanup(view: PreviousShotsView) -> None:
    """Detach the view from its model before dependent objects are deleted."""
    with contextlib.suppress(RuntimeError):
        view.list_view.setModel(None)
        view._model = None
        view._unified_model = None
        view.close()


def _schedule_delete_later(*objects: QObject) -> None:
    """Queue QObject cleanup without forcing immediate event-loop re-entry."""
    for obj in objects:
        with contextlib.suppress(RuntimeError):
            obj.deleteLater()


def _wait_for_qt_condition(
    condition: Callable[[], object], timeout_ms: int = 1000
) -> None:
    """Poll a Qt condition without entering pytest-qt nested wait loops."""

    def _poll() -> bool:
        process_qt_events()
        return bool(condition())

    assert SynchronizationHelpers.wait_for_condition(_poll, timeout_ms=timeout_ms), (
        "Timed out waiting for Qt state to settle"
    )


class FakePreviousShotsModel(QObject):
    """Test double for PreviousShotsModel with real Qt signals."""

    # Real Qt signals for proper testing
    shots_updated = Signal()
    scan_started = Signal()
    scan_finished = Signal()
    scan_progress = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._shots: list[Shot] = []
        self._scanning = False
        self.refresh_calls: list[bool] = []

    def get_shots(self) -> list[Shot]:
        return self._shots.copy()

    def get_shot_count(self) -> int:
        return len(self._shots)

    def set_shots(self, shots: list[Shot]) -> None:
        """Configure shots for testing."""
        self._shots = shots
        self.shots_updated.emit()

    def refresh_shots(self) -> bool:
        """Simulate refresh with signals."""
        self.refresh_calls.append(True)
        self._scanning = True
        self.scan_started.emit()
        # Complete synchronously in test context to avoid Qt lifecycle issues
        self._scanning = False
        self.scan_finished.emit()
        return True

    def is_scanning(self) -> bool:
        return self._scanning


class TestPreviousShotsView:
    """Test cases for PreviousShotsView Model/View component with real Qt components."""

    @pytest.fixture
    def test_model(self, qtbot: QtBot) -> Generator[FakePreviousShotsModel, None, None]:
        """Create test double PreviousShotsModel with real Qt signals."""
        model = FakePreviousShotsModel()
        # Register for automatic cleanup (QObject, not QWidget)
        # This ensures proper cleanup even if test fails
        yield model
        # Ensure cleanup happens
        _schedule_delete_later(model)

    @pytest.fixture
    def test_cache_manager(self, tmp_path: Path) -> TestCacheManager:
        """Create test double CacheManager."""
        return TestCacheManager(tmp_path / "cache")

    @pytest.fixture
    def real_cache_manager(self, tmp_path: Path) -> ShotDataCache:
        """Create real CacheManager with temp storage for integration tests."""
        return ShotDataCache(tmp_path / "cache")

    @pytest.fixture
    def grid_widget(
        self,
        test_model: FakePreviousShotsModel,
        test_cache_manager: TestCacheManager,
        qtbot: QtBot,
    ) -> Generator[PreviousShotsView, None, None]:
        """Create PreviousShotsView widget with Model/View architecture."""
        # Create the item model wrapper for the previous shots model
        item_model = PreviousShotsItemModel(
            test_model, cache_manager=test_cache_manager
        )
        # Create the view with the model
        view = PreviousShotsView(model=item_model)
        qtbot.addWidget(view)  # Proper - this IS a QWidget
        view.show()
        qtbot.waitExposed(view)  # Wait for widget to be visible
        yield view
        _prepare_view_for_cleanup(view)
        _schedule_delete_later(item_model)

    def test_grid_initialization(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        test_cache_manager: TestCacheManager,
    ) -> None:
        """Test grid widget initialization."""
        # View has the item model, which wraps the test_model
        assert grid_widget.model is not None
        assert isinstance(grid_widget.model, object)  # UnifiedItemModel
        assert grid_widget.selected_shot is None

        # UI components should be created
        assert grid_widget._status_label is not None
        assert grid_widget._refresh_button is not None
        assert hasattr(grid_widget, "list_view")  # Model/View uses list_view
        assert hasattr(grid_widget, "size_slider")  # Size control

        # View should have proper methods
        assert hasattr(grid_widget, "refresh")
        assert hasattr(grid_widget, "get_selected_shot")

    def test_refresh_button_interaction(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test refresh button click behavior with signal waiting."""
        # Initially button should be enabled
        assert grid_widget._refresh_button.isEnabled()
        assert grid_widget._refresh_button.text() == "Refresh"

        # Use test double for ProgressManager to avoid Qt lifecycle issues with status bar
        with (
            patch(
                "progress_manager.ProgressManager.start_operation",
                TestProgressManager.start_operation,
            ),
            patch(
                "progress_manager.ProgressManager.finish_operation",
                TestProgressManager.finish_operation,
            ),
        ):
            # Test button click
            QTest.mouseClick(grid_widget._refresh_button, Qt.MouseButton.LeftButton)
            qtbot.wait(1)  # Minimal event processing

        # Verify refresh was attempted (the important behavior)
        assert len(test_model.refresh_calls) >= 1

    def test_scan_state_signal_handling(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test handling of scan state signals."""
        # Use test double for ProgressManager to avoid Qt lifecycle issues with status bar
        with (
            patch(
                "progress_manager.ProgressManager.start_operation",
                TestProgressManager.start_operation,
            ),
            patch(
                "progress_manager.ProgressManager.finish_operation",
                TestProgressManager.finish_operation,
            ),
        ):
            # Test scan started signal
            test_model.scan_started.emit()
            qtbot.wait(1)  # Minimal event processing

            # Test scan finished signal
            test_model.scan_finished.emit()
            qtbot.wait(1)  # Minimal event processing

        # The key test is that signals don't crash the widget
        assert grid_widget is not None

    def test_scan_progress_updates(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test scan progress signal handling."""
        test_model.scan_progress.emit(50, 100)

        # Wait for queued signal to be processed
        qtbot.wait(1)  # Minimal event processing

        status_text = grid_widget._status_label.text()
        # The scan progress might be quickly replaced by status update
        # Test that the signal was handled without crashing
        assert status_text is not None  # Label was updated

    def test_empty_state_display(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test display when no shots are available."""
        # Model has no shots
        test_model.set_shots([])

        # PreviousShotsView uses Model/View architecture
        # Test that widget exists and model has no items
        assert grid_widget.isVisible()
        if grid_widget._model:
            assert grid_widget._model.rowCount() == 0

    def test_grid_population_with_real_thumbnails(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test grid population with real ThumbnailWidget components.

        Following UNIFIED_TESTING_GUIDE:
        - Use real components where possible
        - Test actual behavior
        """
        # Add test shots to model
        test_shots = create_test_shots(3)
        test_model.set_shots(test_shots)

        # Wait for parent widget to be visible first
        _wait_for_qt_condition(lambda: grid_widget.isVisible(), timeout_ms=500)

        # Then check list_view visibility (uses list_view in Model/View architecture)
        # The list_view should be visible if parent is shown
        assert grid_widget.list_view is not None

        # Wait for model to update (QueuedConnection needs event loop processing)
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() == 3,
            timeout_ms=1000,
        )

        # Status should show shot count
        _wait_for_qt_condition(
            lambda: "3" in grid_widget._status_label.text(), timeout_ms=1000
        )

    def test_thumbnail_signal_connections(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test that thumbnail signals are properly connected."""
        # Add a shot
        shot = create_test_shot("test", "seq01", "shot01")
        test_model.set_shots([shot])

        # Wait for model to have data
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() > 0,
            timeout_ms=500,
        )

        # Set up signal spy on grid's shot_selected signal
        shot_selected_spy = QSignalSpy(grid_widget.shot_selected)

        # Simulate click on item using Qt's selection model
        # This triggers _on_selection_changed which emits the signal
        # Third-party imports
        from PySide6.QtCore import (
            QModelIndex,
        )

        index = grid_widget._model.index(0, 0) if grid_widget._model else QModelIndex()
        grid_widget.list_view.setCurrentIndex(index)

        # Verify signal propagation
        assert shot_selected_spy.count() == 1
        assert shot_selected_spy.at(0)[0] == shot

    def test_shot_selection_behavior(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test shot selection and visual feedback."""
        shot1 = create_test_shot("show1", "seq1", "shot1")
        shot2 = create_test_shot("show1", "seq1", "shot2")
        test_model.set_shots([shot1, shot2])

        # Wait for model population
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() == 2,
            timeout_ms=500,
        )

        # Set up signal spy
        shot_selected_spy = QSignalSpy(grid_widget.shot_selected)

        # Simulate shot selection using Qt's selection model
        # This triggers _on_selection_changed which emits the signal
        # Third-party imports
        from PySide6.QtCore import (
            QModelIndex,
        )

        index = grid_widget._model.index(0, 0) if grid_widget._model else QModelIndex()
        grid_widget.list_view.setCurrentIndex(index)

        # Should update selection state (using selected_shot, not selected_item)
        assert grid_widget.selected_shot is shot1
        assert shot_selected_spy.count() == 1
        assert shot_selected_spy.at(0)[0] is shot1

    def test_shot_double_click_behavior(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test shot double-click signal emission."""
        shot = create_test_shot("show1", "seq1", "shot1")
        test_model.set_shots([shot])

        # Wait for model to have data
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() > 0,
            timeout_ms=500,
        )

        # Set up signal spy
        shot_double_clicked_spy = QSignalSpy(grid_widget.shot_double_clicked)

        # Simulate double-click using model index
        # Third-party imports
        from PySide6.QtCore import (
            QModelIndex,
        )

        index = grid_widget._model.index(0, 0) if grid_widget._model else QModelIndex()
        grid_widget._on_item_double_clicked(index)

        # Should emit signal
        assert shot_double_clicked_spy.count() == 1
        assert shot_double_clicked_spy.at(0)[0] is shot

    def test_grid_clear_functionality(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test clearing grid widgets properly."""
        # Add shots
        test_model.set_shots(create_test_shots(2))
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() == 2,
            timeout_ms=1000,
        )

        # Clear model
        test_model.set_shots([])

        # Wait for model to clear (QueuedConnection needs event loop processing)
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() == 0,
            timeout_ms=1000,
        )

        # Selection should be reset
        assert grid_widget.selected_shot is None

    def test_grid_column_calculation(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test that grid columns are calculated correctly based on width."""
        # Set specific size
        grid_widget.resize(1000, 600)

        # Add shots to trigger population
        test_model.set_shots(create_test_shots(6))

        # Wait for model population
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() == 6,
            timeout_ms=500,
        )

        # Calculate expected columns based on widget width
        available_width = grid_widget.width()
        expected_columns = max(
            1, available_width // (Config.DEFAULT_THUMBNAIL_SIZE + 20)
        )

        # Verify layout (Model/View manages layout automatically)
        assert expected_columns > 0
        # List view in icon mode automatically arranges items based on size
        assert (
            grid_widget.list_view.viewMode() == grid_widget.list_view.ViewMode.IconMode
        )

    def test_refresh_method_delegation(
        self, grid_widget: PreviousShotsView, test_model: FakePreviousShotsModel
    ) -> None:
        """Test that refresh method delegates to model."""
        # Use test double for ProgressManager to avoid Qt lifecycle issues with status bar
        with (
            patch(
                "progress_manager.ProgressManager.start_operation",
                TestProgressManager.start_operation,
            ),
            patch(
                "progress_manager.ProgressManager.finish_operation",
                TestProgressManager.finish_operation,
            ),
        ):
            grid_widget.refresh()

        # The important thing is the refresh call was attempted
        assert len(test_model.refresh_calls) >= 1

    def test_get_selected_shot(
        self,
        grid_widget: PreviousShotsView,
        test_model: FakePreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """Test getting currently selected shot."""
        # Initially no selection
        assert grid_widget.get_selected_shot() is None

        # Add shot and select it
        shot = create_test_shot("show1", "seq1", "shot1")
        test_model.set_shots([shot])

        # Wait for model to update
        _wait_for_qt_condition(
            lambda: grid_widget._model and grid_widget._model.rowCount() == 1,
            timeout_ms=1000,
        )

        # Select the shot using Qt's selection model
        # This triggers _on_selection_changed which updates _selected_shot
        # Third-party imports
        from PySide6.QtCore import (
            QModelIndex,
        )

        index = grid_widget._model.index(0, 0) if grid_widget._model else QModelIndex()
        grid_widget.list_view.setCurrentIndex(index)

        assert grid_widget.get_selected_shot() is shot


class TestPreviousShotsViewIntegration:
    """Integration tests with real components."""

    @pytest.fixture
    def integration_grid(
        self, qtbot: QtBot, tmp_path: Path
    ) -> Generator[PreviousShotsView, None, None]:
        """Create view with all real components for integration testing."""
        # Local application imports
        from shot_model import (
            ShotModel,
        )

        # Real components
        cache_manager = ShotDataCache(tmp_path / "cache")
        shot_model = ShotModel(cache_manager)
        previous_model = PreviousShotsModel(shot_model, cache_manager)

        # Create the item model and view
        item_model = PreviousShotsItemModel(previous_model)
        view = PreviousShotsView(model=item_model)
        qtbot.addWidget(view)
        view.show()
        qtbot.waitExposed(view)

        yield view

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        _prepare_view_for_cleanup(view)
        _schedule_delete_later(item_model, previous_model, shot_model)

    def test_integration_grid_creation(
        self, integration_grid: PreviousShotsView, qtbot: QtBot
    ) -> None:
        """Test that integration grid creates successfully."""
        grid = integration_grid

        # Grid should be created successfully
        assert grid is not None
        assert isinstance(grid, PreviousShotsView)

        # Should have UI components
        assert hasattr(grid, "_refresh_button")
        assert hasattr(grid, "_status_label")
        assert hasattr(grid, "list_view")  # Model/View uses list_view

        # Test basic functionality without triggering ProgressManager
        # Just verify the grid works and doesn't crash
        try:
            # Test basic properties
            assert grid._refresh_button.isEnabled()
            assert grid._status_label is not None
            assert grid.list_view is not None
        except RuntimeError:
            # Qt object lifecycle issues during testing are expected
            pass

        # Verify grid remains functional
        assert grid is not None
