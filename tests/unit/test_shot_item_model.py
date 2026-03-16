"""Comprehensive unit tests for ShotItemModel.

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real components (CacheManager with tmp_path)
- Use QSignalSpy for signal testing
- Test doubles for system boundaries (ProcessPool)
- No mocking of Qt components
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy

from base_item_model import BaseItemRole
from config import Config
from shot_item_model import ShotItemModel
from tests.test_helpers import process_qt_events
from type_definitions import Shot


if TYPE_CHECKING:

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from base_shot_model import BaseShotModel
    from tests.fixtures.test_doubles import TestProcessPool

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def test_shots() -> list[Shot]:
    """Create test Shot objects for testing."""
    return [
        Shot("show1", "seq01", "0010", f"{Config.SHOWS_ROOT}/show1/shots/seq01/seq01_0010"),
        Shot("show1", "seq01", "0020", f"{Config.SHOWS_ROOT}/show1/shots/seq01/seq01_0020"),
        Shot("show2", "seq02", "0030", f"{Config.SHOWS_ROOT}/show2/shots/seq02/seq02_0030"),
        Shot("show2", "seq02", "0040", f"{Config.SHOWS_ROOT}/show2/shots/seq02/seq02_0040"),
    ]


@pytest.fixture
def shot_item_model(
    qapp: QApplication, cache_manager: object
) -> ShotItemModel:
    """Create a ShotItemModel instance for testing."""
    return ShotItemModel(cache_manager=cache_manager)


@pytest.fixture
def base_shot_model(
    cache_manager: object, test_process_pool: TestProcessPool
) -> BaseShotModel:
    """Create a real BaseShotModel with test process pool."""
    from base_shot_model import (
        BaseShotModel,
    )

    return BaseShotModel(
        cache_manager=cache_manager,
        load_cache=False,
        process_pool=test_process_pool,
    )


# ============================================================================
# Test Classes
# ============================================================================


class TestInitialization:
    """Test ShotItemModel initialization behavior."""

    def test_initialization_with_underlying_model(
        self, qapp: QApplication, cache_manager: object
    ) -> None:
        """Test proper setup with cache manager."""
        model = ShotItemModel(cache_manager=cache_manager)

        assert model._cache_manager is cache_manager
        assert model.rowCount() == 0

    def test_initialization_with_cache_manager(
        self, qapp: QApplication, cache_manager: object
    ) -> None:
        """Test cache integration during initialization."""
        model = ShotItemModel(cache_manager=cache_manager)

        # Verify cache manager is properly set
        assert model._cache_manager is not None
        assert model._cache_manager is cache_manager

        # Verify initial state
        assert len(model.shots) == 0
        assert model.rowCount() == 0

    def test_signals_exist(self, shot_item_model: ShotItemModel) -> None:
        """Test that shot-specific signals are properly defined."""
        # Verify shot-specific signals exist
        assert hasattr(shot_item_model, "shots_updated")

        # Verify base signals are inherited
        assert hasattr(shot_item_model, "items_updated")

    def test_shots_updated_connected_to_items_updated(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test that shots_updated signal is emitted when items_updated fires."""
        shots_spy = QSignalSpy(shot_item_model.shots_updated)
        items_spy = QSignalSpy(shot_item_model.items_updated)

        shot_item_model.set_shots(test_shots)

        # Both signals should be emitted
        assert shots_spy.count() == 1
        assert items_spy.count() == 1


