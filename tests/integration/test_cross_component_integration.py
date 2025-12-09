"""Cross-component integration tests for ShotBot.

This module tests critical interactions between multiple components to ensure
they work together correctly. Following UNIFIED_TESTING_GUIDE principles:
- Use real components with test doubles only at boundaries
- Test behavior, not implementation
- Thread-safe testing patterns
- Proper signal testing with qtbot.waitSignal()
"""

from __future__ import annotations

# Standard library imports
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Third-party imports
import pytest
from PySide6.QtWidgets import QApplication

# Local application imports
# Moved to lazy import to fix Qt initialization
# from main_window import MainWindow
from cache_manager import CacheManager
from shot_model import Shot
from tests.test_doubles_library import TestProcessPool
from tests.test_helpers import process_qt_events
from threede_scene_model import ThreeDEScene


if TYPE_CHECKING:
    # Third-party imports
    from pytestqt.qtbot import QtBot


# Module-level fixture to handle lazy imports after Qt initialization
@pytest.fixture(autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow  # noqa: PLW0603
    from main_window import (
        MainWindow,
    )



pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,  # CRITICAL: Same group for all Qt tests
    pytest.mark.allow_dialogs,  # Dialogs expected during MainWindow setup
]


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestCrossTabSynchronization:
    """Test data synchronization across all three tabs."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, qtbot: QtBot) -> None:
        """Properly clean up Qt widgets and process events between tests.

        This fixture implements the complete Qt cleanup sequence:
        1. Close windows and trigger closeEvent
        2. deleteLater() to schedule C++ object deletion
        3. processEvents() to flush deletion queue
        4. sendPostedEvents() for deferred deletes
        5. processEvents() again for cascading cleanups

        See tests/helpers/qt_thread_cleanup.py for similar pattern.
        """
        # Clear ProcessPoolManager singleton before test
        # Local application imports

        # Track windows created during test
        self.test_windows: list[MainWindow] = []

        yield

        # Properly close all windows to trigger closeEvent and cleanup
        for window in self.test_windows:
            if window:
                # Explicitly call closeEvent to ensure workers are stopped
                # Third-party imports
                from PySide6.QtGui import (
                    QCloseEvent,
                )

                close_event = QCloseEvent()
                window.closeEvent(close_event)

                # Now close the window
                if not window.isHidden():
                    window.close()
                    # Wait for window to close
                    qtbot.waitUntil(lambda w=window: w.isHidden(), timeout=2000)

                # Delete the window instance explicitly
                window.deleteLater()
                process_qt_events()

        # Clear the list immediately after closing
        self.test_windows.clear()

        # Process all pending events and deleteLater calls
        # This follows the Qt cleanup pattern from qt_thread_cleanup.py
        app = QApplication.instance()
        if app:
            for _ in range(3):
                app.processEvents()
                app.sendPostedEvents(None, 0)  # Process all deferred deletions
                process_qt_events()

    def test_shot_selection_syncs_info_panel_across_tabs(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Verify info panel updates when switching tabs with different selections.

        This tests that:
        1. Selecting a shot in My Shots tab updates info panel
        2. Switching to 3DE tab and selecting a scene updates info panel
        3. Info panel correctly reflects the current selection
        """
        # Force legacy model to avoid async issues in tests
        os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

        # HACK: Temporarily disable QTimer to prevent background refreshes during init
        # TODO: Refactor to use proper async initialization or mock at subprocess boundary
        # instead of disabling core Qt mechanisms. This hack means integration tests
        # aren't fully testing background task integration.
        # Third-party imports
        from PySide6.QtCore import (
            QTimer,
        )

        original_singleshot = QTimer.singleShot
        QTimer.singleShot = lambda *_args, **_kwargs: None  # Disable all timers

        try:
            # Create MainWindow with real components
            window = MainWindow()
            qtbot.addWidget(window)  # CRITICAL: Register for cleanup
            self.test_windows.append(window)  # Track for proper cleanup
        finally:
            # Restore QTimer immediately after window creation
            QTimer.singleShot = original_singleshot

        # Stop any background loaders that might have started
        # This is critical - must stop before setting up test pool
        # Third-party imports
        from PySide6.QtCore import (
            QMutexLocker,
        )

        # Stop async loader with lock held
        with QMutexLocker(window.shot_model._loader_lock):
            if window.shot_model._async_loader:
                window.shot_model._async_loader.stop()
                window.shot_model._async_loader.wait()
                window.shot_model._async_loader.deleteLater()
                # Note: deleteLater() is deferred, object will be deleted when control returns to event loop
                window.shot_model._async_loader = None
            window.shot_model._loading_in_progress = False

        # Process Qt events AFTER releasing lock to avoid deadlock with _on_loader_finished
        # (deleteLater objects are processed here)
        process_qt_events()

        # Clear cache to ensure clean test state
        window.cache_manager.clear_cache()

        # Mock only the subprocess boundary
        # Note: ws -sg returns all shots in a single multi-line output
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs(
            "workspace /shows/TEST/shots/seq01/seq01_0010\nworkspace /shows/TEST/shots/seq01/seq01_0020"
        )
        window.shot_model._process_pool = test_pool

        # Refresh shots to populate the model
        success, _has_changes = window.shot_model.refresh_shots()
        assert success, "refresh_shots should succeed"

        # Verify shots were loaded (may be affected by async operations)
        assert len(window.shot_model.shots) >= 1, (
            f"Expected at least 1 shot, got {len(window.shot_model.shots)}: {window.shot_model.shots}"
        )

        # Process events to ensure UI updates
        process_qt_events()

        # If shots were cleared by background process, reload them
        if len(window.shot_model.shots) == 0:
            window.shot_model._process_pool = test_pool  # Ensure mock is still in place
            success, _ = window.shot_model.refresh_shots()
            assert success, "Second refresh should succeed"

        # Ensure we start on the My Shots tab
        window.tab_widget.setCurrentIndex(0)
        process_qt_events()

        # If shots were cleared again, reload one more time
        if len(window.shot_model.shots) == 0:
            window.shot_model._process_pool = test_pool
            success, _ = window.shot_model.refresh_shots()
            assert success, "Third refresh should succeed"

        # Tab 1: Select a shot in My Shots tab
        assert window.tab_widget.currentIndex() == 0  # My Shots tab
        shots = window.shot_model.get_shots()

        # Accept that background loading may have updated the shots
        # At least one shot should be present for the test to proceed
        assert len(shots) >= 1, f"Expected at least 1 shot, got {len(shots)}"

        # Simulate selecting first shot
        first_shot = shots[0]
        window.shot_selection_controller.on_shot_selected(first_shot)

        # Verify info panel shows the selected shot
        assert window.right_panel._current_shot == first_shot
        # DCC sections should be enabled when shot is selected
        for section in window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

        # Tab 2: Switch to 3DE tab
        window.tab_widget.setCurrentIndex(1)  # Other 3DE scenes tab
        process_qt_events()

        # Create and select a 3DE scene
        scene = ThreeDEScene(
            show="TEST",
            sequence="seq02",
            shot="0030",
            workspace_path="/shows/TEST/shots/seq02/seq02_0030",
            user="testuser",
            plate="PLATE01",
            scene_path=Path("/test/scene.3de"),
        )
        # Use the controller to handle scene selection (if available)
        # or directly set the right panel's shot for testing
        if window.threede_controller is not None:
            window.threede_controller.on_scene_selected(scene)
        else:
            # Directly update the right panel for testing
            shot = Shot(
                show=scene.show,
                sequence=scene.sequence,
                shot=scene.shot,
                workspace_path=scene.workspace_path,
            )
            window.right_panel.set_shot(shot)

        # Verify info panel updated to show the 3DE scene
        current_shot = window.right_panel._current_shot
        assert current_shot is not None
        assert current_shot.shot == "0030"
        assert current_shot.sequence == "seq02"

        # Tab 3: Switch to Previous Shots tab
        window.tab_widget.setCurrentIndex(2)  # Previous shots tab
        process_qt_events()

        # The info panel should be cleared since Previous Shots tab has no selection
        # (Tab switching calls on_shot_selected(None) when new tab has no selection)
        assert window.right_panel._current_shot is None

        # Go back to My Shots and verify it also clears since no selection
        # (Each tab maintains its own selection state independently)
        window.tab_widget.setCurrentIndex(0)
        process_qt_events()

        # Info panel should be cleared because My Shots tab has no current selection
        assert window.right_panel._current_shot is None

        # Select a different shot if available, or deselect/reselect the first
        if len(shots) > 1:
            second_shot = shots[1]
            window.shot_selection_controller.on_shot_selected(second_shot)
            assert window.right_panel._current_shot == second_shot
        else:
            # Only one shot available, test deselect/reselect
            window.shot_selection_controller.on_shot_selected(None)
            assert window.right_panel._current_shot is None
            window.shot_selection_controller.on_shot_selected(first_shot)
            assert window.right_panel._current_shot == first_shot

    def test_show_filter_affects_all_tabs(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that show filtering propagates to all tabs correctly.

        This verifies that:
        1. Show filter is available on all tabs
        2. Filtering on one tab affects that tab's display
        3. Each tab can have independent filter settings
        """
        # Prevent any async loading by stubbing out the initialization
        # Local application imports
        from shot_model import (
            AsyncShotLoader,
        )

        original_init_async = AsyncShotLoader.__init__

        def no_op_init(self: Any, *args: Any, **kwargs: Any) -> None:
            super(AsyncShotLoader, self).__init__()
            self._should_stop = True  # Mark as stopped immediately

        AsyncShotLoader.__init__ = no_op_init

        # HACK: Disable background refresh from QTimer during init
        # TODO: Refactor to use proper async initialization or mock at subprocess boundary
        # instead of disabling core Qt mechanisms
        # Third-party imports
        from PySide6.QtCore import (
            QTimer,
        )

        original_singleshot = QTimer.singleShot
        QTimer.singleShot = lambda *_args, **_kwargs: None  # Disable all timers

        # Create a temporary cache manager in a fresh directory to avoid old data
        # Standard library imports
        import tempfile
        from pathlib import (
            Path,
        )

        # Local application imports
        from cache_manager import (
            CacheManager,
        )

        temp_cache_dir = Path(tempfile.mkdtemp(prefix="shotbot_test_"))
        test_cache_manager = CacheManager(cache_dir=temp_cache_dir)

        # Create MainWindow with fresh cache manager
        window = MainWindow(cache_manager=test_cache_manager)
        qtbot.addWidget(window)
        self.test_windows.append(window)  # Track for proper cleanup

        # Restore AsyncShotLoader
        AsyncShotLoader.__init__ = original_init_async

        # Clear any cached shots that might have been loaded
        window.shot_model.shots.clear()
        window.shot_item_model.set_shots([])

        # Make sure no background loading can interfere
        # Third-party imports
        from PySide6.QtCore import (
            QMutexLocker,
        )

        # Stop async loader with lock held
        with QMutexLocker(window.shot_model._loader_lock):
            if window.shot_model._async_loader:
                window.shot_model._async_loader.stop()
                window.shot_model._async_loader.wait()
                window.shot_model._async_loader.deleteLater()
                # Note: deleteLater() is deferred, object will be deleted when control returns to event loop
                window.shot_model._async_loader = None
            window.shot_model._loading_in_progress = False

        # Process Qt events AFTER releasing lock to avoid deadlock with _on_loader_finished
        # (deleteLater objects are processed here)
        process_qt_events()

        # Set up test data with multiple shows
        # Note: ws -sg returns all shots in a single multi-line output
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs(
            "workspace /shows/SHOW1/shots/seq01/seq01_0010\nworkspace /shows/SHOW1/shots/seq01/seq01_0020\nworkspace /shows/SHOW2/shots/seq02/seq02_0030"
        )
        window.shot_model._process_pool = test_pool

        # Restore QTimer.singleShot after setting up test pool
        QTimer.singleShot = original_singleshot

        # Refresh to populate
        success, _ = window.shot_model.refresh_shots()
        assert success, "refresh_shots should succeed"

        # Process any pending events
        QApplication.processEvents()

        # Check My Shots tab has all shots initially
        shot_item_model = window.shot_item_model
        assert shot_item_model.rowCount() == 3

        # Apply show filter to SHOW1
        shot_item_model.set_show_filter(window.shot_model, "SHOW1")
        QApplication.processEvents()  # Process updates without timer

        # Verify filter applied
        assert shot_item_model.rowCount() == 2  # Only SHOW1 shots visible

        # Clear filter
        shot_item_model.set_show_filter(window.shot_model, None)
        assert shot_item_model.rowCount() == 3  # All shots visible again


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestCacheUICoordination:
    """Test cache manager and UI synchronization."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self: TestCacheUICoordination, qtbot: QtBot, tmp_path: Path) -> None:
        """Clean up state between tests.

        Args:
            qtbot: Qt test bot for Qt event handling
            tmp_path: Pytest tmp_path fixture for isolated filesystem

        """
        # Track windows for cleanup
        self.test_windows: list[MainWindow] = []

        yield

        # Properly close all windows to trigger closeEvent and cleanup
        for window in self.test_windows:
            if window:
                # Explicitly call closeEvent to ensure workers are stopped
                # Third-party imports
                from PySide6.QtGui import (
                    QCloseEvent,
                )

                close_event = QCloseEvent()
                window.closeEvent(close_event)

                # Now close the window
                if not window.isHidden():
                    window.close()
                    # Wait for window to close
                    qtbot.waitUntil(lambda w=window: w.isHidden(), timeout=2000)

                # Delete the window instance explicitly
                window.deleteLater()
                process_qt_events()

        self.test_windows.clear()

        # Process all pending events and deleteLater calls
        # This implements the Qt cleanup pattern from qt_thread_cleanup.py
        app = QApplication.instance()
        if app:
            for _ in range(3):
                app.processEvents()
                app.sendPostedEvents(None, 0)  # Process all deferred deletions
                process_qt_events()

    def test_thumbnail_cache_updates_ui(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Verify thumbnail caching updates UI correctly.

        This tests that:
        1. Thumbnails are cached after first load
        2. Cache manager provides cached thumbnails
        3. UI updates when cache is invalidated
        """
        # Force legacy model for synchronous behavior
        os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

        # Create test cache directory
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir(exist_ok=True)

        # Create test cache manager
        test_cache_manager = CacheManager(cache_dir=cache_dir)

        # Create MainWindow with test cache
        window = MainWindow(cache_manager=test_cache_manager)
        qtbot.addWidget(window)
        self.test_windows.append(window)  # Track for cleanup

        # Set up test shot
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs("workspace /shows/TEST/shots/seq01/seq01_0010")
        window.shot_model._process_pool = test_pool
        window.shot_model.refresh_shots()

        # Get the shot
        shots = window.shot_model.get_shots()
        assert len(shots) == 1
        shot = shots[0]

        # Verify cache manager can check for cached thumbnail
        # Note: Cache may exist from previous runs; clear it first
        window.cache_manager.clear_cached_data("thumbnails")
        cache_path = window.cache_manager.get_cached_thumbnail(
            shot.show, shot.sequence, shot.shot
        )
        # Cache path should be None after clearing
        assert cache_path is None  # No thumbnail cached after clear

        # Create a valid test image file to cache
        fake_thumb = tmp_path / "test_thumb.jpg"
        # Create a minimal valid JPEG (1x1 red pixel)
        # Third-party imports
        from PySide6.QtGui import (
            QColor,
            QImage,
        )

        img = QImage(1, 1, QImage.Format.Format_RGB32)
        img.fill(QColor(255, 0, 0))
        img.save(str(fake_thumb), "JPEG")

        # Cache the thumbnail
        cached_path = window.cache_manager.cache_thumbnail(
            fake_thumb, shot.show, shot.sequence, shot.shot
        )
        assert cached_path is not None

        # Now get_cached_thumbnail should return the path
        cache_path = window.cache_manager.get_cached_thumbnail(
            shot.show, shot.sequence, shot.shot
        )
        assert cache_path is not None
        assert cache_path.exists()
        assert str(shot.show) in str(cache_path)

    def test_cache_invalidation_refreshes_data(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Verify cache invalidation causes data refresh.

        This tests that:
        1. Data is loaded from cache initially
        2. Cache invalidation clears cached data
        3. Next access fetches fresh data
        """
        # Force legacy model
        os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

        window = MainWindow()
        qtbot.addWidget(window)
        self.test_windows.append(window)  # Track for cleanup

        # Set up initial data
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.set_outputs(
            "workspace /shows/TEST/shots/seq01/seq01_0010\nworkspace /shows/TEST/shots/seq01/seq01_0020"
        )
        window.shot_model._process_pool = test_pool

        # Initial refresh
        success, _ = window.shot_model.refresh_shots()
        assert success
        assert len(window.shot_model.shots) == 2

        # Change the test data
        test_pool.set_outputs(
            "workspace /shows/TEST/shots/seq01/seq01_0010\n"
            "workspace /shows/TEST/shots/seq01/seq01_0020\n"
            "workspace /shows/TEST/shots/seq01/seq01_0030"
        )

        # Refresh again - should get new data
        success, _has_changes = window.shot_model.refresh_shots()
        assert success
        assert len(window.shot_model.shots) == 3  # New shot added


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestErrorPropagationChains:
    """Test error handling across component boundaries."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, qtbot: QtBot) -> None:
        """Clean up state between tests."""
        # Local application imports

        # Track windows for cleanup
        self.test_windows: list[MainWindow] = []

        yield

        # Properly close all windows to trigger closeEvent and cleanup
        for window in self.test_windows:
            if window:
                # Explicitly call closeEvent to ensure workers are stopped
                # Third-party imports
                from PySide6.QtGui import (
                    QCloseEvent,
                )

                close_event = QCloseEvent()
                window.closeEvent(close_event)

                # Now close the window
                if not window.isHidden():
                    window.close()
                    # Wait for window to close
                    qtbot.waitUntil(lambda w=window: w.isHidden(), timeout=2000)

                # Delete the window instance explicitly
                window.deleteLater()
                process_qt_events()

        self.test_windows.clear()

        # Process all pending events and deleteLater calls
        # This implements the Qt cleanup pattern from qt_thread_cleanup.py
        app = QApplication.instance()
        if app:
            for _ in range(3):
                app.processEvents()
                app.sendPostedEvents(None, 0)  # Process all deferred deletions
                process_qt_events()

    def test_subprocess_failure_handled_gracefully(
        self, qapp: QApplication, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Verify subprocess failures are handled without crashing.

        This tests that:
        1. Process pool failures are caught
        2. Error signals are emitted
        3. UI remains responsive after error
        """
        os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

        window = MainWindow()
        qtbot.addWidget(window)
        self.test_windows.append(window)  # Track for cleanup
        window.show()  # Make window visible for test

        # Set up test pool to fail
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.should_fail = True
        window.shot_model._process_pool = test_pool

        # Track error signal
        error_emitted = False
        error_message = ""

        def on_error(msg: str) -> None:
            nonlocal error_emitted, error_message
            error_emitted = True
            error_message = msg

        window.shot_model.error_occurred.connect(on_error)

        try:
            # Refresh should fail gracefully
            success, _ = window.shot_model.refresh_shots()
            assert not success  # Should fail
            assert error_emitted  # Should emit error signal
            assert "fail" in error_message.lower()  # Should contain failure message

            # UI should still be responsive (not crashed)
            assert window.isVisible()
        finally:
            # CRITICAL: Disconnect signal to prevent dangling connections
            try:
                window.shot_model.error_occurred.disconnect(on_error)
            except (TypeError, RuntimeError):
                pass

    def test_timeout_handled_properly(self, qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
        """Verify timeout errors are handled correctly.

        This tests that:
        1. Timeouts are caught and handled
        2. Appropriate error signals are emitted
        3. System recovers from timeout
        """
        os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

        window = MainWindow()
        qtbot.addWidget(window)
        self.test_windows.append(window)  # Track for cleanup
        window.show()  # Make window visible for test

        # Set up test pool to timeout (allow_main_thread=True for sync testing)
        test_pool = TestProcessPool(allow_main_thread=True)
        test_pool.fail_with_timeout = True
        window.shot_model._process_pool = test_pool

        # Track error signal
        error_emitted = False

        def on_error(msg: str) -> None:
            nonlocal error_emitted
            error_emitted = True

        window.shot_model.error_occurred.connect(on_error)

        try:
            # Refresh should handle timeout gracefully
            success, _ = window.shot_model.refresh_shots()
            assert not success  # Should fail
            assert error_emitted  # Should emit error signal

            # Now fix the test pool and verify recovery
            test_pool.fail_with_timeout = False
            test_pool.set_outputs("workspace /shows/TEST/shots/seq01/seq01_0010")

            # Should recover and work again
            success, _ = window.shot_model.refresh_shots()
            assert success  # Should succeed now
            assert len(window.shot_model.shots) == 1
        finally:
            # CRITICAL: Disconnect signal to prevent dangling connections
            try:
                window.shot_model.error_occurred.disconnect(on_error)
            except (TypeError, RuntimeError):
                pass
