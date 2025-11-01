"""Integration tests for complete undistortion workflow."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from command_launcher import CommandLauncher
from nuke_script_generator import NukeScriptGenerator
from raw_plate_finder import RawPlateFinder
from shot_model import Shot
from undistortion_finder import UndistortionFinder


class TestUndistortionWorkflowIntegration:
    """Integration tests for complete undistortion workflow."""

    @pytest.fixture
    def vfx_project_structure(self, tmp_path):
        """Create a realistic VFX project directory structure."""
        project = tmp_path / "shows" / "test_project" / "shots" / "seq01" / "shot01"

        # Create shot workspace structure
        workspace_path = project / "workspace"
        workspace_path.mkdir(parents=True)

        # Create undistortion structure matching what UndistortionFinder expects
        # workspace_path / "user" / username / "mm" / "3de" / "mm-default" / "exports" / "scene" / "bg01" / "nuke_lens_distortion"
        undist_base = (
            workspace_path
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "bg01"
            / "nuke_lens_distortion"
        )
        undist_v001 = undist_base / "v001" / "shot01_turnover-plate_bg01_aces_v002"
        undist_v001.mkdir(parents=True)

        undist_v002 = undist_base / "v002" / "shot01_turnover-plate_bg01_aces_v002"
        undist_v002.mkdir(parents=True)

        # Create undistortion files
        undist_file_v001 = undist_v001 / "shot01_mm_default_LD_v001.nk"
        undist_file_v001.write_text("""# Nuke undistortion script v001
Root {
 inputs 0
 name shot01_undistortion_v001
}

LensDistortion {
 inputs 0
 serializeKnob ""
 model_card "3DE4 Anamorphic - Degree 6"
 name LensDistortion1
}""")

        undist_file_v002 = undist_v002 / "shot01_mm_default_LD_v002.nk"
        undist_file_v002.write_text("""# Nuke undistortion script v002
Root {
 inputs 0
 name shot01_undistortion_v002
}

