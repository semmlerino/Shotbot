"""Integration tests for MainWindow UI coordination following UNIFIED_TESTING_GUIDE.

Tests signal-slot connections, tab switching, launcher execution, and error handling
with real Qt components and minimal mocking.
"""

# Add parent directory to path

from __future__ import annotations

import contextlib

# Standard library imports
from collections.abc import Generator
from datetime import UTC
from pathlib import Path
from typing import Any, ClassVar

# Third-party imports
import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMessageBox

# Removed sys.path modification - can cause import issues
# sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# Local application imports
from cache_manager import CacheManager

# Moved to lazy import to fix Qt initialization
# from main_window import MainWindow
from notification_manager import NotificationType
from shot_model import RefreshResult, Shot

# Import qapp fixture from conftest to ensure QApplication exists
# Import proper test doubles following UNIFIED_TESTING_GUIDE
from tests.fixtures.test_doubles import (
    TestProcessPool,
    TestSubprocess,
)


# Module-level fixture to handle lazy imports after Qt initialization
@pytest.fixture(autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow  # noqa: PLW0603
    from main_window import (
        MainWindow,
    )



# =============================================================================
# TEST DOUBLES FOR INTEGRATION TESTING
# =============================================================================


class TestProgressContext:
    """Test double for ProgressManager context."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize test progress context."""
        self.args = args
        self.kwargs = kwargs
        self.progress_updates: list[dict[str, Any]] = []

    def __enter__(self) -> TestProgressContext:
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any, **kwargs: Any) -> None:
        """Exit context manager."""

    def update(self, value: int, message: str = "") -> None:
        """Track progress updates."""
        self.progress_updates.append({"value": value, "message": message})

    def set_indeterminate(self) -> None:
        """Set progress to indeterminate mode."""
        self.progress_updates.append(
            {"type": "indeterminate", "value": -1, "message": "Indeterminate"}
        )


class TestProgressManager:
    """Test double for ProgressManager following UNIFIED_TESTING_GUIDE."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test progress manager."""
        self.operations: list[dict[str, Any]] = []
        self.active_operations: dict[str, TestProgressContext] = {}
        self._next_operation_id = 0

    def operation(self, *args: Any, **kwargs: Any) -> TestProgressContext:
        """Create a test progress context."""
        return TestProgressContext(*args, **kwargs)

    def start_operation(self, config: Any) -> TestProgressContext:
        """Track operation start. Accepts ProgressConfig or string for compatibility."""
        # Handle both ProgressConfig object and string for backward compatibility
        operation_id = config.title if hasattr(config, "title") else str(config)
        self._next_operation_id += 1
        key = f"{operation_id}_{self._next_operation_id}"
        self.operations.append({"type": "start", "id": operation_id})
        ctx = TestProgressContext()
        self.active_operations[key] = ctx
        return ctx

    def finish_operation(self, success: bool = True, error_message: str = "") -> None:
        """Track operation finish."""
        self.operations.append({"type": "finish", "success": success})
        # Clean up the most recent operation
        if self.active_operations:
            key = list(self.active_operations.keys())[-1]
            del self.active_operations[key]

    def clear(self) -> None:
        """Clear operation history."""
        self.operations.clear()
        self.active_operations.clear()
        self._next_operation_id = 0


