"""Tests for RefreshCoordinator class."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject

from controllers.refresh_coordinator import RefreshCoordinator


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_main_window() -> Mock:
    """Create mock MainWindow with necessary attributes."""
    main_window = Mock()

    # Tab widget
    main_window.tab_widget = Mock()
    main_window.tab_widget.currentIndex = Mock(return_value=0)

    # Shot model
    main_window.shot_model = Mock()
    main_window.shot_model.refresh_shots = Mock(return_value=(True, True))
    main_window.shot_model.shots = []
    main_window.shot_model.find_shot_by_name = Mock(return_value=None)
    main_window.shot_model.get_available_shows = Mock(return_value=set())

    # Shot item model
    main_window.shot_item_model = Mock()
    main_window.shot_item_model.set_shots = Mock()

    # Shot grid
    main_window.shot_grid = Mock()
    main_window.shot_grid.populate_show_filter = Mock()
    main_window.shot_grid.select_shot_by_name = Mock()

    # 3DE controller
    main_window.threede_controller = Mock()
    main_window.threede_controller.refresh_threede_scenes = Mock()

    # Previous shots model
    main_window.previous_shots_model = Mock()
    main_window.previous_shots_model.refresh_shots = Mock()

    # Status update (method name without underscore - matches main_window.py)
    main_window.update_status = Mock()

    # Last selected shot (property name without underscore - matches main_window.py)
    main_window.last_selected_shot_name = None

    return main_window


@pytest.fixture
def mock_progress_manager(mocker) -> Mock:
    """Mock ProgressManager at system boundary."""
    mock = mocker.patch("controllers.refresh_coordinator.ProgressManager")
    progress_op = Mock()
    progress_op.set_indeterminate = Mock()

    # Support both old context manager pattern and new manual pattern
    mock.start_operation = Mock(return_value=progress_op)
    mock.finish_operation = Mock()
    # Legacy support for any remaining context manager tests
    progress_op.__enter__ = Mock(return_value=progress_op)
    progress_op.__exit__ = Mock(return_value=False)
    mock.operation = Mock(return_value=progress_op)
    return mock


@pytest.fixture
def mock_notification_manager(mocker) -> Mock:
    """Mock NotificationManager at system boundary."""
    mock = mocker.patch("controllers.refresh_coordinator.NotificationManager")
    mock.info = Mock()
    mock.success = Mock()
    mock.error = Mock()
    return mock


@pytest.fixture
def orchestrator(qapp: QApplication, mock_main_window: Mock) -> RefreshCoordinator:
    """Create RefreshCoordinator instance."""
    return RefreshCoordinator(mock_main_window)


# ============================================================================
# Initialization Tests
# ============================================================================


def test_initialization(qapp: QApplication, mock_main_window: Mock) -> None:
    """Test RefreshCoordinator initialization."""
    orchestrator = RefreshCoordinator(mock_main_window)

    assert orchestrator.main_window is mock_main_window
    assert isinstance(orchestrator, QObject)


# ============================================================================
# Tab Refresh Routing Tests
# ============================================================================


def test_refresh_current_tab_gets_current_index(
    orchestrator: RefreshCoordinator, mock_main_window: Mock, mocker
) -> None:
    """Test refresh_current_tab routes to refresh_tab with the current tab index."""
    mock_main_window.tab_widget.currentIndex.return_value = 1

    mock_refresh = mocker.patch.object(orchestrator, "refresh_tab")
    orchestrator.refresh_current_tab()

    mock_refresh.assert_called_once_with(1)


def test_refresh_tab_ignores_invalid_index(
    orchestrator: RefreshCoordinator,
    mocker,
) -> None:
    """Test refresh_tab ignores invalid tab indices gracefully."""
    # Invalid indices should emit signal but not call any refresh method
    mock_shots = mocker.patch.object(orchestrator, "_refresh_shots")
    mock_threede = mocker.patch.object(orchestrator, "_refresh_threede")
    mock_previous = mocker.patch.object(orchestrator, "_refresh_previous")
    orchestrator.refresh_tab(99)  # Invalid index

    # None of the refresh methods should be called
    mock_shots.assert_not_called()
    mock_threede.assert_not_called()
    mock_previous.assert_not_called()


# ============================================================================
# 3DE Refresh Tests
# ============================================================================


# ============================================================================
# Signal Handler Tests - Refresh Finished
# ============================================================================


def test_handle_refresh_finished_with_success_and_changes(
    orchestrator: RefreshCoordinator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished with success and changes."""
    orchestrator.handle_refresh_finished(success=True, has_changes=True)

    # Should not call status or notification (handled by shots_changed signal)
    mock_notification_manager.info.assert_not_called()
    mock_notification_manager.success.assert_not_called()
    mock_notification_manager.error.assert_not_called()


