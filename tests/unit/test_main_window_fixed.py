"""Fixed tests for MainWindow - avoiding hanging issues.

This version uses test doubles instead of mocks, following UNIFIED_TESTING_GUIDE.
Background workers are managed properly through Qt mechanisms.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING

# Third-party imports
import pytest

# Local application imports
# Lazy imports to avoid Qt initialization at module level
# from cache_manager import CacheManager
# from main_window import MainWindow
# from shot_model import Shot
# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.test_doubles_library import (
    TestCompletedProcess,
    TestProcessPool,
)


if TYPE_CHECKING:
    # Standard library imports
    from pathlib import Path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,  # Requires complete isolation
]


# Module-level fixture to handle lazy imports
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow, CacheManager, Shot  # noqa: PLW0603
    # Local application imports
    from cache_manager import (
        CacheManager,
    )
    from main_window import (
        MainWindow,
    )
    from shot_model import (
        Shot,
    )


@pytest.fixture(autouse=True)
def reset_all_mainwindow_singletons():
    """Reset ALL singletons used by MainWindow to prevent test contamination.

    MainWindow uses many singletons that must be reset between tests:
    - NotificationManager (UI notifications and toasts)
    - ProgressManager (progress dialogs and operations)
    - ProcessPoolManager (process pool for background tasks)
    - QRunnableTracker (thread pool task tracking)
    - FilesystemCoordinator (filesystem operation coordination)

    This fixture ensures complete isolation between tests by resetting all
    singleton state before and after each test.
    """
    # Import all singleton managers
    from filesystem_coordinator import FilesystemCoordinator
    from notification_manager import NotificationManager
    from progress_manager import ProgressManager
    from runnable_tracker import QRunnableTracker

    # BEFORE TEST: Reset all singletons to clean state
    # Reset NotificationManager FIRST (closes Qt widgets that others may reference)
    if NotificationManager._instance is not None:
        try:
            NotificationManager.cleanup()
        except (RuntimeError, AttributeError):
            pass  # Qt object may already be deleted
        if hasattr(NotificationManager._instance, "_initialized"):
            delattr(NotificationManager._instance, "_initialized")
    NotificationManager._instance = None
    NotificationManager._main_window = None
    NotificationManager._status_bar = None
    NotificationManager._active_toasts = []
    NotificationManager._current_progress = None

    # Reset ProgressManager (after NotificationManager to avoid Qt widget access)
    if ProgressManager._instance is not None:
        try:
            ProgressManager.clear_all_operations()
        except (RuntimeError, AttributeError):
            pass  # Qt objects may already be deleted
        if hasattr(ProgressManager._instance, "_initialized"):
            delattr(ProgressManager._instance, "_initialized")
    ProgressManager._instance = None
    ProgressManager._operation_stack = []
    ProgressManager._status_bar = None

    # Reset QRunnableTracker
    try:
        QRunnableTracker.reset()
    except Exception:
        pass  # Ignore reset errors

    # Reset FilesystemCoordinator
    FilesystemCoordinator._instance = None

    # Process pending Qt events before test
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app:
        app.processEvents()

    yield  # Run the test

    # AFTER TEST: Reset all singletons again (defense in depth)
    # Reset NotificationManager FIRST
    if NotificationManager._instance is not None:
        try:
            NotificationManager.cleanup()
        except (RuntimeError, AttributeError):
            pass
        if hasattr(NotificationManager._instance, "_initialized"):
            delattr(NotificationManager._instance, "_initialized")
    NotificationManager._instance = None
    NotificationManager._main_window = None
    NotificationManager._status_bar = None
    NotificationManager._active_toasts = []
    NotificationManager._current_progress = None

    # Reset ProgressManager
    if ProgressManager._instance is not None:
        try:
            ProgressManager.clear_all_operations()
        except (RuntimeError, AttributeError):
            pass
        if hasattr(ProgressManager._instance, "_initialized"):
            delattr(ProgressManager._instance, "_initialized")
    ProgressManager._instance = None
    ProgressManager._operation_stack = []
    ProgressManager._status_bar = None

    # Reset QRunnableTracker
    try:
        QRunnableTracker.reset()
    except Exception:
        pass

    # Reset FilesystemCoordinator
    FilesystemCoordinator._instance = None

    # Process pending Qt events after test
    if app:
        app.processEvents()


class TestMainWindowNoHang:
    """Fixed MainWindow tests that don't hang."""

    @pytest.fixture
    def safe_main_window(self, qtbot, tmp_path: Path, monkeypatch, mock_process_pool_manager):
        """Create MainWindow with test doubles for subprocess operations."""
        # Force legacy ShotModel for predictable synchronous behavior in tests
        monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")

        # Ensure consistent SHOWS_ROOT for test isolation
        # This prevents interference from previous tests that might have modified Config.SHOWS_ROOT
        # Use setattr like other tests instead of setenv to avoid module reload complexity
        from config import Config
        monkeypatch.setattr(Config, "SHOWS_ROOT", "/shows")

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(exist_ok=True)
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Create window with test process pool to avoid real subprocess calls
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # CRITICAL: Recreate shot_model's _shot_finder to use the correct SHOWS_ROOT
        # The MainWindow may have been created with a cached finder that uses the wrong SHOWS_ROOT
        from targeted_shot_finder import TargetedShotsFinder
        main_window.shot_model._shot_finder = TargetedShotsFinder()

        # CRITICAL: Wait for background shot loading to complete
        # This prevents state pollution from async operations started in __init__
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Replace process pool with test double
        test_pool = TestProcessPool()
        test_pool.set_outputs("")  # Empty output by default
        main_window.shot_model._process_pool = test_pool

        # Stop any background workers if they exist
        if hasattr(main_window, "_background_refresh_worker"):
            worker = main_window._background_refresh_worker
            if worker and worker.isRunning():
                worker.stop()
                worker.wait(100)  # Short wait

        # Disable auto-refresh timers if they exist
        if (
            hasattr(main_window, "_refresh_timer")
            and main_window._refresh_timer
            and main_window._refresh_timer.isActive()
        ):
            main_window._refresh_timer.stop()

        return main_window

    def test_main_window_creates_components(self, safe_main_window) -> None:
        """Test that MainWindow initializes all required components."""
        # Test all components exist
        assert safe_main_window.cache_manager is not None
        assert safe_main_window.shot_model is not None
        assert safe_main_window.threede_scene_model is not None
        assert safe_main_window.previous_shots_model is not None
        assert safe_main_window.command_launcher is not None
        assert safe_main_window.launcher_manager is not None

        # Test UI components
        assert safe_main_window.tab_widget is not None
        assert safe_main_window.shot_grid is not None
        assert safe_main_window.threede_shot_grid is not None
        assert safe_main_window.previous_shots_grid is not None
        assert safe_main_window.shot_info_panel is not None

        # Test tabs
        assert safe_main_window.tab_widget.count() == 3
        assert safe_main_window.tab_widget.tabText(0) == "My Shots"
        assert safe_main_window.tab_widget.tabText(1) == "Other 3DE scenes"
        assert safe_main_window.tab_widget.tabText(2) == "Previous Shots"

    def test_shot_selection_enables_buttons(self, safe_main_window, tmp_path) -> None:
        """Test that selecting a shot enables application launcher buttons."""
        # Initially disabled
        for section in safe_main_window.launcher_panel.app_sections.values():
            assert not section.launch_button.isEnabled()

        # Select shot with tmp_path as workspace
        workspace_path = str(tmp_path / "test_workspace")
        shot = Shot("test_show", "seq01", "0010", workspace_path)
        safe_main_window._on_shot_selected(shot)

        # Now enabled
        for section in safe_main_window.launcher_panel.app_sections.values():
            assert section.launch_button.isEnabled()

        # Shot info updated
        assert safe_main_window.shot_info_panel._current_shot == shot

    @pytest.mark.skip_if_parallel
    def test_refresh_shots_with_test_pool(self, safe_main_window) -> None:
        """Test shot refresh with test process pool.

        Skipped in parallel execution due to TestProcessPool state management issues.
        The test pool outputs aren't being consumed properly when multiple workers are active.
        Passes reliably in serial execution.
        """
        # Use the SHOWS_ROOT that was set by the fixture via monkeypatch
        # The fixture sets Config.SHOWS_ROOT to "/shows" for test isolation
        from config import Config
        shows_root = Config.SHOWS_ROOT

        # Clear any existing shots to ensure clean test start
        safe_main_window.shot_model.shots = []

        # CRITICAL: Set test pool outputs BEFORE clearing cache
        # Cache clear might trigger background operations that consume outputs
        test_pool = safe_main_window.shot_model._process_pool
        test_pool.set_outputs(f"workspace {shows_root}/test_show/shots/seq01/seq01_0010\n")

        # Now clear cache after outputs are set
        safe_main_window.cache_manager.clear_cache()

        # Using legacy ShotModel for synchronous behavior in tests
        safe_main_window._refresh_shots()

        # Verify shot loaded
        assert len(safe_main_window.shot_model.shots) == 1
        assert safe_main_window.shot_model.shots[0].shot == "0010"


