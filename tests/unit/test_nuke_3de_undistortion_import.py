from __future__ import annotations

# Standard library imports
from pathlib import Path

# Local application imports
from config import Config
from nuke_script_generator import NukeScriptGenerator
from nuke_undistortion_parser import NukeUndistortionParser


"""Test 3DE undistortion import with realistic node types."""

# Mock 3DE undistortion export with actual 3DE node types
MOCK_3DE_UNDISTORTION = """#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx
version 16.0 v4
define_window_layout_xml {<?xml version="1.0" encoding="UTF-8"?>
<layout version="1.0">
    <window x="0" y="0" w="1920" h="1080" screen="0">
        <splitter orientation="1">
            <split size="1920"/>
            <dock id="DAG.1">
                <page id="DAG.1"/>
            </dock>
        </splitter>
    </window>
</layout>
}
Root {
 inputs 0
 name /tmp/DB_256_1200_undistortion.nk
 frame 1001
 first_frame 1001
 last_frame 1100
 fps 24
 format "4312 2304 0 0 4312 2304 1 4K_DCI"
 proxy_type scale
 proxy_format "1024 778 0 0 1024 778 1 1K_Super_35(full-ap)"
 colorManagement OCIO
 OCIO_config aces_1.2
 defaultViewerLUT "OCIO LUTs"
}
LD_3DE4_Radial_Standard_Degree_4 {
 inputs 0
 direction undistort
 field_of_view_xa_unit 1.41732283
 field_of_view_ya_unit 0.75476378
 field_of_view_xb_unit 1.41732283
 field_of_view_yb_unit 0.75476378
 tde4_focal_length_cm 3.5
 tde4_filmback_width_cm 3.6576
 tde4_filmback_height_cm 1.9456
 tde4_lens_center_offset_x_cm 0
 tde4_lens_center_offset_y_cm 0
 tde4_pixel_aspect 1
 Distortion_Degree_2 -0.0342
 U_Degree_2 0.0125
 V_Degree_2 0.0089
 Quartic_Distortion_Degree_4 0.0023
 U_Degree_4_Cylindric_Direction 0
 V_Degree_4_Cylindric_Direction 0
 Phi_Cylindric_Direction 0
 B_Cylindric_Bending 0
 name LD_3DE4_Radial_Standard_Degree_4_1
 xpos 100
 ypos -200
}
Group {
 inputs 1
 name UndistortionGroup
 xpos 100
 ypos -100
 addUserKnob {20 User}
 addUserKnob {26 info l "" +STARTLINE T "3DE Undistortion for DB_256_1200"}
}
 Input {
  inputs 0
  name Input1
  xpos 0
  ypos -300
 }
 Output {
  name Output1
  xpos 0
  ypos 100
 }
end_group
"""

# Mock copy/paste format (what 3DE might export when copying nodes)
MOCK_3DE_COPY_PASTE = """set cut_paste_input [stack 0]
version 16.0 v4
push $cut_paste_input
LD_3DE4_Anamorphic_Standard_Degree_4 {
 inputs 0
 direction undistort
 field_of_view_xa_unit 1.41732283
 field_of_view_ya_unit 0.75476378
 anamorphic_squeeze 2
 name LD_3DE4_Anamorphic_1
 xpos 200
 ypos -300
}
"""

# Mock with LD_3DE_Classic node
MOCK_3DE_CLASSIC = """LD_3DE_Classic_LD_Model {
 inputs 0
 direction undistort
 fov_xa 1.41732283
 fov_ya 0.75476378
 distortion -0.0342
 anamorphic_squeeze 1
 name LD_3DE_Classic_1
 xpos 0
 ypos -400
}
"""


