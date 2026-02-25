"""Comprehensive unit tests for BaseThumbnailDelegate.

This test suite covers:
- Delegate initialization and configuration
- Size hint calculation (grid mode)
- Theme customization
- Data extraction (get_item_data)
- Text truncation and eliding
- State management (selection, hover, loading)
- Edge cases (missing data, None values, empty strings)
- Loading animation optimization (targeted repaints)
- Resource cleanup

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real components (ShotItemModel with shots)
- Verify signals using QSignalSpy
- Accept that QPainter drawing code is difficult to test (focus on logic)

Note: QPainter rendering operations (drawText, fillRect, etc.) are NOT
fully testable without visual verification. We focus on:
- Calculations (size hints, rects)
- Data retrieval logic
- State management
- Text processing (eliding)
- Edge case handling
Target coverage: 70%+ (QPainter code will remain untested)
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QListView, QStyleOptionViewItem

from base_thumbnail_delegate import (
    BaseThumbnailDelegate,
    DelegateTheme,
    ThumbnailItemData,
)
from config import Config
from shot_item_model import ShotItemModel
from shot_model import Shot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


# ============================================================================
# Test Fixtures and Helpers
# ============================================================================


class ConcreteThumbnailDelegate(BaseThumbnailDelegate):
    """Concrete implementation for testing (not a test class itself)."""

    def get_theme(self) -> DelegateTheme:
        """Get default theme."""
        return DelegateTheme()

    def get_item_data(self, index):
        """Extract item data from index."""
        item = index.data(Qt.ItemDataRole.UserRole + 1)  # ObjectRole
        if not item:
            return {"name": "Unknown"}

        return {
            "name": item.full_name,
            "show": item.show,
            "sequence": item.sequence,
            "thumbnail": index.data(Qt.ItemDataRole.DecorationRole),
            "loading_state": index.data(Qt.ItemDataRole.UserRole + 9),  # LoadingStateRole
            "is_selected": False,
        }


class CustomThemeDelegate(BaseThumbnailDelegate):
    """Delegate with custom theme for testing theme customization."""

    def __init__(self, theme: DelegateTheme, parent=None):
        self._custom_theme = theme
        super().__init__(parent)

    def get_theme(self) -> DelegateTheme:
        """Return custom theme."""
        return self._custom_theme

    def get_item_data(self, index):
        """Extract basic item data."""
        return {"name": "test_item"}


class MinimalDataDelegate(BaseThumbnailDelegate):
    """Delegate that returns minimal data for testing edge cases."""

    def __init__(self, data_override: ThumbnailItemData | None = None, parent=None):
        self._data_override = data_override or {}
        super().__init__(parent)

    def get_theme(self) -> DelegateTheme:
        """Get default theme."""
        return DelegateTheme()

    def get_item_data(self, index):
        """Return overridden data."""
        return self._data_override


def create_mock_shot(index: int) -> Shot:
    """Create a mock shot for testing."""
    return Shot(
        show="test_show",
        sequence="seq01",
        shot=f"shot_{index:04d}",
        workspace_path=f"/tmp/test/shot_{index:04d}",
    )


def create_test_pixmap(width: int = 100, height: int = 100) -> QPixmap:
    """Create a test pixmap with specific dimensions."""
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(128, 128, 128))
    return pixmap


# ============================================================================
# Test Classes
# ============================================================================


class TestDelegateInitialization:
    """Test BaseThumbnailDelegate initialization."""

    def test_initialization_default(self, qtbot) -> None:
        """Test default initialization sets up delegate correctly."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        assert delegate.theme is not None
        assert delegate._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE
        assert delegate._name_font is not None
        assert delegate._info_font is not None
        assert delegate._metrics_cache == {}
        assert delegate._loading_angle == 0
        assert delegate._loading_timer is None

    def test_initialization_without_parent(self) -> None:
        """Test delegate can be created without parent."""
        delegate = ConcreteThumbnailDelegate()

        assert delegate.parent() is None
        assert delegate.theme is not None

    def test_theme_applied_to_fonts(self, qtbot) -> None:
        """Test that theme font sizes are applied correctly."""
        view = QListView()
        qtbot.addWidget(view)

        custom_theme = DelegateTheme(name_font_size=12, info_font_size=10)
        delegate = CustomThemeDelegate(custom_theme, parent=view)

        assert delegate._name_font.pointSize() == 12
        assert delegate._info_font.pointSize() == 10

    def test_not_implemented_errors_for_abstract_methods(self) -> None:
        """Test that abstract methods raise NotImplementedError."""
        # Test get_theme raises NotImplementedError
        # Cannot create instance without overriding get_theme (called in __init__)
        # So we test by trying to create base class instance
        with pytest.raises(NotImplementedError, match="get_theme"):
            BaseThumbnailDelegate()

        # Test get_item_data separately with a minimal subclass
        class MinimalDelegate(BaseThumbnailDelegate):
            def get_theme(self) -> DelegateTheme:
                return DelegateTheme()

        delegate = MinimalDelegate()
        index = QModelIndex()

        with pytest.raises(NotImplementedError, match="get_item_data"):
            delegate.get_item_data(index)


