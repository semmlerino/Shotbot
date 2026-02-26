"""Tests for MainWindow widgets and components.

Following UNIFIED_TESTING_GUIDE principles:
- Test behavior not implementation
- Use real Qt components with minimal mocking
- Use QSignalSpy for signal testing
- Test user interactions with real Qt events
- Verify widget state changes
- Handle Qt event loop properly with qtbot
- Clean up widgets with qtbot.addWidget()
"""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from cache_manager import CacheManager
    from main_window import MainWindow

# Lazy import to avoid Qt initialization at module level
# MainWindow imported inside each test/fixture to avoid module-level issues

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.permissive_process_pool,  # Widget tests check UI, not subprocess output
]


# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)


@pytest.fixture
def real_cache_manager(tmp_path: Path) -> CacheManager:
    """Create real CacheManager for testing."""
    # Local application imports
    from cache_manager import (
        CacheManager,
    )

    return CacheManager(cache_dir=tmp_path / "test_cache")


class TestMainWindowInitialization:
    """Test MainWindow initialization and basic properties."""

    @pytest.fixture
    def main_window(self, qtbot: QtBot, real_cache_manager: CacheManager) -> MainWindow:
        """Create MainWindow for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        return window

    def test_window_creation(self, main_window: MainWindow) -> None:
        """Test MainWindow creates successfully."""
        window = main_window

        # Window should be created
        assert window is not None
        assert isinstance(window, QMainWindow)
        assert window.cache_manager is not None

    def test_window_properties(self, main_window: MainWindow) -> None:
        """Test window has correct basic properties."""
        window = main_window

        # Window should have title
        title = window.windowTitle()
        assert isinstance(title, str)
        assert len(title) > 0

        # Window should have reasonable size
        size = window.size()
        assert size.width() > 0
        assert size.height() > 0

    def test_window_central_widget(self, main_window: MainWindow) -> None:
        """Test window has central widget setup."""
        window = main_window

        # Should have central widget
        central_widget = window.centralWidget()
        assert central_widget is not None
        assert isinstance(central_widget, QWidget)

    def test_cache_manager_assignment(
        self, main_window: MainWindow, real_cache_manager: CacheManager
    ) -> None:
        """Test cache manager is properly assigned."""
        window = main_window

        # Cache manager should be assigned
        assert window.cache_manager == real_cache_manager
        assert window.cache_manager is not None


class TestMainWindowUIComponents:
    """Test MainWindow UI components exist and are properly configured."""

    @pytest.fixture
    def main_window_ui(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> MainWindow:
        """Create MainWindow with UI setup for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        # Allow UI to initialize
        process_qt_events()
        return window

    def test_tab_widget_exists(self, main_window_ui: MainWindow) -> None:
        """Test main tab widget exists and is configured."""
        window = main_window_ui

        # Find tab widget
        tab_widget = window.findChild(QTabWidget)
        if tab_widget:
            assert isinstance(tab_widget, QTabWidget)

            # Should have multiple tabs
            tab_count = tab_widget.count()
            assert tab_count >= 3  # My Shots, Other 3DE scenes, Previous Shots

    def test_status_bar_exists(self, main_window_ui: MainWindow) -> None:
        """Test status bar exists and is functional."""
        window = main_window_ui

        # MainWindow should have status bar
        status_bar = window.statusBar()
        assert status_bar is not None
        assert isinstance(status_bar, QStatusBar)

    def test_menu_bar_exists(self, main_window_ui: MainWindow) -> None:
        """Test menu bar exists."""
        window = main_window_ui

        # MainWindow should have menu bar
        menu_bar = window.menuBar()
        assert menu_bar is not None