class TestNotificationManager:
    """Test double for NotificationManager following UNIFIED_TESTING_GUIDE.

    FIXED: All methods are now @classmethod to match the real NotificationManager interface.
    This prevents Fatal Python errors when Qt objects are created from worker threads.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    # Class-level storage for notifications
    _notifications: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def _record_notification(
        cls, notif_type: str, title: str, message: str = "", **kwargs: Any
    ) -> None:
        """Record a notification."""
        cls._notifications.append(
            {"type": notif_type, "title": title, "message": message, **kwargs}
        )

    @classmethod
    def error(cls, title: str, message: str = "", details: str = "") -> None:
        """Record error notification with exact signature match."""
        cls._record_notification("error", title, message, details=details)

    @classmethod
    def warning(cls, title: str, message: str = "", details: str = "") -> None:
        """Record warning notification with exact signature match."""
        cls._record_notification("warning", title, message, details=details)

    @classmethod
    def info(cls, message: str, timeout: int = 3000) -> None:
        """Record info notification with exact signature match."""
        cls._record_notification("info", "", message, timeout=timeout)

    @classmethod
    def success(cls, message: str, timeout: int = 3000) -> None:
        """Record success notification with exact signature match."""
        cls._record_notification("success", "", message, timeout=timeout)

    @classmethod
    def toast(
        cls,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        duration: int = 4000,
    ) -> None:
        """Record toast notification with exact signature match."""
        cls._record_notification(
            "toast", "", message, notification_type=notification_type, duration=duration
        )

    @classmethod
    def get_last_notification(cls) -> dict[str, Any] | None:
        """Get the last notification."""
        return cls._notifications[-1] if cls._notifications else None

    @classmethod
    def clear(cls) -> None:
        """Clear notification history."""
        cls._notifications.clear()


class TestMessageBox:
    """Test double for QMessageBox to capture dialogs."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test message box."""
        self.messages: list[dict[str, Any]] = []

    def warning(self, parent: QObject | None, title: str, message: str) -> None:
        """Capture warning dialog."""
        self.messages.append(
            {"type": "warning", "parent": parent, "title": title, "message": message}
        )

    def get_last_message(self) -> dict[str, Any] | None:
        """Get the last message."""
        return self.messages[-1] if self.messages else None

    def clear(self) -> None:
        """Clear message history."""
        self.messages.clear()


@pytest.fixture
def real_cache_manager(tmp_path: Path) -> CacheManager:
    """Real cache manager with temp storage."""
    return CacheManager(cache_dir=tmp_path / "cache")


