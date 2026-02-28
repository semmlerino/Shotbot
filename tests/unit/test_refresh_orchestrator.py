"""Tests for RefreshOrchestrator class."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QObject

from refresh_orchestrator import RefreshOrchestrator


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
def mock_progress_manager() -> Generator[Mock, None, None]:
    """Mock ProgressManager at system boundary."""
    with patch("refresh_orchestrator.ProgressManager") as mock:
        progress_op = Mock()
        progress_op.set_indeterminate = Mock()

        # Support both old context manager pattern and new manual pattern
        mock.start_operation = Mock(return_value=progress_op)
        mock.finish_operation = Mock()
        # Legacy support for any remaining context manager tests
        progress_op.__enter__ = Mock(return_value=progress_op)
        progress_op.__exit__ = Mock(return_value=False)
        mock.operation = Mock(return_value=progress_op)
        yield mock


@pytest.fixture
def mock_notification_manager() -> Generator[Mock, None, None]:
    """Mock NotificationManager at system boundary."""
    with patch("refresh_orchestrator.NotificationManager") as mock:
        mock.info = Mock()
        mock.success = Mock()
        mock.error = Mock()
        yield mock


@pytest.fixture
def orchestrator(qapp: QApplication, mock_main_window: Mock) -> RefreshOrchestrator:
    """Create RefreshOrchestrator instance."""
    return RefreshOrchestrator(mock_main_window)


# ============================================================================
# Initialization Tests
# ============================================================================


def test_initialization(qapp: QApplication, mock_main_window: Mock) -> None:
    """Test RefreshOrchestrator initialization."""
    orchestrator = RefreshOrchestrator(mock_main_window)

    assert orchestrator.main_window is mock_main_window
    assert isinstance(orchestrator, QObject)


# ============================================================================
# Tab Refresh Routing Tests
# ============================================================================


def test_refresh_current_tab_gets_current_index(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test refresh_current_tab routes to refresh_tab with the current tab index."""
    mock_main_window.tab_widget.currentIndex.return_value = 1

    with patch.object(orchestrator, "refresh_tab") as mock_refresh:
        orchestrator.refresh_current_tab()

        mock_refresh.assert_called_once_with(1)


@pytest.mark.parametrize(
    ("tab_index", "handler_name"),
    [
        (0, "_refresh_shots"),
        (1, "_refresh_threede"),
        (2, "_refresh_previous"),
    ],
)
def test_refresh_tab_routes_to_expected_handler(
    orchestrator: RefreshOrchestrator,
    tab_index: int,
    handler_name: str,
) -> None:
    """Test refresh_tab routes each valid index to the expected handler."""
    with patch.object(orchestrator, handler_name) as mock_refresh:
        orchestrator.refresh_tab(tab_index)
        mock_refresh.assert_called_once()


def test_refresh_tab_ignores_invalid_index(
    orchestrator: RefreshOrchestrator,
) -> None:
    """Test refresh_tab ignores invalid tab indices gracefully."""
    # Invalid indices should emit signal but not call any refresh method
    with (
        patch.object(orchestrator, "_refresh_shots") as mock_shots,
        patch.object(orchestrator, "_refresh_threede") as mock_threede,
        patch.object(orchestrator, "_refresh_previous") as mock_previous,
    ):
        orchestrator.refresh_tab(99)  # Invalid index

        # None of the refresh methods should be called
        mock_shots.assert_not_called()
        mock_threede.assert_not_called()
        mock_previous.assert_not_called()


# ============================================================================
# 3DE Refresh Tests
# ============================================================================


def test_refresh_threede_calls_controller_when_available(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_threede calls controller when available."""
    orchestrator._refresh_threede()

    mock_main_window.threede_controller.refresh_threede_scenes.assert_called_once()


# ============================================================================
# Previous Shots Refresh Tests
# ============================================================================


def test_refresh_previous_calls_model_when_available(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_previous calls model when available."""
    orchestrator._refresh_previous()

    mock_main_window.previous_shots_model.refresh_shots.assert_called_once()


# ============================================================================
# Signal Handler Tests - Refresh Finished
# ============================================================================


def test_handle_refresh_finished_with_success_and_changes(
    orchestrator: RefreshOrchestrator,
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
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished with success but no changes."""
    mock_main_window.shot_model.shots = [Mock(), Mock()]

    orchestrator.handle_refresh_finished(success=True, has_changes=False)

    mock_main_window.update_status.assert_called_once_with("2 shots (no changes)")
    mock_notification_manager.info.assert_called_once_with("2 shots (no changes)")


def test_handle_refresh_finished_restores_last_selected_shot(
    orchestrator: RefreshOrchestrator,
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
    orchestrator: RefreshOrchestrator,
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
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test trigger_previous_shots_refresh triggers refresh when shots exist."""
    shots = [Mock(), Mock()]

    orchestrator.trigger_previous_shots_refresh(shots)

    mock_main_window.previous_shots_model.refresh_shots.assert_called_once()


def test_trigger_previous_shots_refresh_skips_when_no_shots(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test trigger_previous_shots_refresh skips when no shots."""
    orchestrator.trigger_previous_shots_refresh([])

    mock_main_window.previous_shots_model.refresh_shots.assert_not_called()


# ============================================================================
# Debouncing Tests (Issue #2 Fix)
# ============================================================================


def test_refresh_shot_display_debounces_rapid_calls(
    qapp: QApplication, orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test that rapid _refresh_shot_display calls are debounced.

    Issue #2 fix: Prevents duplicate set_shots() and populate_show_filter()
    when both shots_loaded and shots_changed signals fire rapidly within 500ms.

    Uses time_machine to advance time deterministically instead of qtbot.wait(),
    which is susceptible to segfaults from stale Qt events left by prior tests.
    """
    import time

    import time_machine

    # Track call count
    call_count = 0
    original_set_shots = mock_main_window.shot_item_model.set_shots

    def counting_set_shots(shots):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return original_set_shots(shots)

    mock_main_window.shot_item_model.set_shots = counting_set_shots

    with time_machine.travel(time.time(), tick=False) as traveller:
        # Call refresh multiple times rapidly (within 500ms debounce window)
        orchestrator.refresh_shot_display()
        orchestrator.refresh_shot_display()
        orchestrator.refresh_shot_display()

        # Should only execute once due to debouncing (first call goes through)
        assert call_count == 1, "Expected exactly 1 call due to debouncing"

        # Advance past debounce interval (500ms + margin)
        traveller.shift(1.0)

        # Now a new call should execute (debounce window expired)
        orchestrator.refresh_shot_display()
        assert call_count == 2, "Expected 2nd call after debounce window expired"
