"""Unit tests for BaseItemModel - base Qt Model/View implementation.

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real components (CacheManager with tmp_path)
- Use QSignalSpy for signal testing
- Test doubles for system boundaries
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QSignalSpy

from config import Config
from type_definitions import Shot
from ui.base_item_model import BaseItemModel, BaseItemRole


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


# Concrete implementation for testing abstract base class
class ConcreteTestModel(BaseItemModel[Shot]):
    """Minimal concrete implementation for testing BaseItemModel."""

    def get_display_role_data(self, item: Shot) -> str:
        """Get display text for an item."""
        return item.full_name

    def get_tooltip_data(self, item: Shot) -> str:
        """Get tooltip text for an item."""
        return f"{item.show}/{item.sequence}/{item.shot}"


class TestBaseItemModelInitialization:
    """Test BaseItemModel initialization behavior."""

    def test_initialization_default(self, qapp: QApplication) -> None:
        """Test default initialization creates cache manager."""
        model = ConcreteTestModel()

        assert model.rowCount() == 0
        assert model._cache_manager is not None

    def test_initialization_requires_main_thread(self, qapp: QApplication) -> None:
        """Test that model creation fails outside main thread."""
        from threading import (
            Thread,
        )

        error_occurred = False

        def create_model() -> None:
            nonlocal error_occurred
            try:
                ConcreteTestModel()
            except RuntimeError as e:
                if "main thread" in str(e):
                    error_occurred = True

        thread = Thread(target=create_model)
        thread.start()
        thread.join(timeout=5.0)
        assert not thread.is_alive(), \
            "Thread failed to complete within 5 seconds (possible deadlock)"

        assert error_occurred


class TestRowCount:
    """Test rowCount() method."""

    def test_with_items(self, qapp: QApplication) -> None:
        """Test row count with items."""
        model = ConcreteTestModel()
        shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]
        model.set_items(shots)

        assert model.rowCount() == 2

    def test_invalid_parent(self, qapp: QApplication) -> None:
        """Test row count returns 0 for valid parent (list models have no children)."""
        model = ConcreteTestModel()
        shots = [Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")]
        model.set_items(shots)

        # List models return 0 for any valid parent
        parent = model.index(0, 0)
        assert model.rowCount(parent) == 0


class TestDataMethod:
    """Test data() method for various roles."""

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            (Qt.ItemDataRole.DisplayRole, "seq01_0010"),
            (Qt.ItemDataRole.ToolTipRole, "TEST/seq01/0010"),
            (BaseItemRole.ObjectRole, None),  # sentinel: identity check below
            (BaseItemRole.ShowRole, "TEST"),
            (BaseItemRole.SequenceRole, "seq01"),
            (BaseItemRole.FullNameRole, "seq01_0010"),
            (BaseItemRole.WorkspacePathRole, f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            (BaseItemRole.LoadingStateRole, "idle"),
        ],
        ids=[
            "DisplayRole",
            "TooltipRole",
            "ObjectRole",
            "ShowRole",
            "SequenceRole",
            "FullNameRole",
            "WorkspacePathRole",
            "LoadingStateRole",
        ],
    )
    def test_role_data(self, qapp: QApplication, role: object, expected: object) -> None:
        """Test data() returns correct value for each role."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = model.index(0, 0)
        data = model.data(index, role)  # type: ignore[arg-type]

        if role is BaseItemRole.ObjectRole:
            assert data is shot
        else:
            assert data == expected

    def test_size_hint_role(self, qapp: QApplication) -> None:
        """Test SizeHintRole returns QSize."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = model.index(0, 0)
        data = model.data(index, Qt.ItemDataRole.SizeHintRole)

        assert isinstance(data, QSize)
        assert data.width() > 0
        assert data.height() > 0

    @pytest.mark.parametrize(
        "make_index",
        [
            pytest.param(lambda _m: QModelIndex(), id="invalid_index"),
            pytest.param(lambda _m: _m.index(10, 0), id="out_of_range_index"),
        ],
    )
    def test_data_returns_none_for_bad_index(
        self, qapp: QApplication, make_index: object
    ) -> None:
        """Test data() returns None for invalid or out-of-range index."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = make_index(model)  # type: ignore[operator]
        data = model.data(index, Qt.ItemDataRole.DisplayRole)

        assert data is None


