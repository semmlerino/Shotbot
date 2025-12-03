#!/usr/bin/env python3
"""Test different parser optimization strategies."""

# Standard library imports
import re
import time

# Local application imports
from config import Config
from optimized_shot_parser import ParseResult


# Global pre-compiled pattern (fastest approach)
_GLOBAL_WS_PATTERN = re.compile(
    rf"workspace\s+({re.escape(Config.SHOWS_ROOT)}/([^/]+)/shots/([^/]+)/([^/]+))"
)


def parse_workspace_line_global(line: str) -> ParseResult | None:
    """Parser using global pre-compiled regex."""
    match = _GLOBAL_WS_PATTERN.search(line)
    if not match:
        return None

    workspace_path, show, sequence, shot_dir = match.groups()

    # Most common case first (85%)
    if shot_dir.startswith(sequence) and "_" in shot_dir:
        seq_len = len(sequence)
        if shot_dir[seq_len : seq_len + 1] == "_":
            return ParseResult(show, sequence, shot_dir[seq_len + 1 :], workspace_path)

    # Fallback cases
    underscore_pos = shot_dir.rfind("_")
    if underscore_pos > 0:
        return ParseResult(
            show, sequence, shot_dir[underscore_pos + 1 :], workspace_path
        )

    return ParseResult(show, sequence, shot_dir, workspace_path)


def parse_workspace_line_inline(line: str) -> ParseResult | None:
    """Parser with all operations inlined."""
    # Check for workspace prefix
    if not line.startswith("workspace "):
        return None

    # Find the shows root
    shows_root = Config.SHOWS_ROOT
    start = line.find(shows_root)
    if start == -1:
        return None

    # Extract the path part
    path = line[start:].rstrip()

    # Manual parsing (avoiding regex entirely)
    # Expected format: /shows/SHOW/shots/SEQUENCE/SHOT_DIR
    parts = path[len(shows_root) :].strip("/").split("/")
    if len(parts) < 4:
        return None

    show = parts[0]
    if parts[1] != "shots":
        return None
    sequence = parts[2]
    shot_dir = parts[3]
    workspace_path = f"{shows_root}/{show}/shots/{sequence}/{shot_dir}"

    # Extract shot name
    if shot_dir.startswith(sequence) and "_" in shot_dir:
        seq_len = len(sequence)
        if shot_dir[seq_len : seq_len + 1] == "_":
            return ParseResult(show, sequence, shot_dir[seq_len + 1 :], workspace_path)

    underscore_pos = shot_dir.rfind("_")
    if underscore_pos > 0:
        return ParseResult(
            show, sequence, shot_dir[underscore_pos + 1 :], workspace_path
        )

    return ParseResult(show, sequence, shot_dir, workspace_path)


def benchmark_all_approaches(iterations: int = 100000) -> None:
    """Benchmark all parsing approaches."""
    test_lines = [
        f"workspace {Config.SHOWS_ROOT}/demo/shots/seq01/seq01_0010",
        f"workspace {Config.SHOWS_ROOT}/broken_eggs/shots/BRX/BRX_166",
        f"workspace {Config.SHOWS_ROOT}/gator/shots/012/012_DC",
        f"workspace {Config.SHOWS_ROOT}/jack_ryan/shots/100/100_0010",
        f"workspace {Config.SHOWS_ROOT}/show_abc/shots/seq05/seq05_0230",
    ]

    # Test global regex approach
    start = time.perf_counter()
    for _ in range(iterations):
        for line in test_lines:
            parse_workspace_line_global(line)
    global_time = time.perf_counter() - start

    # Test inline approach (no regex)
    start = time.perf_counter()
    for _ in range(iterations):
        for line in test_lines:
            parse_workspace_line_inline(line)
    inline_time = time.perf_counter() - start

    # Import and test the current OptimizedShotParser
    # Local application imports
    from optimized_shot_parser import (
        OptimizedShotParser,
    )

    parser = OptimizedShotParser()

    start = time.perf_counter()
    for _ in range(iterations):
        for line in test_lines:
            parser.parse_workspace_line(line)
    class_time = time.perf_counter() - start

    # Calculate ops/sec
    total_ops = iterations * len(test_lines)

    print("Performance Comparison:")
    print(f"Global regex:    {total_ops / global_time:,.0f} ops/s ({global_time:.3f}s)")
    print(f"Inline parsing:  {total_ops / inline_time:,.0f} ops/s ({inline_time:.3f}s)")
    print(f"Class-based:     {total_ops / class_time:,.0f} ops/s ({class_time:.3f}s)")
    print("\nTarget: 3,000,000 ops/s")
    print(
        f"Best approach: {'Global' if global_time < inline_time and global_time < class_time else 'Inline' if inline_time < class_time else 'Class'}"
    )

    # Verify correctness
    print("\nCorrectness check:")
    for line in test_lines[:2]:
        result1 = parse_workspace_line_global(line)
        result2 = parse_workspace_line_inline(line)
        result3 = parser.parse_workspace_line(line)
        assert result1 == result3, f"Global mismatch: {result1} != {result3}"
        assert result2 == result3, f"Inline mismatch: {result2} != {result3}"
    print("✓ All approaches produce identical results")


if __name__ == "__main__":
    print("Testing different parser optimization strategies...\n")
    benchmark_all_approaches(50000)
