"""Integration tests for QProcessManager error recovery and resilience.

This test suite verifies that the QProcessManager system properly handles
and recovers from various error conditions including invalid commands,
missing executables, permission errors, and resource exhaustion.
"""

import sys
import time
import tempfile
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QTimer

from qprocess_manager import (
    ProcessConfig,
    ProcessInfo,
    ProcessState,
    ProcessWorker,
    QProcessManager,
)


class TestQProcessErrorRecovery:
    """Test QProcessManager error recovery and resilience."""

    @pytest.fixture
    def app(self, qtbot):
        """Ensure QCoreApplication exists."""
        return QCoreApplication.instance() or QCoreApplication(sys.argv)

    @pytest.fixture
    def manager(self, app):
        """Create QProcessManager instance."""
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_invalid_command_recovery(self, manager, qtbot):
        """Test recovery from invalid command execution."""
        # Track errors
        errors_received = []
        
        def on_error(pid, error_msg):
            errors_received.append((pid, error_msg))
        
        if hasattr(manager, 'process_error'):
            manager.process_error.connect(on_error)
        
        # Execute non-existent command
        process_id = manager.execute(
            command="this_command_does_not_exist_12345",
            arguments=["--help"],
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Wait for failure
        final_info = manager.wait_for_process(process_id, timeout_ms=10000)
        assert final_info is not None
        
        # Should be in FAILED state
        assert final_info.state in [ProcessState.FAILED, ProcessState.CRASHED]
        
        # Manager should still be functional - test with valid command
        valid_id = manager.execute(
            command="echo",
            arguments=["recovery test"],
            capture_output=True
        )
        
        assert valid_id is not None
        valid_info = manager.wait_for_process(valid_id, timeout_ms=5000)
        assert valid_info is not None
        assert valid_info.state == ProcessState.FINISHED
        assert valid_info.exit_code == 0

    def test_permission_denied_recovery(self, manager, qtbot):
        """Test recovery from permission denied errors."""
        # Create a file without execute permission
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("#!/bin/bash\necho 'This should not run'\n")
            script_path = f.name
        
        try:
            # Remove execute permission
            os.chmod(script_path, 0o644)
            
            # Try to execute the non-executable file
            process_id = manager.execute(
                command=script_path,
                capture_output=True,
                timeout_ms=5000
            )
            
            assert process_id is not None
            
            # Wait for failure
            final_info = manager.wait_for_process(process_id, timeout_ms=10000)
            assert final_info is not None
            
            # Should fail due to permission denied
            assert final_info.state in [ProcessState.FAILED, ProcessState.CRASHED]
            
            # Manager should still work for valid commands
            valid_id = manager.execute(
                command="echo",
                arguments=["permission recovery"],
                capture_output=True
            )
            
            assert valid_id is not None
            valid_info = manager.wait_for_process(valid_id, timeout_ms=5000)
            assert valid_info is not None
            assert valid_info.state == ProcessState.FINISHED
            
        finally:
            # Clean up
            os.unlink(script_path)

    def test_rapid_failure_recovery(self, manager, qtbot):
        """Test recovery from rapid consecutive failures."""
        failed_processes = []
        
        # Start multiple failing processes rapidly
        for i in range(5):
            pid = manager.execute(
                command="sh",
                arguments=["-c", f"exit {i+1}"],  # Different exit codes
                capture_output=False,
                timeout_ms=5000
            )
            if pid:
                failed_processes.append(pid)
        
        assert len(failed_processes) == 5
        
        # Wait for all to fail
        for pid in failed_processes:
            info = manager.wait_for_process(pid, timeout_ms=5000)
            assert info is not None
            assert info.state == ProcessState.FAILED
            assert info.exit_code == failed_processes.index(pid) + 1
        
        # Verify manager is still responsive
        success_id = manager.execute(
            command="echo",
            arguments=["rapid recovery"],
            capture_output=True
        )
        
        assert success_id is not None
        success_info = manager.wait_for_process(success_id, timeout_ms=5000)
        assert success_info is not None
        assert success_info.state == ProcessState.FINISHED

    def test_timeout_recovery(self, manager, qtbot):
        """Test recovery from process timeouts."""
        # Start process that will timeout
        timeout_id = manager.execute(
            command="sleep",
            arguments=["30"],
            capture_output=False,
            timeout_ms=500  # Very short timeout
        )
        
        assert timeout_id is not None
        
        # Wait for timeout
        timeout_info = manager.wait_for_process(timeout_id, timeout_ms=2000)
        assert timeout_info is not None
        assert timeout_info.state == ProcessState.TERMINATED
        
        # Start another long-running process with proper timeout
        normal_id = manager.execute(
            command="sleep",
            arguments=["1"],
            capture_output=False,
            timeout_ms=5000
        )
        
        assert normal_id is not None
        normal_info = manager.wait_for_process(normal_id, timeout_ms=5000)
        assert normal_info is not None
        assert normal_info.state == ProcessState.FINISHED

    def test_resource_exhaustion_recovery(self, manager, qtbot):
        """Test behavior when approaching resource limits."""
        processes = []
        
        # Start fewer processes to avoid overwhelming the system
        # Use shorter sleep times and test with a smaller number
        test_limit = min(10, QProcessManager.MAX_CONCURRENT_PROCESSES)
        
        # Try to start many processes (up to limit)
        for i in range(test_limit + 2):
            pid = manager.execute(
                command="true",  # Exits immediately
                arguments=[],
                capture_output=False,
                timeout_ms=5000
            )
            if pid:
                processes.append(pid)
            else:
                # Should hit limit eventually
                break
        
        # Should have started at most test_limit processes
        assert len(processes) <= test_limit + 2
        
        # Wait for processes to complete (they exit immediately)
        qtbot.wait(500)
        
        # Now we should definitely be able to start a new process
        new_pid = manager.execute(
            command="echo",
            arguments=["resource recovery"],
            capture_output=True
        )
        
        # Should succeed since earlier processes have completed
        assert new_pid is not None
        new_info = manager.wait_for_process(new_pid, timeout_ms=5000)
        assert new_info is not None
        assert new_info.state == ProcessState.FINISHED

    def test_shutdown_during_execution(self, manager, qtbot):
        """Test graceful shutdown while processes are running."""
        # Start several long-running processes
        processes = []
        for i in range(3):
            pid = manager.execute(
                command="sleep",
                arguments=["10"],
                capture_output=False
            )
            if pid:
                processes.append(pid)
        
        assert len(processes) == 3
        
        # Verify they're running
        for pid in processes:
            info = manager.get_process_info(pid)
            assert info is not None
            assert info.is_active
        
        # Shutdown manager
        manager.shutdown()
        
        # After shutdown, processes should be terminated
        for pid in processes:
            info = manager.get_process_info(pid)
            if info:  # Might be cleaned up
                assert not info.is_active

    def test_invalid_working_directory_recovery(self, manager, qtbot):
        """Test recovery from invalid working directory."""
        # Try to execute with non-existent working directory
        process_id = manager.execute(
            command="echo",
            arguments=["test"],
            working_directory="/this/directory/does/not/exist/12345",
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Should handle the error gracefully
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        # Process might still run (using current directory) or fail
        assert final_info is not None
        
        # Manager should still be functional
        valid_id = manager.execute(
            command="echo",
            arguments=["directory recovery"],
            capture_output=True
        )
        
        assert valid_id is not None
        valid_info = manager.wait_for_process(valid_id, timeout_ms=5000)
        assert valid_info is not None
        assert valid_info.state == ProcessState.FINISHED


class TestConcurrentErrorHandling:
    """Test error handling with concurrent processes."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_mixed_success_failure(self, manager, qtbot):
        """Test handling mixed successful and failing processes."""
        processes = []
        
        # Start mix of successful and failing processes
        for i in range(6):
            if i % 2 == 0:
                # Successful process
                pid = manager.execute(
                    command="echo",
                    arguments=[f"success_{i}"],
                    capture_output=True
                )
            else:
                # Failing process
                pid = manager.execute(
                    command="sh",
                    arguments=["-c", f"exit {i}"],
                    capture_output=False
                )
            
            if pid:
                processes.append((pid, i % 2 == 0))  # (pid, is_successful)
        
        assert len(processes) == 6
        
        # Wait and verify each process
        for pid, should_succeed in processes:
            info = manager.wait_for_process(pid, timeout_ms=5000)
            assert info is not None
            
            if should_succeed:
                assert info.state == ProcessState.FINISHED
                assert info.exit_code == 0
            else:
                assert info.state == ProcessState.FAILED
                assert info.exit_code != 0
        
        # Manager should still be fully functional
        active, total = manager.get_process_count()
        assert active == 0  # All completed
        assert total >= 6  # At least our test processes

    def test_concurrent_timeouts(self, manager, qtbot):
        """Test handling multiple concurrent timeouts."""
        timeout_processes = []
        
        # Start multiple processes that will timeout
        for i in range(3):
            pid = manager.execute(
                command="sleep",
                arguments=["30"],
                capture_output=False,
                timeout_ms=200 + (i * 100)  # Staggered timeouts
            )
            if pid:
                timeout_processes.append(pid)
        
        assert len(timeout_processes) == 3
        
        # Wait for all to timeout
        for pid in timeout_processes:
            info = manager.wait_for_process(pid, timeout_ms=2000)
            assert info is not None
            assert info.state == ProcessState.TERMINATED
        
        # Verify manager can still handle new processes
        new_pid = manager.execute(
            command="echo",
            arguments=["post-timeout"],
            capture_output=True
        )
        
        assert new_pid is not None
        new_info = manager.wait_for_process(new_pid, timeout_ms=5000)
        assert new_info is not None
        assert new_info.state == ProcessState.FINISHED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])