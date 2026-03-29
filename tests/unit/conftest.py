"""Unit test fixtures and configuration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from previous_shots.item_model import PreviousShotsItemModel
from previous_shots.model import PreviousShotsModel
from previous_shots.view import PreviousShotsView
from shots.shot_grid_view import ShotGridView
from shots.shot_item_model import ShotItemModel
from shots.shot_model import ShotModel
from tests.fixtures.model_fixtures import TestCacheManager
from tests.fixtures.process_fixtures import TestProcessPool


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def mock_shows_root(monkeypatch: pytest.MonkeyPatch) -> str:
    """Mock Config.Paths.SHOWS_ROOT for VFX path testing.

    Sets SHOWS_ROOT to /shows, which:
    1. Doesn't exist on dev machines (preventing filesystem access)
    2. Matches hardcoded paths in test data (workspace /shows/...)
    3. Ensures consistent path behavior across all unit tests

    Can be used as a simple fixture parameter to avoid @patch decorators.
    """
    from config import (
        Config,
    )

    monkeypatch.setattr(Config.Paths, "SHOWS_ROOT", "/shows")
    return "/shows"


@pytest.fixture
def mock_main_window(
    tmp_path: Path, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> Any:
    """Create a mock MainWindow setup for testing filter handlers.

    We don't create the full MainWindow as it has too many dependencies.
    Instead, we test the handler methods directly.

    Provides a MainWindow-like object with:
    - shot_model, shot_item_model, previous_shots_model, previous_shots_item_model
    - shot_grid (ShotGridView), previous_shots_grid (PreviousShotsView)
    - refresh_coordinator, filter_coordinator
    - status_bar (Mock), _contextual_logger (Mock)
    - shot_proxy, previous_shots_proxy (_ProxyDouble instances)
    """
    from unittest.mock import Mock

    from controllers.filter_coordinator import FilterCoordinator
    from controllers.refresh_coordinator import RefreshCoordinator
    from main_window import MainWindow

    # Prevent actual window creation
    monkeypatch.setattr(MainWindow, "__init__", lambda _self: None)

    window = MainWindow()

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
    window.refresh_coordinator = RefreshCoordinator(window)

    # Add mock status bar for filter feedback
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
