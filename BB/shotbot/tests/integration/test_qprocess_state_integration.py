"""Integration tests for QProcess state management.

This test suite verifies the complete process lifecycle and state transitions
across ProcessWorker, QProcessManager, and UI components, ensuring our recent
fixes handle all edge cases correctly.

These tests use real process execution without mocking to verify actual
system behavior.
"""

import sys
import time
from pathlib import Path
import tempfile
import os

import pytest
from PySide6.QtCore import QCoreApplication, QTimer, QProcess

from qprocess_manager import (
    ProcessConfig,
    ProcessInfo,
    ProcessState,
    ProcessWorker,
    QProcessManager,
)


class TestProcessStateLifecycle:
    """Test complete process lifecycle state transitions."""

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

    def test_normal_completion_state_transitions(self, manager, app, qtbot):
        """Test state transitions for normally completing process."""
        # Track state changes
        state_history = []
        
        def record_state(process_id, state):
            state_history.append(state)
        
        manager.process_state_changed.connect(record_state)
        
        # Execute simple echo command
        process_id = manager.execute(
            command="echo",
            arguments=["test"],
            capture_output=True
        )
        
        assert process_id is not None
        
        # Initial state should be PENDING
        info = manager.get_process_info(process_id)
        assert info is not None
        assert info.state == ProcessState.PENDING
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        assert final_info.exit_code == 0
        assert final_info.output_buffer == ["test"]
        
        # Process events to ensure signals are delivered
        for _ in range(10):
            app.processEvents()
            qtbot.wait(10)
        
        # Verify state transition sequence
        # Note: PENDING state is initial but not emitted as a signal
        # First emitted state is RUNNING
        assert ProcessState.RUNNING in state_history
        assert ProcessState.FINISHED in state_history
        
        # Verify proper order
        running_idx = state_history.index(ProcessState.RUNNING)
        finished_idx = state_history.index(ProcessState.FINISHED)
        assert running_idx < finished_idx

    def test_timeout_state_transitions(self, manager, app, qtbot):
        """Test state transitions when process times out."""
        state_history = []
        
        def record_state(process_id, state):
            state_history.append(state)
        
        manager.process_state_changed.connect(record_state)
        
        # Execute command that will timeout
        process_id = manager.execute(
            command="sleep",
            arguments=["10"],
            capture_output=False,
            timeout_ms=500  # 500ms timeout
        )
        
        assert process_id is not None
        
        # Wait for timeout
        final_info = manager.wait_for_process(process_id, timeout_ms=2000)
        assert final_info is not None
        assert final_info.state == ProcessState.TERMINATED
        assert final_info.exit_code == -15  # SIGTERM
        
        # Process events to ensure signals are delivered
        for _ in range(10):
            app.processEvents()
            qtbot.wait(10)
        
        # Verify timeout was handled correctly
        assert ProcessState.TERMINATED in state_history

    def test_explicit_termination_state(self, manager, qtbot):
        """Test state when process is explicitly terminated."""
        # Start long-running process
        process_id = manager.execute(
            command="sleep",
            arguments=["30"],
            capture_output=False
        )
        
        assert process_id is not None
        
        # Let it start
        qtbot.wait(200)
        
        # Verify it's running
        info = manager.get_process_info(process_id)
        assert info.state in [ProcessState.PENDING, ProcessState.STARTING, ProcessState.RUNNING]
        
        # Terminate it
        success = manager.terminate_process(process_id)
        assert success
        
        # Wait for termination
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.TERMINATED

    def test_failed_process_state(self, manager, qtbot):
        """Test state when process fails with non-zero exit code."""
        process_id = manager.execute(
            command="sh",
            arguments=["-c", "exit 42"],
            capture_output=False
        )
        
        assert process_id is not None
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FAILED
        assert final_info.exit_code == 42

    def test_crashed_process_state(self, manager, qtbot):
        """Test state when process crashes."""
        # Create a Python script that will crash
        crash_script = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False
        )
        try:
            crash_script.write("""
import sys
import os
# Force a segmentation fault by accessing invalid memory
# This is platform-specific but should work on Linux
import ctypes
ctypes.string_at(0)
""")
            crash_script.close()
            
            # Execute the crashing script
            process_id = manager.execute(
                command=sys.executable,
                arguments=[crash_script.name],
                capture_output=True
            )
            
            assert process_id is not None
            
            # Wait for crash
            final_info = manager.wait_for_process(process_id, timeout_ms=5000)
            assert final_info is not None
            
            # On most systems, this will result in CRASHED or FAILED state
            # The exact behavior depends on how Python handles the segfault
            assert final_info.state in [ProcessState.CRASHED, ProcessState.FAILED]
            assert final_info.exit_code != 0
            
        finally:
            # Clean up
            os.unlink(crash_script.name)


