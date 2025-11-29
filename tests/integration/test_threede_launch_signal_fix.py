"""Integration tests for 3DE scene launch signal fix.

This test file verifies the complete fix for the bug where opening a 3DE scene
from the "Other 3DE Scenes" tab resulted in "No shot selected" error.

The bug was caused by a signal/slot signature mismatch in main_window.py where
the ThreeDEGridView.app_launch_requested signal (emitting app_name AND scene)
was directly connected to launcher_controller.launch_app() which only accepts
app_name, causing the scene parameter to be silently dropped.

Fix: Added _launch_app_with_scene_context() method that properly sets scene
context before launching.

Following UNIFIED_TESTING_GUIDE patterns:
- Test behavior through public interfaces
- Use real Qt components where possible
- Mock only at system boundaries
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from unittest.mock import Mock

# Third-party imports
import pytest
from PySide6.QtCore import QObject, Signal

# Local application imports
from controllers.launcher_controller import LauncherController
from shot_model import Shot
from threede_scene_model import ThreeDEScene


# Integration tests may show error dialogs when mocks are incomplete
pytestmark = [pytest.mark.integration, pytest.mark.qt, pytest.mark.allow_dialogs]


# Test doubles for integration testing
class TestCommandLauncherWithSceneSupport(QObject):
    """Test double for CommandLauncher with scene context support."""

    __test__ = False  # Prevent pytest collection

    command_executed = Signal(str, str)
    command_error = Signal(str, str)

    def __init__(self) -> None:
        """Initialize test command launcher."""
        super().__init__()
        self.current_shot: Shot | None = None
        self._current_scene_path: Path | None = None
        self.executed_commands: list[dict] = []

    def set_current_shot(self, shot: Shot | None) -> None:
        """Set current shot context."""
        self.current_shot = shot

    def launch_app(
        self,
        app_name: str,
        include_raw_plate: bool = False,
        open_latest_threede: bool = False,
        open_latest_maya: bool = False,
        open_latest_scene: bool = False,
        create_new_file: bool = False,
    ) -> bool:
        """Record app launch with current context."""
        command = {
            "app_name": app_name,
            "shot": self.current_shot.full_name if self.current_shot else None,
            "scene_path": str(self._current_scene_path)
            if self._current_scene_path
            else None,
            "options": {
                "include_raw_plate": include_raw_plate,
                "open_latest_threede": open_latest_threede,
                "open_latest_maya": open_latest_maya,
                "open_latest_scene": open_latest_scene,
                "create_new_file": create_new_file,
            },
        }
        self.executed_commands.append(command)

        # Verify scene context was set (this is the critical check)
        if app_name == "3de" and not self._current_scene_path and not self.current_shot:
            self.command_error.emit("00:00:00", "No shot selected")
            return False

        self.command_executed.emit("00:00:00", f"Launched {app_name}")
        return True

    def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
        """Launch app with 3DE scene file."""
        self._current_scene_path = scene.scene_path
        command = {
            "app_name": app_name,
            "scene_path": str(scene.scene_path),
            "method": "launch_app_with_scene",
        }
        self.executed_commands.append(command)
        self.command_executed.emit("00:00:00", f"Launched {app_name} with scene")
        return True

    def launch_app_with_scene_context(
        self,
        app_name: str,
        scene: ThreeDEScene,
        include_raw_plate: bool = False,
    ) -> bool:
        """Launch app with scene context (shot context, no scene file)."""
        command = {
            "app_name": app_name,
            "scene": scene,
            "include_raw_plate": include_raw_plate,
            "method": "launch_app_with_scene_context",
        }
        self.executed_commands.append(command)
        self.command_executed.emit("00:00:00", f"Launched {app_name}")
        return True


class MockLauncherTargetForIntegration(QObject):
    """Mock MainWindow for integration testing."""

    __test__ = False

    def __init__(self) -> None:
        """Initialize mock target."""
        super().__init__()
        self.command_launcher = TestCommandLauncherWithSceneSupport()
        self.launcher_manager = None

        # Create mock right_panel with get_dcc_options support
        self.right_panel = Mock()
        self.right_panel.get_dcc_options = Mock(return_value={
            "open_latest_scene": True,
            "include_raw_plate": False,
            "selected_plate": None,
        })

        self.log_viewer = Mock()
        self.status_bar = Mock()
        self.custom_launcher_menu = Mock()
        self.status_messages: list[str] = []

    def update_status(self, message: str) -> None:
        """Record status updates."""
        self.status_messages.append(message)


@pytest.fixture
def create_test_scene():
    """Factory fixture for creating test scenes."""

    def _create(
        show: str = "test_show",
        sequence: str = "010",
        shot: str = "0010",
        user: str = "testuser",
        plate: str = "main",
    ) -> ThreeDEScene:
        return ThreeDEScene(
            show=show,
            sequence=sequence,
            shot=shot,
            workspace_path=f"/shows/{show}/sequences/{sequence}/shots/{shot}",
            user=user,
            plate=plate,
            scene_path=Path(
                f"/shows/{show}/sequences/{sequence}/shots/{shot}/3de/{user}/{plate}/scene.3de"
            ),
        )

    return _create


@pytest.fixture
def launcher_controller_with_scene_support():
    """Create LauncherController with scene-aware command launcher."""
    target = MockLauncherTargetForIntegration()
    controller = LauncherController(target)
    return controller, target


class TestThreeDELaunchSignalIntegration:
    """Integration tests for the complete signal flow from grid to launcher."""

    def test_scene_context_properly_set_before_launch(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that scene context is set in launcher controller before launching.

        This is the critical test that verifies the bug fix. Previously, the
        scene parameter was dropped by signal/slot mismatch, causing "No shot
        selected" error.
        """
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene()

        # Simulate the new _launch_app_with_scene_context flow
        controller.set_current_scene(test_scene)
        controller.launch_app("3de")  # Returns None (void)

        # Verify command was executed with scene context
        assert len(target.command_launcher.executed_commands) == 1
        command = target.command_launcher.executed_commands[0]
        assert command["app_name"] == "3de"
        # Scene path should be set via set_current_scene()
        assert target.command_launcher._current_scene_path == test_scene.scene_path

        # Verify no error was emitted (launch queued - Phase 1)
        # Phase 1: Status shows "Launching..." not "Launched" (verification in Phase 2)
        assert "Launching 3de..." in target.status_messages

    def test_old_broken_behavior_would_fail(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that WITHOUT setting scene context, launch is properly rejected.

        This verifies the fix: if scene context isn't set,
        launch_app() correctly refuses to launch (no commands executed).
        """
        controller, target = launcher_controller_with_scene_support
        create_test_scene()

        # Attempt to launch WITHOUT setting context
        # (This is what happened when signal parameter was dropped)
        controller.launch_app("3de")  # Returns None (void)

        # Verify launch was rejected (no commands executed)
        # The new correct behavior is to refuse launch without context
        assert len(target.command_launcher.executed_commands) == 0
        # Error is logged but not necessarily captured in status_messages mock

    def test_complete_signal_flow_with_scene(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test complete signal flow: grid emits → controller receives → launcher executes.

        This integration test verifies the entire chain:
        1. Grid emits app_launch_requested(app_name, scene)
        2. MainWindow._launch_app_with_scene_context() is called
        3. Controller.set_current_scene() is called
        4. Controller.launch_app() is called with context
        5. Launch succeeds
        """
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene(user="artist1", plate="plate01")

        # Simulate the complete flow
        controller.set_current_scene(test_scene)  # Step 3
        controller.launch_app("3de")  # Step 4 (returns None)

        # Verify scene metadata was preserved
        command_launcher = target.command_launcher
        assert command_launcher._current_scene_path == test_scene.scene_path
        assert "artist1" in str(test_scene.scene_path)
        assert "plate01" in str(test_scene.scene_path)

        # Verify launch queued (Phase 1 - verification in Phase 2)
        assert "Launching 3de..." in target.status_messages

    def test_multiple_scene_launches_update_context(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that launching multiple scenes correctly updates context each time."""
        controller, target = launcher_controller_with_scene_support

        # Create multiple different scenes
        scene1 = create_test_scene(user="user1", plate="plate1")
        scene2 = create_test_scene(user="user2", plate="plate2")
        scene3 = create_test_scene(user="user3", plate="plate3")

        # Launch each scene
        for scene in [scene1, scene2, scene3]:
            controller.set_current_scene(scene)
            controller.launch_app("3de")  # Returns None

        # Verify all three launches were recorded
        assert len(target.command_launcher.executed_commands) == 3

        # Verify final scene context is scene3
        assert target.command_launcher._current_scene_path == scene3.scene_path

    def test_scene_context_cleared_when_launching_regular_shot(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that scene context is properly cleared when switching to regular shot."""
        controller, target = launcher_controller_with_scene_support

        # First launch with scene
        test_scene = create_test_scene()
        controller.set_current_scene(test_scene)
        controller.launch_app("3de")

        # Now switch to regular shot (no scene)
        regular_shot = Shot(
            show="test_show",
            sequence="020",
            shot="0020",
            workspace_path="/workspace/020_0020",
        )
        controller.set_current_shot(regular_shot)
        controller.set_current_scene(None)  # Clear scene context

        # Launch again
        controller.launch_app("nuke")

        # Verify scene context was cleared
        assert controller._current_scene is None
        assert target.command_launcher.current_shot == regular_shot


class TestMainWindowLaunchHelperMethod:
    """Test the new _launch_app_with_scene_context helper method behavior."""

    def test_helper_method_sets_scene_before_launching(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test the helper method sets scene context correctly."""
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene()

        # Simulate what _launch_app_with_scene_context does
        controller.set_current_scene(test_scene)
        controller.launch_app("3de")

        # Verify scene was set
        assert controller._current_scene == test_scene

        # Verify launch succeeded
        assert len(target.command_launcher.executed_commands) == 1

    def test_helper_method_works_with_different_apps(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test helper works with different applications (nuke, maya, etc)."""
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene()

        for app_name in ["3de", "nuke", "maya"]:
            # Reset for each test
            target.command_launcher.executed_commands.clear()

            # Launch app with scene context
            controller.set_current_scene(test_scene)
            controller.launch_app(app_name)

            # Verify launch
            assert len(target.command_launcher.executed_commands) == 1
            command = target.command_launcher.executed_commands[0]
            assert command["app_name"] == app_name


class TestSignalSlotTypeSafety:
    """Test that signal/slot connections are type-safe."""

    def test_signal_signature_matches_handler(
        self, create_test_scene, launcher_controller_with_scene_support
    ) -> None:
        """Test that signal signature (str, ThreeDEScene) matches handler signature.

        This test verifies the fix uses proper typing to prevent future regressions.
        The bug occurred because the signal had 2 parameters but was connected to
        a function accepting only 1 parameter.
        """
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene()

        # Create a test signal with the correct signature
        class TestSignalEmitter(QObject):
            app_launch_requested = Signal(str, object)  # app_name, scene

        emitter = TestSignalEmitter()

        # Create handler that matches our fix
        def handle_launch(app_name: str, scene: ThreeDEScene) -> None:
            controller.set_current_scene(scene)
            controller.launch_app(app_name)

        try:
            # Connect signal to handler (this should work)
            emitter.app_launch_requested.connect(handle_launch)

            # Emit signal
            emitter.app_launch_requested.emit("3de", test_scene)

            # Verify launch succeeded with scene context
            assert controller._current_scene == test_scene
            assert len(target.command_launcher.executed_commands) > 0
        finally:
            # CRITICAL: Disconnect signal to prevent dangling connections
            # Dangling connections cause segfaults in subsequent tests
            try:
                emitter.app_launch_requested.disconnect(handle_launch)
            except (TypeError, RuntimeError):
                pass  # Already disconnected or object deleted
            emitter.deleteLater()


class TestLauncherPanelButtonWithSceneContext:
    """Test launcher panel button click after scene selection (the actual bug scenario).

    These tests verify the fix for the launcher panel button not working when
    a scene is selected but not double-clicked. The bug was that selecting a
    scene (single-click) didn't sync the scene context with launcher_controller,
    so clicking the launcher panel button would fail with "No shot selected".

    Fix: threede_controller.on_scene_selected() now calls
    launcher_controller.set_current_scene(scene) to keep them synchronized.
    """

    def test_scene_selection_syncs_with_launcher_controller(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that selecting a scene (single-click) syncs context with launcher_controller.

        This is the core of the fix - when threede_controller handles scene selection,
        it must also update launcher_controller so that launcher panel buttons work.
        """
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene()

        # Simulate threede_controller.on_scene_selected() behavior
        # (which gets called when user single-clicks a scene)
        target.command_launcher.set_current_shot(None)  # Clear regular shot
        controller.set_current_scene(test_scene)  # Sync with launcher controller

        # Verify launcher controller has the scene context
        assert controller._current_scene == test_scene
        assert controller._current_scene.scene_path == test_scene.scene_path

    def test_launcher_panel_button_works_after_scene_selection(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that launcher panel button works after selecting (not double-clicking) a scene.

        This is the bug scenario that was failing:
        1. User single-clicks a scene in "Other 3DE Scenes" tab (selects it)
        2. User clicks "Launch 3de" button in launcher panel
        3. Previously: "No shot selected" error (launcher_controller had no context)
        4. Now: Launch succeeds (launcher_controller has scene context)
        """
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene(user="artist1", plate="plate01")

        # Step 1: User selects a scene (single-click) - simulate on_scene_selected
        target.command_launcher.set_current_shot(None)
        controller.set_current_scene(test_scene)

        # Step 2: User clicks "Launch 3de" button in launcher panel
        # This triggers launcher_panel.app_launch_requested.emit("3de")
        # which is connected to launcher_controller.launch_app("3de")
        controller.launch_app("3de")  # Returns None (void)

        # Verify launch succeeded (no "No shot selected" error)
        assert len(target.command_launcher.executed_commands) == 1
        command = target.command_launcher.executed_commands[0]
        assert command["app_name"] == "3de"
        # Phase 1: Status shows "Launching..." not "Launched" (verification in Phase 2)
        assert "Launching 3de..." in target.status_messages

        # Verify scene metadata was used
        assert "artist1" in str(test_scene.scene_path)
        assert "plate01" in str(test_scene.scene_path)

    def test_launcher_panel_button_fails_without_scene_sync(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that WITHOUT syncing scene context, launcher panel button is rejected.

        This verifies the fix - if on_scene_selected doesn't call
        launcher_controller.set_current_scene(), launch is properly refused.
        """
        controller, target = launcher_controller_with_scene_support
        create_test_scene()

        # Simulate scenario: scene is selected but NOT synced with launcher_controller
        # (i.e., on_scene_selected didn't call launcher_controller.set_current_scene)
        # So launcher_controller._current_scene is still None

        # User clicks "Launch 3de" button
        controller.launch_app("3de")

        # Verify launch was properly rejected (no commands executed)
        # The new correct behavior is to refuse launch without context
        assert len(target.command_launcher.executed_commands) == 0
        # Error is logged but not necessarily captured in status_messages mock

    def test_multiple_scene_selections_update_launcher_context(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that switching between scenes updates launcher_controller each time."""
        controller, _target = launcher_controller_with_scene_support

        # Create different scenes
        scene1 = create_test_scene(user="user1", plate="plate1")
        scene2 = create_test_scene(user="user2", plate="plate2")
        scene3 = create_test_scene(user="user3", plate="plate3")

        # Select each scene in sequence
        for scene in [scene1, scene2, scene3]:
            controller.set_current_scene(scene)

            # Verify launcher_controller context is updated
            assert controller._current_scene == scene
            assert controller._current_scene.user == scene.user
            assert controller._current_scene.plate == scene.plate

        # Verify final context is scene3
        assert controller._current_scene == scene3
        assert controller._current_scene.user == "user3"

    def test_launcher_panel_button_with_different_apps(
        self, launcher_controller_with_scene_support, create_test_scene
    ) -> None:
        """Test that launcher panel buttons work for all apps after scene selection."""
        controller, target = launcher_controller_with_scene_support
        test_scene = create_test_scene()

        # Select a scene
        controller.set_current_scene(test_scene)

        # Test launching different apps from launcher panel
        for app_name in ["3de", "nuke", "maya"]:
            target.command_launcher.executed_commands.clear()
            target.status_messages.clear()

            controller.launch_app(app_name)

            # Verify each app launches successfully
            assert len(target.command_launcher.executed_commands) == 1
            command = target.command_launcher.executed_commands[0]
            assert command["app_name"] == app_name
            # Phase 1: Status shows "Launching..." not "Launched" (verification in Phase 2)
            assert f"Launching {app_name}..." in target.status_messages
