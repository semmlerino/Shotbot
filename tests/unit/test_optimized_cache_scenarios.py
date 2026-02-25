#!/usr/bin/env python3
"""Test cache behavior and performance metrics for ShotModel."""

# Standard library imports
import time
from unittest.mock import Mock, patch

# Third-party imports
import pytest

# Local application imports
from shot_model import ShotModel


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
    pytest.mark.performance_like,
]


@pytest.mark.allow_main_thread  # Tests call pre_warm_session() synchronously from main thread
class TestCacheScenarios:
    """Test cache hit/miss scenarios and performance tracking."""

    @pytest.fixture
    def optimized_model_with_cache(self, real_cache_manager):
        """Create ShotModel with real cache."""
        return ShotModel(real_cache_manager)

    def test_cache_hit_scenario(self, optimized_model_with_cache) -> None:
        """Test performance when cache data is available."""
        model = optimized_model_with_cache

        # Pre-populate cache
        cached_data = [
            {
                "show": "CACHED",
                "sequence": "seq01",
                "shot": "0010",
                "workspace_path": "/cached/path1",
            },
            {
                "show": "CACHED",
                "sequence": "seq01",
                "shot": "0020",
                "workspace_path": "/cached/path2",
            },
        ]
        model.cache_manager.cache_shots(cached_data)

        # Measure initialization time
        start_time = time.perf_counter()
        result = model.initialize_async()
        elapsed = time.perf_counter() - start_time

        # Should be fast with cache hit (relaxed timing for CI environment)
        assert elapsed < 0.1, f"Cache hit took {elapsed:.3f}s, should be < 0.1s"
        assert result.success is True
        assert len(model.shots) == 2

        # Check performance metrics
        metrics = model.get_performance_metrics()
        assert metrics["cache_hit_count"] == 1
        assert metrics["cache_miss_count"] == 0
        assert metrics["cache_hit_rate"] == 1.0

    def test_cache_miss_scenario(self, optimized_model_with_cache) -> None:
        """Test behavior when no cache data available."""
        model = optimized_model_with_cache

        # Ensure empty cache
        model.cache_manager.clear_cache()

        start_time = time.perf_counter()
        result = model.initialize_async()
        elapsed = time.perf_counter() - start_time

        # Should still return quickly (showing empty UI) - relaxed timing for CI
        assert elapsed < 0.1, f"Cache miss initialization took {elapsed:.3f}s"
        assert result.success is True
        assert len(model.shots) == 0  # Empty initially

        # Check metrics
        metrics = model.get_performance_metrics()
        assert metrics["cache_miss_count"] == 1
        assert metrics["cache_hit_rate"] == 0.0

    def test_mixed_cache_scenarios(self, optimized_model_with_cache) -> None:
        """Test multiple cache operations to verify hit rate calculation."""
        model = optimized_model_with_cache

        # First call - cache miss
        model.cache_manager.clear_cache()
        model.initialize_async()

        # Populate cache for next call
        model.cache_manager.cache_shots(
            [
                {
                    "show": "TEST",
                    "sequence": "seq",
                    "shot": "0010",
                    "workspace_path": "/test",
                }
            ]
        )

        # Second call - cache hit
        model.initialize_async()

        # Third call - cache hit
        model.initialize_async()

        metrics = model.get_performance_metrics()
        assert metrics["cache_hit_count"] == 2
        assert metrics["cache_miss_count"] == 1
        assert metrics["cache_hit_rate"] == 2 / 3  # 2 hits out of 3 total

    def test_manual_refresh_behavior(self, optimized_model_with_cache, qtbot) -> None:
        """Test that manual refresh works when no cache is available."""
        model = optimized_model_with_cache

        # Mock cache with no data (manual refresh mode)
        with patch.object(model.cache_manager, "get_cached_shots") as mock_get:
            mock_get.return_value = None  # No cached data

            # Mock process pool for background refresh
            mock_pool = Mock()
            mock_pool.execute_workspace_command.return_value = "workspace /new/data"
            model._process_pool = mock_pool

            result = model.initialize_async()
            assert (
                result.success is True
            )  # initialize_async returns success immediately

            # Should start with empty shots and begin background loading
            assert len(model.shots) == 0

            # The background refresh should be triggered manually, not by expiration
            # In the current system, cache expiration doesn't automatically trigger refresh
            # Instead, refresh happens when initialize_async is called

    def test_performance_metrics_accuracy(self, optimized_model_with_cache) -> None:
        """Test that performance metrics accurately track operations."""
        model = optimized_model_with_cache

        initial_metrics = model.get_performance_metrics()
        assert initial_metrics["cache_hit_count"] == 0
        assert initial_metrics["cache_miss_count"] == 0

        # Perform operations and verify metrics update
        model.cache_manager.clear_cache()
        model.initialize_async()  # Should be cache miss

        # Add cache data
        model.cache_manager.cache_shots(
            [{"show": "TEST", "sequence": "s", "shot": "1", "workspace_path": "/p"}]
        )
        model.initialize_async()  # Should be cache hit

        final_metrics = model.get_performance_metrics()
        assert final_metrics["cache_hit_count"] == 1
        assert final_metrics["cache_miss_count"] == 1

    def test_session_warming_performance(self, optimized_model_with_cache) -> None:
        """Test that session pre-warming improves subsequent performance."""
        model = optimized_model_with_cache

        # Use test double instead of mock to track behavior
        # Local application imports
        from tests.fixtures.doubles_library import (
            TestProcessPool,
        )

        # Permissive for this test + allow_main_thread since test runs from main thread
        test_pool = TestProcessPool(strict=False, allow_main_thread=True)
        test_pool.set_outputs("warming")
        model._process_pool = test_pool

        # Measure pre-warming
        start_time = time.perf_counter()
        model.pre_warm_sessions()
        warm_time = time.perf_counter() - start_time

        # Should complete quickly and mark as warmed
        assert warm_time < 1.0, f"Session warming took {warm_time:.3f}s"

        metrics = model.get_performance_metrics()
        assert metrics["session_warmed"] is True

        # Test behavior: verify warming command was executed
        assert len(test_pool.commands) == 1
        assert test_pool.commands[0] == "echo warming"

    def test_concurrent_cache_access(self, optimized_model_with_cache) -> None:
        """Test cache behavior with concurrent access (thread safety)."""
        model = optimized_model_with_cache

        # Pre-populate cache
        model.cache_manager.cache_shots(
            [
                {
                    "show": "CONCURRENT",
                    "sequence": "seq",
                    "shot": "0010",
                    "workspace_path": "/path",
                }
            ]
        )

        # Simulate concurrent initialization calls
        results = []
        for _ in range(3):
            result = model.initialize_async()
            results.append(result)

        # All should succeed
        assert all(r.success for r in results)

        # Cache hit count should be accurate (may be 3 if all hit cache)
        metrics = model.get_performance_metrics()
        assert metrics["cache_hit_count"] >= 1
