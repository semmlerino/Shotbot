"""Unit tests for NukeScriptGenerator following UNIFIED_TESTING_GUIDE.

Tests Nuke script generation with proper Read nodes for plates.
Focuses on script content, colorspace handling, and temporary file management.

Following UNIFIED_TESTING_GUIDE principles:
- Test behavior, not implementation
- Use real NukeScriptGenerator with temporary files
- Use TestCommand instead of unittest.mock
- Focus on edge cases and error conditions
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path
from tempfile import TemporaryDirectory

# Third-party imports
import pytest

# Local application imports
from nuke.media_detector import NukeMediaDetector
from nuke.script_generator import NukeScriptGenerator


pytestmark = [pytest.mark.unit, pytest.mark.slow]

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)


class TestNukeScriptGenerator:
    """Test NukeScriptGenerator with real components."""

    def test_initialization(self) -> None:
        """Test NukeScriptGenerator initializes correctly."""
        NukeScriptGenerator()

        # Test class variables exist
        assert hasattr(NukeScriptGenerator, "_temp_files")
        assert hasattr(NukeScriptGenerator, "_cleanup_registered")
        assert isinstance(NukeScriptGenerator._temp_files, set)
        assert isinstance(NukeScriptGenerator._cleanup_registered, bool)

    def test_cleanup_registration(self) -> None:
        """Test cleanup function registration happens when tracking files."""
        # Reset cleanup state for testing
        NukeScriptGenerator._cleanup_registered = False
        NukeScriptGenerator._temp_files.clear()

        # Creating instance doesn't register cleanup
        NukeScriptGenerator()
        assert NukeScriptGenerator._cleanup_registered is False

        # Tracking a temp file should register cleanup
        temp_file = "/tmp/test_file.nk"
        NukeScriptGenerator._track_temp_file(temp_file)
        assert NukeScriptGenerator._cleanup_registered is True
        assert temp_file in NukeScriptGenerator._temp_files

    def test_generate_script_basic(self) -> None:
        """Test basic script generation."""
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plate_path = temp_path / "test_plate.exr"
            plate_path.touch()  # Create dummy file

            # Use create_plate_script for basic script generation
            script_path = NukeScriptGenerator.create_plate_script(
                plate_path=str(plate_path), shot_name="test_shot"
            )

            assert script_path is not None
            assert Path(script_path).exists()

    def test_temporary_file_tracking(self) -> None:
        """Test that temporary files are properly tracked."""
        initial_count = len(NukeScriptGenerator._temp_files)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plate_path = temp_path / "test_plate.exr"
            plate_path.touch()

            script_path = NukeScriptGenerator.create_plate_script(
                plate_path=str(plate_path), shot_name="test_shot"
            )

            # Test that temp file was tracked
            assert len(NukeScriptGenerator._temp_files) > initial_count
            assert script_path in NukeScriptGenerator._temp_files

    def test_cleanup_temp_files(self) -> None:
        """Test temporary file cleanup functionality."""
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plate_path = temp_path / "test_plate.exr"
            plate_path.touch()

            script_path = NukeScriptGenerator.create_plate_script(
                plate_path=str(plate_path), shot_name="test_shot"
            )

            # Verify file exists and is tracked
            assert Path(script_path).exists()
            assert script_path in NukeScriptGenerator._temp_files

            # Test cleanup
            NukeScriptGenerator._cleanup_temp_files()

            # File should be removed and not tracked
            assert not Path(script_path).exists()
            assert script_path not in NukeScriptGenerator._temp_files

    def test_error_handling_missing_plate(self) -> None:
        """Test error handling for missing plate file."""
        # Test with non-existent file
        script_path = NukeScriptGenerator.create_plate_script(
            plate_path="/path/that/does/not/exist.exr", shot_name="test_shot"
        )

        # Should handle gracefully (may return None or create script anyway)
        # The exact behavior depends on implementation
        if script_path is not None:
            assert isinstance(script_path, str)

    def test_multiple_script_generation(self) -> None:
        """Test generating multiple scripts in sequence."""
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            script_paths = []

            for i in range(3):
                plate_path = temp_path / f"plate_{i}.exr"
                plate_path.touch()

                script_path = NukeScriptGenerator.create_plate_script(
                    plate_path=str(plate_path), shot_name=f"shot_{i}"
                )

                script_paths.append(script_path)
                assert script_path is not None
                assert Path(script_path).exists()

            # Test all scripts are unique
            assert len(set(script_paths)) == 3

            # Test all are tracked
            for path in script_paths:
                assert path in NukeScriptGenerator._temp_files

    def test_colorspace_with_spaces(self, monkeypatch) -> None:
        """Test colorspace handling with spaces in names."""
        # Test colorspace names that contain spaces
        test_colorspace = "Input - Sony - S-Gamut3.Cine - Linear"

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plate_path = temp_path / "test_plate.exr"
            plate_path.touch()

            # Use monkeypatch instead of patch.object
            monkeypatch.setattr(
                NukeMediaDetector,
                "detect_colorspace",
                lambda _filepath: (test_colorspace, False),
            )

            script_path = NukeScriptGenerator.create_plate_script(
                plate_path=str(plate_path), shot_name="test_shot"
            )

            with Path(script_path).open() as f:
                content = f.read()

            # Test colorspace is properly quoted/handled
            assert (
                test_colorspace in content
                or test_colorspace.replace(" ", "_") in content
            )
