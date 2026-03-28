"""Tests for RV plate launch routing through the standard launch pipeline.

Verifies that _open_main_plate_in_rv in GridContextMenuMixin correctly:
- Discovers the main plate using find_main_plate
- Delegates to CommandLauncher.launch() with the appropriate LaunchRequest
- Shows an error notification when no plate is found
- Shows an error notification when no launcher is available
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from ui.grid_context_menu_mixin import GridContextMenuMixin


if TYPE_CHECKING:
    from launch.launch_request import LaunchRequest


pytestmark = [pytest.mark.unit]


# ============================================================================
# Test Doubles
# ============================================================================


class _ItemDouble:
    """Minimal item double with a workspace_path attribute."""

    def __init__(self, workspace_path: str) -> None:
        self.workspace_path = workspace_path


class _MixinConsumer(GridContextMenuMixin):
    """Minimal mixin consumer with logger and optional CommandLauncher."""

    def __init__(self, command_launcher: object | None = None) -> None:
        self.logger = logging.getLogger("test")
        if command_launcher is not None:
            self._command_launcher = command_launcher


# ============================================================================
# Tests: RV plate launch routing
# ============================================================================


@pytest.mark.unit
class TestOpenMainPlateInRV:
    """Tests for GridContextMenuMixin._open_main_plate_in_rv."""

    @patch("discovery.find_main_plate", return_value=None)
    def test_no_plate_found_shows_notification(self, mock_find: MagicMock) -> None:
        """When find_main_plate returns None, shows error notification."""
        from managers.notification_manager import NotificationManager

        consumer = _MixinConsumer()
        with patch.object(NotificationManager, "error") as mock_notify:
            consumer._open_main_plate_in_rv(_ItemDouble("/some/workspace"))

        mock_notify.assert_called_once()
        title, _ = mock_notify.call_args[0]
        assert title == "No Plate Found"

    @patch("discovery.find_main_plate", return_value=None)
    def test_no_plate_found_does_not_call_launcher(
        self, mock_find: MagicMock
    ) -> None:
        """When no plate is found, CommandLauncher.launch is never called."""
        launcher = MagicMock()
        consumer = _MixinConsumer(command_launcher=launcher)

        with patch("managers.notification_manager.NotificationManager.error"):
            consumer._open_main_plate_in_rv(_ItemDouble("/some/workspace"))

        launcher.launch.assert_not_called()

    @patch("discovery.find_main_plate", return_value="/shots/abc/plates/abc.%04d.exr")
    def test_no_launcher_available_shows_notification(
        self, mock_find: MagicMock
    ) -> None:
        """When _command_launcher is absent, shows error notification."""
        from managers.notification_manager import NotificationManager

        consumer = _MixinConsumer()  # no launcher
        with patch.object(NotificationManager, "error") as mock_notify:
            consumer._open_main_plate_in_rv(_ItemDouble("/some/workspace"))

        mock_notify.assert_called_once()
        title, _ = mock_notify.call_args[0]
        assert title == "RV Launch Failed"

    @patch("discovery.find_main_plate", return_value="/shots/abc/plates/abc.%04d.exr")
    def test_delegates_to_command_launcher_with_rv_app(
        self, mock_find: MagicMock
    ) -> None:
        """When plate found and launcher available, calls launcher.launch with app_name='rv'."""
        launcher = MagicMock()
        consumer = _MixinConsumer(command_launcher=launcher)

        consumer._open_main_plate_in_rv(_ItemDouble("/shots/abc"))

        launcher.launch.assert_called_once()
        request: LaunchRequest = launcher.launch.call_args[0][0]
        assert request.app_name == "rv"

    @patch("discovery.find_main_plate", return_value="/shots/abc/plates/abc.%04d.exr")
    def test_launch_request_carries_plate_as_sequence_path(
        self, mock_find: MagicMock
    ) -> None:
        """LaunchRequest passes the plate path as context.sequence_path."""
        launcher = MagicMock()
        consumer = _MixinConsumer(command_launcher=launcher)

        consumer._open_main_plate_in_rv(_ItemDouble("/shots/abc"))

        request: LaunchRequest = launcher.launch.call_args[0][0]
        assert request.context is not None
        assert request.context.sequence_path == "/shots/abc/plates/abc.%04d.exr"

    @patch("discovery.find_main_plate", return_value="/shots/abc/plates/abc.%04d.exr")
    def test_launch_request_carries_workspace_path(
        self, mock_find: MagicMock
    ) -> None:
        """LaunchRequest carries the item's workspace_path."""
        launcher = MagicMock()
        consumer = _MixinConsumer(command_launcher=launcher)

        consumer._open_main_plate_in_rv(_ItemDouble("/shots/abc"))

        request: LaunchRequest = launcher.launch.call_args[0][0]
        assert request.workspace_path == "/shots/abc"

    @patch("discovery.find_main_plate", return_value="/shots/abc/plates/abc.%04d.exr")
    def test_find_main_plate_called_with_workspace_path(
        self, mock_find: MagicMock
    ) -> None:
        """find_main_plate is called with the item's workspace_path."""
        launcher = MagicMock()
        consumer = _MixinConsumer(command_launcher=launcher)

        consumer._open_main_plate_in_rv(_ItemDouble("/shots/abc"))

        mock_find.assert_called_once_with("/shots/abc")

    @patch("discovery.find_main_plate", return_value="/shots/abc/plates/abc.%04d.exr")
    def test_launch_request_has_no_file_path_or_scene(
        self, mock_find: MagicMock
    ) -> None:
        """LaunchRequest leaves file_path and scene as None (standard launch path)."""
        launcher = MagicMock()
        consumer = _MixinConsumer(command_launcher=launcher)

        consumer._open_main_plate_in_rv(_ItemDouble("/shots/abc"))

        request: LaunchRequest = launcher.launch.call_args[0][0]
        assert request.file_path is None
        assert request.scene is None
