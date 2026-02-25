"""Timing decorator for performance testing operations."""

from __future__ import annotations

# Standard library imports
import functools
import logging
import time
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable

# Set up logger for this module
logger = logging.getLogger(__name__)


def timed_operation(
    name: str,
    log_threshold_ms: float = 0.0,
    store_results: bool = True,
) -> Callable:
    """Decorator to time function execution for performance testing.

    Args:
        name: Operation name for logging/tracking
        log_threshold_ms: Only log if execution time exceeds this threshold
        store_results: Whether to store timing results in global registry

    Returns:
        Decorated function

    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()

            try:
                return func(*args, **kwargs)
            finally:
                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000

                # Log if above threshold
                if duration_ms >= log_threshold_ms:
                    logger.debug(f"{name} took {duration_ms:.2f}ms")

                # Store results in global registry if enabled
                if store_results:
                    TimingRegistry.add_timing(name, duration_ms)

        return wrapper

    return decorator


class TimingRegistry:
    """Global registry for storing and analyzing timing results."""

    _timings: dict[str, list[float]] = {}  # noqa: RUF012  # Intentional class-level mutable for singleton registry pattern

    @classmethod
    def add_timing(cls, operation: str, duration_ms: float) -> None:
        """Add a timing measurement.

        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds

        """
        if operation not in cls._timings:
            cls._timings[operation] = []
        cls._timings[operation].append(duration_ms)

    @classmethod
    def get_stats(cls, operation: str) -> dict[str, float | None]:
        """Get statistics for an operation.

        Args:
            operation: Operation name

        Returns:
            Dictionary with timing statistics or None if no data

        """
        if operation not in cls._timings or not cls._timings[operation]:
            return None

        times = cls._timings[operation]
        return {
            "count": len(times),
            "total_ms": sum(times),
            "mean_ms": sum(times) / len(times),
            "min_ms": min(times),
            "max_ms": max(times),
            "median_ms": sorted(times)[len(times) // 2] if times else 0.0,
        }

    @classmethod
    def get_all_stats(cls) -> dict[str, dict[str, float]]:
        """Get statistics for all operations.

        Returns:
            Dictionary mapping operation names to their statistics

        """
        return {op: cls.get_stats(op) for op in cls._timings if cls.get_stats(op)}

    @classmethod
    def clear(cls) -> None:
        """Clear all timing data."""
        cls._timings.clear()

    @classmethod
    def get_operation_names(cls) -> list[str]:
        """Get list of all tracked operation names.

        Returns:
            List of operation names

        """
        return list(cls._timings.keys())

    @classmethod
    def compare_operations(cls, baseline: str, optimized: str) -> float | None:
        """Compare two operations and calculate speedup factor.

        Args:
            baseline: Name of baseline operation
            optimized: Name of optimized operation

        Returns:
            Speedup factor (baseline_time / optimized_time) or None if data missing

        """
        baseline_stats = cls.get_stats(baseline)
        optimized_stats = cls.get_stats(optimized)

        if not baseline_stats or not optimized_stats:
            return None

        baseline_mean = baseline_stats["mean_ms"]
        optimized_mean = optimized_stats["mean_ms"]

        if optimized_mean == 0:
            return float("inf")

        return baseline_mean / optimized_mean