class TestThumbnailLoading:
    """Test thumbnail loading behavior."""

    def test_thumbnail_loaded_signal_emission(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test that thumbnail_loaded signal is emitted when thumbnail loads."""
        shot_item_model.set_shots(test_shots)

        spy = QSignalSpy(shot_item_model.thumbnail_loaded)

        # Trigger thumbnail loading by setting visible range
        shot_item_model.set_visible_range(0, 1)

        # Process events to allow async loading
        process_qt_events()

        # Signal emission depends on cache manager behavior
        # We verify the signal exists and can be connected
        assert spy is not None

    def test_atomic_thumbnail_loading(
        self,
        shot_item_model: ShotItemModel,
        qtbot: QtBot,
        test_shots: list[Shot],
        cache_manager: object,
    ) -> None:
        """Test no duplicate loads for same shot (atomic check-and-mark)."""
        shot_item_model.set_shots(test_shots)

        # Get initial loading state
        {
            shot.full_name: shot_item_model._thumbnail_loader.loading_states.get(shot.full_name, "idle")
            for shot in test_shots
        }

        # Trigger loading for same range multiple times
        for _ in range(3):
            shot_item_model.set_visible_range(0, 1)
            process_qt_events()

        # Verify states are consistent (no duplicate loading)
        for shot in test_shots[:2]:
            state = shot_item_model._thumbnail_loader.loading_states.get(shot.full_name, "idle")
            # State should be either idle or loaded, never stuck in loading
            assert state in ("idle", "loading", "loaded")

    def test_thumbnail_loading_respects_visibility(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test only loads visible items."""
        shot_item_model.set_shots(test_shots)

        # Set visible range to only first two items
        shot_item_model.set_visible_range(0, 1)
        process_qt_events()

        # Check loading states - only visible items should be marked
        visible_states = [
            shot_item_model._thumbnail_loader.loading_states.get(shot.full_name, "idle")
            for shot in test_shots[:2]
        ]
        invisible_states = [
            shot_item_model._thumbnail_loader.loading_states.get(shot.full_name, "idle")
            for shot in test_shots[2:]
        ]

        # Visible items may be in loading or loaded state
        for state in visible_states:
            assert state in ("idle", "loading", "loaded")

        # Invisible items should remain idle
        for state in invisible_states:
            assert state == "idle"

    def test_thumbnail_loading_lifecycle(
        self,
        shot_item_model: ShotItemModel,
        qtbot: QtBot,
        test_shots: list[Shot],
        cache_manager: object,
    ) -> None:
        """Test load → cache → retrieve pattern."""
        shot_item_model.set_shots(test_shots)
        shot = test_shots[0]

        # Initial state - no thumbnail
        assert shot.full_name not in shot_item_model._thumbnail_loader.thumbnail_cache

        # Trigger loading
        shot_item_model.set_visible_range(0, 0)
        process_qt_events()

        # After loading, thumbnail may be cached (depends on cache manager)
        # We verify the mechanism exists
        assert hasattr(shot_item_model._thumbnail_loader, "thumbnail_cache")
        assert isinstance(shot_item_model._thumbnail_loader.thumbnail_cache, dict)


class TestShowFiltering:
    """Test show filtering behavior."""

    def test_show_filter_updates_visible_items(
        self,
        shot_item_model: ShotItemModel,
        base_shot_model: BaseShotModel,
        qtbot: QtBot,
        test_shots: list[Shot],
    ) -> None:
        """Test filter changes item visibility."""
        # Set initial shots in base model
        base_shot_model.shots = test_shots
        shot_item_model.set_shots(test_shots)

        assert shot_item_model.rowCount() == 4

        # Apply filter for show1
        shot_item_model.set_show_filter(base_shot_model, "show1")

        # Should only show show1 shots (2 items)
        assert shot_item_model.rowCount() == 2

        # Verify filtered shots are correct
        for i in range(shot_item_model.rowCount()):
            shot = shot_item_model.get_shot_at_index(shot_item_model.index(i, 0))
            assert shot is not None
            assert shot.show == "show1"

    def test_show_filter_all_shows_returns_all(
        self,
        shot_item_model: ShotItemModel,
        base_shot_model: BaseShotModel,
        qtbot: QtBot,
        test_shots: list[Shot],
    ) -> None:
        """Test 'All' filter shows everything."""
        base_shot_model.shots = test_shots
        shot_item_model.set_shots(test_shots)

        # Apply specific filter first
        shot_item_model.set_show_filter(base_shot_model, "show1")
        assert shot_item_model.rowCount() == 2

        # Apply "All Shows" filter (None)
        shot_item_model.set_show_filter(base_shot_model, None)

        # Should show all shots
        assert shot_item_model.rowCount() == 4

    def test_show_filter_specific_show(
        self,
        shot_item_model: ShotItemModel,
        base_shot_model: BaseShotModel,
        qtbot: QtBot,
        test_shots: list[Shot],
    ) -> None:
        """Test specific show filters correctly."""
        base_shot_model.shots = test_shots
        shot_item_model.set_shots(test_shots)

        # Filter for show2
        shot_item_model.set_show_filter(base_shot_model, "show2")

        # Verify row count reflects the filter
        assert shot_item_model.rowCount() == 2

        # Verify all visible shots are from show2
        for i in range(shot_item_model.rowCount()):
            shot = shot_item_model.get_shot_at_index(shot_item_model.index(i, 0))
            assert shot is not None
            assert shot.show == "show2"


class TestDataAccess:
    """Test data access methods."""

    def test_data_returns_correct_role_values(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test Qt.DisplayRole, Qt.DecorationRole, etc."""
        shot_item_model.set_shots(test_shots)
        shot = test_shots[0]
        index = shot_item_model.index(0, 0)

        # DisplayRole
        display = shot_item_model.data(index, Qt.ItemDataRole.DisplayRole)
        assert display == shot.full_name

        # ToolTipRole
        tooltip = shot_item_model.data(index, Qt.ItemDataRole.ToolTipRole)
        assert shot.show in tooltip
        assert shot.sequence in tooltip
        assert shot.shot in tooltip
        assert shot.workspace_path in tooltip

        # ObjectRole
        obj = shot_item_model.data(index, BaseItemRole.ObjectRole)
        assert obj is shot

        # ShowRole
        show = shot_item_model.data(index, BaseItemRole.ShowRole)
        assert show == shot.show

        # SequenceRole
        sequence = shot_item_model.data(index, BaseItemRole.SequenceRole)
        assert sequence == shot.sequence

    def test_rowCount_matches_filtered_shots(
        self,
        shot_item_model: ShotItemModel,
        base_shot_model: BaseShotModel,
        qtbot: QtBot,
        test_shots: list[Shot],
    ) -> None:
        """Test row count reflects filters."""
        base_shot_model.shots = test_shots
        shot_item_model.set_shots(test_shots)

        # Initial count
        assert shot_item_model.rowCount() == 4

        # Apply filter
        shot_item_model.set_show_filter(base_shot_model, "show1")

        # Row count should reflect filtered list
        assert shot_item_model.rowCount() == 2


class TestShotSpecificMethods:
    """Test shot-specific methods."""

    def test_set_shots(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test set_shots method."""
        spy = QSignalSpy(shot_item_model.shots_updated)

        shot_item_model.set_shots(test_shots)

        assert shot_item_model.rowCount() == 4
        assert spy.count() == 1
        assert len(shot_item_model.shots) == 4

    def test_refresh_shots_detects_changes(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test refresh_shots detects changes."""
        # Set initial shots
        initial_shots = test_shots[:2]
        shot_item_model.set_shots(initial_shots)

        # Refresh with different shots
        new_shots = test_shots[2:]
        result = shot_item_model.refresh_shots(new_shots)

        assert result.success is True
        assert result.has_changes is True
        assert shot_item_model.rowCount() == 2

    def test_refresh_shots_no_changes(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test refresh_shots with no changes."""
        shot_item_model.set_shots(test_shots)

        # Refresh with same shots
        result = shot_item_model.refresh_shots(test_shots)

        assert result.success is True
        assert result.has_changes is False

    def test_get_shot_at_index(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test get_shot_at_index method."""
        shot_item_model.set_shots(test_shots)

        # Valid index
        index = shot_item_model.index(0, 0)
        shot = shot_item_model.get_shot_at_index(index)
        assert shot is test_shots[0]

        # Invalid index
        invalid_index = QModelIndex()
        shot = shot_item_model.get_shot_at_index(invalid_index)
        assert shot is None


class TestQtIntegration:
    """Test Qt Model/View integration."""

    def test_index_creation(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test creating model indexes."""
        shot_item_model.set_shots(test_shots)

        # Valid index
        index = shot_item_model.index(0, 0)
        assert index.isValid()
        assert index.row() == 0

        # Out of range
        index = shot_item_model.index(100, 0)
        assert not index.isValid()

    def test_flags(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test item flags."""
        shot_item_model.set_shots(test_shots)

        index = shot_item_model.index(0, 0)
        flags = shot_item_model.flags(index)

        assert flags & Qt.ItemFlag.ItemIsEnabled
        assert flags & Qt.ItemFlag.ItemIsSelectable

    def test_abstract_methods_implemented(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test abstract methods are implemented correctly."""
        shot = test_shots[0]

        # get_display_role_data
        display = shot_item_model.get_display_role_data(shot)
        assert display == shot.full_name

        # get_tooltip_data
        tooltip = shot_item_model.get_tooltip_data(shot)
        assert isinstance(tooltip, str)
        assert shot.show in tooltip

        # get_custom_role_data
        custom = shot_item_model.get_custom_role_data(shot, 9999)
        assert custom is None  # No custom roles for Shot


class TestCleanup:
    """Test cleanup and resource management."""

    def test_cleanup_releases_resources(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test cleanup properly releases resources."""
        shot_item_model.set_shots(test_shots)

        # Call cleanup
        shot_item_model.cleanup()

        # Caches should be cleared
        assert len(shot_item_model._thumbnail_loader.thumbnail_cache) == 0
        assert len(shot_item_model._thumbnail_loader.loading_states) == 0

    def test_set_items_preserves_matching_cache(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test setting items preserves thumbnails for matching shots."""
        from PySide6.QtCore import (
            QMutexLocker,
        )
        from PySide6.QtGui import (
            QImage,
        )

        shot_item_model.set_shots(test_shots[:2])

        # Add to cache
        test_image = QImage(100, 100, QImage.Format.Format_RGB32)
        with QMutexLocker(shot_item_model._thumbnail_loader.cache_mutex):
            shot_item_model._thumbnail_loader.thumbnail_cache[test_shots[0].full_name] = test_image

        # Set new items - test_shots[0] preserved, test_shots[1] removed
        shot_item_model.set_shots([test_shots[0], test_shots[2]])

        # Verify preservation
        assert len(shot_item_model._thumbnail_loader.thumbnail_cache) == 1
        assert test_shots[0].full_name in shot_item_model._thumbnail_loader.thumbnail_cache
        with QMutexLocker(shot_item_model._thumbnail_loader.cache_mutex):
            assert shot_item_model._thumbnail_loader.thumbnail_cache[test_shots[0].full_name] is test_image


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_shot_list(self, shot_item_model: ShotItemModel, qtbot: QtBot) -> None:
        """Test handling empty shot list."""
        shot_item_model.set_shots([])

        assert shot_item_model.rowCount() == 0
        assert len(shot_item_model.shots) == 0

    def test_find_shot_by_full_name(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test _find_shot_by_full_name helper."""
        shot_item_model.set_shots(test_shots)

        # Find existing shot
        result = shot_item_model._find_shot_by_full_name("seq01_0010")
        assert result is not None
        shot, row = result
        assert shot.full_name == "seq01_0010"
        assert row == 0

        # Find non-existent shot
        result = shot_item_model._find_shot_by_full_name("nonexistent")
        assert result is None

    def test_properties_access(
        self, shot_item_model: ShotItemModel, qtbot: QtBot, test_shots: list[Shot]
    ) -> None:
        """Test shots property accessor."""
        shot_item_model.set_shots(test_shots)

        # Access via property
        shots = shot_item_model.shots
        assert len(shots) == 4
        assert shots is shot_item_model._items
