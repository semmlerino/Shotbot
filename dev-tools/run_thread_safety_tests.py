#!/usr/bin/env python3
"""Compatibility wrapper for the maintained thread-safety test suites."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUICK_TESTS = [
    "tests/unit/test_zombie_thread_lifecycle.py",
]
DEFAULT_TESTS = [
    "tests/unit/test_zombie_thread_lifecycle.py",
    "tests/integration/test_shutdown_sequence.py",
    "tests/regression/test_process_pool_race.py",
    "tests/regression/test_subprocess_no_deadlock.py",
]


def build_command(args: argparse.Namespace) -> list[str]:
    """Build the pytest command for the selected mode."""
    verbosity_flag = "-vv" if args.verbose else "-v"

    if args.performance_only:
        return [
            "uv",
            "run",
            "pytest",
            "tests/performance/",
            "-m",
            "",
            verbosity_flag,
        ]

    selected_tests = QUICK_TESTS if args.quick else DEFAULT_TESTS
    return ["uv", "run", "pytest", *selected_tests, verbosity_flag]


def main() -> int:
    """Run maintained thread-safety coverage."""
    parser = argparse.ArgumentParser(
        description="Run maintained thread-safety-focused test suites"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a minimal smoke test for thread lifecycle handling",
    )
    parser.add_argument(
        "--performance-only",
        action="store_true",
        help="Run only the explicit performance test directory",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Increase pytest verbosity",
    )
    args = parser.parse_args()

    cmd = build_command(args)

    print("Running maintained thread-safety compatibility wrapper")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Command: {' '.join(cmd)}")
    print("Canonical threading guidance lives in docs/THREADING_ARCHITECTURE.md.")

    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    except FileNotFoundError as exc:
        print(f"Failed to run command: {exc}")
        return 1

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
