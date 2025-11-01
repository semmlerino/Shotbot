#!/usr/bin/env python3
"""Test script for enhanced thumbnail discovery with turnover plates."""

import logging

from config import Config
from shot_model import Shot
from utils import PathUtils

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_turnover_plate_discovery():
    """Test finding thumbnails from turnover plates."""

    # Create a test shot
    test_shot = Shot(
        show="jack_ryan",
        sequence="GG_000",
        shot="0050",
        workspace_path="/shows/jack_ryan/shots/GG_000/GG_000_0050",
    )

    print("\n=== Testing Turnover Plate Discovery ===")
    print(f"Shot: {test_shot.full_name}")
    print(f"Show: {test_shot.show}")

    # Test editorial thumbnail path (original)
    print("\n1. Editorial thumbnail directory:")
    print(f"   {test_shot.thumbnail_dir}")

    # Test finding turnover plate thumbnail
    print("\n2. Looking for turnover plate thumbnails...")
    turnover_thumb = PathUtils.find_turnover_plate_thumbnail(
        Config.SHOWS_ROOT, test_shot.show, test_shot.sequence, test_shot.shot
    )

    if turnover_thumb:
        print(f"   ✓ Found turnover plate: {turnover_thumb}")
        print(f"   File size: {turnover_thumb.stat().st_size / (1024 * 1024):.2f} MB")
        print(f"   Plate type: {turnover_thumb.parent.parent.parent.parent.name}")
    else:
        print("   ✗ No turnover plates found")

    # Test the integrated get_thumbnail_path method
    print("\n3. Testing integrated get_thumbnail_path()...")
    thumbnail = test_shot.get_thumbnail_path()

    if thumbnail:
        print(f"   ✓ Found thumbnail: {thumbnail}")
        if "editorial" in str(thumbnail):
            print("   Source: Editorial")
        elif "turnover" in str(thumbnail):
            print("   Source: Turnover plate")
    else:
        print("   ✗ No thumbnail found")

    # Test another shot
    test_shot2 = Shot(
        show="jack_ryan",
        sequence="GF_256",
        shot="1200",
        workspace_path="/shows/jack_ryan/shots/GF_256/GF_256_1200",
    )

    print(f"\n=== Testing Shot 2: {test_shot2.full_name} ===")
    thumbnail2 = test_shot2.get_thumbnail_path()

    if thumbnail2:
        print(f"   ✓ Found thumbnail: {thumbnail2.name}")
        print(f"   Full path: {thumbnail2}")
    else:
        print("   ✗ No thumbnail found")


if __name__ == "__main__":
    test_turnover_plate_discovery()
    print("\n=== Test Complete ===\n")
