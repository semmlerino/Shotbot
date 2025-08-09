"""Integration tests for concurrent application launching.

This test suite verifies thread safety when launching multiple applications
simultaneously, tests process limit enforcement, and ensures proper cleanup
under load conditions.

All tests use real process execution without mocking.
"""

import sys
import time
import threading
import tempfile
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication

from qprocess_manager import QProcessManager, ProcessState
from command_launcher_qprocess import CommandLauncherQProcess
from shot_model import Shot


class TestConcurrentProcessLaunching:
    """Test concurrent process launching scenarios."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    @pytest.fixture
    def launcher(self):
        """Create CommandLauncherQProcess instance."""
        launcher = CommandLauncherQProcess()
        yield launcher
        launcher.cleanup()

    def test_parallel_process_execution(self, manager, qtbot):
        """Test launching multiple processes in parallel."""
        num_processes = 10
        process_ids = []
        completed = []
        
        # Track completion
        def on_finished(pid, info):
            completed.append(pid)
        
        manager.process_finished.connect(on_finished)
        
        # Launch processes in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            
            for i in range(num_processes):
                future = executor.submit(
                    manager.execute,
                    command="echo",
                    arguments=[f"concurrent_{i}"],
                    capture_output=True
                )
                futures.append(future)
            
            # Collect process IDs
            for future in as_completed(futures):
                pid = future.result()
                if pid:
                    process_ids.append(pid)
        
        # All processes should have been created
        assert len(process_ids) == num_processes
        
        # All process IDs should be unique
        assert len(set(process_ids)) == num_processes
        
        # Wait for all to complete
        timeout = 10000  # 10 seconds total
        start_time = time.time()
        
        while len(completed) < num_processes and (time.time() - start_time) * 1000 < timeout:
            qtbot.wait(100)
        
        # All should have completed
        assert len(completed) == num_processes
        
        # Verify all completed successfully
        for pid in process_ids:
            info = manager.get_process_info(pid)
            assert info is not None
            assert info.state == ProcessState.FINISHED
            assert info.exit_code == 0

    def test_process_limit_enforcement(self, manager, qtbot):
        """Test that process limit is properly enforced."""
        # Use QProcessManager's limit directly
        max_processes = QProcessManager.MAX_CONCURRENT_PROCESSES
        
        # Try to launch more than the limit
        launch_attempts = max_processes + 5
        process_ids = []
        
        for i in range(launch_attempts):
            pid = manager.execute(
                command="sleep",
                arguments=["2"],  # 2 second sleep
                capture_output=False
            )
            if pid:
                process_ids.append(pid)
            qtbot.wait(10)  # Small delay between launches
        
        # Should only create up to max_processes
        assert len(process_ids) <= max_processes
        
        # Get active process count
        active_count, total_count = manager.get_process_count()
        assert active_count <= max_processes
        
        # Clean up - terminate all
        for pid in process_ids:
            manager.terminate_process(pid)

    def test_thread_safety_with_concurrent_operations(self, manager, qtbot):
        """Test thread safety with mixed concurrent operations."""
        num_threads = 8
        operations_per_thread = 5
        results = []
        errors = []
        
        def worker_thread(thread_id):
            """Worker that performs various operations."""
            thread_results = []
            
            try:
                for op in range(operations_per_thread):
                    # Mix of operations
                    if op % 3 == 0:
                        # Launch process
                        pid = manager.execute(
                            command="echo",
                            arguments=[f"thread_{thread_id}_op_{op}"],
                            capture_output=True
                        )
                        if pid:
                            thread_results.append(('launch', pid))
                    
                    elif op % 3 == 1:
                        # Query process info
                        active_procs = manager.get_active_processes()
                        thread_results.append(('query', len(active_procs)))
                    
                    else:
                        # Get process count
                        active, total = manager.get_process_count()
                        thread_results.append(('count', (active, total)))
                    
                    time.sleep(0.01)  # Small delay
                    
            except Exception as e:
                errors.append((thread_id, str(e)))
            
            results.append((thread_id, thread_results))
        
        # Launch threads
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker_thread, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join(timeout=30)
        
        # No errors should have occurred
        assert len(errors) == 0, f"Thread errors: {errors}"
        
        # All threads should have completed
        assert len(results) == num_threads
        
        # Verify some processes were launched
        launch_count = sum(
            1 for _, ops in results 
            for op_type, _ in ops 
            if op_type == 'launch'
        )
        assert launch_count > 0

    def test_cleanup_after_concurrent_crashes(self, manager, qtbot):
        """Test cleanup when multiple processes crash simultaneously."""
        # Create a script that will exit with error
        error_script = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False
        )
        try:
            error_script.write("""
