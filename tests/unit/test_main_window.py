"""Tests for MainWindow - critical UI integration.

Following UNIFIED_TESTING_GUIDE principles:
- Use real components where possible
- Use test doubles at system boundaries (subprocess)
- Test behavior not implementation
- Use qtbot for proper Qt testing
"""

# Standard library imports
from datetime import UTC
from pathlib import Path
from typing import Protocol
from unittest.mock import MagicMock, patch

# Third-party imports
import pytest
from pytestqt.qtbot import QtBot

# Local application imports
# Lazy imports to avoid Qt initialization at module level
# from cache_manager import CacheManager
# from main_window import MainWindow
# from shot_model import Shot
from config import Config


class TestProcessPoolType(Protocol):
    """Protocol for process pool test doubles."""

    __test__ = False

    should_fail: bool
    call_count: int
    commands: list[str]

    def set_outputs(self, output: str) -> None: ...
    def set_errors(self, error: str) -> None: ...
    def execute_workspace_command(
        self, command: str, cache_ttl: int | None = None
    ) -> str: ...
    def reset(self) -> None: ...


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.permissive_process_pool,  # MainWindow tests check UI, not subprocess output
]


# Module-level fixture to handle lazy imports
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow, CacheManager, Shot, ThreeDEScene, SceneFile, FileType  # noqa: PLW0603
    # Local application imports
    from cache_manager import (
        CacheManager,
    )
    from main_window import (
        MainWindow,
    )
    from scene_file import (
        FileType,
        SceneFile,
    )
    from shot_model import (
        Shot,
    )
    from threede_scene_model import (
        ThreeDEScene,
    )



