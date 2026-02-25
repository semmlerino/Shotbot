"""Unit tests for Text filter functionality across all components.

This module tests the Text filter feature added to all tabs including:
- Model filtering (base_shot_model, threede_scene_model, previous_shots_model)
- View UI components (base_grid_view and subclasses)
- Main window signal handlers

Following UNIFIED_TESTING_GUIDE principles:
- Test behavior, not implementation
- Use real components with test doubles at boundaries
- Mock only external dependencies
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

# Standard library imports
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLineEdit

from previous_shots_item_model import PreviousShotsItemModel
from previous_shots_model import PreviousShotsModel
from previous_shots_view import PreviousShotsView
from shot_grid_view import ShotGridView

# Local application imports
from shot_item_model import ShotItemModel
from shot_model import Shot, ShotModel
from tests.fixtures.doubles_library import TestCacheManager, TestProcessPool
from tests.test_helpers import process_qt_events
from threede_grid_view import ThreeDEGridView
from threede_item_model import ThreeDEItemModel
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytestqt.qtbot import QtBot

    from main_window import MainWindow

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestThreeDESceneModelTextFiltering:
    """Test Text filter methods in ThreeDESceneModel."""

    @pytest.fixture
    def threede_scene_model(self, tmp_path: Path) -> ThreeDESceneModel:
        """Create ThreeDESceneModel."""
        return ThreeDESceneModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)

    @pytest.fixture
    def test_scenes(self, tmp_path: Path) -> list[ThreeDEScene]:
        """Create test 3DE scenes with various names."""
        return [
            ThreeDEScene(
                "show1",
                "seq1",
                "dm_scene",
                "/workspace/show1/seq1/dm_scene",
                "user1",
                "FG01",
                tmp_path / "dm_scene.3de",
            ),
            ThreeDEScene(
                "show1",
                "seq2",
                "DM_scene2",
                "/workspace/show1/seq2/DM_scene2",
                "user2",
                "BG01",
                tmp_path / "DM_scene2.3de",
            ),
            ThreeDEScene(
                "show2",
                "seq3",
                "other_scene",
                "/workspace/show2/seq3/other_scene",
                "user1",
                "FG01",
                tmp_path / "other_scene.3de",
            ),
        ]

    def test_set_text_filter(self, threede_scene_model: ThreeDESceneModel) -> None:
        """Test setting the text filter on 3DE scene model."""
        assert threede_scene_model.get_text_filter() is None

        threede_scene_model.set_text_filter("dm")
        assert threede_scene_model.get_text_filter() == "dm"

        threede_scene_model.set_text_filter(None)
        assert threede_scene_model.get_text_filter() is None

    def test_get_filtered_scenes_with_text_filter(
        self, threede_scene_model: ThreeDESceneModel, test_scenes: list[ThreeDEScene]
    ) -> None:
        """Test filtering 3DE scenes by text."""
        threede_scene_model.scenes = test_scenes

        # Filter to "dm"
        threede_scene_model.set_text_filter("dm")
        filtered = threede_scene_model.get_filtered_scenes()
        assert len(filtered) == 2  # dm_scene and DM_scene2
        assert all("dm" in scene.shot.lower() for scene in filtered)

        # Filter to "other"
        threede_scene_model.set_text_filter("other")
        filtered = threede_scene_model.get_filtered_scenes()
        assert len(filtered) == 1
        assert filtered[0].shot == "other_scene"

    def test_get_filtered_scenes_combined_filters(
        self, threede_scene_model: ThreeDESceneModel, test_scenes: list[ThreeDEScene]
    ) -> None:
        """Test combining show and text filters for 3DE scenes."""
        threede_scene_model.scenes = test_scenes

        # Both filters: show1 AND dm
        threede_scene_model.set_show_filter("show1")
        threede_scene_model.set_text_filter("dm")
        filtered = threede_scene_model.get_filtered_scenes()
        assert len(filtered) == 2
        assert all(scene.show == "show1" for scene in filtered)
        assert all("dm" in scene.shot.lower() for scene in filtered)


class TestPreviousShotsModelTextFiltering:
    """Test Text filter methods in PreviousShotsModel."""

    @pytest.fixture
    def shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a base ShotModel."""
        model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        model._process_pool = TestProcessPool(allow_main_thread=True)
        return model

    @pytest.fixture
    def previous_shots_model(self, tmp_path: Path, shot_model: ShotModel, qtbot: QtBot) -> Generator[PreviousShotsModel, None, None]:
        """Create PreviousShotsModel."""
        model = PreviousShotsModel(shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2"))
        yield model
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        model.deleteLater()
        process_qt_events()

    @pytest.fixture
    def test_previous_shots(self) -> list[Shot]:
        """Create test previous shots with various names."""
        return [
            Shot("show1", "seq10", "dm_010", "/workspace/show1/seq10/dm_010"),
            Shot("show1", "seq11", "DM_011", "/workspace/show1/seq11/DM_011"),
            Shot("show2", "seq20", "other_020", "/workspace/show2/seq20/other_020"),
        ]

    def test_previous_shots_text_filtering(
        self, previous_shots_model: PreviousShotsModel, test_previous_shots: list[Shot]
    ) -> None:
        """Test filtering previous shots by text."""
        previous_shots_model._previous_shots = test_previous_shots

        # Filter to "dm"
        previous_shots_model.set_text_filter("dm")
        filtered = previous_shots_model.get_filtered_shots()
        assert len(filtered) == 2
        assert all("dm" in shot.shot.lower() for shot in filtered)

        # Filter to "other"
        previous_shots_model.set_text_filter("other")
        filtered = previous_shots_model.get_filtered_shots()
        assert len(filtered) == 1
        assert filtered[0].shot == "other_020"

    def test_previous_shots_combined_filters(
        self, previous_shots_model: PreviousShotsModel, test_previous_shots: list[Shot]
    ) -> None:
        """Test combining show and text filters for previous shots."""
        previous_shots_model._previous_shots = test_previous_shots

        # Both filters: show1 AND dm
        previous_shots_model.set_show_filter("show1")
        previous_shots_model.set_text_filter("dm")
        filtered = previous_shots_model.get_filtered_shots()
        assert len(filtered) == 2
        assert all(shot.show == "show1" for shot in filtered)
        assert all("dm" in shot.shot.lower() for shot in filtered)


class TestBaseGridViewTextFilterUI:
    """Test Text filter UI in BaseGridView subclasses."""

    @pytest.fixture
    def shot_item_model(self, tmp_path: Path, qtbot: QtBot) -> Generator[ShotItemModel, None, None]:
        """Create ShotItemModel."""
        model = ShotItemModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"))
        yield model
        model.clear_thumbnail_cache()
        model.deleteLater()
        process_qt_events()

    @pytest.fixture
    def shot_grid_view(self, shot_item_model: ShotItemModel, qtbot: QtBot) -> ShotGridView:
        """Create ShotGridView with model."""
        view = ShotGridView(model=shot_item_model)
        qtbot.addWidget(view)
        return view

    def test_text_filter_widget_exists(self, shot_grid_view: ShotGridView) -> None:
        """Test that text filter QLineEdit exists."""
        assert hasattr(shot_grid_view, "text_filter_input")
        assert isinstance(shot_grid_view.text_filter_input, QLineEdit)
        # Compact toolbar uses shorter placeholder "Filter..."
        assert shot_grid_view.text_filter_input.placeholderText() == "Filter..."
        assert shot_grid_view.text_filter_input.isClearButtonEnabled()

    def test_text_filter_signal_emission(self, shot_grid_view: ShotGridView, qtbot: QtBot) -> None:
        """Test that typing in filter emits signal."""
        signal_spy = QSignalSpy(shot_grid_view.text_filter_requested)

        # Type some text
        shot_grid_view.text_filter_input.setText("dm")

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "dm"

        # Change text
        shot_grid_view.text_filter_input.setText("shot")
        assert signal_spy.count() == 2
        assert signal_spy.at(1)[0] == "shot"

        # Clear text
        shot_grid_view.text_filter_input.clear()
        assert signal_spy.count() == 3
        assert signal_spy.at(2)[0] == ""

    def test_text_filter_in_threede_view(self, tmp_path: Path, qtbot: QtBot) -> None:
        """Test that text filter also exists in ThreeDEGridView."""
        threede_item_model = ThreeDEItemModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"))
        view = ThreeDEGridView(model=threede_item_model)
        qtbot.addWidget(view)

        assert hasattr(view, "text_filter_input")
        assert isinstance(view.text_filter_input, QLineEdit)

        # Cleanup
        threede_item_model.clear_thumbnail_cache()
        threede_item_model.deleteLater()
        process_qt_events()

    def test_text_filter_in_previous_shots_view(self, tmp_path: Path, qtbot: QtBot) -> None:
        """Test that text filter also exists in PreviousShotsView."""
        shot_model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        shot_model._process_pool = TestProcessPool(allow_main_thread=True)
        previous_model = PreviousShotsModel(
            shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2")
        )
        previous_item_model = PreviousShotsItemModel(previous_model, TestCacheManager(cache_dir=tmp_path / "cache3"))

        view = PreviousShotsView(model=previous_item_model)
        qtbot.addWidget(view)

        assert hasattr(view, "text_filter_input")
        assert isinstance(view.text_filter_input, QLineEdit)

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        previous_model.deleteLater()
        process_qt_events()
        previous_item_model.deleteLater()
        process_qt_events()


class TestMainWindowTextFilterHandlers:
    """Test Text filter signal handlers in MainWindow."""

    @pytest.fixture
    def mock_main_window(self, tmp_path: Path, qtbot: QtBot, monkeypatch: MonkeyPatch) -> MainWindow:
        """Create a mock MainWindow setup for testing text filter handlers."""
        # Local application imports
        from main_window import (
            MainWindow,
        )

        # Prevent actual window creation
        monkeypatch.setattr(MainWindow, "__init__", lambda _self: None)

        window = MainWindow()

        # Set up minimal required attributes
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

        # Add RefreshOrchestrator for refactored MainWindow
        from refresh_orchestrator import (
            RefreshOrchestrator,
        )

        window.refresh_orchestrator = RefreshOrchestrator(window)

        # Add mock status bar for filter feedback
        from unittest.mock import Mock
        window.status_bar = Mock()

        # Add mock grid views for FilterCoordinator signal connections
        # Mock signals with connect() method that does nothing
        mock_signal = Mock()
        mock_signal.connect = Mock(return_value=None)

        mock_shot_grid = Mock()
        mock_shot_grid.show_filter_requested = mock_signal
        mock_shot_grid.text_filter_requested = mock_signal
        window.shot_grid = mock_shot_grid

        mock_previous_grid = Mock()
        mock_previous_grid.show_filter_requested = mock_signal
        mock_previous_grid.text_filter_requested = mock_signal
        window.previous_shots_grid = mock_previous_grid

        # Add FilterCoordinator for filter handling
        from controllers.filter_coordinator import FilterCoordinator
        window.filter_coordinator = FilterCoordinator(window)  # pyright: ignore[reportArgumentType]

        return window

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)

    def test_on_shot_text_filter_requested(self, mock_main_window: MainWindow) -> None:
        """Test the handler for My Shots text filter request."""
        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "dm_001", "/workspace/show1/seq1/dm_001"),
            Shot("show1", "seq2", "DM_002", "/workspace/show1/seq2/DM_002"),
            Shot("show1", "seq3", "shot_003", "/workspace/show1/seq3/shot_003"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_items(test_shots)

        # Call the handler with "dm" filter via filter_coordinator
        mock_main_window.filter_coordinator._on_shot_text_filter_requested("dm")

        # Verify the filter was applied
        assert mock_main_window.shot_model.get_text_filter() == "dm"
        assert mock_main_window.shot_item_model.rowCount() == 2

        # Test clearing filter
        mock_main_window.filter_coordinator._on_shot_text_filter_requested("")
        assert mock_main_window.shot_model.get_text_filter() is None
        assert mock_main_window.shot_item_model.rowCount() == 3

    def test_on_previous_text_filter_requested(self, mock_main_window: MainWindow) -> None:
        """Test the handler for Previous Shots text filter request."""
        # Set up test previous shots
        test_shots = [
            Shot("showA", "seq10", "dm_010", "/workspace/showA/seq10/dm_010"),
            Shot("showA", "seq11", "other_011", "/workspace/showA/seq11/other_011"),
            Shot("showB", "seq20", "dm_020", "/workspace/showB/seq20/dm_020"),
        ]
        mock_main_window.previous_shots_model._previous_shots = test_shots
        mock_main_window.previous_shots_item_model.set_items(test_shots)

        # Call the handler with "dm" filter via filter_coordinator
        mock_main_window.filter_coordinator._on_previous_text_filter_requested("dm")

        # Verify the filter was applied
        assert mock_main_window.previous_shots_model.get_text_filter() == "dm"
        assert mock_main_window.previous_shots_item_model.rowCount() == 2

    def test_text_and_show_filters_together(self, mock_main_window: MainWindow) -> None:
        """Test that text and show filters work together."""
        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "dm_001", "/workspace/show1/seq1/dm_001"),
            Shot("show1", "seq2", "DM_002", "/workspace/show1/seq2/DM_002"),
            Shot("show2", "seq3", "dm_003", "/workspace/show2/seq3/dm_003"),
            Shot("show2", "seq4", "other_004", "/workspace/show2/seq4/other_004"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_items(test_shots)

        # Apply show filter first via filter_coordinator
        mock_main_window.filter_coordinator._on_shot_show_filter_requested("show1")
        assert mock_main_window.shot_item_model.rowCount() == 2

        # Then apply text filter via filter_coordinator
        mock_main_window.filter_coordinator._on_shot_text_filter_requested("dm")
        # Should show only show1 shots with "dm"
        assert mock_main_window.shot_item_model.rowCount() == 2
        filtered = [
            mock_main_window.shot_item_model.get_item_at_index(
                mock_main_window.shot_item_model.index(i, 0)
            )
            for i in range(mock_main_window.shot_item_model.rowCount())
        ]
        assert all(shot.show == "show1" for shot in filtered)
        assert all("dm" in shot.shot.lower() for shot in filtered)

    def test_text_filter_updates_status_bar(self, mock_main_window: MainWindow) -> None:
        """Test that applying text filter updates status bar with count."""
        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "dm_001", "/workspace/show1/seq1/dm_001"),
            Shot("show1", "seq2", "DM_002", "/workspace/show1/seq2/DM_002"),
            Shot("show1", "seq3", "shot_003", "/workspace/show1/seq3/shot_003"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_items(test_shots)

        # Call the handler with "dm" filter via filter_coordinator
        mock_main_window.filter_coordinator._on_shot_text_filter_requested("dm")

        # Verify status bar was updated with filter result
        mock_main_window.status_bar.showMessage.assert_called()
        call_args = mock_main_window.status_bar.showMessage.call_args[0][0]
        assert "2 of 3" in call_args  # 2 filtered out of 3
        assert "dm" in call_args  # Filter text shown
