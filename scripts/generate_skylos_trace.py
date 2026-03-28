"""Generate .skylos_trace by running tests with incremental trace saving.

Skylos's built-in ``--trace`` mode installs a process-wide profile hook and
persists its trace data on process exit. In larger GUI-heavy or C-extension-
heavy suites, a single crash or wedged process can lose the entire trace.

This wrapper reduces that risk by:
1. Using pytest's own collection so tracing matches the real test suite
2. Running each test file in its own subprocess with the tracer active
3. Saving a per-file partial trace in each subprocess
4. Merging the surviving partial traces into ``.skylos_trace``
5. Failing non-zero by default when any file times out or crashes

Usage:
    uv run python scripts/generate_skylos_trace.py
    uv run python scripts/generate_skylos_trace.py --resume
    uv run python scripts/generate_skylos_trace.py --per-file-timeout 0
    uv run python scripts/generate_skylos_trace.py --markexpr "legacy or not legacy"
    uv run python scripts/generate_skylos_trace.py --include-default-pass --markexpr "legacy"
    uv run python scripts/generate_skylos_trace.py --markexpr "legacy" --markexpr "tutorial"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = PROJECT_ROOT / ".skylos_traces"
FINAL_TRACE = PROJECT_ROOT / ".skylos_trace"
FAILURE_MANIFEST = PROJECT_ROOT / ".skylos_trace_failures.json"
DEFAULT_PYTEST_TARGET = "tests"
DEFAULT_PER_FILE_TIMEOUT = 300.0
DEFAULT_INTERNAL_ERROR_RETRIES = 1
OUTPUT_TAIL_LINES = 40
OUTPUT_TAIL_CHARS = 4000


@dataclass(frozen=True)
class ScriptOptions:
    resume: bool
    allow_partial: bool
    per_file_timeout: float | None
    include_default_pass: bool
    markexprs: tuple[str, ...]


@dataclass(frozen=True)
class TraceRunResult:
    exit_code: int
    traced_count: int | None
    stdout_tail: str
    stderr_tail: str


def parse_args(argv: list[str]) -> ScriptOptions:
    """Parse CLI options for trace generation."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate .skylos_trace by tracing each collected test file in its "
            "own subprocess."
        )
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing per-file traces when they are still valid.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit 0 even if some test files time out or crash.",
    )
    parser.add_argument(
        "--per-file-timeout",
        type=float,
        default=DEFAULT_PER_FILE_TIMEOUT,
        help=(
            "Kill a traced test-file subprocess after N seconds. Use 0 to disable "
            f"the outer timeout (default: {DEFAULT_PER_FILE_TIMEOUT:g}s)."
        ),
    )
    parser.add_argument(
        "--include-default-pass",
        action="store_true",
        help=(
            "When --markexpr is repeated, also keep the unfiltered collection pass "
            "instead of replacing it."
        ),
    )
    parser.add_argument(
        "--markexpr",
        action="append",
        default=[],
        help=(
            "Add a pytest -m expression for collection and traced runs. Repeat "
            "this flag to merge multiple marker-specific passes into one "
            ".skylos_trace."
        ),
    )

    args = parser.parse_args(argv)
    per_file_timeout = None if args.per_file_timeout <= 0 else args.per_file_timeout
    return ScriptOptions(
        resume=args.resume,
        allow_partial=args.allow_partial,
        per_file_timeout=per_file_timeout,
        include_default_pass=args.include_default_pass,
        markexprs=tuple(args.markexpr),
    )


def pytest_run_args(markexpr: str | None) -> list[str]:
    """Return pytest args used for each traced test-file run."""
    if not markexpr:
        return []
    return ["-m", markexpr]


def pytest_collect_args(markexpr: str | None) -> list[str]:
    """Return pytest args used for collection."""
    args = [DEFAULT_PYTEST_TARGET]
    args.extend(pytest_run_args(markexpr))
    return args


