"""Tests for SessionWarmer."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from startup_coordinator import SessionWarmer


pytestmark = [
    pytest.mark.unit,
]


# ============================================================================
# SessionWarmer Tests
# ============================================================================


class TestSessionWarmer:
    """Tests for the SessionWarmer background thread."""

    def test_do_work_executes_warming_command(self) -> None:
        """SessionWarmer calls execute_workspace_command to warm the session."""
        mock_pool = Mock()
        mock_pool.execute_workspace_command = Mock(return_value="warming")

        warmer = SessionWarmer(mock_pool)
        warmer.do_work()

        mock_pool.execute_workspace_command.assert_called_once()
        call_args = mock_pool.execute_workspace_command.call_args
        assert call_args[0][0] == "echo warming"

    def test_do_work_stops_early_if_should_stop(self) -> None:
        """SessionWarmer skips the command when should_stop() returns True."""
        mock_pool = Mock()

        warmer = SessionWarmer(mock_pool)
        warmer.request_stop()  # Signal stop before work starts
        warmer.do_work()

        mock_pool.execute_workspace_command.assert_not_called()

    def test_do_work_swallows_exception_without_raising(self) -> None:
        """SessionWarmer does not propagate exceptions from the warming command."""
        mock_pool = Mock()
        mock_pool.execute_workspace_command = Mock(
            side_effect=RuntimeError("subprocess failed")
        )

        warmer = SessionWarmer(mock_pool)
        # Should not raise
        warmer.do_work()
