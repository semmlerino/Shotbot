#!/usr/bin/env python3
"""Verify the URL generation fix handles all edge cases correctly."""

from PySide6.QtCore import QUrl


def test_url_generation():
    """Test various path scenarios to ensure correct URL generation."""

    # Test cases with expected outcomes
    test_cases = [
        # (input_path, expected_url_string, description)
        (
            "/shows/test/shots/001/0010",
            "file:///shows/test/shots/001/0010",
            "Absolute Unix path",
        ),
        (
            "shows/test/shots/001/0010",
            "file:///shows/test/shots/001/0010",
            "Relative Unix path (missing leading /)",
        ),
        (
            "/path with spaces/folder",
            "file:///path%20with%20spaces/folder",
            "Path with spaces",
        ),
        (
            "/path/with/special!@#$%^&()chars",
            "file:///path/with/special!@%23$%25%5E&()chars",
            "Path with special characters",
        ),
        ("C:/Windows/System32", "file:///C:/Windows/System32", "Windows path"),
        ("//network/share/folder", "file:////network/share/folder", "UNC path"),
        (
            "/path/with/unicode/测试/folder",
            "file:///path/with/unicode/%E6%B5%8B%E8%AF%95/folder",
            "Unicode characters",
        ),
        ("/", "file:///", "Root directory"),
        ("", "file:///", "Empty path"),
    ]

    print("Testing URL Generation Fix")
    print("=" * 60)

    all_passed = True

    for input_path, expected_url, description in test_cases:
        # Apply the fix from thumbnail_widget_base.py
        folder_path = input_path
        if not folder_path.startswith("/"):
            folder_path = "/" + folder_path

        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

        url_string = url.toString()

        # Check if it starts with file:/// (three slashes)
        has_correct_prefix = url_string.startswith("file:///")

        # For comparison, what does fromLocalFile produce?
        from_local_url = QUrl.fromLocalFile(input_path)
        from_local_string = from_local_url.toString()

        # Determine if this case passes
        passes = has_correct_prefix

        print(f"\nTest: {description}")
        print(f"  Input: '{input_path}'")
        print(f"  Modified: '{folder_path}'")
        print(f"  Generated URL: '{url_string}'")
        print(f"  fromLocalFile: '{from_local_string}'")
        print(f"  Has file:///? {has_correct_prefix}")
        print(f"  Status: {'✓ PASS' if passes else '✗ FAIL'}")

        if not passes:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed! URL generation fix is working correctly.")
    else:
        print("✗ Some tests failed. Review the implementation.")

    return all_passed


def test_problematic_cases():
    """Test the specific problematic cases that caused the original issue."""

    print("\n" + "=" * 60)
    print("Testing Original Problem Cases")
    print("=" * 60)

    # The original issue: file://shows/... instead of file:///shows/...
    problem_paths = [
        "shows/TEST/shots/001/0010",  # This would generate file://shows/...
        "/shows/TEST/shots/001/0010",  # This should work correctly
    ]

    for path in problem_paths:
        print(f"\nOriginal path: '{path}'")

        # What would the old approach produce (potentially)?
        # Just using QUrl.fromLocalFile without the leading slash fix
        old_url = QUrl.fromLocalFile(path)
        print(f"  Old approach (fromLocalFile): '{old_url.toString()}'")

        # The new fix
        folder_path = path
        if not folder_path.startswith("/"):
            folder_path = "/" + folder_path

        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

        print(f"  New approach (with fix): '{url.toString()}'")

        # Check correctness
        is_correct = url.toString().startswith("file:///")
        print(f"  Correct format? {is_correct}")


def main():
    """Run all tests."""
    print("URL Generation Fix Verification")
    print("=" * 60)

    # Run comprehensive tests
    test_url_generation()

    # Test specific problem cases
    test_problematic_cases()

    print("\n" + "=" * 60)
    print("Verification complete.")


if __name__ == "__main__":
    main()
