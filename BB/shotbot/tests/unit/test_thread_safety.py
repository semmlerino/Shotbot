"""Unit tests for thread-safe architecture components."""

import concurrent.futures
import threading
import time

import pytest
from PySide6.QtCore import QProcess

from memory_safe_cache import LRUCache, MemoryMonitor
from progressive_scanner import FileScanner, ScanState
from qprocess_manager import ManagedProcess, ProcessConfig
from thread_safe_manager import (
    AtomicCounter,
    DeadlockPreventingLockManager,
    LockContext,
    LockHierarchy,
    ProcessInfo,
    ProcessState,
    ResourcePool,
    ThreadSafeCollection,
    ThreadSafeProcessManager,
)


class TestThreadSafeCollection:
    """Test ThreadSafeCollection for thread safety."""

    def test_concurrent_add_remove(self):
        """Test concurrent add and remove operations."""
        collection = ThreadSafeCollection[str]("test")
        errors = []

        def add_items(start, count):
            try:
                for i in range(start, start + count):
                    key = f"item_{i}"
                    collection.add(key, f"value_{i}")
                    time.sleep(0.001)  # Small delay to increase contention
            except Exception as e:
                errors.append(e)

        def remove_items(start, count):
            try:
                for i in range(start, start + count):
                    key = f"item_{i}"
                    time.sleep(0.002)  # Small delay
                    collection.remove(key)
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []

            # Add items
            for i in range(5):
                futures.append(executor.submit(add_items, i * 20, 20))

            # Wait for adds to complete
            concurrent.futures.wait(futures)

            # Now remove items
            futures = []
            for i in range(5):
                futures.append(executor.submit(remove_items, i * 20, 10))

            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors occurred: {errors}"
        # Should have 50 items remaining (100 added, 50 removed)
        assert collection.size() == 50

    def test_safe_iteration_during_modification(self):
        """Test safe iteration while collection is being modified."""
        collection = ThreadSafeCollection[int]("test")

        # Add initial items
        for i in range(100):
            collection.add(f"key_{i}", i)

        results = []
        errors = []

        def iterate_collection():
            try:
                with collection.safe_iteration() as snapshot:
                    for key, value in snapshot.items():
                        results.append(value)
                        time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def modify_collection():
            try:
                # Add new items
                for i in range(100, 150):
                    collection.add(f"key_{i}", i)
                    time.sleep(0.001)

                # Remove some items
                for i in range(0, 25):
                    collection.remove(f"key_{i}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Run iteration and modification concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(iterate_collection),
                executor.submit(modify_collection),
            ]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors occurred: {errors}"
        # Iterator should have seen exactly 100 items (the snapshot)
        assert len(results) == 100
        # Collection should now have 125 items (100 + 50 - 25)
        assert collection.size() == 125


class TestDeadlockPrevention:
    """Test deadlock prevention in lock manager."""

    def test_lock_hierarchy_enforcement(self):
        """Test that lock hierarchy is enforced."""
        manager = DeadlockPreventingLockManager()

        # Create locks at different levels
        global_lock = LockContext("global", LockHierarchy.GLOBAL, threading.RLock())
        collection_lock = LockContext(
            "collection", LockHierarchy.COLLECTION, threading.RLock()
        )

        # Should be able to acquire in correct order
        assert manager.acquire(global_lock)
        assert manager.acquire(collection_lock)

        manager.release(collection_lock)
        manager.release(global_lock)

        # Should not be able to acquire in wrong order
        assert manager.acquire(collection_lock)
        assert not manager.acquire(global_lock)  # Should fail

        manager.release(collection_lock)

    def test_timeout_handling(self):
        """Test lock timeout handling."""
        manager = DeadlockPreventingLockManager()
        lock = LockContext("test", LockHierarchy.GLOBAL, threading.RLock())

        # Acquire lock in another thread and hold it
        def hold_lock():
            manager.acquire(lock)
            time.sleep(2)  # Hold for 2 seconds
            manager.release(lock)

        thread = threading.Thread(target=hold_lock)
        thread.start()

        time.sleep(0.1)  # Let other thread acquire lock

        # Try to acquire with short timeout
        assert not manager.acquire(lock, timeout=0.5)

        thread.join()