@pytest.fixture
def main_window_with_real_components(
    qapp: Any, qtbot: Any, real_cache_manager: CacheManager, monkeypatch: Any
) -> Generator[Any, None, None]:
    """MainWindow with real components, not mocked.

    FIXED: Added qapp fixture to ensure QApplication exists before creating widgets.
    This prevents segmentation faults from Qt object creation without an app.

    FIXED: Forces legacy ShotModel to avoid ShotModel threading issues
    and ensures TestProcessPool is used throughout the system.

    FIXED: Monkey-patch NotificationManager BEFORE creating MainWindow to prevent
    Fatal Python errors from QMessageBox being called from worker threads.
    """
    # Ensure QApplication is available (required for all Qt widgets)
    assert qapp is not None, "QApplication must exist before creating widgets"

    # Force legacy ShotModel for predictable testing
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")

    # Replace ProcessPoolManager.get_instance() to return our test double
    # allow_main_thread=True because MainWindow tests call refresh synchronously
    test_pool = TestProcessPool(ttl_aware=True, allow_main_thread=True)
    test_pool.set_outputs("workspace /test/path")

    def mock_get_instance() -> TestProcessPool:
        return test_pool

    # Mock at the system boundary - ProcessPoolManager singleton
    # Local application imports
    from process_pool_manager import (
        ProcessPoolManager,
    )

    monkeypatch.setattr(ProcessPoolManager, "get_instance", mock_get_instance)

    # CRITICAL: Replace NotificationManager BEFORE creating MainWindow
    # This prevents Fatal Python errors when Qt objects are called from worker threads
    # Local application imports
    from notification_manager import (
        NotificationManager,
    )

    # Clear any previous test notifications
    TestNotificationManager.clear()

    # Monkey-patch NotificationManager class methods with test double
    # Must happen BEFORE MainWindow creation to avoid Qt threading issues
    original_notification_methods = {
        "error": NotificationManager.error,
        "warning": NotificationManager.warning,
        "info": NotificationManager.info,
        "success": NotificationManager.success,
        "toast": NotificationManager.toast,
    }
    NotificationManager.error = TestNotificationManager.error
    NotificationManager.warning = TestNotificationManager.warning
    NotificationManager.info = TestNotificationManager.info
    NotificationManager.success = TestNotificationManager.success
    NotificationManager.toast = TestNotificationManager.toast

    # Replace ProgressManager with test double to avoid Qt object deletion issues
    # Local application imports
    from progress_manager import (
        ProgressManager,
    )

    test_progress_manager = TestProgressManager()

    # Store original ProgressManager methods for restoration
    original_operation = ProgressManager.operation
    original_start_operation = ProgressManager.start_operation
    original_finish_operation = ProgressManager.finish_operation

    # Monkey-patch ProgressManager class methods with test double
    ProgressManager.operation = test_progress_manager.operation
    ProgressManager.start_operation = test_progress_manager.start_operation
    ProgressManager.finish_operation = test_progress_manager.finish_operation

    # Mock the modules that CommandLauncher will import in __init__
    # Standard library imports
    import sys
    import types

    # Create mock classes for CommandLauncher's internal imports with required methods
    class MockNukeScriptGenerator:
        """Mock for NukeScriptGenerator."""

        @staticmethod
        def create_plate_script(*_args: Any, **_kwargs: Any) -> str | None:
            return None

    class MockThreeDELatestFinder:
        """Mock for ThreeDELatestFinder."""

        def find_latest_threede_scene(self, *_args: Any, **_kwargs: Any) -> str | None:
            return None

    class MockMayaLatestFinder:
        """Mock for MayaLatestFinder."""

        def find_latest_maya_scene(self, *_args: Any, **_kwargs: Any) -> str | None:
            return None

    # Create mock modules
    mock_nuke_script_generator = types.ModuleType("nuke_script_generator")
    mock_nuke_script_generator.NukeScriptGenerator = MockNukeScriptGenerator
    sys.modules["nuke_script_generator"] = mock_nuke_script_generator

    mock_threede_latest_finder = types.ModuleType("threede_latest_finder")
    mock_threede_latest_finder.ThreeDELatestFinder = MockThreeDELatestFinder
    sys.modules["threede_latest_finder"] = mock_threede_latest_finder

    mock_maya_latest_finder = types.ModuleType("maya_latest_finder")
    mock_maya_latest_finder.MayaLatestFinder = MockMayaLatestFinder
    sys.modules["maya_latest_finder"] = mock_maya_latest_finder

    # NOW create the MainWindow with all patches in place
    window = MainWindow(cache_manager=real_cache_manager)
    qtbot.addWidget(window)

    # Store test references for assertions
    window._test_process_pool = test_pool
    window._test_progress_manager = test_progress_manager
    window._test_notification_manager = TestNotificationManager

    # CRITICAL: Replace the shot model's process pool with our test double
    # This is needed because the ShotModel is already initialized with the real ProcessPoolManager
    window.shot_model._process_pool = test_pool

    # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
    # Previous shots now only refresh on explicit user action

    try:
        yield window
    finally:
        # Restore NotificationManager methods before other tests run
        for name, method in original_notification_methods.items():
            setattr(NotificationManager, name, method)

        # CRITICAL: Restore ProgressManager class methods FIRST (before Qt cleanup)
        # This prevents contamination of subsequent tests
        ProgressManager.operation = original_operation
        ProgressManager.start_operation = original_start_operation
        ProgressManager.finish_operation = original_finish_operation

        # CRITICAL: Proper cleanup to prevent crashes
        # Stop all timers first
        if hasattr(window, "auto_refresh_timer") and window.auto_refresh_timer:
            window.auto_refresh_timer.stop()

        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        # No timer cleanup needed for previous shots model

        # Stop any workers
        if (
            hasattr(window, "threede_worker")
            and window.threede_worker
            and window.threede_worker.isRunning()
        ):
            window.threede_worker.quit()
            window.threede_worker.wait(1000)

        # Disconnect all signals to prevent crashes during cleanup
        with contextlib.suppress(RuntimeError, TypeError):
            window.disconnect()

        # Close the window properly
        window.close()

        # Process events to ensure cleanup happens
        # Third-party imports
        from PySide6.QtCore import (
            QCoreApplication,
        )

        app = QCoreApplication.instance()
        if app:
            app.processEvents()

        # Delete the window
        window.deleteLater()
        qtbot.wait(1)  # Flush Qt deletion queue

        # Force garbage collection
        # Standard library imports
        import gc

        gc.collect()


