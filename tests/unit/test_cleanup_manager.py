"""Comprehensive tests for cleanup_manager module.

Tests the CleanupManager class for resource cleanup orchestration following
UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

from cleanup_manager import CleanupManager


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_main_window() -> Mock:
    """Create mock MainWindow with all expected attributes."""
    window = Mock()
    window.closing = False

    # Controllers
    window.threede_controller = Mock()
    window.threede_controller.cleanup_worker = Mock()

    # Session warmer
    window.session_warmer = Mock()
    window.session_warmer.isFinished = Mock(return_value=False)
    window.session_warmer.request_stop = Mock()
    window.session_warmer.wait = Mock(return_value=True)
    window.session_warmer.safe_terminate = Mock()
    window.session_warmer.deleteLater = Mock()
    window.session_warmer.is_zombie = Mock(return_value=False)

    # Managers
    window.cache_manager = Mock()
    window.cache_manager.shutdown = Mock()

    # Models
    window.shot_model = Mock()
    window.shot_model.cleanup = Mock()
    window.previous_shots_model = Mock()
    window.previous_shots_model.cleanup = Mock()
    window.previous_shots_item_model = Mock()
    window.previous_shots_item_model.cleanup = Mock()

    return window


@pytest.fixture
def cleanup_manager(mock_main_window: Mock) -> CleanupManager:
    """Create CleanupManager instance."""
    return CleanupManager(mock_main_window)


# =============================================================================
# Initialization Tests
# =============================================================================


# =============================================================================
# Cleanup Orchestration Tests
# =============================================================================


class TestCleanupOrchestration:
    """Test cleanup orchestration and signal emission."""

    def test_perform_cleanup_emits_signals(
        self, cleanup_manager: CleanupManager, qtbot: QtBot
    ) -> None:
        """Test perform_cleanup emits started and finished signals."""
        with qtbot.waitSignal(cleanup_manager.cleanup_started), qtbot.waitSignal(
            cleanup_manager.cleanup_finished
        ):
            cleanup_manager.perform_cleanup()

    def test_perform_cleanup_emits_finished_even_on_exception(
        self, cleanup_manager: CleanupManager, qtbot: QtBot
    ) -> None:
        """Test cleanup_finished signal emitted even if exception occurs."""
        with patch.object(
            cleanup_manager, "_mark_closing", side_effect=RuntimeError("Test error")
        ), pytest.raises(RuntimeError), qtbot.waitSignal(
            cleanup_manager.cleanup_finished
        ):
            cleanup_manager.perform_cleanup()


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestCleanupIntegration:
    """Test complete cleanup workflows."""

    def test_full_cleanup_workflow(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock, qtbot: QtBot
    ) -> None:
        """Test complete cleanup workflow with all components."""
        # Save references before they're set to None
        session_warmer = mock_main_window.session_warmer

        with qtbot.waitSignal(
            cleanup_manager.cleanup_started
        ), qtbot.waitSignal(
            cleanup_manager.cleanup_finished
        ), patch(
            "runnable_tracker.cleanup_all_runnables"
        ), patch(
            "cleanup_manager.QApplication.instance", return_value=Mock()
        ), patch("gc.collect"):
            cleanup_manager.perform_cleanup()

        # Verify all cleanup methods called
        assert mock_main_window.closing is True
        mock_main_window.threede_controller.cleanup_worker.assert_called_once()
        session_warmer.deleteLater.assert_called_once()
        mock_main_window.cache_manager.shutdown.assert_called_once()
        mock_main_window.shot_model.cleanup.assert_called_once()

    def test_cleanup_with_partial_components(self) -> None:
        """Test cleanup works with only some components present."""
        # Create window with minimal components
        window = Mock()
        window.closing = False
        window.shot_model = Mock()
        window.shot_model.cleanup = Mock()
        # No other components

        manager = CleanupManager(window)

        with patch("runnable_tracker.cleanup_all_runnables"), patch(
            "cleanup_manager.QApplication.instance", return_value=Mock()
        ), patch("gc.collect"):
            # Should not raise
            manager.perform_cleanup()

        window.shot_model.cleanup.assert_called_once()

    def test_cleanup_resilient_to_multiple_exceptions(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock, qtbot: QtBot
    ) -> None:
        """Test cleanup continues despite multiple exceptions."""
        # Make multiple components raise exceptions
        mock_main_window.threede_controller.cleanup_worker.side_effect = RuntimeError(
            "3DE error"
        )
        mock_main_window.shot_model.cleanup.side_effect = RuntimeError("Model error")

        with patch("runnable_tracker.cleanup_all_runnables"), patch(
            "cleanup_manager.QApplication.instance", return_value=Mock()
        ), patch("gc.collect"), pytest.raises(
            RuntimeError, match="3DE error"
        ), qtbot.waitSignal(cleanup_manager.cleanup_finished):
            # Should raise first exception but still emit finished signal
            cleanup_manager.perform_cleanup()
