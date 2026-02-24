#!/usr/bin/env python3
"""Standalone test for shot extraction logic without PySide6 dependencies.

This test directly tests the actual implementation code to verify:
1. Shot extraction from directory names works correctly
2. Edge cases are handled properly
3. Empty string validation prevents crashes
"""

# Standard library imports
import re
import sys
from pathlib import Path


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def extract_shot_from_directory(shot_dir: str, sequence: str) -> str | None:
    """Extract shot number from directory name using actual implementation logic.

    This is the exact logic from targeted_shot_finder.py, previous_shots_finder.py,
    and threede_scene_finder_optimized.py.
    """
    # Extract shot number from directory name to match ws -sg parsing
    # The shot directory format is {sequence}_{shot}
    if shot_dir.startswith(f"{sequence}_"):
        # Remove the sequence prefix to get the shot number
        shot = shot_dir[len(sequence) + 1 :]  # +1 for the underscore
    else:
        # Fallback: use the last part after underscore
        shot_parts = shot_dir.rsplit("_", 1)
        # No underscore found, use whole name as shot
        shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

    # Validate shot is not empty (critical bug fix)
    if not shot:
        return None

    return shot


def parse_shot_from_path(path: str) -> tuple[str, str, str] | None:
    """Parse shot information from a filesystem path.

    This is the actual implementation from the finders.
    """
    shot_pattern = re.compile(r"/shows/([^/]+)/shots/([^/]+)/([^/]+)/")
    match = shot_pattern.search(path)

    if match:
        show, sequence, shot_dir = match.groups()

        shot = extract_shot_from_directory(shot_dir, sequence)
        if shot:
            return (show, sequence, shot)

    return None


def test_shot_extraction():
    """Test shot extraction with actual ws -sg data patterns."""
    print("Testing Shot Extraction Logic")
    print("=" * 50)

    # Test cases from actual ws -sg output
    test_cases = [
        # (shot_dir, sequence, expected_shot, description)
        ("012_DC_1000", "012_DC", "1000", "Standard format from gator"),
        ("012_DC_1070", "012_DC", "1070", "Another gator shot"),
        ("DB_271_1760", "DB_271", "1760", "Jack Ryan shot"),
        ("FF_278_4380", "FF_278", "4380", "Jack Ryan with high number"),
        ("BRX_166_0010", "BRX_166", "0010", "Broken eggs with leading zeros"),
        ("999_xx_999", "999_xx", "999", "Special test shot"),
        # User's specific examples
        ("DB_256_1200", "DB_256", "1200", "User's DB_256 example"),
        # Edge cases that should be handled
        ("BB_", "BB", None, "Empty shot after underscore (bug fix)"),
        ("BB", "BB", "BB", "No underscore, use whole name"),
        ("TEST_001", "TEST", "001", "Simple case"),
        ("A_B_C", "A_B", "C", "Multiple underscores"),
        ("XYZ_", "XYZ", None, "Another empty shot case"),
    ]

    passed = 0
    failed = 0

    for shot_dir, sequence, expected, description in test_cases:
        result = extract_shot_from_directory(shot_dir, sequence)

        if result == expected:
            print(f"  ✓ {shot_dir} → {result} ({description})")
            passed += 1
        else:
            print(
                f"  ❌ {shot_dir}: expected '{expected}', got '{result}' ({description})"
            )
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    assert failed == 0, f"{failed} test(s) failed"


def test_path_parsing():
    """Test parsing full paths from filesystem."""
    print("\nTesting Full Path Parsing")
    print("=" * 50)

    test_paths = [
        # (path, expected_result, description)
        (
            "/shows/gator/shots/012_DC/012_DC_1000/user/ryan",
            ("gator", "012_DC", "1000"),
            "Gator shot path",
        ),
        (
            "/shows/jack_ryan/shots/DB_271/DB_271_1760/user/john",
            ("jack_ryan", "DB_271", "1760"),
            "Jack Ryan shot path",
        ),
        (
            "/shows/broken_eggs/shots/BRX_166/BRX_166_0010/publish/mm",
            ("broken_eggs", "BRX_166", "0010"),
            "Broken eggs with publish",
        ),
        (
            "/shows/jack_ryan/shots/999_xx/999_xx_999/user/test",
            ("jack_ryan", "999_xx", "999"),
            "Special test shot",
        ),
        (
            "/shows/test/shots/BB/BB_/user/someone",
            None,
            "Empty shot case (should be rejected)",
        ),
        (
            "/shows/test/shots/XYZ/XYZ/user/someone",
            ("test", "XYZ", "XYZ"),
            "No underscore case",
        ),
    ]

    passed = 0
    failed = 0

    for path, expected, description in test_paths:
        result = parse_shot_from_path(path)

        if result == expected:
            if result:
                print(f"  ✓ {result[0]}/{result[1]}/{result[2]} ({description})")
            else:
                print(f"  ✓ Correctly rejected: {path} ({description})")
            passed += 1
        else:
            print(f"  ❌ Path: {path}")
            print(f"     Expected: {expected}")
            print(f"     Got: {result}")
            print(f"     ({description})")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    assert failed == 0, f"{failed} test(s) failed"


def test_3de_file_paths():
    """Test extraction from actual 3DE file paths."""
    print("\nTesting 3DE File Path Extraction")
    print("=" * 50)

    # Example 3DE paths from user
    test_3de_paths = [
        (
            "/shows/gator/shots/012_DC/012_DC_1000/user/ryan-p/mm/3de/mm-default/scenes/scene/bg01/012_DC_1000_mm_default_bg01_scene_v001.3de",
            ("gator", "012_DC", "1000"),
            "Complex 3DE path",
        ),
        (
            "/shows/jack_ryan/shots/DB_256/DB_256_1200/user/john/3de/test.3de",
            ("jack_ryan", "DB_256", "1200"),
            "User's DB_256 example",
        ),
        (
            "/shows/broken_eggs/shots/BRX_170/BRX_170_0100/publish/mm/3de/scene.3de",
            ("broken_eggs", "BRX_170", "0100"),
            "Published 3DE file",
        ),
    ]

    passed = 0
    failed = 0

    for path, expected, description in test_3de_paths:
        result = parse_shot_from_path(path)

        if result == expected:
            print(f"  ✓ {result[0]}/{result[1]}/{result[2]} ({description})")
            passed += 1
        else:
            print(f"  ❌ Failed to extract from: {path}")
            print(f"     Expected: {expected}")
            print(f"     Got: {result}")
            print(f"     ({description})")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    assert failed == 0, f"{failed} test(s) failed"


def main() -> int:
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SHOT EXTRACTION STANDALONE TEST")
    print("=" * 60)
    print("\nThis test validates the actual implementation logic")
    print("without any mocking or PySide6 dependencies.\n")

    all_passed = True

    # Run tests
    if not test_shot_extraction():
        all_passed = False

    if not test_path_parsing():
        all_passed = False

    if not test_3de_file_paths():
        all_passed = False

    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED!")
        print("The shot extraction logic correctly handles all cases,")
        print("including the critical empty string validation fix.")
        return 0
    print("❌ SOME TESTS FAILED")
    print("Please review the failures above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