def selected_markexprs(options: ScriptOptions) -> tuple[str | None, ...]:
    """Return the ordered set of trace passes to run."""
    selected: list[str | None] = []
    seen: set[str | None] = set()

    if options.include_default_pass or not options.markexprs:
        selected.append(None)
        seen.add(None)

    for markexpr in options.markexprs:
        if markexpr not in seen:
            selected.append(markexpr)
            seen.add(markexpr)

    return tuple(selected)


def format_markexpr(markexpr: str | None) -> str:
    """Return a readable label for a trace pass."""
    if markexpr is None:
        return "default collection"
    return f'-m "{markexpr}"'


def markexpr_filename_suffix(markexpr: str | None) -> str:
    """Return a stable filename suffix for a marker-specific trace pass."""
    if markexpr is None:
        return ""

    readable = "".join(ch if ch.isalnum() else "_" for ch in markexpr)
    readable = "_".join(part for part in readable.split("_") if part)
    if not readable:
        readable = "markexpr"
    readable = readable[:32].rstrip("_")
    digest = hashlib.sha1(markexpr.encode("utf-8")).hexdigest()[:8]
    return f"__{readable}__{digest}"


def discover_test_files(markexpr: str | None) -> list[Path]:
    """Use pytest's collector so tracing matches the real configured suite."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            *pytest_collect_args(markexpr),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode not in (0, 5):
        detail = (
            result.stderr.strip() or result.stdout.strip() or "unknown collection error"
        )
        message = f"pytest collection failed: {detail}"
        raise RuntimeError(message)

    files: set[Path] = set()
    for line in result.stdout.splitlines():
        node_path = line.split("::", 1)[0].strip()
        if not node_path.endswith(".py"):
            continue
        path = Path(node_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.is_file():
            files.add(path.resolve())

    if not files:
        message = "pytest collection returned no test files"
        raise RuntimeError(message)

    return sorted(files)


def trace_output_path(test_file: Path, markexpr: str | None) -> Path:
    """Return a collision-safe trace filename for a test file."""
    rel = test_file.resolve().relative_to(PROJECT_ROOT)
    slug = "__".join(rel.with_suffix("").parts)
    return TRACE_DIR / f"{slug}{markexpr_filename_suffix(markexpr)}.json"


def read_trace_count(trace_output: Path) -> int | None:
    """Return the traced-call count for a partial trace, or None if invalid."""
    if not trace_output.exists():
        return None

    try:
        data = json.loads(trace_output.read_text())
    except json.JSONDecodeError:
        return None

    calls = data.get("calls")
    if not isinstance(calls, list):
        return None
    return len(calls)


def summarize_output(text: str | None) -> str:
    """Return a readable tail of subprocess output for failure diagnostics."""
    if not text:
        return ""

    lines = text.strip().splitlines()
    if not lines:
        return ""

    tail = "\n".join(lines[-OUTPUT_TAIL_LINES:])
    if len(tail) <= OUTPUT_TAIL_CHARS:
        return tail
    return tail[-OUTPUT_TAIL_CHARS:]


def run_traced_test(
    test_file: Path,
    trace_output: Path,
    per_file_timeout: float | None,
    markexpr: str | None,
) -> TraceRunResult:
    """Run a single test file with call tracing in a subprocess.

    Returns exit status, trace count, and captured output tails.
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
    ret = pytest.main(["-q", "--tb=no", "--no-header", *{pytest_run_args(markexpr)!r}, {str(test_file)!r}])
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
        timeout=per_file_timeout,
        check=False,
    )

    return TraceRunResult(
        exit_code=result.returncode,
        traced_count=read_trace_count(trace_output),
        stdout_tail=summarize_output(result.stdout),
        stderr_tail=summarize_output(result.stderr),
    )


def should_retry_pytest_internal_error(result: TraceRunResult, attempt: int) -> bool:
    """Return whether a traced run should be retried after a pytest internal error."""
    return (
        attempt < DEFAULT_INTERNAL_ERROR_RETRIES
        and result.exit_code == 3
        and "INTERNALERROR>" in result.stdout_tail
    )


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


