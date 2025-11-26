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
    from pytest_qt.qtbot import QtBot

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
    """Test refresh_current_tab gets tab index from widget."""
    mock_main_window.tab_widget.currentIndex.return_value = 1

    with patch.object(orchestrator, "refresh_tab") as mock_refresh:
        orchestrator.refresh_current_tab()

        mock_main_window.tab_widget.currentIndex.assert_called_once()
        mock_refresh.assert_called_once_with(1)


def test_refresh_tab_emits_refresh_started(
    orchestrator: RefreshOrchestrator, qtbot: QtBot
) -> None:
    """Test refresh_tab emits refresh_started signal."""
    with qtbot.waitSignal(orchestrator.refresh_started) as blocker, patch.object(
        orchestrator, "_refresh_shots"
    ):
        orchestrator.refresh_tab(0)

    assert blocker.args == [0]


def test_refresh_tab_routes_to_shots_for_index_0(
    orchestrator: RefreshOrchestrator,
) -> None:
    """Test refresh_tab routes index 0 to _refresh_shots."""
    with patch.object(orchestrator, "_refresh_shots") as mock_refresh:
        orchestrator.refresh_tab(0)

        mock_refresh.assert_called_once()


def test_refresh_tab_routes_to_threede_for_index_1(
    orchestrator: RefreshOrchestrator,
) -> None:
    """Test refresh_tab routes index 1 to _refresh_threede."""
    with patch.object(orchestrator, "_refresh_threede") as mock_refresh:
        orchestrator.refresh_tab(1)

        mock_refresh.assert_called_once()


def test_refresh_tab_routes_to_previous_for_index_2(
    orchestrator: RefreshOrchestrator,
) -> None:
    """Test refresh_tab routes index 2 to _refresh_previous."""
    with patch.object(orchestrator, "_refresh_previous") as mock_refresh:
        orchestrator.refresh_tab(2)

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
# Shot Refresh Tests
# ============================================================================


def test_refresh_shots_uses_progress_manager(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_progress_manager: Mock,
) -> None:
    """Test _refresh_shots uses ProgressManager context."""
    orchestrator._refresh_shots()

    mock_progress_manager.operation.assert_called_once_with(
        "Refreshing shots", cancelable=False
    )


def test_refresh_shots_sets_indeterminate_progress(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_progress_manager: Mock,
) -> None:
    """Test _refresh_shots sets indeterminate progress."""
    orchestrator._refresh_shots()

    progress_op = mock_progress_manager.operation.return_value
    progress_op.set_indeterminate.assert_called_once()


def test_refresh_shots_calls_model_refresh(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_progress_manager: Mock,
) -> None:
    """Test _refresh_shots calls shot_model.refresh_shots."""
    orchestrator._refresh_shots()

    mock_main_window.shot_model.refresh_shots.assert_called_once()


def test_refresh_shots_emits_finished_signal_on_success(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_progress_manager: Mock,
    qtbot: QtBot,
) -> None:
    """Test _refresh_shots emits refresh_finished with success=True."""
    mock_main_window.shot_model.refresh_shots.return_value = (True, True)

    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_shots()

    assert blocker.args == [0, True]


def test_refresh_shots_emits_finished_signal_on_failure(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_progress_manager: Mock,
    qtbot: QtBot,
) -> None:
    """Test _refresh_shots emits refresh_finished with success=False."""
    mock_main_window.shot_model.refresh_shots.return_value = (False, False)

    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_shots()

    assert blocker.args == [0, False]


# ============================================================================
# 3DE Refresh Tests
# ============================================================================


