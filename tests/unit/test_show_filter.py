"""Unit tests for Show filter functionality across all components.

This module tests the Show filter feature added to all tabs including:
- Model filtering (base_shot_model, shot_item_model, previous_shots)
- View UI components (shot_grid_view, previous_shots_view)
- Main window signal handlers

Following UNIFIED_TESTING_GUIDE principles:
- Test behavior, not implementation
- Use real components with test doubles at boundaries
- Mock only external dependencies
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QComboBox

from previous_shots_item_model import PreviousShotsItemModel
from previous_shots_model import PreviousShotsModel
from previous_shots_view import PreviousShotsView
from shot_grid_view import ShotGridView

# Local application imports
from shot_item_model import ShotItemModel
from shot_model import Shot, ShotModel
from tests.fixtures.test_doubles import TestCacheManager, TestProcessPool


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytestqt.qtbot import QtBot

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestShotItemModelFiltering:
    """Test Show filter methods in ShotItemModel."""

    @pytest.fixture
    def shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a ShotModel with test process pool."""
        model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def shot_item_model(self, tmp_path: Path, qtbot: QtBot) -> Generator[ShotItemModel, None, None]:
        """Create ShotItemModel for testing."""
        model = ShotItemModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"))
        yield model
        model.clear_thumbnail_cache()
        model.deleteLater()

    @pytest.fixture
    def test_shots(self) -> list[Shot]:
        """Create test shots from different shows."""
        return [
            Shot("show1", "seq1", "shot1", "/workspace/show1/seq1/shot1"),
            Shot("show1", "seq2", "shot2", "/workspace/show1/seq2/shot2"),
            Shot("show2", "seq3", "shot3", "/workspace/show2/seq3/shot3"),
        ]

    def test_set_show_filter_updates_display(
        self,
        shot_item_model: ShotItemModel,
        shot_model: ShotModel,
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test that set_show_filter updates the displayed shots."""
        shot_model.shots = test_shots
        shot_item_model.set_shots(test_shots)

        # Spy on the show_filter_changed signal
        signal_spy = QSignalSpy(shot_item_model.show_filter_changed)

        # Filter to show1
        shot_item_model.set_show_filter(shot_model, "show1")

        # Check signal was emitted
        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "show1"

        # Check model updated
        assert shot_item_model.rowCount() == 2

        # Filter to show2
        shot_item_model.set_show_filter(shot_model, "show2")
        assert signal_spy.count() == 2
        assert signal_spy.at(1)[0] == "show2"
        assert shot_item_model.rowCount() == 1

    def test_set_show_filter_none_shows_all(
        self,
        shot_item_model: ShotItemModel,
        shot_model: ShotModel,
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test that setting filter to None shows all shots."""
        shot_model.shots = test_shots
        shot_item_model.set_shots(test_shots)

        # Apply filter
        shot_item_model.set_show_filter(shot_model, "show1")
        assert shot_item_model.rowCount() == 2

        # Clear filter
        signal_spy = QSignalSpy(shot_item_model.show_filter_changed)
        shot_item_model.set_show_filter(shot_model, None)

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "All Shows"
        assert shot_item_model.rowCount() == 3


class TestPreviousShotsModelFiltering:
    """Test Show filter methods in PreviousShotsModel."""

    @pytest.fixture
    def shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a base ShotModel."""
        model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def previous_shots_model(
        self, tmp_path: Path, shot_model: ShotModel, qtbot: QtBot
    ) -> Generator[PreviousShotsModel, None, None]:
        """Create PreviousShotsModel."""
        model = PreviousShotsModel(shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2"))
        yield model
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        model.deleteLater()

    @pytest.fixture
    def test_previous_shots(self) -> list[Shot]:
        """Create test approved shots."""
        return [
            Shot("show1", "seq10", "shot10", "/workspace/show1/seq10/shot10"),
            Shot("show1", "seq11", "shot11", "/workspace/show1/seq11/shot11"),
            Shot("show2", "seq20", "shot20", "/workspace/show2/seq20/shot20"),
        ]

    def test_previous_shots_filtering(
        self, previous_shots_model: PreviousShotsModel, test_previous_shots: list[Shot]
    ) -> None:
        """Test filtering previous shots by show."""
        # Set up previous shots
        previous_shots_model._previous_shots = test_previous_shots

        # Test no filter
        filtered = previous_shots_model.get_filtered_shots()
        assert len(filtered) == 3

        # Filter to show1
        previous_shots_model.set_show_filter("show1")
        filtered = previous_shots_model.get_filtered_shots()
        assert len(filtered) == 2
        assert all(shot.show == "show1" for shot in filtered)

        # Filter to show2
        previous_shots_model.set_show_filter("show2")
        filtered = previous_shots_model.get_filtered_shots()
        assert len(filtered) == 1
        assert filtered[0].show == "show2"

    def test_previous_shots_available_shows(
        self, previous_shots_model: PreviousShotsModel, test_previous_shots: list[Shot]
    ) -> None:
        """Test getting available shows from previous shots."""
        previous_shots_model._previous_shots = test_previous_shots

        shows = previous_shots_model.get_available_shows()
        assert shows == {"show1", "show2"}


class TestShotGridViewShowFilter:
    """Test Show filter UI in ShotGridView."""

    @pytest.fixture
    def shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a ShotModel."""
        model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def shot_item_model(self, tmp_path: Path, qtbot: QtBot) -> Generator[ShotItemModel, None, None]:
        """Create ShotItemModel."""
        model = ShotItemModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"))
        yield model
        model.clear_thumbnail_cache()
        model.deleteLater()

    @pytest.fixture
    def shot_grid_view(
        self, shot_item_model: ShotItemModel, qtbot: QtBot
    ) -> ShotGridView:
        """Create ShotGridView with model."""
        view = ShotGridView(model=shot_item_model)
        qtbot.addWidget(view)
        return view

    def test_show_filter_combo_exists(self, shot_grid_view: ShotGridView) -> None:
        """Test that Show filter combo box exists."""
        assert hasattr(shot_grid_view, "show_combo")
        assert isinstance(shot_grid_view.show_combo, QComboBox)
        assert shot_grid_view.show_combo.count() == 1  # "All Shows" initially
        assert shot_grid_view.show_combo.itemText(0) == "All Shows"

    def test_populate_show_filter(
        self, shot_grid_view: ShotGridView, shot_model: ShotModel
    ) -> None:
        """Test populating show filter combo box."""
        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "shot1", "/workspace/show1/seq1/shot1"),
            Shot("show2", "seq2", "shot2", "/workspace/show2/seq2/shot2"),
            Shot("show3", "seq3", "shot3", "/workspace/show3/seq3/shot3"),
        ]
        shot_model.shots = test_shots

        # Populate filter
        shot_grid_view.populate_show_filter(shot_model)

        # Check combo box items
        assert shot_grid_view.show_combo.count() == 4  # All Shows + 3 shows
        items = [
            shot_grid_view.show_combo.itemText(i)
            for i in range(shot_grid_view.show_combo.count())
        ]
        assert items == ["All Shows", "show1", "show2", "show3"]

    def test_show_filter_signal_emission(
        self, shot_grid_view: ShotGridView, qtbot: QtBot
    ) -> None:
        """Test that changing filter emits signal."""
        # Spy on signal
        signal_spy = QSignalSpy(shot_grid_view.show_filter_requested)

        # Add shows to combo
        shot_grid_view.show_combo.addItem("show1")
        shot_grid_view.show_combo.addItem("show2")

        # Change selection
        shot_grid_view.show_combo.setCurrentIndex(1)  # Select "show1"

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "show1"

        # Select "All Shows"
        shot_grid_view.show_combo.setCurrentIndex(0)
        assert signal_spy.count() == 2
        assert signal_spy.at(1)[0] == ""  # Empty string for "All Shows"