def load_previous_failed_trace_outputs() -> set[Path]:
    """Return trace outputs referenced by the previous failure manifest."""
    if not FAILURE_MANIFEST.exists():
        return set()

    try:
        raw = json.loads(FAILURE_MANIFEST.read_text())
    except (OSError, json.JSONDecodeError):
        return set()

    if not isinstance(raw, list):
        return set()

    failed_outputs: set[Path] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        trace_output = item.get("trace_output")
        if isinstance(trace_output, str):
            failed_outputs.add(Path(trace_output))
    return failed_outputs


def write_failure_manifest(failures: list[dict[str, object]]) -> None:
    """Persist structured diagnostics for non-clean trace runs."""
    if not failures:
        FAILURE_MANIFEST.unlink(missing_ok=True)
        return

    FAILURE_MANIFEST.write_text(json.dumps(failures, indent=2))


def main() -> None:
    options = parse_args(sys.argv[1:])
    TRACE_DIR.mkdir(exist_ok=True)
    previous_failed_trace_outputs = load_previous_failed_trace_outputs()

    trace_passes: list[tuple[str | None, list[Path]]] = []
    for markexpr in selected_markexprs(options):
        try:
            test_files = discover_test_files(markexpr)
        except RuntimeError as exc:
            print(f"{format_markexpr(markexpr)}: {exc}", file=sys.stderr)
            sys.exit(1)
        trace_passes.append((markexpr, test_files))

    expected_trace_files = {
        trace_output_path(test_file, markexpr)
        for markexpr, test_files in trace_passes
        for test_file in test_files
    }

    for old in TRACE_DIR.glob("*.json"):
        if not options.resume or old not in expected_trace_files:
            old.unlink()

    timeout_label = (
        "disabled"
        if options.per_file_timeout is None
        else f"{options.per_file_timeout:g}s"
    )
    total_targets = sum(len(test_files) for _, test_files in trace_passes)
    if len(trace_passes) == 1:
        print(f"Found {total_targets} test files (per-file timeout: {timeout_label})")
    else:
        print(
            f"Found {total_targets} test-file passes across {len(trace_passes)} "
            f"collections (per-file timeout: {timeout_label})"
        )
        for markexpr, test_files in trace_passes:
            print(f"  {format_markexpr(markexpr)}: {len(test_files)} files")

    passed = 0
    failed = 0
    errored = 0
    timed_out = 0
    skipped = 0
    failures: list[dict[str, object]] = []
    processed_targets = 0

    for markexpr, test_files in trace_passes:
        pass_label = format_markexpr(markexpr)
        if len(trace_passes) > 1:
            print(f"\n== Trace pass: {pass_label} ==")

        for test_file in test_files:
            processed_targets += 1
            rel = test_file.relative_to(PROJECT_ROOT)
            trace_out = trace_output_path(test_file, markexpr)
            target_label = (
                f"{rel} ({pass_label})" if len(trace_passes) > 1 else str(rel)
            )

            if options.resume and trace_out.exists():
                if trace_out not in previous_failed_trace_outputs:
                    existing_count = read_trace_count(trace_out)
                    if existing_count is not None:
                        print(
                            f"  [{processed_targets}/{total_targets}] {target_label} ... "
                            f"SKIP ({existing_count} calls)"
                        )
                        skipped += 1
                        continue
                trace_out.unlink()

            print(
                f"  [{processed_targets}/{total_targets}] {target_label} ... ",
                end="",
                flush=True,
            )

            try:
                attempt = 0
                while True:
                    result = run_traced_test(
                        test_file,
                        trace_out,
                        options.per_file_timeout,
                        markexpr,
                    )
                    if not should_retry_pytest_internal_error(result, attempt):
                        break
                    attempt += 1
                    print("PYTEST INTERNAL ERROR (retrying once)")
                    print(
                        f"  [{processed_targets}/{total_targets}] {target_label} ... ",
                        end="",
                        flush=True,
                    )

                if result.traced_count is None:
                    if result.exit_code < 0:
                        print(f"CRASHED (signal {-result.exit_code}, no trace data)")
                    else:
                        print(f"NO TRACE (exit {result.exit_code})")
                    errored += 1
                    failures.append(
                        {
                            "file": str(rel),
                            "markexpr": markexpr,
                            "status": "crashed_no_trace"
                            if result.exit_code < 0
                            else "no_trace",
                            "exit_code": result.exit_code,
                            "signal": -result.exit_code
                            if result.exit_code < 0
                            else None,
                            "trace_output": str(trace_out),
                            "had_trace": False,
                            "traced_count": None,
                            "stdout_tail": result.stdout_tail,
                            "stderr_tail": result.stderr_tail,
                        }
                    )
                elif result.exit_code == 0:
                    print(f"OK ({result.traced_count} calls)")
                    passed += 1
                elif result.exit_code == 1:
                    print(f"TESTS FAILED ({result.traced_count} calls)")
                    failed += 1
                    failures.append(
                        {
                            "file": str(rel),
                            "markexpr": markexpr,
                            "status": "tests_failed",
                            "exit_code": result.exit_code,
                            "signal": None,
                            "trace_output": str(trace_out),
                            "had_trace": True,
                            "traced_count": result.traced_count,
                            "stdout_tail": result.stdout_tail,
                            "stderr_tail": result.stderr_tail,
                        }
                    )
                else:
                    print(
                        f"PYTEST ERROR (exit {result.exit_code}, "
                        f"{result.traced_count} calls)"
                    )
                    errored += 1
                    failures.append(
                        {
                            "file": str(rel),
                            "markexpr": markexpr,
                            "status": "pytest_error",
                            "exit_code": result.exit_code,
                            "signal": -result.exit_code
                            if result.exit_code < 0
                            else None,
                            "trace_output": str(trace_out),
                            "had_trace": True,
                            "traced_count": result.traced_count,
                            "stdout_tail": result.stdout_tail,
                            "stderr_tail": result.stderr_tail,
                        }
                    )
            except subprocess.TimeoutExpired as exc:
                print("TIMEOUT")
                timed_out += 1
                timed_out_count = read_trace_count(trace_out)
                failures.append(
                    {
                        "file": str(rel),
                        "markexpr": markexpr,
                        "status": "timeout",
                        "exit_code": None,
                        "signal": None,
                        "trace_output": str(trace_out),
                        "had_trace": timed_out_count is not None,
                        "traced_count": timed_out_count,
                        "stdout_tail": summarize_output(exc.stdout),
                        "stderr_tail": summarize_output(exc.stderr),
                    }
                )

    # Merge all partial traces
    unique_count = merge_traces(TRACE_DIR, FINAL_TRACE)
    write_failure_manifest(failures)

    print("\n--- Results ---")
    if skipped:
        print(f"  Skipped (cached): {skipped}")
    print(
        "  Pass targets: "
        f"{passed} OK, {failed} test-failed, {errored} errored, "
        f"{timed_out} timed out, {total_targets} total"
    )
    print(f"  Traced calls: {unique_count} unique functions")
    print(f"  Output: {FINAL_TRACE}")
    if failures:
        print(f"  Failure log: {FAILURE_MANIFEST}")

    incomplete = errored + timed_out
    if incomplete:
        detail = (
            f"\nIncomplete trace: {incomplete} test files did not finish cleanly. "
            "Use --allow-partial to keep the merged trace without failing the run."
        )
        if options.allow_partial:
            print(detail)
        else:
            print(detail, file=sys.stderr)
            sys.exit(1)

    print(
        "\nNow run: uv run skylos . --table --exclude-folder tests "
        "--exclude-folder archive --confidence 80"
    )


if __name__ == "__main__":
    main()
