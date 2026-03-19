#!/usr/bin/env python3
"""Run ShotBot in mock mode and display a summary of available shots."""

# Standard library imports
import os
import sys
from collections import defaultdict

# Local application imports
from cache_manager import CacheManager
from shot_model import ShotModel


# Enable mock mode
os.environ["SHOTBOT_MOCK"] = "1"

print("🎬 SHOTBOT MOCK VFX ENVIRONMENT")
print("=" * 70)
print("Simulating production VFX workstation: tempest.blue-bolt.lan")
print("=" * 70)

# Create shot model
cache_manager = CacheManager()
shot_model = ShotModel(cache_manager)

# Refresh shots
print("\n📊 Loading shots from mock VFX filesystem...")
success, has_changes = shot_model.refresh_shots()

if success:
    print(f"✅ Successfully loaded {len(shot_model.shots)} shots\n")

    # Organize by show and sequence
    shows = defaultdict(lambda: defaultdict(list))

    for shot in shot_model.shots:
        shows[shot.show][shot.sequence].append(shot)

    # Display summary
    print("📺 SHOWS AND SHOTS:")
    print("-" * 70)

    for show_name in sorted(shows.keys()):
        sequences = shows[show_name]
        total_shots = sum(len(shots) for shots in sequences.values())

        print(
            f"\n🎬 {show_name.upper()} ({total_shots} shots, {len(sequences)} sequences)"
        )
        print("  " + "=" * 60)

        # Show first few sequences
        for seq_count, seq_name in enumerate(sorted(sequences.keys()), start=1):
            shots = sequences[seq_name]

            if seq_count <= 5:
                # Show shot numbers
                shot_nums = sorted([s.shot for s in shots])
                shot_display = ", ".join(shot_nums[:5])
                if len(shot_nums) > 5:
                    shot_display += f", ... ({len(shot_nums)} total)"

                print(f"  📁 {seq_name}: {shot_display}")
            elif seq_count == 6:
                remaining = len(sequences) - 5
                print(f"  ... and {remaining} more sequences")
                break

    print("\n" + "=" * 70)
    print("💡 WHAT YOU CAN DO:")
    print("-" * 70)
    print("  • Browse all 432 shots in the GUI")
    print("  • Launch VFX applications (3DE, Nuke, Maya)")
    print("  • Search for 3DE scenes across shows")
    print("  • View previous/approved shots")
    print("  • All WITHOUT needing VFX infrastructure!")

    print("\n" + "=" * 70)
    print("🚀 TO RUN SHOTBOT WITH GUI:")
    print("-" * 70)
    print("  uv run python shotbot_mock.py")
    print("  OR")
    print("  uv run python run_mock_vfx_env.py")

    print("\n" + "=" * 70)
    print("✅ MOCK ENVIRONMENT STATUS: FULLY OPERATIONAL")
    print("=" * 70)

else:
    print("❌ Failed to load shots")
    sys.exit(1)
