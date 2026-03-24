"""Unit tests for controllers/shot_selection_controller.py.

Minimal smoke tests for ShotSelectionController which manages shot selection,
async file discovery, and crash recovery.

Tests cover:
1. Shot selection updates command_launcher.current_shot
2. Shot deselection clears state
3. Discovery cancellation on rapid selection
4. Crash recovery requires shot selection (warning shown)
5. Cleanup cancels active worker
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.test_doubles import SignalDouble


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


class ShotGridViewDouble:
    """Test double for ShotGridView."""

    __test__ = False

    def __init__(self) -> None:
        self.shot_selected = SignalDouble()
        self.shot_double_clicked = SignalDouble()
        self.recover_crashes_requested = SignalDouble()


class PreviousShotsViewDouble:
    """Test double for PreviousShotsView."""

    __test__ = False

    def __init__(self) -> None:
        self.shot_selected = SignalDouble()
        self.shot_double_clicked = SignalDouble()


class ThreeDEGridViewDouble:
    """Test double for ThreeDEGridView."""

    __test__ = False

    def __init__(self) -> None:
        self._selected_scene: Any = None

    @property
    def selected_scene(self) -> Any:
        return self._selected_scene


class RightPanelDouble:
    """Test double for RightPanelWidget."""

    __test__ = False

    def __init__(self) -> None:
        self._shot: Any = None
        self._plates: list[str] = []
        self._files: dict[Any, list[Any]] = {}

    def set_shot(self, shot: Any, discover_files: bool = False) -> None:
        self._shot = shot

    def set_available_plates(self, plates: list[str]) -> None:
        self._plates = plates

    def set_files(self, files: dict[Any, list[Any]]) -> None:
        self._files = files

    def discover_rv_sequences(self, shot: Any) -> None:
        pass


class CommandLauncherDouble:
    """Test double for CommandLauncher."""

    __test__ = False

    def __init__(self) -> None:
        self._current_shot: Any = None

    @property
    def current_shot(self) -> Any:
        return self._current_shot

    def set_current_shot(self, shot: Any) -> None:
        self._current_shot = shot

    def launch_app(self, app_name: str) -> bool:
        return True


class SettingsControllerDouble:
    """Test double for SettingsController."""

    __test__ = False

    def __init__(self) -> None:
        self.save_count = 0

    def save_settings(self) -> None:
        self.save_count += 1


class ShotSelectionTargetDouble:
    """Test double implementing ShotSelectionTarget protocol."""

    __test__ = False

    def __init__(self) -> None:
        self.right_panel = RightPanelDouble()
        self.shot_grid = ShotGridViewDouble()
        self.previous_shots_grid = PreviousShotsViewDouble()
        self.threede_shot_grid = ThreeDEGridViewDouble()
        self.command_launcher = CommandLauncherDouble()
        self.settings_controller = SettingsControllerDouble()
        self.last_selected_shot_name: str | None = None
        self._closing = False
        self._window_title = ""
        self._status_message = ""

    @property
    def closing(self) -> bool:
        return self._closing

    def setWindowTitle(self, title: str) -> None:
        self._window_title = title

    def update_status(self, message: str) -> None:
        self._status_message = message


class ShotDouble:
    """Test double for Shot."""

    __test__ = False

    def __init__(
        self,
        show: str = "test_show",
        sequence: str = "sq010",
        shot: str = "sh0010",
        workspace_path: str = "/shows/test_show/shots/sq010/sh0010",
    ) -> None:
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.workspace_path = workspace_path
        self.full_name = f"{sequence}_{shot}"


# ============================================================================
# Tests
# ============================================================================


class TestShotSelectionController:
    """Tests for ShotSelectionController."""

    def test_on_shot_selected_sets_current_shot(self) -> None:
        """Verify command_launcher.set_current_shot() is called."""
        from controllers.shot_selection_controller import ShotSelectionController

        target = ShotSelectionTargetDouble()
        controller = ShotSelectionController(
            target, command_launcher=target.command_launcher
        )  # type: ignore[arg-type]
        shot = ShotDouble()

        controller.on_shot_selected(shot)

        assert target.command_launcher.current_shot == shot

    def test_on_shot_selected_updates_right_panel(self) -> None:
        """Verify right_panel.set_shot() is called."""
        from controllers.shot_selection_controller import ShotSelectionController

        target = ShotSelectionTargetDouble()
        controller = ShotSelectionController(
            target, command_launcher=target.command_launcher
        )  # type: ignore[arg-type]
        shot = ShotDouble()

        controller.on_shot_selected(shot)

        assert target.right_panel._shot == shot

    def test_on_shot_deselected_clears_state(self) -> None:
        """Verify None shot clears all state."""
        from controllers.shot_selection_controller import ShotSelectionController

        target = ShotSelectionTargetDouble()
        controller = ShotSelectionController(
            target, command_launcher=target.command_launcher
        )  # type: ignore[arg-type]

        # First select a shot
        shot = ShotDouble()
        controller.on_shot_selected(shot)

        # Then deselect
        controller.on_shot_selected(None)

        assert target.command_launcher.current_shot is None
        assert target.right_panel._shot is None
        assert target.right_panel._plates == []
        assert target.last_selected_shot_name is None

    def test_discovery_cancellation_on_rapid_selection(self) -> None:
        """Verify old discovery worker is cancelled before starting new one."""
        from controllers.shot_selection_controller import ShotSelectionController

        target = ShotSelectionTargetDouble()
        controller = ShotSelectionController(
            target, command_launcher=target.command_launcher
        )  # type: ignore[arg-type]

        # Create a mock worker
        mock_worker = MagicMock()
        controller._discovery_worker = mock_worker

        # Select a new shot
        shot = ShotDouble()
        controller.on_shot_selected(shot)

        # Previous worker should have been cancelled
        mock_worker.cancel.assert_called_once()

    def test_recover_crashes_requires_selection(self) -> None:
        """Verify warning when no shot selected."""
        from controllers.shot_selection_controller import ShotSelectionController

        target = ShotSelectionTargetDouble()
        target.command_launcher._current_shot = None
        target.threede_shot_grid._selected_scene = None

        controller = ShotSelectionController(
            target, command_launcher=target.command_launcher
        )  # type: ignore[arg-type]

        with patch("managers.notification_manager.NotificationManager") as mock_notif:
            controller.on_recover_crashes_requested()
            mock_notif.warning.assert_called_once()

    def test_cleanup_cancels_active_worker(self) -> None:
        """Verify cleanup cancels any active discovery worker."""
        from controllers.shot_selection_controller import ShotSelectionController

        target = ShotSelectionTargetDouble()
        controller = ShotSelectionController(
            target, command_launcher=target.command_launcher
        )  # type: ignore[arg-type]

        # Create a mock worker
        mock_worker = MagicMock()
        controller._discovery_worker = mock_worker

        controller.cleanup()

        mock_worker.cancel.assert_called_once()
        assert controller._discovery_worker is None
