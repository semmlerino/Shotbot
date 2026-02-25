#!/usr/bin/env python3
"""⚠️ ARCHIVED - PyFFMPEG Test Runner

This script is archived and was designed for an obsolete project (PyFFMPEG).

For current ShotBot testing, use:
  - pytest tests/           # Run all tests
  - pytest tests/ -n 2      # Parallel execution (faster)
  - pytest tests/ --cov=.   # With coverage

See UNIFIED_TESTING_V2.MD for comprehensive testing documentation.

---

Test runner script for PyFFMPEG
Provides easy commands to run different test suites with coverage
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import cast


def run_command(cmd: list[str], check: bool = True) -> int:
    """Run a command and return exit code"""
    print(f"Running: {' '.join(cmd)}")
    print("-" * 60)
    result = subprocess.run(cmd, check=False)
    if check and result.returncode != 0:
        print(f"\nCommand failed with exit code {result.returncode}")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="PyFFMPEG Test Runner")
    _ = parser.add_argument(
        "suite",
        nargs="?",
        default="all",
        choices=["all", "unit", "integration", "coverage", "quick"],
        help="Test suite to run (default: all)"
    )
    _ = parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    _ = parser.add_argument(
        "--no-cov",
        action="store_true",
        help="Disable coverage reporting"
    )
    _ = parser.add_argument(
        "--module", "-m",
        help="Run tests for specific module (e.g., file_list_widget)"
    )
    _ = parser.add_argument(
        "--failed-first", "-f",
        action="store_true",
        help="Run failed tests first"
    )
    _ = parser.add_argument(
        "--pdb",
        action="store_true",
        help="Drop into debugger on failures"
    )

    args = parser.parse_args()

    # Extract args with explicit casting for type safety
    verbose: bool = cast("bool", args.verbose)
    failed_first: bool = cast("bool", args.failed_first)
    pdb: bool = cast("bool", args.pdb)
    no_cov: bool = cast("bool", args.no_cov)
    suite: str = cast("str", args.suite)
    module: str | None = cast("str | None", args.module)

    # Base pytest command
    cmd = [sys.executable, "-m", "pytest"]

    # Add verbosity
    if verbose:
        cmd.append("-vv")
    else:
        cmd.append("-v")

    # Add failed first
    if failed_first:
        cmd.append("--failed-first")

    # Add debugger
    if pdb:
        cmd.append("--pdb")

    # Coverage options
    if not no_cov and suite != "quick":
        cmd.extend([
            "--cov=.",
            "--cov-exclude=tests/*",
            "--cov-exclude=venv/*",
            "--cov-exclude=__pycache__/*",
            "--cov-exclude=PyMPEG.py",
            "--cov-exclude=archive/*",
            "--cov-report=term-missing",
            "--cov-report=html:coverage_html"
        ])

    # Select test suite
    if suite == "unit" or (suite == "all" and not module):
        cmd.append("tests/unit")
    elif suite == "integration":
        cmd.append("tests/integration")
    elif suite == "quick":
        # Quick tests - no coverage, stop on first failure
        cmd.extend(["-x", "--tb=short"])
        if module:
            cmd.append(f"tests/unit/test_{module}.py")
        else:
            cmd.append("tests/unit")
    elif suite == "coverage":
        # Full coverage report
        cmd.extend(["--cov-report=html", "--cov-report=term"])
        cmd.append("tests/")

    # Run specific module tests
    if module and suite not in ["quick"]:
        test_file = Path(f"tests/unit/test_{module}.py")
        if test_file.exists():
            cmd = [c for c in cmd if not c.startswith("tests/")]  # Remove test path
            cmd.append(str(test_file))
        else:
            print(f"Error: Test file not found: {test_file}")
            return 1

    # Print info
    print("PyFFMPEG Test Runner")
    print("=" * 60)
    print(f"Suite: {suite}")
    if module:
        print(f"Module: {module}")
    print(f"Coverage: {'disabled' if no_cov else 'enabled'}")
    print()

    # Run tests
    exit_code = run_command(cmd)

    # Print coverage report location
    if not no_cov and exit_code == 0 and suite != "quick":
        print("\n" + "=" * 60)
        print("Coverage report generated:")
        print("  - Terminal: See above")
        print("  - HTML: coverage_html/index.html")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