class TestProcessManager:
    """Test thread-safe process manager."""

    def test_process_state_transitions(self):
        """Test valid process state transitions."""
        manager = ThreadSafeProcessManager(max_processes=5)

        process_info = ProcessInfo(
            process_id="test_1",
            launcher_id="launcher_1",
            launcher_name="Test Launcher",
            command="echo test",
        )

        # Register process
        assert manager.register_process(process_info)
        assert process_info.state == ProcessState.STARTING

        # Valid transitions
        manager.update_process_state("test_1", ProcessState.RUNNING)
        assert process_info.state == ProcessState.RUNNING

        manager.update_process_state("test_1", ProcessState.COMPLETED, exit_code=0)
        assert process_info.state == ProcessState.COMPLETED
        assert process_info.exit_code == 0

    def test_max_processes_limit(self):
        """Test that max processes limit is enforced."""
        manager = ThreadSafeProcessManager(max_processes=2)

        # Register first two processes
        for i in range(2):
            process_info = ProcessInfo(
                process_id=f"test_{i}",
                launcher_id=f"launcher_{i}",
                launcher_name=f"Test {i}",
                command=f"echo {i}",
            )
            assert manager.register_process(process_info)

        # Third process should fail
        process_info = ProcessInfo(
            process_id="test_2",
            launcher_id="launcher_2",
            launcher_name="Test 2",
            command="echo 2",
        )
        assert not manager.register_process(process_info)

        # Mark one as completed
        manager.update_process_state("test_0", ProcessState.COMPLETED)

        # Now should be able to register new process
        assert manager.register_process(process_info)


class TestMemoryCache:
    """Test memory-safe cache implementation."""

    def test_lru_eviction(self):
        """Test LRU eviction policy."""
        cache = LRUCache[str](max_size=3)

        # Add items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # Access key1 to make it recently used
        assert cache.get("key1") == "value1"

        # Add new item, should evict key2 (least recently used)
        cache.put("key4", "value4")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = LRUCache[str](ttl_seconds=0.5)  # 500ms TTL

        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

        time.sleep(0.6)  # Wait for expiration

        assert cache.get("key1") is None  # Should be expired

    def test_memory_limit(self):
        """Test memory-based eviction."""
        cache = LRUCache[bytes](max_memory_mb=0.001)  # 1KB limit

        # Add items that exceed memory limit
        cache.put("key1", b"x" * 500)  # 500 bytes
        cache.put("key2", b"x" * 500)  # 500 bytes
        cache.put("key3", b"x" * 500)  # 500 bytes - should trigger eviction

        # Should have evicted some entries to stay under limit
        stats = cache.get_stats()
        assert stats["memory_mb"] <= 0.001


class TestResourcePool:
    """Test resource pool management."""

    def test_resource_acquisition_release(self):
        """Test resource acquisition and release."""
        created_count = 0
        cleaned_count = 0

        def create_resource():
            nonlocal created_count
            created_count += 1
            return f"resource_{created_count}"

        def cleanup_resource(resource):
            nonlocal cleaned_count
            cleaned_count += 1

        pool = ResourcePool(
            name="test_pool",
            factory=create_resource,
            max_size=3,
            cleanup_func=cleanup_resource,
        )

        # Acquire resources
        r1 = pool.acquire()
        r2 = pool.acquire()
        assert created_count == 2

        # Release one
        pool.release(r1)

        # Acquire again - should reuse
        r3 = pool.acquire()
        assert r3 == r1  # Reused
        assert created_count == 2  # No new creation

        # Clean up
        pool.shutdown()
        assert cleaned_count == 2  # Both resources cleaned

    def test_resource_context_manager(self):
        """Test resource pool context manager."""
        pool = ResourcePool(
            name="test_pool",
            factory=lambda: "resource",
            max_size=1,
        )

        with pool.resource() as r1:
            assert r1 == "resource"

            # Try to acquire another - should timeout
            with pytest.raises(RuntimeError):
                with pool.resource(timeout=0.1) as r2:
                    pass  # Should not reach here


