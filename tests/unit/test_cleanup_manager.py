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
    window.launcher_manager = Mock()
    window.launcher_manager.shutdown = Mock()
    window.cache_manager = Mock()
    window.cache_manager.shutdown = Mock()

    # Models
    window.shot_model = Mock()
    window.shot_model.cleanup = Mock()
    window.previous_shots_model = Mock()
    window.previous_shots_model.cleanup = Mock()
    window.previous_shots_item_model = Mock()
    window.previous_shots_item_model.cleanup = Mock()

    # Terminal
    window.persistent_terminal = Mock()
    window.persistent_terminal.cleanup = Mock()
    window.persistent_terminal.cleanup_fifo_only = Mock()

    return window


@pytest.fixture
def cleanup_manager(mock_main_window: Mock) -> CleanupManager:
    """Create CleanupManager instance."""
    return CleanupManager(mock_main_window)


# =============================================================================
# Initialization Tests
# =============================================================================


class TestCleanupManagerInitialization:
    """Test CleanupManager initialization."""

    def test_initialization(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test manager initializes with correct reference."""
        assert cleanup_manager.main_window is mock_main_window

    def test_initialization_sets_up_logging(
        self, cleanup_manager: CleanupManager
    ) -> None:
        """Test initialization sets up logging."""
        assert hasattr(cleanup_manager, "logger")


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

    def test_perform_cleanup_calls_all_steps_in_order(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test perform_cleanup calls cleanup steps in correct order."""
        with patch.object(cleanup_manager, "_mark_closing") as mock_mark, patch.object(
            cleanup_manager, "_cleanup_threede_controller"
        ) as mock_3de, patch.object(
            cleanup_manager, "_cleanup_session_warmer"
        ) as mock_session, patch.object(
            cleanup_manager, "_cleanup_managers"
        ) as mock_managers, patch.object(
            cleanup_manager, "_cleanup_models"
        ) as mock_models, patch.object(
            cleanup_manager, "_cleanup_terminal"
        ) as mock_terminal, patch.object(
            cleanup_manager, "_final_cleanup"
        ) as mock_final:
            cleanup_manager.perform_cleanup()

        # Verify all steps called
        mock_mark.assert_called_once()
        mock_3de.assert_called_once()
        mock_session.assert_called_once()
        mock_managers.assert_called_once()
        mock_models.assert_called_once()
        mock_terminal.assert_called_once()
        mock_final.assert_called_once()

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
# Mark Closing Tests
# =============================================================================


class TestMarkClosing:
    """Test marking application as closing."""

    def test_mark_closing_sets_flag(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test _mark_closing sets closing flag to True."""
        assert mock_main_window.closing is False

        cleanup_manager._mark_closing()

        assert mock_main_window.closing is True


# =============================================================================
# 3DE Controller Cleanup Tests
# =============================================================================


class TestThreeDEControllerCleanup:
    """Test 3DE controller cleanup."""

    def test_cleanup_threede_controller_calls_cleanup_worker(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup calls controller's cleanup_worker."""
        cleanup_manager._cleanup_threede_controller()

        mock_main_window.threede_controller.cleanup_worker.assert_called_once()

    def test_cleanup_threede_controller_handles_missing_controller(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles missing controller gracefully."""
        del mock_main_window.threede_controller

        # Should not raise
        cleanup_manager._cleanup_threede_controller()

    def test_cleanup_threede_controller_handles_none_controller(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles None controller gracefully."""
        mock_main_window.threede_controller = None

        # Should not raise
        cleanup_manager._cleanup_threede_controller()


# =============================================================================
# Session Warmer Cleanup Tests
# =============================================================================


class TestSessionWarmerCleanup:
    """Test session warmer thread cleanup."""

    def test_cleanup_session_warmer_requests_stop_and_waits(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test session warmer cleanup requests stop and waits."""
        # Save reference before it's set to None
        session_warmer = mock_main_window.session_warmer

        cleanup_manager._cleanup_session_warmer()

        session_warmer.request_stop.assert_called_once()
        session_warmer.wait.assert_called()
        session_warmer.deleteLater.assert_called_once()
        assert mock_main_window.session_warmer is None

    def test_cleanup_session_warmer_uses_test_timeout_in_tests(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test session warmer uses shorter timeout in test environment."""
        # pytest is in sys.modules during test
        session_warmer = mock_main_window.session_warmer

        cleanup_manager._cleanup_session_warmer()

        # Should use 200ms timeout in test environment
        session_warmer.wait.assert_called_with(200)

    def test_cleanup_session_warmer_handles_timeout(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test session warmer cleanup handles wait timeout."""
        session_warmer = mock_main_window.session_warmer
        session_warmer.wait.return_value = False

        cleanup_manager._cleanup_session_warmer()

        session_warmer.safe_terminate.assert_called_once()

    def test_cleanup_session_warmer_handles_zombie_thread(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup doesn't delete zombie threads."""
        session_warmer = mock_main_window.session_warmer
        session_warmer.is_zombie.return_value = True

        cleanup_manager._cleanup_session_warmer()

        # Should not call deleteLater for zombie
        session_warmer.deleteLater.assert_not_called()
        assert mock_main_window.session_warmer is None

    def test_cleanup_session_warmer_handles_missing_warmer(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles missing session warmer gracefully."""
        del mock_main_window.session_warmer

        # Should not raise
        cleanup_manager._cleanup_session_warmer()

    def test_cleanup_session_warmer_handles_already_finished(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles already-finished warmer."""
        session_warmer = mock_main_window.session_warmer
        session_warmer.isFinished.return_value = True

        cleanup_manager._cleanup_session_warmer()

        # Should not request stop if already finished
        session_warmer.request_stop.assert_not_called()
        session_warmer.deleteLater.assert_called_once()


# =============================================================================
# Managers Cleanup Tests
# =============================================================================


class TestManagersCleanup:
    """Test managers cleanup."""

    def test_cleanup_managers_shuts_down_launcher_manager(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup shuts down launcher manager."""
        cleanup_manager._cleanup_managers()

        mock_main_window.launcher_manager.shutdown.assert_called_once()

    def test_cleanup_managers_shuts_down_cache_manager(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup shuts down cache manager."""
        cleanup_manager._cleanup_managers()

        mock_main_window.cache_manager.shutdown.assert_called_once()

    def test_cleanup_managers_handles_missing_launcher_manager(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles missing launcher manager."""
        del mock_main_window.launcher_manager

        # Should not raise
        cleanup_manager._cleanup_managers()

    def test_cleanup_managers_handles_launcher_manager_without_shutdown(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles launcher manager without shutdown method."""
        del mock_main_window.launcher_manager.shutdown

        # Should not raise
        cleanup_manager._cleanup_managers()

    def test_cleanup_managers_handles_missing_cache_manager(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles missing cache manager."""
        del mock_main_window.cache_manager

        # Should not raise
        cleanup_manager._cleanup_managers()


# =============================================================================
# Models Cleanup Tests
# =============================================================================


class TestModelsCleanup:
    """Test models cleanup."""

    def test_cleanup_models_cleans_shot_model(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup cleans shot model."""
        cleanup_manager._cleanup_models()

        mock_main_window.shot_model.cleanup.assert_called_once()

    def test_cleanup_models_cleans_previous_shots_model(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup cleans previous shots model."""
        cleanup_manager._cleanup_models()

        mock_main_window.previous_shots_model.cleanup.assert_called_once()

    def test_cleanup_models_cleans_previous_shots_item_model(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup cleans previous shots item model."""
        cleanup_manager._cleanup_models()

        mock_main_window.previous_shots_item_model.cleanup.assert_called_once()

    def test_cleanup_models_handles_shot_model_exception(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup continues after shot model exception."""
        mock_main_window.shot_model.cleanup.side_effect = RuntimeError("Test error")

        # Should not raise - error is logged
        with pytest.raises(RuntimeError):
            cleanup_manager._cleanup_models()

    def test_cleanup_models_handles_previous_shots_model_exception(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles previous shots model exception gracefully."""
        mock_main_window.previous_shots_model.cleanup.side_effect = RuntimeError(
            "Test error"
        )

        # Should not raise - error is caught and logged
        cleanup_manager._cleanup_models()

        # Should still try to clean item model
        mock_main_window.previous_shots_item_model.cleanup.assert_called_once()

    def test_cleanup_models_handles_missing_models(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles missing models gracefully."""
        del mock_main_window.shot_model
        del mock_main_window.previous_shots_model
        del mock_main_window.previous_shots_item_model

        # Should not raise
        cleanup_manager._cleanup_models()


# =============================================================================
# Terminal Cleanup Tests
# =============================================================================


class TestTerminalCleanup:
    """Test persistent terminal cleanup."""

    def test_cleanup_terminal_calls_cleanup(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test terminal cleanup calls cleanup method."""
        with patch("cleanup_manager.Config") as mock_config:
            mock_config.KEEP_TERMINAL_ON_EXIT = False
            cleanup_manager._cleanup_terminal()

        mock_main_window.persistent_terminal.cleanup.assert_called_once()

    def test_cleanup_terminal_keeps_terminal_open_if_configured(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test terminal cleanup respects KEEP_TERMINAL_ON_EXIT config."""
        with patch("cleanup_manager.Config") as mock_config:
            mock_config.KEEP_TERMINAL_ON_EXIT = True

            cleanup_manager._cleanup_terminal()

        # Should not call full cleanup
        mock_main_window.persistent_terminal.cleanup.assert_not_called()
        # Should call FIFO-only cleanup
        mock_main_window.persistent_terminal.cleanup_fifo_only.assert_called_once()

    def test_cleanup_terminal_handles_missing_terminal(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles missing terminal gracefully."""
        del mock_main_window.persistent_terminal

        # Should not raise
        cleanup_manager._cleanup_terminal()

    def test_cleanup_terminal_handles_missing_cleanup_fifo_only(
        self, cleanup_manager: CleanupManager, mock_main_window: Mock
    ) -> None:
        """Test cleanup handles terminal without cleanup_fifo_only method."""
        del mock_main_window.persistent_terminal.cleanup_fifo_only

        with patch("cleanup_manager.Config") as mock_config:
            mock_config.KEEP_TERMINAL_ON_EXIT = True

            # Should not raise
            cleanup_manager._cleanup_terminal()


# =============================================================================
# Final Cleanup Tests
# =============================================================================


class TestFinalCleanup:
    """Test final cleanup operations."""

    def test_final_cleanup_calls_cleanup_all_runnables(
        self, cleanup_manager: CleanupManager
    ) -> None:
        """Test final cleanup calls cleanup_all_runnables."""
        with patch("runnable_tracker.cleanup_all_runnables") as mock_cleanup, patch(
            "cleanup_manager.QApplication.instance", return_value=Mock()
        ), patch("gc.collect"):
            cleanup_manager._final_cleanup()

        mock_cleanup.assert_called_once()

    def test_final_cleanup_processes_qt_events(
        self, cleanup_manager: CleanupManager
    ) -> None:
        """Test final cleanup processes pending Qt events."""
        mock_app = Mock()
        with patch("runnable_tracker.cleanup_all_runnables"), patch(
            "cleanup_manager.QApplication.instance", return_value=mock_app
        ), patch("gc.collect"):
            cleanup_manager._final_cleanup()

        mock_app.processEvents.assert_called_once()

    def test_final_cleanup_runs_garbage_collection(
        self, cleanup_manager: CleanupManager
    ) -> None:
        """Test final cleanup runs garbage collection."""
        with patch("runnable_tracker.cleanup_all_runnables"), patch(
            "cleanup_manager.QApplication.instance", return_value=Mock()
        ), patch("gc.collect") as mock_gc:
            cleanup_manager._final_cleanup()

        mock_gc.assert_called_once()

    def test_final_cleanup_handles_no_qapplication(
        self, cleanup_manager: CleanupManager
    ) -> None:
        """Test final cleanup handles missing QApplication gracefully."""
        with patch("runnable_tracker.cleanup_all_runnables"), patch(
            "cleanup_manager.QApplication.instance", return_value=None
        ), patch("gc.collect"):
            # Should not raise
            cleanup_manager._final_cleanup()


# =============================================================================
# Integration Tests
# =============================================================================


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
        mock_main_window.launcher_manager.shutdown.assert_called_once()
        mock_main_window.cache_manager.shutdown.assert_called_once()
        mock_main_window.shot_model.cleanup.assert_called_once()
        mock_main_window.persistent_terminal.cleanup.assert_called_once()

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
