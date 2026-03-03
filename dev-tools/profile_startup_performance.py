#!/usr/bin/env python3
"""Profile startup performance bottleneck in ws -sg command.

Analyzes the 2.4 second startup delay to identify optimization opportunities.
"""

from __future__ import annotations

import contextlib

# Standard library imports
import cProfile
import json
import os
import pstats
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


# Set minimal environment
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_LOGGING_RULES"] = "*.debug=false"


def profile_subprocess_call() -> dict[str, float]:
    """Profile the raw subprocess call to ws -sg."""
    timings = {}

    # Time the basic subprocess call with shell
    start = time.perf_counter()
    try:
        result = subprocess.run(
            ["/bin/bash", "-i", "-c", "ws -sg"],
            check=False, capture_output=True,
            text=True,
            timeout=10,
        )
        timings["raw_subprocess"] = time.perf_counter() - start
        timings["output_size"] = len(result.stdout) if result.stdout else 0
        timings["returncode"] = result.returncode
    except subprocess.TimeoutExpired:
        timings["raw_subprocess"] = time.perf_counter() - start
        timings["error"] = "timeout"
    except Exception as e:
        timings["raw_subprocess"] = time.perf_counter() - start
        timings["error"] = str(e)

    return timings


def profile_process_pool_manager() -> dict[str, float]:
    """Profile ProcessPoolManager overhead."""
    # Local application imports
    from process_pool_manager import ProcessPoolManager

    timings = {}

    # Time ProcessPoolManager creation
    start = time.perf_counter()
    pool = ProcessPoolManager()
    timings["pool_creation"] = time.perf_counter() - start

    # Time first command execution
    start = time.perf_counter()
    try:
        output = pool.execute_workspace_command("ws -sg", timeout=10)
        timings["pool_first_call"] = time.perf_counter() - start
        timings["output_size"] = len(output) if output else 0
    except Exception as e:
        timings["pool_first_call"] = time.perf_counter() - start
        timings["error"] = str(e)

    # Time second command (should use cache or session)
    start = time.perf_counter()
    try:
        output = pool.execute_workspace_command("ws -sg", timeout=10)
        timings["pool_second_call"] = time.perf_counter() - start
    except Exception:
        timings["pool_second_call"] = time.perf_counter() - start

    return timings


def profile_shot_model_refresh() -> dict[str, Any]:
    """Profile ShotModel refresh with detailed breakdown."""
    # Local application imports
    from cache.shot_cache import ShotDataCache
    from shot_model import ShotModel

    timings = {}

    # Create shot cache with temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ShotDataCache(Path(tmpdir))

        # Create shot model
        start = time.perf_counter()
        model = ShotModel(cache_manager=cache)
        timings["model_creation"] = time.perf_counter() - start

        # Profile refresh_shots with cProfile
        profiler = cProfile.Profile()
        start = time.perf_counter()

        profiler.enable()
        result = model.refresh_shots()
        profiler.disable()

        timings["refresh_total"] = time.perf_counter() - start
        timings["success"] = result.success
        timings["has_changes"] = result.has_changes
        timings["shot_count"] = len(model.shots)

        # Get profiling stats
        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative")

        # Extract top time consumers
        top_functions = []
        # Type checker doesn't know about stats.stats attribute
        stats_items = list(stats.stats.items()) if hasattr(stats, "stats") else []  # type: ignore[attr-defined]
        for (file, line, func), (_cc, nc, tt, ct, _callers) in stats_items[:10]:
            top_functions.append(
                {
                    "function": f"{func}:{line}",
                    "file": Path(file).name if file else "unknown",
                    "cumulative_time": ct,
                    "total_time": tt,
                    "calls": nc,
                }
            )
        timings["top_functions"] = top_functions

    return timings


