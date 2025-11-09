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
from tests.test_doubles_library import TestCacheManager, TestProcessPool
from tests.test_helpers import process_qt_events
from threede_grid_view import ThreeDEGridView
from threede_item_model import ThreeDEItemModel
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytestqt.qtbot import QtBot

    from main_window import MainWindow

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestBaseShotModelTextFiltering:
    """Test Text filter methods in BaseShotModel."""

    @pytest.fixture
    def mock_shot_model(self, tmp_path: Path) -> ShotModel:
        """Create a ShotModel with test process pool."""
        process_pool = TestProcessPool()
        model = ShotModel(cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        model._process_pool = process_pool
        return model

    @pytest.fixture
    def test_shots(self) -> list[Shot]:
        """Create test shots with various names for filtering."""
        return [
            Shot("show1", "seq1", "dm_001", "/workspace/show1/seq1/dm_001"),
            Shot("show1", "seq2", "DM_002", "/workspace/show1/seq2/DM_002"),
            Shot("show1", "seq3", "shot_003", "/workspace/show1/seq3/shot_003"),
            Shot("show2", "seq4", "Dm_004", "/workspace/show2/seq4/Dm_004"),
            Shot("show2", "seq5", "other_005", "/workspace/show2/seq5/other_005"),
        ]

    def test_set_text_filter(self, mock_shot_model: ShotModel) -> None:
        """Test setting the text filter."""
        # Initially no filter
        assert mock_shot_model.get_text_filter() is None

        # Set filter to "dm"
        mock_shot_model.set_text_filter("dm")
        assert mock_shot_model.get_text_filter() == "dm"

        # Clear filter
        mock_shot_model.set_text_filter(None)
        assert mock_shot_model.get_text_filter() is None

    def test_get_filtered_shots_no_filter(self, mock_shot_model: ShotModel, test_shots: list[Shot]) -> None:
        """Test getting filtered shots with no filter returns all shots."""
        mock_shot_model.shots = test_shots

        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 5
        assert filtered == test_shots

    def test_get_filtered_shots_with_text_filter(
        self, mock_shot_model: ShotModel, test_shots: list[Shot]
    ) -> None:
        """Test getting filtered shots with text filter (case-insensitive)."""
        mock_shot_model.shots = test_shots

        # Filter to "dm" (case-insensitive)
        mock_shot_model.set_text_filter("dm")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 3  # dm_001, DM_002, Dm_004
        assert all("dm" in shot.shot.lower() for shot in filtered)

        # Filter to "shot"
        mock_shot_model.set_text_filter("shot")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 1  # shot_003
        assert filtered[0].shot == "shot_003"

        # Filter to "other"
        mock_shot_model.set_text_filter("other")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 1  # other_005
        assert filtered[0].shot == "other_005"

    def test_get_filtered_shots_case_insensitive(
        self, mock_shot_model: ShotModel, test_shots: list[Shot]
    ) -> None:
        """Test that text filtering is case-insensitive."""
        mock_shot_model.shots = test_shots

        # Test different cases of "dm"
        for text in ["dm", "DM", "Dm", "dM"]:
            mock_shot_model.set_text_filter(text)
            filtered = mock_shot_model.get_filtered_shots()
            assert len(filtered) == 3
            assert all("dm" in shot.shot.lower() for shot in filtered)

    def test_get_filtered_shots_no_matches(self, mock_shot_model: ShotModel, test_shots: list[Shot]) -> None:
        """Test filtering for text that doesn't match any shots returns empty list."""
        mock_shot_model.shots = test_shots

        mock_shot_model.set_text_filter("nonexistent")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 0

    def test_get_filtered_shots_combined_filters(
        self, mock_shot_model: ShotModel, test_shots: list[Shot]
    ) -> None:
        """Test using both show filter and text filter together."""
        mock_shot_model.shots = test_shots

        # Apply both filters: show1 AND dm
        mock_shot_model.set_show_filter("show1")
        mock_shot_model.set_text_filter("dm")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 2  # dm_001 and DM_002 from show1
        assert all(shot.show == "show1" for shot in filtered)
        assert all("dm" in shot.shot.lower() for shot in filtered)

        # Apply both filters: show2 AND other
        mock_shot_model.set_show_filter("show2")
        mock_shot_model.set_text_filter("other")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 1  # other_005 from show2
        assert filtered[0].show == "show2"
        assert filtered[0].shot == "other_005"

    def test_get_filtered_shots_filters_on_full_name(
        self, mock_shot_model: ShotModel, test_shots: list[Shot]
    ) -> None:
        """Test that filtering works on full_name property (sequence_shot)."""
        mock_shot_model.shots = test_shots

        # Filter by sequence pattern
        mock_shot_model.set_text_filter("seq1")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 1
        assert "seq1" in filtered[0].full_name

        # Filter by full_name pattern
        mock_shot_model.set_text_filter("seq2_DM")
        filtered = mock_shot_model.get_filtered_shots()
        assert len(filtered) == 1
        assert filtered[0].full_name == "seq2_DM_002"


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
        model._process_pool = TestProcessPool()
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
        assert (
            shot_grid_view.text_filter_input.placeholderText()
            == "Type to filter shots..."
        )
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
        shot_model._process_pool = TestProcessPool()
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
        window.shot_model._process_pool = TestProcessPool()

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

        return window

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)

    def test_on_shot_text_filter_requested(self, mock_main_window: MainWindow) -> None:
        """Test the handler for My Shots text filter request."""
        # Local application imports
        from main_window import (
            MainWindow,
        )

        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "dm_001", "/workspace/show1/seq1/dm_001"),
            Shot("show1", "seq2", "DM_002", "/workspace/show1/seq2/DM_002"),
            Shot("show1", "seq3", "shot_003", "/workspace/show1/seq3/shot_003"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_items(test_shots)

        # Call the handler with "dm" filter
        MainWindow._on_shot_text_filter_requested(mock_main_window, "dm")

        # Verify the filter was applied
        assert mock_main_window.shot_model.get_text_filter() == "dm"
        assert mock_main_window.shot_item_model.rowCount() == 2

        # Test clearing filter
        MainWindow._on_shot_text_filter_requested(mock_main_window, "")
        assert mock_main_window.shot_model.get_text_filter() is None
        assert mock_main_window.shot_item_model.rowCount() == 3

    def test_on_previous_text_filter_requested(self, mock_main_window: MainWindow) -> None:
        """Test the handler for Previous Shots text filter request."""
        # Local application imports
        from main_window import (
            MainWindow,
        )

        # Set up test previous shots
        test_shots = [
            Shot("showA", "seq10", "dm_010", "/workspace/showA/seq10/dm_010"),
            Shot("showA", "seq11", "other_011", "/workspace/showA/seq11/other_011"),
            Shot("showB", "seq20", "dm_020", "/workspace/showB/seq20/dm_020"),
        ]
        mock_main_window.previous_shots_model._previous_shots = test_shots
        mock_main_window.previous_shots_item_model.set_items(test_shots)

        # Call the handler with "dm" filter
        MainWindow._on_previous_text_filter_requested(mock_main_window, "dm")

        # Verify the filter was applied
        assert mock_main_window.previous_shots_model.get_text_filter() == "dm"
        assert mock_main_window.previous_shots_item_model.rowCount() == 2

    def test_text_and_show_filters_together(self, mock_main_window: MainWindow) -> None:
        """Test that text and show filters work together."""
        # Local application imports
        from main_window import (
            MainWindow,
        )

        # Set up test shots
        test_shots = [
            Shot("show1", "seq1", "dm_001", "/workspace/show1/seq1/dm_001"),
            Shot("show1", "seq2", "DM_002", "/workspace/show1/seq2/DM_002"),
            Shot("show2", "seq3", "dm_003", "/workspace/show2/seq3/dm_003"),
            Shot("show2", "seq4", "other_004", "/workspace/show2/seq4/other_004"),
        ]
        mock_main_window.shot_model.shots = test_shots
        mock_main_window.shot_item_model.set_items(test_shots)

        # Apply show filter first
        MainWindow._on_shot_show_filter_requested(mock_main_window, "show1")
        assert mock_main_window.shot_item_model.rowCount() == 2

        # Then apply text filter
        MainWindow._on_shot_text_filter_requested(mock_main_window, "dm")
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