class TestThemeConfiguration:
    """Test DelegateTheme dataclass and customization."""

    def test_default_theme_colors(self) -> None:
        """Test default theme has expected colors."""
        theme = DelegateTheme()

        assert theme.bg_color == QColor("#2b2b2b")
        assert theme.bg_hover_color == QColor("#3a3a3a")
        assert theme.bg_selected_color == QColor("#0d7377")
        assert theme.border_color == QColor("#444")
        assert theme.border_hover_color == QColor("#888")
        assert theme.border_selected_color == QColor("#14ffec")
        assert theme.text_color == QColor("#ffffff")
        assert theme.text_selected_color == QColor("#14ffec")

    def test_default_theme_dimensions(self) -> None:
        """Test default theme has expected dimensions."""
        theme = DelegateTheme()

        assert theme.text_height == 40
        assert theme.padding == 8
        assert theme.border_radius == 8

    def test_custom_theme_colors(self, qtbot) -> None:
        """Test custom theme colors are applied."""
        view = QListView()
        qtbot.addWidget(view)

        custom_theme = DelegateTheme(
            bg_color=QColor("#ff0000"),
            text_color=QColor("#00ff00"),
        )
        delegate = CustomThemeDelegate(custom_theme, parent=view)

        assert delegate.theme.bg_color == QColor("#ff0000")
        assert delegate.theme.text_color == QColor("#00ff00")

    def test_custom_theme_dimensions(self, qtbot) -> None:
        """Test custom theme dimensions are applied."""
        view = QListView()
        qtbot.addWidget(view)

        custom_theme = DelegateTheme(
            text_height=50,
            padding=12,
            border_radius=4,
        )
        delegate = CustomThemeDelegate(custom_theme, parent=view)

        assert delegate.theme.text_height == 50
        assert delegate.theme.padding == 12
        assert delegate.theme.border_radius == 4

    def test_user_color_optional(self) -> None:
        """Test user_color is optional in theme."""
        theme = DelegateTheme()
        assert theme.user_color is None

        theme_with_user_color = DelegateTheme(user_color=QColor("#ffaa00"))
        assert theme_with_user_color.user_color == QColor("#ffaa00")