def test_handle_refresh_finished_with_success_no_changes(
    orchestrator: RefreshCoordinator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished with success but no changes."""
    mock_main_window.shot_model.shots = [Mock(), Mock()]

    orchestrator.handle_refresh_finished(success=True, has_changes=False)

    mock_main_window.update_status.assert_called_once_with("2 shots (no changes)")
    mock_notification_manager.info.assert_called_once_with("2 shots (no changes)")


def test_handle_refresh_finished_restores_last_selected_shot(
    orchestrator: RefreshCoordinator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished selects the previously selected shot in the grid."""
    mock_main_window.last_selected_shot_name = "test_shot_001"

    mock_shot = Mock()
    mock_shot.full_name = "show_test_shot_001"
    mock_main_window.shot_model.find_shot_by_name.return_value = mock_shot

    orchestrator.handle_refresh_finished(success=True, has_changes=False)

    mock_main_window.shot_grid.select_shot_by_name.assert_called_once_with(
        "show_test_shot_001"
    )


def test_handle_refresh_finished_shows_error_on_failure(
    orchestrator: RefreshCoordinator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished shows error notification on failure."""
    orchestrator.handle_refresh_finished(success=False, has_changes=False)

    mock_main_window.update_status.assert_called_once_with("Failed to refresh shots")
    mock_notification_manager.error.assert_called_once_with(
        "Failed to Load Shots",
        "Unable to retrieve shot data from the workspace.",
        "Make sure the 'ws -sg' command is available and you're in a valid workspace.",
    )


# ============================================================================
# Previous Shots Trigger Tests
# ============================================================================


def test_trigger_previous_shots_refresh_when_shots_exist(
    orchestrator: RefreshCoordinator, mock_main_window: Mock
) -> None:
    """Test trigger_previous_shots_refresh triggers refresh when shots exist."""
    shots = [Mock(), Mock()]

    orchestrator.trigger_previous_shots_refresh(shots)

    mock_main_window.previous_shots_model.refresh_shots.assert_called_once()


def test_trigger_previous_shots_refresh_skips_when_no_shots(
    orchestrator: RefreshCoordinator, mock_main_window: Mock
) -> None:
    """Test trigger_previous_shots_refresh skips when no shots."""
    orchestrator.trigger_previous_shots_refresh([])

    mock_main_window.previous_shots_model.refresh_shots.assert_not_called()


# ============================================================================
# Debouncing Tests (Issue #2 Fix)
# ============================================================================


def test_refresh_shot_display_debounces_rapid_calls(
    qapp: QApplication, orchestrator: RefreshCoordinator, mock_main_window: Mock
) -> None:
    """Test that rapid refresh_shot_display calls are debounced.

    Issue #2 fix: Prevents duplicate set_shots() and populate_show_filter()
    when both shots_loaded and shots_changed signals fire rapidly within 500ms.

    Simulates cooldown expiry by stopping the QTimer directly (equivalent to
    the 500ms interval elapsing without a real-time wait).
    """
    # Track call count
    call_count = 0
    original_set_shots = mock_main_window.shot_item_model.set_shots

    def counting_set_shots(shots):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return original_set_shots(shots)

    mock_main_window.shot_item_model.set_shots = counting_set_shots

    # Call refresh multiple times rapidly (within 500ms debounce window)
    orchestrator.refresh_shot_display()
    orchestrator.refresh_shot_display()
    orchestrator.refresh_shot_display()

    # Should only execute once due to debouncing (first call goes through)
    assert call_count == 1, "Expected exactly 1 call due to debouncing"

    # Simulate cooldown expiry by stopping the timer (equivalent to 500ms elapsing)
    orchestrator._refresh_debounce_timer.stop()

    # Now a new call should execute (debounce window expired)
    orchestrator.refresh_shot_display()
    assert call_count == 2, "Expected 2nd call after debounce window expired"