class TestFlags:
    """Test flags() method."""

    def test_valid_index(self, qapp: QApplication) -> None:
        """Test flags for valid index."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = model.index(0, 0)
        flags = model.flags(index)

        assert flags & Qt.ItemFlag.ItemIsEnabled
        assert flags & Qt.ItemFlag.ItemIsSelectable

    def test_invalid_index(self, qapp: QApplication) -> None:
        """Test flags for invalid index."""
        model = ConcreteTestModel()
        flags = model.flags(QModelIndex())

        assert flags == Qt.ItemFlag.NoItemFlags


class TestSetData:
    """Test setData() method."""

    def test_set_loading_state(self, qapp: QApplication) -> None:
        """Test setting loading state."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = model.index(0, 0)
        result = model.setData(index, "loading", BaseItemRole.LoadingStateRole)

        assert result is True
        assert model.data(index, BaseItemRole.LoadingStateRole) == "loading"

class TestVisibleRange:
    """Test visible range and lazy loading."""

    def test_set_visible_range(self, qapp: QApplication) -> None:
        """Test setting visible range."""
        model = ConcreteTestModel()
        shots = [
            Shot("TEST", "seq01", f"{i:04d}", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_{i:04d}")
            for i in range(10, 60, 10)
        ]
        model.set_items(shots)

        model.set_visible_range(1, 3)

        assert model._visible_start == 1
        assert model._visible_end == 3

    def test_visible_range_clamps_to_bounds(self, qapp: QApplication) -> None:
        """Test visible range clamps to item bounds."""
        model = ConcreteTestModel()
        shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]
        model.set_items(shots)

        model.set_visible_range(-5, 100)

        assert model._visible_start == 0
        assert model._visible_end == 1

    def test_visible_range_empty_items(self, qapp: QApplication) -> None:
        """Test visible range with empty items."""
        model = ConcreteTestModel()

        model.set_visible_range(0, 10)

        assert model._visible_start == 0
        assert model._visible_end == 0


