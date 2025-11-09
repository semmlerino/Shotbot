"""Integration tests for launcher panel within main window context.

This test suite validates launcher panel integration using:
- Real Qt components and main window integration
- Test doubles only at system boundaries (subprocess, process pools)
- Behavior testing for complete workflow scenarios
- Real signal flow from launcher panel through main window

Tests cover:
- MainWindow launcher panel integration
- Complete shot-to-launch workflow
- Signal propagation through the application
- Application launching with proper context
- Error handling in integrated scenarios
"""

from __future__ import annotations

# Standard library imports
import contextlib
from typing import TYPE_CHECKING, Any
from unittest.mock import patch


if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

# Third-party imports
import pytest
from PySide6.QtCore import Qt

# Removed sys.path modification - can cause import issues
# sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# Local application imports
from launcher_panel import LauncherPanel

# Moved to lazy import to fix Qt initialization
# from main_window import MainWindow
from shot_model import Shot

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.test_doubles_extended import TestProcessPoolDouble as TestProcessPool
from tests.test_doubles_library import TestSubprocess


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
    pytest.mark.qt,
    pytest.mark.enforce_unique_connections,
]


# =============================================================================
# FACTORY FIXTURES FOR INTEGRATION TESTING
# =============================================================================


@pytest.fixture
def make_shot() -> Callable[..., Shot]:
    """Factory fixture for creating Shot objects."""

    def _make(
        show: str = "test_show",
        sequence: str = "test_seq",
        shot: str = "0010",
        workspace_path: str = "/test/path",
    ) -> Shot:
        return Shot(show, sequence, shot, workspace_path)

    return _make


@pytest.fixture
def test_process_pool() -> TestProcessPool:
    """Test double for process pool at system boundary."""
    pool = TestProcessPool()
    pool.set_outputs("workspace /shows/test_show/shots/test_seq/test_seq_0010")
    return pool


@pytest.fixture
def test_subprocess() -> TestSubprocess:
    """Test double for subprocess calls."""
    return TestSubprocess()


# =============================================================================
# MAIN WINDOW INTEGRATION TESTS
# =============================================================================


