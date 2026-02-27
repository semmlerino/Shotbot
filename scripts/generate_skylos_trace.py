"""Generate .skylos_trace by running tests with incremental trace saving.

PySide6/shiboken segfaults when sys.setprofile() is active during certain
C++ -> Python transitions (e.g., QImage.save()). Skylos's --trace flag sets
the profile hook globally and only saves at exit via a finally block, but a
segfault kills the process before finally runs — losing all trace data.

This script works around the issue by:
1. Running each test file in its own subprocess with the tracer active
2. Each subprocess saves a partial trace file immediately in its finally block
3. If a subprocess crashes (segfault), only that file's data is lost
4. The main process merges all partial traces into .skylos_trace

Usage:
    uv run python scripts/generate_skylos_trace.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = PROJECT_ROOT / ".skylos_traces"
FINAL_TRACE = PROJECT_ROOT / ".skylos_trace"


def discover_test_files() -> list[Path]:
    """Find all test files, excluding conftest and helpers."""
    test_dirs = [PROJECT_ROOT / "tests" / "unit", PROJECT_ROOT / "tests" / "integration"]
    files = []
    for d in test_dirs:
        if d.exists():
            files.extend(sorted(d.glob("test_*.py")))
    return files


def run_traced_test(test_file: Path, trace_output: Path) -> tuple[bool, int]:
    """Run a single test file with call tracing in a subprocess.

    Returns (success, traced_count).
    """
    script = textwrap.dedent(f"""\
import os, sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})
os.chdir({str(PROJECT_ROOT)!r})
from skylos.tracer import CallTracer

tracer = CallTracer(exclude_patterns=[
    "site-packages", "venv", ".venv", "pytest", "_pytest", "pluggy",
])
tracer.start()

ret = 0
try:
    import pytest
    ret = pytest.main(["-q", "--tb=no", "--no-header", {str(test_file)!r}])
finally:
    tracer.stop()
    tracer.save({str(trace_output)!r})

sys.exit(ret)
""")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )

    if trace_output.exists():
        try:
            data = json.loads(trace_output.read_text())
            return True, len(data.get("calls", []))
        except (json.JSONDecodeError, KeyError):
            return False, 0
    return False, 0


def merge_traces(trace_dir: Path, output: Path) -> int:
    """Merge all partial trace files into a single .skylos_trace."""
    all_calls: dict[tuple[str, str, int], int] = {}

    for partial in sorted(trace_dir.glob("*.json")):
        try:
            data = json.loads(partial.read_text())
            for call in data.get("calls", []):
                key = (call["file"], call["function"], call["line"])
                all_calls[key] = all_calls.get(key, 0) + call.get("count", 1)
        except (json.JSONDecodeError, KeyError):
            continue

    merged = {
        "version": 1,
        "calls": [
            {"file": f, "function": fn, "line": ln, "count": cnt}
            for (f, fn, ln), cnt in sorted(all_calls.items())
        ],
    }

    output.write_text(json.dumps(merged, indent=2))
    return len(all_calls)


def main() -> None:
    TRACE_DIR.mkdir(exist_ok=True)

    skip_existing = "--resume" in sys.argv

    if not skip_existing:
        # Clean old partial traces
        for old in TRACE_DIR.glob("*.json"):
            old.unlink()

    test_files = discover_test_files()
    print(f"Found {len(test_files)} test files")

    succeeded = 0
    crashed = 0
    skipped = 0
    total_traced = 0

    for i, test_file in enumerate(test_files, 1):
        rel = test_file.relative_to(PROJECT_ROOT)
        trace_out = TRACE_DIR / f"{test_file.stem}.json"

        if skip_existing and trace_out.exists():
            skipped += 1
            succeeded += 1
            continue

        print(f"  [{i}/{len(test_files)}] {rel} ... ", end="", flush=True)

        try:
            ok, count = run_traced_test(test_file, trace_out)
            if ok:
                print(f"OK ({count} calls)")
                succeeded += 1
                total_traced += count
            else:
                print("CRASHED (no trace data)")
                crashed += 1
        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            crashed += 1

    # Merge all partial traces
    unique_count = merge_traces(TRACE_DIR, FINAL_TRACE)

    print(f"\n--- Results ---")
    if skipped:
        print(f"  Skipped (cached): {skipped}")
    print(f"  Test files:  {succeeded} OK, {crashed} crashed, {len(test_files)} total")
    print(f"  Traced calls: {unique_count} unique functions")
    print(f"  Output: {FINAL_TRACE}")
    print(f"\nNow run: uv run skylos . --table --exclude-folder tests")


if __name__ == "__main__":
    main()
