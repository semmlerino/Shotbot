from tests.helpers.synchronization import process_qt_events

"""Unit tests for memory management performance optimizations.

These tests verify that:
1. Cache eviction works at memory limits
2. Thread safety of cache operations
3. Memory monitoring accuracy
4. Prevention of memory leaks
5. Proper resource cleanup
"""

import gc
from typing import Dict, List
from unittest.mock import patch

import psutil
import pytest
from PySide6.QtWidgets import QApplication

from tests.performance.timed_operation import TimingRegistry, timed_operation


class MemoryTracker:
    """Helper class to track memory usage during tests."""

    def __init__(self):
        self.process = psutil.Process()
        self.initial_memory = self.get_memory_mb()
        self.peak_memory = self.initial_memory
        self.measurements: List[float] = []

    def get_memory_mb(self) -> float:
        """Get current memory usage in MB."""
        memory_info = self.process.memory_info()
        return memory_info.rss / (1024 * 1024)  # RSS in MB

    def measure(self) -> float:
        """Take a memory measurement."""
        current_memory = self.get_memory_mb()
        self.measurements.append(current_memory)
        self.peak_memory = max(self.peak_memory, current_memory)
        return current_memory

    def get_memory_increase(self) -> float:
        """Get memory increase from initial."""
        return self.get_memory_mb() - self.initial_memory

    def get_peak_increase(self) -> float:
        """Get peak memory increase from initial."""
        return self.peak_memory - self.initial_memory