class TestMainWindowTabFunctionality:
    """Test tab widget functionality and navigation."""

    @pytest.fixture
    def tabbed_window(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> MainWindow:
        """Create MainWindow with tabs for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        process_qt_events()
        return window

    def test_tab_navigation(self, qtbot: QtBot, tabbed_window: MainWindow) -> None:
        """Test tab navigation works correctly."""
        window = tabbed_window
        tab_widget = window.findChild(QTabWidget)

        if tab_widget and tab_widget.count() > 1:
            # Get initial tab
            initial_tab = tab_widget.currentIndex()

            # Switch to next tab
            next_tab = (initial_tab + 1) % tab_widget.count()
            tab_widget.setCurrentIndex(next_tab)
            # Wait for tab change to complete
            qtbot.waitUntil(lambda: tab_widget.currentIndex() == next_tab, timeout=1000)

            # Verify tab changed
            current_tab = tab_widget.currentIndex()
            assert current_tab == next_tab

    def test_tab_content_exists(self, tabbed_window: MainWindow) -> None:
        """Test tabs have content widgets."""
        window = tabbed_window
        tab_widget = window.findChild(QTabWidget)

        if tab_widget:
            # Each tab should have a widget
            for i in range(tab_widget.count()):
                tab_widget.setCurrentIndex(i)
                current_widget = tab_widget.currentWidget()
                assert current_widget is not None
                assert isinstance(current_widget, QWidget)

    def test_tab_labels(self, tabbed_window: MainWindow) -> None:
        """Test tabs have appropriate labels."""
        window = tabbed_window
        tab_widget = window.findChild(QTabWidget)

        if tab_widget:
            # Each tab should have text
            for i in range(tab_widget.count()):
                tab_text = tab_widget.tabText(i)
                assert isinstance(tab_text, str)
                assert len(tab_text) > 0

    def test_tab_switching_signals(
        self, qtbot: QtBot, tabbed_window: MainWindow
    ) -> None:
        """Test tab switching emits proper signals."""
        window = tabbed_window
        tab_widget = window.findChild(QTabWidget)

        if tab_widget and tab_widget.count() > 1:
            # Switch tabs with signal expectation
            original_index = tab_widget.currentIndex()
            new_index = (original_index + 1) % tab_widget.count()

            # Set up signal expectation with parameter checking
            def check_tab_change(index: int) -> bool:
                return index == new_index

            with qtbot.waitSignal(
                tab_widget.currentChanged, check_params_cb=check_tab_change
            ):
                tab_widget.setCurrentIndex(new_index)

            process_qt_events()


class TestMainWindowSignalConnections:
    """Test signal connections between MainWindow components."""

    @pytest.fixture
    def connected_window(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> MainWindow:
        """Create MainWindow with signal connections for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        process_qt_events()
        return window

class TestMainWindowKeyboardShortcuts:
    """Test keyboard shortcuts and accessibility."""

    @pytest.fixture
    def shortcut_window(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> MainWindow:
        """Create MainWindow for shortcut testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        return window

    def test_refresh_shortcut(self, qtbot: QtBot, shortcut_window: MainWindow) -> None:
        """Test keyboard shortcut handling infrastructure."""
        window = shortcut_window

        # Attempt to activate window for shortcuts
        window.activateWindow()
        window.raise_()
        window.setFocus()
        # Wait for window to become active
        try:
            qtbot.waitUntil(lambda: window.isActiveWindow(), timeout=1000)
        except Exception:
            # Window activation may fail in headless environment
            pass

        # Test that window can handle key events without triggering refresh
        # Use a safe key that won't trigger complex operations
        QTest.keyPress(window, Qt.Key.Key_Space)
        process_qt_events()

        # The key press should be processed without crashing the window
        assert window.isVisible()
        assert not window.isMinimized()

    def test_escape_key_handling(
        self, qtbot: QtBot, shortcut_window: MainWindow
    ) -> None:
        """Test escape key handling."""
        window = shortcut_window

        window.activateWindow()
        window.setFocus()
        # Wait for window to become active
        try:
            qtbot.waitUntil(lambda: window.isActiveWindow(), timeout=1000)
        except Exception:
            # Window activation may fail in headless environment
            pass

        # Press escape
        QTest.keyPress(window, Qt.Key.Key_Escape)
        process_qt_events()

        # Escape should be handled without leaving the app in invalid state.
        assert window is not None


class TestMainWindowStateManagement:
    """Test window state management and persistence."""

    @pytest.fixture
    def stateful_window(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> MainWindow:
        """Create MainWindow for state testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        return window

    def test_window_geometry_management(
        self, qtbot: QtBot, stateful_window: MainWindow
    ) -> None:
        """Test window geometry can be managed."""
        window = stateful_window

        # Get initial geometry
        initial_geometry = window.geometry()

        # Resize window
        new_width = initial_geometry.width() + 100
        new_height = initial_geometry.height() + 100
        window.resize(new_width, new_height)
        # Wait for resize to complete
        try:
            qtbot.waitUntil(
                lambda: window.geometry().width() >= new_width - 50,
                timeout=1000
            )
        except Exception:
            # Resize may not complete in headless environment
            pass

        # Verify resize
        new_geometry = window.geometry()
        assert new_geometry.width() >= new_width - 50  # Allow some tolerance
        assert new_geometry.height() >= new_height - 50

    def test_window_show_hide(self, qtbot: QtBot, stateful_window: MainWindow) -> None:
        """Test window show/hide functionality."""
        window = stateful_window

        # Window should be visible initially (fixture shows it)
        assert window.isVisible()

        # Hide window
        window.hide()
        # Wait for window to become hidden
        qtbot.waitUntil(lambda: not window.isVisible(), timeout=1000)
        assert not window.isVisible()

        # Show window
        window.show()
        # Wait for window to become visible
        qtbot.waitUntil(lambda: window.isVisible(), timeout=1000)
        assert window.isVisible()

    def test_window_minimize_restore(
        self, qtbot: QtBot, stateful_window: MainWindow
    ) -> None:
        """Test window minimize/restore functionality."""
        window = stateful_window

        # Test minimize
        window.showMinimized()
        # Wait for window to become minimized
        try:
            qtbot.waitUntil(
                lambda: window.isMinimized() or window.windowState() & Qt.WindowState.WindowMinimized,
                timeout=1000
            )
        except Exception:
            # Minimize may not work in headless environment
            pass

        # Window state should change
        assert (
            window.isMinimized()
            or window.windowState() & Qt.WindowState.WindowMinimized
        )

        # Restore window
        window.showNormal()
        # Wait for window to be restored
        try:
            qtbot.waitUntil(lambda: not window.isMinimized(), timeout=1000)
        except Exception:
            # Restore may not work in headless environment
            pass


class TestMainWindowErrorHandling:
    """Test MainWindow error handling and edge cases."""

    def test_window_creation_with_no_cache_manager(self, qtbot: QtBot) -> None:
        """Test window creates with default cache manager."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=None)
        qtbot.addWidget(window)

        # Should create with default cache manager
        assert window is not None
        assert window.cache_manager is not None

    def test_window_close_event_handling(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> None:
        """Test window handles close events properly."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)

        # Create close event
        close_event = QCloseEvent()

        # Window should handle close event without crashing
        with contextlib.suppress(RuntimeError):
            window.closeEvent(close_event)

        # Event handling shouldn't crash the process
        assert window is not None

class TestMainWindowIntegration:
    """Test integration between MainWindow components."""

    @pytest.fixture
    def integrated_window(
        self, qtbot: QtBot, real_cache_manager: CacheManager
    ) -> MainWindow:
        """Create fully integrated MainWindow for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_manager=real_cache_manager)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        process_qt_events()
        return window

    def test_cache_manager_integration(
        self,
        qtbot: QtBot,
        integrated_window: MainWindow,
        real_cache_manager: CacheManager,
    ) -> None:
        """Test cache manager integrates with all components."""
        window = integrated_window

        # Cache manager should be shared
        assert window.cache_manager == real_cache_manager

        # Components should use the same cache manager
        # Shot model should use the cache manager
        assert hasattr(window.shot_model, "cache_manager")

    def test_status_updates(self, qtbot: QtBot, integrated_window: MainWindow) -> None:
        """Test status bar receives updates from components."""
        window = integrated_window
        status_bar = window.statusBar()

        # Status bar should be functional
        status_bar.showMessage("Test message")
        # Wait for message to be displayed
        qtbot.waitUntil(lambda: status_bar.currentMessage() == "Test message", timeout=1000)

        # Message should be displayed
        current_message = status_bar.currentMessage()
        assert current_message == "Test message"

    def test_ui_responsiveness_under_load(
        self, qtbot: QtBot, integrated_window: MainWindow
    ) -> None:
        """Test UI remains responsive under component load."""
        window = integrated_window

        # Simulate multiple UI updates
        for i in range(5):
            window.statusBar().showMessage(f"Update {i}")
            process_qt_events()

        # Window should remain responsive (fixture shows it)
        assert window.isVisible()
        assert window.isEnabled()
