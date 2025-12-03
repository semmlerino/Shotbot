#!/usr/bin/env python3
"""
Comprehensive test suite for critical fixes in ShotBot.

This test suite validates:
1. Dynamic SHOWS_ROOT configuration in regex patterns
2. PreviousShotsModel cleanup in main window closeEvent
3. JSON error handling in mock workspace pool

Run with: python test_critical_fixes_complete.py
"""

# Standard library imports
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def test_shows_root_dynamic_configuration():
    """Test that regex patterns adapt to SHOWS_ROOT configuration.

    IMPORTANT: This test reloads modules to test dynamic configuration.
    It must restore module state after completion to avoid contaminating
    other tests (see cleanup in finally block).
    """
    print("\n=== Testing Dynamic SHOWS_ROOT Configuration ===")

    # Standard library imports
    import importlib

    # Store original module references to restore later
    # This is critical because reloading creates new class objects,
    # which breaks isinstance() checks in other tests that already
    # imported the old class.
    modules_to_track = ["config", "targeted_shot_finder", "optimized_shot_parser"]
    original_modules = {}
    for mod_name in modules_to_track:
        if mod_name in sys.modules:
            original_modules[mod_name] = sys.modules[mod_name]

    test_cases = [
        ("/shows", r"\/shows\/([^/]+)/shots/([^/]+)/\2_([^/]+)/"),
        ("/tmp/mock_vfx", r"\/tmp\/mock_vfx\/([^/]+)/shots/([^/]+)/\2_([^/]+)/"),
        ("/custom/path", r"\/custom\/path\/([^/]+)/shots/([^/]+)/\2_([^/]+)/"),
    ]

    success_count = 0

    try:
        for shows_root, _expected_pattern_start in test_cases:
            print(f"\nTesting with SHOWS_ROOT={shows_root}")

            # Set environment variable
            with mock.patch.dict(os.environ, {"SHOWS_ROOT": shows_root}):
                # Force reload of config to pick up new environment
                # Local application imports
                import config

                importlib.reload(config)

                # Test targeted_shot_finder.py
                try:
                    # Local application imports
                    import targeted_shot_finder

                    # Reload the module to pick up new SHOWS_ROOT
                    importlib.reload(targeted_shot_finder)

                    from targeted_shot_finder import (
                        TargetedShotsFinder,
                    )

                    finder = TargetedShotsFinder()
                    pattern = finder._shot_pattern.pattern

                    # Check pattern contains escaped SHOWS_ROOT
                    shows_root_escaped = re.escape(shows_root)
                    assert shows_root_escaped in pattern, (
                        f"targeted_shot_finder.py: Pattern missing {shows_root_escaped}. Got: {pattern}"
                    )
                    print(
                        f"  ✓ targeted_shot_finder.py: Pattern contains {shows_root_escaped}"
                    )
                    success_count += 1

                    # Test pattern matching
                    test_path = f"{shows_root}/show1/shots/seq1/seq1_0010/user/test"
                    match = finder._shot_pattern.search(test_path)
                    assert match is not None, "targeted_shot_finder.py: Pattern match failed"
                    assert match.groups() == ("show1", "seq1", "seq1_0010"), (
                        "targeted_shot_finder.py: Pattern groups do not match"
                    )
                    print("  ✓ targeted_shot_finder.py: Pattern matches correctly")
                    success_count += 1

                except Exception as e:
                    print(f"  ✗ Error testing targeted_shot_finder.py: {e}")
                    raise

                # Test optimized_shot_parser.py
                try:
                    # Local application imports
                    import optimized_shot_parser

                    # Reload the module to pick up new SHOWS_ROOT
                    importlib.reload(optimized_shot_parser)

                    from optimized_shot_parser import (
                        OptimizedShotParser,
                    )

                    parser = OptimizedShotParser()
                    pattern = parser._ws_pattern.pattern

                    # Check pattern contains escaped SHOWS_ROOT
                    assert shows_root_escaped in pattern, (
                        f"optimized_shot_parser.py: Pattern missing {shows_root_escaped}. Got: {pattern}"
                    )
                    print(
                        f"  ✓ optimized_shot_parser.py: Pattern contains {shows_root_escaped}"
                    )
                    success_count += 1

                    # Test pattern matching
                    test_line = f"workspace {shows_root}/show1/shots/seq1/seq1_0010"
                    match = parser._ws_pattern.search(test_line)
                    assert match, "optimized_shot_parser.py: Workspace pattern failed"
                    print("  ✓ optimized_shot_parser.py: Workspace pattern matches")
                    success_count += 1

                except Exception as e:
                    print(f"  ✗ Error testing optimized_shot_parser.py: {e}")
                    raise

        print(f"\n✅ Dynamic SHOWS_ROOT tests: {success_count}/12 passed")
        assert success_count == 12, f"Expected 12 tests to pass, got {success_count}"

    finally:
        # CRITICAL: Restore original modules to prevent contaminating other tests.
        # After reloading, classes like ParseResult have different identities,
        # which breaks isinstance() checks in tests that imported the old class.
        for mod_name, original_mod in original_modules.items():
            sys.modules[mod_name] = original_mod


