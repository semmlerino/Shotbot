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

from previous_shots.item_model import PreviousShotsItemModel
from previous_shots.model import PreviousShotsModel
from previous_shots.view import PreviousShotsView
from shots.shot_grid_view import ShotGridView

# Local application imports
from shots.shot_item_model import ShotItemModel
from shots.shot_model import ShotModel
from tests.fixtures.model_fixtures import TestCacheManager
from tests.fixtures.process_fixtures import TestProcessPool
from type_definitions import Shot


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytestqt.qtbot import QtBot

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestShotItemModelFiltering:
    """Test Show filter methods in ShotItemModel."""

    @pytest.fixture
    def shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a ShotModel with test process pool."""
        model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"),
            load_cache=False,
        )
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def shot_item_model(
        self, tmp_path: Path, qtbot: QtBot
    ) -> Generator[ShotItemModel, None, None]:
        """Create ShotItemModel for testing."""
        model = ShotItemModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache")
        )
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

        # Filter to show1 and check model state
        shot_item_model.set_show_filter(shot_model, "show1")
        assert shot_item_model.rowCount() == 2
        for i in range(shot_item_model.rowCount()):
            shot = shot_item_model.get_item_at_index(shot_item_model.index(i, 0))
            assert shot is not None
            assert shot.show == "show1"

        # Filter to show2 and check model state
        shot_item_model.set_show_filter(shot_model, "show2")
        assert shot_item_model.rowCount() == 1
        shot = shot_item_model.get_item_at_index(shot_item_model.index(0, 0))
        assert shot is not None
        assert shot.show == "show2"

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

        # Clear filter — check that all shots are visible again
        shot_item_model.set_show_filter(shot_model, None)
        assert shot_item_model.rowCount() == 3


class TestPreviousShotsModelFiltering:
    """Test Show filter methods in PreviousShotsModel."""

    @pytest.fixture
    def shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a base ShotModel."""
        model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"),
            load_cache=False,
        )
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def previous_shots_model(
        self, tmp_path: Path, shot_model: ShotModel, qtbot: QtBot
    ) -> Generator[PreviousShotsModel, None, None]:
        """Create PreviousShotsModel."""
        model = PreviousShotsModel(
            shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2")
        )
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
        model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"),
            load_cache=False,
        )
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def shot_item_model(
        self, tmp_path: Path, qtbot: QtBot
    ) -> Generator[ShotItemModel, None, None]:
        """Create ShotItemModel."""
        model = ShotItemModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache")
        )
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
        shot_model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"),
            load_cache=False,
        )
        shot_model._process_pool = TestProcessPool(allow_main_thread=True)
        model = PreviousShotsModel(
            shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2")
        )
        yield model
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        model.deleteLater()

    @pytest.fixture
    def previous_shots_item_model(
        self, tmp_path: Path, previous_shots_model: PreviousShotsModel, qtbot: QtBot
    ) -> Generator[PreviousShotsItemModel, None, None]:
        """Create PreviousShotsItemModel."""
        model = PreviousShotsItemModel(
            previous_shots_model, TestCacheManager(cache_dir=tmp_path / "cache3")
        )
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
        from tests.fixtures.model_fixtures import TestCacheManager
        from tests.fixtures.process_fixtures import TestProcessPool

        # Create test models
        window.shot_model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"),
            load_cache=False,
        )
        window.shot_model._process_pool = TestProcessPool(allow_main_thread=True)

        window.shot_item_model = ShotItemModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2")
        )

        window.previous_shots_model = PreviousShotsModel(
            window.shot_model,
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache3"),
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

        # Add RefreshCoordinator for refactored MainWindow
        from controllers.refresh_coordinator import (
            RefreshCoordinator,
        )

        window.refresh_coordinator = RefreshCoordinator(window)

        # Add mock status bar for filter feedback
        from unittest.mock import Mock

        window.status_bar = Mock()
        window._contextual_logger = Mock()

        # Add proxy model doubles (filtering moved to proxy in Phase 3)
        class _ProxyDouble:
            def __init__(self) -> None:
                self._show_filter: str | None = None
                self._text_filter: str | None = None

            def set_show_filter(self, show: str | None) -> None:
                self._show_filter = show

            def set_text_filter(self, text: str | None) -> None:
                self._text_filter = text

            def rowCount(self) -> int:
                return 0

            def sourceModel(self) -> Any:
                class _Src:
                    def rowCount(self) -> int:
                        return 0

                return _Src()

        window.shot_proxy = _ProxyDouble()
        window.previous_shots_proxy = _ProxyDouble()

        # Build a FilterCoordinator so tests can call it directly
        from controllers.filter_coordinator import FilterCoordinator

        window.filter_coordinator = FilterCoordinator(
            shot_proxy=window.shot_proxy,  # type: ignore[arg-type]
            previous_shots_proxy=window.previous_shots_proxy,  # type: ignore[arg-type]
            threede_proxy=Mock(),  # type: ignore[arg-type]
            threede_item_model=Mock(),  # type: ignore[arg-type]
            previous_shots_item_model=Mock(),  # type: ignore[arg-type]
            threede_shot_grid=Mock(),  # type: ignore[arg-type]
            previous_shots_grid=window.previous_shots_grid,
            previous_shots_model=window.previous_shots_model,
            settings_manager=Mock(),  # type: ignore[arg-type]
            status_bar=window.status_bar,  # type: ignore[arg-type]
        )

        return window

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)

    def test_on_shot_show_filter_requested(self, mock_main_window: Any) -> None:
        """Test the handler for My Shots show filter request."""
        mock_main_window.filter_coordinator.apply_show_filter(
            mock_main_window.shot_proxy, "My Shots", "show1"
        )

        # Verify the filter was applied to the proxy (proxy handles filtering)
        assert mock_main_window.shot_proxy._show_filter == "show1"

        # Test clearing filter
        mock_main_window.filter_coordinator.apply_show_filter(
            mock_main_window.shot_proxy, "My Shots", ""
        )
        assert mock_main_window.shot_proxy._show_filter is None

    def test_on_previous_show_filter_requested(self, mock_main_window: Any) -> None:
        """Test the handler for Previous Shots show filter request."""
        mock_main_window.filter_coordinator.apply_show_filter(
            mock_main_window.previous_shots_proxy, "Previous Shots", "showA"
        )

        # Verify the filter was applied to the proxy (proxy handles filtering)
        assert mock_main_window.previous_shots_proxy._show_filter == "showA"

    def test_refresh_populates_show_filter(self, mock_main_window: Any) -> None:
        """Test that refreshing shots populates the show filter combo."""
        # Local application imports

        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "shot1", "/workspace/show1/seq1/shot1"),
            Shot("show2", "seq2", "shot2", "/workspace/show2/seq2/shot2"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_shots(test_shots)

        # Call refresh method
        mock_main_window.refresh_coordinator.refresh_shot_display()

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

        mock_main_window.filter_coordinator.on_previous_shots_updated()

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
        """Test that applying show filter updates status bar."""
        mock_main_window.filter_coordinator.apply_show_filter(
            mock_main_window.shot_proxy, "My Shots", "show1"
        )

        # Verify status bar was updated with filter info
        mock_main_window.status_bar.showMessage.assert_called()
        call_args = mock_main_window.status_bar.showMessage.call_args[0][0]
        assert "show1" in call_args
        assert "My Shots" in call_args