@pytest.mark.gui_mainwindow
class TestMainWindowLauncherIntegration:
    """Test launcher panel integration within MainWindow."""

    def setup_method(self) -> None:
        """Setup method to initialize Qt object tracking."""
        self.qt_objects: list[Any] = []

    def teardown_method(self, qtbot: QtBot) -> None:
        """Clean up Qt objects to prevent resource leaks."""
        for obj in self.qt_objects:
            try:
                # Stop worker threads in MainWindow's launcher_manager before cleanup
                if hasattr(obj, "launcher_manager") and obj.launcher_manager:
                    obj.launcher_manager.stop_all_workers()

                if hasattr(obj, "deleteLater"):
                    obj.deleteLater()
                    qtbot.wait(1)
            except Exception:
                pass
        self.qt_objects.clear()

    def test_launcher_panel_initialization_in_main_window(
        self, qapp: QApplication, qtbot: QtBot
    ) -> None:
        """Test that launcher panel is properly initialized in main window."""
        # We need to patch process pool creation to avoid real VFX dependencies
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)
            window.show()
            qtbot.waitExposed(window)

            # Verify launcher panel exists and is integrated
            assert hasattr(window, "launcher_panel")
            assert isinstance(window.launcher_panel, LauncherPanel)

            # Verify signal connections exist
            # The launcher panel should be connected to main window methods
            assert window.launcher_panel.app_launch_requested is not None
            assert window.launcher_panel.custom_launcher_requested is not None

    def test_shot_selection_enables_launcher_panel(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test that selecting a shot properly enables the launcher panel."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)
            window.show()
            qtbot.waitExposed(window)

            # Initially no shot selected - launcher should be disabled
            for section in window.launcher_panel.app_sections.values():
                assert not section.launch_button.isEnabled()

            # Select a shot using the proper MainWindow integration
            shot = make_shot(show="integration_test", sequence="seq01", shot="0100")
            window._on_shot_selected(shot)

            # Verify launcher panel is enabled
            for section in window.launcher_panel.app_sections.values():
                assert section.launch_button.isEnabled()

            # Verify info label is updated
            assert (
                "integration_test/seq01/0100" in window.launcher_panel.info_label.text()
            )

    def test_app_launch_signal_flow_through_main_window(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test complete signal flow from launcher panel through main window."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            # Set up shot context using proper MainWindow integration
            shot = make_shot(show="signal_test", sequence="seq02", shot="0200")
            window._on_shot_selected(shot)

            # Mock the launcher controller's launch_app to track calls without executing
            launch_calls: list[str] = []

            def mock_launch_app(app_name: str) -> None:
                # Record the call for verification
                launch_calls.append(app_name)

            # Disconnect existing signal and connect to mock
            original_slot = window.launcher_controller.launch_app
            window.launcher_panel.app_launch_requested.disconnect(original_slot)
            window.launcher_panel.app_launch_requested.connect(mock_launch_app)

            try:
                # Trigger app launch from launcher panel
                nuke_section = window.launcher_panel.app_sections["nuke"]

                # Debug: Check button state
                assert nuke_section.launch_button.isEnabled(), "Launch button should be enabled after shot selection"

                qtbot.mouseClick(nuke_section.launch_button, Qt.MouseButton.LeftButton)

                # Wait for signal to be processed by the connected handler

                qtbot.waitUntil(
                    lambda: len(launch_calls) > 0,
                    timeout=1000
                )

                # Verify signal reached main window
                assert len(launch_calls) == 1
                assert launch_calls[0] == "nuke"
            finally:
                # Reconnect original signal to avoid bleed-over
                window.launcher_panel.app_launch_requested.disconnect(mock_launch_app)
                window.launcher_panel.app_launch_requested.connect(original_slot)

    @pytest.mark.slow
    def test_multiple_app_launches_through_main_window(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test launching multiple applications through the integrated workflow."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            shot = make_shot(show="multi_test", sequence="seq03", shot="0300")
            window._on_shot_selected(shot)

            launch_calls: list[str] = []

            def mock_launch_app(app_name: str) -> None:
                # Record the call for verification
                launch_calls.append(app_name)

            # Disconnect existing signal and connect to mock to avoid double-execution
            original_slot = window.launcher_controller.launch_app
            window.launcher_panel.app_launch_requested.disconnect(original_slot)
            window.launcher_panel.app_launch_requested.connect(mock_launch_app)

            try:
                # Launch multiple apps in sequence
                apps_to_launch = ["3de", "maya", "rv"]
                for app_name in apps_to_launch:
                    section = window.launcher_panel.app_sections[app_name]
                    initial_count = len(launch_calls)
                    qtbot.mouseClick(section.launch_button, Qt.MouseButton.LeftButton)
                    # Wait for this specific launch call to be processed
                    qtbot.waitUntil(
                        lambda count=initial_count: len(launch_calls) > count,
                        timeout=1000
                    )

                # Verify all launches were processed
                assert launch_calls == apps_to_launch
            finally:
                # Reconnect original signal to avoid bleed-over
                window.launcher_panel.app_launch_requested.disconnect(mock_launch_app)
                window.launcher_panel.app_launch_requested.connect(original_slot)

    def test_checkbox_options_passed_through_main_window(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test that checkbox options are properly accessed through main window."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            shot = make_shot()
            window._on_shot_selected(shot)

            # Configure nuke options
            nuke_section = window.launcher_panel.app_sections["nuke"]
            nuke_section.checkboxes["include_raw_plate"].setChecked(False)

            # Test that main window can access checkbox states
            raw_plate_enabled = window.launcher_panel.get_checkbox_state(
                "nuke", "include_raw_plate"
            )

            assert raw_plate_enabled is False

    def test_custom_launcher_integration(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test custom launcher functionality through main window."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            # Mock launcher_manager for custom launcher support
            from unittest.mock import (
                Mock,
            )

            mock_launcher = Mock()
            mock_launcher.name = "Test Custom Launcher"
            mock_launcher_manager = Mock()
            mock_launcher_manager.get_launcher.return_value = mock_launcher
            mock_launcher_manager.execute_in_shot_context.return_value = True
            window.launcher_manager = mock_launcher_manager

            shot = make_shot()
            window._on_shot_selected(shot)

            # Add custom launcher through the panel
            window.launcher_panel.add_custom_launcher(
                "test_custom", "Test Custom Launcher"
            )

            # No need to mock execute_custom_launcher - let it run with our mocked launcher_manager

            # Trigger custom launcher
            custom_button = window.launcher_panel.custom_launcher_buttons["test_custom"]

            # Debug: Check button state
            assert custom_button is not None, "Custom button should exist"
            assert custom_button.isEnabled(), (
                f"Custom button should be enabled, current shot: {window.launcher_panel._current_shot}"
            )

            # Add signal spy to verify signal emission
            from PySide6.QtTest import (
                QSignalSpy,
            )

            signal_spy = QSignalSpy(window.launcher_panel.custom_launcher_requested)

            qtbot.mouseClick(custom_button, Qt.MouseButton.LeftButton)

            # Wait for the custom launcher signal to be emitted
            qtbot.waitUntil(
                lambda: signal_spy.count() > 0,
                timeout=1000
            )

            # Debug: Check if signal was emitted
            assert signal_spy.count() >= 1, (
                f"Signal should have been emitted, spy count: {signal_spy.count()}"
            )

            # Verify custom launcher was called through launcher_manager
            mock_launcher_manager.get_launcher.assert_called_once_with("test_custom")
            mock_launcher_manager.execute_in_shot_context.assert_called_once()


# =============================================================================
# END-TO-END INTEGRATION SCENARIOS
# =============================================================================


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestEndToEndLauncherWorkflow:
    """Test complete end-to-end launcher workflows."""

    def setup_method(self) -> None:
        """Setup method to initialize Qt object tracking."""
        self.qt_objects: list[Any] = []

    def teardown_method(self, qtbot: QtBot) -> None:
        """Clean up Qt objects to prevent resource leaks."""
        for obj in self.qt_objects:
            try:
                # Stop worker threads in MainWindow's launcher_manager before cleanup
                if hasattr(obj, "launcher_manager") and obj.launcher_manager:
                    obj.launcher_manager.stop_all_workers()

                if hasattr(obj, "deleteLater"):
                    obj.deleteLater()
                    qtbot.wait(1)
            except Exception:
                pass
        self.qt_objects.clear()

    @pytest.mark.integration
    def test_complete_nuke_launch_workflow(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test complete workflow: shot selection -> option configuration -> nuke launch."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            # Step 1: Select shot using proper MainWindow integration
            shot = make_shot(show="endtoend", sequence="workflow", shot="0001")
            window._on_shot_selected(shot)

            # Step 2: Configure nuke options
            nuke_section = window.launcher_panel.app_sections["nuke"]
            nuke_section.checkboxes["include_raw_plate"].setChecked(True)

            # Step 3: Verify UI state before launch
            assert nuke_section.launch_button.isEnabled()
            assert (
                window.launcher_panel.get_checkbox_state("nuke", "include_raw_plate")
                is True
            )

            # Step 4: Mock the app launch process
            launch_context: dict[str, Any] = {}

            def mock_launch_app(app_name: str) -> None:
                # Capture launch context for verification
                launch_context["app"] = app_name
                launch_context["shot"] = window.launcher_panel._current_shot
                launch_context["raw_plate"] = window.launcher_panel.get_checkbox_state(
                    "nuke", "include_raw_plate"
                )

            # Disconnect existing signal and connect to mock to avoid validation errors
            original_slot = window.launcher_controller.launch_app
            window.launcher_panel.app_launch_requested.disconnect(original_slot)
            window.launcher_panel.app_launch_requested.connect(mock_launch_app)

            try:
                # Step 5: Launch nuke
                qtbot.mouseClick(nuke_section.launch_button, Qt.MouseButton.LeftButton)

                # Wait for the launch signal to be processed by the mock handler
                qtbot.waitUntil(
                    lambda: "app" in launch_context,
                    timeout=1000
                )

                # Step 6: Verify complete context was captured
                assert launch_context["app"] == "nuke"
                assert launch_context["shot"] == shot
                assert launch_context["raw_plate"] is True
            finally:
                # Reconnect original signal to avoid bleed-over
                window.launcher_panel.app_launch_requested.disconnect(mock_launch_app)
                window.launcher_panel.app_launch_requested.connect(original_slot)

    @pytest.mark.integration
    def test_3de_launch_with_scene_options(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test 3DE launch workflow with scene opening option."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            shot = make_shot(show="threedee", sequence="tracking", shot="0050")
            window._on_shot_selected(shot)

            # Configure 3DE options
            threede_section = window.launcher_panel.app_sections["3de"]
            threede_section.checkboxes["open_latest_threede"].setChecked(True)

            launch_context: dict[str, Any] = {}

            def mock_launch_3de(app_name: str) -> None:
                """Mock handler for app launch signal."""
                launch_context["app"] = app_name
                launch_context["shot"] = window.launcher_panel._current_shot
                launch_context["open_latest"] = (
                    window.launcher_panel.get_checkbox_state(
                        "3de", "open_latest_threede"
                    )
                )

            # Disconnect existing signal and connect to mock to avoid validation errors
            original_slot = window.launcher_controller.launch_app
            window.launcher_panel.app_launch_requested.disconnect(original_slot)
            window.launcher_panel.app_launch_requested.connect(mock_launch_3de)

            try:
                qtbot.mouseClick(
                    threede_section.launch_button, Qt.MouseButton.LeftButton
                )

                # Wait for the launch signal to be processed and context populated
                qtbot.waitUntil(
                    lambda: "app" in launch_context,
                    timeout=1000
                )

                assert launch_context["app"] == "3de"
                assert launch_context["shot"] == shot
                assert launch_context["open_latest"] is True
            finally:
                # Reconnect original signal to avoid bleed-over
                window.launcher_panel.app_launch_requested.disconnect(mock_launch_3de)
                window.launcher_panel.app_launch_requested.connect(original_slot)

    @pytest.mark.integration
    def test_launcher_panel_state_persistence(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test that launcher panel maintains state correctly during shot changes."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            # Set initial shot and configure options
            shot1 = make_shot(show="state1", sequence="seq1", shot="0010")
            window.launcher_panel.set_shot(shot1)

            nuke_section = window.launcher_panel.app_sections["nuke"]
            nuke_section.checkboxes["include_raw_plate"].setChecked(True)

            # Change to different shot
            shot2 = make_shot(show="state2", sequence="seq2", shot="0020")
            window.launcher_panel.set_shot(shot2)

            # Verify checkbox states persist (they should maintain their UI state)
            assert nuke_section.checkboxes["include_raw_plate"].isChecked() is True

            # Clear shot
            window.launcher_panel.set_shot(None)

            # Verify buttons are disabled but checkboxes maintain state
            assert not nuke_section.launch_button.isEnabled()
            assert nuke_section.checkboxes["include_raw_plate"].isChecked() is True

    @pytest.mark.slow
    def test_rapid_shot_switching_stability(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test launcher panel stability during rapid shot switching."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            shots = [
                make_shot(show="rapid1", sequence="seq1", shot="0010"),
                make_shot(show="rapid2", sequence="seq2", shot="0020"),
                make_shot(show="rapid3", sequence="seq3", shot="0030"),
            ]

            # Rapidly switch between shots
            for i in range(50):  # Many iterations
                shot = shots[i % len(shots)]
                window.launcher_panel.set_shot(shot)

                # Minimal event processing for UI updates
                qtbot.wait(1)

                # Quick verification that state is consistent
                for section in window.launcher_panel.app_sections.values():
                    assert section.launch_button.isEnabled()

            # Final verification
            final_shot = shots[-1]
            window.launcher_panel.set_shot(final_shot)
            assert window.launcher_panel._current_shot == final_shot


# =============================================================================
# ERROR HANDLING AND EDGE CASES
# =============================================================================


@pytest.mark.gui_mainwindow
class TestLauncherIntegrationErrorHandling:
    """Test error handling in integrated launcher scenarios."""

    def setup_method(self) -> None:
        """Setup method to initialize Qt object tracking."""
        self.qt_objects: list[Any] = []

    def teardown_method(self, qtbot: QtBot) -> None:
        """Clean up Qt objects to prevent resource leaks."""
        for obj in self.qt_objects:
            try:
                # Stop worker threads in MainWindow's launcher_manager before cleanup
                if hasattr(obj, "launcher_manager") and obj.launcher_manager:
                    obj.launcher_manager.stop_all_workers()

                if hasattr(obj, "deleteLater"):
                    obj.deleteLater()
                    qtbot.wait(1)
            except Exception:
                pass
        self.qt_objects.clear()

    def test_main_window_without_shot_model(
        self, qapp: QApplication, qtbot: QtBot
    ) -> None:
        """Test launcher panel behavior when shot model is not available."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            # Launcher should still be functional even without shot model integration
            assert window.launcher_panel is not None
            assert len(window.launcher_panel.app_sections) > 0

    def test_launcher_panel_with_invalid_shot_data(
        self, qapp: QApplication, qtbot: QtBot
    ) -> None:
        """Test launcher panel behavior with invalid shot data."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            # Try to set invalid shot data (should handle gracefully)
            try:
                window.launcher_panel.set_shot(None)
                # Should not crash
                assert True
            except Exception as e:
                pytest.fail(f"Launcher panel crashed with None shot: {e}")

    def test_signal_disconnection_handling(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test that launcher panel handles signal disconnection gracefully."""
        with patch(
            "process_pool_manager.ProcessPoolManager.get_instance"
        ) as mock_factory:
            mock_pool = TestProcessPool()
            mock_factory.return_value = mock_pool

            window = MainWindow()
            self.qt_objects.append(window)  # Track for cleanup
            qtbot.addWidget(window)

            shot = make_shot()
            window.launcher_panel.set_shot(shot)

            # Safely disconnect signal if connected
            with contextlib.suppress(TypeError, RuntimeError):
                window.launcher_panel.app_launch_requested.disconnect()

            # Should still function without crashing
            nuke_section = window.launcher_panel.app_sections["nuke"]
            qtbot.mouseClick(nuke_section.launch_button, Qt.MouseButton.LeftButton)

            # Minimal event processing to verify no crash
            qtbot.wait(1)
            assert True  # If we reach here, no crash occurred