def test_previous_shots_model_cleanup():
    """Test that PreviousShotsModel is properly cleaned up via CleanupManager."""
    print("\n=== Testing PreviousShotsModel Cleanup ===")

    # Check that main_window uses CleanupManager
    main_window_path = Path(__file__).parent.parent.parent / "main_window.py"
    assert main_window_path.exists(), f"main_window.py not found at {main_window_path}"

    with main_window_path.open() as f:
        main_window_content = f.read()

    # Verify closeEvent delegates to CleanupManager
    if "self.cleanup_manager.perform_cleanup()" in main_window_content:
        print("  ✓ closeEvent delegates to CleanupManager")
        success_count = 1
    else:
        print("  ✗ closeEvent does not delegate to CleanupManager")
        success_count = 0

    # Check cleanup_manager.py for actual cleanup code
    cleanup_manager_path = Path(__file__).parent.parent.parent / "cleanup_manager.py"
    assert cleanup_manager_path.exists(), "cleanup_manager.py not found"

    with cleanup_manager_path.open() as f:
        content = f.read()

    checks = [
        (
            "PreviousShotsModel cleanup exists",
            'hasattr(self.main_window, "previous_shots_model")',
        ),
        ("Cleanup method called", "self.main_window.previous_shots_model.cleanup()"),
        ("Error handling present", "except Exception as e:"),
        ("Error logging", 'logger.error(f"Error cleaning up PreviousShotsModel: {e}")'),
        (
            "PreviousShotsItemModel cleanup",
            'hasattr(self.main_window, "previous_shots_item_model")',
        ),
        ("ItemModel cleanup call", "self.main_window.previous_shots_item_model.cleanup()"),
    ]

    failed_checks = []
    for check_name, check_string in checks:
        if check_string in content:
            print(f"  ✓ {check_name}")
            success_count += 1
        else:
            print(f"  ✗ {check_name} not found")
            failed_checks.append(check_name)

    print(f"\n✅ PreviousShotsModel cleanup tests: {success_count}/7 passed")
    assert success_count == 7, f"Expected 7 checks to pass, got {success_count}. Failed: {', '.join(failed_checks)}"


