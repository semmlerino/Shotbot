"""Tests for undistortion integration in command launchers."""

from unittest.mock import Mock, patch

import pytest

from command_launcher import CommandLauncher
from shot_model import Shot


class TestCommandLauncherUndistortionIntegration:
    """Test undistortion integration in CommandLauncher."""

    @pytest.fixture
    def mock_shot(self):
        """Create a mock Shot object."""
        shot = Mock(spec=Shot)
        shot.workspace_path = "/shows/test_show/shots/seq01/shot01"
        shot.full_name = "seq01_shot01"
        return shot

    @pytest.fixture
    def launcher(self, mock_shot):
        """Create CommandLauncher with mock shot."""
        launcher = CommandLauncher()
        launcher.current_shot = mock_shot
        return launcher

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_launch_nuke_with_both_plate_and_undistortion(
        self, mock_plate_finder, mock_undist_finder, launcher, tmp_path
    ):
        """Test launching Nuke with both plate and undistortion using REAL NukeScriptGenerator."""
        # Create real temporary files for testing
        mock_plate_path = "/path/to/plates/shot01.%04d.exr"

        # Create real undistortion file
        real_undist_path = tmp_path / "shot01_v001.nk"
        real_undist_path.write_text("""# Real Nuke undistortion script
LensDistortion {
 inputs 0
 name LensDistortion1
}""")

        mock_plate_finder.find_latest_raw_plate.return_value = mock_plate_path
        mock_plate_finder.verify_plate_exists.return_value = True
        mock_plate_finder.get_version_from_path.return_value = "v002"

        mock_undist_finder.find_latest_undistortion.return_value = real_undist_path
        mock_undist_finder.get_version_from_path.return_value = "v001"

        # Mock subprocess.Popen to avoid actual terminal launching
        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            # Launch Nuke with both options - uses REAL NukeScriptGenerator
            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Verify Popen was called to launch terminal
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]  # Get the command list
        command_str = " ".join(str(arg) for arg in call_args)

        # Should contain workspace setup and nuke command with generated .nk script
        assert "ws " in command_str  # Workspace setup
        assert "nuke" in command_str  # Nuke command
        assert ".nk" in command_str  # Generated script path

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_launch_nuke_with_undistortion_only(
        self, mock_plate_finder, mock_undist_finder, launcher, tmp_path
    ):
        """Test launching Nuke with undistortion only (no plate) using REAL NukeScriptGenerator."""
        # Create real undistortion file
        real_undist_path = tmp_path / "shot01_v003.nk"
        real_undist_path.write_text("""# Real undistortion script v003
LensDistortion {
 inputs 0
 name LensDistortion1
 selected true
}""")

        mock_plate_finder.find_latest_raw_plate.return_value = None
        mock_undist_finder.find_latest_undistortion.return_value = real_undist_path
        mock_undist_finder.get_version_from_path.return_value = "v003"

        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            # Launch Nuke with undistortion only - uses REAL NukeScriptGenerator
            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Verify a real Nuke script was generated (undistortion-only)
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(str(arg) for arg in call_args)

        # Should contain workspace setup and generated script
        assert "ws " in command_str  # Workspace setup
        assert ".nk" in command_str  # Generated script path

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_launch_nuke_with_plate_only(
        self, mock_plate_finder, mock_undist_finder, launcher
    ):
        """Test launching Nuke with plate only (no undistortion) using REAL NukeScriptGenerator."""
        # Setup mocks - no undistortion available
        mock_plate_path = "/path/to/plates/shot01.%04d.exr"

        mock_plate_finder.find_latest_raw_plate.return_value = mock_plate_path
        mock_plate_finder.verify_plate_exists.return_value = True
        mock_plate_finder.get_version_from_path.return_value = "v004"

        mock_undist_finder.find_latest_undistortion.return_value = None

        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            # Launch Nuke with plate only - uses REAL NukeScriptGenerator
            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Verify a real Nuke script was generated (plate-only)
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(str(arg) for arg in call_args)

        # Should contain workspace setup and generated script
        assert "ws " in command_str  # Workspace setup
        assert ".nk" in command_str  # Generated script path

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_launch_nuke_no_files_found(
        self, mock_plate_finder, mock_undist_finder, launcher
    ):
        """Test launching Nuke when no plate or undistortion files are found."""
        # Setup mocks - no files available
        mock_plate_finder.find_latest_raw_plate.return_value = None
        mock_undist_finder.find_latest_undistortion.return_value = None

        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            # Launch Nuke with both options requested but no files available
            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Should still launch Nuke, just without the additional files
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(str(arg) for arg in call_args)

        # Command should contain workspace setup and basic nuke command
        assert "ws " in command_str  # Workspace setup
        assert "nuke" in command_str  # Basic nuke command

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_launch_nuke_script_generation_failure(
        self, mock_plate_finder, mock_undist_finder, launcher, tmp_path
    ):
        """Test handling when script generation encounters issues using REAL NukeScriptGenerator."""
        # Setup mocks
        mock_plate_path = "/path/to/plates/shot01.%04d.exr"

        # Create real but problematic undistortion file (e.g., empty)
        problematic_undist_path = tmp_path / "problematic_v001.nk"
        problematic_undist_path.write_text("")  # Empty file

        mock_plate_finder.find_latest_raw_plate.return_value = mock_plate_path
        mock_plate_finder.verify_plate_exists.return_value = True
        mock_undist_finder.find_latest_undistortion.return_value = (
            problematic_undist_path
        )

        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            # Launch should still work even if script generation has issues
            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Should still launch Nuke (may or may not have generated script depending on real generator's robustness)
        mock_popen.assert_called_once()

    def test_launch_non_nuke_app_ignores_undistortion(self, launcher):
        """Test that non-Nuke apps ignore undistortion options."""
        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            # Launch Maya with undistortion options (should be ignored)
            success = launcher.launch_app(
                "maya", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Should launch Maya normally without any undistortion processing
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(str(arg) for arg in call_args)
        assert "maya" in command_str

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_signal_emissions_during_undistortion_workflow(
        self, mock_plate_finder, mock_undist_finder, launcher, tmp_path
    ):
        """Test that appropriate signals are emitted during undistortion workflow using REAL NukeScriptGenerator."""
        # Create real undistortion file
        real_undist_path = tmp_path / "shot01_v005.nk"
        real_undist_path.write_text("""# Real Nuke undistortion script v005
LensDistortion {
 inputs 0
 name LensDistortion1
 selected true
}""")

        mock_plate_finder.find_latest_raw_plate.return_value = None
        mock_undist_finder.find_latest_undistortion.return_value = real_undist_path
        mock_undist_finder.get_version_from_path.return_value = "v005"

        # Mock the signal
        launcher.command_executed = Mock()

        # Use REAL NukeScriptGenerator - no mocking
        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            launcher.launch_app("nuke", include_undistortion=True)

        # Verify signals were emitted
        launcher.command_executed.emit.assert_called()

        # Check that undistortion version info was emitted
        emitted_calls = launcher.command_executed.emit.call_args_list
        version_messages = [call[0][1] for call in emitted_calls if len(call[0]) > 1]
        assert any("v005" in msg for msg in version_messages)

    @patch("command_launcher.UndistortionFinder")
    @patch("command_launcher.RawPlateFinder")
    def test_plate_verification_with_undistortion(
        self, mock_plate_finder, mock_undist_finder, launcher, tmp_path
    ):
        """Test that plate verification works correctly with undistortion using REAL NukeScriptGenerator."""
        # Setup mocks - plate found but verification fails
        mock_plate_path = "/path/to/plates/shot01.%04d.exr"

        # Create real undistortion file
        real_undist_path = tmp_path / "shot01_v001.nk"
        real_undist_path.write_text("""# Real Nuke undistortion script v001
LensDistortion {
 inputs 0
 name LensDistortion1
}""")

        mock_plate_finder.find_latest_raw_plate.return_value = mock_plate_path
        mock_plate_finder.verify_plate_exists.return_value = False  # Verification fails
        mock_undist_finder.find_latest_undistortion.return_value = real_undist_path

        # Use REAL NukeScriptGenerator - no mocking
        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful Popen call

            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

        assert success

        # Verify a real Nuke script was generated (undistortion-only since plate verification failed)
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(str(arg) for arg in call_args)

        # Should contain workspace setup and generated script path
        assert "ws " in command_str  # Workspace setup
        assert ".nk" in command_str  # Generated script path

        # Real undistortion file should be referenced somewhere in the command
        # Note: The undistortion path will be embedded in the generated script, not directly in the command
