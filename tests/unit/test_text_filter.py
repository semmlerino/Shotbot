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

from previous_shots.item_model import PreviousShotsItemModel
from previous_shots.model import PreviousShotsModel
from previous_shots.view import PreviousShotsView
from shots.shot_grid_view import ShotGridView

# Local application imports
from shots.shot_item_model import ShotItemModel
from shots.shot_model import ShotModel
from tests.fixtures.model_fixtures import TestCacheManager
from tests.fixtures.process_fixtures import TestProcessPool
from threede import ThreeDEGridView, ThreeDEItemModel


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from main_window import MainWindow

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestBaseGridViewTextFilterUI:
    """Test Text filter UI in BaseGridView subclasses."""

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
        qtbot.wait(1)

    @pytest.fixture
    def shot_grid_view(
        self, shot_item_model: ShotItemModel, qtbot: QtBot
    ) -> ShotGridView:
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

    def test_text_filter_signal_emission(
        self, shot_grid_view: ShotGridView, qtbot: QtBot
    ) -> None:
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
        threede_item_model = ThreeDEItemModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache")
        )
        view = ThreeDEGridView(model=threede_item_model)
        qtbot.addWidget(view)

        assert hasattr(view, "text_filter_input")
        assert isinstance(view.text_filter_input, QLineEdit)

        # Cleanup
        threede_item_model.clear_thumbnail_cache()
        threede_item_model.deleteLater()
        qtbot.wait(1)

    def test_text_filter_in_previous_shots_view(
        self, tmp_path: Path, qtbot: QtBot
    ) -> None:
        """Test that text filter also exists in PreviousShotsView."""
        shot_model = ShotModel(
            cache_manager=TestCacheManager(cache_dir=tmp_path / "cache"),
            load_cache=False,
        )
        shot_model._process_pool = TestProcessPool(allow_main_thread=True)
        previous_model = PreviousShotsModel(
            shot_model, cache_manager=TestCacheManager(cache_dir=tmp_path / "cache2")
        )
        previous_item_model = PreviousShotsItemModel(
            previous_model, TestCacheManager(cache_dir=tmp_path / "cache3")
        )

        view = PreviousShotsView(model=previous_item_model)
        qtbot.addWidget(view)

        assert hasattr(view, "text_filter_input")
        assert isinstance(view.text_filter_input, QLineEdit)

        # Cleanup
        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        previous_model.deleteLater()
        qtbot.wait(1)
        previous_item_model.deleteLater()
        qtbot.wait(1)


class TestMainWindowTextFilterHandlers:
    """Test Text filter signal handlers in MainWindow."""

    def test_on_shot_text_filter_requested(self, mock_main_window: MainWindow) -> None:
        """Test the handler for My Shots text filter request."""
        mock_main_window.filter_coordinator.apply_text_filter(
            mock_main_window.shot_proxy, "My Shots", "dm"
        )  # type: ignore[attr-defined]

        # Verify the filter was applied to the proxy (proxy handles filtering)
        assert mock_main_window.shot_proxy._text_filter == "dm"  # type: ignore[attr-defined]

        # Test clearing filter
        mock_main_window.filter_coordinator.apply_text_filter(
            mock_main_window.shot_proxy, "My Shots", ""
        )  # type: ignore[attr-defined]
        assert mock_main_window.shot_proxy._text_filter is None  # type: ignore[attr-defined]

    def test_on_previous_text_filter_requested(
        self, mock_main_window: MainWindow
    ) -> None:
        """Test the handler for Previous Shots text filter request."""
        mock_main_window.filter_coordinator.apply_text_filter(
            mock_main_window.previous_shots_proxy, "Previous Shots", "dm"
        )  # type: ignore[attr-defined]

        # Verify the filter was applied to the proxy
        assert mock_main_window.previous_shots_proxy._text_filter == "dm"  # type: ignore[attr-defined]

    def test_text_and_show_filters_together(self, mock_main_window: MainWindow) -> None:
        """Test that text and show filters work together via proxy."""
        mock_main_window.filter_coordinator.apply_show_filter(
            mock_main_window.shot_proxy, "My Shots", "show1"
        )  # type: ignore[attr-defined]
        assert mock_main_window.shot_proxy._show_filter == "show1"  # type: ignore[attr-defined]

        mock_main_window.filter_coordinator.apply_text_filter(
            mock_main_window.shot_proxy, "My Shots", "dm"
        )  # type: ignore[attr-defined]
        assert mock_main_window.shot_proxy._text_filter == "dm"  # type: ignore[attr-defined]

    def test_text_filter_updates_status_bar(self, mock_main_window: MainWindow) -> None:
        """Test that applying text filter updates status bar."""
        mock_main_window.filter_coordinator.apply_text_filter(
            mock_main_window.shot_proxy, "My Shots", "dm"
        )  # type: ignore[attr-defined]

        # Verify status bar was updated with filter info
        mock_main_window.status_bar.showMessage.assert_called()
        call_args = mock_main_window.status_bar.showMessage.call_args[0][0]
        assert "dm" in call_args  # Filter text shown
        assert "My Shots" in call_args