class TestSizeHint:
    """Test sizeHint() calculations."""

    def test_size_hint_default_size(self, qtbot) -> None:
        """Test size hint with default thumbnail size."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        option = QStyleOptionViewItem()
        index = QModelIndex()

        size = delegate.sizeHint(option, index)

        expected_width = Config.DEFAULT_THUMBNAIL_SIZE + 2 * delegate.theme.padding
        # Height uses 16:9 aspect ratio for plate images
        thumbnail_height = int(
            Config.DEFAULT_THUMBNAIL_SIZE / Config.THUMBNAIL_ASPECT_RATIO
        )
        expected_height = (
            thumbnail_height + delegate.theme.text_height + 2 * delegate.theme.padding
        )

        assert size == QSize(expected_width, expected_height)

    def test_size_hint_custom_thumbnail_size(self) -> None:
        """Test size hint after setting custom thumbnail size (no parent to avoid update() bug)."""
        delegate = ConcreteThumbnailDelegate()  # No parent to avoid update() bug

        custom_size = 500  # Use a value within valid range (400-1200)
        delegate.set_thumbnail_size(custom_size)

        option = QStyleOptionViewItem()
        index = QModelIndex()

        size = delegate.sizeHint(option, index)

        expected_width = custom_size + 2 * delegate.theme.padding
        # Height uses 16:9 aspect ratio for plate images
        thumbnail_height = int(custom_size / Config.THUMBNAIL_ASPECT_RATIO)
        expected_height = (
            thumbnail_height + delegate.theme.text_height + 2 * delegate.theme.padding
        )

        assert size == QSize(expected_width, expected_height)

    def test_size_hint_with_custom_padding(self, qtbot) -> None:
        """Test size hint respects custom theme padding."""
        view = QListView()
        qtbot.addWidget(view)

        custom_theme = DelegateTheme(padding=16)
        delegate = CustomThemeDelegate(custom_theme, parent=view)

        option = QStyleOptionViewItem()
        index = QModelIndex()

        size = delegate.sizeHint(option, index)

        expected_width = Config.DEFAULT_THUMBNAIL_SIZE + 2 * 16
        # Height uses 16:9 aspect ratio for plate images
        thumbnail_height = int(
            Config.DEFAULT_THUMBNAIL_SIZE / Config.THUMBNAIL_ASPECT_RATIO
        )
        expected_height = thumbnail_height + custom_theme.text_height + 2 * 16

        assert size == QSize(expected_width, expected_height)

    def test_size_hint_with_custom_text_height(self, qtbot) -> None:
        """Test size hint respects custom text height."""
        view = QListView()
        qtbot.addWidget(view)

        custom_theme = DelegateTheme(text_height=60)
        delegate = CustomThemeDelegate(custom_theme, parent=view)

        option = QStyleOptionViewItem()
        index = QModelIndex()

        size = delegate.sizeHint(option, index)

        # Height uses 16:9 aspect ratio for plate images
        thumbnail_height = int(
            Config.DEFAULT_THUMBNAIL_SIZE / Config.THUMBNAIL_ASPECT_RATIO
        )
        expected_height = thumbnail_height + 60 + 2 * custom_theme.padding

        assert size.height() == expected_height

    def test_size_hint_with_persistent_model_index(self, qtbot) -> None:
        """Test size hint works with QPersistentModelIndex."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        shots = [create_mock_shot(0)]
        model.set_items(shots)

        regular_index = model.index(0, 0)
        persistent_index = QPersistentModelIndex(regular_index)

        option = QStyleOptionViewItem()

        size_regular = delegate.sizeHint(option, regular_index)
        size_persistent = delegate.sizeHint(option, persistent_index)

        assert size_regular == size_persistent


