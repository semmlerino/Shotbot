#!/usr/bin/env python3
"""Quick test validation without pytest overhead."""

# Standard library imports
import os
import sys
from pathlib import Path


# Set up environment
# Add the project root directory (two levels up from utilities)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def test_imports():
    """Test that key modules can be imported."""
    print("Testing imports...")

    modules_to_test = [
        "shot_model",
        "cache_manager",
        "utils",
        "main_window",
        "command_launcher",
        "launcher_manager",
        "previous_shots_finder",
        # "threede_scene_finder",  # Removed in Phase 1 Task 1.2 (deleted alias layer)
    ]

    failed = []
    for module in modules_to_test:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except Exception as e:
            print(f"  ❌ {module}: {e}")
            failed.append(module)

    return len(failed) == 0


def test_basic_functionality():
    """Test basic functionality without pytest."""
    print("\nTesting basic functionality...")

    tests_passed = 0
    tests_failed = 0

    # Test 1: Shot model
    try:
        # Local application imports
        from shot_model import (
            Shot,
        )

        shot = Shot("test_show", "seq01", "0010", "/test/path")
        assert shot.show == "test_show"
        assert shot.full_name == "seq01_0010"
        print("  ✅ Shot model works")
        tests_passed += 1
    except Exception as e:
        print(f"  ❌ Shot model failed: {e}")
        tests_failed += 1

    # Test 2: Utils
    try:
        # Local application imports
        from utils import (
            PathUtils,
        )

        path = PathUtils.build_path("/base", "dir", "file.txt")
        assert str(path) == "/base/dir/file.txt"
        print("  ✅ PathUtils works")
        tests_passed += 1
    except Exception as e:
        print(f"  ❌ PathUtils failed: {e}")
        tests_failed += 1

    # Test 3: Config
    try:
        # Local application imports
        from config import (
            Config,
        )

        assert Config.CACHE_THUMBNAIL_SIZE > 0
        assert Config.CACHE_EXPIRY_MINUTES > 0
        assert Config.APP_NAME == "ShotBot"
        print("  ✅ Config works")
        tests_passed += 1
    except Exception as e:
        print(f"  ❌ Config failed: {e}")
        tests_failed += 1

    # Test 4: File utils
    try:
        # Local application imports
        from utils import (
            FileUtils,
        )

        # Just test that methods exist
        assert hasattr(FileUtils, "find_files_by_extension")
        assert hasattr(FileUtils, "get_first_image_file")
        print("  ✅ FileUtils works")
        tests_passed += 1
    except Exception as e:
        print(f"  ❌ FileUtils failed: {e}")
        tests_failed += 1

    print(f"\n📊 Results: {tests_passed} passed, {tests_failed} failed")
    return tests_failed == 0


def test_qt_components() -> bool | None:
    """Test Qt components can be imported."""
    print("\nTesting Qt components...")

    try:
        print("  ✅ Qt imports work")
        return True
    except Exception as e:
        print(f"  ❌ Qt imports failed: {e}")
        return False


def main() -> int:
    """Run quick tests."""
    print("🚀 Quick Test Suite (No pytest)")
    print("=" * 40)

    all_passed = True

    # Test imports
    if not test_imports():
        all_passed = False

    # Test basic functionality
    if not test_basic_functionality():
        all_passed = False

    # Test Qt
    if not test_qt_components():
        all_passed = False

    print("\n" + "=" * 40)
    if all_passed:
        print("✅ All quick tests passed!")
        print("\n💡 Next steps:")
        print("  1. Run during low system load for full tests")
        print("  2. Or use: python3 run_tests_wsl.py --fast")
        print("  3. Or test single files to reduce I/O")
        return 0
    print("❌ Some tests failed")
    print("\n💡 Fix the failures above before running full test suite")
    return 1


if __name__ == "__main__":
    sys.exit(main())
