#!/usr/bin/env python3
"""
Test runner script for PyFFMPEG
Provides easy commands to run different test suites with coverage
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd: list[str], check: bool = True) -> int:
    """Run a command and return exit code"""
    print(f"Running: {' '.join(cmd)}")
    print("-" * 60)
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        print(f"\nCommand failed with exit code {result.returncode}")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="PyFFMPEG Test Runner")
    parser.add_argument(
        "suite",
        nargs="?",
        default="all",
        choices=["all", "unit", "integration", "coverage", "quick"],
        help="Test suite to run (default: all)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--no-cov",
        action="store_true",
        help="Disable coverage reporting"
    )
    parser.add_argument(
        "--module", "-m",
        help="Run tests for specific module (e.g., file_list_widget)"
    )
    parser.add_argument(
        "--failed-first", "-f",
        action="store_true",
        help="Run failed tests first"
    )
    parser.add_argument(
        "--pdb",
        action="store_true",
        help="Drop into debugger on failures"
    )
    
    args = parser.parse_args()
    
    # Base pytest command
    cmd = [sys.executable, "-m", "pytest"]
    
    # Add verbosity
    if args.verbose:
        cmd.append("-vv")
    else:
        cmd.append("-v")
    
    # Add failed first
    if args.failed_first:
        cmd.append("--failed-first")
    
    # Add debugger
    if args.pdb:
        cmd.append("--pdb")
    
    # Coverage options
    if not args.no_cov and args.suite != "quick":
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
    if args.suite == "unit" or (args.suite == "all" and not args.module):
        cmd.append("tests/unit")
    elif args.suite == "integration":
        cmd.append("tests/integration")
    elif args.suite == "quick":
        # Quick tests - no coverage, stop on first failure
        cmd.extend(["-x", "--tb=short"])
        if args.module:
            cmd.append(f"tests/unit/test_{args.module}.py")
        else:
            cmd.append("tests/unit")
    elif args.suite == "coverage":
        # Full coverage report
        cmd.extend(["--cov-report=html", "--cov-report=term"])
        cmd.append("tests/")
    
    # Run specific module tests
    if args.module and args.suite not in ["quick"]:
        test_file = Path(f"tests/unit/test_{args.module}.py")
        if test_file.exists():
            cmd = [c for c in cmd if not c.startswith("tests/")]  # Remove test path
            cmd.append(str(test_file))
        else:
            print(f"Error: Test file not found: {test_file}")
            return 1
    
    # Print info
    print("PyFFMPEG Test Runner")
    print("=" * 60)
    print(f"Suite: {args.suite}")
    if args.module:
        print(f"Module: {args.module}")
    print(f"Coverage: {'disabled' if args.no_cov else 'enabled'}")
    print()
    
    # Run tests
    exit_code = run_command(cmd)
    
    # Print coverage report location
    if not args.no_cov and exit_code == 0 and args.suite != "quick":
        print("\n" + "=" * 60)
        print("Coverage report generated:")
        print("  - Terminal: See above")
        print("  - HTML: coverage_html/index.html")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())