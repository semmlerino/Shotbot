#!/usr/bin/env python3
"""Manual verification script for incremental caching system.

This script demonstrates the complete incremental caching workflow:
1. Load 432 mock shots and verify initial state
2. Simulate removal of 3 shots
3. Verify 429 in My Shots, 3 in Previous Shots
4. Print clear pass/fail results

Usage:
    python verify_incremental_caching.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from cache_manager import CacheManager
from shot_model import Shot


def print_header(text: str) -> None:
    """Print formatted section header."""
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}\n")


def print_status(test_name: str, passed: bool, details: str = "") -> None:
    """Print test status with pass/fail indicator."""
    status = "✓ PASS" if passed else "✗ FAIL"
    symbol = "✓" if passed else "✗"
    print(f"{symbol} {test_name:.<60} {status}")
    if details:
        print(f"  └─ {details}")


def generate_mock_shots(count: int, show: str = "broken_eggs") -> list[Shot]:
    """Generate mock Shot objects.

    Args:
        count: Number of shots to generate
        show: Show name (default: broken_eggs)

    Returns:
        List of Shot objects with sequential naming

    """
    shots = []
    for i in range(count):
        sequence = f"sq{i // 10:04d}"
        shot = f"shot_{i:04d}"
        workspace = f"/shows/{show}/shots/{sequence}/{shot}"
        shots.append(
            Shot(show=show, sequence=sequence, shot=shot, workspace_path=workspace)
        )
    return shots


def verify_initial_load() -> tuple[bool, CacheManager, Path]:
    """Test 1: Initial load of 432 shots.

    Returns:
        Tuple of (success, cache_manager, cache_dir)

    """
    print_header("Test 1: Initial Load (432 Shots)")

    # Create temporary cache directory
    temp_dir = tempfile.mkdtemp(prefix="shotbot_verify_")
    cache_dir = Path(temp_dir)
    cache_manager = CacheManager(cache_dir=cache_dir)

    # Generate and cache 432 mock shots
    shots = generate_mock_shots(432)
    cache_manager.cache_shots(shots)

    # Verify cache file exists
    cache_file_exists = cache_manager.shots_cache_file.exists()
    print_status("Cache file created", cache_file_exists)

    # Verify shot count
    cached = cache_manager.get_shots_no_ttl()
    if cached is None:
        print_status("Initial shots cached", False, "Cache returned None")
        return False, cache_manager, cache_dir

    count_correct = len(cached) == 432
    print_status(
        "Initial shot count correct", count_correct, f"Expected 432, got {len(cached)}"
    )

    # Verify no migrations yet
    migrated = cache_manager.get_shots_archive()
    no_migrations = migrated is None or len(migrated) == 0
    print_status("No migrations initially", no_migrations)

    success = cache_file_exists and count_correct and no_migrations
    return success, cache_manager, cache_dir


def verify_merge_no_changes(cache_manager: CacheManager) -> bool:
    """Test 2: Merge with identical data (no changes).

    Args:
        cache_manager: CacheManager instance with 432 cached shots

    Returns:
        True if test passes

    """
    print_header("Test 2: Merge No Changes (432 → 432)")

    # Load cached shots
    cached = cache_manager.get_shots_no_ttl()
    if cached is None:
        print_status("Load cached shots", False, "Cache returned None")
        return False

    # Merge with identical fresh data
    fresh = cached.copy()
    result = cache_manager.update_shots_cache(cached, fresh)

    # Verify no changes detected
    no_changes = not result.has_changes
    print_status("No changes detected", no_changes)

    # Verify counts
    no_new = len(result.new_shots) == 0
    print_status("No new shots", no_new, f"Expected 0, got {len(result.new_shots)}")

    no_removed = len(result.removed_shots) == 0
    print_status(
        "No removed shots", no_removed, f"Expected 0, got {len(result.removed_shots)}"
    )

    count_unchanged = len(result.updated_shots) == 432
    print_status(
        "Shot count unchanged",
        count_unchanged,
        f"Expected 432, got {len(result.updated_shots)}",
    )

    return no_changes and no_new and no_removed and count_unchanged


def verify_remove_shots(cache_manager: CacheManager) -> bool:
    """Test 3: Remove 3 shots via incremental merge.

    Args:
        cache_manager: CacheManager instance with 432 cached shots

    Returns:
        True if test passes

    """
    print_header("Test 3: Remove 3 Shots (432 → 429)")

    # Load cached shots (432)
    cached = cache_manager.get_shots_no_ttl()
    if cached is None:
        print_status("Load cached shots", False, "Cache returned None")
        return False

    # Create fresh data with 3 shots removed (remove last 3)
    fresh = cached[:-3]  # 429 shots

    # Perform merge
    result = cache_manager.update_shots_cache(cached, fresh)

    # Verify changes detected
    changes_detected = result.has_changes
    print_status("Changes detected", changes_detected)

    # Verify removed count
    removed_count = len(result.removed_shots) == 3
    print_status(
        "3 shots removed", removed_count, f"Expected 3, got {len(result.removed_shots)}"
    )

    # Verify updated count
    updated_count = len(result.updated_shots) == 429
    print_status(
        "429 shots remaining",
        updated_count,
        f"Expected 429, got {len(result.updated_shots)}",
    )

    # Verify no new shots
    no_new = len(result.new_shots) == 0
    print_status("No new shots added", no_new)

    # Migrate removed shots
    cache_manager.archive_shots_as_previous(result.removed_shots)

    # Verify migration
    migrated = cache_manager.get_shots_archive()
    migration_success = migrated is not None and len(migrated) == 3
    print_status(
        "Migration successful",
        migration_success,
        f"Expected 3 migrated, got {len(migrated) if migrated else 0}",
    )

    return (
        changes_detected
        and removed_count
        and updated_count
        and no_new
        and migration_success
    )


def verify_deduplication(cache_manager: CacheManager) -> bool:
    """Test 4: Verify composite key deduplication.

    Args:
        cache_manager: CacheManager instance

    Returns:
        True if test passes

    """
    print_header("Test 4: Deduplication (Composite Keys)")

    # Clear any existing migrated shots from previous tests
    if cache_manager.migrated_shots_cache_file.exists():
        cache_manager.migrated_shots_cache_file.unlink()

    # Create shots with same sequence/shot, different shows
    shot1 = Shot(
        show="broken_eggs", sequence="sq0010", shot="sq0010_0010", workspace_path="/p1"
    )
    shot2 = Shot(
        show="gator", sequence="sq0010", shot="sq0010_0010", workspace_path="/p2"
    )
    shot3 = Shot(
        show="broken_eggs", sequence="sq0010", shot="sq0010_0010", workspace_path="/p3"
    )  # Duplicate of shot1

    # Migrate all three
    cache_manager.archive_shots_as_previous([shot1, shot2, shot3])

    # Load migrated shots
    migrated = cache_manager.get_shots_archive()
    if migrated is None:
        print_status("Load migrated shots", False, "Migration returned None")
        return False

    # Verify only 2 unique shots (shot1 and shot2, shot3 is duplicate of shot1)
    unique_count = len(migrated) == 2
    print_status(
        "2 unique shots preserved", unique_count, f"Expected 2, got {len(migrated)}"
    )

    # Verify composite keys
    composite_keys = {(s["show"], s["sequence"], s["shot"]) for s in migrated}
    expected_keys = {
        ("broken_eggs", "sq0010", "sq0010_0010"),
        ("gator", "sq0010", "sq0010_0010"),
    }
    keys_correct = composite_keys == expected_keys
    print_status("Composite keys correct", keys_correct)

    # Verify cross-show uniqueness preserved
    shows = {s["show"] for s in migrated}
    cross_show = shows == {"broken_eggs", "gator"}
    print_status("Cross-show uniqueness", cross_show, f"Shows: {shows}")

    return unique_count and keys_correct and cross_show


def verify_performance(cache_manager: CacheManager) -> bool:
    """Test 5: Performance benchmark for merge operation.

    Args:
        cache_manager: CacheManager instance

    Returns:
        True if test passes

    """
    print_header("Test 5: Performance Benchmark")

    # Generate 500 cached shots
    cached_shots = generate_mock_shots(500)
    cached_dicts = [s.to_dict() for s in cached_shots]

    # Generate fresh data with 1 new shot
    fresh_shots = [
        *cached_shots,
        Shot(show="test", sequence="sq9999", shot="shot_9999", workspace_path="/test"),
    ]
    fresh_dicts = [s.to_dict() for s in fresh_shots]

    # Benchmark merge operation
    start = time.time()
    result = cache_manager.update_shots_cache(cached_dicts, fresh_dicts)
    elapsed_ms = (time.time() - start) * 1000

    # Verify performance requirement (<10ms)
    fast_enough = elapsed_ms < 10.0
    print_status("Merge completes in <10ms", fast_enough, f"Actual: {elapsed_ms:.2f}ms")

    # Verify correctness
    correct_count = len(result.updated_shots) == 501
    print_status("Correct result", correct_count, "501 shots after merge")

    new_shot_found = len(result.new_shots) == 1
    print_status("New shot detected", new_shot_found)

    return fast_enough and correct_count and new_shot_found


def cleanup_cache(cache_dir: Path) -> None:
    """Clean up temporary cache directory.

    Args:
        cache_dir: Path to cache directory to remove

    """
    import shutil

    try:
        shutil.rmtree(cache_dir)
        print(f"\n✓ Cleaned up temporary cache: {cache_dir}")
    except OSError as e:
        print(f"\n⚠ Failed to clean up cache: {e}")


def main() -> int:
    """Run all verification tests.

    Returns:
        Exit code (0 = success, 1 = failure)

    """
    print("\n" + "=" * 70)
    print("  INCREMENTAL CACHING VERIFICATION")
    print("=" * 70)
    print("\nThis script verifies the complete incremental caching system:")
    print("  • Phases 1-3 implementation")
    print("  • Merge algorithm correctness")
    print("  • Migration system functionality")
    print("  • Deduplication via composite keys")
    print("  • Performance benchmarks")

    results = []

    # Test 1: Initial load
    success1, cache_manager, cache_dir = verify_initial_load()
    results.append(("Initial Load (432 shots)", success1))

    if not success1:
        print("\n✗ Test 1 failed, cannot continue")
        return 1

    # Test 2: Merge no changes
    success2 = verify_merge_no_changes(cache_manager)
    results.append(("Merge No Changes", success2))

    # Test 3: Remove shots and migrate
    success3 = verify_remove_shots(cache_manager)
    results.append(("Remove & Migrate (429 + 3)", success3))

    # Test 4: Deduplication
    success4 = verify_deduplication(cache_manager)
    results.append(("Deduplication", success4))

    # Test 5: Performance
    success5 = verify_performance(cache_manager)
    results.append(("Performance (<10ms)", success5))

    # Print summary
    print_header("SUMMARY")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        print_status(test_name, success)

    print(f"\n{passed}/{total} tests passed")

    # Cleanup
    cleanup_cache(cache_dir)

    # Final verdict
    if passed == total:
        print("\n" + "=" * 70)
        print("  ✓✓✓ ALL TESTS PASSED - INCREMENTAL CACHING VERIFIED ✓✓✓")
        print("=" * 70 + "\n")
        return 0
    print("\n" + "=" * 70)
    print(f"  ✗✗✗ {total - passed} TEST(S) FAILED ✗✗✗")
    print("=" * 70 + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
