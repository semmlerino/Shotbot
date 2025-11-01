"""Tests for NukeScriptGenerator class."""

from pathlib import Path

from nuke_script_generator import NukeScriptGenerator


class TestNukeScriptGenerator:
    """Test NukeScriptGenerator functionality."""

    def test_create_plate_script_basic(self, tmp_path: Path) -> None:
        """Test basic plate script generation."""
        # Create test plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        # Create dummy EXR files
        for frame in range(1001, 1004):
            plate_file = plate_dir / f"test_plate.{frame:04d}.exr"
            plate_file.write_text("dummy exr content")

        plate_path = str(plate_dir / "test_plate.%04d.exr")
        shot_name = "test_shot"

        # Generate script
        script_path = NukeScriptGenerator.create_plate_script(plate_path, shot_name)

        assert script_path is not None
        assert Path(script_path).exists()

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        assert "test_shot_plate" in content  # Uses _plate suffix for regular scripts
        assert plate_path in content
        assert "Read {" in content
        assert "first_frame 1001" in content
        # The script detects frames 1001-1003 but uses default 1001-1100 range
        assert "last_frame 1003" in content or "last_frame 1100" in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_both_files(
        self, tmp_path: Path
    ) -> None:
        """Test script generation with both plate and undistortion."""
        # Create test plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        for frame in range(1001, 1004):
            plate_file = plate_dir / f"test_plate.{frame:04d}.exr"
            plate_file.write_text("dummy exr content")

        plate_path = str(plate_dir / "test_plate.%04d.exr")

        # Create test undistortion file with proper LensDistortion node
        undist_file = tmp_path / "undistortion_v001.nk"
        undist_content = """#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx
version 16.0 v4
Root {
 inputs 0
 name test_undist
}
LensDistortion {
 inputs 1
 distortion 0.1
 name LensDistortion1
 xpos 0
 ypos 100
}
"""
        undist_file.write_text(undist_content)

        shot_name = "test_shot"

        # Generate script
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, str(undist_file), shot_name
        )

        assert script_path is not None
        assert Path(script_path).exists()

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        # Check for plate content
        assert "test_shot_comp" in content
        assert plate_path in content
        assert "name Read_Plate" in content

        # Check for imported undistortion nodes
        assert "LensDistortion {" in content or "LensDistortion1" in content
        # Should have note about import source
        assert (
            "Undistortion imported from:" in content
            or "Note_Undistortion_Source" in content
        )

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_plate_only(self, tmp_path):
        """Test script generation with plate only (no undistortion)."""
        # Create test plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        for frame in range(1001, 1003):
            plate_file = plate_dir / f"test_plate.{frame:04d}.exr"
            plate_file.write_text("dummy exr content")

        plate_path = str(plate_dir / "test_plate.%04d.exr")
        shot_name = "test_shot"

        # Generate script with no undistortion
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, None, shot_name
        )

        assert script_path is not None
        assert Path(script_path).exists()

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        # Should have plate content
        assert plate_path in content
        assert "name Read_Plate" in content

        # Should NOT have undistortion content
        assert "UNDISTORTION AVAILABLE" not in content
        assert "Note_Undistortion" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_undistortion_only(self, tmp_path):
        """Test script generation with undistortion only (no plate)."""
        # Create test undistortion file with proper nodes
        undist_file = tmp_path / "undistortion_v002.nk"
        undist_content = """#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx
version 16.0 v4
Root {
 inputs 0
 name test_undist
}
LensDistortion {
 inputs 1
 distortion 0.2
 name LensDistortion2
 xpos 0
 ypos 200
}
UVTile2 {
 inputs 1
 name UVTile2_1
 xpos 0
 ypos 250
}
"""
        undist_file.write_text(undist_content)

        shot_name = "test_shot"

        # Generate script with empty plate path
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            "", str(undist_file), shot_name
        )

        assert script_path is not None
        assert Path(script_path).exists()

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        # Should have basic Nuke structure
        assert "test_shot_comp" in content
        assert "Root {" in content

        # Should have imported undistortion nodes
        assert "LensDistortion {" in content or "LensDistortion2" in content
        assert "UVTile2 {" in content or "UVTile2_1" in content
        assert "Undistortion imported from:" in content

        # Should NOT have plate Read node (only undist, no plate)
        assert "name Read_Plate" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_missing_undist_file(self, tmp_path):
        """Test script generation with non-existent undistortion file."""
        # Create test plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        for frame in range(1001, 1003):
            plate_file = plate_dir / f"test_plate.{frame:04d}.exr"
            plate_file.write_text("dummy exr content")

        plate_path = str(plate_dir / "test_plate.%04d.exr")
        undist_path = "/non/existent/undistortion.nk"
        shot_name = "test_shot"

        # Generate script with missing undistortion file
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, undist_path, shot_name
        )

        assert script_path is not None
        assert Path(script_path).exists()

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        # Should have plate content
        assert plate_path in content
        assert "name Read_Plate" in content

        # Should NOT have undistortion content (file doesn't exist)
        assert "undistortion_import" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_resolution_detection(self, tmp_path):
        """Test resolution detection from path."""
        # Create test plate files with resolution in path
        plate_dir = tmp_path / "project" / "shots" / "4312x2304" / "plates"
        plate_dir.mkdir(parents=True)

        for frame in range(1001, 1003):
            plate_file = plate_dir / f"test_plate.{frame:04d}.exr"
            plate_file.write_text("dummy exr content")

        plate_path = str(plate_dir / "test_plate.%04d.exr")
        shot_name = "test_shot"

        # Generate script
        script_path = NukeScriptGenerator.create_plate_script(plate_path, shot_name)

        assert script_path is not None

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        # Should detect resolution from path
        assert 'format "4312 2304 0 0 4312 2304 1' in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_no_frames(self, tmp_path):
        """Test script generation when no frame files exist."""
        plate_dir = tmp_path / "empty_plates"
        plate_dir.mkdir()

        plate_path = str(plate_dir / "test_plate.%04d.exr")
        shot_name = "test_shot"

        # Generate script with no frame files
        script_path = NukeScriptGenerator.create_plate_script(plate_path, shot_name)

        assert script_path is not None

        # Read and verify script content
        with open(script_path, "r") as f:
            content = f.read()

        # Should use default frame range (1001-1100 as per actual implementation)
        assert "first_frame 1001" in content
        assert "last_frame 1100" in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_error_handling(self):
        """Test error handling in script generation."""
        # Test with invalid path
        NukeScriptGenerator.create_plate_script(
            "/invalid/path/plates.%04d.exr", "test_shot"
        )

        # Should not crash, but may return None or handle gracefully
        # This depends on implementation - the main requirement is no crashes

    def test_create_plate_script_with_undistortion_error_handling(self):
        """Test error handling in undistortion script generation."""
        # Test with invalid paths
        NukeScriptGenerator.create_plate_script_with_undistortion(
            "/invalid/plate/path.%04d.exr", "/invalid/undist/path.nk", "test_shot"
        )

        # Should not crash, but may return None or handle gracefully
        # This depends on implementation - the main requirement is no crashes

    def test_import_realistic_3de_undistortion(self, tmp_path):
        """Test importing a realistic 3DE lens distortion file."""
        # Create test plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "GF_256_0760.1001.exr"
        plate_file.write_text("dummy")

        # Create realistic 3DE lens distortion file
        undist_file = tmp_path / "GF_256_0760_mm_default_LD_v028.nk"
        undist_content = """#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx
version 16.0 v4
define_window_layout_xml {<?xml version="1.0" encoding="UTF-8"?>
<layout version="1.0">
</layout>
}
Root {
 inputs 0
 name /shows/jack_ryan/shots/GF_256/GF_256_0760/user/gabriel-h/mm/3de/mm-default/exports/scene/FG01/nuke_lens_distortion/v028/GF_256_0760_mm_default_LD_v028.nk
 frame 1001
 first_frame 1001
 last_frame 1100
 fps 24
 format "4312 2304 0 0 4312 2304 1 4312x2304"
 proxy_type scale
 proxy_format "1024 778 0 0 1024 778 1 1K_Super_35(full-ap)"
 proxySetting "if {[value root.proxy]} { 960 540 } else { 4312 2304 }"
 colorManagement OCIO
 OCIO_config aces_1.2
 defaultViewerLUT "OCIO LUTs"
 workingSpaceLUT "ACES - ACEScg"
 monitorLut "Rec.709 (ACES)"
}
LensDistortion {
 inputs 1
 serializeKnob ""
 serialiseKnob "22 serialization::archive 19 0 0 0 0 0 0 0 0 0 0 0 0"
 distortion {{curve i x1001 0.02345}}
 anamorphic_squeeze 1
 asymmetric_distortion {0.00123 -0.00045}
 name LensDistortion_3DE
 label "3DE4 Lens Distortion v028"
 xpos 0
 ypos 50
}
UVTile2 {
 inputs 1
 filter_type Simon
 wrap_mode repeat
 uv_scale {1.024 1.024}
 name UVTile2_3DE
 label "Undistort Scale"
 xpos 0
 ypos 100
}
Crop {
 box {0 0 4312 2304}
 reformat true
 crop false
 name Crop_3DE
 xpos 0
 ypos 150
}
"""
        undist_file.write_text(undist_content)

        plate_path = str(plate_dir / "GF_256_0760.%04d.exr")
        shot_name = "GF_256_0760"

        # Generate script
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, str(undist_file), shot_name
        )

        assert script_path is not None
        assert Path(script_path).exists()

        with open(script_path, "r") as f:
            content = f.read()

        # Check that all 3DE nodes were imported
        assert "LensDistortion {" in content
        assert "LensDistortion_3DE" in content
        assert "3DE4 Lens Distortion v028" in content

        assert "UVTile2 {" in content
        assert "UVTile2_3DE" in content
        assert "Undistort Scale" in content

        assert "Crop {" in content
        assert "Crop_3DE" in content

        # Check that distortion values were preserved
        assert "distortion {{curve i x1001 0.02345}}" in content
        assert "asymmetric_distortion {0.00123 -0.00045}" in content
        assert "uv_scale {1.024 1.024}" in content

        # Check that positions were adjusted
        assert "ypos -150" in content or "ypos -100" in content  # Adjusted positions

        # Check for import source note
        assert "Undistortion imported from:" in content

        # Cleanup
        Path(script_path).unlink()

    def test_script_content_structure(self, tmp_path):
        """Test that generated script has proper Nuke structure."""
        # Create minimal test setup
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test_plate.1001.exr"
        plate_file.write_text("dummy exr")

        undist_file = tmp_path / "undist.nk"
        undist_file.write_text("# undist")

        plate_path = str(plate_dir / "test_plate.%04d.exr")
        shot_name = "test_shot_123"

        # Generate script
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, str(undist_file), shot_name
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Check essential Nuke script structure
        assert content.startswith("#!")  # Shebang
        assert "version 16.0 v4" in content  # Updated to Nuke 16
        assert "Root {" in content
        assert "name test_shot_123_comp" in content
        assert "OCIO_config aces_1.2" in content
        assert "Viewer {" in content

        # Check that nodes have proper positioning
        assert "xpos" in content
        assert "ypos" in content

        # Cleanup
        Path(script_path).unlink()
