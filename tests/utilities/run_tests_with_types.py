#!/usr/bin/env python3
"""Enhanced test runner with type checking for shotbot.

This script runs comprehensive testing including:
1. Type checking with basedpyright
2. Test execution with coverage
3. Type-safe test validation
"""

from __future__ import annotations

# Standard library imports
import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> tuple[bool, str]:
    """Run a command and return success status and output."""
    print(f"🔍 {description}...")
    try:
        result = subprocess.run(
            cmd,
            check=False, capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            print(f"✅ {description} passed")
            return True, result.stdout
        print(f"❌ {description} failed:")
        print(result.stderr)
        return False, result.stderr

    except subprocess.TimeoutExpired:
        print(f"⏰ {description} timed out")
        return False, "Command timed out"
    except Exception as e:
        print(f"💥 {description} crashed: {e}")
        return False, str(e)


def check_type_safety() -> bool:
    """Run type checking on test files."""
    # Check if basedpyright is available
    try:
        subprocess.run(["basedpyright", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  basedpyright not found, skipping type checking")
        return True

    # Run type checking on tests
    success, _output = run_command(["basedpyright", "tests/"], "Type checking tests")

    if not success:
        print("Type checking failed. Please fix type errors before running tests.")
        return False

    return True


def run_tests_with_coverage() -> bool:
    """Run pytest with coverage reporting."""
    # Set up environment
    env = os.environ.copy()
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_LOGGING_RULES": "*.debug=false",
            "PYTEST_QT_API": "pyside6",
        }
    )

    args = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "--tb=short",
        "-p",
        "no:xvfb",
        "--cov=.",
        "--cov-report=term-missing",
        "--cov-report=html",
        "--cov-config=.coveragerc",
        "tests/",
    ]

    success, _output = run_command(args, "Running tests with coverage")
    return success


def validate_test_types() -> bool:
    """Validate that tests follow type safety guidelines."""
    print("🔍 Validating test type safety...")

    issues = []
    test_files = list(Path("tests/unit").glob("test_*.py"))

    for test_file in test_files:
        content = test_file.read_text()

        # Check for missing type annotations on test methods
        if "def test_" in content:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if (
                    line.strip().startswith("def test_")
                    and ") -> None:" not in line
                    and "def test_" in line
                    and ":" in line
                ):
                    issues.append(
                        f"{test_file.name}:{i + 1} - Missing return type annotation"
                    )

        # Check for proper type: ignore usage
        if "# type: ignore" in content and "# pyright: ignore[" not in content:
            issues.append(
                f"{test_file.name} - Use pyright-specific ignores instead of generic type: ignore"
            )

    if issues:
        print("⚠️  Type safety validation issues found:")
        for issue in issues:
            print(f"  - {issue}")
        return False

    print("✅ Test type safety validation passed")
    return True


def main() -> int:
    """Main test runner."""
    print("🧪 Running comprehensive test suite with type checking...")

    # Set working directory
    os.chdir(Path(__file__).parent)

    all_passed = True

    # 1. Type checking
    if not check_type_safety():
        all_passed = False

    # 2. Test type validation
    if not validate_test_types():
        all_passed = False

    # 3. Run tests
    if not run_tests_with_coverage():
        all_passed = False

    if all_passed:
        print("\n🎉 All checks passed! Code is ready for commit.")
        return 0
    print("\n❌ Some checks failed. Please address the issues above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