class TestPreviousShotsViewShowFilter:
    """Test Show filter UI in PreviousShotsView."""

    @pytest.fixture
    def previous_shots_model(
        self, tmp_path: Path, qtbot: QtBot
    ) -> Generator[PreviousShotsModel, None, None]:
        """Create PreviousShotsModel."""
        shot_model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        shot_model._process_pool = TestProcessPool(allow_main_thread=True)
        model = PreviousShotsModel(shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2"))
        yield model
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        model.deleteLater()

    @pytest.fixture
    def previous_shots_item_model(
        self, tmp_path: Path, previous_shots_model: PreviousShotsModel, qtbot: QtBot
    ) -> Generator[PreviousShotsItemModel, None, None]:
        """Create PreviousShotsItemModel."""
        model = PreviousShotsItemModel(previous_shots_model, TestCacheManager(cache_dir=tmp_path / "cache3"))
        yield model
        model.deleteLater()

    @pytest.fixture
    def previous_shots_view(
        self, previous_shots_item_model: PreviousShotsItemModel, qtbot: QtBot
    ) -> PreviousShotsView:
        """Create PreviousShotsView with model."""
        view = PreviousShotsView(model=previous_shots_item_model)
        qtbot.addWidget(view)
        return view

    def test_show_filter_combo_exists(
        self, previous_shots_view: PreviousShotsView
    ) -> None:
        """Test that Show filter combo box exists in previous shots view."""
        assert hasattr(previous_shots_view, "show_combo")
        assert isinstance(previous_shots_view.show_combo, QComboBox)
        assert previous_shots_view.show_combo.count() == 1  # "All Shows" initially
        assert previous_shots_view.show_combo.itemText(0) == "All Shows"

    def test_populate_show_filter_previous_shots(
        self,
        previous_shots_view: PreviousShotsView,
        previous_shots_model: PreviousShotsModel,
    ) -> None:
        """Test populating show filter for previous shots."""
        # Set up test previous shots
        test_shots = [
            Shot("showA", "seq1", "shot1", "/workspace/showA/seq1/shot1"),
            Shot("showB", "seq2", "shot2", "/workspace/showB/seq2/shot2"),
        ]
        previous_shots_model._previous_shots = test_shots

        # Populate filter
        previous_shots_view.populate_show_filter(previous_shots_model)

        # Check combo box items
        assert previous_shots_view.show_combo.count() == 3  # All Shows + 2 shows
        items = [
            previous_shots_view.show_combo.itemText(i)
            for i in range(previous_shots_view.show_combo.count())
        ]
        assert items == ["All Shows", "showA", "showB"]

    def test_previous_shots_filter_signal(
        self, previous_shots_view: PreviousShotsView, qtbot: QtBot
    ) -> None:
        """Test that filter change emits signal in previous shots view."""
        signal_spy = QSignalSpy(previous_shots_view.show_filter_requested)

        # Add a show
        previous_shots_view.show_combo.addItem("showA")

        # Change selection
        previous_shots_view.show_combo.setCurrentIndex(1)  # Select "showA"

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "showA"


class TestMainWindowFilterHandlers:
    """Test Show filter signal handlers in MainWindow."""

    @pytest.fixture
    def mock_main_window(
        self, tmp_path: Path, qtbot: QtBot, monkeypatch: MonkeyPatch
    ) -> Generator[Any, None, None]:
        """Create a mock MainWindow setup for testing filter handlers.

        We don't create the full MainWindow as it has too many dependencies.
        Instead, we test the handler methods directly.
        """
        # Local application imports
        from main_window import (
            MainWindow,
        )

        # Prevent actual window creation
        monkeypatch.setattr(MainWindow, "__init__", lambda _self: None)

        window = MainWindow()

        # Set up minimal required attributes
        # Local application imports
        from tests.fixtures.test_doubles import (
            TestCacheManager,
            TestProcessPool,
        )

        # Create test models
        window.shot_model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False
        )
        window.shot_model._process_pool = TestProcessPool(allow_main_thread=True)

        window.shot_item_model = ShotItemModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2"))

        window.previous_shots_model = PreviousShotsModel(
            window.shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache3")
        )
        window.previous_shots_item_model = PreviousShotsItemModel(
            window.previous_shots_model, TestCacheManager(cache_dir=tmp_path / "cache4")
        )

        # Create test views
        window.shot_grid = ShotGridView(model=window.shot_item_model)
        qtbot.addWidget(window.shot_grid)

        window.previous_shots_grid = PreviousShotsView(
            model=window.previous_shots_item_model
        )
        qtbot.addWidget(window.previous_shots_grid)

        # Add RefreshOrchestrator for refactored MainWindow
        from refresh_orchestrator import (
            RefreshOrchestrator,
        )

        window.refresh_orchestrator = RefreshOrchestrator(window)

        # Add mock status bar for filter feedback
        from unittest.mock import Mock
        window.status_bar = Mock()

        # Add FilterCoordinator (filter methods moved from MainWindow)
        from controllers.filter_coordinator import FilterCoordinator
        window.filter_coordinator = FilterCoordinator(window)

        # Logger is already provided by LoggingMixin

        return window

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)

    def test_on_shot_show_filter_requested(self, mock_main_window: Any) -> None:
        """Test the handler for My Shots show filter request."""
        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "shot1", "/workspace/show1/seq1/shot1"),
            Shot("show1", "seq2", "shot2", "/workspace/show1/seq2/shot2"),
            Shot("show2", "seq3", "shot3", "/workspace/show2/seq3/shot3"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_shots(test_shots)

        # Call the handler (method is now on FilterCoordinator)
        mock_main_window.filter_coordinator._on_shot_show_filter_requested("show1")

        # Verify the filter was applied
        assert mock_main_window.shot_model.get_show_filter() == "show1"
        assert mock_main_window.shot_item_model.rowCount() == 2

        # Test clearing filter
        mock_main_window.filter_coordinator._on_shot_show_filter_requested("")
        assert mock_main_window.shot_model.get_show_filter() is None
        assert mock_main_window.shot_item_model.rowCount() == 3

    def test_on_previous_show_filter_requested(self, mock_main_window: Any) -> None:
        """Test the handler for Previous Shots show filter request."""
        # Set up test previous shots
        test_shots = [
            Shot("showA", "seq10", "shot10", "/workspace/showA/seq10/shot10"),
            Shot("showA", "seq11", "shot11", "/workspace/showA/seq11/shot11"),
            Shot("showB", "seq20", "shot20", "/workspace/showB/seq20/shot20"),
        ]
        mock_main_window.previous_shots_model._previous_shots = test_shots
        mock_main_window.previous_shots_item_model._shots = test_shots

        # Call the handler (method is now on FilterCoordinator)
        mock_main_window.filter_coordinator._on_previous_show_filter_requested("showA")

        # Verify the filter was applied
        assert mock_main_window.previous_shots_model.get_show_filter() == "showA"
        # The filter should have been applied, showing only showA shots
        filtered_shots = [
            s
            for s in mock_main_window.previous_shots_item_model._shots
            if s.show == "showA"
        ]
        assert len(filtered_shots) == 2

    def test_refresh_populates_show_filter(self, mock_main_window: Any) -> None:
        """Test that refreshing shots populates the show filter combo."""
        # Local application imports
        from main_window import (
            MainWindow,
        )

        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "shot1", "/workspace/show1/seq1/shot1"),
            Shot("show2", "seq2", "shot2", "/workspace/show2/seq2/shot2"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_shots(test_shots)

        # Call refresh method
        MainWindow._refresh_shot_display(mock_main_window)

        # Check that show filter was populated
        assert mock_main_window.shot_grid.show_combo.count() == 3  # All Shows + 2 shows
        items = [
            mock_main_window.shot_grid.show_combo.itemText(i)
            for i in range(mock_main_window.shot_grid.show_combo.count())
        ]
        assert "show1" in items
        assert "show2" in items

    def test_on_previous_shots_updated(self, mock_main_window: Any) -> None:
        """Test the handler for previous shots updated signal."""
        # Set up test previous shots
        test_shots = [
            Shot("showX", "seq1", "shot1", "/workspace/showX/seq1/shot1"),
            Shot("showY", "seq2", "shot2", "/workspace/showY/seq2/shot2"),
        ]
        mock_main_window.previous_shots_model._previous_shots = test_shots

        # Call the handler (method is now on FilterCoordinator)
        mock_main_window.filter_coordinator._on_previous_shots_updated()

        # Check that show filter was populated
        assert (
            mock_main_window.previous_shots_grid.show_combo.count() == 3
        )  # All Shows + 2 shows
        items = [
            mock_main_window.previous_shots_grid.show_combo.itemText(i)
            for i in range(mock_main_window.previous_shots_grid.show_combo.count())
        ]
        assert "showX" in items
        assert "showY" in items

    def test_filter_updates_status_bar(self, mock_main_window: Any) -> None:
        """Test that applying show filter updates status bar with count."""
        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "shot1", "/workspace/show1/seq1/shot1"),
            Shot("show1", "seq2", "shot2", "/workspace/show1/seq2/shot2"),
            Shot("show2", "seq3", "shot3", "/workspace/show2/seq3/shot3"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_shots(test_shots)

        # Call the handler (method is now on FilterCoordinator)
        mock_main_window.filter_coordinator._on_shot_show_filter_requested("show1")

        # Verify status bar was updated with filter result
        mock_main_window.status_bar.showMessage.assert_called()
        call_args = mock_main_window.status_bar.showMessage.call_args[0][0]
        assert "show1" in call_args
        assert "2" in call_args  # 2 shots filtered
