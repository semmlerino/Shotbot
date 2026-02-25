#!/usr/bin/env python3
"""Run the current integration test suite via pytest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run tests/integration with optional marker/path filters.",
    )
    parser.add_argument(
        "-m",
        "--marker",
        help="Pytest marker expression (for example: real_subprocess or 'not slow').",
    )
    parser.add_argument(
        "-k",
        "--keyword",
        help="Pytest -k keyword expression.",
    )
    parser.add_argument(
        "-n",
        "--workers",
        default="auto",
        help="xdist worker count (default: auto). Use 0 to disable parallelism.",
    )
    parser.add_argument(
        "--dist",
        default="loadgroup",
        help="xdist distribution mode (default: loadgroup).",
    )
    parser.add_argument(
        "--maxfail",
        type=int,
        default=1,
        help="Stop after this many failures (default: 1).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["tests/integration"],
        help="Optional specific integration paths/files.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[2]

    cmd: list[str] = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "--tb=short",
        "--maxfail",
        str(args.maxfail),
    ]

    if args.workers != "0":
        cmd.extend(["-n", str(args.workers), "--dist", args.dist])
    if args.marker:
        cmd.extend(["-m", args.marker])
    if args.keyword:
        cmd.extend(["-k", args.keyword])

    cmd.extend(args.paths)

    print("Running integration suite:")
    print(" ".join(cmd))

    result = subprocess.run(
        cmd,
        cwd=project_root,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
