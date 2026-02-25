#!/usr/bin/env python3
"""Run performance tests via pytest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run tests/performance with pytest.")
    parser.add_argument(
        "-m",
        "--marker",
        default="performance",
        help="Marker expression (default: performance).",
    )
    parser.add_argument(
        "-k",
        "--keyword",
        help="Optional pytest -k expression.",
    )
    parser.add_argument(
        "--benchmark-only",
        action="store_true",
        help="Pass --benchmark-only to pytest (requires pytest-benchmark).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["tests/performance"],
        help="Optional specific performance paths/files.",
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
        "-m",
        args.marker,
    ]
    if args.keyword:
        cmd.extend(["-k", args.keyword])
    if args.benchmark_only:
        cmd.append("--benchmark-only")
    cmd.extend(args.paths)

    print("Running performance suite:")
    print(" ".join(cmd))

    result = subprocess.run(
        cmd,
        cwd=project_root,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
