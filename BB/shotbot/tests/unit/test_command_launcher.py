"""Unit tests for command_launcher.py"""

from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QObject

from command_launcher import CommandLauncher
from config import Config
from shot_model import Shot


class SignalCapture(QObject):
    """Helper to capture Qt signals during tests."""

    def __init__(self):
        super().__init__()
        self.captured_signals = []

    def capture(self, *args):
        """Capture signal arguments."""
        self.captured_signals.append(args)

    def clear(self):
        """Clear captured signals."""
        self.captured_signals = []


class TestCommandLauncher:
    """Test CommandLauncher class."""

    @pytest.fixture
    def launcher(self, qapp):
        """Create a CommandLauncher instance."""
        return CommandLauncher()

    @pytest.fixture
    def signal_capture(self):
        """Create signal capture helper."""
        return SignalCapture()

    @pytest.fixture
    def sample_shot(self):
        """Create a sample shot."""
        return Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
        )

    def test_initialization(self, launcher):
        """Test CommandLauncher initialization."""
        assert launcher.current_shot is None
        assert hasattr(launcher, "command_executed")
        assert hasattr(launcher, "command_error")

    def test_set_current_shot(self, launcher, sample_shot):
        """Test setting current shot."""
        launcher.set_current_shot(sample_shot)
        assert launcher.current_shot == sample_shot

        # Test setting to None
        launcher.set_current_shot(None)
        assert launcher.current_shot is None

    def test_launch_app_no_shot(self, launcher, signal_capture):
        """Test launching app with no shot selected."""
        launcher.command_error.connect(signal_capture.capture)

        result = launcher.launch_app("nuke")

        assert result is False
        assert len(signal_capture.captured_signals) == 1
        timestamp, error = signal_capture.captured_signals[0]
        assert error == "No shot selected"
        assert isinstance(timestamp, str)

    def test_launch_app_unknown_app(self, launcher, sample_shot, signal_capture):
        """Test launching unknown application."""
        launcher.set_current_shot(sample_shot)
        launcher.command_error.connect(signal_capture.capture)

        result = launcher.launch_app("nonexistent_app")

        assert result is False
        assert len(signal_capture.captured_signals) == 1
        timestamp, error = signal_capture.captured_signals[0]
        assert error == "Unknown application: nonexistent_app"

    @patch("subprocess.Popen")
    def test_launch_app_success_gnome_terminal(
        self, mock_popen, launcher, sample_shot, signal_capture
    ):
        """Test successful app launch with gnome-terminal."""
        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        result = launcher.launch_app("nuke")

        assert result is True

        # Check subprocess was called with gnome-terminal
        expected_cmd = [
            "gnome-terminal",
            "--",
            "bash",
            "-i",
            "-c",
            f"ws {sample_shot.workspace_path} && nuke",
        ]
        mock_popen.assert_called_once_with(expected_cmd)

        # Check signal was emitted
        assert len(signal_capture.captured_signals) == 1
        timestamp, command = signal_capture.captured_signals[0]
        assert command == f"ws {sample_shot.workspace_path} && nuke"
        assert isinstance(timestamp, str)

    @patch("subprocess.Popen")
    def test_launch_app_fallback_xterm(
        self, mock_popen, launcher, sample_shot, signal_capture
    ):
        """Test app launch falling back to xterm."""
        # Make gnome-terminal fail
        mock_popen.side_effect = [FileNotFoundError(), Mock()]

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        result = launcher.launch_app("maya")

        assert result is True
        assert mock_popen.call_count == 2

        # Check xterm command
        xterm_call = mock_popen.call_args_list[1]
        xterm_cmd = xterm_call[0][0]
        assert xterm_cmd[0] == "xterm"
        assert xterm_cmd[1] == "-e"

    @patch("subprocess.Popen")
    def test_launch_app_fallback_konsole(self, mock_popen, launcher, sample_shot):
        """Test app launch falling back to konsole."""
        # Make gnome-terminal and xterm fail
        mock_popen.side_effect = [FileNotFoundError(), FileNotFoundError(), Mock()]

        launcher.set_current_shot(sample_shot)

        result = launcher.launch_app("rv")

        assert result is True
        assert mock_popen.call_count == 3

        # Check konsole command
        konsole_call = mock_popen.call_args_list[2]
        konsole_cmd = konsole_call[0][0]
        assert konsole_cmd[0] == "konsole"

    @patch("subprocess.Popen")
    def test_launch_app_direct_execution(self, mock_popen, launcher, sample_shot):
        """Test direct execution when all terminals fail."""
        # Make all terminal commands fail
        mock_popen.side_effect = [
            FileNotFoundError(),  # gnome-terminal
            FileNotFoundError(),  # xterm
            FileNotFoundError(),  # konsole
            Mock(),  # direct execution
        ]

        launcher.set_current_shot(sample_shot)

        result = launcher.launch_app("3de")

        assert result is True
        assert mock_popen.call_count == 4

        # Check direct execution
        direct_call = mock_popen.call_args_list[3]
        assert direct_call[0][0] == [
            "/bin/bash",
            "-i",
            "-c",
            f"ws {sample_shot.workspace_path} && 3de",
        ]

    @patch("subprocess.Popen")
    def test_launch_app_all_fail(
        self, mock_popen, launcher, sample_shot, signal_capture
    ):
        """Test when all launch methods fail."""
        # Make everything fail including direct execution
        mock_popen.side_effect = [
            FileNotFoundError(),  # gnome-terminal
            FileNotFoundError(),  # xterm
            FileNotFoundError(),  # konsole
            RuntimeError("Launch failed"),  # direct execution
        ]

        launcher.set_current_shot(sample_shot)
        launcher.command_error.connect(signal_capture.capture)

        result = launcher.launch_app("publish")

        assert result is False
        assert len(signal_capture.captured_signals) == 1
        timestamp, error = signal_capture.captured_signals[0]
        assert "Failed to launch publish" in error
        assert "Launch failed" in error

    def test_emit_error_format(self, launcher, signal_capture):
        """Test error emission format."""
        launcher.command_error.connect(signal_capture.capture)

        with patch("command_launcher.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:34:56"
            launcher._emit_error("Test error message")

        assert len(signal_capture.captured_signals) == 1
        timestamp, error = signal_capture.captured_signals[0]
        assert timestamp == "12:34:56"
        assert error == "Test error message"

    @patch("subprocess.Popen")
    def test_all_configured_apps(self, mock_popen, launcher, sample_shot):
        """Test launching all configured applications."""
        launcher.set_current_shot(sample_shot)

        for app_name in Config.APPS:
            mock_popen.reset_mock()
            result = launcher.launch_app(app_name)
            assert result is True
            assert mock_popen.called

    @patch("subprocess.Popen")
    def test_command_formatting(
        self, mock_popen, launcher, sample_shot, signal_capture
    ):
        """Test that commands are formatted correctly."""
        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Test with a shot path containing spaces
        shot_with_spaces = Shot(
            show="test show",
            sequence="101 ABC",
            shot="0010",
            workspace_path="/shows/test show/shots/101 ABC/101_ABC_0010",
        )
        launcher.set_current_shot(shot_with_spaces)

        result = launcher.launch_app("nuke")

        assert result is True
        _, command = signal_capture.captured_signals[0]
        assert command == "ws /shows/test show/shots/101 ABC/101_ABC_0010 && nuke"

    @patch("undistortion_finder.UndistortionFinder.get_version_from_path")
    @patch("undistortion_finder.UndistortionFinder.find_latest_undistortion")
    @patch("subprocess.Popen")
    def test_launch_nuke_with_undistortion_found(
        self,
        mock_popen,
        mock_find_undist,
        mock_get_version,
        launcher,
        sample_shot,
        signal_capture,
    ):
        """Test launching Nuke with undistortion file found."""
        from pathlib import Path

        # Mock undistortion file found
        undist_path = Path(
            "/shows/testshow/shots/101_ABC/101_ABC_0010/user/gabriel-h/mm/3de/mm-default/exports/scene/bg01/nuke_lens_distortion/v006/101_ABC_0010_turnover-plate_bg01_aces_v002/101_ABC_0010_mm_default_LD_v006.nk"
        )
        mock_find_undist.return_value = undist_path
        mock_get_version.return_value = "v006"

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch with undistortion
        result = launcher.launch_app("nuke", include_undistortion=True)

        assert result is True

        # Check that find_latest_undistortion was called with correct args
        mock_find_undist.assert_called_once_with(
            sample_shot.workspace_path, sample_shot.full_name
        )

        # Check signals - should have 2: undistortion found message + command
        assert len(signal_capture.captured_signals) == 2

        # Check undistortion found message
        _, message = signal_capture.captured_signals[0]
        assert (
            "Found undistortion file: v006/101_ABC_0010_mm_default_LD_v006.nk"
            in message
        )

        # Check command includes undistortion file
        _, command = signal_capture.captured_signals[1]
        assert command == f"ws {sample_shot.workspace_path} && nuke {undist_path}"

    @patch("undistortion_finder.UndistortionFinder.find_latest_undistortion")
    @patch("subprocess.Popen")
    def test_launch_nuke_with_undistortion_not_found(
        self, mock_popen, mock_find_undist, launcher, sample_shot, signal_capture
    ):
        """Test launching Nuke with undistortion file not found."""
        # Mock undistortion file not found
        mock_find_undist.return_value = None

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch with undistortion
        result = launcher.launch_app("nuke", include_undistortion=True)

        assert result is True

        # Check signals - should have 2: warning + command
        assert len(signal_capture.captured_signals) == 2

        # Check warning message
        _, message = signal_capture.captured_signals[0]
        assert "Warning: Undistortion file not found for this shot" in message

        # Check command is standard (no undistortion file)
        _, command = signal_capture.captured_signals[1]
        assert command == f"ws {sample_shot.workspace_path} && nuke"

    @patch("subprocess.Popen")
    def test_launch_nuke_without_undistortion(
        self, mock_popen, launcher, sample_shot, signal_capture
    ):
        """Test launching Nuke without undistortion option."""
        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch without undistortion (default)
        result = launcher.launch_app("nuke", include_undistortion=False)

        assert result is True

        # Check only one signal (the command)
        assert len(signal_capture.captured_signals) == 1
        _, command = signal_capture.captured_signals[0]
        assert command == f"ws {sample_shot.workspace_path} && nuke"

    @patch("subprocess.Popen")
    def test_launch_other_app_with_undistortion(
        self, mock_popen, launcher, sample_shot, signal_capture
    ):
        """Test that undistortion is ignored for non-Nuke apps."""
        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Try to launch Maya with undistortion (should be ignored)
        result = launcher.launch_app("maya", include_undistortion=True)

        assert result is True

        # Check only one signal (the command)
        assert len(signal_capture.captured_signals) == 1
        _, command = signal_capture.captured_signals[0]
        assert command == f"ws {sample_shot.workspace_path} && maya"

    @patch("raw_plate_finder.RawPlateFinder.verify_plate_exists")
    @patch("raw_plate_finder.RawPlateFinder.get_version_from_path")
    @patch("raw_plate_finder.RawPlateFinder.find_latest_raw_plate")
    @patch("subprocess.Popen")
    def test_launch_nuke_with_raw_plate_found(
        self,
        mock_popen,
        mock_find_plate,
        mock_get_version,
        mock_verify,
        launcher,
        sample_shot,
        signal_capture,
    ):
        """Test launching Nuke with raw plate found."""
        # Mock raw plate found and verified
        plate_path = "/shows/testshow/shots/101_ABC/101_ABC_0010/publish/turnover/plate/input_plate/bg01/v002/exr/4042x2274/101_ABC_0010_turnover-plate_bg01_aces_v002.####.exr"
        mock_find_plate.return_value = plate_path
        mock_verify.return_value = True
        mock_get_version.return_value = "v002"

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch with raw plate
        result = launcher.launch_app(
            "nuke", include_undistortion=False, include_raw_plate=True
        )

        assert result is True

        # Check that find_latest_raw_plate was called with correct args
        mock_find_plate.assert_called_once_with(
            sample_shot.workspace_path, sample_shot.full_name
        )

        # Check verify was called
        mock_verify.assert_called_once_with(plate_path)

        # Check signals - should have 2: plate found message + command
        assert len(signal_capture.captured_signals) == 2

        # Check plate found message
        _, message = signal_capture.captured_signals[0]
        assert "Found raw plate: v002/" in message
        assert ".####.exr" in message

        # Check command includes plate file
        _, command = signal_capture.captured_signals[1]
        assert command == f"ws {sample_shot.workspace_path} && nuke {plate_path}"

    @patch("raw_plate_finder.RawPlateFinder.find_latest_raw_plate")
    @patch("subprocess.Popen")
    def test_launch_nuke_with_raw_plate_not_found(
        self, mock_popen, mock_find_plate, launcher, sample_shot, signal_capture
    ):
        """Test launching Nuke with raw plate not found."""
        # Mock raw plate not found
        mock_find_plate.return_value = None

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch with raw plate
        result = launcher.launch_app("nuke", include_raw_plate=True)

        assert result is True

        # Check signals - should have 2: warning + command
        assert len(signal_capture.captured_signals) == 2

        # Check warning message
        _, message = signal_capture.captured_signals[0]
        assert "Warning: Raw plate not found for this shot" in message

        # Check command is standard (no plate file)
        _, command = signal_capture.captured_signals[1]
        assert command == f"ws {sample_shot.workspace_path} && nuke"

    @patch("raw_plate_finder.RawPlateFinder.verify_plate_exists")
    @patch("raw_plate_finder.RawPlateFinder.find_latest_raw_plate")
    @patch("subprocess.Popen")
    def test_launch_nuke_with_raw_plate_no_frames(
        self,
        mock_popen,
        mock_find_plate,
        mock_verify,
        launcher,
        sample_shot,
        signal_capture,
    ):
        """Test launching Nuke with raw plate path found but no frames."""
        # Mock plate path found but no frames exist
        plate_path = "/shows/test/plate.####.exr"
        mock_find_plate.return_value = plate_path
        mock_verify.return_value = False

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch with raw plate
        result = launcher.launch_app("nuke", include_raw_plate=True)

        assert result is True

        # Check signals - should have 2: warning + command
        assert len(signal_capture.captured_signals) == 2

        # Check warning message
        _, message = signal_capture.captured_signals[0]
        assert "Warning: Raw plate path found but no frames exist" in message

        # Check command is standard (no plate file)
        _, command = signal_capture.captured_signals[1]
        assert command == f"ws {sample_shot.workspace_path} && nuke"

    @patch("undistortion_finder.UndistortionFinder.get_version_from_path")
    @patch("undistortion_finder.UndistortionFinder.find_latest_undistortion")
    @patch("raw_plate_finder.RawPlateFinder.verify_plate_exists")
    @patch("raw_plate_finder.RawPlateFinder.get_version_from_path")
    @patch("raw_plate_finder.RawPlateFinder.find_latest_raw_plate")
    @patch("subprocess.Popen")
    def test_launch_nuke_with_both_options(
        self,
        mock_popen,
        mock_find_plate,
        mock_get_plate_ver,
        mock_verify,
        mock_find_undist,
        mock_get_undist_ver,
        launcher,
        sample_shot,
        signal_capture,
    ):
        """Test launching Nuke with both raw plate and undistortion."""
        from pathlib import Path

        # Mock both files found
        plate_path = "/shows/test/plate.####.exr"
        undist_path = Path("/shows/test/undist.nk")

        mock_find_plate.return_value = plate_path
        mock_verify.return_value = True
        mock_get_plate_ver.return_value = "v002"

        mock_find_undist.return_value = undist_path
        mock_get_undist_ver.return_value = "v006"

        launcher.set_current_shot(sample_shot)
        launcher.command_executed.connect(signal_capture.capture)

        # Launch with both options
        result = launcher.launch_app(
            "nuke", include_undistortion=True, include_raw_plate=True
        )

        assert result is True

        # Check signals - should have 3: plate found, undist found, command
        assert len(signal_capture.captured_signals) == 3

        # Check messages
        assert "Found raw plate: v002/" in signal_capture.captured_signals[0][1]
        assert "Found undistortion file: v006/" in signal_capture.captured_signals[1][1]

        # Check command includes both files (plate first, then undistortion)
        _, command = signal_capture.captured_signals[2]
        assert (
            command
            == f"ws {sample_shot.workspace_path} && nuke {plate_path} {undist_path}"
        )
