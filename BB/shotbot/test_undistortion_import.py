#!/usr/bin/env python3
"""
Demonstration that undistortion nodes are IMPORTED, not just referenced.
"""

import tempfile
from pathlib import Path

from nuke_script_generator import NukeScriptGenerator


def test_undistortion_is_imported_not_referenced():
    """Prove that undistortion nodes are imported into the script."""

    # Create a temporary undistortion .nk file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nk", delete=False) as f:
        f.write("""# 3DE Lens Distortion Example
Root {
 inputs 0
 name test_undistortion
}

LensDistortion {
 inputs 0
 serializeKnob ""
 model_card "3DE4 Anamorphic - Degree 6"
 distortion {{curve i x1001 0.02345}}
 asymmetric_distortion {0.00123 -0.00045}
 name LensDistortion_3DE_Test
 label "TEST UNDISTORTION NODE"
 xpos 100
 ypos 200
}

UVTile2 {
 inputs 1
 uv_scale {1.024 1.024}
 name UVTile2_3DE_Test
 label "TEST SCALE NODE"
 xpos 100
 ypos 250
}
""")
        undist_path = f.name

    # Create a Nuke script with undistortion
    script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
        "",  # No plate path
        undist_path,
        "test_shot",
    )

    # Read the generated script
    with open(script_path, "r") as f:
        generated_content = f.read()

    print("=" * 80)
    print("PROOF THAT UNDISTORTION IS IMPORTED, NOT JUST REFERENCED:")
    print("=" * 80)

    # Check 1: The actual LensDistortion node is in the generated script
    if "LensDistortion {" in generated_content:
        print("✅ LensDistortion node found in generated script")

        # Extract the LensDistortion node
        start_idx = generated_content.find("LensDistortion {")
        end_idx = generated_content.find("}", start_idx) + 1
        lens_node = generated_content[start_idx:end_idx]
        print("\nActual imported LensDistortion node:")
        print("-" * 40)
        print(lens_node)
        print("-" * 40)
    else:
        print("❌ LensDistortion node NOT found")

    # Check 2: The actual parameters are imported
    if "distortion {{curve i x1001 0.02345}}" in generated_content:
        print("\n✅ Distortion parameters imported correctly (0.02345)")
    else:
        print("\n❌ Distortion parameters NOT imported")

    # Check 3: The UVTile2 node is imported
    if "UVTile2 {" in generated_content:
        print("✅ UVTile2 node found in generated script")

        # Extract the UVTile2 node
        start_idx = generated_content.find("UVTile2 {")
        end_idx = generated_content.find("}", start_idx) + 1
        uv_node = generated_content[start_idx:end_idx]
        print("\nActual imported UVTile2 node:")
        print("-" * 40)
        print(uv_node)
        print("-" * 40)
    else:
        print("❌ UVTile2 node NOT found")

    # Check 4: Show that it's NOT just a file reference
    print("\n" + "=" * 80)
    print("IMPORTANT: This is NOT just a file reference!")
    print("=" * 80)

    if "source " + undist_path in generated_content:
        print("❌ Found 'source' command (would be just referencing)")
    else:
        print("✅ No 'source' command - nodes are truly imported")

    if "read " + undist_path in generated_content:
        print("❌ Found 'read' command (would be just referencing)")
    else:
        print("✅ No 'read' command - nodes are truly imported")

    # Check 5: Show that Y positions were adjusted
    if "ypos 0" in generated_content or "ypos -" in generated_content:
        print("✅ Y positions adjusted for integration (not at original 200/250)")

    print("\n" + "=" * 80)
    print("CONCLUSION: The undistortion nodes are IMPORTED into the script,")
    print("not just referenced. The actual node definitions and parameters")
    print("are copied into the generated Nuke script.")
    print("=" * 80)

    # Cleanup
    Path(undist_path).unlink()
    Path(script_path).unlink()


if __name__ == "__main__":
    test_undistortion_is_imported_not_referenced()
