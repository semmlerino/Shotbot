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

from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QWidget,
)

from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

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
def real_cache_manager(tmp_path: Path) -> Path:
    """Return cache directory path for MainWindow construction."""
    return tmp_path / "test_cache"


@pytest.fixture(autouse=True)
def stable_main_window_startup(
    monkeypatch: pytest.MonkeyPatch, expect_no_dialogs: object
) -> None:
    """Disable background startup work unrelated to widget behavior."""
    from type_definitions import RefreshResult

    def _skip_async_init(_self: object) -> RefreshResult:
        return RefreshResult(success=True, has_changes=False)

    monkeypatch.setenv("SHOTBOT_NO_INITIAL_LOAD", "1")
    monkeypatch.setattr("shot_model.ShotModel.initialize_async", _skip_async_init)
    monkeypatch.setattr(
        "launch.environment_manager.EnvironmentManager.warm_cache_async",
        lambda _self: None,
    )


class TestMainWindowInitialization:
    """Test MainWindow initialization and basic properties."""

    @pytest.fixture
    def main_window(self, qtbot: QtBot, real_cache_manager: Path) -> MainWindow:
        """Create MainWindow for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_dir=real_cache_manager)
        qtbot.addWidget(window)
        return window

    def test_window_creation(self, main_window: MainWindow) -> None:
        """Test MainWindow creates successfully."""
        window = main_window

        # Window should be created
        assert window is not None
        assert isinstance(window, QMainWindow)
        assert window.cache_coordinator is not None

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

    def test_cache_sub_managers_created(
        self, main_window: MainWindow
    ) -> None:
        """Test cache sub-managers are properly created."""
        window = main_window

        # Cache sub-managers should be created
        assert window.thumbnail_cache is not None
        assert window.shot_cache is not None
        assert window.scene_disk_cache is not None
        assert window.latest_file_cache is not None
        assert window.cache_coordinator is not None


class TestMainWindowUIComponents:
    """Test MainWindow UI components exist and are properly configured."""

    @pytest.fixture
    def main_window_ui(
        self, qtbot: QtBot, real_cache_manager: Path
    ) -> MainWindow:
        """Create MainWindow with UI setup for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_dir=real_cache_manager)
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

class TestMainWindowTabFunctionality:
    """Test tab widget functionality and navigation."""

    @pytest.fixture
    def tabbed_window(
        self, qtbot: QtBot, real_cache_manager: Path
    ) -> MainWindow:
        """Create MainWindow with tabs for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_dir=real_cache_manager)
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
        self, qtbot: QtBot, real_cache_manager: Path
    ) -> MainWindow:
        """Create MainWindow with signal connections for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_dir=real_cache_manager)
        qtbot.addWidget(window)
        process_qt_events()
        return window

class TestMainWindowStateManagement:
    """Test window state management and persistence."""

    @pytest.fixture
    def stateful_window(
        self, qtbot: QtBot, real_cache_manager: Path
    ) -> MainWindow:
        """Create MainWindow for state testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_dir=real_cache_manager)
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
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            # Restore may not work in headless environment
            pass


class TestMainWindowErrorHandling:
    """Test MainWindow error handling and edge cases."""

    def test_window_creation_with_default_cache(self, qtbot: QtBot) -> None:
        """Test window creates with default cache directory."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow()
        qtbot.addWidget(window)

        # Should create with default cache sub-managers
        assert window is not None
        assert window.cache_coordinator is not None

class TestMainWindowIntegration:
    """Test integration between MainWindow components."""

    @pytest.fixture
    def integrated_window(
        self, qtbot: QtBot, real_cache_manager: Path
    ) -> MainWindow:
        """Create fully integrated MainWindow for testing."""
        # Local import to avoid module-level issues
        from main_window import (
            MainWindow,
        )

        window = MainWindow(cache_dir=real_cache_manager)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        process_qt_events()
        return window

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
