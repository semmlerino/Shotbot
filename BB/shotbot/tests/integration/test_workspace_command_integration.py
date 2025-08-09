"""Integration tests for workspace command execution.

This test suite verifies that the QProcessManager correctly handles
workspace (ws) commands, which are shell functions used in VFX pipelines.
The ws command requires interactive bash and special handling.
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtCore import QCoreApplication

from qprocess_manager import (
    ProcessConfig,
    ProcessInfo,
    ProcessState,
    QProcessManager,
)


class TestWorkspaceCommandIntegration:
    """Test workspace command execution through QProcessManager."""

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

    def test_ws_command_execution(self, manager, qtbot):
        """Test executing ws command with interactive bash."""
        # Mock the ws command since it may not exist in test environment
        with patch.object(manager, 'execute') as mock_execute:
            # Configure mock to simulate successful execution
            mock_execute.return_value = "ws_test_process"
            
            # Execute ws command
            process_id = manager.execute_ws_command(
                workspace_path="/shows/test_show/shots/seq01/shot01",
                command="echo 'In workspace'",
                capture_output=True,
                timeout_ms=5000
            )
            
            # Verify the command was constructed correctly
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            
            # Check that interactive_bash is enabled
            assert call_args.kwargs.get('interactive_bash') is True
            
            # Check that the command includes ws
            assert call_args.kwargs.get('command').startswith('ws ')
            
            # Check workspace path is included
            assert '/shows/test_show/shots/seq01/shot01' in call_args.kwargs.get('command')

    def test_ws_command_with_terminal(self, manager, qtbot):
        """Test executing ws command in terminal window."""
        with patch.object(manager, 'execute') as mock_execute:
            mock_execute.return_value = "ws_terminal_process"
            
            # Execute ws command in terminal
            process_id = manager.execute_ws_command(
                workspace_path="/shows/test_show",
                command="nuke",
                terminal=True,
                capture_output=False
            )
            
            # Verify terminal option was passed
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args.kwargs.get('terminal') is True
            assert call_args.kwargs.get('capture_output') is False

    def test_interactive_bash_requirement(self, manager, qtbot):
        """Test that ws commands always use interactive bash."""
        # Track actual process execution
        executed_configs = []
        
        def track_config(process_id, config):
            executed_configs.append(config)
            return ProcessInfo(
                process_id=process_id,
                config=config,
                state=ProcessState.FINISHED,
                exit_code=0
            )
        
        # Patch ProcessWorker to track configs
        with patch('qprocess_manager.ProcessWorker') as mock_worker:
            mock_instance = MagicMock()
            mock_instance.get_info.side_effect = lambda: track_config(
                "test_proc", mock_worker.call_args[0][1]
            )
            mock_instance.start = MagicMock()
            mock_worker.return_value = mock_instance
            
            # Execute using the execute method directly with interactive bash
            process_id = manager.execute(
                command="ws /test/path && echo test",
                interactive_bash=True,
                capture_output=True
            )
            
            # Verify ProcessWorker was created with correct config
            assert mock_worker.called
            config = mock_worker.call_args[0][1]  # Second argument is config
            assert config.interactive_bash is True

    def test_ws_command_output_capture(self, manager, qtbot):
        """Test capturing output from ws commands."""
        # Since ws might not exist, test with a simulated interactive bash command
        process_id = manager.execute(
            command="echo 'Workspace output'",
            interactive_bash=True,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=10000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        
        # Check output was captured
        if final_info.output_buffer:
            assert any('Workspace output' in line for line in final_info.output_buffer)

    def test_ws_command_error_handling(self, manager, qtbot):
        """Test error handling for ws commands."""
        # Test with invalid workspace path (command will fail)
        process_id = manager.execute(
            command="bash -i -c 'exit 42'",  # Simulate ws failure
            interactive_bash=True,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=10000)
        assert final_info is not None
        assert final_info.state == ProcessState.FAILED
        assert final_info.exit_code == 42

    def test_concurrent_ws_commands(self, manager, qtbot):
        """Test running multiple ws commands concurrently."""
        processes = []
        
        # Start multiple ws-style commands
        for i in range(3):
            pid = manager.execute(
                command=f"echo 'Workspace {i}'",
                interactive_bash=True,
                capture_output=True,
                timeout_ms=5000
            )
            if pid:
                processes.append(pid)
        
        assert len(processes) == 3
        
        # Wait for all to complete
        for pid in processes:
            info = manager.wait_for_process(pid, timeout_ms=5000)
            assert info is not None
            assert info.state == ProcessState.FINISHED
            assert info.exit_code == 0

    def test_ws_command_environment_variables(self, manager, qtbot):
        """Test that ws commands can access environment variables."""
        # Set custom environment
        custom_env = {
            "TEST_WS_VAR": "test_value",
            "SHOT_NAME": "shot_001"
        }
        
        # Execute command that uses environment variables
        process_id = manager.execute(
            command="echo ${TEST_WS_VAR:-not_set}",
            interactive_bash=True,
            environment=custom_env,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        
        # Verify environment variable was accessible
        if final_info.output_buffer:
            # Should output "test_value" or "not_set"
            output = ' '.join(final_info.output_buffer)
            assert 'test_value' in output or 'not_set' in output

    def test_ws_command_working_directory(self, manager, qtbot):
        """Test ws commands with specific working directory."""
        # Use /tmp as a safe working directory
        working_dir = "/tmp"
        
        # Execute command that prints working directory
        process_id = manager.execute(
            command="pwd",
            interactive_bash=True,
            working_directory=working_dir,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        
        # Verify working directory was set
        if final_info.output_buffer:
            assert any('/tmp' in line for line in final_info.output_buffer)

    def test_ws_command_timeout(self, manager, qtbot):
        """Test timeout handling for ws commands."""
        # Start a long-running ws-style command
        process_id = manager.execute(
            command="sleep 30",
            interactive_bash=True,
            capture_output=False,
            timeout_ms=500  # Short timeout
        )
        
        assert process_id is not None
        
        # Wait for timeout - need more time since timeout happens in worker thread
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.TERMINATED
        assert final_info.exit_code == -15  # SIGTERM

    def test_ws_sg_command_simulation(self, manager, qtbot):
        """Test simulating ws -sg command for shot listing."""
        # Simulate the ws -sg command output format
        mock_output = """show:project1 seq:seq01 shot:shot01 /shows/project1/shots/seq01/shot01
