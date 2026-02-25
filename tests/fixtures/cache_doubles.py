"""Cache and progress test doubles.

Classes:
    TestCache: In-memory cache replacement for testing
    TestProgressOperation: Minimal test double for progress operations
    TestProgressManager: Test double for progress manager

Fixtures:
    test_process_pool: TestProcessPool instance for mocking ProcessPoolManager
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from tests.fixtures.process_doubles import TestProcessPool


class TestCache:
    """In-memory cache replacement for testing.

    Use this instead of mocking cache operations.
    Provides metrics for cache hit/miss analysis.

    Example usage:
        def test_cache_behavior():
            cache = TestCache()

            # Store and retrieve
            cache.set("key1", "value1")
            assert cache.get("key1") == "value1"
            assert cache.hits == 1

            # Miss scenario
            assert cache.get("key2") is None
            assert cache.misses == 1

            # Check metrics
            metrics = cache.metrics
            assert metrics["hit_rate"] == 0.5  # 1 hit, 1 miss
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize test cache."""
        from pathlib import Path
        self.cache_dir: Path | None = None  # Add missing cache_dir attribute
        self.data: dict[str, Any] = {}
        self.hits: int = 0
        self.misses: int = 0
        self.sets: int = 0
        self.evictions: int = 0
        self.max_size: int | None = None
        self.ttl_seconds: float | None = None
        self.access_times: dict[str, float] = {}
        self.creation_times: dict[str, float] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache.

        Updates hit/miss counters.

        Args:
            key: Cache key
            default: Default value if key not found

        Returns:
            Cached value or default

        """
        # Check TTL if configured
        if self.ttl_seconds and key in self.creation_times:
            age = time.time() - self.creation_times[key]
            if age > self.ttl_seconds:
                # Expired
                del self.data[key]
                del self.creation_times[key]
                if key in self.access_times:
                    del self.access_times[key]

        if key in self.data:
            self.hits += 1
            self.access_times[key] = time.time()
            return self.data[key]
        self.misses += 1
        return default

    def set(self, key: str, value: Any) -> None:
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache

        """
        # Check size limit and evict if needed
        if (
            self.max_size
            and len(self.data) >= self.max_size
            and key not in self.data
            and self.access_times
        ):
            # Simple LRU eviction
            oldest_key = min(self.access_times, key=self.access_times.get)  # type: ignore[arg-type]
            del self.data[oldest_key]
            del self.access_times[oldest_key]
            if oldest_key in self.creation_times:
                del self.creation_times[oldest_key]
            self.evictions += 1

        self.data[key] = value
        self.sets += 1
        self.creation_times[key] = time.time()
        self.access_times[key] = time.time()

    def clear(self) -> None:
        """Clear all cached data and reset counters."""
        self.data.clear()
        self.access_times.clear()
        self.creation_times.clear()
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.evictions = 0

    def delete(self, key: str) -> bool:
        """Delete a specific key from cache.

        Returns:
            True if key was deleted, False if not found

        """
        if key in self.data:
            del self.data[key]
            if key in self.access_times:
                del self.access_times[key]
            if key in self.creation_times:
                del self.creation_times[key]
            return True
        return False

    @property
    def metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary with cache statistics

        """
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0.0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "evictions": self.evictions,
            "hit_rate": hit_rate,
            "size": len(self.data),
            "total_requests": total_requests,
        }

    def set_ttl(self, seconds: float) -> None:
        """Set TTL for cache entries."""
        self.ttl_seconds = seconds

    def set_max_size(self, size: int) -> None:
        """Set maximum cache size with LRU eviction."""
        self.max_size = size


@dataclass
class TestProgressOperation:
    """Minimal test double for progress operations (internal to TestProgressManager)."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    title: str
    cancelable: bool = False
    progress: int = 0
    finished: bool = False


class TestProgressManager:
    """Test double for progress manager."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    _current_operation: ClassVar[TestProgressOperation | None] = None
    _operations_started: ClassVar[list[TestProgressOperation]] = []
    _operations_finished: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def start_operation(cls, config: Any) -> TestProgressOperation:
        """Start a new progress operation."""
        if isinstance(config, str):
            operation = TestProgressOperation(title=config)
        else:
            # Handle config object
            title = getattr(config, "title", "Test Operation")
            cancelable = getattr(config, "cancelable", False)
            operation = TestProgressOperation(title=title, cancelable=cancelable)

        cls._current_operation = operation
        cls._operations_started.append(operation)
        return operation

    @classmethod
    def finish_operation(cls, success: bool = True, error_message: str = "") -> None:
        """Finish the current progress operation."""
        if cls._current_operation:
            cls._operations_finished.append(
                {
                    "operation": cls._current_operation,
                    "success": success,
                    "error_message": error_message,
                    "timestamp": time.time(),
                }
            )
            cls._current_operation = None

    @classmethod
    def get_current_operation(cls) -> TestProgressOperation | None:
        """Get the current progress operation."""
        return cls._current_operation

    @classmethod
    def clear_all_operations(cls) -> None:
        """Clear all operations for testing."""
        cls._current_operation = None
        cls._operations_started.clear()
        cls._operations_finished.clear()

    @classmethod
    def get_operations_started_count(cls) -> int:
        """Get number of operations started (for testing)."""
        return len(cls._operations_started)

    @classmethod
    def get_operations_finished_count(cls) -> int:
        """Get number of operations finished (for testing)."""
        return len(cls._operations_finished)


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest.fixture
def test_process_pool(request: pytest.FixtureRequest) -> TestProcessPool:
    """Provide a TestProcessPool instance for mocking ProcessPoolManager.

    Args:
        request: Pytest request for marker checking

    Returns:
        TestProcessPool instance that can be configured to return
        specific outputs or simulate errors.

    NOTE: Tests that define their own local `test_process_pool` fixture
    will shadow this global one - the local fixture takes precedence.

    MARKERS:
        @pytest.mark.permissive_process_pool: Disable strict mode
        @pytest.mark.enforce_thread_guard: Enable main-thread rejection (contract testing)
        @pytest.mark.allow_main_thread: Allow calls from main/UI thread (opt-out from guard)

    """
    # Check for markers
    is_permissive = "permissive_process_pool" in [
        m.name for m in request.node.iter_markers()
    ]
    enforce_guard = "enforce_thread_guard" in [
        m.name for m in request.node.iter_markers()
    ]
    allow_main = "allow_main_thread" in [
        m.name for m in request.node.iter_markers()
    ]
    return TestProcessPool(
        strict=not is_permissive,
        enforce_thread_guard=enforce_guard,
        allow_main_thread=allow_main,
    )
