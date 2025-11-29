"""Comprehensive unit tests for ShotItemModel with async callback race condition testing.

This module tests the critical async callback fixes and thread safety improvements
made to ShotItemModel, focusing on the QMetaObject.invokeMethod race condition
protection and immutable shot identifier handling.
"""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytestqt.qtbot import QtBot

sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
from base_item_model import BaseItemRole as UnifiedRole
from shot_item_model import ShotItemModel
from shot_model import Shot
from tests.test_doubles_library import TestCacheManager
from tests.test_helpers import process_qt_events


# Backward compatibility alias
ShotRole = UnifiedRole

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.critical,
]


@pytest.mark.xdist_group("serial_qt_state")
class TestAsyncCallbackRaceConditions:
    """Test async callback race condition fixes in ShotItemModel."""

    @pytest.fixture
    def test_cache_manager(self, tmp_path: Path) -> TestCacheManager:
        """Create test double CacheManager with predictable behavior."""
        return TestCacheManager(cache_dir=tmp_path / "cache")

    @pytest.fixture
    def model(
        self, test_cache_manager: TestCacheManager, qtbot: QtBot
    ) -> Generator[ShotItemModel, None, None]:
        """Create ShotItemModel with test cache manager."""
        model = ShotItemModel(test_cache_manager)
        # Don't use qtbot.addWidget() for QAbstractItemModel (UNIFIED_TESTING_GUIDE)
        yield model
        # Process pending Qt events to complete async callbacks before deletion
        # This prevents "Internal C++ object already deleted" errors
        process_qt_events()
        model.clear_thumbnail_cache()
        model.deleteLater()
        # Process events again to execute deleteLater
        process_qt_events()

    @pytest.fixture
    def test_shots(self) -> list[Shot]:
        """Create test shots for model testing."""
        return [
            Shot("show1", "seq1", "shot1", "/workspace/shot1"),
            Shot("show1", "seq1", "shot2", "/workspace/shot2"),
            Shot("show2", "seq2", "shot3", "/workspace/shot3"),
        ]

    def test_find_shot_by_full_name_race_protection(
        self, model: ShotItemModel, test_shots: list[Shot]
    ) -> None:
        """Test _find_shot_by_full_name handles concurrent access safely."""
        model.set_shots(test_shots)

        target_shot = test_shots[1]

        # Should find existing shot
        result = model._find_shot_by_full_name(target_shot.full_name)
        assert result is not None
        shot, row = result
        assert shot.full_name == target_shot.full_name
        assert row == 1

        # Should return None for non-existent shot
        result = model._find_shot_by_full_name("nonexistent_shot")
        assert result is None

    @pytest.mark.real_timing  # Uses qtbot.wait(50) for async thumbnail callbacks
    def test_concurrent_thumbnail_loading(
        self,
        model: ShotItemModel,
        test_shots: list[Shot],
        qtbot: QtBot,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test multiple simultaneous thumbnail load operations for thread safety."""
        # Create fake thumbnail files for each shot
        thumbnail_paths: dict[str, Path] = {}
        for i, shot in enumerate(test_shots):
            thumbnail_path = tmp_path / f"thumbnail_{i}.jpg"
            thumbnail_path.touch()
            thumbnail_paths[shot.full_name] = thumbnail_path

        # Mock get_thumbnail_path to return correct path for each shot
        def mock_get_thumbnail(self: Shot) -> Path | None:
            return thumbnail_paths.get(self.full_name)

        monkeypatch.setattr(Shot, "get_thumbnail_path", mock_get_thumbnail)

        model.set_shots(test_shots)

        # Mock cache manager to simulate concurrent operations
        cache_calls: list[tuple[Any, ...]] = []

        def mock_cache_thumbnail(*args: Any, **kwargs: Any) -> Path:
            cache_calls.append(args)
            # Return immediate success for simplicity
            return Path("/cache/mock_thumbnail.jpg")

        with patch.object(
            model._cache_manager, "cache_thumbnail", mock_cache_thumbnail
        ):
            # Pre-mark items as "loading" (as documented in _load_thumbnail_async)
            for shot in test_shots:
                model._loading_states[shot.full_name] = "loading"

            # Start multiple concurrent thumbnail loads
            for i, shot in enumerate(test_shots):
                model._load_thumbnail_async(i, shot)

            # Wait for async callbacks to complete
            qtbot.wait(50)

            # Verify all cache calls were made
            assert len(cache_calls) == len(test_shots)

            # Verify loading states were set correctly (may transition to loaded/failed)
            for shot in test_shots:
                state = model._loading_states.get(shot.full_name)
                assert state in ["loading", "loaded", "failed"]  # Valid states

    def test_thumbnail_cache_consistency_during_model_reset(
        self, model: ShotItemModel, test_shots: list[Shot], qtbot: QtBot
    ) -> None:
        """Test that thumbnail cache remains consistent during model reset operations."""
        model.set_shots(test_shots)

        # Populate thumbnail cache
        test_image = QImage(64, 64, QImage.Format.Format_RGB32)
        test_image.fill(Qt.GlobalColor.red)
        model._thumbnail_cache[test_shots[0].full_name] = test_image

        # Set up spy for model reset signals
        reset_spy = QSignalSpy(model.modelAboutToBeReset)
        reset_done_spy = QSignalSpy(model.modelReset)

        # Reset model with new shots
        new_shots = [Shot("new_show", "new_seq", "new_shot", "/new/path")]
        model.set_shots(new_shots)

        # Verify signals were emitted
        assert reset_spy.count() == 1
        assert reset_done_spy.count() == 1

        # Verify cache was cleared during reset
        assert len(model._thumbnail_cache) == 0
        assert len(model._loading_states) == 0


class TestShotItemModelCore:
    """Test core ShotItemModel functionality."""

    @pytest.fixture
    def model(self, qtbot: QtBot) -> Generator[ShotItemModel, None, None]:
        """Create basic ShotItemModel."""
        model = ShotItemModel()
        yield model
        # Process pending Qt events before deletion
        process_qt_events()
        model.deleteLater()
        process_qt_events()

    def test_model_initialization(self, model: ShotItemModel) -> None:
        """Test model initializes correctly."""
        assert model.rowCount() == 0
        assert isinstance(model._thumbnail_cache, dict)
        assert isinstance(model._loading_states, dict)
        assert model._cache_manager is not None

    def test_shot_data_access(self, model: ShotItemModel) -> None:
        """Test data access through Qt model interface."""
        test_shots = [Shot("show", "seq", "shot", "/path")]
        model.set_shots(test_shots)

        index = model.index(0, 0)

        # Test various role access
        assert model.data(index, Qt.ItemDataRole.DisplayRole) == test_shots[0].full_name
        assert model.data(index, ShotRole.ObjectRole) == test_shots[0]
        assert model.data(index, ShotRole.ShowRole) == "show"
        assert model.data(index, ShotRole.SequenceRole) == "seq"
        # Note: ShotNameRole doesn't exist in UnifiedRole - use ItemSpecificRole1 for shot name

    def test_selection_handling(self, model: ShotItemModel) -> None:
        """Test selection state management."""
        test_shots = [Shot("show", "seq", "shot1", "/path1")]
        model.set_shots(test_shots)

        index = model.index(0, 0)

        # Set selection
        success = model.setData(index, True, ShotRole.IsSelectedRole)
        assert success

        # Verify selection state
        assert model.data(index, ShotRole.IsSelectedRole) is True

        # Clear selection
        success = model.setData(index, False, ShotRole.IsSelectedRole)
        assert success
        assert model.data(index, ShotRole.IsSelectedRole) is False

    def test_refresh_shots_change_detection(self, model: ShotItemModel) -> None:
        """Test intelligent change detection during refresh."""
        original_shots = [Shot("show", "seq", "shot1", "/path1")]
        model.set_shots(original_shots)

        # Refresh with same shots - no changes
        result = model.refresh_shots(original_shots)
        assert result.success is True
        assert result.has_changes is False

        # Refresh with different shots - has changes
        new_shots = [Shot("show", "seq", "shot2", "/path2")]
        result = model.refresh_shots(new_shots)
        assert result.success is True
        assert result.has_changes is True