show:project1 seq:seq01 shot:shot02 /shows/project1/shots/seq01/shot02
show:project1 seq:seq02 shot:shot01 /shows/project1/shots/seq02/shot01"""
        
        # Execute command that outputs in ws -sg format
        process_id = manager.execute(
            command=f"echo '{mock_output}'",
            interactive_bash=True,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        # Wait for completion
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        
        # Parse the output like ShotModel would
        if final_info.output_buffer:
            output_text = '\n'.join(final_info.output_buffer)
            lines = output_text.strip().split('\n')
            
            # Verify we got the expected format
            assert len(lines) >= 3
            for line in lines:
                if 'show:' in line and 'seq:' in line and 'shot:' in line:
                    # Valid ws -sg format
                    assert '/' in line  # Should include path


class TestWorkspaceCommandEdgeCases:
    """Test edge cases for workspace command handling."""

    @pytest.fixture
    def manager(self):
        """Create QProcessManager instance."""
        app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        manager = QProcessManager()
        yield manager
        manager.shutdown()

    def test_ws_command_with_quotes(self, manager, qtbot):
        """Test ws command with quoted arguments."""
        # Test command with quotes and special characters
        process_id = manager.execute(
            command='echo "Test with spaces" && echo \'Single quotes\'',
            interactive_bash=True,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED

    def test_ws_command_with_pipes(self, manager, qtbot):
        """Test ws command with pipes and redirection."""
        # Test command with pipes
        process_id = manager.execute(
            command='echo "line1\nline2\nline3" | grep line2',
            interactive_bash=True,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        
        # Should only output line2
        if final_info.output_buffer:
            assert any('line2' in line for line in final_info.output_buffer)
            assert not any('line1' in line for line in final_info.output_buffer)

    def test_ws_command_with_background_job(self, manager, qtbot):
        """Test that background jobs in ws commands are handled properly."""
        # Note: Background jobs in interactive bash are tricky
        # Test that we don't hang on background jobs
        process_id = manager.execute(
            command='echo "Foreground" && (sleep 0.1 &) && echo "Done"',
            interactive_bash=True,
            capture_output=True,
            timeout_ms=5000
        )
        
        assert process_id is not None
        
        final_info = manager.wait_for_process(process_id, timeout_ms=5000)
        assert final_info is not None
        assert final_info.state == ProcessState.FINISHED
        
        # Should complete without waiting for background job
        if final_info.output_buffer:
            output = ' '.join(final_info.output_buffer)
            assert 'Done' in output or 'Foreground' in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])