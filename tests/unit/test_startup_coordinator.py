"""Tests for StartupCoordinator."""

from __future__ import annotations

import pytest

from workers.startup_coordinator import StartupCoordinator


pytestmark = [
    pytest.mark.unit,
]


# ============================================================================
# StartupCoordinator Tests
# ============================================================================


class TestStartupCoordinator:
    """Tests for the StartupCoordinator background thread."""

    def test_do_work_executes_warming_command(self, mocker) -> None:
        """StartupCoordinator calls execute_workspace_command to warm the session."""
        mock_pool = mocker.Mock()
        mock_pool.execute_workspace_command = mocker.Mock(return_value="warming")

        warmer = StartupCoordinator(mock_pool)
        warmer.do_work()

        mock_pool.execute_workspace_command.assert_called_once()
        call_args = mock_pool.execute_workspace_command.call_args
        assert call_args[0][0] == "echo warming"

    def test_do_work_stops_early_if_should_stop(self, mocker) -> None:
        """StartupCoordinator skips the command when should_stop() returns True."""
        mock_pool = mocker.Mock()

        warmer = StartupCoordinator(mock_pool)
        warmer.request_stop()  # Signal stop before work starts
        warmer.do_work()

        mock_pool.execute_workspace_command.assert_not_called()

    def test_do_work_swallows_exception_without_raising(self, mocker) -> None:
        """StartupCoordinator does not propagate exceptions from the warming command."""
        mock_pool = mocker.Mock()
        mock_pool.execute_workspace_command = mocker.Mock(
            side_effect=RuntimeError("subprocess failed")
        )

        warmer = StartupCoordinator(mock_pool)
        # Should not raise
        warmer.do_work()
