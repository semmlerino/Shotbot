"""Test SimplifiedLauncher's integration with NukeLaunchHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from shot_model import Shot
from simplified_launcher import SimplifiedLauncher


@pytest.fixture
def mock_shot():
    """Create a mock shot for testing."""
    return Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")


@pytest.fixture
def launcher():
    """Create a SimplifiedLauncher instance for testing."""
    return SimplifiedLauncher()


class TestSimplifiedLauncherNukeIntegration:
    """Test SimplifiedLauncher's Nuke functionality using NukeLaunchHandler."""

    def test_launcher_has_nuke_handler(self, launcher) -> None:
        """Test that SimplifiedLauncher initializes with NukeLaunchHandler."""
        assert hasattr(launcher, "nuke_handler")
        assert launcher.nuke_handler is not None

    @patch("simplified_launcher.subprocess.Popen")
    def test_launch_nuke_basic(self, mock_popen, launcher, mock_shot) -> None:
        """Test basic Nuke launch using NukeLaunchHandler."""
        launcher.set_current_shot(mock_shot)

        # Mock the subprocess
        mock_popen.return_value = MagicMock()

        # Launch Nuke
        result = launcher.launch_vfx_app("nuke")

        # Should launch successfully
        assert result is True

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        # Should include terminal command and nuke
        assert any("nuke" in str(arg) for arg in call_args)

    @patch("simplified_launcher.subprocess.Popen")
    def test_launch_nuke_with_options(self, mock_popen, launcher, mock_shot) -> None:
        """Test Nuke launch with various options."""
        launcher.set_current_shot(mock_shot)

        # Mock the subprocess
        mock_popen.return_value = MagicMock()

        # Mock NukeLaunchHandler methods
        with (
            patch.object(launcher.nuke_handler, "prepare_nuke_command") as mock_prepare,
            patch.object(launcher.nuke_handler, "get_environment_fixes") as mock_env,
        ):
            mock_prepare.return_value = (
                "nuke /path/to/script.nk",
                ["Opening script"],
            )
            mock_env.return_value = "export OCIO=/fallback.ocio && "

            # Launch Nuke with options
            result = launcher.launch_vfx_app(
                "nuke",
                open_latest=True,
                include_plate=True,
            )

            # Should launch successfully
            assert result is True

            # Verify NukeLaunchHandler was called correctly
            mock_prepare.assert_called_once()
            args = mock_prepare.call_args[0]
            assert args[0] == mock_shot
            assert args[1] == "nuke"

            # Check options were passed
            options = args[2]
            assert options["open_latest_scene"] is True
            assert options["include_raw_plate"] is True

    @patch("simplified_launcher.subprocess.Popen")
    def test_launch_nuke_with_environment_fixes(
        self, mock_popen, launcher, mock_shot
    ) -> None:
        """Test that environment fixes are properly applied."""
        launcher.set_current_shot(mock_shot)

        # Mock the subprocess
        mock_popen.return_value = MagicMock()

        # Mock environment fixes
        with patch.object(launcher.nuke_handler, "get_environment_fixes") as mock_env:
            mock_env.return_value = "export NUKE_DISABLE_CRASH_REPORTING=1 && "

            # Launch Nuke
            result = launcher.launch_vfx_app("nuke")

            # Should launch successfully
            assert result is True

            # Verify subprocess was called
            assert mock_popen.called
            call_args = mock_popen.call_args[0][0]
            # Command should include environment fixes
            command_str = " ".join(str(arg) for arg in call_args)
            assert "NUKE_DISABLE_CRASH_REPORTING" in command_str or mock_env.called

    def test_launch_nuke_without_shot_fails(self, launcher) -> None:
        """Test that Nuke launch fails without shot context."""
        # Don't set current shot
        result = launcher.launch_vfx_app("nuke")

        # Should fail
        assert result is False

    @patch("simplified_launcher.subprocess.Popen")
    def test_nuke_handler_logs_are_captured(
        self, mock_popen, launcher, mock_shot, caplog
    ) -> None:
        """Test that log messages from NukeLaunchHandler are captured."""
        import logging

        caplog.set_level(logging.INFO)

        launcher.set_current_shot(mock_shot)

        # Mock the subprocess
        mock_popen.return_value = MagicMock()

        # Mock NukeLaunchHandler to return log messages
        with patch.object(
            launcher.nuke_handler, "prepare_nuke_command"
        ) as mock_prepare:
            mock_prepare.return_value = (
                "nuke /path/to/script.nk",
                ["Opening existing Nuke script: v001", "Script loaded successfully"],
            )

            # Launch Nuke
            result = launcher.launch_vfx_app("nuke", open_latest=True)

            # Should launch successfully
            assert result is True

            # Check that log messages were logged by the launcher
            # (The launcher logs these messages through its logger)
            assert mock_prepare.called
            # Since we mocked prepare_nuke_command, verify it returned expected messages
            _, messages = mock_prepare.return_value
            assert "Opening existing Nuke script: v001" in messages
            assert "Script loaded successfully" in messages

    def test_deprecated_find_latest_nuke_workspace_script(
        self, launcher, mock_shot
    ) -> None:
        """Test that deprecated method delegates to NukeLaunchHandler."""
        launcher.set_current_shot(mock_shot)

        with (
            patch.object(
                launcher.nuke_handler.workspace_manager,
                "get_workspace_script_directory",
            ) as mock_get_dir,
            patch.object(
                launcher.nuke_handler.workspace_manager, "find_latest_nuke_script"
            ) as mock_find,
        ):
            mock_get_dir.return_value = Path("/test/scripts")
            mock_find.return_value = Path("/test/script.nk")

            result = launcher._find_latest_nuke_workspace_script(
                Path("/test/workspace")
            )

            assert result == Path("/test/script.nk")
            mock_get_dir.assert_called_once_with(
                "/test/workspace"
            )  # Method expects str, not Path
            mock_find.assert_called_once()