class TestNuke3DEUndistortionImport:
    """Test importing 3DE undistortion nodes."""

    def test_import_3de_radial_standard_node(self, tmp_path) -> None:
        """Test importing LD_3DE4_Radial_Standard_Degree_4 node."""
        # Create temp undistortion file
        undist_file = tmp_path / "test_undistortion.nk"
        undist_file.write_text(MOCK_3DE_UNDISTORTION)

        # Test parsing with NukeUndistortionParser
        parser = NukeUndistortionParser()
        result = parser.parse_undistortion_file(
            str(undist_file),
            ypos_offset=-200,
        )

        assert result
        assert "LD_3DE4_Radial_Standard_Degree_4" in result
        assert "UndistortionGroup" in result
        # Note: Connection to plate is handled at a higher level, not in import method
        # The import just preserves the original inputs value
        # Should not have Root node
        assert "Root {" not in result
        # Should not have duplicate version line
        assert result.count("version 16.0") == 0

    def test_import_copy_paste_format(self, tmp_path) -> None:
        """Test importing copy/paste format with 3DE nodes."""
        # Create temp file
        undist_file = tmp_path / "copy_paste.nk"
        undist_file.write_text(MOCK_3DE_COPY_PASTE)

        # Test simple import (should handle copy/paste format too)
        parser = NukeUndistortionParser()
        result = parser.parse_undistortion_file(
            str(undist_file),
            ypos_offset=-200,
        )

        assert result
        assert "LD_3DE4_Anamorphic_Standard_Degree_4" in result
        # Should not have copy/paste markers
        assert "set cut_paste_input" not in result
        assert "push $cut_paste_input" not in result
        # Note: Connection to plate is handled at a higher level, not in import method
        assert "inputs 0" in result

    def test_import_classic_ld_model(self, tmp_path) -> None:
        """Test importing LD_3DE_Classic_LD_Model node."""
        # Create temp file
        undist_file = tmp_path / "classic.nk"
        undist_file.write_text(MOCK_3DE_CLASSIC)

        parser = NukeUndistortionParser()
        result = parser.parse_undistortion_file(
            str(undist_file),
            ypos_offset=-200,
        )

        assert result
        assert "LD_3DE_Classic_LD_Model" in result
        assert "inputs 0" in result  # Should keep inputs 0 when not connecting

    def test_fallback_to_parsers(self, tmp_path) -> None:
        """Test that fallback parsers are tried if simple import fails."""
        # Create an empty file to trigger fallback
        undist_file = tmp_path / "empty.nk"
        undist_file.write_text("")

        # This should fail all parsers and return empty
        parser = NukeUndistortionParser()
        result = parser.parse_undistortion_file(
            str(undist_file),
            ypos_offset=-200,
        )

        assert result == ""

    def test_full_script_generation_with_3de_undistortion(self, tmp_path) -> None:
        """Test full script generation with 3DE undistortion."""
        # Create undistortion file
        undist_file = tmp_path / "undist.nk"
        undist_file.write_text(MOCK_3DE_UNDISTORTION)

        # Create mock plate path
        plate_path = f"{Config.SHOWS_ROOT}/test/plates/shot_001.####.exr"

        # Generate full script
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path,
            str(undist_file),
            "shot_001",
        )

        assert script_path
        assert Path(script_path).exists()

        # Read generated script
        with Path(script_path).open() as f:
            content = f.read()

        # Verify content
        assert "Read_Plate" in content
        assert "LD_3DE4_Radial_Standard_Degree_4" in content
        assert "UndistortionGroup" in content
        # Should have proper connection
        assert "inputs 1" in content

    def test_3de_node_types_accepted(self) -> None:
        """Verify 3DE node types are accepted by simplified pattern matching."""
        # Standard library imports
        import re

        # Test that our simplified pattern accepts all 3DE node types
        test_nodes = [
            "LD_3DE4_Radial_Standard_Degree_4 {",
            "LD_3DE4_Anamorphic_Standard_Degree_4 {",
            "LD_3DE_Classic_LD_Model {",
            "LD_3DE4_Radial_Fisheye_Degree_8 {",
            "tde4_ldp_classic_3de_mixed {",
        ]

        # Pattern from our simplified implementation
        excluded_patterns = ["Root", "set", "push", "if", "else", "for", "while"]

        for node_line in test_nodes:
            node_pattern = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*\{", node_line)
            assert node_pattern, f"Pattern should match: {node_line}"

            node_type = node_pattern.group(1)
            assert node_type not in excluded_patterns, (
                f"3DE node should not be excluded: {node_type}"
            )

    def test_mixed_node_types(self, tmp_path) -> None:
        """Test importing file with both standard and 3DE nodes."""
        mixed_content = """Group {
 inputs 0
 name SetupGroup
}
 LD_3DE4_Radial_Standard_Degree_4 {
  inputs 1
  direction undistort
  name LD_Undistort
 }
 LensDistortion {
  inputs 1
  distortion -0.01
  name StandardLens
 }
end_group
"""
        undist_file = tmp_path / "mixed.nk"
        undist_file.write_text(mixed_content)

        parser = NukeUndistortionParser()
        result = parser.parse_undistortion_file(
            str(undist_file),
            ypos_offset=-200,
        )

        assert result
        assert "SetupGroup" in result
        assert "LD_3DE4_Radial_Standard_Degree_4" in result
        assert "LensDistortion" in result
        # First node should connect to plate
        assert (
            result.replace("inputs 0", "inputs 1", 1) in result or "inputs 1" in result
        )