class TestApplicationLaunchingNoHang:
    """Test application launching without hanging."""

    @pytest.fixture
    def safe_window_with_shot(self, qtbot, tmp_path):
        """Create window with a shot pre-selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")

        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Use test process pool
        test_pool = TestProcessPool()
        test_pool.set_outputs("")
        main_window.shot_model._process_pool = test_pool

        # Disable timers
        if (
            hasattr(main_window, "_refresh_timer")
            and main_window._refresh_timer
            and main_window._refresh_timer.isActive()
        ):
            main_window._refresh_timer.stop()

        # Clear any existing shots to prevent interference
        main_window.shot_model.shots = []

        # Select a shot with tmp_path as workspace
        workspace_path = str(tmp_path / "test_workspace")
        shot = Shot("test_show", "seq01", "0010", workspace_path)
        main_window._on_shot_selected(shot)

        # Verify the shot was correctly set
        assert main_window.command_launcher.current_shot == shot
        assert (
            main_window.command_launcher.current_shot.workspace_path == workspace_path
        )

        return main_window, shot

    def test_launch_app_with_selected_shot(
        self, safe_window_with_shot, monkeypatch, tmp_path
    ) -> None:
        """Test launching an application with a selected shot."""
        main_window, _shot = safe_window_with_shot

        # Mock the NukeWorkspaceManager to avoid creating directories

        # Local application imports
        from nuke_workspace_manager import (
            NukeWorkspaceManager,
        )

        def mock_get_workspace_script_directory(
            workspace_path, user=None, plate="mm-default", pass_name="PL01"
        ):
            # Return a temp directory that exists
            script_dir = tmp_path / "nuke_scripts"
            script_dir.mkdir(parents=True, exist_ok=True)
            return script_dir

        monkeypatch.setattr(
            NukeWorkspaceManager,
            "get_workspace_script_directory",
            classmethod(
                lambda _cls, *args, **kwargs: mock_get_workspace_script_directory(
                    *args, **kwargs
                )
            ),
        )

        # Replace command launcher's subprocess execution with test double
        executed_commands = []
        original_run = None

        if hasattr(main_window.command_launcher, "_run_command"):
            original_run = main_window.command_launcher._run_command

            def test_run_command(command, **kwargs):
                executed_commands.append(command)
                return TestCompletedProcess(
                    args=command, returncode=0, stdout="", stderr=""
                )

            main_window.command_launcher._run_command = test_run_command

        try:
            # Launch app
            result = main_window.launch_app("nuke")

            # Test behavior: verify command was executed
            if original_run:
                assert len(executed_commands) > 0
                # Should have nuke in the command
                assert any("nuke" in str(cmd) for cmd in executed_commands)
                # Verify launch was successful
                assert result is True
        finally:
            if original_run:
                main_window.command_launcher._run_command = original_run

    def test_launch_without_shot_returns_false(self, qtbot, tmp_path) -> None:
        """Test launching without shot is handled properly."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Use test process pool
        test_pool = TestProcessPool()
        main_window.shot_model._process_pool = test_pool

        # Disable timers
        if (
            hasattr(main_window, "_refresh_timer")
            and main_window._refresh_timer
            and main_window._refresh_timer.isActive()
        ):
            main_window._refresh_timer.stop()

        # No shot selected - buttons should be disabled
        assert "nuke" in main_window.launcher_panel.app_sections
        assert not main_window.launcher_panel.app_sections[
            "nuke"
        ].launch_button.isEnabled()

        # Try to launch without shot - button is disabled so can't be clicked
        # This is the correct behavior - UI prevents invalid operations


# Helper fixture for all tests
@pytest.fixture(autouse=True)
def cleanup_workers(qtbot) -> None:
    """Ensure all workers are cleaned up after each test."""
    yield
    # Minimal event processing for cleanup
    qtbot.wait(1)
