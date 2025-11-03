#!/usr/bin/env python3
"""Standalone test script to verify ws output parsing without PySide6."""

# Standard library imports
import re

# Local application imports
from config import Config


# Get current shows root
SHOWS_ROOT = Config.SHOWS_ROOT

# Actual ws -sg output from VFX environment
WS_OUTPUT = f"""workspace {SHOWS_ROOT}/gator/shots/012_DC/012_DC_1000
workspace {SHOWS_ROOT}/gator/shots/012_DC/012_DC_1070
workspace {SHOWS_ROOT}/gator/shots/012_DC/012_DC_1050
workspace {SHOWS_ROOT}/jack_ryan/shots/DB_271/DB_271_1760
workspace {SHOWS_ROOT}/jack_ryan/shots/FF_278/FF_278_4380
workspace {SHOWS_ROOT}/jack_ryan/shots/DA_280/DA_280_0280
workspace {SHOWS_ROOT}/jack_ryan/shots/DC_278/DC_278_0050
workspace {SHOWS_ROOT}/broken_eggs/shots/BRX_166/BRX_166_0010
workspace {SHOWS_ROOT}/broken_eggs/shots/BRX_166/BRX_166_0020
workspace {SHOWS_ROOT}/broken_eggs/shots/BRX_170/BRX_170_0100
workspace {SHOWS_ROOT}/broken_eggs/shots/BRX_070/BRX_070_0010
workspace {SHOWS_ROOT}/jack_ryan/shots/999_xx/999_xx_999"""


def test_parsing() -> None:
    """Test parsing of actual ws output."""
    parse_pattern = re.compile(
        r"workspace\s+(/shows/(\w+)/shots/(\w+)/(\w+_\w+))",
    )

    lines = WS_OUTPUT.strip().split("\n")
    print(f"Parsing {len(lines)} lines of ws output\n")
    print("=" * 80)

    all_passed = True

    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        match = parse_pattern.search(stripped_line)
        if match:
            workspace_path = match.group(1)
            show = match.group(2)
            sequence = match.group(3)
            shot_dir = match.group(4)

            # Extract shot from shot_dir
            if shot_dir.startswith(f"{sequence}_"):
                shot = shot_dir[len(sequence) + 1 :]
            else:
                shot_parts = shot_dir.rsplit("_", 1)
                shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

            print(f"Line {line_num}: {line}")
            print("  Parsed:")
            print(f"    workspace_path: {workspace_path}")
            print(f"    show: {show}")
            print(f"    sequence: {sequence}")
            print(f"    shot_dir: {shot_dir}")
            print(f"    extracted shot: {shot}")

            # Create full_name
            full_name = f"{sequence}_{shot}"
            print(f"    full_name: {full_name}")

            # Build thumbnail path (manually construct it)
            thumb_path = f"{SHOWS_ROOT}/{show}/shots/{sequence}/{shot_dir}/publish/editorial/cutref/v001/jpg/1920x1080"
            print(f"    thumbnail_dir: {thumb_path}")

            # Check for the issue - should NOT contain /shots/shots/
            if "/shots/shots/" in thumb_path:
                print(f"    ❌ ERROR: Path contains duplicate 'shots': {thumb_path}")
                all_passed = False
            elif f"/shots/{sequence}/{shot_dir}/" in thumb_path:
                print("    ✓ Path correctly constructed")
            else:
                print("    ⚠ WARNING: Path structure may be incorrect")
                all_passed = False

            # Check if shot is parsed correctly (should be numeric, not contain underscores)
            if "_" in shot or shot == sequence:
                print(
                    f"    ❌ ERROR: Shot '{shot}' incorrectly parsed (should be numeric part only)"
                )
                all_passed = False
            else:
                print("    ✓ Shot correctly extracted")

            print()
        else:
            print(f"Line {line_num}: NO MATCH - {line}")
            print()
            all_passed = False

    print("=" * 80)
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    assert all_passed, "Some parsing tests failed - check output above for details"


if __name__ == "__main__":
    try:
        test_parsing()
        print("\n✅ Test script completed successfully")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import sys
        sys.exit(1)