class TestAtomicCounter:
    """Test atomic counter operations."""

    def test_concurrent_increments(self):
        """Test concurrent increment operations."""
        counter = AtomicCounter()
        errors = []

        def increment_many():
            try:
                for _ in range(1000):
                    counter.increment()
            except Exception as e:
                errors.append(e)

        # Run multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=increment_many)
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

        assert len(errors) == 0
        assert counter.get() == 10000  # 10 threads * 1000 increments

    def test_compare_and_swap(self):
        """Test atomic compare-and-swap operation."""
        counter = AtomicCounter(initial=5)

        # Successful CAS
        assert counter.compare_and_swap(5, 10)
        assert counter.get() == 10

        # Failed CAS (value changed)
        assert not counter.compare_and_swap(5, 15)
        assert counter.get() == 10  # Unchanged


class TestQProcessManager:
    """Test QProcess-based process management."""

    @pytest.mark.skipif(
        not hasattr(QProcess, "start"),
        reason="QProcess not available in test environment",
    )
    def test_process_lifecycle(self, qtbot):
        """Test QProcess lifecycle management."""
        config = ProcessConfig(
            command="echo",
            args=["test"],
            timeout_seconds=5,
        )

        process = ManagedProcess("test_process", config)

        # Connect to signals
        started = []
        finished = []

        process.started.connect(lambda: started.append(True))
        process.finished.connect(lambda code, status: finished.append((code, status)))

        # Start process
        assert process.start()

        # Wait for completion
        qtbot.wait(1000)  # Wait up to 1 second

        assert len(started) == 1
        assert len(finished) == 1
        assert finished[0][0] == 0  # Exit code should be 0

    def test_process_timeout(self, qtbot):
        """Test process timeout handling."""
        config = ProcessConfig(
            command="sleep",
            args=["10"],
            timeout_seconds=0.5,  # 500ms timeout
        )

        process = ManagedProcess("test_timeout", config)

        timeout_reached = []
        process.timeout_reached.connect(lambda: timeout_reached.append(True))

        # Start process
        process.start()

        # Wait for timeout
        qtbot.wait(1000)

        assert len(timeout_reached) == 1
        assert not process.is_running()


class TestFileScanner:
    """Test progressive file scanner."""

    def test_basic_scanning(self, tmp_path):
        """Test basic file scanning functionality."""
        # Create test files
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file3.py").write_text("print('hello')")

        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file4.txt").write_text("content4")

        # Scan for txt files
        scanner = FileScanner(
            root_path=tmp_path,
            file_patterns=["*.txt"],
        )

        results = list(scanner.scan())

        # Should find 3 txt files
        txt_files = [r for r in results if r.file_type == ".txt"]
        assert len(txt_files) == 3

    def test_scan_cancellation(self, tmp_path):
        """Test scan cancellation."""
        # Create many files
        for i in range(100):
            (tmp_path / f"file{i}.txt").write_text(f"content{i}")

        scanner = FileScanner(
            root_path=tmp_path,
            file_patterns=["*.txt"],
        )

        results = []
        for result in scanner.scan():
            results.append(result)
            if len(results) == 10:
                scanner.cancel()

        # Should have stopped after cancellation
        assert len(results) <= 15  # Some buffer for in-flight operations
        assert scanner._state == ScanState.CANCELLED


class TestMemoryMonitor:
    """Test memory monitoring functionality."""

    def test_memory_info(self):
        """Test memory information retrieval."""
        monitor = MemoryMonitor()

        info = monitor.get_memory_info()

        assert "process_rss_mb" in info
        assert "system_percent" in info
        assert "under_pressure" in info

        # Process should be using some memory
        assert info["process_rss_mb"] > 0

    def test_memory_pressure_detection(self):
        """Test memory pressure detection."""
        monitor = MemoryMonitor()
        monitor._memory_threshold_percent = 1  # Set very low threshold

        assert monitor.is_under_pressure()  # Should detect pressure

        monitor._memory_threshold_percent = 99  # Set very high threshold
        assert not monitor.is_under_pressure()  # Should not detect pressure
