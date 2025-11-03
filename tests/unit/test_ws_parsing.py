#!/usr/bin/env python3
"""Test script to verify ws output parsing with actual VFX data."""

# Standard library imports
import re

# Local application imports
from shot_model import Shot


# Actual ws -sg output from VFX environment
WS_OUTPUT = """workspace /shows/gator/shots/012_DC/012_DC_1000
workspace /shows/gator/shots/012_DC/012_DC_1070
workspace /shows/gator/shots/012_DC/012_DC_1050
workspace /shows/jack_ryan/shots/DB_271/DB_271_1760
workspace /shows/jack_ryan/shots/FF_278/FF_278_4380
workspace /shows/jack_ryan/shots/DA_280/DA_280_0280
workspace /shows/jack_ryan/shots/DC_278/DC_278_0050
workspace /shows/broken_eggs/shots/BRX_166/BRX_166_0010
workspace /shows/broken_eggs/shots/BRX_166/BRX_166_0020
workspace /shows/broken_eggs/shots/BRX_170/BRX_170_0100
workspace /shows/broken_eggs/shots/BRX_070/BRX_070_0010
workspace /shows/jack_ryan/shots/999_xx/999_xx_999"""


def test_parsing() -> None:
    """Test parsing of actual ws output."""
    parse_pattern = re.compile(
        r"workspace\s+(/shows/(\w+)/shots/(\w+)/(\w+_\w+))",
    )

    lines = WS_OUTPUT.strip().split("\n")
    print(f"Parsing {len(lines)} lines of ws output\n")

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

            # Create Shot object
            shot_obj = Shot(
                show=show, sequence=sequence, shot=shot, workspace_path=workspace_path
            )
            print("  Shot object:")
            print(f"    full_name: {shot_obj.full_name}")

            # Test path construction
            thumb_path = shot_obj.thumbnail_dir
            print(f"    thumbnail_dir: {thumb_path}")

            # Check for the issue - should NOT contain /shots/shots/
            path_str = str(thumb_path)
            if "/shots/shots/" in path_str:
                print(f"    ❌ ERROR: Path contains duplicate 'shots': {path_str}")
            elif f"/shots/{sequence}/{shot_dir}/" in path_str:
                print("    ✓ Path correctly constructed")
            else:
                print("    ⚠ WARNING: Path structure may be incorrect")
            print()


if __name__ == "__main__":
    test_parsing()
