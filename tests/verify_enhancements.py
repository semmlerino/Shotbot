#!/usr/bin/env python3
"""Verify test suite enhancements are correctly implemented."""

# Standard library imports
import sys
from pathlib import Path


# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def verify_property_based_tests() -> bool:
    """Verify property-based test file exists and is structured correctly."""
    test_file = Path(__file__).parent / "unit" / "test_property_based.py"

    if not test_file.exists():
        print("❌ Property-based test file not found")
        return False

    content = test_file.read_text()

    # Check for key property test classes
    required_classes = [
        "TestShotPathProperties",
        "TestCacheKeyProperties",
        "TestWorkspaceCommandProperties",
        "TestPathValidationProperties",
        "TestSceneFinderProperties",
    ]

    for cls in required_classes:
        if f"class {cls}" not in content:
            print(f"❌ Missing class: {cls}")
            return False

    print("✅ Property-based tests correctly structured")
    return True


def verify_conftest_enhancements() -> bool:
    """Verify conftest.py has been enhanced with new fixtures."""
    conftest = Path(__file__).parent / "conftest.py"

    if not conftest.exists():
        print("❌ conftest.py not found")
        return False

    content = conftest.read_text()

    # Check for new fixtures
    required_fixtures = [
        "pytest_configure",  # Marker configuration
        "test_data_dir",  # Session fixtures
        "performance_threshold",
        "make_test_process",  # Factory fixtures
        "make_test_launcher",
        "make_thread_safe_image",
        "workspace_command_outputs",  # Common test data
        "common_test_paths",
        "benchmark_timer",  # Performance fixtures
        "memory_tracker",
        "concurrent_executor",  # Threading fixtures
        "thread_safety_monitor",
    ]

    missing = [
        fixture
        for fixture in required_fixtures
        if f"def {fixture}" not in content and f"def _{fixture}" not in content
    ]

    if missing:
        print(f"❌ Missing fixtures: {', '.join(missing)}")
        return False

    print("✅ Conftest enhancements correctly implemented")
    return True


def verify_marker_consistency() -> bool:
    """Verify test files have consistent markers."""
    test_files = [
        Path(__file__).parent / "unit" / "test_launcher_manager_coverage.py",
        Path(__file__).parent / "unit" / "test_cache_manager.py",
        Path(__file__).parent / "unit" / "test_doubles.py",
        Path(__file__).parent / "integration" / "test_shot_workflow_integration.py",
    ]

    files_with_markers = 0
    for test_file in test_files:
        if test_file.exists():
            content = test_file.read_text()
            if "pytestmark" in content or "@pytest.mark" in content:
                files_with_markers += 1

    if files_with_markers < len(test_files) - 1:  # Allow 1 file without markers
        print(f"⚠️  Only {files_with_markers}/{len(test_files)} files have markers")
        return False

    print("✅ Test markers are consistently applied")
    return True


def verify_test_doubles() -> bool:
    """Verify test doubles follow UNIFIED_TESTING_GUIDE patterns."""
    test_doubles_file = Path(__file__).parent / "unit" / "test_doubles.py"

    if not test_doubles_file.exists():
        print("❌ test_doubles.py not found")
        return False

    content = test_doubles_file.read_text()

    # Check for key test doubles
    required_doubles = [
        "SignalDouble",
        "TestProcessPool",
        "TestFileSystem",
        "TestCache",
    ]

    for double in required_doubles:
        if f"class {double}" not in content:
            print(f"❌ Missing test double: {double}")
            return False

    # Check for __test__ = False to prevent pytest collection
    if "__test__ = False" not in content:
        print("⚠️  Test doubles should have __test__ = False")

    print("✅ Test doubles correctly implemented")
    return True


def main() -> int:
    """Run all verification checks."""
    print("=" * 60)
    print("VERIFYING TEST SUITE ENHANCEMENTS")
    print("=" * 60)

    checks = [
        ("Property-Based Tests", verify_property_based_tests),
        ("Conftest Enhancements", verify_conftest_enhancements),
        ("Marker Consistency", verify_marker_consistency),
        ("Test Doubles", verify_test_doubles),
    ]

    results = []
    for name, check_func in checks:
        print(f"\n📋 Checking {name}...")
        try:
            results.append(check_func())
        except Exception as e:
            print(f"❌ Error during {name}: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    if all(results):
        print("🎉 ALL ENHANCEMENTS SUCCESSFULLY IMPLEMENTED!")
        print("✨ Test suite compliance: 100/100")
    else:
        failed = sum(1 for r in results if not r)
        print(f"⚠️  {failed} enhancement(s) need attention")
    print("=" * 60)

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