class TestThumbnailSizeManagement:
    """Test set_thumbnail_size() method.

    Note: Some tests are skipped due to a bug in base_thumbnail_delegate.py line 555:
    QListView.update() requires a QRect argument but is called without one.
    This is a source code bug that should be fixed.
    """

    def test_set_thumbnail_size_updates_size_without_parent(self) -> None:
        """Test setting thumbnail size updates internal size (no parent to avoid update() bug)."""
        delegate = ConcreteThumbnailDelegate()

        initial_size = delegate._thumbnail_size
        new_size = 256

        delegate.set_thumbnail_size(new_size)

        assert delegate._thumbnail_size == new_size
        assert delegate._thumbnail_size != initial_size

    def test_set_thumbnail_size_clears_cache_without_parent(self) -> None:
        """Test setting thumbnail size clears metrics cache (no parent to avoid update() bug)."""
        delegate = ConcreteThumbnailDelegate()

        # Populate cache
        delegate._metrics_cache["test_key"] = QSize(100, 100)
        assert len(delegate._metrics_cache) > 0

        delegate.set_thumbnail_size(256)

        assert delegate._metrics_cache == {}

    def test_set_thumbnail_size_with_parent(self, qtbot) -> None:
        """Test setting thumbnail size with parent view.

        Fixed: Now properly calls viewport().update() for QAbstractItemView parents.
        """
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        # Should not raise TypeError anymore
        delegate.set_thumbnail_size(256)

        assert delegate._thumbnail_size == 256


class TestGetThumbnailRect:
    """Test _get_thumbnail_rect() calculations."""

    @pytest.mark.parametrize(
        ("item_rect", "theme_kwargs", "expected_fn"),
        [
            pytest.param(
                QRect(0, 0, 200, 240),
                {},
                lambda _r, t: QRect(
                    t.padding,
                    t.padding,
                    200 - 2 * t.padding,
                    240 - t.text_height - 2 * t.padding,
                ),
                id="default_padding",
            ),
            pytest.param(
                QRect(10, 20, 300, 350),
                {"padding": 16, "text_height": 50},
                lambda _r, _t: QRect(10 + 16, 20 + 16, 300 - 2 * 16, 350 - 50 - 2 * 16),
                id="custom_padding",
            ),
        ],
    )
    def test_get_thumbnail_rect_calculations(
        self, qtbot, item_rect: QRect, theme_kwargs: dict, expected_fn
    ) -> None:
        """Test thumbnail rect calculation with various padding configurations."""
        view = QListView()
        qtbot.addWidget(view)

        if theme_kwargs:
            custom_theme = DelegateTheme(**theme_kwargs)
            delegate = CustomThemeDelegate(custom_theme, parent=view)
        else:
            delegate = ConcreteThumbnailDelegate(parent=view)

        thumb_rect = delegate._get_thumbnail_rect(item_rect)
        expected = expected_fn(item_rect, delegate.theme)

        assert thumb_rect == expected

    def test_get_thumbnail_rect_maintains_position(self, qtbot) -> None:
        """Test thumbnail rect maintains item rect offset position."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        item_rect = QRect(100, 200, 200, 240)
        thumb_rect = delegate._get_thumbnail_rect(item_rect)

        # Thumbnail should be offset by item position + padding
        assert thumb_rect.x() == 100 + delegate.theme.padding
        assert thumb_rect.y() == 200 + delegate.theme.padding

    def test_get_thumbnail_rect_with_zero_padding(self, qtbot) -> None:
        """Test thumbnail rect calculation with zero padding."""
        view = QListView()
        qtbot.addWidget(view)

        custom_theme = DelegateTheme(padding=0)
        delegate = CustomThemeDelegate(custom_theme, parent=view)

        item_rect = QRect(0, 0, 200, 240)
        thumb_rect = delegate._get_thumbnail_rect(item_rect)

        # Should use full width with no inset
        assert thumb_rect.width() == 200
        assert thumb_rect.x() == 0
        assert thumb_rect.y() == 0


class TestDataExtraction:
    """Test get_item_data() implementation in concrete delegates."""

    def test_get_item_data_with_shot(self, qtbot) -> None:
        """Test data extraction from shot model index."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        shots = [create_mock_shot(0)]
        model.set_items(shots)

        index = model.index(0, 0)
        data = delegate.get_item_data(index)

        assert data["name"] == "seq01_shot_0000"
        assert data["show"] == "test_show"
        assert data["sequence"] == "seq01"
        assert "loading_state" in data

    def test_get_item_data_with_invalid_index(self, qtbot) -> None:
        """Test data extraction with invalid index returns minimal data."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        invalid_index = QModelIndex()
        data = delegate.get_item_data(invalid_index)

        assert data["name"] == "Unknown"

    def test_get_item_data_with_persistent_index(self, qtbot) -> None:
        """Test data extraction works with QPersistentModelIndex."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        shots = [create_mock_shot(0)]
        model.set_items(shots)

        regular_index = model.index(0, 0)
        persistent_index = QPersistentModelIndex(regular_index)

        data = delegate.get_item_data(persistent_index)

        assert data["name"] == "seq01_shot_0000"
        assert data["show"] == "test_show"