LensDistortion {
 inputs 0
 serializeKnob ""
 model_card "3DE4 Anamorphic - Degree 6" 
 name LensDistortion1
 selected true
}""")

        # Create raw plate structure exactly matching what RawPlateFinder expects
        # RawPlateFinder expects: base_path / plate_name / version / "exr" / resolution / files
        plate_base = workspace_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create BG01 plate structure
        bg01_v001 = plate_base / "BG01" / "v001" / "exr" / "4312x2304"
        bg01_v001.mkdir(parents=True)

        bg01_v002 = plate_base / "BG01" / "v002" / "exr" / "4312x2304"
        bg01_v002.mkdir(parents=True)

        # Create plate files with proper naming pattern
        # Pattern: {shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.####.exr
        for frame in range(1001, 1025):  # 24 frames
            plate_file_v001 = (
                bg01_v001 / f"shot01_turnover-plate_BG01_aces_v001.{frame:04d}.exr"
            )
            plate_file_v001.write_text(f"# EXR frame {frame} v001")

            plate_file_v002 = (
                bg01_v002 / f"shot01_turnover-plate_BG01_aces_v002.{frame:04d}.exr"
            )
            plate_file_v002.write_text(f"# EXR frame {frame} v002")

        return {
            "project_root": tmp_path / "shows" / "test_project",
            "shot_workspace": str(workspace_path),
            "undist_v001": undist_file_v001,
            "undist_v002": undist_file_v002,
            "plate_v001": bg01_v001 / "shot01_turnover-plate_BG01_aces_v001.%04d.exr",
            "plate_v002": bg01_v002 / "shot01_turnover-plate_BG01_aces_v002.%04d.exr",
            "shot_name": "shot01",
        }

    @pytest.fixture
    def shot_with_undistortion(self, vfx_project_structure):
        """Create a Shot with undistortion files available."""
        shot = Mock(spec=Shot)
        shot.workspace_path = vfx_project_structure["shot_workspace"]
        shot.full_name = vfx_project_structure["shot_name"]
        shot.show = "test_project"
        shot.sequence = "seq01"
        shot.shot = "shot01"
        return shot

    def test_end_to_end_undistortion_workflow(
        self, vfx_project_structure, shot_with_undistortion
    ):
        """Test complete end-to-end undistortion workflow using REAL components."""
        # Setup launcher
        launcher = CommandLauncher()
        launcher.current_shot = shot_with_undistortion

        # Only mock external boundaries (subprocess launching)
        # Use REAL finders and script generator with actual files created by fixture
        with patch("command_launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = None  # Simulate successful terminal launch

            # Execute the complete workflow using REAL components
            success = launcher.launch_app(
                "nuke", include_raw_plate=True, include_undistortion=True
            )

            # Verify workflow execution
            assert success

            # Verify that Popen was called to launch terminal
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            command_str = " ".join(str(arg) for arg in call_args)

            # Verify the command contains expected elements
            assert "ws " in command_str  # Workspace setup command
            assert "nuke" in command_str  # Nuke application
            assert ".nk" in command_str  # Generated script path

            # The real finders should have found the files created by the fixture
            # The real script generator should have created an actual .nk file
            # This is true integration testing with minimal mocking

    def test_undistortion_only_workflow(
        self, vfx_project_structure, shot_with_undistortion
    ):
        """Test workflow with undistortion only (no plates) using REAL components."""
        launcher = CommandLauncher()
        launcher.current_shot = shot_with_undistortion

        # Only mock the plate finder to return None (simulate no plates available)
        # Use REAL undistortion finder and script generator
        with patch.object(RawPlateFinder, "find_latest_raw_plate") as mock_plate_finder:
            with patch("command_launcher.subprocess.Popen") as mock_popen:
                # Setup: no plates available, but undistortion files exist in fixture
                mock_plate_finder.return_value = None  # No plates
                mock_popen.return_value = None  # Simulate successful terminal launch

                success = launcher.launch_app(
                    "nuke", include_raw_plate=True, include_undistortion=True
                )

                assert success

                # Verify terminal launch was called
                mock_popen.assert_called_once()
                call_args = mock_popen.call_args[0][0]
                command_str = " ".join(str(arg) for arg in call_args)

                # Should contain workspace setup, nuke command, and generated script
                assert "ws " in command_str  # Workspace setup
                assert "nuke" in command_str  # Nuke application
                assert ".nk" in command_str  # Generated undistortion-only script

                # Real UndistortionFinder should find the v002 file created by fixture
                # Real NukeScriptGenerator should create undistortion-only script

    def test_plate_only_workflow(self, vfx_project_structure, shot_with_undistortion):
        """Test workflow with plates only (no undistortion) using REAL components."""
        launcher = CommandLauncher()
        launcher.current_shot = shot_with_undistortion

        # Only mock the undistortion finder to return None (simulate no undistortion available)
        # Use REAL plate finder and script generator with actual plate files from fixture
        with patch.object(
            UndistortionFinder, "find_latest_undistortion"
        ) as mock_undist_finder:
            with patch("command_launcher.subprocess.Popen") as mock_popen:
                # Setup: no undistortion available, but plate files exist in fixture
                mock_undist_finder.return_value = None  # No undistortion
                mock_popen.return_value = None  # Simulate successful terminal launch

                success = launcher.launch_app(
                    "nuke", include_raw_plate=True, include_undistortion=True
                )

                assert success

                # Verify terminal launch was called
                mock_popen.assert_called_once()
                call_args = mock_popen.call_args[0][0]
                command_str = " ".join(str(arg) for arg in call_args)

                # Should contain workspace setup, nuke command, and generated script
                assert "ws " in command_str  # Workspace setup
                assert "nuke" in command_str  # Nuke application
                assert ".nk" in command_str  # Generated plate-only script

                # Real RawPlateFinder should find the v002 plates created by fixture
                # Real NukeScriptGenerator should create plate-only script

    def test_workflow_with_corrupted_undistortion_file(
        self, vfx_project_structure, shot_with_undistortion, tmp_path
    ):
        """Test workflow with corrupted undistortion file (realistic failure scenario)."""
        launcher = CommandLauncher()
        launcher.current_shot = shot_with_undistortion

        # Create a corrupted undistortion file to test real error handling
        corrupted_undist_dir = tmp_path / "corrupted_undist"
        corrupted_undist_dir.mkdir(parents=True)
        corrupted_undist_file = corrupted_undist_dir / "corrupted_v001.nk"
        corrupted_undist_file.write_bytes(b"\x00\x01\x02\xff\xfe")  # Binary garbage

        # Mock undistortion finder to return the corrupted file
        with patch.object(
            UndistortionFinder, "find_latest_undistortion"
        ) as mock_undist_finder:
            with patch("command_launcher.subprocess.Popen") as mock_popen:
                # Setup: plates available, corrupted undistortion file
                mock_undist_finder.return_value = corrupted_undist_file
                mock_popen.return_value = None  # Simulate successful terminal launch

                success = launcher.launch_app(
                    "nuke", include_raw_plate=True, include_undistortion=True
                )

                # Should still launch Nuke successfully even with corrupted undistortion
                assert success
                mock_popen.assert_called_once()

                # Command should still be executed (graceful degradation)
                call_args = mock_popen.call_args[0][0]
                command_str = " ".join(str(arg) for arg in call_args)
                assert "ws " in command_str  # Workspace setup
                assert "nuke" in command_str  # Nuke command

                # Real components handle the corrupted file gracefully
                # Real RawPlateFinder should still find valid plates from fixture

    def test_realistic_undistortion_finder_integration(self, vfx_project_structure):
        """Test UndistortionFinder with realistic project structure."""
        shot_workspace = vfx_project_structure["shot_workspace"]
        shot_name = vfx_project_structure["shot_name"]

        # Test finding latest undistortion
        result = UndistortionFinder.find_latest_undistortion(
            shot_workspace, shot_name, "gabriel-h"
        )

        # Should find v002 (latest version)
        assert result is not None
        assert result == vfx_project_structure["undist_v002"]
        assert "v002" in str(result)

    def test_realistic_script_generation_integration(self, vfx_project_structure):
        """Test NukeScriptGenerator with realistic file paths."""
        plate_path = str(vfx_project_structure["plate_v002"])
        undist_path = str(vfx_project_structure["undist_v002"])
        shot_name = vfx_project_structure["shot_name"]

        # Generate integrated script
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, undist_path, shot_name
        )

        assert script_path is not None
        assert Path(script_path).exists()

        # Read and verify realistic script content
        with open(script_path, "r") as f:
            content = f.read()

        # Check for realistic VFX elements
        assert shot_name in content
        assert plate_path in content
        assert undist_path in content
        assert "OCIO_config aces_1.2" in content  # VFX color management
        assert "first_frame 1001" in content  # VFX frame numbering
        assert "last_frame 1024" in content

        # Cleanup
        Path(script_path).unlink()

    def test_version_detection_integration(self, vfx_project_structure):
        """Test version detection across the workflow."""
        undist_path = vfx_project_structure["undist_v002"]

        # Test version extraction
        version = UndistortionFinder.get_version_from_path(undist_path)
        assert version == "v002"

        # Test that the latest version is correctly identified
        shot_workspace = vfx_project_structure["shot_workspace"]
        shot_name = vfx_project_structure["shot_name"]

        result = UndistortionFinder.find_latest_undistortion(
            shot_workspace, shot_name, "gabriel-h"
        )

        assert result is not None
        detected_version = UndistortionFinder.get_version_from_path(result)
        assert detected_version == "v002"  # Should pick the latest

    def test_signal_emission_integration(
        self, vfx_project_structure, shot_with_undistortion
    ):
        """Test that signals are properly emitted during workflow."""
        launcher = CommandLauncher()
        launcher.current_shot = shot_with_undistortion

        # Mock signal to capture emissions
        signal_emissions = []

        def capture_signal(timestamp, message):
            signal_emissions.append((timestamp, message))

        launcher.command_executed.connect(capture_signal)

        with patch.object(
            UndistortionFinder, "find_latest_undistortion"
        ) as mock_undist_finder:
            with patch.object(
                UndistortionFinder, "get_version_from_path"
            ) as mock_version:
                with patch.object(
                    RawPlateFinder, "find_latest_raw_plate"
                ) as mock_plate_finder:
                    with patch.object(
                        RawPlateFinder, "verify_plate_exists"
                    ) as mock_verify:
                        with patch.object(
                            RawPlateFinder, "get_version_from_path"
                        ) as mock_plate_version:
                            with patch.object(
                                NukeScriptGenerator,
                                "create_plate_script_with_undistortion",
                            ) as mock_script_gen:
                                with patch(
                                    "command_launcher.subprocess.Popen"
                                ) as mock_popen:
                                    # Setup realistic return values
                                    mock_undist_finder.return_value = (
                                        vfx_project_structure["undist_v002"]
                                    )
                                    mock_version.return_value = "v002"
                                    mock_plate_finder.return_value = str(
                                        vfx_project_structure["plate_v002"]
                                    )
                                    mock_verify.return_value = True
                                    mock_plate_version.return_value = "v002"
                                    mock_script_gen.return_value = (
                                        "/tmp/integrated_shot01.nk"
                                    )
                                    mock_popen.return_value = (
                                        None  # Simulate successful Popen call
                                    )

                                    success = launcher.launch_app(
                                        "nuke",
                                        include_raw_plate=True,
                                        include_undistortion=True,
                                    )

                                    assert success

                                    # Verify signals were emitted
                                    assert len(signal_emissions) > 0

                                    # Check for version information in signals
                                    version_messages = [
                                        msg
                                        for _, msg in signal_emissions
                                        if "v002" in msg
                                    ]
                                    assert len(version_messages) > 0

    def test_workspace_setup_integration(
        self, vfx_project_structure, shot_with_undistortion
    ):
        """Test that workspace setup is properly included in commands."""
        launcher = CommandLauncher()
        launcher.current_shot = shot_with_undistortion

        with patch.object(UndistortionFinder, "find_latest_undistortion"):
            with patch.object(RawPlateFinder, "find_latest_raw_plate"):
                with patch.object(
                    NukeScriptGenerator, "create_plate_script_with_undistortion"
                ) as mock_script_gen:
                    with patch("command_launcher.subprocess.Popen") as mock_popen:
                        mock_script_gen.return_value = "/tmp/test_script.nk"
                        mock_popen.return_value = None  # Simulate successful Popen call

                        success = launcher.launch_app("nuke", include_undistortion=True)

                        assert success

                        # Verify workspace setup is included in command
                        mock_popen.assert_called_once()
                        call_args = mock_popen.call_args[0][0]

                        # Should include workspace setup
                        command_str = " ".join(str(arg) for arg in call_args)
                        assert shot_with_undistortion.workspace_path in command_str
                        assert "ws " in command_str
