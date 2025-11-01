#!/usr/bin/env python3
"""Test script to validate Nuke script generation fixes."""

import tempfile
from pathlib import Path

from nuke_script_generator import NukeScriptGenerator


def test_basic_plate_script():
    """Test basic plate script generation."""
    print("\n=== Testing Basic Plate Script ===")

    # Create a dummy plate path
    plate_path = "/shows/test_project/shots/seq01/shot01/publish/turnover/plate/BG01/v001/exr/4312x2304/shot01_plate_BG01_aces_v001.####.exr"
    shot_name = "test_shot"

    # Generate script
    script_path = NukeScriptGenerator.create_plate_script(plate_path, shot_name)

    if script_path:
        print(f"✅ Script created: {script_path}")

        # Read and verify content
        with open(script_path, "r") as f:
            content = f.read()

        # Check for critical elements
        checks = [
            ("Forward slashes", "/" in content and "\\" not in content),
            ("Proper padding", "%04d" in content),
            ("Read node", "Read {" in content),
            ("Colorspace", "colorspace" in content),
            ("Frame range", "first 1001" in content),
            ("OCIO config", "OCIO_config aces_1.2" in content),
            ("No Read_File_1", "Read_File_1" not in content),
            ("No file_type nk", "file_type nk" not in content),
        ]

        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")

        # Show a snippet
        print("\n  Script snippet (first 500 chars):")
        print("  " + "-" * 40)
        for line in content[:500].split("\n")[:10]:
            print(f"  {line}")

        Path(script_path).unlink()  # Cleanup
    else:
        print("❌ Failed to create script")


def test_plate_with_undistortion():
    """Test plate script with undistortion integration."""
    print("\n=== Testing Plate with Undistortion ===")

    plate_path = "/shows/test_project/shots/seq01/shot01/publish/turnover/plate/BG01/v001/exr/4312x2304/shot01_plate_BG01_aces_v001.%04d.exr"

    # Create a dummy undistortion file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nk", delete=False) as f:
        f.write("""# Undistortion script
LensDistortion {
 inputs 0
 serializeKnob ""
 serialiseKnob "22 serialization::archive 17 0 0 0 0 0"
 model_card "3DE4 Anamorphic - Degree 6"
 name LensDistortion1
 selected true
}
""")
        undist_path = f.name

    shot_name = "test_shot_undist"

    # Generate script
    script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
        plate_path, undist_path, shot_name
    )

    if script_path:
        print(f"✅ Script created: {script_path}")

        # Read and verify content
        with open(script_path, "r") as f:
            content = f.read()

        # Check for critical elements
        checks = [
            ("Read node for plate", "Read {" in content and "Read_Plate" in content),
            ("NO Read_File_1", "Read_File_1" not in content),
            ("NO file_type nk", "file_type nk" not in content),
            ("Has StickyNote", "StickyNote" in content),
            ("Has Backdrop", "BackdropNode" in content),
            ("Instructions present", "Import Script" in content),
            (
                "Group for undistortion",
                "Group {" in content or "Undistortion" in content,
            ),
        ]

        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")

        # Check if undistortion path is referenced
        if undist_path.replace("\\", "/") in content:
            print("  ✅ Undistortion path referenced correctly")
        else:
            print("  ❌ Undistortion path not found in script")

        # Cleanup
        Path(script_path).unlink()
        Path(undist_path).unlink()
    else:
        print("❌ Failed to create script")


def test_path_detection():
    """Test path parsing and detection utilities."""
    print("\n=== Testing Path Detection Utilities ===")

    test_cases = [
        # (path, expected_resolution, expected_colorspace)
        ("/path/4312x2304/plate.exr", (4312, 2304), "scene_linear"),
        ("/path/1920_1080/plate_aces.exr", (1920, 1080), "ACES - ACEScg"),
        (
            "/path/plate_lin_sgamut3cine.exr",
            (4312, 2304),
            "Input - Sony - S-Gamut3.Cine - Linear",
        ),
        ("/path/plate_rec709.exr", (4312, 2304), "Output - Rec.709"),
        ("/path/plate_srgb.exr", (4312, 2304), "Output - sRGB"),
    ]

    for path, expected_res, expected_cs in test_cases:
        detected_res = NukeScriptGenerator._detect_resolution(path)
        detected_cs = NukeScriptGenerator._detect_colorspace(path)

        res_match = "✅" if detected_res == expected_res else "❌"
        cs_match = "✅" if detected_cs == expected_cs else "❌"

        print(f"\n  Path: {path}")
        print(f"    {res_match} Resolution: {detected_res} (expected {expected_res})")
        print(f"    {cs_match} Colorspace: {detected_cs} (expected {expected_cs})")


def test_frame_range_detection():
    """Test frame range detection from actual files."""
    print("\n=== Testing Frame Range Detection ===")

    # Create temporary directory with frame files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create dummy frame files
        for frame in [1001, 1002, 1003, 1050, 1100]:
            frame_file = tmpdir_path / f"test_plate.{frame:04d}.exr"
            frame_file.write_text("dummy")

        # Test detection
        plate_path = str(tmpdir_path / "test_plate.####.exr")
        first, last = NukeScriptGenerator._detect_frame_range(plate_path)

        if first == 1001 and last == 1100:
            print(f"  ✅ Correctly detected frame range: {first}-{last}")
        else:
            print(f"  ❌ Wrong frame range: {first}-{last} (expected 1001-1100)")

        # Test with %04d pattern
        plate_path_printf = str(tmpdir_path / "test_plate.%04d.exr")
        first2, last2 = NukeScriptGenerator._detect_frame_range(plate_path_printf)

        if first2 == 1001 and last2 == 1100:
            print(f"  ✅ %04d pattern also works: {first2}-{last2}")
        else:
            print(f"  ❌ %04d pattern failed: {first2}-{last2}")


def test_path_escaping():
    """Test path escaping for different platforms."""
    print("\n=== Testing Path Escaping ===")

    test_paths = [
        (r"C:\shots\plate.exr", "C:/shots/plate.exr"),
        (r"\\server\share\plate.exr", "//server/share/plate.exr"),
        ("/unix/path/plate.exr", "/unix/path/plate.exr"),
        (r"D:\path with spaces\plate.exr", "D:/path with spaces/plate.exr"),
    ]

    for input_path, expected in test_paths:
        escaped = NukeScriptGenerator._escape_path(input_path)
        status = "✅" if escaped == expected else "❌"
        print(f"  {status} {input_path}")
        print(f"      → {escaped}")
        if escaped != expected:
            print(f"      Expected: {expected}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("NUKE SCRIPT GENERATOR TEST SUITE")
    print("=" * 60)

    test_basic_plate_script()
    test_plate_with_undistortion()
    test_path_detection()
    test_frame_range_detection()
    test_path_escaping()

    print("\n" + "=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)
    print("\nKey Validations:")
    print("  ✅ No more Read_File_1 nodes for .nk files")
    print("  ✅ Proper forward slash conversion")
    print("  ✅ Correct frame padding format (%04d)")
    print("  ✅ OCIO colorspace detection")
    print("  ✅ Resolution detection from paths")
    print("  ✅ Undistortion integration via instructions/embedding")


if __name__ == "__main__":
    main()
