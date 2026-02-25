#!/usr/bin/env python3
"""Test runner for shotbot with marker-based test execution support.

Examples:
    python run_tests.py                    # Run all tests
    python run_tests.py -m unit            # Run only unit tests
    python run_tests.py -m "not slow"      # Run all tests except slow ones
    python run_tests.py -m "unit and qt"   # Run unit tests that use Qt
    python run_tests.py -m integration     # Run only integration tests
    python run_tests.py --unit             # Shortcut for -m unit
    python run_tests.py --fast             # Shortcut for -m "not slow"
    python run_tests.py --qt               # Shortcut for -m qt
    python run_tests.py --cov              # Run with coverage

"""

# Standard library imports
import argparse
import os
import sys
from pathlib import Path

# Third-party imports
import pytest


# Set up paths - go up 2 levels from tests/utilities/ to project root
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# Set Qt to run in offscreen mode to prevent GUI popups during tests
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_LOGGING_RULES"] = "*.debug=false"  # Reduce Qt debug output
# Set Qt API for pytest-qt
os.environ["PYTEST_QT_API"] = "pyside6"


def parse_arguments():
    """Parse command line arguments for test execution."""
    parser = argparse.ArgumentParser(
        description="Run shotbot tests with marker support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run all tests
  %(prog)s -m unit            # Run only unit tests
  %(prog)s -m "not slow"      # Run all tests except slow ones
  %(prog)s -m "unit and qt"   # Run unit tests that use Qt
  %(prog)s --unit             # Shortcut for -m unit
  %(prog)s --fast             # Shortcut for -m "not slow"
  %(prog)s --qt               # Shortcut for -m qt
  %(prog)s --cov              # Run with coverage
        """,
    )

    # Marker options
    parser.add_argument(
        "-m",
        "--marker",
        help="Run tests matching given mark expression (e.g., 'unit', 'not slow', 'unit and qt')",
    )

    # Shortcut options
    parser.add_argument(
        "--unit", action="store_true", help="Run only unit tests (shortcut for -m unit)"
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run only integration tests (shortcut for -m integration)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run fast tests only (shortcut for -m 'not slow')",
    )
    parser.add_argument(
        "--slow", action="store_true", help="Run slow tests only (shortcut for -m slow)"
    )
    parser.add_argument(
        "--qt", action="store_true", help="Run Qt tests only (shortcut for -m qt)"
    )

    # Coverage option
    parser.add_argument(
        "--cov", action="store_true", help="Run with coverage reporting"
    )

    # Verbose option
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output (default: True)"
    )

    # Test paths and pytest arguments
    parser.add_argument(
        "paths",
        nargs="*",
        default=["tests/"],
        help="Test paths to run (default: tests/)",
    )

    # Allow unknown arguments to be passed through to pytest
    args, unknown_args = parser.parse_known_args()
    args.pytest_args = unknown_args

    return args


def build_pytest_args(args):
    """Build pytest arguments from parsed command line arguments."""
    pytest_args = [
        "-v",  # Always verbose for now
        "--tb=short",
        "-p",
        "no:xvfb",  # Keep xvfb disabled for WSL compatibility
    ]

    # Handle marker selection
    marker_expr = None

    if args.marker:
        marker_expr = args.marker
    elif args.unit:
        marker_expr = "unit"
    elif args.integration:
        marker_expr = "integration"
    elif args.fast:
        marker_expr = "not slow"
    elif args.slow:
        marker_expr = "slow"
    elif args.qt:
        marker_expr = "qt"

    if marker_expr:
        pytest_args.extend(["-m", marker_expr])

    # Add coverage options
    if args.cov:
        pytest_args.extend(
            [
                "--cov=.",
                "--cov-report=term-missing",
                "--cov-report=html:coverage_html",
            ]
        )

    # Add test paths
    pytest_args.extend(args.paths)

    # Add any additional pytest arguments
    if hasattr(args, "pytest_args") and args.pytest_args:
        pytest_args.extend(args.pytest_args)

    return pytest_args


def main() -> None:
    """Main entry point for test runner."""
    args = parse_arguments()
    pytest_args = build_pytest_args(args)

    # Debug print
    if os.environ.get("DEBUG_TESTS"):
        print(f"Parsed args: {args}")
        print(f"Final pytest args: {pytest_args}")

    # Print marker information if using markers
    if any([args.marker, args.unit, args.integration, args.fast, args.slow, args.qt]):
        marker_used = (
            args.marker
            or ("unit" if args.unit else "")
            or ("integration" if args.integration else "")
            or ("not slow" if args.fast else "")
            or ("slow" if args.slow else "")
            or ("qt" if args.qt else "")
        )
        print(f"Running tests with marker: {marker_used}")

    sys.exit(pytest.main(pytest_args))


if __name__ == "__main__":
    main()
