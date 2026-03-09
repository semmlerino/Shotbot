"""Cheap textual verification pass for Skylos dead-code candidates.

This script is intentionally conservative: it does not try to prove a symbol is
live or dead. It reads a Skylos JSON report, extracts candidate functions and
classes, then runs a quick ripgrep pass to find obvious textual references
before a human reviews or removes code.

Usage:
    uv run python scripts/verify_skylos_candidates.py /tmp/skylos_report.json
    uv run python scripts/verify_skylos_candidates.py /tmp/skylos_report.json --limit 40
    uv run python scripts/verify_skylos_candidates.py /tmp/skylos_report.json --category unused_functions
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATEGORIES = ("unused_functions", "unused_classes")


@dataclass(frozen=True)
class SearchMatch:
    path: Path
    line: int
    text: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a quick textual reference check for Skylos dead-code "
            "candidates using ripgrep."
        )
    )
    parser.add_argument(
        "report",
        type=Path,
        help="Path to a Skylos JSON report.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=PROJECT_ROOT,
        help=f"Project root to search (default: {PROJECT_ROOT}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of candidates to inspect (default: 25).",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=3,
        help="Maximum sample matches to print per candidate (default: 3).",
    )
    parser.add_argument(
        "--category",
        action="append",
        choices=sorted(DEFAULT_CATEGORIES),
        help=(
            "Skylos report category to inspect. Repeat to include multiple "
            "categories. Defaults to unused_functions and unused_classes."
        ),
    )
    return parser.parse_args(argv)


def load_report(path: Path) -> dict[str, object]:
    """Load a Skylos JSON report."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"failed to read report: {exc}"
        raise RuntimeError(msg) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"invalid JSON report: {exc}"
        raise RuntimeError(msg) from exc

    if not isinstance(data, dict):
        msg = "report root is not a JSON object"
        raise RuntimeError(msg)
    return data


def iter_candidates(
    report: dict[str, object], categories: tuple[str, ...], limit: int
) -> list[dict[str, object]]:
    """Return the first N candidates from the selected report categories."""
    candidates: list[dict[str, object]] = []

    for category in categories:
        raw = report.get(category, [])
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                enriched = dict(item)
                enriched["_category"] = category
                candidates.append(enriched)
                if len(candidates) >= limit:
                    return candidates

    return candidates


def rg_search(pattern: str, repo_root: Path) -> list[SearchMatch]:
    """Search Python files using ripgrep and return parsed matches."""
    if shutil.which("rg") is None:
        msg = "ripgrep (rg) is required for verification"
        raise RuntimeError(msg)

    result = subprocess.run(
        [
            "rg",
            "-n",
            "--glob",
            "*.py",
            pattern,
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or result.stdout.strip() or "unknown rg error"
        msg = f"ripgrep failed: {detail}"
        raise RuntimeError(msg)

    matches: list[SearchMatch] = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        path_str, line_str, text = parts
        try:
            line_no = int(line_str)
        except ValueError:
            continue
        matches.append(SearchMatch(Path(path_str), line_no, text.strip()))
    return matches


def build_search_patterns(candidate: dict[str, object]) -> list[tuple[str, str]]:
    """Return textual search patterns for a Skylos candidate."""
    simple_name = candidate.get("simple_name")
    kind = candidate.get("type")
    if not isinstance(simple_name, str) or not simple_name:
        return []

    escaped = re.escape(simple_name)
    if kind == "class":
        return [("name", rf"\b{escaped}\b")]
    if kind == "method":
        return [
            ("attribute-call", rf"\.{escaped}\("),
            ("bare-call", rf"\b{escaped}\("),
        ]
    return [("call", rf"\b{escaped}\(")]


def filter_definition_line(
    matches: list[SearchMatch], candidate: dict[str, object]
) -> list[SearchMatch]:
    """Remove the defining line for the candidate from textual matches."""
    file_value = candidate.get("file")
    line_value = candidate.get("line")
    if not isinstance(file_value, str) or not isinstance(line_value, int):
        return matches

    definition_path = Path(file_value).resolve()
    return [
        match
        for match in matches
        if not (match.path.resolve() == definition_path and match.line == line_value)
    ]


def verify_candidate(
    candidate: dict[str, object], repo_root: Path
) -> tuple[list[SearchMatch], list[str]]:
    """Return aggregated textual matches plus the patterns that were used."""
    all_matches: dict[tuple[Path, int, str], SearchMatch] = {}
    labels: list[str] = []

    for label, pattern in build_search_patterns(candidate):
        labels.append(label)
        for match in filter_definition_line(rg_search(pattern, repo_root), candidate):
            key = (match.path, match.line, match.text)
            all_matches[key] = match

    ordered = sorted(all_matches.values(), key=lambda m: (str(m.path), m.line, m.text))
    return ordered, labels


def main() -> None:
    args = parse_args(sys.argv[1:])
    categories = tuple(args.category or DEFAULT_CATEGORIES)
    report = load_report(args.report)
    candidates = iter_candidates(report, categories, args.limit)

    if not candidates:
        print("No candidates found for the selected categories.")
        return

    print(
        f"Checking {len(candidates)} candidates from {', '.join(categories)} "
        f"under {args.repo_root}"
    )

    definition_only = 0
    possible_refs = 0

    for candidate in candidates:
        matches, labels = verify_candidate(candidate, args.repo_root)
        full_name = candidate.get("full_name") or candidate.get("name") or "<unknown>"
        kind = candidate.get("type", "<unknown>")
        confidence = candidate.get("confidence", "?")
        basename = candidate.get("basename") or Path(str(candidate.get("file", ""))).name
        line = candidate.get("line", "?")
        pattern_info = ", ".join(labels) if labels else "no patterns"

        print(
            f"\n{full_name} [{kind}, confidence {confidence}] "
            f"{basename}:{line} ({pattern_info})"
        )

        if not matches:
            definition_only += 1
            print("  textual refs: none beyond the definition line")
            continue

        possible_refs += 1
        print(f"  textual refs: {len(matches)} possible external matches")
        for match in matches[: args.max_matches]:
            try:
                rel_path = match.path.resolve().relative_to(args.repo_root.resolve())
            except ValueError:
                rel_path = match.path
            print(f"  {rel_path}:{match.line}: {match.text}")
        if len(matches) > args.max_matches:
            print(f"  ... {len(matches) - args.max_matches} more matches")

    print(
        f"\nSummary: {definition_only} definition-only, "
        f"{possible_refs} with possible textual references"
    )


if __name__ == "__main__":
    main()
