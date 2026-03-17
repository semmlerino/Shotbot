"""Unit tests for base_grid_view.py - Base class contract tests.

Tests the common functionality inherited by all grid view subclasses:
- ShotGridView, ThreeDEGridView, PreviousShotsView

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior not implementation
- Use real Qt components with minimal mocking
- Set up signal waiters BEFORE triggering actions
- Use qtbot for proper Qt event handling
- Clean up widgets properly

Test Coverage:
- UI component initialization (slider, combo, text filter, list view)
- Signal emission on user interactions
- Thumbnail size adjustment (slider, wheel event)
- Show filter population and change
- Text filter change
- Keyboard shortcuts for app launching
- Grid size updates
- Visibility tracking
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget

from config import Config
from tests.test_helpers import process_qt_events
from ui.base_grid_view import BaseGridView, HasAvailableShows
from ui.base_thumbnail_delegate import BaseThumbnailDelegate, DelegateTheme


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# ============================================================================
# Test Doubles
# ============================================================================


class MockDelegate(BaseThumbnailDelegate):
    """Minimal delegate for testing BaseGridView.

    Implements the required abstract methods with no-op implementations.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE

    def get_theme(self) -> DelegateTheme:
        """Return default theme for testing."""
        return DelegateTheme()

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size for testing."""
        self._thumbnail_size = size

    def _get_thumbnail_image(self, _index: QModelIndex) -> None:
        """No-op implementation for testing."""
        return

    def _get_display_text(self, _index: QModelIndex) -> str:
        """Return placeholder text for testing."""
        return "Test Item"

    def _get_tooltip_text(self, _index: QModelIndex) -> str:
        """Return placeholder tooltip for testing."""
        return "Test Tooltip"


class ConcreteGridView(BaseGridView):
    """Concrete implementation of BaseGridView for testing.

    Implements all abstract methods with minimal functionality
    to allow testing of the base class behavior.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        # Track method calls for testing
        self.clicked_indices: list[QModelIndex] = []
        self.double_clicked_indices: list[QModelIndex] = []
        self.visible_range_updates: list[tuple[int, int]] = []
        self.toolbar_widget_added = False
        self.top_widget_added = False
        super().__init__(parent)

    def _create_delegate(self) -> BaseThumbnailDelegate:
        """Create mock delegate for testing."""
        return MockDelegate(self)

    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Track clicked indices for testing."""
        self.clicked_indices.append(index)

    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """Track double-clicked indices for testing."""
        self.double_clicked_indices.append(index)

    def _handle_visible_range_update(self, start: int, end: int) -> None:
        """Track visible range updates for testing."""
        self.visible_range_updates.append((start, end))

    def _add_toolbar_widgets(self, layout) -> None:
        """Track that toolbar widgets were added."""
        self.toolbar_widget_added = True

    def _add_top_widgets(self, layout) -> None:
        """Track that top widgets were added."""
        self.top_widget_added = True


class ShowProviderDouble:
    """Test double implementing HasAvailableShows protocol."""

    def __init__(self, shows: list[str]) -> None:
        self._shows = shows

    def get_available_shows(self) -> list[str]:
        return self._shows


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def grid_view(qtbot: QtBot) -> ConcreteGridView:
    """Create ConcreteGridView for testing."""
    view = ConcreteGridView()
    qtbot.addWidget(view)
    return view


@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot: QtBot):
    """Ensure Qt state is cleaned up after each test."""
    yield
    process_qt_events()


# ============================================================================
# Test Initialization
# ============================================================================


class TestBaseGridViewInitialization:
    """Test BaseGridView initialization and UI setup."""

    def test_initialization_creates_all_ui_components(self, grid_view: ConcreteGridView) -> None:
        """Test that initialization creates all expected UI components with correct configuration."""
        from PySide6.QtWidgets import QListView

        # size_slider
        assert hasattr(grid_view, "size_slider"), "size_slider attribute missing"
        assert grid_view.size_slider is not None, "size_slider is None"
        assert grid_view.size_slider.minimum() == Config.MIN_THUMBNAIL_SIZE, "size_slider minimum incorrect"
        assert grid_view.size_slider.maximum() == Config.MAX_THUMBNAIL_SIZE, "size_slider maximum incorrect"
        assert grid_view.size_slider.value() == Config.DEFAULT_THUMBNAIL_SIZE, "size_slider default value incorrect"

        # size_label
        assert hasattr(grid_view, "size_label"), "size_label attribute missing"
        assert grid_view.size_label is not None, "size_label is None"
        assert grid_view.size_label.text() == f"{Config.DEFAULT_THUMBNAIL_SIZE}px", "size_label text incorrect"

        # show_combo
        assert hasattr(grid_view, "show_combo"), "show_combo attribute missing"
        assert grid_view.show_combo is not None, "show_combo is None"
        assert grid_view.show_combo.count() == 1, "show_combo should have one item ('All Shows') by default"
        assert grid_view.show_combo.currentText() == "All Shows", "show_combo default text incorrect"

        # text_filter_input
        assert hasattr(grid_view, "text_filter_input"), "text_filter_input attribute missing"
        assert grid_view.text_filter_input is not None, "text_filter_input is None"
        assert grid_view.text_filter_input.placeholderText() == "Filter...", "text_filter_input placeholder incorrect"
        assert grid_view.text_filter_input.isClearButtonEnabled(), "text_filter_input clear button not enabled"

        # list_view
        assert hasattr(grid_view, "list_view"), "list_view attribute missing"
        assert grid_view.list_view is not None, "list_view is None"
        assert grid_view.list_view.viewMode() == QListView.ViewMode.IconMode, "list_view not in IconMode"

        # delegate
        assert hasattr(grid_view, "_delegate"), "_delegate attribute missing"
        assert grid_view._delegate is not None, "_delegate is None"
        assert isinstance(grid_view._delegate, MockDelegate), "_delegate is not a MockDelegate"

        # template methods
        assert grid_view.toolbar_widget_added is True, "_add_toolbar_widgets() was not called"
        assert grid_view.top_widget_added is True, "_add_top_widgets() was not called"

        # focus policy
        assert grid_view.focusPolicy() == Qt.FocusPolicy.StrongFocus, "grid_view focus policy incorrect"
        assert grid_view.list_view.focusPolicy() == Qt.FocusPolicy.StrongFocus, "list_view focus policy incorrect"

    def test_thumbnail_size_property(self, grid_view: ConcreteGridView) -> None:
        """Test thumbnail_size property returns current size."""
        assert grid_view.thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE


# ============================================================================
# Test Thumbnail Size Control
# ============================================================================


class TestThumbnailSizeControl:
    """Test thumbnail size slider and related functionality."""

    def test_slider_change_updates_label(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that slider change updates size label."""
        # Use a value within valid range (MIN=400, MAX=1200)
        new_size = 500
        grid_view.size_slider.setValue(new_size)
        process_qt_events()

        assert grid_view.size_label.text() == f"{new_size}px"

    def test_slider_change_updates_thumbnail_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that slider change updates internal thumbnail size."""
        # Use a value within valid range (400-1200)
        new_size = 600
        grid_view.size_slider.setValue(new_size)
        process_qt_events()

        assert grid_view.thumbnail_size == new_size

    def test_slider_change_updates_delegate_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that slider change updates delegate thumbnail size."""
        # Use a value within valid range
        new_size = 450
        grid_view.size_slider.setValue(new_size)
        process_qt_events()

        assert grid_view._delegate._thumbnail_size == new_size

    def test_slider_change_updates_grid_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that slider change triggers grid size update."""
        # Use a value within valid range
        new_size = 500
        grid_view.size_slider.setValue(new_size)
        process_qt_events()

        # Grid size calculation uses 16:9 aspect ratio for plate images
        padding = 8
        text_height = 50
        expected_width = new_size + 2 * padding
        thumbnail_height = int(new_size / Config.THUMBNAIL_ASPECT_RATIO)
        expected_height = thumbnail_height + text_height + 2 * padding
        expected_grid_size = QSize(expected_width, expected_height)
        assert grid_view.list_view.gridSize() == expected_grid_size


# ============================================================================
# Test Show Filter
# ============================================================================


class TestShowFilter:
    """Test show filter combo box functionality."""

    def test_populate_show_filter_with_list(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test populating show filter with list of shows."""
        shows = ["ShowA", "ShowC", "ShowB"]
        grid_view.populate_show_filter(shows)

        # Should have "All Shows" + sorted shows
        assert grid_view.show_combo.count() == 4
        assert grid_view.show_combo.itemText(0) == "All Shows"
        assert grid_view.show_combo.itemText(1) == "ShowA"
        assert grid_view.show_combo.itemText(2) == "ShowB"
        assert grid_view.show_combo.itemText(3) == "ShowC"

    def test_populate_show_filter_clears_previous(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that populate_show_filter clears previous shows."""
        # Add first set
        grid_view.populate_show_filter(["Show1", "Show2"])
        assert grid_view.show_combo.count() == 3

        # Add second set
        grid_view.populate_show_filter(["ShowX", "ShowY", "ShowZ"])
        assert grid_view.show_combo.count() == 4
        assert grid_view.show_combo.itemText(1) == "ShowX"

    def test_populate_show_filter_with_protocol_object(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that protocol objects are handled by returning early."""
        provider = ShowProviderDouble(["Show1", "Show2"])

        # Should return early without modifying combo (subclass responsibility)
        initial_count = grid_view.show_combo.count()
        grid_view.populate_show_filter(provider)  # type: ignore[arg-type]

        # Count should remain unchanged
        assert grid_view.show_combo.count() == initial_count

    @pytest.mark.allow_dialogs
    def test_show_filter_change_emits_signal(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that show filter change emits signal."""
        grid_view.populate_show_filter(["TestShow"])

        signal_spy = QSignalSpy(grid_view.show_filter_requested)
        grid_view.show_combo.setCurrentText("TestShow")
        process_qt_events()

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == "TestShow"

    @pytest.mark.allow_dialogs
    def test_show_filter_all_shows_emits_empty_string(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that 'All Shows' selection emits empty string."""
        grid_view.populate_show_filter(["TestShow"])
        grid_view.show_combo.setCurrentText("TestShow")
        process_qt_events()

        signal_spy = QSignalSpy(grid_view.show_filter_requested)
        grid_view.show_combo.setCurrentText("All Shows")
        process_qt_events()

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == ""


# ============================================================================
# Test Text Filter
# ============================================================================


class TestTextFilter:
    """Test text filter input functionality."""

    @pytest.mark.allow_dialogs
    def test_text_filter_change_emits_signal(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that text filter change emits signal."""
        signal_spy = QSignalSpy(grid_view.text_filter_requested)

        grid_view.text_filter_input.setText("test query")
        process_qt_events()

        assert signal_spy.count() >= 1
        # Last emission should be the complete text
        last_idx = signal_spy.count() - 1
        assert signal_spy.at(last_idx)[0] == "test query"

    @pytest.mark.allow_dialogs
    def test_text_filter_clear_emits_empty_string(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that clearing text filter emits empty string."""
        grid_view.text_filter_input.setText("some text")
        process_qt_events()

        signal_spy = QSignalSpy(grid_view.text_filter_requested)
        grid_view.text_filter_input.clear()
        process_qt_events()

        assert signal_spy.count() >= 1
        last_idx = signal_spy.count() - 1
        assert signal_spy.at(last_idx)[0] == ""


# ============================================================================
# Test Wheel Event
# ============================================================================


class TestWheelEvent:
    """Test Ctrl+Wheel thumbnail size adjustment."""

    def test_ctrl_wheel_up_increases_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that Ctrl+Wheel up increases thumbnail size."""
        initial_size = grid_view.thumbnail_size

        # Create wheel event with Ctrl modifier and positive delta
        wheel_event = MagicMock(spec=QWheelEvent)
        wheel_event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
        wheel_event.angleDelta.return_value.y.return_value = 120  # Positive = up

        grid_view.wheelEvent(wheel_event)
        process_qt_events()

        # Size should increase by 10 (capped at MAX)
        expected = min(initial_size + 10, Config.MAX_THUMBNAIL_SIZE)
        assert grid_view.thumbnail_size == expected
        wheel_event.accept.assert_called_once()

    def test_ctrl_wheel_down_decreases_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that Ctrl+Wheel down decreases thumbnail size."""
        # Start at a size that allows decrease
        grid_view.size_slider.setValue(200)
        process_qt_events()

        initial_size = grid_view.thumbnail_size

        wheel_event = MagicMock(spec=QWheelEvent)
        wheel_event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
        wheel_event.angleDelta.return_value.y.return_value = -120  # Negative = down

        grid_view.wheelEvent(wheel_event)
        process_qt_events()

        expected = max(initial_size - 10, Config.MIN_THUMBNAIL_SIZE)
        assert grid_view.thumbnail_size == expected

    def test_wheel_without_ctrl_not_handled(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that wheel without Ctrl passes to parent."""
        initial_size = grid_view.thumbnail_size

        wheel_event = MagicMock(spec=QWheelEvent)
        wheel_event.modifiers.return_value = Qt.KeyboardModifier.NoModifier
        wheel_event.angleDelta.return_value.y.return_value = 120

        with patch.object(QWidget, "wheelEvent") as mock_super:
            grid_view.wheelEvent(wheel_event)

        # Size should not change
        assert grid_view.thumbnail_size == initial_size
        # Super should be called
        mock_super.assert_called_once_with(wheel_event)

    def test_ctrl_wheel_respects_min_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that Ctrl+Wheel respects minimum thumbnail size."""
        grid_view.size_slider.setValue(Config.MIN_THUMBNAIL_SIZE)
        process_qt_events()

        wheel_event = MagicMock(spec=QWheelEvent)
        wheel_event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
        wheel_event.angleDelta.return_value.y.return_value = -120  # Try to go below min

        grid_view.wheelEvent(wheel_event)
        process_qt_events()

        assert grid_view.thumbnail_size == Config.MIN_THUMBNAIL_SIZE

    def test_ctrl_wheel_respects_max_size(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that Ctrl+Wheel respects maximum thumbnail size."""
        grid_view.size_slider.setValue(Config.MAX_THUMBNAIL_SIZE)
        process_qt_events()

        wheel_event = MagicMock(spec=QWheelEvent)
        wheel_event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
        wheel_event.angleDelta.return_value.y.return_value = 120  # Try to go above max

        grid_view.wheelEvent(wheel_event)
        process_qt_events()

        assert grid_view.thumbnail_size == Config.MAX_THUMBNAIL_SIZE


# ============================================================================
# Test Keyboard Shortcuts
# ============================================================================


class TestKeyboardShortcuts:
    """Test keyboard shortcuts for app launching."""

    @pytest.mark.allow_dialogs
    @pytest.mark.parametrize(
        ("key", "expected_app"),
        [
            (Qt.Key.Key_3, "3de"),
            (Qt.Key.Key_N, "nuke"),
            (Qt.Key.Key_M, "maya"),
            (Qt.Key.Key_R, "rv"),
            (Qt.Key.Key_P, "publish"),
        ],
    )
    def test_app_launch_keyboard_shortcuts(
        self,
        qtbot: QtBot,
        grid_view: ConcreteGridView,
        key: Qt.Key,
        expected_app: str,
    ) -> None:
        """Test that keyboard shortcuts emit app_launch_requested signal."""
        signal_spy = QSignalSpy(grid_view.app_launch_requested)

        # QAction shortcuts require the widget to be visible to fire
        grid_view.show()
        grid_view.list_view.setFocus()
        process_qt_events()

        QTest.keyPress(grid_view.list_view, key)
        process_qt_events()

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == expected_app

    def test_unhandled_key_passes_to_list_view(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that unhandled keys are passed to list view."""
        # Arrow keys should go to list view for navigation
        with patch.object(grid_view.list_view, "keyPressEvent") as mock_key:
            QTest.keyPress(grid_view, Qt.Key.Key_Down)
            process_qt_events()
            mock_key.assert_called_once()

    def test_launch_actions_installed_on_list_view(
        self, grid_view: ConcreteGridView
    ) -> None:
        """Test that launch QActions are installed on list_view."""
        actions = grid_view.list_view.actions()
        # Should have 5 actions: 3, N, M, R, P
        assert len(actions) == 5

    @pytest.mark.allow_dialogs
    @pytest.mark.parametrize(
        ("key", "expected_app"),
        [
            (Qt.Key.Key_3, "3de"),
            (Qt.Key.Key_N, "nuke"),
            (Qt.Key.Key_M, "maya"),
            (Qt.Key.Key_R, "rv"),
            (Qt.Key.Key_P, "publish"),
        ],
    )
    def test_shortcuts_fire_when_list_view_focused(
        self,
        qtbot: QtBot,
        grid_view: ConcreteGridView,
        key: Qt.Key,
        expected_app: str,
    ) -> None:
        """Test that QAction shortcuts fire when list_view has focus."""
        signal_spy = QSignalSpy(grid_view.app_launch_requested)

        # QAction shortcuts require the widget to be visible to fire
        grid_view.show()
        grid_view.list_view.setFocus()
        process_qt_events()

        QTest.keyPress(grid_view.list_view, key)
        process_qt_events()

        assert signal_spy.count() == 1
        assert signal_spy.at(0)[0] == expected_app

    def test_navigation_keys_still_work_on_list_view(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that arrow keys still navigate the grid.

        Arrow keys should reach list_view for item navigation.
        """
        # Arrow keys should not trigger app_launch_requested
        signal_spy = QSignalSpy(grid_view.app_launch_requested)

        grid_view.list_view.setFocus()
        process_qt_events()

        QTest.keyPress(grid_view.list_view, Qt.Key.Key_Down)
        process_qt_events()

        assert signal_spy.count() == 0

    def test_shortcuts_dont_fire_when_search_focused(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that shortcuts don't fire when search field has focus.

        Typing 'N' in the search field should type 'N', not launch Nuke.
        """
        signal_spy = QSignalSpy(grid_view.app_launch_requested)

        # Show widget and focus the search field (not list_view)
        grid_view.show()
        grid_view.text_filter_input.setFocus()
        process_qt_events()

        QTest.keyPress(grid_view.text_filter_input, Qt.Key.Key_N)
        process_qt_events()

        assert signal_spy.count() == 0


# ============================================================================
# Test List View Configuration
# ============================================================================


class TestListViewConfiguration:
    """Test QListView configuration."""

    @pytest.mark.parametrize(
        ("method_name", "expected"),
        [
            ("viewMode", "QListView.ViewMode.IconMode"),
            ("resizeMode", "QListView.ResizeMode.Adjust"),
            ("uniformItemSizes", True),
            ("spacing", Config.THUMBNAIL_SPACING),
            ("selectionMode", "QAbstractItemView.SelectionMode.SingleSelection"),
        ],
        ids=["IconMode", "ResizeMode", "UniformItemSizes", "Spacing", "SingleSelection"],
    )
    def test_list_view_property(
        self, grid_view: ConcreteGridView, method_name: str, expected: object
    ) -> None:
        """Test QListView property is configured correctly."""
        from PySide6.QtWidgets import QAbstractItemView, QListView

        # Resolve string sentinels to actual Qt enum values
        _enum_map: dict[str, object] = {
            "QListView.ViewMode.IconMode": QListView.ViewMode.IconMode,
            "QListView.ResizeMode.Adjust": QListView.ResizeMode.Adjust,
            "QAbstractItemView.SelectionMode.SingleSelection": QAbstractItemView.SelectionMode.SingleSelection,
        }
        expected_value = _enum_map.get(expected, expected)  # type: ignore[arg-type]

        actual = getattr(grid_view.list_view, method_name)()
        assert actual == expected_value

    def test_list_view_batched_layout(self, grid_view: ConcreteGridView) -> None:
        """Test list view uses batched layout for performance."""
        from PySide6.QtWidgets import QListView
        assert grid_view.list_view.layoutMode() == QListView.LayoutMode.Batched
        assert grid_view.list_view.batchSize() == 20

    def test_list_view_pixel_scrolling(self, grid_view: ConcreteGridView) -> None:
        """Test list view uses pixel-based scrolling."""
        from PySide6.QtWidgets import QAbstractItemView
        assert (
            grid_view.list_view.verticalScrollMode()
            == QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        assert (
            grid_view.list_view.horizontalScrollMode()
            == QAbstractItemView.ScrollMode.ScrollPerPixel
        )


# ============================================================================
# Test Visibility Tracking
# ============================================================================


class TestVisibilityTracking:
    """Test visibility tracking for lazy loading."""

    def test_visibility_timer_created(self, grid_view: ConcreteGridView) -> None:
        """Test that visibility timer is created."""
        assert hasattr(grid_view, "_visibility_timer")
        assert grid_view._visibility_timer is not None

    def test_visibility_timer_is_single_shot(self, grid_view: ConcreteGridView) -> None:
        """Test visibility timer is configured as single-shot."""
        assert grid_view._visibility_timer.isSingleShot()

    def test_visibility_timer_is_not_active_until_triggered(self, grid_view: ConcreteGridView) -> None:
        """Test visibility timer is not active until a scroll/resize event triggers it."""
        # Single-shot timer is not running until _schedule_visible_range_update is called
        assert not grid_view._visibility_timer.isActive()

    def test_update_visible_range_called(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that _handle_visible_range_update is called when model exists."""
        # Create a mock model
        mock_model = MagicMock()
        mock_model.rowCount.return_value = 10
        mock_model.index.return_value.isValid.return_value = True
        mock_model.index.return_value.row.return_value = 0
        grid_view._model = mock_model

        # Clear any previous updates
        grid_view.visible_range_updates.clear()

        # Manually trigger update
        grid_view._update_visible_range()
        process_qt_events()

        # Should have recorded a visible range update
        assert len(grid_view.visible_range_updates) >= 1

    def test_update_visible_range_no_model(
        self, qtbot: QtBot, grid_view: ConcreteGridView
    ) -> None:
        """Test that _update_visible_range returns early without model."""
        grid_view._model = None
        grid_view.visible_range_updates.clear()

        grid_view._update_visible_range()
        process_qt_events()

        # No updates should be recorded
        assert len(grid_view.visible_range_updates) == 0


# ============================================================================
# Test Signals
# ============================================================================


class TestSignals:
    """Test signal definitions and connectivity."""


# ============================================================================
# Test HasAvailableShows Protocol
# ============================================================================


class TestHasAvailableShowsProtocol:
    """Test HasAvailableShows protocol compliance."""

    def test_protocol_structural_typing(self) -> None:
        """Test that objects with get_available_shows() match protocol."""
        provider = ShowProviderDouble(["Show1", "Show2"])

        # Verify structural typing works
        def accepts_protocol(obj: HasAvailableShows) -> list[str]:
            return obj.get_available_shows()

        result = accepts_protocol(provider)
        assert result == ["Show1", "Show2"]

    def test_protocol_method_signature(self) -> None:
        """Test protocol defines correct method signature."""
        from typing import get_type_hints

        # Check protocol has required method
        assert hasattr(HasAvailableShows, "get_available_shows")

        # Check return type annotation
        hints = get_type_hints(HasAvailableShows.get_available_shows)
        assert hints.get("return") == list[str]
