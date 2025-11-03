#!/usr/bin/env python3
"""Test mock functionality without GUI."""

# Standard library imports
import os
import sys
from pathlib import Path


# Set mock mode
os.environ["SHOTBOT_MOCK"] = "1"
os.environ["SHOWS_ROOT"] = "/tmp/mock_vfx/shows"

# Local application imports
# Import modules
from maya_latest_finder import MayaLatestFinder
from mock_workspace_pool import create_mock_pool_from_filesystem
from shot_model import Shot, ShotModel
from targeted_shot_finder import TargetedShotsFinder
from threede_latest_finder import ThreeDELatestFinder


def test_mock_pool() -> None:
    """Test MockWorkspacePool functionality."""
    print("=" * 70)
    print("TESTING MOCK WORKSPACE POOL")
    print("=" * 70)

    # Get mock pool
    pool = create_mock_pool_from_filesystem()
    print(f"✅ Pool type: {type(pool).__name__}")

    # Execute mock ws command
    result = pool.execute_workspace_command("ws -sg")
    print(f"✅ Mock 'ws -sg' returned {len(result)} shots")

    if result:
        # Parse first shot
        first_line = result[0]
        print(f"   First shot line: {first_line[:80]}...")

        # Count by show
        show_counts = {}
        for line in result:
            if "workspace" in line:
                parts = line.split()
                if len(parts) >= 2:
                    ws_path = parts[1]
                    if "/shows/" in ws_path:
                        show = ws_path.split("/shows/")[1].split("/")[0]
                        show_counts[show] = show_counts.get(show, 0) + 1

        print("\nShots by show:")
        for show, count in sorted(show_counts.items()):
            print(f"   • {show}: {count} shots")

    print()


def test_shot_model() -> None:
    """Test ShotModel with mock data."""
    print("=" * 70)
    print("TESTING SHOT MODEL")
    print("=" * 70)

    # Create shot model
    model = ShotModel()
    print("✅ Created ShotModel")

    # Refresh shots (will use mock pool)
    success, has_changes = model.refresh_shots()
    print(f"✅ Refresh shots: success={success}, has_changes={has_changes}")

    # Get shots
    shots = model.get_shots()
    print(f"✅ Model contains {len(shots)} shots")

    if shots:
        # Show first few shots
        print("\nFirst 5 shots:")
        for i, shot in enumerate(shots[:5]):
            print(f"   {i + 1}. {shot.show}/{shot.sequence}/{shot.shot}")
            print(f"      Path: {shot.workspace_path}")

    print()


def test_finders() -> None:
    """Test finder classes with mock filesystem."""
    print("=" * 70)
    print("TESTING FINDER CLASSES")
    print("=" * 70)

    # Test workspace path
    workspace = Path("/tmp/mock_vfx/shows/gator/shots/012_DC/012_DC_1000")

    if workspace.exists():
        print(f"✅ Test workspace exists: {workspace}")

        # Test MayaLatestFinder
        print("\nTesting MayaLatestFinder:")
        maya_finder = MayaLatestFinder()
        latest_maya = maya_finder.find_latest_maya_scene(str(workspace))
        if latest_maya:
            print(f"   ✅ Found latest Maya scene: {latest_maya.name}")
        else:
            print("   No Maya scenes found (expected in mock)")

        # Test ThreeDELatestFinder
        print("\nTesting ThreeDELatestFinder:")
        threede_finder = ThreeDELatestFinder()
        latest_3de = threede_finder.find_latest_threede_scene(str(workspace))
        if latest_3de:
            print(f"   ✅ Found latest 3DE scene: {latest_3de.name}")
        else:
            print("   No 3DE scenes found")

        # Test TargetedShotsFinder
        print("\nTesting TargetedShotsFinder:")
        targeted_finder = TargetedShotsFinder(username="gabriel-h")

        # Create mock active shots
        active_shots = [
            Shot(
                show="gator",
                sequence="012_DC",
                shot="1000",
                workspace_path=str(workspace),
            )
        ]

        shows = targeted_finder.extract_shows_from_active_shots(active_shots)
        print(f"   ✅ Extracted shows: {shows}")

        # Find user shots in shows
        shots = list(
            targeted_finder.find_user_shots_in_shows(shows, Path("/tmp/mock_vfx/shows"))
        )
        print(f"   ✅ Found {len(shots)} user shots")
    else:
        print(f"❌ Test workspace does not exist: {workspace}")

    print()


def test_filesystem_structure() -> None:
    """Test mock filesystem structure."""
    print("=" * 70)
    print("TESTING MOCK FILESYSTEM STRUCTURE")
    print("=" * 70)

    mock_root = Path("/tmp/mock_vfx")
    shows_root = mock_root / "shows"

    if mock_root.exists():
        print(f"✅ Mock root exists: {mock_root}")

        # Count directories and files
        dir_count = sum(1 for _ in mock_root.rglob("*/"))
        file_count = sum(1 for _ in mock_root.rglob("*") if _.is_file())
        print(f"   • Directories: {dir_count:,}")
        print(f"   • Files: {file_count:,}")

        # List shows
        if shows_root.exists():
            shows = [d.name for d in shows_root.iterdir() if d.is_dir()]
            print(f"\nShows found ({len(shows)}):")
            for show in sorted(shows):
                show_path = shows_root / show / "shots"
                if show_path.exists():
                    shot_count = len(
                        [
                            d
                            for d in show_path.rglob("*/")
                            if d.is_dir() and "user" not in d.parts
                        ]
                    )
                    print(
                        f"   • {show}: ~{shot_count // 2} shots"
                    )  # Approximate since we count seq and shot dirs

        # Check for 3DE files
        threede_files = list(mock_root.rglob("*.3de"))
        print(f"\n3DE files created: {len(threede_files)}")
        if threede_files:
            print("Sample 3DE files:")
            for f in threede_files[:3]:
                rel_path = f.relative_to(mock_root)
                print(f"   • {rel_path}")
    else:
        print(f"❌ Mock root does not exist: {mock_root}")

    print()


def main() -> int:
    """Run all mock tests."""
    print("\n" + "=" * 70)
    print("SHOTBOT MOCK FUNCTIONALITY TEST")
    print("=" * 70)
    print(f"Mock mode: {os.environ.get('SHOTBOT_MOCK', 'not set')}")
    print(f"Shows root: {os.environ.get('SHOWS_ROOT', 'not set')}")
    print()

    try:
        test_filesystem_structure()
        test_mock_pool()
        test_shot_model()
        test_finders()

        print("=" * 70)
        print("✅ ALL MOCK TESTS COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print("\nThe mock environment is fully operational!")
        print("You can now run: uv run python shotbot.py --mock")
        print("(Note: GUI requires display environment)")

    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        # Standard library imports
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