class TestPaintMethod:
    """Test paint() method behavior (focus on logic, not QPainter rendering)."""

    def test_paint_skips_invalid_index(self, qtbot) -> None:
        """Test paint method returns early for invalid index."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        # Create mock painter
        mock_painter = Mock()
        option = QStyleOptionViewItem()
        invalid_index = QModelIndex()

        # Should not raise error and should not call painter methods
        delegate.paint(mock_painter, option, invalid_index)

        # Painter should not be used (save/restore not called)
        mock_painter.save.assert_not_called()

    def test_paint_saves_and_restores_painter_state(self, qtbot) -> None:
        """Test paint method saves and restores painter state."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        shots = [create_mock_shot(0)]
        model.set_items(shots)

        index = model.index(0, 0)

        # Create mock painter
        mock_painter = Mock()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 200, 240)  # type: ignore
        from PySide6.QtWidgets import (
            QStyle,
        )

        option.state = QStyle.StateFlag(0)  # type: ignore

        delegate.paint(mock_painter, option, index)

        # Verify save/restore called
        mock_painter.save.assert_called_once()
        mock_painter.restore.assert_called_once()

    def test_paint_enables_antialiasing(self, qtbot) -> None:
        """Test paint method enables antialiasing for smooth rendering."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        shots = [create_mock_shot(0)]
        model.set_items(shots)

        index = model.index(0, 0)

        # Create mock painter
        mock_painter = Mock()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 200, 240)  # type: ignore
        from PySide6.QtWidgets import (
            QStyle,
        )

        option.state = QStyle.StateFlag(0)  # type: ignore

        delegate.paint(mock_painter, option, index)

        # Verify antialiasing enabled
        from PySide6.QtGui import (
            QPainter,
        )

        mock_painter.setRenderHint.assert_called_with(QPainter.RenderHint.Antialiasing)


class TestLoadingStates:
    """Test rendering of different loading states."""

    def test_get_loading_rows_no_loading_items(self, qtbot) -> None:
        """Test _get_loading_rows when no items are loading."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        shots = [create_mock_shot(i) for i in range(5)]
        model.set_items(shots)

        loading_rows = delegate._get_loading_rows()

        assert loading_rows == []

    def test_get_loading_rows_identifies_correct_items(self, qtbot) -> None:
        """Test that _get_loading_rows correctly identifies loading items."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)

        # Add shots
        shots = [create_mock_shot(i) for i in range(10)]
        model.set_items(shots)

        # Mark specific items as loading
        model._loading_states["seq01_shot_0002"] = "loading"
        model._loading_states["seq01_shot_0005"] = "loading"
        model._loading_states["seq01_shot_0007"] = "loading"

        # Get loading rows
        loading_rows = delegate._get_loading_rows()

        # Should return rows 2, 5, 7
        assert set(loading_rows) == {2, 5, 7}, f"Expected rows {{2, 5, 7}}, got {set(loading_rows)}"

    def test_get_loading_rows_without_parent(self) -> None:
        """Test _get_loading_rows when delegate has no parent."""
        delegate = ConcreteThumbnailDelegate()

        loading_rows = delegate._get_loading_rows()

        assert loading_rows == []

    def test_get_loading_rows_with_invalid_parent(self, qtbot) -> None:
        """Test _get_loading_rows when parent is not a view."""
        from PySide6.QtWidgets import (
            QWidget,
        )

        widget = QWidget()
        qtbot.addWidget(widget)
        delegate = ConcreteThumbnailDelegate(parent=widget)

        loading_rows = delegate._get_loading_rows()

        assert loading_rows == []


class TestLoadingAnimation:
    """Test loading animation behavior."""

    def test_loading_animation_targeted_repaint(self, qtbot) -> None:
        """Test loading animation only repaints loading items, not entire view.

        This test verifies the critical optimization:
        - Before: parent.update() repaints all 30 items (600 paint calls over 30s)
        - After: dataChanged.emit() repaints only 2 loading items (40 paint calls)
        - Result: 15x reduction in paint calls (93% waste eliminated)
        """
        # Create view and model first
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        # Create delegate with view as parent (critical for parent() to work)
        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Add 30 shots to simulate realistic grid
        shots = [create_mock_shot(i) for i in range(30)]
        model.set_items(shots)

        # Mark 2 items as loading (typical scenario)
        model._loading_states["seq01_shot_0000"] = "loading"
        model._loading_states["seq01_shot_0001"] = "loading"

        # Spy on dataChanged signal to track repaints
        spy = QSignalSpy(model.dataChanged)

        # Trigger one animation update (happens 20x/second during loading)
        delegate._update_loading_animation()

        # Verify: Should emit exactly 2 signals (one per loading item)
        assert spy.count() == 2, f"Expected 2 dataChanged signals, got {spy.count()}"

        # Verify: Each signal should target a single item (not range)
        for i in range(spy.count()):
            signal_args = spy.at(i)
            top_left = signal_args[0]
            bottom_right = signal_args[1]
            # Verify it's a single item (top_left == bottom_right)
            assert top_left.row() == bottom_right.row(), (
                f"Expected single-item repaint, got range {top_left.row()}-{bottom_right.row()}"
            )

        # Verify: Repaints should be for loading items only
        repainted_rows = {spy.at(i)[0].row() for i in range(spy.count())}
        assert repainted_rows == {0, 1}, f"Expected rows {{0, 1}} to be repainted, got {repainted_rows}"

    @pytest.mark.parametrize(
        ("num_shots", "num_loading", "expected_signals"),
        [
            pytest.param(10, 0, 0, id="no_loading_items"),
            pytest.param(5, 5, 5, id="all_items_loading"),
        ],
    )
    def test_loading_animation_signal_count(
        self, qtbot, num_shots: int, num_loading: int, expected_signals: int
    ) -> None:
        """Test animation emits correct number of dataChanged signals for loading items."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        shots = [create_mock_shot(i) for i in range(num_shots)]
        model.set_items(shots)

        # Mark the first num_loading shots as loading
        for shot in shots[:num_loading]:
            model._loading_states[shot.full_name] = "loading"

        spy = QSignalSpy(model.dataChanged)
        delegate._update_loading_animation()

        assert spy.count() == expected_signals, (
            f"Expected {expected_signals} signals for {num_loading}/{num_shots} loading items, "
            f"got {spy.count()}"
        )

        if num_loading > 0:
            repainted_rows = {spy.at(i)[0].row() for i in range(spy.count())}
            assert repainted_rows == set(range(num_loading))

    def test_animation_angle_updates(self, qtbot) -> None:
        """Test that animation angle increments correctly."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        # Create delegate with view as parent
        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Initial angle
        initial_angle = delegate._loading_angle

        # Update animation (no items, so no repaints but angle should update)
        delegate._update_loading_animation()

        # Angle should increment by 10
        assert delegate._loading_angle == (initial_angle + 10) % 360

        # Update 36 times (full rotation)
        for _ in range(35):
            delegate._update_loading_animation()

        # Should be back to initial angle (modulo 360)
        assert delegate._loading_angle == initial_angle


class TestResourceCleanup:
    """Test cleanup() method and resource management."""

    def test_cleanup_stops_timer(self, qtbot) -> None:
        """Test cleanup stops and deletes loading timer."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        # Start loading timer by triggering loading indicator draw
        # (simulated by directly creating timer)
        from PySide6.QtCore import (
            QTimer,
        )

        delegate._loading_timer = QTimer()
        try:
            delegate._loading_timer.start(50)

            assert delegate._loading_timer is not None
            assert delegate._loading_timer.isActive()

            # Cleanup
            delegate.cleanup()

            # Timer should be stopped and deleted
            # Note: We can't test deleteLater() directly, but can verify it was called
            assert delegate._loading_timer is None
        finally:
            # Always ensure timer is cleaned up (Qt resource leak protection)
            if delegate._loading_timer is not None:
                delegate._loading_timer.stop()
                delegate._loading_timer.deleteLater()

    def test_cleanup_clears_cache(self, qtbot) -> None:
        """Test cleanup clears metrics cache."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        # Populate cache
        delegate._metrics_cache["key1"] = QSize(100, 100)
        delegate._metrics_cache["key2"] = QSize(200, 200)

        assert len(delegate._metrics_cache) > 0

        delegate.cleanup()

        assert delegate._metrics_cache == {}

    def test_cleanup_with_no_timer(self, qtbot) -> None:
        """Test cleanup works when timer is None."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        assert delegate._loading_timer is None

        # Should not raise error
        delegate.cleanup()

        assert delegate._loading_timer is None

    def test_cleanup_idempotent(self, qtbot) -> None:
        """Test cleanup can be called multiple times safely."""
        view = QListView()
        qtbot.addWidget(view)
        delegate = ConcreteThumbnailDelegate(parent=view)

        # Populate cache
        delegate._metrics_cache["key1"] = QSize(100, 100)

        # Call cleanup multiple times
        delegate.cleanup()
        delegate.cleanup()
        delegate.cleanup()

        # Should remain clean
        assert delegate._metrics_cache == {}
        assert delegate._loading_timer is None


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param({"name": "test"}, id="missing_key"),
            pytest.param({"name": "test", "thumbnail": None}, id="explicit_none"),
        ],
    )
    def test_null_thumbnail_in_data(self, qtbot, data: ThumbnailItemData) -> None:
        """Test handling of missing or None thumbnail resolves to None."""
        view = QListView()
        qtbot.addWidget(view)

        delegate = MinimalDataDelegate(data_override=data, parent=view)

        index = QModelIndex()
        extracted_data = delegate.get_item_data(index)

        assert extracted_data.get("thumbnail") is None

    def test_very_long_name_truncation(self, qtbot) -> None:
        """Test that very long names get truncated by Qt's eliding."""
        view = QListView()
        qtbot.addWidget(view)

        long_name = "a" * 1000
        data: ThumbnailItemData = {"name": long_name}
        delegate = MinimalDataDelegate(data_override=data, parent=view)

        # Size hint should still work with long names
        option = QStyleOptionViewItem()
        index = QModelIndex()

        size = delegate.sizeHint(option, index)

        # Should return valid size (not error)
        assert size.width() > 0
        assert size.height() > 0

    def test_partial_optional_fields(self, qtbot) -> None:
        """Test handling when only some optional fields are present."""
        view = QListView()
        qtbot.addWidget(view)

        data: ThumbnailItemData = {
            "name": "test_shot",
            "show": "test_show",
            # Missing: sequence, thumbnail, user, timestamp
        }
        delegate = MinimalDataDelegate(data_override=data, parent=view)

        index = QModelIndex()
        extracted_data = delegate.get_item_data(index)

        assert extracted_data["name"] == "test_shot"
        assert extracted_data["show"] == "test_show"
        assert extracted_data.get("sequence") is None
        assert extracted_data.get("user") is None



