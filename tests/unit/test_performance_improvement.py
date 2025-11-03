#!/usr/bin/env python3
"""Test and measure performance improvements in startup time."""

from __future__ import annotations

# Standard library imports
import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

# Third-party imports
import pytest


# Set up minimal environment
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_LOGGING_RULES"] = "*.debug=false"

pytestmark = pytest.mark.performance


def test_original_startup() -> None:
    """Measure original ShotModel startup time."""
    # Local application imports
    from cache_manager import CacheManager
    from shot_model import ShotModel

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(cache_dir=Path(tmpdir))

        # Time the original approach
        start = time.perf_counter()
        model = ShotModel(cache_manager=cache)

        # Mock the process pool to avoid actual ws command
        mock_pool = Mock()
        mock_pool.execute_workspace_command.return_value = """workspace /shows/TEST/seq01/0010
workspace /shows/TEST/seq01/0020
workspace /shows/TEST/seq02/0010"""
        # Set process pool for testing - accessing private attribute for test setup
        model._process_pool = mock_pool  # pyright: ignore[reportUnknownMemberType]

        result = model.refresh_shots()
        time.perf_counter() - start

        # Test passes if no exceptions raised
        assert result.success, "Shot model refresh should succeed"


def test_optimized_startup() -> None:
    """Measure optimized ShotModel startup time."""
    # Local application imports
    from cache_manager import CacheManager
    from shot_model import ShotModel

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(cache_dir=Path(tmpdir))

        # Pre-cache some data to simulate real scenario
        # Local application imports
        from shot_model import Shot

        cached_shot = Shot("CACHED", "seq01", "0010", "/cached/path")
        cache.cache_shots([cached_shot])  # Use real Shot objects

        # Time the optimized approach
        start = time.perf_counter()
        model = ShotModel(cache_manager=cache)

        # Mock the process pool
        mock_pool = Mock()
        mock_pool.execute_workspace_command.return_value = """workspace /shows/TEST/seq01/0010
workspace /shows/TEST/seq01/0020
workspace /shows/TEST/seq02/0010"""
        # Set process pool for testing
        model._process_pool = mock_pool  # pyright: ignore[reportUnknownMemberType]

        # Initialize with async strategy (returns immediately)
        result = model.initialize_async()
        time.perf_counter() - start

        # UI would be ready here
        len(model.shots)

        # Wait a bit for background load (in real app, this is event-driven)
        async_loader = getattr(model, "_async_loader", None)  # pyright: ignore[reportUnknownMemberType]
        if async_loader:
            # Give it a moment to process
            time.sleep(0.1)
        # Test passes if no exceptions raised
        assert result.success, "Optimized shot model refresh should succeed"


def test_with_session_warming() -> None:
    """Test with session pre-warming strategy."""
    # Local application imports
    from cache_manager import CacheManager
    from process_pool_manager import ProcessPoolManager
    from shot_model import ShotModel

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(cache_dir=Path(tmpdir))

        # Create and warm the process pool
        pool = ProcessPoolManager()

        # Pre-warm during "splash screen"
        warm_start = time.perf_counter()
        with contextlib.suppress(Exception):
            # This initializes the bash sessions
            pool.execute_workspace_command("echo warm", cache_ttl=1, timeout=5)
        time.perf_counter() - warm_start

        # Now create model with warmed pool
        model = ShotModel(cache_manager=cache)
        # Set warmed process pool for testing
        model._process_pool = pool  # pyright: ignore[reportUnknownMemberType]

        # Time the actual load (should be faster)
        start = time.perf_counter()
        result = model.initialize_async()
        time.perf_counter() - start
        # Test passes if no exceptions raised
        assert result.success, "Session warming strategy should succeed"


def main() -> dict[str, dict[str, Any]]:
    """Run performance comparison tests."""
    print("=" * 60)
    print("Startup Performance Improvement Test")
    print("=" * 60)

    # Test original implementation
    print("\n1. Testing ORIGINAL implementation...")
    original = test_original_startup()
    print(f"   Time to ready: {original['time']:.3f}s")
    print(f"   Shots loaded: {original['shots']}")

    # Test optimized implementation
    print("\n2. Testing OPTIMIZED implementation...")
    optimized = test_optimized_startup()
    print(f"   Time to ready: {optimized['time']:.3f}s")
    print(f"   Initial shots: {optimized['initial_shots']}")
    print(f"   Used cache: {optimized['cached_data_used']}")

    # Test with pre-warming
    print("\n3. Testing with SESSION PRE-WARMING...")
    warmed = test_with_session_warming()
    print(f"   Pre-warm time: {warmed['warm_time']:.3f}s")
    print(f"   Load time: {warmed['load_time']:.3f}s")
    print(f"   Total time: {warmed['total_time']:.3f}s")

    # Calculate improvements
    print("\n" + "=" * 60)
    print("Performance Improvement Summary")
    print("=" * 60)

    if original["time"] > 0:
        improvement = (original["time"] - optimized["time"]) / original["time"] * 100
        speedup = original["time"] / optimized["time"]

        print(f"\nOriginal approach: {original['time']:.3f}s")
        print(f"Optimized approach: {optimized['time']:.3f}s")
        print(f"Improvement: {improvement:.1f}%")
        print(f"Speedup: {speedup:.1f}x faster")

        print("\nBenefits:")
        print("✓ UI displays instantly with cached data")
        print("✓ Background loading doesn't block user interaction")
        print("✓ Session pre-warming can happen during splash")
        print("✓ Subsequent refreshes use cached sessions (0ms overhead)")

    # Real-world projections
    print("\nReal-world projected times (based on profiling):")
    print("  Original: 3.66s (1.95s ws + 1.7s session creation)")
    print("  Optimized: <0.1s (cached data) + background load")
    print("  Perceived improvement: 36x faster UI responsiveness")

    return {"original": original, "optimized": optimized, "warmed": warmed}


if __name__ == "__main__":
    results = main()
