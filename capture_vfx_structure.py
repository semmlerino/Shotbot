#!/usr/bin/env python3
"""Capture VFX filesystem structure for mock environment recreation.

Run this on the VFX workstation to capture directory structure and filenames.
The output can be used to recreate the structure on a development machine.

Usage:
    # Auto-generates timestamped filename (e.g., vfx_structure_workstation_20240315_143022.json)
    python capture_vfx_structure.py

    # Capture specific shows only
    python capture_vfx_structure.py --shows gator jack_ryan

    # Specify custom output file
    python capture_vfx_structure.py --output my_structure.json

    # Output to stdout (for piping)
    python capture_vfx_structure.py --stdout | gzip > structure.json.gz
"""

# Standard library imports
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC
from pathlib import Path
from typing import TypeAlias

# Third-party imports
from typing_extensions import TypedDict


# Type alias for directory/file node structures
# Using object for the recursive structure to avoid overly complex union types
DirectoryNode: TypeAlias = dict[str, object]


class ShowStructure(TypedDict):
    """Type definition for show structure."""

    root: str
    structure: DirectoryNode  # Complex nested structure from scan_directory


class StructureDict(TypedDict):
    """Type definition for the structure dictionary."""

    capture_time: float
    capture_host: str
    workspace_shots: list[str]
    shows: dict[str, list[ShowStructure]]
    show_roots: list[str]
    patterns: dict[str, list[str]]


def get_workspace_shots() -> tuple[list[str], list[str]]:
    """Get list of shots from ws -sg command."""
    try:
        result = subprocess.run(
            ["/bin/bash", "-i", "-c", "ws -sg"],
            check=False, capture_output=True,
            text=True,
            timeout=10,
        )

        shots: list[str] = []
        shows: set[str] = set()

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith("workspace"):
                    parts = line.split()
                    if len(parts) >= 2:
                        path = parts[1]  # /shows/gator/shots/012_DC/012_DC_1000
                        # Extract show name
                        if "/shows/" in path:
                            show = path.split("/shows/")[1].split("/")[0]
                            shows.add(show)
                        shots.append(path)

        return list(shots), list(shows)
    except Exception as e:
        print(f"Error getting workspace shots: {e}", file=sys.stderr)
        return [], []


def scan_directory(
    path: Path, base_path: Path, max_depth: int = 10, current_depth: int = 0
) -> DirectoryNode | None:
    """Recursively scan directory structure.

    Returns dict with:
    - type: 'dir' or 'file'
    - name: basename
    - path: relative path from base
    - size: file size (for files)
    - children: list of child items (for dirs)
    """
    if current_depth >= max_depth:
        return None

    rel_path = path.relative_to(base_path) if path != base_path else Path()

    if path.is_file():
        try:
            size = path.stat().st_size
        except (OSError, AttributeError):
            size = 0
        return {"type": "file", "name": path.name, "path": str(rel_path), "size": size}

    if path.is_dir():
        children: list[DirectoryNode] = []

        # Key directories we care about
        important_dirs = {
            "publish",
            "editorial",
            "cutref",
            "turnover",
            "plate",
            "user",
            "3de",
            "scenes",
            "scene",
            "exports",
            "jpg",
            "1920x1080",
            "mm",
            "mm-default",
            "shots",
        }

        # File patterns we care about
        important_patterns = {
            ".3de",
            ".jpg",
            ".jpeg",
            ".png",
            ".exr",
            ".nk",
            "thumbnail",
            "poster_frame",
            "frame",
        }

        try:
            # Use os.scandir for efficiency
            with os.scandir(path) as entries:
                for entry in entries:
                    # Skip hidden files/dirs unless important
                    if entry.name.startswith(".") and entry.name not in {".thumbnails"}:
                        continue

                    # Check if this is important
                    is_important = (
                        entry.name.lower() in important_dirs
                        or any(
                            pattern in entry.name.lower()
                            for pattern in important_patterns
                        )
                        or current_depth < 3  # Always include top levels
                    )

                    if is_important or current_depth < 5:
                        child_path = Path(entry.path)
                        child_data = scan_directory(
                            child_path, base_path, max_depth, current_depth + 1
                        )
                        if child_data:
                            children.append(child_data)

                    # Limit children to prevent huge outputs
                    if len(children) > 1000:
                        children.append(
                            {
                                "type": "truncated",
                                "name": "...more files...",
                                "count": len(list(entries)),
                            }
                        )
                        break

        except PermissionError:
            pass
        except Exception as e:
            print(f"Error scanning {path}: {e}", file=sys.stderr)

        return {
            "type": "dir",
            "name": path.name,
            "path": str(rel_path),
            "children": children,
        }


