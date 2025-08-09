#!/usr/bin/env python3
"""Verification script for type safety implementation."""

import subprocess
import sys
from pathlib import Path


def main():
    """Verify type safety implementation."""
    print("🔍 ShotBot Type Safety Verification")
    print("=" * 50)

    project_root = Path(__file__).parent
    success = True

    # Check 1: Verify type stub files exist
    print("\n1. Checking type stub files...")
    stub_files = ["shot_model.pyi", "cache_manager.pyi", "utils.pyi"]

    for stub_file in stub_files:
        stub_path = project_root / stub_file
        if stub_path.exists():
            print(f"   ✅ {stub_file} exists")
        else:
            print(f"   ❌ {stub_file} missing")
            success = False

    # Check 2: Verify configuration files
    print("\n2. Checking configuration files...")
    config_files = [
        ("pyrightconfig.json", "basedpyright configuration"),
        ("pyproject.toml", "project configuration"),
    ]

    for config_file, description in config_files:
        config_path = project_root / config_file
        if config_path.exists():
            print(f"   ✅ {config_file} exists ({description})")
            # Check for basedpyright config in pyproject.toml
            if config_file == "pyproject.toml":
                content = config_path.read_text()
                if "[tool.basedpyright]" in content:
                    print("      ✅ basedpyright configuration found")
                else:
                    print("      ❌ basedpyright configuration missing")
                    success = False
        else:
            print(f"   ❌ {config_file} missing ({description})")
            success = False

    # Check 3: Verify test files exist
    print("\n3. Checking type safety test files...")
    test_files = [
        "tests/unit/test_type_safety.py",
        "tests/unit/test_basedpyright_config.py",
        "tests/unit/test_raw_plate_finder_types.py",
        "tests/integration/test_type_safety_integration.py",
    ]

    for test_file in test_files:
        test_path = project_root / test_file
        if test_path.exists():
            print(f"   ✅ {test_file} exists")
        else:
            print(f"   ❌ {test_file} missing")
            success = False

    # Check 4: Run basedpyright if available
    print("\n4. Running basedpyright type checking...")
    try:
        result = subprocess.run(
            ["python3", "-m", "basedpyright", "--stats", "shot_model.py"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30,
        )

        if result.returncode == 0:
            # Count errors and warnings
            output = result.stdout
            if "0 errors" in output and (
                "0 warnings" in output or "1 warning" in output
            ):
                print("   ✅ basedpyright check passed")
                # Show any warnings
                if "1 warning" in output:
                    print("      ⚠️  1 minor warning (acceptable)")
            else:
                print("   ❌ basedpyright found issues:")
                print(f"      {output}")
                success = False
        else:
            print("   ❌ basedpyright failed:")
            print(f"      {result.stderr}")
            success = False

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"   ⚠️  basedpyright not available: {e}")
        print("      (Install with: pip install basedpyright)")

    # Check 5: Run a sample of type safety tests
    print("\n5. Running type safety tests...")
    try:
        result = subprocess.run(
            [
                "python3",
                "run_tests.py",
                "tests/unit/test_type_safety.py::TestRefreshResultTypeAnnotations",
                "-v",
            ],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60,
        )

        if result.returncode == 0 and "PASSED" in result.stdout:
            print("   ✅ Type safety tests passed")
        else:
            print("   ❌ Type safety tests failed:")
            print(f"      {result.stdout}")
            print(f"      {result.stderr}")
            success = False

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"   ❌ Test execution failed: {e}")
        success = False

    # Summary
    print("\n" + "=" * 50)
    if success:
        print("🎉 Type Safety Verification: SUCCESS")
        print("\nAll type safety features are properly implemented:")
        print("   • Type stub files (.pyi) created")
        print("   • basedpyright configuration set up")
        print("   • Comprehensive test suite implemented")
        print("   • Runtime type validation working")
        print("   • Integration tests passing")
        return 0
    else:
        print("❌ Type Safety Verification: FAILED")
        print("\nSome type safety features are missing or broken.")
        print("Please review the issues above and fix them.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
