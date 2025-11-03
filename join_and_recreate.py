#!/usr/bin/env python3
"""Helper script to join split VFX structure JSON files and recreate the environment.

This handles the common case where large JSON captures are split for transfer.
"""

# Standard library imports
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast


class VFXStructureData(TypedDict):
    """Type definition for VFX structure JSON data."""

    shows: dict[str, object]  # Show name -> show data mapping


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Join split VFX structure JSONs and recreate environment"
    )
    _ = parser.add_argument("files", nargs="+", help="JSON files to join (in order)")
    _ = parser.add_argument(
        "--output",
        default="vfx_structure_complete.json",
        help="Combined output file (default: vfx_structure_complete.json)",
    )
    _ = parser.add_argument(
        "--recreate",
        action="store_true",
        default=True,
        help="Automatically recreate structure after joining (default: True)",
    )
    _ = parser.add_argument(
        "--no-recreate",
        dest="recreate",
        action="store_false",
        help="Just join files without recreating",
    )
    _ = parser.add_argument(
        "--root",
        default="/tmp/mock_vfx",
        help="Root for recreation (default: /tmp/mock_vfx)",
    )

    args = parser.parse_args()

    # Extract typed variables from argparse namespace (argparse returns Any types)
    files: list[str] = cast("list[str]", args.files)
    output: str = cast("str", args.output)
    recreate: bool = cast("bool", args.recreate)
    root: str = cast("str", args.root)

    print(f"📁 Joining {len(files)} files...")

    # Concatenate files
    with Path(output).open("wb") as outfile:
        for i, fname in enumerate(files, 1):
            print(
                f"   {i}. {fname} ({Path(fname).stat().st_size / 1024 / 1024:.1f} MB)"
            )
            with Path(fname).open("rb") as infile:
                _ = outfile.write(infile.read())

    output_size = Path(output).stat().st_size / 1024 / 1024
    print(f"✅ Created {output} ({output_size:.1f} MB)")

    # Validate JSON
    print("\n🔍 Validating JSON...")
    try:
        with Path(output).open() as f:
            data = cast("VFXStructureData", json.load(f))
        shows = list(data.get("shows", {}).keys())
        print(f"✅ Valid JSON with {len(shows)} shows: {', '.join(shows)}")
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        print("\nThis might mean:")
        print("  1. Files were joined in wrong order")
        print("  2. Files are not consecutive parts of the same JSON")
        print("  3. One of the files is corrupted")
        sys.exit(1)

    # Recreate structure if requested
    if recreate:
        print(f"\n🏗️  Recreating VFX structure at {root}...")
        cmd = [
            sys.executable,
            "recreate_vfx_structure.py",
            output,
            "--root",
            root,
            "--clean",
        ]

        result = subprocess.run(cmd, check=False, capture_output=True, text=True)

        if result.returncode == 0:
            print(result.stdout)
            print(f"\n✨ Success! Mock VFX environment ready at {root}")
            print("\nYou can now run:")
            print("  uv run python shotbot_mock.py")
        else:
            print("❌ Recreation failed:")
            print(result.stderr)
            sys.exit(1)
    else:
        print("\nTo recreate the structure later, run:")
        print(f"  python recreate_vfx_structure.py {output}")


if __name__ == "__main__":
    main()
