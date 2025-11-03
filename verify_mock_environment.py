#!/usr/bin/env python3
"""Verify the mock VFX environment is working correctly.

This script tests that ShotBot can properly load and work with
the recreated VFX filesystem containing hundreds of real shots.
"""

# Standard library imports
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path


# Set up environment
os.environ["SHOTBOT_MOCK"] = "1"
os.environ["SHOTBOT_HEADLESS"] = "1"  # Run without display

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def test_mock_pool() -> int:
    """Test the mock workspace pool directly."""
    # Local application imports
    from mock_workspace_pool import create_mock_pool_from_filesystem

    logger.info("=" * 70)
    logger.info("TESTING MOCK WORKSPACE POOL")
    logger.info("=" * 70)

    pool = create_mock_pool_from_filesystem()
    output = pool.execute_workspace_command("ws -sg")
    shots = [line for line in output.split("\n") if line.strip()]

    logger.info(f"✅ Mock pool loaded {len(shots)} shots from filesystem")

    # Analyze shots by show
    by_show: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for shot_line in shots:
        if "workspace /shows/" in shot_line:
            parts = shot_line.split("/")
            if len(parts) >= 6:
                show = parts[2]
                seq = parts[4]
                shot = parts[5]
                by_show[show].append((seq, shot))

    logger.info("\nShots by show:")
    for show, shot_list in sorted(by_show.items()):
        logger.info(f"  📺 {show}: {len(shot_list)} shots")

        # Group by sequence
        by_seq: defaultdict[str, list[str]] = defaultdict(list)
        for seq, shot in shot_list:
            by_seq[seq].append(shot)

        # Show first few sequences
        for seq in sorted(by_seq.keys())[:3]:
            logger.info(f"      {seq}: {len(by_seq[seq])} shots")

        if len(by_seq) > 3:
            logger.info(f"      ... and {len(by_seq) - 3} more sequences")

    return len(shots)


def test_shot_model() -> int:
    """Test that ShotModel properly loads all shots."""
    # Local application imports
    from cache_manager import CacheManager
    from mock_workspace_pool import create_mock_pool_from_filesystem
    from shot_model import ShotModel

    logger.info("\n" + "=" * 70)
    logger.info("TESTING SHOT MODEL")
    logger.info("=" * 70)

    # Create mock pool
    mock_pool = create_mock_pool_from_filesystem()

    # Create shot model with mock pool
    cache_manager = CacheManager()
    shot_model = ShotModel(cache_manager, process_pool=mock_pool)

    # Refresh shots
    success, _ = shot_model.refresh_shots()  # has_changes not used

    if success:
        logger.info(f"✅ ShotModel loaded {len(shot_model.shots)} shots")

        # Analyze loaded shots
        by_show: defaultdict[str, int] = defaultdict(int)
        by_seq: defaultdict[str, int] = defaultdict(int)

        for shot in shot_model.shots:
            by_show[shot.show] += 1
            by_seq[f"{shot.show}/{shot.sequence}"] += 1

        logger.info("\nLoaded shots by show:")
        for show, count in sorted(by_show.items()):
            logger.info(f"  📺 {show}: {count} shots")

        # Show some example shots
        logger.info("\nExample shots:")
        for shot in shot_model.shots[:5]:
            logger.info(
                f"  • {shot.show}/{shot.sequence}/{shot.shot} - {shot.workspace_path}"
            )

        if len(shot_model.shots) > 5:
            logger.info(f"  ... and {len(shot_model.shots) - 5} more")

        return len(shot_model.shots)
    logger.error("❌ Failed to load shots")
    return 0


def test_headless_app() -> int:
    """Test running the app in headless mode."""
    # Local application imports
    from headless_mode import HeadlessMainWindow

    logger.info("\n" + "=" * 70)
    logger.info("TESTING HEADLESS APPLICATION")
    logger.info("=" * 70)

    # Create headless window
    window = HeadlessMainWindow()

    # Refresh shots
    if window.refresh_shots():
        shots = window.get_shots()
        logger.info(f"✅ Headless app loaded {len(shots)} shots")
        return len(shots)
    logger.error("❌ Failed to load shots in headless mode")
    return 0


def verify_filesystem() -> bool:
    """Verify the mock filesystem structure."""
    logger.info("\n" + "=" * 70)
    logger.info("VERIFYING MOCK FILESYSTEM")
    logger.info("=" * 70)

    mock_root = Path("/tmp/mock_vfx")

    if not mock_root.exists():
        logger.error("❌ Mock filesystem not found at /tmp/mock_vfx")
        return False

    # Count directories and files
    total_dirs = 0
    total_files = 0
    shot_dirs = 0

    for path in mock_root.rglob("*"):
        if path.is_dir():
            total_dirs += 1
            # Check if it's a shot directory
            if path.parent.name == "shots" or (
                path.parent.parent.name == "shots" and "_" in path.name
            ):
                shot_dirs += 1
        else:
            total_files += 1

    logger.info("✅ Mock filesystem statistics:")
    logger.info(f"   • Total directories: {total_dirs:,}")
    logger.info(f"   • Total files: {total_files:,}")
    logger.info(f"   • Shot directories: {shot_dirs}")

    # Check marker file
    marker = mock_root / "MOCK_VFX_ENVIRONMENT.txt"
    if marker.exists():
        with marker.open() as f:
            content = f.read()
            if "tempest.blue-bolt.lan" in content:
                logger.info(
                    "   • Source: tempest.blue-bolt.lan (production VFX workstation)"
                )

    return True


def main() -> int:
    """Run all verification tests."""
    logger.info("🎬 SHOTBOT MOCK VFX ENVIRONMENT VERIFICATION")
    logger.info("=" * 70)

    results: dict[str, str] = {}

    # Verify filesystem
    if verify_filesystem():
        results["filesystem"] = "✅ PASS"
    else:
        results["filesystem"] = "❌ FAIL"

    # Test mock pool
    try:
        shot_count = test_mock_pool()
        if shot_count > 0:
            results["mock_pool"] = f"✅ PASS ({shot_count} shots)"
        else:
            results["mock_pool"] = "❌ FAIL"
    except Exception as e:
        logger.error(f"Mock pool test failed: {e}")
        results["mock_pool"] = "❌ ERROR"

    # Test shot model
    try:
        shot_count = test_shot_model()
        if shot_count > 0:
            results["shot_model"] = f"✅ PASS ({shot_count} shots)"
        else:
            results["shot_model"] = "❌ FAIL"
    except Exception as e:
        logger.error(f"Shot model test failed: {e}")
        results["shot_model"] = "❌ ERROR"

    # Test headless app
    try:
        shot_count = test_headless_app()
        if shot_count > 0:
            results["headless"] = f"✅ PASS ({shot_count} shots)"
        else:
            results["headless"] = "❌ FAIL"
    except Exception as e:
        logger.error(f"Headless test failed: {e}")
        results["headless"] = "❌ ERROR"

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("=" * 70)

    for test_name, result in results.items():
        logger.info(f"  {test_name:20} {result}")

    # Overall result
    all_pass = all("PASS" in str(r) for r in results.values())

    logger.info("\n" + "=" * 70)
    if all_pass:
        logger.info("🎉 ALL TESTS PASSED! Mock VFX environment is fully operational")
        logger.info("   ShotBot can now run without VFX infrastructure")
        logger.info("   simulating a production workstation with 400+ real shots")
    else:
        logger.info("⚠️  Some tests failed. Check output above for details")
    logger.info("=" * 70)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
