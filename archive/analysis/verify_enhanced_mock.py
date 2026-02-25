#!/usr/bin/env python3
"""Verify enhanced mock environment has 3DE files for both tabs.
"""

# Standard library imports
import sys
from pathlib import Path


def verify_mock_environment(shows_root: str | Path) -> bool:
    """Verify the enhanced mock environment has both gabriel-h and other user 3DE files."""
    shows_path = Path(shows_root)

    print(f"🔍 Verifying enhanced mock environment at: {shows_path}")

    if not shows_path.exists():
        print(f"❌ Shows root does not exist: {shows_path}")
        return False

    # Find all 3DE files
    all_3de_files = list(shows_path.rglob("*.3de"))
    gabrielh_3de_files = [f for f in all_3de_files if "/user/gabriel-h/" in str(f)]
    other_users_3de_files = [
        f for f in all_3de_files if "/user/gabriel-h/" not in str(f)
    ]

    print("\n📊 3DE File Statistics:")
    print(f"   Total 3DE files: {len(all_3de_files)}")
    print(f"   Gabriel-h files (My Shots): {len(gabrielh_3de_files)}")
    print(f"   Other users files (Other 3DE Scenes): {len(other_users_3de_files)}")

    # Show sample files
    if gabrielh_3de_files:
        print("\n✅ My Shots tab will be populated:")
        for f in gabrielh_3de_files[:3]:
            # Extract shot info
            parts = f.parts
            if "shots" in parts:
                shots_idx = parts.index("shots")
                if shots_idx + 2 < len(parts):
                    shot = parts[shots_idx + 2]
                    print(f"   - {shot}")
        if len(gabrielh_3de_files) > 3:
            print(f"   ... and {len(gabrielh_3de_files) - 3} more")
    else:
        print("\n❌ My Shots tab will be empty (no gabriel-h 3DE files)")

    if other_users_3de_files:
        print("\n✅ Other 3DE Scenes tab will be populated:")
        users: set[str] = set()
        shots: set[str] = set()
        for f in other_users_3de_files:
            parts = f.parts
            if "user" in parts:
                user_idx = parts.index("user")
                if user_idx + 1 < len(parts):
                    users.add(parts[user_idx + 1])
            if "shots" in parts:
                shots_idx = parts.index("shots")
                if shots_idx + 2 < len(parts):
                    shots.add(parts[shots_idx + 2])

        print(f"   Users: {', '.join(sorted(users))}")
        print(f"   Sample shots: {', '.join(sorted(shots)[:5])}")
    else:
        print("\n❌ Other 3DE Scenes tab will be empty (no other user 3DE files)")

    print("\n🎯 Summary:")
    if gabrielh_3de_files and other_users_3de_files:
        print("   ✅ Both 'My Shots' and 'Other 3DE Scenes' tabs will be populated")
        print("   🚀 Mock environment is ready for testing!")
        return True
    if gabrielh_3de_files:
        print("   ⚠️  Only 'My Shots' tab will be populated")
        return False
    if other_users_3de_files:
        print("   ⚠️  Only 'Other 3DE Scenes' tab will be populated")
        return False
    print("   ❌ Neither tab will be populated")
    return False


if __name__ == "__main__":
    # Test the enhanced mock environment
    shows_root = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mock_vfx_final/shows"
    success = verify_mock_environment(shows_root)

    if success:
        print("\n🎉 Enhanced mock environment verification PASSED!")
        print("\n📋 To test ShotBot with this environment:")
        print(f"   SHOWS_ROOT={shows_root} python shotbot.py --mock")
    else:
        print("\n❌ Enhanced mock environment verification FAILED!")

    sys.exit(0 if success else 1)