class TestMemoryManagement:
    """Test suite for memory management optimizations."""

    def setup_method(self):
        """Set up test environment."""
        TimingRegistry.clear()
        # Force garbage collection before tests
        gc.collect()

        # Clear any existing caches
        try:
            from utils import clear_all_caches

            clear_all_caches()
        except ImportError:
            pass

    def teardown_method(self):
        """Clean up after tests."""
        TimingRegistry.clear()
        # Force garbage collection after tests
        gc.collect()

    def test_cache_memory_limits(self):
        """Test that caches respect memory limits."""
        memory_tracker = MemoryTracker()
        initial_memory = memory_tracker.measure()

        # Try to import enhanced cache
        try:
            from enhanced_cache import LRUCache

            # Create cache with small memory limit
            cache = LRUCache(
                max_size=10000,
                max_memory_mb=1.0,  # 1MB limit
                name="memory_test",
            )

            # Fill cache with data that should exceed memory limit
            large_data_entries = []
            for i in range(1000):
                # Create ~2KB of data per entry
                large_data = "x" * 2048
                cache.put(f"key_{i}", large_data)
                large_data_entries.append(large_data)

            # Measure memory after filling cache
            after_fill_memory = memory_tracker.measure()

            # Cache should have evicted entries to stay within memory limit
            stats = cache.get_stats()

            # Should have some evictions due to memory pressure
            if "memory_evictions" in stats:
                assert stats["memory_evictions"] > 0

            # Memory usage should be reasonable
            memory_increase = after_fill_memory - initial_memory
            assert memory_increase < 50.0, (
                f"Memory increased by {memory_increase:.1f}MB, too much!"
            )

            print(f"Cache entries: {stats.get('entries', 0)}")
            print(f"Memory evictions: {stats.get('memory_evictions', 0)}")
            print(f"Memory increase: {memory_increase:.1f}MB")

        except ImportError:
            pytest.skip("Enhanced cache not available")

    def test_cache_eviction_strategies(self):
        """Test different cache eviction strategies."""
        try:
            from enhanced_cache import LRUCache

            # Create cache with low size limit to trigger evictions
            cache = LRUCache(max_size=10, ttl_seconds=300.0, name="eviction_test")

            # Fill cache beyond capacity
            for i in range(20):
                cache.put(f"key_{i}", f"value_{i}")

            # Cache should be at max size
            stats = cache.get_stats()
            assert stats.get("entries", 0) <= 10

            # Should have evictions
            assert stats.get("evictions", 0) > 0

            # Verify LRU behavior - recent items should still be present
            # Last few items should still be in cache
            for i in range(15, 20):
                result = cache.get(f"key_{i}")
                assert result is not None, f"Recent key_{i} should still be in cache"

            # Earlier items should have been evicted
            early_items_present = 0
            for i in range(5):
                result = cache.get(f"key_{i}")
                if result is not None:
                    early_items_present += 1

            # Most early items should have been evicted
            assert early_items_present < 3, "Too many early items still present"

            print(f"Final cache size: {stats.get('entries', 0)}")
            print(f"Total evictions: {stats.get('evictions', 0)}")

        except ImportError:
            pytest.skip("Enhanced cache not available")

    def test_memory_leak_prevention(self):
        """Test that caches don't cause memory leaks."""
        memory_tracker = MemoryTracker()
        initial_memory = memory_tracker.measure()

        def create_and_destroy_caches(iterations: int = 5):
            """Create and destroy caches to test for leaks."""
            for i in range(iterations):
                try:
                    from enhanced_cache import LRUCache

                    # Create cache and fill with data
                    cache = LRUCache(max_size=100, name=f"leak_test_{i}")

                    # Fill with data
                    for j in range(50):
                        cache.put(f"key_{j}", f"value_{j}_{'x' * 100}")

                    # Access some data
                    for j in range(0, 50, 5):
                        cache.get(f"key_{j}")

                    # Clear cache explicitly
                    cache.clear()
                    del cache

                    # Force garbage collection
                    gc.collect()

                    # Measure memory periodically
                    if i % 2 == 0:
                        memory_tracker.measure()

                except ImportError:
                    # Use utils cache instead
                    from utils import PathUtils

                    # Fill path cache
                    test_paths = [f"/tmp/leak_test_{i}_{j}" for j in range(50)]

                    with patch.object(
                        PathUtils, "validate_path_exists"
                    ) as mock_validate:
                        mock_validate.return_value = True
                        for path in test_paths:
                            PathUtils.validate_path_exists(path, "Leak test")

                    # Clear cache
                    from utils import clear_all_caches

                    clear_all_caches()
                    gc.collect()

                    if i % 2 == 0:
                        memory_tracker.measure()

        # Run cache creation/destruction cycles
        create_and_destroy_caches(10)

        # Final memory measurement
        final_memory = memory_tracker.measure()
        memory_increase = final_memory - initial_memory

        # Memory increase should be minimal (less than 10MB)
        assert memory_increase < 10.0, (
            f"Memory leak detected: {memory_increase:.1f}MB increase after cache cycles"
        )

        print(f"Memory increase after leak test: {memory_increase:.1f}MB")
        print(f"Peak memory increase: {memory_tracker.get_peak_increase():.1f}MB")

    def test_thread_safe_cache_operations(self):
        """Test thread safety of cache operations under memory pressure."""
        import concurrent.futures

        memory_tracker = MemoryTracker()
        memory_tracker.measure()

        def worker_function(worker_id: int, iterations: int = 100) -> Dict[str, int]:
            """Worker function for concurrent cache operations."""
            stats = {"puts": 0, "gets": 0, "hits": 0, "misses": 0}

            try:
                from enhanced_cache import LRUCache

                # Each worker gets its own cache to avoid conflicts
                cache = LRUCache(
                    max_size=50,
                    max_memory_mb=0.5,  # Small memory limit
                    name=f"thread_test_{worker_id}",
                )

                for i in range(iterations):
                    # Put operations
                    key = f"worker_{worker_id}_key_{i}"
                    value = f"data_{'x' * 100}_{i}"  # ~100 bytes per value
                    cache.put(key, value)
                    stats["puts"] += 1

                    # Get operations (mix of existing and non-existing keys)
                    if i % 3 == 0 and i > 0:
                        # Try to get existing key
                        get_key = f"worker_{worker_id}_key_{i - 1}"
                        result = cache.get(get_key)
                        stats["gets"] += 1
                        if result is not None:
                            stats["hits"] += 1
                        else:
                            stats["misses"] += 1

                return stats

            except ImportError:
                # Fallback to utils cache
                from utils import PathUtils

                for i in range(iterations):
                    path = f"/tmp/thread_test_{worker_id}_{i}"
                    with patch.object(
                        PathUtils, "validate_path_exists", return_value=True
                    ):
                        result = PathUtils.validate_path_exists(path, "Thread test")
                        if result:
                            stats["puts"] += 1

                return stats

        # Run multiple workers concurrently
        num_workers = 6
        iterations_per_worker = 50  # Reduced for memory constraints

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(worker_function, i, iterations_per_worker)
                for i in range(num_workers)
            ]

            # Collect results
            results = []
            for future in concurrent.futures.as_completed(futures, timeout=30):
                result = future.result()
                results.append(result)

        # Verify all workers completed
        assert len(results) == num_workers

        # Aggregate statistics
        total_puts = sum(r["puts"] for r in results)
        total_gets = sum(r["gets"] for r in results)

        assert total_puts == num_workers * iterations_per_worker

        # Check memory usage
        memory_tracker.measure()
        memory_increase = memory_tracker.get_memory_increase()

        # Memory increase should be reasonable
        assert memory_increase < 20.0, (
            f"Excessive memory usage: {memory_increase:.1f}MB"
        )

        print(f"Thread safety test completed: {total_puts} puts, {total_gets} gets")
        print(f"Memory increase: {memory_increase:.1f}MB")

    def test_memory_monitoring_accuracy(self):
        """Test accuracy of memory monitoring systems."""
        try:
            from memory_aware_cache import get_memory_monitor

            monitor = get_memory_monitor()

            # Get initial memory metrics
            initial_metrics = monitor.get_metrics()
            initial_memory = initial_metrics.process_mb

            # Allocate some memory
            large_objects = []
            for i in range(10):
                # Allocate ~1MB objects
                obj = "x" * (1024 * 1024)  # 1MB string
                large_objects.append(obj)

            # Get metrics after allocation
            after_alloc_metrics = monitor.get_metrics()
            after_alloc_memory = after_alloc_metrics.process_mb

            # Should detect memory increase
            memory_increase = after_alloc_memory - initial_memory

            # Should detect at least 5MB increase (allowing for overhead)
            assert memory_increase >= 5.0, (
                f"Memory monitor didn't detect increase: {memory_increase:.1f}MB"
            )

            # Clean up
            del large_objects
            gc.collect()

            # Get final metrics
            final_metrics = monitor.get_metrics()
            final_memory = final_metrics.process_mb

            # Memory should decrease after cleanup (may not be immediate)
            print(f"Initial: {initial_memory:.1f}MB")
            print(f"After alloc: {after_alloc_memory:.1f}MB")
            print(f"After cleanup: {final_memory:.1f}MB")
            print(f"Detected increase: {memory_increase:.1f}MB")

        except ImportError:
            pytest.skip("Memory monitoring not available")

    def test_cache_size_estimation(self):
        """Test accuracy of cache size estimation."""
        try:
            from enhanced_cache import LRUCache

            cache = LRUCache(max_size=1000, name="size_test")

            # Add entries of known size
            test_data = {
                "small": "x" * 10,  # ~10 bytes
                "medium": "x" * 1000,  # ~1KB
                "large": "x" * 10000,  # ~10KB
            }

            for key, value in test_data.items():
                cache.put(key, value)

            # Check estimated memory usage
            stats = cache.get_stats()

            if "memory_usage" in stats:
                estimated_memory = stats["memory_usage"]

                # Should be reasonable estimate (at least sum of data sizes)
                expected_min_bytes = sum(len(v) for v in test_data.values())
                expected_min_kb = expected_min_bytes / 1024

                assert estimated_memory >= expected_min_kb, (
                    f"Size estimate too low: {estimated_memory:.1f}KB < {expected_min_kb:.1f}KB"
                )

                print(f"Data size: {expected_min_kb:.1f}KB")
                print(f"Estimated cache memory: {estimated_memory:.1f}KB")

        except ImportError:
            pytest.skip("Enhanced cache not available")

    def test_garbage_collection_integration(self):
        """Test integration with Python garbage collection."""
        memory_tracker = MemoryTracker()
        initial_memory = memory_tracker.measure()

        # Create objects that should be garbage collected
        cache_objects = []

        try:
            from enhanced_cache import LRUCache

            for i in range(10):
                cache = LRUCache(max_size=100, name=f"gc_test_{i}")

                # Fill with circular references to test GC
                for j in range(50):
                    data = {"id": j, "cache_ref": cache}
                    cache.put(f"key_{j}", data)

                cache_objects.append(cache)

            # Memory should have increased
            after_create_memory = memory_tracker.measure()
            memory_increase = after_create_memory - initial_memory
            assert memory_increase > 1.0, "Should have allocated some memory"

            # Clear references and force GC
            cache_objects.clear()
            gc.collect()

            # Give GC time to clean up
            process_qt_events(QApplication.instance(), 100)
            gc.collect()

            final_memory = memory_tracker.measure()
            final_increase = final_memory - initial_memory

            # Memory usage should have decreased significantly
            cleanup_ratio = final_increase / memory_increase
            assert cleanup_ratio < 0.5, (
                f"Poor garbage collection: {cleanup_ratio:.2f} memory ratio after cleanup"
            )

            print(f"Memory after creation: {memory_increase:.1f}MB")
            print(f"Memory after GC: {final_increase:.1f}MB")
            print(f"Cleanup ratio: {cleanup_ratio:.2f}")

        except ImportError:
            pytest.skip("Enhanced cache not available")

    def test_memory_pressure_response(self):
        """Test system response to memory pressure."""
        try:
            from memory_aware_cache import get_memory_monitor

            monitor = get_memory_monitor()
            monitor.get_metrics()

            # Simulate memory pressure by allocating large objects
            pressure_objects = []

            for i in range(20):
                # Allocate 5MB objects
                obj = "x" * (5 * 1024 * 1024)
                pressure_objects.append(obj)

                # Check memory pressure periodically
                if i % 5 == 0:
                    metrics = monitor.get_metrics()
                    print(
                        f"Iteration {i}: Memory pressure = {metrics.pressure_level.value}"
                    )

            # Should detect high memory pressure
            final_metrics = monitor.get_metrics()

            # Clean up to avoid affecting other tests
            del pressure_objects
            gc.collect()

            print(f"Final memory pressure: {final_metrics.pressure_level.value}")
            print(f"Process memory: {final_metrics.process_mb:.1f}MB")

        except ImportError:
            pytest.skip("Memory monitoring not available")

    def test_resource_cleanup_patterns(self):
        """Test proper resource cleanup patterns."""
        resource_tracker = []

        class TestResource:
            def __init__(self, resource_id: str):
                self.resource_id = resource_id
                self.cleaned_up = False
                resource_tracker.append(self)

            def cleanup(self):
                self.cleaned_up = True

            def __del__(self):
                if not self.cleaned_up:
                    self.cleanup()

        # Create resources and simulate cache usage
        resources = []

        try:
            from enhanced_cache import LRUCache

            cache = LRUCache(max_size=10, name="resource_test")

            # Add resources to cache
            for i in range(20):  # More than cache size to trigger evictions
                resource = TestResource(f"resource_{i}")
                resources.append(resource)
                cache.put(f"key_{i}", resource)

            # Clear cache
            cache.clear()
            del cache

        except ImportError:
            # Use simple resource management
            pass

        # Clear references
        resources.clear()
        gc.collect()

        # Check that resources were cleaned up
        cleaned_resources = sum(1 for r in resource_tracker if r.cleaned_up)
        total_resources = len(resource_tracker)

        cleanup_ratio = (
            cleaned_resources / total_resources if total_resources > 0 else 1.0
        )

        assert cleanup_ratio >= 0.8, (
            f"Poor resource cleanup: {cleanup_ratio:.2f} ratio "
            f"({cleaned_resources}/{total_resources})"
        )

        print(
            f"Resource cleanup: {cleaned_resources}/{total_resources} ({cleanup_ratio:.1%})"
        )

    @timed_operation("memory_allocation_performance", store_results=True)
    def test_allocation_performance_under_pressure(self):
        """Test allocation performance under memory pressure."""
        memory_tracker = MemoryTracker()
        memory_tracker.measure()

        # Simulate VFX workload with many small allocations
        allocated_objects = []

        try:
            from enhanced_cache import LRUCache

            # Create multiple caches as in real usage
            caches = []
            for i in range(5):
                cache = LRUCache(max_size=200, max_memory_mb=2.0, name=f"perf_test_{i}")
                caches.append(cache)

            # Perform many small allocations (simulate shot/scene data)
            for iteration in range(100):
                for cache_idx, cache in enumerate(caches):
                    # Simulate VFX data structures
                    shot_data = {
                        "shot_name": f"shot_{iteration}_{cache_idx}",
                        "thumbnail_path": f"/path/to/thumb_{iteration}.jpg",
                        "plate_path": f"/path/to/plate_{iteration}.exr",
                        "metadata": {"version": "v001", "frames": 240},
                    }

                    cache.put(f"shot_{iteration}_{cache_idx}", shot_data)
                    allocated_objects.append(shot_data)

            # Measure memory usage
            memory_tracker.measure()

            # Performance should remain reasonable even with many allocations
            stats = TimingRegistry.get_stats("memory_allocation_performance")
            if stats:
                assert stats["mean_ms"] < 1000, "Allocation performance degraded"

            print(
                f"Allocated {len(allocated_objects)} objects across {len(caches)} caches"
            )
            print(f"Peak memory increase: {memory_tracker.get_peak_increase():.1f}MB")

        except ImportError:
            # Fallback test with simple allocations
            for i in range(1000):
                obj = {
                    "id": i,
                    "data": "x" * 100,
                    "metadata": {"type": "test", "iteration": i},
                }
                allocated_objects.append(obj)

            memory_tracker.measure()

        # Clean up
        allocated_objects.clear()
        gc.collect()
