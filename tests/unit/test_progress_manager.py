"""Tests for progress_manager module.

Tests the simplified ProgressManager singleton.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QStatusBar

from managers.progress_manager import ProgressManager, ProgressOperation


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
def mock_notification_manager() -> Generator[Mock, None, None]:
    """Mock NotificationManager at system boundary."""
    with patch("managers.progress_manager.NotificationManager") as mock:
        mock.get_status_bar.return_value = None
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


# =============================================================================
# ProgressOperation Tests
# =============================================================================


class TestOperation:
    """Test ProgressOperation state management."""

    def test_initialization(self) -> None:
        """Operation initializes with correct default state."""
        op = ProgressOperation("Test Operation", total=0)

        assert op.label == "Test Operation"
        assert op.total == 0
        assert op.current == 0
        assert op.cancelled is False

    def test_set_total(self) -> None:
        """set_total updates the total."""
        op = ProgressOperation("Test", total=0)
        op.set_total(100)
        assert op.total == 100

    def test_update_value_and_message(self) -> None:
        """update() stores current value and message."""
        op = ProgressOperation("Test", total=100)
        op.update(50, "Halfway")
        assert op.current == 50
        assert op.message == "Halfway"

    def test_update_without_message_preserves_label(self) -> None:
        """update() without message keeps existing message."""
        op = ProgressOperation("My label", total=100)
        op.update(10)
        assert op.message == "My label"

    def test_cancellation(self) -> None:
        """cancel() sets is_cancelled to True."""
        op = ProgressOperation("Test", total=0)
        assert not op.is_cancelled()
        op.cancel()
        assert op.is_cancelled() is True


# =============================================================================
# ProgressManager Singleton Tests
# =============================================================================


class TestProgressManagerSingleton:
    """Test ProgressManager singleton behavior."""

    def test_singleton_pattern(self) -> None:
        """ProgressManager implements singleton correctly."""
        instance1 = ProgressManager()
        instance2 = ProgressManager()
        assert instance1 is instance2

    def test_initialize_sets_status_bar(self, status_bar: QStatusBar) -> None:
        """initialize() attaches the status bar."""
        manager = ProgressManager.initialize(status_bar)
        assert ProgressManager._status_bar is status_bar
        assert isinstance(manager, ProgressManager)


# =============================================================================
# ProgressManager Operation Stack Tests
# =============================================================================


class TestProgressManagerOperationStack:
    """Test operation stack management and lifecycle."""

    def test_start_operation_with_label(self, mock_notification_manager: Mock) -> None:
        """start_operation() pushes operation and returns it."""
        op = ProgressManager.start_operation("Test Operation")

        assert op is not None
        assert op.label == "Test Operation"

    def test_start_operation_with_total(self, mock_notification_manager: Mock) -> None:
        """start_operation() accepts an optional total."""
        op = ProgressManager.start_operation("Counting", total=50)
        assert op.total == 50

    def test_finish_operation_pops_stack(self, mock_notification_manager: Mock) -> None:
        """finish_operation() removes the current operation."""
        ProgressManager.start_operation("Test")

        ProgressManager.finish_operation(success=True)

        assert ProgressManager.get_current_operation() is None

    def test_finish_operation_empty_stack_is_safe(
        self, mock_notification_manager: Mock
    ) -> None:
        """Finishing on an empty stack logs a warning but does not raise."""
        ProgressManager.finish_operation(success=True)
        assert ProgressManager.get_current_operation() is None

    def test_get_current_operation(self, mock_notification_manager: Mock) -> None:
        """get_current_operation() returns the top-of-stack operation."""
        op = ProgressManager.start_operation("Test")
        assert ProgressManager.get_current_operation() is op

    def test_get_current_operation_empty_stack(self) -> None:
        """get_current_operation() returns None when stack is empty."""
        assert ProgressManager.get_current_operation() is None

    def test_stacked_operations(self, mock_notification_manager: Mock) -> None:
        """Operations stack correctly; finish pops in LIFO order."""
        op1 = ProgressManager.start_operation("Op 1")
        op2 = ProgressManager.start_operation("Op 2")
        op3 = ProgressManager.start_operation("Op 3")

        assert ProgressManager.get_current_operation() is op3

        ProgressManager.finish_operation()
        assert ProgressManager.get_current_operation() is op2

        ProgressManager.finish_operation()
        assert ProgressManager.get_current_operation() is op1

        ProgressManager.finish_operation()
        assert ProgressManager.get_current_operation() is None

    def test_multiple_finish_operations_is_safe(
        self, mock_notification_manager: Mock
    ) -> None:
        """Calling finish_operation() more times than start is safe."""
        ProgressManager.start_operation("Test")
        ProgressManager.finish_operation(success=True)
        ProgressManager.finish_operation(success=True)  # Should not crash
        assert ProgressManager.get_current_operation() is None


# =============================================================================
# ProgressManager Context Manager Tests
# =============================================================================


class TestProgressManagerContextManager:
    """Test context manager behavior."""

    def test_context_manager_basic(self, mock_notification_manager: Mock) -> None:
        """Context manager starts and finishes the operation automatically."""
        with ProgressManager.operation("Test Operation") as op:
            assert op is not None
            assert ProgressManager.get_current_operation() is op

        assert ProgressManager.get_current_operation() is None

    def test_context_manager_with_updates(
        self, mock_notification_manager: Mock
    ) -> None:
        """Context manager allows progress updates mid-operation."""
        with ProgressManager.operation("Test", total=100) as op:
            op.update(50, "Halfway")
            assert op.current == 50
            assert op.total == 100

    def test_context_manager_handles_exceptions(
        self, mock_notification_manager: Mock
    ) -> None:
        """Context manager propagates exceptions after cleanup."""

        def raise_in_context() -> None:
            with ProgressManager.operation("Test"):
                raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            raise_in_context()

        assert ProgressManager.get_current_operation() is None
        mock_notification_manager.error.assert_called()

    def test_context_manager_success_notification(
        self, mock_notification_manager: Mock
    ) -> None:
        """Successful completion triggers a success notification."""
        with ProgressManager.operation("Test Operation"):
            pass

        mock_notification_manager.success.assert_called()
        call_args = mock_notification_manager.success.call_args[0][0]
        assert "Test Operation" in call_args
        assert "completed" in call_args

    def test_context_manager_cancellation_notification(
        self, mock_notification_manager: Mock
    ) -> None:
        """A cancelled operation shows an info notification, not success."""
        with ProgressManager.operation("Test") as op:
            op.cancel()

        mock_notification_manager.info.assert_called()
        call_args = mock_notification_manager.info.call_args[0][0]
        assert "cancelled" in call_args


# =============================================================================
# ProgressManager Cancellation Tests
# =============================================================================


class TestProgressCancellation:
    """Test operation cancellation behavior."""

    def test_is_cancelled_reflects_state(self, mock_notification_manager: Mock) -> None:
        """ProgressManager.is_cancelled() mirrors the current operation's state."""
        op = ProgressManager.start_operation("Test")
        assert not ProgressManager.is_cancelled()

        op.cancel()
        assert ProgressManager.is_cancelled() is True

    def test_is_cancelled_with_no_operation(self) -> None:
        """ProgressManager.is_cancelled() returns False when no operation is active."""
        assert ProgressManager.is_cancelled() is False


