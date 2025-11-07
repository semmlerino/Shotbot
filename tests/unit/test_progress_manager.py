"""Comprehensive tests for progress_manager module.

Tests the ProgressManager singleton, ProgressOperation class, and convenience
functions following UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QProgressDialog, QStatusBar

from progress_manager import (
    ProgressConfig,
    ProgressManager,
    ProgressOperation,
    ProgressType,
    finish_progress,
    is_progress_cancelled,
    set_progress_indeterminate,
    set_progress_total,
    start_progress,
    update_progress,
)


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
def mock_notification_manager(status_bar: QStatusBar) -> Generator[Mock, None, None]:
    """Mock NotificationManager at system boundary."""
    with patch("progress_manager.NotificationManager") as mock:
        mock.get_status_bar.return_value = status_bar
        mock.progress.return_value = Mock(spec=QProgressDialog)
        mock.close_progress.return_value = None
        mock.success.return_value = None
        mock.info.return_value = None
        mock.error.return_value = None
        yield mock


@pytest.fixture
def status_bar(qtbot: QtBot) -> QStatusBar:
    """Create real QStatusBar for testing."""
    bar = QStatusBar()
    qtbot.addWidget(bar)
    return bar


@pytest.fixture
def progress_config() -> ProgressConfig:
    """Create default progress configuration."""
    return ProgressConfig(title="Test Operation", cancelable=False)


@pytest.fixture(autouse=True)
def reset_progress_manager() -> Generator[None, None, None]:
    """Reset ProgressManager singleton state before each test."""
    # Call clear_all_operations() FIRST to properly close Qt widgets
    with contextlib.suppress(Exception):
        ProgressManager.clear_all_operations()
    # Then clear singleton state
    ProgressManager._instance = None
    ProgressManager._operation_stack = []
    ProgressManager._status_bar = None
    yield
    # Cleanup after test (same pattern)
    with contextlib.suppress(Exception):
        ProgressManager.clear_all_operations()
    ProgressManager._instance = None
    ProgressManager._operation_stack = []
    ProgressManager._status_bar = None


# =============================================================================
# ProgressOperation Tests
# =============================================================================


class TestProgressOperation:
    """Test ProgressOperation state management and behavior."""

    def test_initialization(self, progress_config: ProgressConfig) -> None:
        """Test operation initializes with correct default state."""
        operation = ProgressOperation(progress_config)

        assert operation.config.title == "Test Operation"
        assert operation.current_value == 0
        assert operation.total_value == 0
        assert operation.is_indeterminate is True
        assert operation.is_cancelled_flag is False
        assert operation.progress_dialog is None
        assert operation.status_bar is None

    def test_set_total_switches_to_determinate(
        self, progress_config: ProgressConfig
    ) -> None:
        """Test setting total switches from indeterminate to determinate."""
        operation = ProgressOperation(progress_config)
        assert operation.is_indeterminate is True

        operation.set_total(100)

        assert operation.total_value == 100
        assert operation.is_indeterminate is False

    def test_set_indeterminate_clears_total(
        self, progress_config: ProgressConfig
    ) -> None:
        """Test setting indeterminate clears total and switches mode."""
        operation = ProgressOperation(progress_config)
        operation.set_total(100)

        operation.set_indeterminate()

        assert operation.is_indeterminate is True
        assert operation.total_value == 0

    def test_update_throttling(self, progress_config: ProgressConfig) -> None:
        """Test progress updates are throttled to prevent UI blocking."""
        config = ProgressConfig(title="Test", update_interval=100)  # 100ms throttle
        operation = ProgressOperation(config)
        operation.set_total(100)

        # First update should work
        operation.update(10, "Step 1")
        assert operation.current_value == 10
        assert operation.current_message == "Step 1"

        # Immediate second update should be ignored (throttled)
        operation.update(20, "Step 2")
        assert operation.current_value == 10  # Still old value
        assert operation.current_message == "Step 1"  # Still old message

    def test_update_without_throttling_after_interval(
        self, progress_config: ProgressConfig
    ) -> None:
        """Test updates work after throttle interval expires."""
        config = ProgressConfig(title="Test", update_interval=10)  # 10ms throttle
        operation = ProgressOperation(config)
        operation.set_total(100)

        operation.update(10, "Step 1")
        time.sleep(0.02)  # Wait 20ms (> 10ms throttle)
        operation.update(20, "Step 2")

        assert operation.current_value == 20
        assert operation.current_message == "Step 2"

    def test_cancellation(self, progress_config: ProgressConfig) -> None:
        """Test operation cancellation sets flag correctly."""
        operation = ProgressOperation(progress_config)

        assert not operation.is_cancelled()

        operation.cancel()

        assert operation.is_cancelled() is True

    def test_cancel_callback_invoked(self) -> None:
        """Test cancel callback is invoked on cancellation."""
        callback_invoked = {"called": False}

        def cancel_callback() -> None:
            callback_invoked["called"] = True

        config = ProgressConfig(title="Test", cancel_callback=cancel_callback)
        operation = ProgressOperation(config)

        operation.cancel()

        assert callback_invoked["called"] is True

    def test_cancel_callback_exception_handled(self) -> None:
        """Test exceptions in cancel callback are handled gracefully."""

        def failing_callback() -> None:
            raise RuntimeError("Callback failed")

        config = ProgressConfig(title="Test", cancel_callback=failing_callback)
        operation = ProgressOperation(config)

        # Should not raise exception
        operation.cancel()

        assert operation.is_cancelled() is True

    def test_eta_calculation_with_no_data(
        self, progress_config: ProgressConfig
    ) -> None:
        """Test ETA returns empty string when no processing data available."""
        operation = ProgressOperation(progress_config)
        operation.set_total(100)

        eta = operation.get_eta_string()

        assert eta == ""

    def test_eta_calculation_indeterminate(
        self, progress_config: ProgressConfig
    ) -> None:
        """Test ETA returns empty string for indeterminate progress."""
        operation = ProgressOperation(progress_config)
        # Indeterminate by default

        eta = operation.get_eta_string()

        assert eta == ""

    def test_eta_calculation_seconds(self, progress_config: ProgressConfig) -> None:
        """Test ETA formatting for operations under 1 minute."""
        config = ProgressConfig(title="Test", update_interval=1)
        operation = ProgressOperation(config)
        operation.set_total(100)

        # Simulate processing 10 items per second
        operation.processing_times = [10.0]  # 10 items/sec
        operation.current_value = 50

        eta = operation.get_eta_string()

        assert "s remaining" in eta
        assert "~5s" in eta  # (100-50)/10 = 5 seconds

    def test_eta_calculation_minutes(self, progress_config: ProgressConfig) -> None:
        """Test ETA formatting for operations 1-60 minutes."""
        config = ProgressConfig(title="Test", update_interval=1)
        operation = ProgressOperation(config)
        operation.set_total(1000)

        # Simulate processing 1 item per second (slow)
        operation.processing_times = [1.0]
        operation.current_value = 100

        eta = operation.get_eta_string()

        assert "m remaining" in eta
        assert "~15m" in eta  # (1000-100)/1 = 900s = 15min

    def test_eta_calculation_hours(self, progress_config: ProgressConfig) -> None:
        """Test ETA formatting for operations over 1 hour."""
        config = ProgressConfig(title="Test", update_interval=1)
        operation = ProgressOperation(config)
        operation.set_total(10000)

        # Simulate very slow processing
        operation.processing_times = [1.0]
        operation.current_value = 1000

        eta = operation.get_eta_string()

        assert "h" in eta
        assert "m remaining" in eta
        assert "~2h 30m" in eta  # (10000-1000)/1 = 9000s = 2.5 hours

    def test_eta_disabled_when_show_eta_false(self) -> None:
        """Test ETA calculation skipped when show_eta is False."""
        config = ProgressConfig(title="Test", show_eta=False)
        operation = ProgressOperation(config)
        operation.set_total(100)
        operation.processing_times = [10.0]
        operation.current_value = 50

        eta = operation.get_eta_string()

        assert eta == ""

    def test_eta_empty_when_completed(self, progress_config: ProgressConfig) -> None:
        """Test ETA returns empty when operation is complete."""
        operation = ProgressOperation(progress_config)
        operation.set_total(100)
        operation.processing_times = [10.0]
        operation.current_value = 100  # Completed

        eta = operation.get_eta_string()

        assert eta == ""

    def test_processing_rate_tracking(self, progress_config: ProgressConfig) -> None:
        """Test processing rate is tracked for ETA calculation."""
        config = ProgressConfig(title="Test", update_interval=1)
        operation = ProgressOperation(config)
        operation.set_total(100)

        # Simulate multiple updates
        operation.update(10, "Step 1")
        time.sleep(0.01)
        operation.update(20, "Step 2")
        time.sleep(0.01)
        operation.update(30, "Step 3")

        # Processing times should be tracked
        assert len(operation.processing_times) > 0

    def test_processing_rate_max_samples(self, progress_config: ProgressConfig) -> None:
        """Test processing rate maintains maximum sample window."""
        config = ProgressConfig(title="Test", update_interval=1)
        operation = ProgressOperation(config)
        operation.set_total(100)
        operation.max_eta_samples = 5

        # Trigger updates to add processing time samples
        # Need to advance time between updates to avoid throttling
        for i in range(15):  # More than max_eta_samples
            time.sleep(0.002)  # 2ms between updates (> 1ms throttle)
            operation.update(i, f"Step {i}")

        # Should keep only most recent samples (max 5)
        assert len(operation.processing_times) <= 5


# =============================================================================
# ProgressManager Singleton Tests
# =============================================================================


class TestProgressManagerSingleton:
    """Test ProgressManager singleton behavior and instance management."""

    def test_singleton_pattern(self) -> None:
        """Test ProgressManager implements singleton correctly."""
        instance1 = ProgressManager()
        instance2 = ProgressManager()

        assert instance1 is instance2

    def test_initialization_only_once(self) -> None:
        """Test ProgressManager initializes only once despite multiple calls."""
        manager1 = ProgressManager()
        manager2 = ProgressManager()

        # Verify both references point to same singleton instance
        assert manager1 is manager2
        assert hasattr(manager1, "_initialized")
        assert manager1._initialized is True

    def test_initialize_sets_status_bar(self, status_bar: QStatusBar) -> None:
        """Test initialize() sets status bar reference."""
        manager = ProgressManager.initialize(status_bar)

        assert ProgressManager._status_bar is status_bar
        assert isinstance(manager, ProgressManager)


# =============================================================================
# ProgressManager Operation Stack Tests
# =============================================================================


class TestProgressManagerOperationStack:
    """Test operation stack management and lifecycle."""

    def test_start_operation_with_config(self, mock_notification_manager: Mock) -> None:
        """Test starting operation with ProgressConfig."""
        config = ProgressConfig(title="Test Operation", cancelable=False)

        operation = ProgressManager.start_operation(config)

        assert operation is not None
        assert operation.config.title == "Test Operation"
        assert ProgressManager.is_operation_active()

    def test_start_operation_with_string(self, mock_notification_manager: Mock) -> None:
        """Test starting operation with simple string title."""
        operation = ProgressManager.start_operation("Simple Operation")

        assert operation is not None
        assert operation.config.title == "Simple Operation"

    def test_finish_operation_pops_stack(self, mock_notification_manager: Mock) -> None:
        """Test finishing operation removes it from stack."""
        ProgressManager.start_operation("Test")
        assert ProgressManager.is_operation_active()

        ProgressManager.finish_operation(success=True)

        assert not ProgressManager.is_operation_active()

    def test_finish_operation_empty_stack_warning(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test finishing operation on empty stack logs warning gracefully."""
        # Should not raise exception
        ProgressManager.finish_operation(success=True)

        # Stack remains empty
        assert not ProgressManager.is_operation_active()

    def test_get_current_operation(self, mock_notification_manager: Mock) -> None:
        """Test retrieving current operation from stack."""
        operation = ProgressManager.start_operation("Test")

        current = ProgressManager.get_current_operation()

        assert current is operation

    def test_get_current_operation_empty_stack(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test getting current operation returns None when stack empty."""
        current = ProgressManager.get_current_operation()

        assert current is None

    def test_nested_operations_stack(self, mock_notification_manager: Mock) -> None:
        """Test nested operations maintain correct stack order."""
        op1 = ProgressManager.start_operation("Operation 1")
        op2 = ProgressManager.start_operation("Operation 2")
        op3 = ProgressManager.start_operation("Operation 3")

        # Current should be most recent
        assert ProgressManager.get_current_operation() is op3

        ProgressManager.finish_operation()
        assert ProgressManager.get_current_operation() is op2

        ProgressManager.finish_operation()
        assert ProgressManager.get_current_operation() is op1

        ProgressManager.finish_operation()
        assert ProgressManager.get_current_operation() is None


# =============================================================================
# ProgressManager Context Manager Tests
# =============================================================================


class TestProgressManagerContextManager:
    """Test context manager behavior and exception handling."""

    def test_context_manager_basic_usage(self, mock_notification_manager: Mock) -> None:
        """Test basic context manager operation."""
        with ProgressManager.operation("Test Operation") as progress:
            assert progress is not None
            assert ProgressManager.is_operation_active()

        # Should auto-finish on exit
        assert not ProgressManager.is_operation_active()

    def test_context_manager_with_updates(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test context manager with progress updates."""
        with ProgressManager.operation("Test") as progress:
            progress.set_total(100)
            progress.update(50, "Halfway")

            assert progress.current_value == 50
            assert progress.total_value == 100

    def test_context_manager_handles_exceptions(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test context manager propagates exceptions after cleanup."""
        # PT012: Extract setup outside pytest.raises() for single statement rule
        def raise_in_context() -> None:
            with ProgressManager.operation("Test") as progress:
                progress.set_total(10)
                raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            raise_in_context()

        # Operation should be cleaned up
        assert not ProgressManager.is_operation_active()
        mock_notification_manager.error.assert_called()

    def test_context_manager_success_notification(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test success notification shown on successful completion."""
        with ProgressManager.operation("Test Operation"):
            pass

        # Should show success notification
        mock_notification_manager.success.assert_called()
        call_args = mock_notification_manager.success.call_args[0][0]
        assert "Test Operation" in call_args
        assert "completed" in call_args

    def test_context_manager_cancellation_notification(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test cancellation shows appropriate notification."""
        with ProgressManager.operation("Test", cancelable=True) as progress:
            progress.cancel()

        # Should show info (cancellation) not success
        mock_notification_manager.info.assert_called()
        call_args = mock_notification_manager.info.call_args[0][0]
        assert "cancelled" in call_args

    def test_nested_context_managers(self, mock_notification_manager: Mock) -> None:
        """Test nested progress operations with context managers."""
        with ProgressManager.operation("Main Operation") as main:
            main.set_total(2)

            with ProgressManager.operation("Sub-operation 1") as sub1:
                sub1.set_total(10)
                sub1.update(10)

            main.update(1)

            with ProgressManager.operation("Sub-operation 2") as sub2:
                sub2.set_total(20)
                sub2.update(20)

            main.update(2)

        # All should be cleaned up
        assert not ProgressManager.is_operation_active()


# =============================================================================
# ProgressManager Progress Type Selection Tests
# =============================================================================


class TestProgressTypeSelection:
    """Test automatic progress type selection logic."""

    def test_auto_progress_type_cancelable_uses_modal(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test AUTO type uses modal dialog for cancelable operations."""
        config = ProgressConfig(
            title="Test", cancelable=True, progress_type=ProgressType.AUTO
        )

        operation = ProgressManager.start_operation(config)

        # Should have created progress dialog (modal)
        mock_notification_manager.progress.assert_called_once()
        assert operation.progress_dialog is not None

    def test_auto_progress_type_non_cancelable_uses_status(
        self, mock_notification_manager: Mock, status_bar: QStatusBar
    ) -> None:
        """Test AUTO type uses status bar for non-cancelable operations."""
        ProgressManager.initialize(status_bar)
        config = ProgressConfig(
            title="Test", cancelable=False, progress_type=ProgressType.AUTO
        )

        operation = ProgressManager.start_operation(config)

        # Should use status bar, not modal dialog
        mock_notification_manager.progress.assert_not_called()
        assert operation.status_bar is status_bar

    def test_explicit_modal_progress_type(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test explicit MODAL_DIALOG progress type creates dialog."""
        config = ProgressConfig(title="Test", progress_type=ProgressType.MODAL_DIALOG)

        operation = ProgressManager.start_operation(config)

        mock_notification_manager.progress.assert_called_once()
        assert operation.progress_dialog is not None

    def test_explicit_status_bar_progress_type(
        self, mock_notification_manager: Mock, status_bar: QStatusBar
    ) -> None:
        """Test explicit STATUS_BAR progress type uses status bar."""
        ProgressManager.initialize(status_bar)
        config = ProgressConfig(title="Test", progress_type=ProgressType.STATUS_BAR)

        operation = ProgressManager.start_operation(config)

        mock_notification_manager.progress.assert_not_called()
        assert operation.status_bar is status_bar


# =============================================================================
# ProgressManager Cancellation Tests
# =============================================================================


class TestProgressCancellation:
    """Test operation cancellation behavior."""

    def test_cancel_current_operation_cancelable(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test cancelling a cancelable operation."""
        config = ProgressConfig(title="Test", cancelable=True)
        ProgressManager.start_operation(config)

        result = ProgressManager.cancel_current_operation()

        assert result is True
        operation = ProgressManager.get_current_operation()
        assert operation.is_cancelled() is True

    def test_cancel_current_operation_non_cancelable(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test cancelling a non-cancelable operation returns False."""
        config = ProgressConfig(title="Test", cancelable=False)
        ProgressManager.start_operation(config)

        result = ProgressManager.cancel_current_operation()

        assert result is False
        operation = ProgressManager.get_current_operation()
        assert operation.is_cancelled() is False

    def test_cancel_with_no_active_operation(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test cancelling when no operation is active."""
        result = ProgressManager.cancel_current_operation()

        assert result is False

    def test_clear_all_operations(self, mock_notification_manager: Mock) -> None:
        """Test emergency cleanup clears all operations."""
        # Start multiple operations
        ProgressManager.start_operation(ProgressConfig(title="Op1", cancelable=True))
        ProgressManager.start_operation(ProgressConfig(title="Op2", cancelable=True))
        ProgressManager.start_operation(ProgressConfig(title="Op3", cancelable=False))

        ProgressManager.clear_all_operations()

        assert not ProgressManager.is_operation_active()
        mock_notification_manager.close_progress.assert_called()


# =============================================================================
# UI Integration Tests
# =============================================================================


class TestUIIntegration:
    """Test UI updates and integration with Qt widgets."""

    def test_status_bar_message_updates(
        self, mock_notification_manager: Mock, status_bar: QStatusBar
    ) -> None:
        """Test status bar shows progress messages."""
        ProgressManager.initialize(status_bar)
        config = ProgressConfig(title="Test", progress_type=ProgressType.STATUS_BAR)

        operation = ProgressManager.start_operation(config)
        operation.set_total(100)
        operation.update(50, "Processing")

        # Status bar should show message with percentage
        message = status_bar.currentMessage()
        assert "Processing" in message
        assert "50.0%" in message

    def test_status_bar_handles_deleted_widget(self) -> None:
        """Test graceful handling when status bar is deleted."""
        # Create mock status bar that raises RuntimeError (simulates deleted widget)
        mock_status_bar = Mock(spec=QStatusBar)
        mock_status_bar.showMessage.side_effect = RuntimeError(
            "wrapped C/C++ object has been deleted"
        )

        # Mock NotificationManager to return our failing status bar
        with patch("progress_manager.NotificationManager") as mock_nm:
            mock_nm.get_status_bar.return_value = mock_status_bar
            mock_nm.progress.return_value = Mock(spec=QProgressDialog)

            config = ProgressConfig(title="Test", progress_type=ProgressType.STATUS_BAR)
            operation = ProgressManager.start_operation(config)

            # Should handle RuntimeError gracefully
            operation.update(50, "Test")  # Should not raise

            # Reference should be cleared
            assert operation.status_bar is None

    def test_progress_dialog_created_for_modal(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test progress dialog creation for modal operations."""
        config = ProgressConfig(title="Test", progress_type=ProgressType.MODAL_DIALOG)

        operation = ProgressManager.start_operation(config)

        mock_notification_manager.progress.assert_called_once_with(
            title="Test", message="Test", cancelable=False, callback=None
        )
        assert operation.progress_dialog is not None

    def test_progress_dialog_closed_on_finish(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test progress dialog is closed when operation finishes."""
        config = ProgressConfig(title="Test", progress_type=ProgressType.MODAL_DIALOG)
        ProgressManager.start_operation(config)

        ProgressManager.finish_operation(success=True)

        mock_notification_manager.close_progress.assert_called_once()


# =============================================================================
# Convenience Functions Tests
# =============================================================================


class TestConvenienceFunctions:
    """Test convenience wrapper functions."""

    def test_start_progress_function(self, mock_notification_manager: Mock) -> None:
        """Test start_progress() convenience function."""
        operation = start_progress("Test Operation", cancelable=True)

        assert operation is not None
        assert operation.config.title == "Test Operation"
        assert operation.config.cancelable is True

    def test_finish_progress_function(self, mock_notification_manager: Mock) -> None:
        """Test finish_progress() convenience function."""
        start_progress("Test")

        finish_progress(success=True)

        assert not ProgressManager.is_operation_active()

    def test_update_progress_function(self, mock_notification_manager: Mock) -> None:
        """Test update_progress() convenience function."""
        operation = start_progress("Test")
        operation.set_total(100)

        update_progress(50, "Halfway")

        assert operation.current_value == 50
        assert operation.current_message == "Halfway"

    def test_set_progress_total_function(self, mock_notification_manager: Mock) -> None:
        """Test set_progress_total() convenience function."""
        operation = start_progress("Test")

        set_progress_total(100)

        assert operation.total_value == 100
        assert operation.is_indeterminate is False

    def test_set_progress_indeterminate_function(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test set_progress_indeterminate() convenience function."""
        operation = start_progress("Test")
        operation.set_total(100)

        set_progress_indeterminate()

        assert operation.is_indeterminate is True

    def test_is_progress_cancelled_function(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test is_progress_cancelled() convenience function."""
        operation = start_progress("Test", cancelable=True)

        assert is_progress_cancelled() is False

        operation.cancel()

        assert is_progress_cancelled() is True

    def test_convenience_functions_with_no_operation(
        self, mock_notification_manager: Mock
    ) -> None:
        """Test convenience functions handle no active operation gracefully."""
        # Should not raise exceptions
        update_progress(50)
        set_progress_total(100)
        set_progress_indeterminate()

        # Should return False when no operation
        assert is_progress_cancelled() is False


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling."""

    def test_multiple_finish_operations(self, mock_notification_manager: Mock) -> None:
        """Test finishing operation multiple times is safe."""
        ProgressManager.start_operation("Test")

        ProgressManager.finish_operation(success=True)
        ProgressManager.finish_operation(success=True)  # Should not crash

        assert not ProgressManager.is_operation_active()

    def test_operation_with_zero_total(self, mock_notification_manager: Mock) -> None:
        """Test operation handles zero total gracefully."""
        operation = ProgressManager.start_operation("Test")
        operation.set_total(0)

        # Should not crash when calculating percentage
        operation.update(0, "Test")

        assert operation.total_value == 0

    def test_negative_update_values(self, mock_notification_manager: Mock) -> None:
        """Test operation handles negative values gracefully."""
        operation = ProgressManager.start_operation("Test")
        operation.set_total(100)

        # Should not crash with negative value
        operation.update(-10, "Test")

        assert operation.current_value == -10

    def test_update_beyond_total(self, mock_notification_manager: Mock) -> None:
        """Test operation handles values beyond total."""
        operation = ProgressManager.start_operation("Test")
        operation.set_total(100)

        operation.update(150, "Beyond total")

        assert operation.current_value == 150

    def test_eta_with_zero_rate(self, mock_notification_manager: Mock) -> None:
        """Test ETA calculation handles zero processing rate."""
        operation = ProgressManager.start_operation("Test")
        operation.set_total(100)
        operation.processing_times = [0.0]  # Zero rate
        operation.current_value = 50

        eta = operation.get_eta_string()

        # Should return empty string, not crash
        assert eta == ""

    def test_eta_with_negative_rate(self, mock_notification_manager: Mock) -> None:
        """Test ETA calculation handles negative processing rate."""
        operation = ProgressManager.start_operation("Test")
        operation.set_total(100)
        operation.processing_times = [-1.0]  # Negative rate
        operation.current_value = 50

        eta = operation.get_eta_string()

        # Should return empty string, not crash
        assert eta == ""