def analyze_startup_alternatives() -> dict[str, Any]:
    """Analyze potential optimization strategies."""
    strategies = {}

    # Test async loading simulation
    start = time.perf_counter()
    time.sleep(0.01)  # Simulate immediate UI display
    # Background loading would happen here
    strategies["async_ui_display"] = time.perf_counter() - start

    # Test cached data simulation
    cached_data = """workspace /shows/TEST/seq01/0010
workspace /shows/TEST/seq01/0020
workspace /shows/TEST/seq02/0010"""

    start = time.perf_counter()
    lines = cached_data.split("\n")
    strategies["cached_parse_time"] = time.perf_counter() - start
    strategies["cached_lines"] = len(lines)

    # Test connection pooling benefit
    # Local application imports
    from process_pool_manager import ProcessPoolManager

    pool = ProcessPoolManager()

    # Warm up the pool
    with contextlib.suppress(Exception):
        pool.execute_workspace_command("echo test", timeout=1)

    # Time subsequent calls
    times = []
    for i in range(3):
        start = time.perf_counter()
        try:
            pool.execute_workspace_command(f"echo test{i}", timeout=1)
            times.append(time.perf_counter() - start)
        except Exception:
            times.append(time.perf_counter() - start)

    strategies["pooled_calls"] = times
    strategies["pooled_average"] = sum(times) / len(times) if times else 0

    return strategies


def main() -> None:
    """Run comprehensive startup performance profiling."""
    print("=" * 60)
    print("ShotBot Startup Performance Profiling")
    print("=" * 60)

    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": {
            "startup_time": 2.901,  # From PERFORMANCE_BASELINE.json
            "initial_refresh": 2.422,  # From PERFORMANCE_BASELINE.json
        },
    }

    # 1. Profile raw subprocess
    print("\n1. Profiling raw subprocess call...")
    results["subprocess"] = profile_subprocess_call()
    print(f"   Raw subprocess: {results['subprocess'].get('raw_subprocess', -1):.3f}s")

    # 2. Profile ProcessPoolManager
    print("\n2. Profiling ProcessPoolManager...")
    results["process_pool"] = profile_process_pool_manager()
    print(f"   Pool creation: {results['process_pool'].get('pool_creation', -1):.3f}s")
    print(f"   First call: {results['process_pool'].get('pool_first_call', -1):.3f}s")
    print(f"   Second call: {results['process_pool'].get('pool_second_call', -1):.3f}s")

    # 3. Profile ShotModel refresh
    print("\n3. Profiling ShotModel refresh...")
    results["shot_model"] = profile_shot_model_refresh()
    print(f"   Model creation: {results['shot_model'].get('model_creation', -1):.3f}s")
    print(f"   Refresh total: {results['shot_model'].get('refresh_total', -1):.3f}s")
    print(f"   Shots found: {results['shot_model'].get('shot_count', 0)}")

    # 4. Analyze optimization strategies
    print("\n4. Analyzing optimization strategies...")
    results["strategies"] = analyze_startup_alternatives()
    print(
        f"   Async UI display: {results['strategies'].get('async_ui_display', -1):.3f}s"
    )
    print(
        f"   Cached parse time: {results['strategies'].get('cached_parse_time', -1):.6f}s"
    )
    print(f"   Pooled average: {results['strategies'].get('pooled_average', -1):.3f}s")

    # 5. Calculate potential improvements
    print("\n" + "=" * 60)
    print("Analysis Summary")
    print("=" * 60)

    if "subprocess" in results and "raw_subprocess" in results["subprocess"]:
        raw_time = results["subprocess"]["raw_subprocess"]
        print("\nBottleneck breakdown:")
        print(f"  Raw 'ws -sg' command: {raw_time:.3f}s")

        if "process_pool" in results:
            pool_overhead = results["process_pool"].get("pool_first_call", 0) - raw_time
            print(f"  ProcessPool overhead: {pool_overhead:.3f}s")

        if "shot_model" in results:
            model_overhead = results["shot_model"].get("refresh_total", 0) - raw_time
            print(f"  ShotModel overhead: {model_overhead:.3f}s")

    print("\nOptimization opportunities:")
    print("1. Async loading: Show UI immediately, load in background")
    print("2. Cache warming: Pre-load on app start with stale data")
    print("3. Progressive loading: Show first N shots immediately")
    print("4. Connection pooling: Reuse bash session")

    # Save results
    output_file = Path("startup_profile_results.json")
    with output_file.open("w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nDetailed results saved to: {output_file}")

    # Print top time-consuming functions
    if "shot_model" in results and "top_functions" in results["shot_model"]:
        print("\nTop time-consuming functions:")
        for func in results["shot_model"]["top_functions"][:5]:
            print(
                f"  {func['cumulative_time']:.3f}s - {func['function']} ({func['calls']} calls)"
            )

    return results


if __name__ == "__main__":
    main()