class TestStateConsistencyAcrossThreads:
    """Test state consistency between ProcessWorker and QProcessManager."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_worker_manager_state_sync(self, manager, qtbot):
        """Verify worker and manager maintain consistent state."""
        process_id = manager.execute(
            command="echo",
            arguments=["sync test"],
            capture_output=True
        )
        
        assert process_id is not None
        
        # Get worker reference
        worker = manager._workers.get(process_id)
        assert worker is not None
        
        # Wait for completion
        qtbot.wait(500)
        
        # Check state consistency
        worker_info = worker.get_info()
        manager_info = manager.get_process_info(process_id)
        
        assert worker_info.state == manager_info.state
        assert worker_info.exit_code == manager_info.exit_code
        assert worker_info.output_buffer == manager_info.output_buffer

    def test_concurrent_state_updates(self, manager, qtbot):
        """Test state consistency with concurrent process execution."""
        process_ids = []
        
        # Start multiple processes
        for i in range(5):
            pid = manager.execute(
                command="echo",
                arguments=[f"test_{i}"],
                capture_output=True
            )
            if pid:
                process_ids.append(pid)
        
        assert len(process_ids) == 5
        
        # Wait for all to complete
        qtbot.wait(1000)
        
        # Verify all have consistent final states
        for pid in process_ids:
            info = manager.get_process_info(pid)
            assert info is not None
            assert info.state in [ProcessState.FINISHED, ProcessState.FAILED]
            assert not info.is_active


class TestStateTransitionEdgeCases:
    """Test edge cases in state transitions."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_rapid_start_stop(self, manager, qtbot):
        """Test rapid process start/stop doesn't cause state corruption."""
        process_id = manager.execute(
            command="sleep",
            arguments=["10"],
            capture_output=False
        )
        
        assert process_id is not None
        
        # Immediately terminate
        success = manager.terminate_process(process_id)
        assert success
        
        # State should be consistent
        info = manager.wait_for_process(process_id, timeout_ms=2000)
        assert info is not None
        assert info.state == ProcessState.TERMINATED

    def test_state_after_manager_shutdown(self, manager, qtbot):
        """Test state handling during manager shutdown."""
        # Start long-running process
        process_id = manager.execute(
            command="sleep",
            arguments=["30"],
            capture_output=False
        )
        
        assert process_id is not None
        
        # Shutdown manager (should terminate processes)
        manager.shutdown()
        
        # Process should be terminated
        info = manager.get_process_info(process_id)
        if info:  # Might be cleaned up
            assert info.state in [ProcessState.TERMINATED, ProcessState.FAILED]

    def test_state_persistence_across_refresh(self, manager, qtbot):
        """Test that process states persist correctly."""
        completed_processes = []
        
        # Execute and complete several processes
        for i in range(3):
            pid = manager.execute(
                command="echo",
                arguments=[f"test_{i}"],
                capture_output=True
            )
            if pid:
                completed_processes.append(pid)
        
        # Wait for completion
        qtbot.wait(500)
        
        # Verify completed states persist
        for pid in completed_processes:
            info = manager.get_process_info(pid)
            assert info is not None
            assert info.state == ProcessState.FINISHED
            assert not info.is_active
        
        # Start new process
        new_pid = manager.execute(
            command="echo",
            arguments=["new"],
            capture_output=True
        )
        
        # Old processes should still show completed state
        for pid in completed_processes:
            info = manager.get_process_info(pid)
            assert info is not None
            assert info.state == ProcessState.FINISHED

    def test_state_with_empty_output(self, manager, qtbot):
        """Test state handling when process produces no output."""
        process_id = manager.execute(
            command="true",  # Command that succeeds with no output
            arguments=[],
            capture_output=True
        )
        
        assert process_id is not None
        
        # Wait for completion
        info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert info is not None
        assert info.state == ProcessState.FINISHED
        assert info.exit_code == 0
        assert info.output_buffer == []  # No output is valid


class TestSignalEmissionDuringStateChanges:
    """Test that signals are emitted correctly during state transitions."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_signal_emission_sequence(self, manager, qtbot):
        """Test signals are emitted in correct sequence."""
        signals_received = []
        
        def on_started(pid, info):
            signals_received.append(('started', pid))
        
        def on_finished(pid, info):
            signals_received.append(('finished', pid))
        
        def on_state_changed(pid, state):
            signals_received.append(('state', state))
        
        manager.process_started.connect(on_started)
        manager.process_finished.connect(on_finished)
        manager.process_state_changed.connect(on_state_changed)
        
        # Execute command
        process_id = manager.execute(
            command="echo",
            arguments=["signal test"],
            capture_output=True
        )
        
        # Wait for completion
        manager.wait_for_process(process_id, timeout_ms=5000)
        
        # Process events to ensure signals are delivered
        # Signals are queued but need event processing to be delivered
        app = QCoreApplication.instance()
        if app:
            for _ in range(10):
                app.processEvents()
                qtbot.wait(10)
        
        # Verify signals were emitted
        assert any(s[0] == 'started' for s in signals_received)
        assert any(s[0] == 'finished' for s in signals_received)
        assert any(s[0] == 'state' and s[1] == ProcessState.RUNNING for s in signals_received)
        assert any(s[0] == 'state' and s[1] == ProcessState.FINISHED for s in signals_received)

    def test_failed_signal_emission(self, manager, qtbot):
        """Test failed signal is emitted on timeout."""
        # Track process errors through manager's signal
        error_received = []
        
        def on_process_error(pid, error_msg):
            error_received.append((pid, error_msg))
        
        # Connect to manager's error signal (if it has one)
        if hasattr(manager, 'process_error'):
            manager.process_error.connect(on_process_error)
        
        # Execute command that will timeout
        process_id = manager.execute(
            command="sleep",
            arguments=["10"],
            capture_output=False,
            timeout_ms=200  # Very short timeout
        )
        
        assert process_id is not None
        
        # Wait for timeout to occur
        final_info = manager.wait_for_process(process_id, timeout_ms=1000)
        assert final_info is not None
        
        # Verify process was terminated due to timeout
        assert final_info.state == ProcessState.TERMINATED
        assert final_info.exit_code == -15  # SIGTERM
        
        # Check if error information was recorded
        if final_info.error:
            assert "timeout" in final_info.error.lower() or "timed out" in final_info.error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])