class TestThumbnailCache:
    """Test thumbnail caching functionality."""

    def test_clear_thumbnail_cache(self, qapp: QApplication) -> None:
        """Test clearing thumbnail cache."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        # Add to cache
        model._thumbnail_loader.thumbnail_cache[shot.full_name] = QImage()
        model._thumbnail_loader.loading_states[shot.full_name] = "loaded"

        model.clear_thumbnail_cache()

        assert len(model._thumbnail_loader.thumbnail_cache) == 0
        assert len(model._thumbnail_loader.loading_states) == 0

    def test_get_thumbnail_pixmap_cached(self, qapp: QApplication) -> None:
        """Test getting cached thumbnail pixmap."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        # Create and cache a QImage
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.red)
        model._thumbnail_loader.thumbnail_cache[shot.full_name] = image

        pixmap = model._get_thumbnail_pixmap(shot)

        assert isinstance(pixmap, QPixmap)
        assert not pixmap.isNull()

    def test_get_thumbnail_pixmap_not_cached(self, qapp: QApplication) -> None:
        """Test getting thumbnail pixmap when not cached."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        pixmap = model._get_thumbnail_pixmap(shot)

        assert pixmap is None


class TestSetItems:
    """Test set_items() method."""

    def test_set_items(self, qapp: QApplication, qtbot: QtBot) -> None:
        """Test setting items emits signal."""
        model = ConcreteTestModel()
        spy = QSignalSpy(model.items_updated)

        shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]
        model.set_items(shots)

        assert model.rowCount() == 2
        assert spy.count() == 1

    def test_set_items_preserves_matching_thumbnails(self, qapp: QApplication) -> None:
        """Test setting items preserves thumbnails for items still present."""
        model = ConcreteTestModel()
        shot1 = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        shot2 = Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020")
        model.set_items([shot1, shot2])

        # Add to cache (using QImage, not QPixmap)
        image1 = QImage(100, 100, QImage.Format.Format_RGB888)
        image2 = QImage(100, 100, QImage.Format.Format_RGB888)
        model._thumbnail_loader.thumbnail_cache[shot1.full_name] = image1
        model._thumbnail_loader.thumbnail_cache[shot2.full_name] = image2

        # Set new items - shot1 preserved, shot2 removed
        shot3 = Shot("TEST", "seq02", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq02/seq02_0010")
        model.set_items([shot1, shot3])

        # Verify preservation
        assert len(model._thumbnail_loader.thumbnail_cache) == 1
        assert shot1.full_name in model._thumbnail_loader.thumbnail_cache
        assert model._thumbnail_loader.thumbnail_cache[shot1.full_name] is image1  # Same object
        assert shot2.full_name not in model._thumbnail_loader.thumbnail_cache

    def test_set_items_initializes_visible_range(self, qapp: QApplication) -> None:
        """Test setting items initializes visible range for thumbnail loading.

        Critical behavior: When items are set, _visible_end must be initialized
        to len(items) - 1 to trigger thumbnail loading for all items.
        This fixes the bug where thumbnails only loaded in Previous Shots tab.
        """
        model = ConcreteTestModel()

        # Initial state
        assert model._visible_start == 0
        assert model._visible_end == 0

        # Set items
        shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
            Shot("TEST", "seq01", "0030", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0030"),
        ]
        model.set_items(shots)

        # Verify visible range is initialized to cover all items
        assert model._visible_end == 2  # len(shots) - 1
        assert model._visible_start == 0  # Unchanged

    def test_set_items_empty_list_no_thumbnail_load(
        self, qapp: QApplication, qtbot: QtBot
    ) -> None:
        """Test setting empty items list doesn't trigger thumbnail loading.

        Edge case: Empty items should not schedule thumbnail loading.
        """
        model = ConcreteTestModel()

        # Set empty list
        model.set_items([])

        # Minimal wait to ensure no timers fire unexpectedly
        qtbot.wait(1)

        # Verify no thumbnail loading was triggered
        assert model._visible_end == 0  # No change from initial
        assert len(model._thumbnail_loader.loading_states) == 0  # No loading attempted

    def test_set_items_loads_only_initial_visible_count(
        self, qapp: QApplication, qtbot: QtBot
    ) -> None:
        """Test that set_items only schedules loading for first 30 items.

        Issue #4 fix: Prevents loading all 106 thumbnails on startup.
        Instead loads min(30, item_count) initially.
        """
        import tempfile
        from pathlib import Path

        from cache.thumbnail_cache import ThumbnailCache

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_manager = ThumbnailCache(Path(tmp_dir))
            model = ConcreteTestModel(cache_manager=cache_manager)

            # Create 106 shots (typical user count from issue report)
            shots = [
                Shot(
                    show=f"show{i}",
                    sequence=f"seq{i % 10:02d}",
                    shot=f"{i:04d}",
                    workspace_path=f"{Config.SHOWS_ROOT}/show{i}/shots/seq{i % 10:02d}/seq{i % 10:02d}_{i:04d}",
                )
                for i in range(106)
            ]

            model.set_items(shots)

            # Check that visible_end is set to 29 (first 30 items, 0-indexed)
            # NOT 105 (all 106 items)
            assert (
                model._visible_end == 29
            ), f"Expected visible_end=29 for initial load, got {model._visible_end}"

            # Verify the log message mentions loading 30 items, not 106
            # (This is a behavior verification - the visible range should be limited)

    def test_set_items_thumbnail_load_with_cache_manager(
        self, qapp: QApplication, qtbot: QtBot, tmp_path
    ) -> None:
        """Test thumbnail loading works with real CacheManager.

        Integration test: Verifies the complete thumbnail loading flow
        when a CacheManager is provided.
        """
        from cache.thumbnail_cache import ThumbnailCache

        # Create cache manager with temp directory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_manager = ThumbnailCache(cache_dir)

        model = ConcreteTestModel(cache_manager=cache_manager)

        # Create test shots (workspace paths don't need to exist)
        shots = [
            Shot("TEST", "seq01", "0010", "/nonexistent/path1"),
            Shot("TEST", "seq01", "0020", "/nonexistent/path2"),
        ]

        # Set items
        model.set_items(shots)

        # Wait for thumbnail loading timer to fire
        qtbot.waitUntil(
            lambda: len(model._thumbnail_loader.loading_states) > 0,
            timeout=500
        )

        # Verify thumbnail loading was attempted
        # With real CacheManager, states will be set (loading or failed)
        assert len(model._thumbnail_loader.loading_states) >= 2

        # Verify visible range was set correctly
        assert model._visible_end == 1  # len(shots) - 1


class TestGetItemAtIndex:
    """Test get_item_at_index() method."""

    def test_valid_index(self, qapp: QApplication) -> None:
        """Test getting item at valid index."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = model.index(0, 0)
        item = model.get_item_at_index(index)

        assert item is shot

    @pytest.mark.parametrize(
        "make_index",
        [
            pytest.param(lambda _m: QModelIndex(), id="invalid_index"),
            pytest.param(lambda _m: _m.index(10, 0), id="out_of_range_index"),
        ],
    )
    def test_get_item_returns_none_for_bad_index(
        self, qapp: QApplication, make_index: object
    ) -> None:
        """Test get_item_at_index returns None for invalid or out-of-range index."""
        model = ConcreteTestModel()
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        model.set_items([shot])

        index = make_index(model)  # type: ignore[operator]
        item = model.get_item_at_index(index)

        assert item is None






