#!/usr/bin/env python3
"""Run the current canonical lint and type-check commands for Shotbot."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECKS = [
    (["uv", "run", "ruff", "format", "--check", "."], "Ruff formatting check"),
    (["uv", "run", "ruff", "check", "."], "Ruff lint check"),
    (["uv", "run", "basedpyright"], "Basedpyright type check"),
]


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return whether it succeeded."""
    print(f"\n{'=' * 60}")
    print(description)
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)

    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    except FileNotFoundError as exc:
        print(f"Failed to run command: {exc}")
        return False

    return result.returncode == 0


def main() -> int:
    """Run the maintained lint and type-check sequence."""
    results = [run_command(cmd, description) for cmd, description in CHECKS]

    print(f"\n{'=' * 60}")
    print("Summary")
    print("=" * 60)
    print(f"Passed: {sum(results)}/{len(results)}")
    print("Canonical commands also live in README.md.")

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