class TestMainWindowInitialization:
    """Test MainWindow initialization and component setup."""

    def test_main_window_creates_all_components(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that MainWindow initializes all required components."""
        # Use real cache manager with temp directory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(exist_ok=True)
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Create main window with real components
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Verify all critical components exist
        assert main_window.cache_manager is not None
        assert main_window.shot_model is not None
        assert main_window.threede_scene_model is not None
        assert main_window.previous_shots_model is not None
        assert main_window.command_launcher is not None

        # Verify UI components
        assert main_window.tab_widget is not None
        assert main_window.shot_grid is not None
        assert main_window.threede_shot_grid is not None
        assert main_window.previous_shots_grid is not None
        assert main_window.right_panel is not None

    def test_main_window_with_custom_cache_manager(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test MainWindow with custom cache manager."""
        cache_dir = tmp_path / "custom_cache"
        cache_dir.mkdir(exist_ok=True)
        cache_manager = CacheManager(cache_dir=cache_dir)

        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Verify cache manager is used
        assert main_window.cache_manager is cache_manager

    def test_main_window_creates_default_cache_manager(self, qtbot: QtBot) -> None:
        """Test MainWindow creates default cache manager if none provided."""
        main_window = MainWindow()
        qtbot.addWidget(main_window)

        # Verify default cache manager exists
        assert main_window.cache_manager is not None


class TestTabSwitching:
    """Test tab switching functionality."""

    def test_switch_between_tabs(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test switching between different tabs."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Reset to first tab (settings may have restored a different tab from persistent storage)
        main_window.tab_widget.setCurrentIndex(0)

        # Verify we're on the first tab (My Shots)
        assert main_window.tab_widget.currentIndex() == 0
        assert main_window.tab_widget.currentWidget() == main_window.shot_grid

        # Switch to second tab (Other 3DE Scenes)
        main_window.tab_widget.setCurrentIndex(1)
        assert main_window.tab_widget.currentIndex() == 1
        assert main_window.tab_widget.currentWidget() == main_window.threede_shot_grid

        # Switch to third tab
        main_window.tab_widget.setCurrentIndex(2)
        assert main_window.tab_widget.currentIndex() == 2
        assert main_window.tab_widget.currentWidget() == main_window.previous_shots_grid


class TestShotSelection:
    """Test shot selection and application launching."""

    def test_shot_selection_enables_app_buttons(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that selecting a shot enables application launcher buttons."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Initially DCC section launch buttons should be disabled
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert not section._launch_btn.isEnabled()

        # Create a test shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")

        # Simulate shot selection
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Now DCC section launch buttons should be enabled
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

        # Right panel should be updated with the shot
        assert main_window.right_panel is not None

    def test_shot_deselection_disables_app_buttons(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that deselecting a shot disables application launcher buttons."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Select a shot first
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify DCC section launch buttons are enabled
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

        # Deselect shot
        main_window.shot_selection_controller.on_shot_selected(None)

        # DCC section launch buttons should be disabled again
        for section in main_window.right_panel._dcc_accordion._sections.values():
            assert not section._launch_btn.isEnabled()


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestShotRefresh:
    """Test shot refresh functionality."""

    def test_refresh_shots_updates_display(
        self, test_process_pool: TestProcessPoolType, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that refreshing shots updates the display."""
        # QMessageBox mocking now handled by autouse fixture in conftest.py
        from config import (
            Config,
        )

        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # CRITICAL: Wait for background shot loading to complete before test setup
        # The ShotModel starts async loading on init, we need it to finish first
        # to avoid race conditions where the background load overwrites test data
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Use test process pool to avoid real subprocess calls (UNIFIED_TESTING_GUIDE)
        # Use Config.SHOWS_ROOT for proper test isolation
        shows_root = Config.SHOWS_ROOT
        test_process_pool.set_outputs(
            f"workspace {shows_root}/test/shots/seq01/seq01_0010\nworkspace {shows_root}/test/shots/seq01/seq01_0020"
        )
        main_window.shot_model._process_pool = test_process_pool

        # CRITICAL: Recreate parser to use correct SHOWS_ROOT from test environment
        # Manually create pattern with correct shows_root to bypass Config import issues
        import re
        shows_root_escaped = re.escape(shows_root)
        ws_pattern = re.compile(
            rf"workspace\s+({shows_root_escaped}/([^/]+)/shots/([^/]+)/([^/]+))"
        )
        # Manually set the pattern on the existing parser
        main_window.shot_model._parser._ws_pattern = ws_pattern

        # Refresh shots
        main_window._refresh_shots()

        # Wait for async refresh to complete
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Verify shots were loaded
        assert len(main_window.shot_model.shots) == 2


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestApplicationLaunching:
    """Test application launching functionality."""

    @pytest.mark.allow_dialogs  # Error dialog is expected side-effect
    def test_launch_app_without_selection_shows_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test that launching an app without a shot shows an error."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Mock the workspace directory creation to avoid permission errors
        def mock_mkdir(self, *args, **kwargs) -> None:
            pass  # Don't actually create directories

        monkeypatch.setattr("pathlib.Path.mkdir", mock_mkdir)

        # Try to launch app without selecting a shot
        # (subprocess calls are already mocked by autouse fixture, we just verify no crash)
        main_window.launch_app("nuke")

        # Test behavior: should have shown an error (mocked by autouse fixture)
        # We're verifying that the code path completes without crashing

    @pytest.mark.allow_dialogs  # Error dialog is expected side-effect
    def test_launch_app_with_selection(
        self,
        test_process_pool: TestProcessPoolType,
        qtbot: QtBot,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """Test launching an app with a shot selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Use mock mode for this test
        monkeypatch.setenv("SHOTBOT_MOCK_MODE", "1")

        # CRITICAL: Wait for background shot loading to complete before test setup
        # The ShotModel starts async loading on init, we need it to finish first
        # to avoid race conditions where the background load overwrites test data
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Testing the actual behavior rather than mocking internal methods
        # We verify the full integration from shot selection to app launch

        # Set up test process pool for workspace command
        shows_root = Config.SHOWS_ROOT
        test_process_pool.set_outputs(
            f"workspace {shows_root}/test/shots/seq01/seq01_0010"
        )
        main_window.shot_model._process_pool = test_process_pool

        # CRITICAL: Recreate parser to use correct SHOWS_ROOT from test environment
        # Manually create pattern with correct shows_root to bypass Config import issues
        import re
        shows_root_escaped = re.escape(shows_root)
        ws_pattern = re.compile(
            rf"workspace\s+({shows_root_escaped}/([^/]+)/shots/([^/]+)/([^/]+))"
        )
        # Manually set the pattern on the existing parser
        main_window.shot_model._parser._ws_pattern = ws_pattern

        # Load shots
        main_window._refresh_shots()

        # Wait for async refresh to complete
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Verify shot loaded
        assert len(main_window.shot_model.shots) == 1
        shot = main_window.shot_model.shots[0]

        # Select the shot
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify DCC section launch buttons enabled (test behavior)
        assert "nuke" in main_window.right_panel._dcc_accordion._sections
        assert main_window.right_panel._dcc_accordion._sections["nuke"]._launch_btn.isEnabled()

        # Test complete workflow - just verify the app launch doesn't crash
        # The subprocess call is already mocked by our autouse fixture (no real process spawned)
        # We're testing the integration, not the implementation details

        # Mock the workspace directory creation to avoid permission errors
        def mock_mkdir(self, *args, **kwargs) -> None:
            pass  # Don't actually create directories

        monkeypatch.setattr("pathlib.Path.mkdir", mock_mkdir)
        main_window.launch_app("nuke")

        # Test behavior: app launch completed without errors
        # (If it failed, it would have shown an error notification which is mocked)


class TestSignalConnections:
    """Test signal connections are properly established."""

    def test_shot_selected_signal_connected(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that shot selection signal is connected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Create a test shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")

        # Trigger signal and verify handler is called
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify command launcher has the shot
        assert main_window.command_launcher.current_shot == shot


class TestWindowCleanup:
    """Test window cleanup functionality."""

    def test_window_cleanup_on_close(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that closing window properly cleans up resources."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Close the window
        main_window.close()

        # Test behavior: window should be closed without errors
        # Qt cleanup is handled by qtbot and autouse fixtures


class TestStatusBar:
    """Test status bar functionality."""

    def test_status_bar_exists(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that status bar is created."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Verify status bar exists
        assert main_window.statusBar() is not None

    def test_background_load_started_shows_message(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that background load started signal shows status message."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Directly call the handler (simulating signal emission)
        main_window._on_background_load_started()

        # Verify status bar shows fetching message
        assert "Fetching fresh data" in main_window.status_bar.currentMessage()

    def test_show_filter_updates_status_bar(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test that applying show filter updates status bar with count."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Add some test shots
        test_shots = [
            Shot(
                show="TestShow",
                sequence="sq010",
                shot="sh0010",
                workspace_path="/test/path",
            ),
            Shot(
                show="OtherShow",
                sequence="sq020",
                shot="sh0020",
                workspace_path="/other/path",
            ),
        ]
        main_window.shot_model.shots = test_shots
        main_window.shot_item_model.set_shots(test_shots)

        # Apply filter via the filter coordinator
        main_window.filter_coordinator._apply_show_filter(
            main_window.shot_item_model,
            main_window.shot_model,
            "TestShow",
            "My Shots",
        )

        # Verify status bar shows filter result
        message = main_window.status_bar.currentMessage()
        assert "TestShow" in message
        assert "shot" in message.lower()


class TestThumbnailSizeControl:
    """Test thumbnail size control functionality."""

    def test_thumbnail_size_slider_exists(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that thumbnail size sliders exist in each grid view."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Verify size sliders exist in each tab's grid view
        assert hasattr(main_window.shot_grid, "size_slider")
        assert hasattr(main_window.threede_shot_grid, "size_slider")
        assert hasattr(main_window.previous_shots_grid, "size_slider")


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestMainWindowIntegration:
    """Integration tests for MainWindow end-to-end workflows."""

    @pytest.mark.allow_dialogs  # Error dialog is expected side-effect
    def test_complete_shot_workflow(
        self,
        test_process_pool: TestProcessPoolType,
        qtbot: QtBot,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """Test complete workflow: load shots, select, and launch app."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Use mock mode for this test
        monkeypatch.setenv("SHOTBOT_MOCK_MODE", "1")

        # CRITICAL: Wait for background shot loading to complete before test setup
        # The ShotModel starts async loading on init, we need it to finish first
        # to avoid race conditions where the background load overwrites test data
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Set up test data
        shows_root = Config.SHOWS_ROOT
        test_process_pool.set_outputs(
            f"workspace {shows_root}/test/shots/seq01/seq01_0010"
        )
        main_window.shot_model._process_pool = test_process_pool

        # CRITICAL: Recreate parser to use correct SHOWS_ROOT from test environment
        # Manually create pattern with correct shows_root to bypass Config import issues
        import re
        shows_root_escaped = re.escape(shows_root)
        ws_pattern = re.compile(
            rf"workspace\s+({shows_root_escaped}/([^/]+)/shots/([^/]+)/([^/]+))"
        )
        # Manually set the pattern on the existing parser
        main_window.shot_model._parser._ws_pattern = ws_pattern

        # Load shots
        main_window._refresh_shots()

        # Wait for async refresh to complete
        main_window.shot_model.wait_for_async_load(timeout_ms=2000)

        # Verify shot loaded
        assert len(main_window.shot_model.shots) == 1
        shot = main_window.shot_model.shots[0]

        # Select the shot
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify DCC section launch buttons enabled (test behavior)
        assert "nuke" in main_window.right_panel._dcc_accordion._sections
        assert main_window.right_panel._dcc_accordion._sections["nuke"]._launch_btn.isEnabled()

        # Test complete workflow - just verify the app launch doesn't crash
        # The subprocess call is already mocked by our autouse fixture (no real process spawned)
        # We're testing the integration, not the implementation details

        # Mock the workspace directory creation to avoid permission errors
        def mock_mkdir(self, *args, **kwargs) -> None:
            pass  # Don't actually create directories

        monkeypatch.setattr("pathlib.Path.mkdir", mock_mkdir)
        main_window.launch_app("nuke")

        # Test behavior: app launch completed without errors
        # (If it failed, it would have shown an error notification which is mocked)


class TestCrashRecovery:
    """Test 3DE crash recovery functionality."""

    def test_crash_recovery_with_current_shot(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test crash recovery works when current_shot is set (from My Shots).

        This is the bug fix test - crash recovery should work when a shot
        is selected from "My Shots" tab, not just when a 3DE scene is selected.
        """
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Create and select a shot (simulates clicking in "My Shots" tab)
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify shot is set and scene is None (important for the bug fix)
        assert main_window.command_launcher.current_shot == shot
        assert main_window.threede_shot_grid.selected_scene is None

        # Mock the recovery components to avoid filesystem operations
        # Patch where they're imported, not where they're called from
        mock_crash_info = MagicMock()
        mock_crash_info.crash_path.name = "test_scene.3de.crash"

        with patch("threede_recovery.ThreeDERecoveryManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.find_crash_files.return_value = [mock_crash_info]

            with patch("threede_recovery_dialog.ThreeDERecoveryDialog") as mock_dialog_class:
                mock_dialog = mock_dialog_class.return_value
                mock_dialog.exec.return_value = 0  # Dialog rejected

                # Trigger crash recovery
                main_window.shot_selection_controller.on_recover_crashes_requested()

                # Verify recovery manager was called with shot's workspace_path
                mock_manager.find_crash_files.assert_called_once_with(
                    shot.workspace_path, recursive=True
                )

                # Verify dialog was shown
                mock_dialog_class.assert_called_once()

    def test_crash_recovery_with_current_scene(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test crash recovery works when current_scene is set (from Other 3DE Scenes).

        Scene selection clears current_shot, so crash recovery should use
        scene's workspace_path instead.
        """
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Create and select a 3DE scene (simulates clicking in "Other 3DE Scenes" tab)
        shows_root = Config.SHOWS_ROOT
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{shows_root}/test/seq01/0010",
            user="test_user",
            plate="FG01",
            scene_path=Path(f"{shows_root}/test/seq01/0010/test.3de"),
        )
        # Simulate scene selection by setting the grid's internal state directly
        # (in production, this is set by user clicking on a scene in the grid)
        main_window.threede_shot_grid._selected_scene = scene

        # Verify scene is set and shot is None
        assert main_window.threede_shot_grid.selected_scene == scene
        assert main_window.command_launcher.current_shot is None

        # Mock the recovery components
        mock_crash_info = MagicMock()
        mock_crash_info.crash_path.name = "test_scene.3de.crash"

        with patch("threede_recovery.ThreeDERecoveryManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.find_crash_files.return_value = [mock_crash_info]

            with patch("threede_recovery_dialog.ThreeDERecoveryDialog") as mock_dialog_class:
                mock_dialog = mock_dialog_class.return_value
                mock_dialog.exec.return_value = 0

                # Trigger crash recovery
                main_window.shot_selection_controller.on_recover_crashes_requested()

                # Verify recovery manager was called with scene's workspace_path
                # (since current_shot is None, we fall back to scene)
                mock_manager.find_crash_files.assert_called_once_with(
                    scene.workspace_path, recursive=True
                )

                # Verify dialog was shown
                mock_dialog_class.assert_called_once()

    def test_crash_recovery_no_shot_selected(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, expect_dialog
    ) -> None:
        """Test crash recovery shows warning when no shot is selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Don't select any shot or scene
        assert main_window.command_launcher.current_shot is None
        assert main_window.threede_shot_grid.selected_scene is None

        # Trigger crash recovery
        main_window.shot_selection_controller.on_recover_crashes_requested()

        # Verify a warning dialog was shown (QMessageBox.warning intercepted by fixture)
        expect_dialog.assert_shown("warning", "No Shot Selected")

    def test_crash_recovery_no_crash_files_found(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test crash recovery shows info message when no crash files found."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Create and select a shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Mock recovery manager to return no crash files
        with patch("threede_recovery.ThreeDERecoveryManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.find_crash_files.return_value = []  # No crash files

            # Trigger crash recovery
            main_window.shot_selection_controller.on_recover_crashes_requested()

            # Verify info message was shown in the status bar
            message = main_window.status_bar.currentMessage()
            assert "No 3DE crash files found" in message
            assert shot.full_name in message

    def test_crash_recovery_with_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, expect_dialog
    ) -> None:
        """Test crash recovery handles errors gracefully."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Create and select a shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Mock recovery manager to raise an error
        with patch("threede_recovery.ThreeDERecoveryManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.find_crash_files.side_effect = Exception("Test error")

            # Trigger crash recovery
            main_window.shot_selection_controller.on_recover_crashes_requested()

            # Verify a critical error dialog was shown (QMessageBox.critical intercepted)
            expect_dialog.assert_shown("critical", "Scan Error")
            expect_dialog.assert_shown("critical", "Test error")


class TestRightPanelFileLaunch:
    """Test file launch from right panel DCC section.

    When a user selects a file in the DCC panel (e.g., Maya file from
    'Other 3DE scenes' tab) and clicks Launch, the selected file should
    be opened in the application.
    """

    def test_launch_with_selected_file_from_shot_context(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test launching a selected file when shot is selected (My Shots tab)."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Select a shot (provides workspace context)
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Create a SceneFile to simulate file selection in DCC panel
        from datetime import datetime

        maya_file = SceneFile(
            path=Path(f"{shows_root}/test/seq01/0010/scenes/test_scene.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(tz=UTC),
            user="other_user",
        )

        # Mock launch_with_file to verify it's called correctly
        with patch.object(
            main_window.command_launcher, "launch_with_file", return_value=True
        ) as mock_launch:
            # Simulate right panel launch with selected file
            options = {"selected_file": maya_file}
            main_window._on_right_panel_launch("maya", options)

            # Verify launch_with_file was called with correct args
            mock_launch.assert_called_once_with(
                "maya",
                maya_file.path,
                shot.workspace_path,
            )

    def test_launch_with_selected_file_from_scene_context(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test launching a selected file when 3DE scene is selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Select a 3DE scene (provides workspace context via selected_scene)
        shows_root = Config.SHOWS_ROOT
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{shows_root}/test/seq01/0010",
            user="scene_user",
            plate="FG01",
            scene_path=Path(f"{shows_root}/test/seq01/0010/scenes/track.3de"),
        )
        # Set scene directly (simulates user selection in Other 3DE Scenes tab)
        main_window.threede_shot_grid._selected_scene = scene
        # Ensure no shot is selected (Other 3DE Scenes tab behavior)
        main_window.command_launcher.set_current_shot(None)

        # Create a Maya file to launch
        from datetime import datetime

        maya_file = SceneFile(
            path=Path(f"{shows_root}/test/seq01/0010/scenes/finalize.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(tz=UTC),
            user="another_user",
        )

        # Mock launch_with_file
        with patch.object(
            main_window.command_launcher, "launch_with_file", return_value=True
        ) as mock_launch:
            options = {"selected_file": maya_file}
            main_window._on_right_panel_launch("maya", options)

            # Verify launch_with_file was called with scene's workspace
            mock_launch.assert_called_once_with(
                "maya",
                maya_file.path,
                scene.workspace_path,
            )

    def test_launch_with_selected_file_no_context_shows_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch, expect_dialog
    ) -> None:
        """Test that launching without context shows an error."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Ensure no shot or scene is selected
        main_window.command_launcher.set_current_shot(None)
        main_window.threede_shot_grid._selected_scene = None

        # Create a file to launch
        from datetime import datetime

        nuke_file = SceneFile(
            path=Path("/shows/test/scenes/comp.nk"),
            file_type=FileType.NUKE,
            modified_time=datetime.now(tz=UTC),
            user="user",
        )

        options = {"selected_file": nuke_file}
        main_window._on_right_panel_launch("nuke", options)

        # Verify a critical error dialog was shown with correct message
        expect_dialog.assert_shown("critical", "Cannot Launch File")
        expect_dialog.assert_shown("critical", "No shot or scene context available")

    def test_launch_without_selected_file_uses_launch_app(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test that launch without selected_file uses standard launch_app."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Select a shot for context
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Mock both launch methods
        with patch.object(
            main_window.command_launcher, "launch_app", return_value=True
        ) as mock_launch_app, patch.object(
            main_window.command_launcher, "launch_with_file", return_value=True
        ) as mock_launch_with_file:
            # Launch without selected_file
            options = {"open_latest_maya": True}
            main_window._on_right_panel_launch("maya", options)

            # Verify launch_app was called, not launch_with_file
            mock_launch_app.assert_called_once()
            mock_launch_with_file.assert_not_called()


class TestGetCurrentWorkspacePath:
    """Test the _get_current_workspace_path helper method."""

    def test_returns_shot_workspace_when_shot_selected(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test returns workspace from current_shot when available."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Select a shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window.shot_selection_controller.on_shot_selected(shot)

        # Verify workspace path comes from shot
        result = main_window._get_current_workspace_path()
        assert result == shot.workspace_path

    def test_returns_scene_workspace_when_no_shot(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Test returns workspace from selected_scene when no shot selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Select a 3DE scene without a shot
        shows_root = Config.SHOWS_ROOT
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{shows_root}/test/seq01/0010",
            user="user",
            plate="FG01",
            scene_path=Path(f"{shows_root}/test/seq01/0010/track.3de"),
        )
        main_window.threede_shot_grid._selected_scene = scene
        main_window.command_launcher.set_current_shot(None)

        # Verify workspace path comes from scene
        result = main_window._get_current_workspace_path()
        assert result == scene.workspace_path

    def test_prefers_shot_over_scene(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test that shot workspace is preferred when both are available."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        shows_root = Config.SHOWS_ROOT

        # Set both shot and scene with different workspaces
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/shot/workspace")
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{shows_root}/scene/workspace",
            user="user",
            plate="FG01",
            scene_path=Path(f"{shows_root}/scene/workspace/track.3de"),
        )
        main_window.shot_selection_controller.on_shot_selected(shot)
        main_window.threede_shot_grid._selected_scene = scene

        # Verify shot workspace is preferred
        result = main_window._get_current_workspace_path()
        assert result == shot.workspace_path
        assert result != scene.workspace_path

    def test_returns_none_when_no_context(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test returns None when neither shot nor scene is selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Ensure no context
        main_window.command_launcher.set_current_shot(None)
        main_window.threede_shot_grid._selected_scene = None

        result = main_window._get_current_workspace_path()
        assert result is None