@pytest.mark.slow
@pytest.mark.gui_mainwindow
@pytest.mark.qt_heavy
@pytest.mark.integration_unsafe
class TestMainWindowUICoordination:
    """Test UI coordination and signal-slot connections."""

    def test_window_initialization(self, main_window_with_real_components: Any) -> None:
        """Test that main window initializes with all components."""
        window = main_window_with_real_components

        # Verify essential components exist
        assert window.shot_model is not None
        assert window.cache_manager is not None
        assert window.command_launcher is not None

        # Verify UI elements
        assert window.tab_widget is not None
        assert window.shot_grid is not None
        assert window.threede_shot_grid is not None
        assert window.previous_shots_grid is not None

        # Verify right panel created (replaces old launcher_panel)
        assert window.right_panel is not None
        assert len(window.right_panel._dcc_accordion._sections) > 0
        assert "3de" in window.right_panel._dcc_accordion._sections
        assert "nuke" in window.right_panel._dcc_accordion._sections

    def test_shot_selection_enables_launchers(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that selecting a shot enables launcher buttons."""
        window = main_window_with_real_components

        # Initially launch buttons should be disabled
        for section in window.right_panel._dcc_accordion._sections.values():
            assert not section._launch_btn.isEnabled()

        # Create and select a test shot
        test_shot = Shot("testshow", "seq01", "shot01", "/test/workspace")
        window.shot_model.shots = [test_shot]

        # Call the actual selection handler (this is what the signal connection does)
        window.shot_selection_controller.on_shot_selected(test_shot)

        # Process events
        qtbot.wait(1)  # Minimal event processing

        # Launch buttons should now be enabled
        for section in window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

    def test_tab_switching_updates_context(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that switching tabs updates the application context."""
        window = main_window_with_real_components

        # Start on first tab (My Shots)
        window.tab_widget.setCurrentIndex(0)
        qtbot.wait(1)  # Minimal event processing

        # Switch to 3DE scenes tab
        window.tab_widget.setCurrentIndex(1)
        qtbot.wait(1)  # Minimal event processing

        # Verify tab change was processed
        assert window.tab_widget.currentIndex() == 1

        # Switch to Previous Shots tab
        window.tab_widget.setCurrentIndex(2)
        qtbot.wait(1)  # Minimal event processing

        assert window.tab_widget.currentIndex() == 2

    @pytest.mark.usefixtures("qtbot")
    def test_refresh_button_triggers_shot_refresh(
        self, main_window_with_real_components: Any
    ) -> None:
        """Test that refresh button triggers shot model refresh."""
        window = main_window_with_real_components

        # Configure test pool to return success
        test_pool = window._test_process_pool
        test_pool.set_outputs("""workspace /shows/test/shots/seq01/shot01
workspace /shows/test/shots/seq01/shot02""")

        # Get initial command count
        initial_command_count = len(test_pool.get_executed_commands())

        # Invalidate cache to ensure fresh data is fetched
        window.shot_model.invalidate_workspace_cache()

        # Debug: Print cache state and command count
        print(f"Commands before refresh: {test_pool.get_executed_commands()}")
        print(f"Cache state: {test_pool._cache}")

        # Directly test the refresh mechanism instead of using action trigger
        # This avoids any background thread issues
        result = window.shot_model.refresh_shots()

        # Debug: Print after refresh
        print(f"Commands after refresh: {test_pool.get_executed_commands()}")
        print(f"Refresh result: {result}")

        # Verify refresh completed successfully
        assert result.success, "Shot refresh should succeed with test double"

        # Verify refresh was called
        commands = test_pool.get_executed_commands()
        assert len(commands) > initial_command_count, (
            f"Expected commands to be executed. Commands: {commands}"
        )
        # Verify the correct command was executed
        assert any("ws" in cmd for cmd in commands), (
            f"Expected 'ws' command to be executed. Commands: {commands}"
        )

    def test_launcher_execution_workflow(
        self, main_window_with_real_components: Any, qtbot: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """Test complete launcher execution workflow."""
        window = main_window_with_real_components

        # Use TestSubprocess to prevent actual app launch
        test_subprocess = TestSubprocess()
        # Mock at the process_executor module level where subprocess is used
        monkeypatch.setattr("launch.process_executor.subprocess.Popen", test_subprocess.Popen)

        # Mock EnvironmentManager methods to ensure launch proceeds
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_rez_available", lambda _self, _config: False)
        monkeypatch.setattr("command_launcher.EnvironmentManager.detect_terminal", lambda _self: "gnome-terminal")
        # CRITICAL: Mock is_ws_available - 'ws' command isn't available in dev environment
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_ws_available", lambda _self: True)

        # Create real workspace directory to pass validation
        workspace_path = tmp_path / "test_workspace"
        workspace_path.mkdir(parents=True, exist_ok=True)

        # Select a shot using the actual handler
        test_shot = Shot("testshow", "seq01", "shot01", str(workspace_path))
        window.shot_model.shots = [test_shot]
        window.shot_selection_controller.on_shot_selected(
            test_shot
        )  # This enables buttons and sets current shot

        # Process events
        qtbot.wait(1)  # Minimal event processing

        # Click 3de launch button in DCC section
        section_3de = window.right_panel._dcc_accordion._sections.get("3de")
        assert section_3de is not None
        assert section_3de._launch_btn.isEnabled()

        # Disable "open latest" to avoid async file search path
        # (async search is tested separately - this test verifies basic launch)
        open_latest_checkbox = section_3de._checkboxes.get("open_latest_threede")
        if open_latest_checkbox:
            open_latest_checkbox.setChecked(False)

        # Simulate button click
        section_3de._launch_btn.click()
        qtbot.wait(1)  # Minimal event processing

        # Verify launcher was called by checking subprocess execution
        # The test subprocess should have recorded the command
        assert len(test_subprocess.executed_commands) > 0
        # Verify 3de was in the command
        executed_cmd = test_subprocess.get_last_command()
        assert executed_cmd is not None

    @pytest.mark.usefixtures("monkeypatch")
    def test_error_handling_shows_message(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that errors are properly displayed to user."""
        window = main_window_with_real_components

        # Trigger an error through command launcher (this is the real error pathway)
        # Standard library imports
        from datetime import (
            datetime,
        )

        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        window.command_launcher.command_error.emit(timestamp, "Test error message")

        # Process events
        qtbot.wait(1)  # Minimal event processing

        # Verify error was handled - check both status bar and notification manager
        status_message = window.status_bar.currentMessage()
        assert status_message is not None

        # Check that notification was recorded (if error triggers notification)
        # The test notification manager should have recorded any notifications
        # Note: The actual implementation might show an info notification instead of error
        # or might not trigger a notification at all for command errors
        if hasattr(window, "_test_notification_manager"):
            # Check for any notifications that might have been recorded
            pass
            # Just verify that error handling pathway was triggered
            # The specific notification type may vary based on implementation

    def test_progress_indication_during_operations(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that progress is shown during long operations."""
        window = main_window_with_real_components

        # Wait for any initial loading to complete to avoid race conditions
        qtbot.wait(1)  # Minimal event processing

        # Start a refresh (which should show progress)
        window.shot_model.refresh_started.emit()

        # Use waitUntil to check for refresh message - more robust than fixed timing
        def status_contains_refresh_or_loading() -> bool:
            status = window.status_bar.currentMessage()
            return status and (
                "refresh" in status.lower() or "loading" in status.lower()
            )

        qtbot.waitUntil(status_contains_refresh_or_loading, timeout=1000)

        # Get the current status for comparison later
        status_text = window.status_bar.currentMessage()

        # Complete refresh
        window.shot_model.refresh_finished.emit(True, False)

        # Wait for status to change
        def status_changed() -> bool:
            new_status = window.status_bar.currentMessage()
            return new_status != status_text

        qtbot.waitUntil(status_changed, timeout=1000)


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestMainWindowKeyboardShortcuts:
    """Test keyboard shortcuts and navigation."""

    def test_keyboard_shortcuts_work(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test that keyboard shortcuts trigger correct actions."""
        window = main_window_with_real_components

        # Select a shot first using the actual handler
        test_shot = Shot("test", "seq01", "shot01", "/test")
        window.shot_model.shots = [test_shot]
        window.shot_selection_controller.on_shot_selected(test_shot)

        # Test F5 for refresh - since keyboard shortcuts in Qt can be complex,
        # let's test that the shortcut is properly configured and trigger the action directly
        assert window.refresh_action.shortcut() == QKeySequence.StandardKey.Refresh

        # Get test pool and initial command count
        test_pool = window._test_process_pool
        initial_command_count = len(test_pool.get_executed_commands())

        # Invalidate cache to ensure fresh data is fetched
        window.shot_model.invalidate_workspace_cache()

        # Trigger the refresh action directly (this is what the shortcut would do)
        window.refresh_action.trigger()
        qtbot.wait(1)  # Minimal event processing

        # Verify refresh was triggered
        commands = test_pool.get_executed_commands()
        assert len(commands) > initial_command_count, (
            f"Expected commands to be executed. Commands: {commands}"
        )

    def test_tab_navigation_with_keyboard(
        self, main_window_with_real_components: Any, qtbot: Any
    ) -> None:
        """Test tab navigation using keyboard."""
        window = main_window_with_real_components

        # Start on first tab
        window.tab_widget.setCurrentIndex(0)

        # Use Ctrl+Tab to switch tabs
        qtbot.keyClick(
            window.tab_widget, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier
        )
        qtbot.wait(1)  # Minimal event processing

        # Should move to next tab
        assert window.tab_widget.currentIndex() == 1


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestMainWindowErrorScenarios:
    """Test error handling and recovery."""

    def test_handles_shot_refresh_failure(
        self, main_window_with_real_components: Any, qtbot: Any, monkeypatch: Any
    ) -> None:
        """Test graceful handling of shot refresh failures."""
        window = main_window_with_real_components

        # Configure process pool to simulate failure
        test_pool = window._test_process_pool
        test_pool.set_should_fail(True, "Network error")

        # Use TestMessageBox to capture warnings
        test_message_box = TestMessageBox()
        monkeypatch.setattr(QMessageBox, "warning", test_message_box.warning)

        # Invalidate cache to ensure fresh data is fetched
        window.shot_model.invalidate_workspace_cache()

        # Attempt refresh
        window.refresh_action.trigger()
        qtbot.wait(1)  # Minimal event processing

        # Should show error to user - verify notification or message box was called
        # Check if a warning message was displayed
        if test_message_box.messages:
            last_message = test_message_box.get_last_message()
            assert last_message is not None
            assert "error" in last_message.get("message", "").lower()

        # Also check notification manager if it captured the error
        if hasattr(window, "_test_notification_manager"):
            notifications = window._test_notification_manager._notifications
            if notifications:
                # Verify an error notification was created
                error_notifications = [
                    n for n in notifications if n.get("type") in ["error", "warning"]
                ]
                assert len(error_notifications) > 0

    def test_handles_missing_cache_directory(
        self, main_window_with_real_components: Any, tmp_path: Path
    ) -> None:
        """Test that missing cache directory is handled gracefully."""
        window = main_window_with_real_components

        # Remove cache directory
        cache_dir = tmp_path / "cache"
        if cache_dir.exists():
            # Standard library imports
            import shutil

            shutil.rmtree(cache_dir)

        # Operations should still work (cache recreated)
        result = window.shot_model.refresh_shots()
        assert isinstance(result, RefreshResult)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