def test_json_error_handling():
    """Test comprehensive JSON error handling in mock_workspace_pool."""
    print("\n=== Testing JSON Error Handling ===")

    # Local application imports
    from mock_workspace_pool import (
        create_mock_pool_from_filesystem,
    )

    success_count = 0

    # Test 1: Missing demo_shots.json (should handle gracefully)
    print("\n1. Testing missing demo_shots.json")
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_path = Path(tmpdir) / "nonexistent.json"
        pool = create_mock_pool_from_filesystem(demo_shots_path=missing_path)
        assert pool is not None, "Failed to handle missing file"
        assert len(pool.shots) == 0, "Should have no shots with missing file"
        print("  ✓ Handles missing file gracefully")
        success_count += 1

    # Test 2: Invalid JSON syntax
    print("\n2. Testing invalid JSON syntax")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{invalid json}")
        temp_path = Path(f.name)

    try:
        pool = create_mock_pool_from_filesystem(demo_shots_path=temp_path)
        assert pool is not None, "Failed to handle invalid JSON"
        assert len(pool.shots) == 0, "Should have no shots with invalid JSON"
        print("  ✓ JSONDecodeError handled gracefully")
        success_count += 1
    finally:
        temp_path.unlink()

    # Test 3: Wrong JSON structure (not a dict)
    print("\n3. Testing wrong JSON structure (array instead of dict)")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([], f)  # Array instead of dict
        temp_path = Path(f.name)

    try:
        pool = create_mock_pool_from_filesystem(demo_shots_path=temp_path)
        assert pool is not None, "Failed to handle wrong structure"
        assert len(pool.shots) == 0, "Should have no shots with wrong structure"
        print("  ✓ Wrong structure handled")
        success_count += 1
    finally:
        temp_path.unlink()

    # Test 4: Missing 'shots' key
    print("\n4. Testing missing 'shots' key")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"other_key": "value"}, f)
        temp_path = Path(f.name)

    try:
        pool = create_mock_pool_from_filesystem(demo_shots_path=temp_path)
        assert pool is not None, "Failed to handle missing 'shots' key"
        assert len(pool.shots) == 0, "Should have no shots with missing 'shots' key"
        print("  ✓ Missing 'shots' key handled")
        success_count += 1
    finally:
        temp_path.unlink()

    # Test 5: Invalid shot structure (missing required fields)
    print("\n5. Testing invalid shot structure")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(
            {
                "shots": [
                    {"show": "test"},  # Missing seq and shot
                    {"seq": "seq01", "shot": "0010"},  # Missing show
                ]
            },
            f,
        )
        temp_path = Path(f.name)

    try:
        pool = create_mock_pool_from_filesystem(demo_shots_path=temp_path)
        assert pool is not None, "Failed to handle invalid shot structure"
        assert len(pool.shots) == 0, "Should have no shots with invalid structure"
        print("  ✓ Invalid shot structure handled")
        success_count += 1
    finally:
        temp_path.unlink()

    # Test 6: Valid JSON structure
    print("\n6. Testing valid JSON structure")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(
            {
                "shots": [
                    {"show": "test_show", "seq": "seq01", "shot": "0010"},
                    {"show": "test_show", "seq": "seq01", "shot": "0020"},
                ]
            },
            f,
        )
        temp_path = Path(f.name)

    try:
        pool = create_mock_pool_from_filesystem(demo_shots_path=temp_path)
        assert pool is not None, "Valid JSON not processed"
        assert len(pool.shots) == 2, f"Expected 2 shots, got {len(pool.shots)}"
        print("  ✓ Valid JSON processed correctly")
        success_count += 1
    finally:
        temp_path.unlink()

    print(f"\n✅ JSON error handling tests: {success_count}/6 passed")
    assert success_count == 6, f"Expected 6 tests to pass, got {success_count}"


def run_all_tests():
    """Run all critical fix tests."""
    print("=" * 60)
    print("SHOTBOT CRITICAL FIXES TEST SUITE")
    print("=" * 60)

    failed_tests = []

    # Test 1: Dynamic SHOWS_ROOT configuration
    try:
        test_shows_root_dynamic_configuration()
        print("✅ Dynamic SHOWS_ROOT tests PASSED")
    except AssertionError as e:
        failed_tests.append(f"Dynamic SHOWS_ROOT: {e}")
        print(f"❌ Dynamic SHOWS_ROOT tests FAILED: {e}")

    # Test 2: PreviousShotsModel cleanup
    try:
        test_previous_shots_model_cleanup()
        print("✅ PreviousShotsModel cleanup tests PASSED")
    except AssertionError as e:
        failed_tests.append(f"PreviousShotsModel cleanup: {e}")
        print(f"❌ PreviousShotsModel cleanup tests FAILED: {e}")

    # Test 3: JSON error handling
    try:
        test_json_error_handling()
        print("✅ JSON error handling tests PASSED")
    except AssertionError as e:
        failed_tests.append(f"JSON error handling: {e}")
        print(f"❌ JSON error handling tests FAILED: {e}")

    print("\n" + "=" * 60)
    if not failed_tests:
        print("🎉 ALL CRITICAL FIX TESTS PASSED! 🎉")
        print("The application is stable and ready for use.")
    else:
        print("⚠️ SOME TESTS FAILED - Please review the output above")
        for failure in failed_tests:
            print(f"  - {failure}")
    print("=" * 60)

    if failed_tests:
        raise AssertionError(f"{len(failed_tests)} test suite(s) failed")


if __name__ == "__main__":
    # Standard library imports
    import logging

    logging.basicConfig(level=logging.WARNING)  # Reduce noise during tests

    try:
        run_all_tests()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Test suite failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
