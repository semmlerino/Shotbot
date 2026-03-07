#!/usr/bin/env python3
"""Compatibility wrapper for a maintained optimization-focused regression subset."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPTIMIZATION_TESTS = [
    "tests/unit/test_async_shot_loader.py",
    "tests/integration/test_incremental_caching_workflow.py",
    "tests/integration/test_cache_architecture_seams.py",
    "tests/integration/test_cache_merge_correctness.py",
]


def main() -> int:
    """Run a small maintained subset covering async and cache-heavy paths."""
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("QT_LOGGING_RULES", "*.debug=false")

    cmd = ["uv", "run", "pytest", *OPTIMIZATION_TESTS, "-v"]

    print("Running maintained optimization-focused regression subset")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Command: {' '.join(cmd)}")
    print("For full test policy, see README.md and UNIFIED_TESTING_V2.md.")

    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, check=False)
    except FileNotFoundError as exc:
        print(f"Failed to run command: {exc}")
        return 1

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