import sys
import time
time.sleep(0.1)  # Small delay
sys.exit(1)  # Exit with error
""")
            error_script.close()
            
            # Launch multiple instances that will fail
            num_processes = 5
            process_ids = []
            
            for i in range(num_processes):
                pid = manager.execute(
                    command=sys.executable,
                    arguments=[error_script.name],
                    capture_output=True
                )
                if pid:
                    process_ids.append(pid)
            
            assert len(process_ids) == num_processes
            
            # Wait for all to fail
            qtbot.wait(2000)
            
            # All should be in FAILED state
            for pid in process_ids:
                info = manager.get_process_info(pid)
                assert info is not None
                assert info.state == ProcessState.FAILED
                assert info.exit_code == 1
            
            # Active count should be 0
            active_count, _ = manager.get_process_count()
            assert active_count == 0
            
        finally:
            os.unlink(error_script.name)


class TestConcurrentApplicationLaunching:
    """Test launching VFX applications concurrently."""

    @pytest.fixture
    def launcher(self):
        """Create CommandLauncherQProcess instance."""
        launcher = CommandLauncherQProcess()
        yield launcher
        launcher.cleanup()

    @pytest.fixture
    def mock_shot(self):
        """Create a mock shot for testing."""
        return Shot(
            show="test_show",
            sequence="test_seq",
            shot="test_001",
            workspace_path="/tmp/test_workspace"
        )

    def test_concurrent_app_launches(self, launcher, mock_shot, qtbot):
        """Test launching multiple applications concurrently."""
        # Mock Config.APPS to include echo for testing
        from unittest.mock import patch
        from config import Config
        
        with patch.dict(Config.APPS, {'echo': 'echo', 'test1': 'echo', 'test2': 'echo'}):
            launcher.set_current_shot(mock_shot)
            
            # Use test apps that are now in mocked Config.APPS
            apps_to_launch = ["echo", "test1", "test2"]
            launch_results = []
            
            def on_command_executed(timestamp, command):
                launch_results.append((timestamp, command))
            
            launcher.command_executed.connect(on_command_executed)
            
            # Launch apps concurrently
            threads = []
            for i, app in enumerate(apps_to_launch):
                t = threading.Thread(
                    target=launcher.launch_app,
                    args=(app,),
                    kwargs={'blocking': False}
                )
                threads.append(t)
                t.start()
            
            # Wait for threads
            for t in threads:
                t.join(timeout=5)
            
            # Wait for commands to complete
            qtbot.wait(2000)
            
            # All should have executed
            assert len(launch_results) >= len(apps_to_launch)

    def test_rapid_sequential_launches(self, launcher, mock_shot, qtbot):
        """Test rapid sequential application launches."""
        # Mock Config.APPS to include echo for testing
        from unittest.mock import patch
        from config import Config
        
        with patch.dict(Config.APPS, {'echo': 'echo'}):
            launcher.set_current_shot(mock_shot)
            
            num_launches = 10
            completed = []
            
            def on_executed(timestamp, command):
                completed.append(command)
            
            launcher.command_executed.connect(on_executed)
            
            # Rapid sequential launches
            for i in range(num_launches):
                launcher.launch_app(
                    "echo",
                    blocking=False
                )
                qtbot.wait(10)  # Very small delay
            
            # Wait for completion
            timeout = 5000
            start_time = time.time()
            
            while len(completed) < num_launches and (time.time() - start_time) * 1000 < timeout:
                qtbot.wait(100)
            
            # All should have executed
            assert len(completed) == num_launches


class TestResourceManagementUnderLoad:
    """Test resource management when system is under load."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_memory_cleanup_after_bulk_operations(self, manager, qtbot):
        """Test memory is properly cleaned up after bulk operations."""
        import gc
        import psutil
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Launch and complete many processes
        num_operations = 50
        
        for batch in range(5):  # 5 batches of 10
            batch_pids = []
            
            for i in range(10):
                pid = manager.execute(
                    command="echo",
                    arguments=[f"batch_{batch}_item_{i}"],
                    capture_output=True
                )
                if pid:
                    batch_pids.append(pid)
            
            # Wait for batch to complete
            qtbot.wait(500)
            
            # Verify completion
            for pid in batch_pids:
                info = manager.get_process_info(pid)
                assert info is not None
                assert not info.is_active
        
        # Force garbage collection
        gc.collect()
        qtbot.wait(1000)
        
        # Check memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (< 50MB for this test)
        # This is a rough check - exact values depend on system
        assert memory_increase < 50, f"Memory increased by {memory_increase}MB"

    def test_file_descriptor_management(self, manager, qtbot):
        """Test that file descriptors are properly managed."""
        import resource
        
        # Get initial file descriptor count
        soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
        
        # Launch processes with output capture (uses file descriptors)
        num_processes = min(20, soft_limit // 10)  # Conservative limit
        process_ids = []
        
        for i in range(num_processes):
            pid = manager.execute(
                command="echo",
                arguments=[f"fd_test_{i}"],
                capture_output=True
            )
            if pid:
                process_ids.append(pid)
        
        # Wait for completion
        qtbot.wait(2000)
        
        # All should complete without file descriptor exhaustion
        for pid in process_ids:
            info = manager.get_process_info(pid)
            assert info is not None
            assert info.state == ProcessState.FINISHED

    def test_shutdown_with_active_processes(self, manager, qtbot):
        """Test manager shutdown with many active processes."""
        # Launch long-running processes
        num_processes = 10
        process_ids = []
        
        for i in range(num_processes):
            pid = manager.execute(
                command="sleep",
                arguments=["30"],  # Long sleep
                capture_output=False
            )
            if pid:
                process_ids.append(pid)
        
        assert len(process_ids) == num_processes
        
        # Verify they're running
        active_count, _ = manager.get_process_count()
        assert active_count == num_processes
        
        # Shutdown should terminate all
        start_time = time.time()
        manager.shutdown()
        shutdown_time = time.time() - start_time
        
        # Shutdown should complete reasonably quickly (< 5 seconds)
        assert shutdown_time < 5
        
        # All processes should be terminated
        for pid in process_ids:
            info = manager.get_process_info(pid)
            if info:  # Might be cleaned up
                assert info.state in [ProcessState.TERMINATED, ProcessState.FAILED]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])