def test_refresh_threede_calls_controller_when_available(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_threede calls controller when available."""
    orchestrator._refresh_threede()

    mock_main_window.threede_controller.refresh_threede_scenes.assert_called_once()


def test_refresh_threede_emits_success_when_controller_available(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock, qtbot: QtBot
) -> None:
    """Test _refresh_threede emits success when controller available."""
    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_threede()

    assert blocker.args == [1, True]


def test_refresh_threede_handles_missing_controller(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_threede handles missing controller gracefully."""
    del mock_main_window.threede_controller

    orchestrator._refresh_threede()  # Should not raise


def test_refresh_threede_emits_failure_when_controller_missing(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock, qtbot: QtBot
) -> None:
    """Test _refresh_threede emits failure when controller missing."""
    del mock_main_window.threede_controller

    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_threede()

    assert blocker.args == [1, False]


def test_refresh_threede_handles_none_controller(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock, qtbot: QtBot
) -> None:
    """Test _refresh_threede handles None controller."""
    mock_main_window.threede_controller = None

    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_threede()

    assert blocker.args == [1, False]


# ============================================================================
# Previous Shots Refresh Tests
# ============================================================================


def test_refresh_previous_calls_model_when_available(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_previous calls model when available."""
    orchestrator._refresh_previous()

    mock_main_window.previous_shots_model.refresh_shots.assert_called_once()


def test_refresh_previous_emits_success_when_model_available(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock, qtbot: QtBot
) -> None:
    """Test _refresh_previous emits success when model available."""
    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_previous()

    assert blocker.args == [2, True]


def test_refresh_previous_handles_missing_model(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_previous handles missing model gracefully."""
    del mock_main_window.previous_shots_model

    orchestrator._refresh_previous()  # Should not raise


def test_refresh_previous_emits_failure_when_model_missing(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock, qtbot: QtBot
) -> None:
    """Test _refresh_previous emits failure when model missing."""
    del mock_main_window.previous_shots_model

    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_previous()

    assert blocker.args == [2, False]


def test_refresh_previous_handles_none_model(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock, qtbot: QtBot
) -> None:
    """Test _refresh_previous handles None model."""
    mock_main_window.previous_shots_model = None

    with qtbot.waitSignal(orchestrator.refresh_finished) as blocker:
        orchestrator._refresh_previous()

    assert blocker.args == [2, False]


# ============================================================================
# Signal Handler Tests - Shots Loaded
# ============================================================================


def test_handle_shots_loaded_refreshes_display(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_shots_loaded refreshes shot display."""
    shots = [Mock(), Mock(), Mock()]

    with patch.object(orchestrator, "_refresh_shot_display") as mock_refresh:
        orchestrator.handle_shots_loaded(shots)

        mock_refresh.assert_called_once()


def test_handle_shots_loaded_updates_status(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_shots_loaded updates status bar."""
    shots = [Mock(), Mock()]

    with patch.object(orchestrator, "_update_status") as mock_update:
        orchestrator.handle_shots_loaded(shots)

        mock_update.assert_called_once_with("Loaded 2 shots")


def test_handle_shots_loaded_shows_notification(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_shots_loaded shows info notification."""
    shots = [Mock(), Mock(), Mock()]

    orchestrator.handle_shots_loaded(shots)

    # Updated to match actual notification message (without "from cache")
    mock_notification_manager.info.assert_called_once_with("3 shots loaded")


# ============================================================================
# Signal Handler Tests - Shots Changed
# ============================================================================


def test_handle_shots_changed_refreshes_display(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_shots_changed refreshes shot display."""
    shots = [Mock(), Mock()]

    with patch.object(orchestrator, "_refresh_shot_display") as mock_refresh:
        orchestrator.handle_shots_changed(shots)

        mock_refresh.assert_called_once()


def test_handle_shots_changed_updates_status(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_shots_changed updates status bar."""
    shots = [Mock(), Mock(), Mock()]

    with patch.object(orchestrator, "_update_status") as mock_update:
        orchestrator.handle_shots_changed(shots)

        mock_update.assert_called_once_with("Shot list updated: 3 shots")


def test_handle_shots_changed_shows_success_notification(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_shots_changed shows success notification."""
    shots = [Mock(), Mock()]

    orchestrator.handle_shots_changed(shots)

    mock_notification_manager.success.assert_called_once_with("Refreshed 2 shots")


# ============================================================================
# Signal Handler Tests - Refresh Started
# ============================================================================


def test_handle_refresh_started_updates_status(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test handle_refresh_started updates status bar."""
    with patch.object(orchestrator, "_update_status") as mock_update:
        orchestrator.handle_refresh_started()

        mock_update.assert_called_once_with("Refreshing shots...")


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

    with patch.object(orchestrator, "_update_status") as mock_update:
        orchestrator.handle_refresh_finished(success=True, has_changes=False)

        mock_update.assert_called_once_with("2 shots (no changes)")
        mock_notification_manager.info.assert_called_once_with("2 shots (no changes)")


def test_handle_refresh_finished_restores_last_selected_shot(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished restores last selected shot."""
    mock_main_window.last_selected_shot_name = "test_shot_001"

    mock_shot = Mock()
    mock_shot.full_name = "show_test_shot_001"
    mock_main_window.shot_model.find_shot_by_name.return_value = mock_shot

    orchestrator.handle_refresh_finished(success=True, has_changes=False)

    mock_main_window.shot_model.find_shot_by_name.assert_called_once_with(
        "test_shot_001"
    )
    mock_main_window.shot_grid.select_shot_by_name.assert_called_once_with(
        "show_test_shot_001"
    )


def test_handle_refresh_finished_skips_restore_if_shot_not_found(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished skips restore if shot not found."""
    mock_main_window.last_selected_shot_name = "missing_shot"
    mock_main_window.shot_model.find_shot_by_name.return_value = None

    orchestrator.handle_refresh_finished(success=True, has_changes=False)

    mock_main_window.shot_grid.select_shot_by_name.assert_not_called()


def test_handle_refresh_finished_refreshes_threede_on_success(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished refreshes 3DE scenes on success."""
    mock_main_window.shot_model.shots = [Mock()]

    orchestrator.handle_refresh_finished(success=True, has_changes=True)

    mock_main_window.threede_controller.refresh_threede_scenes.assert_called_once()


def test_handle_refresh_finished_skips_threede_if_no_shots(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished skips 3DE refresh if no shots."""
    mock_main_window.shot_model.shots = []

    orchestrator.handle_refresh_finished(success=True, has_changes=True)

    mock_main_window.threede_controller.refresh_threede_scenes.assert_not_called()


def test_handle_refresh_finished_skips_threede_if_controller_missing(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished skips 3DE refresh if controller missing."""
    mock_main_window.shot_model.shots = [Mock()]
    del mock_main_window.threede_controller

    orchestrator.handle_refresh_finished(success=True, has_changes=True)
    # Should not raise


def test_handle_refresh_finished_shows_error_on_failure(
    orchestrator: RefreshOrchestrator,
    mock_main_window: Mock,
    mock_notification_manager: Mock,
) -> None:
    """Test handle_refresh_finished shows error notification on failure."""
    with patch.object(orchestrator, "_update_status") as mock_update:
        orchestrator.handle_refresh_finished(success=False, has_changes=False)

        mock_update.assert_called_once_with("Failed to refresh shots")
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


def test_trigger_previous_shots_refresh_handles_missing_model(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test trigger_previous_shots_refresh handles missing model."""
    del mock_main_window.previous_shots_model

    orchestrator.trigger_previous_shots_refresh([Mock()])
    # Should not raise


def test_trigger_previous_shots_refresh_handles_none_model(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test trigger_previous_shots_refresh handles None model."""
    mock_main_window.previous_shots_model = None

    orchestrator.trigger_previous_shots_refresh([Mock()])
    # Should not raise


# ============================================================================
# Helper Method Tests - Refresh Shot Display
# ============================================================================


def test_refresh_shot_display_updates_item_model(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_shot_display updates shot item model."""
    mock_shots = [Mock(), Mock()]
    mock_main_window.shot_model.shots = mock_shots

    orchestrator._refresh_shot_display()

    mock_main_window.shot_item_model.set_shots.assert_called_once_with(mock_shots)


def test_refresh_shot_display_populates_show_filter(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_shot_display populates show filter."""
    orchestrator._refresh_shot_display()

    mock_main_window.shot_grid.populate_show_filter.assert_called_once_with(
        mock_main_window.shot_model
    )


def test_refresh_shot_display_handles_missing_attributes(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _refresh_shot_display handles missing attributes gracefully."""
    del mock_main_window.shot_item_model

    orchestrator._refresh_shot_display()  # Should not raise


# ============================================================================
# Helper Method Tests - Update Status
# ============================================================================


def test_update_status_calls_main_window_method(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _update_status calls main_window.update_status (no underscore)."""
    orchestrator._update_status("Test message")

    mock_main_window.update_status.assert_called_once_with("Test message")


def test_update_status_handles_missing_method(
    orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test _update_status handles missing method gracefully."""
    del mock_main_window.update_status

    orchestrator._update_status("Test message")  # Should not raise


# ============================================================================
# Debouncing Tests (Issue #2 Fix)
# ============================================================================


def test_refresh_shot_display_debounces_rapid_calls(
    qapp: QApplication, qtbot: QtBot, orchestrator: RefreshOrchestrator, mock_main_window: Mock
) -> None:
    """Test that rapid _refresh_shot_display calls are debounced.

    Issue #2 fix: Prevents duplicate set_shots() and populate_show_filter()
    when both shots_loaded and shots_changed signals fire rapidly within 500ms.
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
    orchestrator._refresh_shot_display()
    orchestrator._refresh_shot_display()
    orchestrator._refresh_shot_display()

    # Should only execute once due to debouncing (first call goes through)
    assert call_count == 1, "Expected exactly 1 call due to debouncing"

    # Wait for debounce interval to pass (500ms + 200ms margin)
    qtbot.wait(700)

    # Now a new call should execute (debounce window expired)
    orchestrator._refresh_shot_display()
    assert call_count == 2, "Expected 2nd call after debounce window expired"
