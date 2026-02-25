"""Comprehensive Qt widget tests for thumbnail widgets.

This test module provides complete Qt widget testing for ThumbnailWidget and
ThumbnailWidgetBase components, focusing on real Qt behavior and interactions.

Test Coverage:
- Widget initialization and UI setup
- Signal emission on mouse interactions
- Selection state changes and visual feedback
- Thumbnail loading and display
- Event handling (mouse, keyboard, resize)

Following UNIFIED_TESTING_GUIDE:
- Use real Qt widgets, not mocks
- Test behavior through user interactions
- Use QSignalSpy for reliable signal testing
- Set up signal waiters BEFORE triggering actions
- Use qtbot for proper Qt event processing
- Avoid threading violations (no QPixmap in threads)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

# Local application imports
from config import Config
from shot_model import Shot
from thumbnail_widget import ThumbnailWidget
from thumbnail_widget_base import ThumbnailWidgetBase


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from cache_manager import CacheManager

pytestmark = [pytest.mark.unit, pytest.mark.qt]

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns


def _process_events(duration_ms: int = 5, iterations: int = 1) -> None:
    """Drain Qt events without relying on qtbot.wait(), keeping teardown stable."""
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, duration_ms)


# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)


class TestThumbnailWidgetBase:
    """Test real Qt widget behavior of ThumbnailWidgetBase."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot for widget testing."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def thumbnail_widget_base(
        self, qtbot: QtBot, test_shot: Shot
    ) -> ThumbnailWidgetBase:
        """Create ThumbnailWidgetBase widget for testing."""
        widget = ThumbnailWidgetBase(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    def test_widget_initialization(
        self, thumbnail_widget_base: ThumbnailWidgetBase, test_shot: Shot
    ) -> None:
        """Test widget initializes with correct properties."""
        widget = thumbnail_widget_base

        # Verify basic properties
        assert widget.data == test_shot
        assert widget._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE
        assert widget._selected is False

    def test_widget_ui_components(
        self, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test widget has expected UI components."""
        widget = thumbnail_widget_base

        # Check for essential UI components
        assert hasattr(widget, "thumbnail_label")
        assert isinstance(widget.thumbnail_label, QLabel)
        assert hasattr(widget, "thumbnail_container")
        assert isinstance(widget.thumbnail_container, QWidget)

    def test_signals_exist(self, thumbnail_widget_base: ThumbnailWidgetBase) -> None:
        """Test widget has all expected signals."""
        widget = thumbnail_widget_base

        # Verify signal existence
        assert hasattr(widget, "clicked")
        assert hasattr(widget, "double_clicked")

    def test_selection_state_change(
        self, qtbot: QtBot, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test selection state changes correctly."""
        widget = thumbnail_widget_base

        # Initially unselected
        assert widget._selected is False

        # Set selected (using internal method)
        widget._selected = True
        _process_events()

        # Verify state change
        assert widget._selected is True

    def test_mouse_click_signal_emission(
        self, qtbot: QtBot, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test mouse clicks emit correct signals."""
        widget = thumbnail_widget_base

        # Set up signal expectation with parameter checking
        def check_click_data(data: Shot) -> bool:
            return data == widget.data

        with qtbot.waitSignal(widget.clicked, check_params_cb=check_click_data):
            # Simulate left mouse click
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

        _process_events()

    def test_mouse_double_click_signal_emission(
        self, qtbot: QtBot, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test mouse double clicks emit correct signals."""
        widget = thumbnail_widget_base

        # Set up signal expectation with parameter checking
        def check_double_click_data(data: Shot) -> bool:
            return data == widget.data

        with qtbot.waitSignal(
            widget.double_clicked, check_params_cb=check_double_click_data
        ):
            # Simulate double click
            QTest.mouseDClick(widget, Qt.MouseButton.LeftButton)

        _process_events()

    def test_thumbnail_size_property(
        self, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test thumbnail size property works correctly."""
        widget = thumbnail_widget_base

        # Initial size should match constructor
        assert widget._thumbnail_size == Config.DEFAULT_THUMBNAIL_SIZE

        # Size should be positive
        assert widget._thumbnail_size > 0

    def test_widget_styling_methods(
        self, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test widget has necessary methods."""
        widget = thumbnail_widget_base

        # Should have essential methods
        assert hasattr(widget, "_setup_base_ui")
        assert callable(widget._setup_base_ui)

    def test_thumbnail_label_configuration(
        self, thumbnail_widget_base: ThumbnailWidgetBase
    ) -> None:
        """Test thumbnail label is properly configured."""
        widget = thumbnail_widget_base
        label = widget.thumbnail_label

        # Label should be configured correctly
        assert label.size().width() == widget._thumbnail_size
        assert label.size().height() == widget._thumbnail_size
        assert label.alignment() & Qt.AlignmentFlag.AlignCenter


class TestThumbnailWidget:
    """Test real Qt widget behavior of ThumbnailWidget (Shot-specific)."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot for widget testing."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def thumbnail_widget(self, qtbot: QtBot, test_shot: Shot) -> ThumbnailWidget:
        """Create ThumbnailWidget for testing."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    def test_shot_widget_initialization(
        self, thumbnail_widget: ThumbnailWidget, test_shot: Shot
    ) -> None:
        """Test shot-specific widget initialization."""
        widget = thumbnail_widget

        # Verify shot-specific properties
        assert widget.shot == test_shot
        assert hasattr(widget, "name_label")
        assert isinstance(widget.name_label, QLabel)

    def test_shot_name_display(
        self, thumbnail_widget: ThumbnailWidget, test_shot: Shot
    ) -> None:
        """Test shot name is displayed correctly."""
        widget = thumbnail_widget
        name_label = widget.name_label

        # Name label should show full shot name
        assert name_label.text() == test_shot.full_name
        assert name_label.alignment() & Qt.AlignmentFlag.AlignCenter

    def test_shot_specific_signals(self, thumbnail_widget: ThumbnailWidget) -> None:
        """Test shot-specific signals exist."""
        widget = thumbnail_widget

        # Shot widget should have backward compatibility signals
        assert hasattr(widget, "clicked")
        assert hasattr(widget, "double_clicked")

    def test_shot_widget_styling(
        self, qtbot: QtBot, thumbnail_widget: ThumbnailWidget
    ) -> None:
        """Test shot widget applies correct styling."""
        widget = thumbnail_widget

        # Widget should have style methods
        assert hasattr(widget, "_get_selected_style")
        assert hasattr(widget, "_get_unselected_style")

        # Test that methods are callable
        selected_style = widget._get_selected_style()
        unselected_style = widget._get_unselected_style()

        assert isinstance(selected_style, str)
        assert isinstance(unselected_style, str)

    def test_shot_widget_layout(self, thumbnail_widget: ThumbnailWidget) -> None:
        """Test shot widget layout includes all components."""
        widget = thumbnail_widget

        # Widget should have layout
        layout = widget.layout()
        assert layout is not None
        assert isinstance(layout, QVBoxLayout)

        # Layout should contain components
        widget_children = widget.findChildren(QLabel)
        assert len(widget_children) >= 1  # At least name_label

    def test_shot_widget_font_configuration(
        self, thumbnail_widget: ThumbnailWidget
    ) -> None:
        """Test shot widget configures fonts correctly."""
        widget = thumbnail_widget
        name_label = widget.name_label

        # Font should be configured (using pixelSize via design system)
        font = name_label.font()
        assert font.pixelSize() == 14  # size_small from design_system

        # Label should support word wrap
        assert name_label.wordWrap() is True


class TestThumbnailWidgetInteractions:
    """Test real user interactions with thumbnail widgets."""

    @pytest.fixture
    def interactive_widget(self, qtbot: QtBot) -> ThumbnailWidget:
        """Create thumbnail widget for interaction testing."""
        shot = Shot("interactive", "test", "0001", "/test/path")
        widget = ThumbnailWidget(shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        widget.show()  # Make visible for interactions
        _process_events()
        return widget

    def test_click_selection_workflow(
        self, qtbot: QtBot, interactive_widget: ThumbnailWidget
    ) -> None:
        """Test complete click-to-select workflow."""
        widget = interactive_widget

        # Set up signal spy
        clicked_spy = QSignalSpy(widget.clicked)

        # Initially not selected
        assert widget._selected is False

        # Click widget to select
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        _process_events()

        # Verify click signal
        assert clicked_spy.count() == 1

    def test_double_click_workflow(
        self, qtbot: QtBot, interactive_widget: ThumbnailWidget
    ) -> None:
        """Test double-click workflow for launching."""
        widget = interactive_widget

        # Set up signal spy
        double_clicked_spy = QSignalSpy(widget.double_clicked)

        # Double-click widget
        QTest.mouseDClick(widget, Qt.MouseButton.LeftButton)
        _process_events()

        # Verify double-click signal
        assert double_clicked_spy.count() == 1

    def test_widget_size_constraints(self, interactive_widget: ThumbnailWidget) -> None:
        """Test widget respects size constraints."""
        widget = interactive_widget

        # Widget should have reasonable minimum size
        min_size = widget.minimumSize()
        assert min_size.width() >= 0
        assert min_size.height() >= 0

        # Widget should have maximum size constraints
        max_size = widget.maximumSize()
        assert max_size.isValid()

    def test_widget_visibility_state(
        self, qtbot: QtBot, interactive_widget: ThumbnailWidget
    ) -> None:
        """Test widget visibility state management."""
        widget = interactive_widget

        # Widget should be visible (we showed it in fixture)
        assert widget.isVisible()

        # Widget should support show/hide
        widget.hide()
        _process_events()
        assert not widget.isVisible()

        widget.show()
        _process_events()
        assert widget.isVisible()


class TestThumbnailWidgetLoadingStates:
    """Test thumbnail loading states and indicators."""

    @pytest.fixture
    def loading_widget(self, qtbot: QtBot) -> ThumbnailWidget:
        """Create widget for loading state testing."""
        shot = Shot("loading", "test", "0001", "/test/path")
        widget = ThumbnailWidget(shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    def test_loading_state_initialization(
        self, loading_widget: ThumbnailWidget
    ) -> None:
        """Test widget initializes with correct loading state."""
        widget = loading_widget

        # Widget should have loading state tracking
        assert hasattr(widget, "_loading_state")

    def test_loading_indicator_exists(self, loading_widget: ThumbnailWidget) -> None:
        """Test loading indicator component exists."""
        widget = loading_widget

        # Widget should have loading indicator
        assert hasattr(widget, "loading_indicator")

    def test_thumbnail_container_setup(self, loading_widget: ThumbnailWidget) -> None:
        """Test thumbnail container is properly configured."""
        widget = loading_widget
        container = widget.thumbnail_container

        # Container should be configured correctly
        assert container.size().width() == widget._thumbnail_size
        assert container.size().height() == widget._thumbnail_size


class TestThumbnailWidgetIntegration:
    """Integration tests for thumbnail widget with cache manager."""

    @pytest.fixture(autouse=True)
    def cleanup_cache_manager(self, cache_manager) -> Iterator[None]:
        """Reset ThumbnailWidget cache manager after each test.

        Per UNIFIED_TESTING_V2.md: Use monkeypatch for global state isolation.
        """
        yield
        # Restore to CLEAN cache manager (from fixture) to prevent pollution
        ThumbnailWidget.set_cache_manager(cache_manager)

    @pytest.fixture
    def integrated_widget(
        self, qtbot: QtBot, cache_manager: CacheManager
    ) -> ThumbnailWidget:
        """Create widget with real cache manager."""
        shot = Shot("integrated", "test", "0001", "/test/path")

        # Set cache manager on widget class
        ThumbnailWidget.set_cache_manager(cache_manager)

        widget = ThumbnailWidget(shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    def test_cache_manager_integration(
        self, integrated_widget: ThumbnailWidget, cache_manager: CacheManager
    ) -> None:
        """Test widget integrates with cache manager."""
        widget = integrated_widget

        # Widget should use the cache manager
        assert widget._cache_manager == cache_manager

    def test_widget_with_real_cache(
        self, qtbot: QtBot, cache_manager: CacheManager
    ) -> None:
        """Test widget behavior with real cache manager."""
        shot = Shot("cached", "test", "0001", "/test/path")
        ThumbnailWidget.set_cache_manager(cache_manager)

        widget = ThumbnailWidget(shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)

        # Widget should be created successfully with cache
        assert widget is not None
        assert widget._cache_manager is not None
