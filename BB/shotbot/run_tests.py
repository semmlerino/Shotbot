#!/usr/bin/env python3
"""Test runner for shotbot."""

import os
import sys
from pathlib import Path

import pytest

# Set up paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# Disable xvfb plugin to avoid WSL issues
# Add coverage if requested
args = [
    "tests/",
    "-v",
    "--tb=short",
    "-p",
    "no:xvfb",
]

# Add coverage options if --cov is in arguments
if "--cov" in sys.argv:
    args.extend(
        [
            "--cov=.",
            "--cov-report=term-missing",
            "--cov-report=html",
            "--cov-config=.coveragerc",
        ]
    )

# Filter out script name and pass remaining arguments
test_args = sys.argv[1:] if len(sys.argv) > 1 else []

# Debug print
if os.environ.get("DEBUG_TESTS"):
    print(f"Base args: {args}")
    print(f"Test args: {test_args}")
    print(f"Final args: {args + test_args}")

sys.exit(pytest.main(args + test_args))
