#!/usr/bin/env python3
"""Test regex pattern optimization performance."""

# Standard library imports
import re
import time

# Local application imports
from config import Config


def benchmark_regex_patterns():
    """Benchmark original vs optimized regex patterns."""

    shows_root_escaped = re.escape(Config.SHOWS_ROOT)

    # Original pattern with \w+
    original_pattern = re.compile(
        rf"workspace\s+({shows_root_escaped}/(\w+)/shots/(\w+)/(\w+_\w+))",
    )

    # Optimized pattern with [^/]+
    optimized_pattern = re.compile(
        rf"workspace\s+({shows_root_escaped}/([^/]+)/shots/([^/]+)/([^/]+))",
    )

    # Test data (realistic VFX workspace output)
    test_lines = [
        f"workspace {Config.SHOWS_ROOT}/demo/shots/seq01/seq01_0010",
        f"workspace {Config.SHOWS_ROOT}/broken_eggs/shots/BRX/BRX_166",
        f"workspace {Config.SHOWS_ROOT}/gator/shots/012/012_DC",
        f"workspace {Config.SHOWS_ROOT}/jack_ryan/shots/100/100_0010",
        f"workspace {Config.SHOWS_ROOT}/show_test/shots/seq_abc/seq_abc_4560",
        f"workspace {Config.SHOWS_ROOT}/project_x/shots/finale/finale_9999",
    ] * 100  # Multiply for more data

    iterations = 1000

    # Benchmark original pattern
    start_time = time.perf_counter()
    for _ in range(iterations):
        for line in test_lines:
            original_pattern.search(line)
    original_time = time.perf_counter() - start_time

    # Benchmark optimized pattern
    start_time = time.perf_counter()
    for _ in range(iterations):
        for line in test_lines:
            optimized_pattern.search(line)
    optimized_time = time.perf_counter() - start_time

    # Calculate results
    total_operations = iterations * len(test_lines)
    original_ops_per_sec = total_operations / original_time
    optimized_ops_per_sec = total_operations / optimized_time
    improvement = ((original_time - optimized_time) / original_time) * 100

    print("Regex Pattern Optimization Benchmark")
    print("=" * 50)
    print(f"Test data size: {len(test_lines)} lines x {iterations} iterations")
    print(f"Total operations: {total_operations:,}")
    print()
    print("Original pattern (\\w+):")
    print(f"  Time: {original_time:.3f}s")
    print(f"  Ops/sec: {original_ops_per_sec:,.0f}")
    print()
    print("Optimized pattern ([^/]+):")
    print(f"  Time: {optimized_time:.3f}s")
    print(f"  Ops/sec: {optimized_ops_per_sec:,.0f}")
    print()
    print(f"Performance improvement: {improvement:.1f}%")
    print(f"Speed multiplier: {optimized_ops_per_sec / original_ops_per_sec:.2f}x")

    # Test correctness
    print("\nCorrectness verification:")
    test_line = f"workspace {Config.SHOWS_ROOT}/demo/shots/seq01/seq01_0010"

    orig_match = original_pattern.search(test_line)
    opt_match = optimized_pattern.search(test_line)

    if orig_match and opt_match:
        orig_groups = orig_match.groups()
        opt_groups = opt_match.groups()

        print(f"Original groups: {orig_groups}")
        print(f"Optimized groups: {opt_groups}")
        print(
            f"Groups match: {orig_groups[0:3] == opt_groups[0:3]}"
        )  # Compare workspace, show, sequence

    return improvement > 0


if __name__ == "__main__":
    improvement_achieved = benchmark_regex_patterns()
    print(f"\nOptimization successful: {improvement_achieved}")