def capture_structure(shows: list[str] | None = None) -> StructureDict:
    """Capture the VFX filesystem structure."""

    print("Capturing VFX filesystem structure...", file=sys.stderr)

    # Get workspace shots
    workspace_shots, workspace_shows = get_workspace_shots()
    print(
        f"Found {len(workspace_shots)} workspace shots from shows: {', '.join(workspace_shows)}",
        file=sys.stderr,
    )

    # Determine which shows to capture
    if shows:
        target_shows = shows
    else:
        target_shows = (
            workspace_shows
            if workspace_shows
            else ["gator", "jack_ryan", "broken_eggs"]
        )

    print(f"Capturing structure for shows: {', '.join(target_shows)}", file=sys.stderr)

    structure: StructureDict = {
        "capture_time": time.time(),
        "capture_host": os.uname().nodename,
        "workspace_shots": workspace_shots,
        "shows": {},
        "show_roots": [],
        "patterns": {},
    }

    # Common show root directories
    possible_roots = ["/shows", "/mnt/shows", "/mnt/projects"]

    for root_path in possible_roots:
        root = Path(root_path)
        if root.exists():
            structure["show_roots"].append(root_path)

            for show in target_shows:
                show_path = root / show
                if show_path.exists():
                    print(f"Scanning {show_path}...", file=sys.stderr)

                    # Capture structure with depth limit
                    show_structure = scan_directory(show_path, root)

                    if show_structure:
                        if show not in structure["shows"]:
                            structure["shows"][show] = []
                        structure["shows"][show].append(
                            {"root": root_path, "structure": show_structure}
                        )

    # Add some sample file patterns we've seen
    structure["patterns"] = {
        "thumbnail_paths": [
            "publish/editorial/cutref/v001/jpg/1920x1080/*.jpg",
            ".thumbnails/thumbnail.jpg",
            ".thumbnails/poster_frame.jpg",
        ],
        "3de_paths": ["user/*/mm/3de/mm-default/scenes/scene/*/*.3de"],
        "plate_paths": ["publish/turnover/plate/input_plate/*/*/*.exr"],
    }

    return structure


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture VFX filesystem structure for mock environment"
    )
    parser.add_argument(
        "--shows",
        nargs="+",
        help="Specific shows to capture (default: use ws -sg shows)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file (default: auto-generated with timestamp)",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="Output to stdout instead of file"
    )

    args = parser.parse_args()

    # Extract typed arguments from argparse Namespace
    shows: list[str] | None = getattr(args, "shows", None)
    stdout_flag: bool = getattr(args, "stdout", False)
    output_file_arg: str | None = getattr(args, "output", None)

    # Capture structure
    structure = capture_structure(shows)

    # Output as JSON
    output = json.dumps(structure, indent=2, sort_keys=True)

    # Determine output destination
    if stdout_flag:
        # Explicitly requested stdout
        print(output)
        print(
            f"\nCapture complete! Found {len(structure['shows'])} shows",
            file=sys.stderr,
        )
    else:
        # Default: auto-generate filename or use provided one
        if output_file_arg:
            output_file = output_file_arg
        else:
            # Auto-generate filename with timestamp and hostname
            # Standard library imports
            from datetime import datetime

            timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
            hostname = os.uname().nodename.split(".")[0]  # First part of hostname
            output_file = f"vfx_structure_{hostname}_{timestamp}.json"

        # Save to file
        with Path(output_file).open("w") as f:
            f.write(output)

        print(f"✅ Structure saved to: {output_file}")
        print(f"\nCapture complete! Found {len(structure['shows'])} shows")

    # Summary statistics
    total_dirs = 0
    total_files = 0

    def count_items(node: DirectoryNode) -> None:
        nonlocal total_dirs, total_files
        if node["type"] == "dir":
            total_dirs += 1
            children = node.get("children", [])
            # children is list[DirectoryNode] but typed as object due to DirectoryNode definition
            # Cast to list for iteration
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        count_items(child)
        elif node["type"] == "file":
            total_files += 1

    for show_data in structure["shows"].values():
        for root_data in show_data:
            count_items(root_data["structure"])

    print(f"Captured {total_dirs} directories and {total_files} files", file=sys.stderr)


if __name__ == "__main__":
    main()
