"""Comprehensive tests for progress_manager module.

Tests the ProgressManager singleton, ProgressOperation class, and convenience
functions following UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

import threading
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


@pytest.fixture(autouse=True)
def _reset_progress_manager() -> Generator[None, None, None]:
    """Reset ProgressManager singleton state before and after each test."""
    ProgressManager.reset()
    yield
    ProgressManager.reset()


@pytest.fixture
def progress_config() -> ProgressConfig:
    """Create default progress configuration."""
    return ProgressConfig(title="Test Operation", cancelable=False)


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

        # First update should work
        operation.update(10, "Step 1")

        # Wait for throttle interval to expire (20ms > 10ms throttle)
        threading.Event().wait(timeout=0.020)  # 20ms

        # Second update should now work
        operation.update(20, "Step 2")

        assert operation.current_value == 20
        assert operation.current_message == "Step 2"

    def test_cancellation(self, progress_config: ProgressConfig) -> None:
        """Test operation cancellation sets flag correctly."""
        operation = ProgressOperation(progress_config)

        assert not operation.is_cancelled()

        operation.cancel()

        assert operation.is_cancelled() is True

    def test_cancel_callback_paths(self) -> None:
        """Test cancellation invokes callback and suppresses callback failures."""
        callbacks_called = {"ok": False, "failing": False}

        def ok_callback() -> None:
            callbacks_called["ok"] = True

        def failing_callback() -> None:
            callbacks_called["failing"] = True
            raise RuntimeError("Callback failed")

        for callback in (ok_callback, failing_callback):
            operation = ProgressOperation(
                ProgressConfig(title="Test", cancel_callback=callback)
            )
            operation.cancel()  # must not propagate callback exceptions
            assert operation.is_cancelled() is True

        assert callbacks_called == {"ok": True, "failing": True}

    def test_eta_returns_empty_for_non_estimated_states(
        self, progress_config: ProgressConfig
    ) -> None:
        """ETA should be empty when estimation is unavailable or disabled."""
        # No processing data
        no_data = ProgressOperation(progress_config)
        no_data.set_total(100)
        assert no_data.get_eta_string() == ""

        # Indeterminate operation
        indeterminate = ProgressOperation(progress_config)
        assert indeterminate.get_eta_string() == ""

        # Explicitly disabled ETA
        disabled = ProgressOperation(ProgressConfig(title="Test", show_eta=False))
        disabled.set_total(100)
        disabled.processing_times = [10.0]
        disabled.current_value = 50
        assert disabled.get_eta_string() == ""

        # Completed operation
        completed = ProgressOperation(progress_config)
        completed.set_total(100)
        completed.processing_times = [10.0]
        completed.current_value = 100
        assert completed.get_eta_string() == ""

    def test_eta_calculation_formats_by_time_range(self) -> None:
        """ETA formatting should cover seconds, minutes, and hours ranges."""
        cases = [
            # total, current, rate, expected fragment
            (100, 50, 10.0, "~5s"),
            (1000, 100, 1.0, "~15m"),
            (10000, 1000, 1.0, "~2h 30m"),
        ]
        for total, current, rate, expected in cases:
            operation = ProgressOperation(ProgressConfig(title="Test", update_interval=1))
            operation.set_total(total)
            operation.processing_times = [rate]
            operation.current_value = current
            eta = operation.get_eta_string()
            assert expected in eta
            assert "remaining" in eta

    def test_processing_rate_tracking(
        self, progress_config: ProgressConfig
    ) -> None:
        """Processing rate tracks samples and respects max sample window."""
        config = ProgressConfig(title="Test", update_interval=1)  # 1ms throttle
        operation = ProgressOperation(config)
        operation.set_total(100)
        operation.max_eta_samples = 5

        for i in range(15):
            operation.update(i, f"Step {i}")
            threading.Event().wait(timeout=0.005)

        assert len(operation.processing_times) > 0
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

    def test_convenience_wrapper_happy_path(
        self, mock_notification_manager: Mock
    ) -> None:
        """Wrapper functions should operate on the active operation."""
        operation = start_progress("Test Operation", cancelable=True)

        assert operation is not None
        assert operation.config.title == "Test Operation"
        assert operation.config.cancelable is True

        set_progress_total(100)
        assert operation.total_value == 100
        assert operation.is_indeterminate is False

        update_progress(50, "Halfway")
        assert operation.current_value == 50
        assert operation.current_message == "Halfway"

        set_progress_indeterminate()
        assert operation.is_indeterminate is True

        finish_progress(success=True)
        assert not ProgressManager.is_operation_active()

    def test_is_progress_cancelled_function(self, mock_notification_manager: Mock) -> None:
        """is_progress_cancelled reflects cancellation state of active operation."""
        operation = start_progress("Cancelable", cancelable=True)

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

    def test_update_value_edge_cases(self, mock_notification_manager: Mock) -> None:
        """Operations should handle boundary/overflow update values safely."""
        operation = ProgressManager.start_operation(
            ProgressConfig(title="Test", update_interval=0)
        )
        for total, value in ((0, 0), (100, -10), (100, 150)):
            operation.set_total(total)
            operation.update(value, "Edge")
            assert operation.current_value == value

    def test_eta_with_non_positive_rate(self, mock_notification_manager: Mock) -> None:
        """ETA should be empty for zero or negative processing rate."""
        operation = ProgressManager.start_operation("Test")
        operation.set_total(100)
        operation.current_value = 50

        for rate in (0.0, -1.0):
            operation.processing_times = [rate]
            assert operation.get_eta_string() == ""