# =============================================================================
# UI Integration Tests
# =============================================================================


class TestUIIntegration:
    """Test status bar updates."""

    def test_status_bar_message_on_start(
        self, mock_notification_manager: Mock, status_bar: QStatusBar
    ) -> None:
        """start_operation() displays the label in the status bar."""
        ProgressManager.initialize(status_bar)
        ProgressManager.start_operation("My Operation")

        assert "My Operation" in status_bar.currentMessage()

    def test_status_bar_message_with_percentage(
        self, mock_notification_manager: Mock, status_bar: QStatusBar
    ) -> None:
        """update() shows percentage when total is set."""
        ProgressManager.initialize(status_bar)
        op = ProgressManager.start_operation("Processing", total=100)
        op.update(50, "Processing")

        message = status_bar.currentMessage()
        assert "Processing" in message
        assert "50.0%" in message

    def test_status_bar_handles_deleted_widget(self) -> None:
        """Gracefully handles a deleted status bar widget."""
        mock_status_bar = Mock(spec=QStatusBar)
        mock_status_bar.showMessage.side_effect = RuntimeError(
            "wrapped C/C++ object has been deleted"
        )

        with patch("managers.progress_manager.NotificationManager") as mock_nm:
            mock_nm.get_status_bar.return_value = mock_status_bar

            op = ProgressManager.start_operation("Test")
            op.update(50, "Test")  # Should not raise

            # Reference should be cleared
            assert ProgressManager._status_bar is None

    def test_update_class_method_delegates_to_current_operation(
        self, mock_notification_manager: Mock, status_bar: QStatusBar
    ) -> None:
        """ProgressManager.update() delegates to the current operation."""
        ProgressManager.initialize(status_bar)
        op = ProgressManager.start_operation("Test", total=10)

        ProgressManager.update(5, "Midway")

        assert op.current == 5
        assert op.message == "Midway"

    def test_update_with_no_operation_is_safe(
        self, mock_notification_manager: Mock
    ) -> None:
        """ProgressManager.update() is a no-op when no operation is active."""
        ProgressManager.update(50)  # Should not raise


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_update_value_edge_cases(self, mock_notification_manager: Mock) -> None:
        """Operations handle boundary update values safely."""
        op = ProgressManager.start_operation("Test")
        for total, value in ((0, 0), (100, -10), (100, 150)):
            op.set_total(total)
            op.update(value, "Edge")
            assert op.current == value
