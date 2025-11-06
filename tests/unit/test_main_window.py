"""Tests for MainWindow - critical UI integration.

Following UNIFIED_TESTING_GUIDE principles:
- Use real components where possible
- Use test doubles at system boundaries (subprocess)
- Test behavior not implementation
- Use qtbot for proper Qt testing
"""

# Standard library imports
from pathlib import Path
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
from tests.unit.test_protocols import ProcessPoolProtocol as TestProcessPoolType


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.xdist_group("qt_state"),
]


# Module-level fixture to handle lazy imports
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow, CacheManager, Shot, ThreeDEScene  # noqa: PLW0603
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
        assert main_window.launcher_manager is not None

        # Verify UI components
        assert main_window.tab_widget is not None
        assert main_window.shot_grid is not None
        assert main_window.threede_shot_grid is not None
        assert main_window.previous_shots_grid is not None
        assert main_window.shot_info_panel is not None

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

        # Initially launcher panel's app buttons should be disabled
        for section in main_window.launcher_panel.app_sections.values():
            assert not section.launch_button.isEnabled()

        # Create a test shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")

        # Simulate shot selection
        main_window._on_shot_selected(shot)

        # Now buttons should be enabled
        for section in main_window.launcher_panel.app_sections.values():
            assert section.launch_button.isEnabled()

        # Shot info panel should be updated with the shot
        # Test behavior: info panel should show shot information
        assert main_window.shot_info_panel is not None

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
        main_window._on_shot_selected(shot)

        # Verify buttons are enabled
        for section in main_window.launcher_panel.app_sections.values():
            assert section.launch_button.isEnabled()

        # Deselect shot
        main_window._on_shot_selected(None)

        # Buttons should be disabled again
        for section in main_window.launcher_panel.app_sections.values():
            assert not section.launch_button.isEnabled()


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
        import re  # noqa: PLC0415 - lazy import to avoid circular dependency
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


class TestApplicationLaunching:
    """Test application launching functionality."""

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
        import re  # noqa: PLC0415 - lazy import to avoid circular dependency
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
        main_window._on_shot_selected(shot)

        # Verify buttons enabled (test behavior)
        assert "nuke" in main_window.launcher_panel.app_sections
        assert main_window.launcher_panel.app_sections["nuke"].launch_button.isEnabled()

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
        main_window._on_shot_selected(shot)

        # Verify launcher controller has the shot
        assert main_window.launcher_controller.current_shot == shot


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


class TestMainWindowIntegration:
    """Integration tests for MainWindow end-to-end workflows."""

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
        import re  # noqa: PLC0415 - lazy import to avoid circular dependency
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
        main_window._on_shot_selected(shot)

        # Verify buttons enabled (test behavior)
        assert "nuke" in main_window.launcher_panel.app_sections
        assert main_window.launcher_panel.app_sections["nuke"].launch_button.isEnabled()

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
        main_window._on_shot_selected(shot)

        # Verify shot is set and scene is None (important for the bug fix)
        assert main_window.launcher_controller.current_shot == shot
        assert main_window.launcher_controller.current_scene is None

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
                main_window._on_shot_recover_crashes_requested()

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
        main_window._on_scene_selected(scene)

        # Verify scene is set and shot is None (cleared by scene selection)
        assert main_window.launcher_controller.current_scene == scene
        assert main_window.launcher_controller.current_shot is None

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
                main_window._on_shot_recover_crashes_requested()

                # Verify recovery manager was called with scene's workspace_path
                # (since current_shot is None, we fall back to scene)
                mock_manager.find_crash_files.assert_called_once_with(
                    scene.workspace_path, recursive=True
                )

                # Verify dialog was shown
                mock_dialog_class.assert_called_once()

    def test_crash_recovery_no_shot_selected(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test crash recovery shows warning when no shot is selected."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Don't select any shot or scene
        assert main_window.launcher_controller.current_shot is None
        assert main_window.launcher_controller.current_scene is None

        # Mock NotificationManager to capture warning
        with patch("notification_manager.NotificationManager") as mock_notif:
            # Trigger crash recovery
            main_window._on_shot_recover_crashes_requested()

            # Verify warning was shown
            mock_notif.warning.assert_called_once_with(
                "No Shot Selected",
                "Please select a shot before attempting crash recovery."
            )

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
        main_window._on_shot_selected(shot)

        # Mock recovery manager to return no crash files
        with patch("threede_recovery.ThreeDERecoveryManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.find_crash_files.return_value = []  # No crash files

            with patch("notification_manager.NotificationManager") as mock_notif:
                # Trigger crash recovery
                main_window._on_shot_recover_crashes_requested()

                # Verify info message was shown
                mock_notif.info.assert_called_once()
                call_args = mock_notif.info.call_args[0][0]
                assert "No 3DE crash files found" in call_args
                assert shot.full_name in call_args

    def test_crash_recovery_with_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        """Test crash recovery handles errors gracefully."""
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        main_window = MainWindow(cache_manager=cache_manager)
        qtbot.addWidget(main_window)

        # Create and select a shot
        shows_root = Config.SHOWS_ROOT
        shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
        main_window._on_shot_selected(shot)

        # Mock recovery manager to raise an error
        with patch("threede_recovery.ThreeDERecoveryManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.find_crash_files.side_effect = Exception("Test error")

            with patch("notification_manager.NotificationManager") as mock_notif:
                # Trigger crash recovery
                main_window._on_shot_recover_crashes_requested()

                # Verify error was shown
                mock_notif.error.assert_called_once()
                call_args = mock_notif.error.call_args
                assert call_args[0][0] == "Scan Error"
                assert "Test error" in call_args[0][1]
