"""Unit tests for ProgressReportingMixin."""

from __future__ import annotations

# Standard library imports
from unittest.mock import MagicMock

# Local application imports
from progress_mixin import ProgressReportingMixin


class ConcreteProgressClass(ProgressReportingMixin):
    """Concrete class for testing the mixin."""

    def __init__(self) -> None:
        """Initialize test class."""
        super().__init__()
        self.operations_performed = []

    def long_operation(self) -> bool:
        """Simulate a long operation that reports progress."""
        total = 10
        for i in range(total):
            if self._check_stop():
                self.operations_performed.append(f"Stopped at {i}")
                return False
            self._report_progress(i + 1, total, f"Processing item {i + 1}")
            self.operations_performed.append(f"Processed {i + 1}")
        return True


class TestProgressReportingMixinInitialization:
    """Test mixin initialization."""

    def test_multiple_inheritance_chain(self) -> None:
        """Test that mixin works in multiple inheritance chain."""

        class MultipleInheritance(ProgressReportingMixin):
            def __init__(self) -> None:
                super().__init__()
                self.custom_attr = "test"

        obj = MultipleInheritance()
        assert hasattr(obj, "_stop_requested")
        assert hasattr(obj, "custom_attr")
        assert obj.custom_attr == "test"


class TestProgressCallback:
    """Test progress callback management."""

    def test_set_progress_callback(self) -> None:
        """Test setting a progress callback."""
        obj = ConcreteProgressClass()
        callback = MagicMock()

        obj.set_progress_callback(callback)
        assert obj._progress_callback is callback

    def test_clear_progress_callback(self) -> None:
        """Test clearing the progress callback."""
        obj = ConcreteProgressClass()
        callback = MagicMock()

        obj.set_progress_callback(callback)
        assert obj._progress_callback is callback

        obj.clear_progress_callback()
        assert obj._progress_callback is None

    def test_report_progress_with_callback(self) -> None:
        """Test that progress is reported to callback."""
        obj = ConcreteProgressClass()
        callback = MagicMock()
        obj.set_progress_callback(callback)

        obj._report_progress(5, 10, "Halfway")
        callback.assert_called_once_with(5, 10, "Halfway")

    def test_report_progress_without_callback(self) -> None:
        """Test that reporting without callback doesn't crash."""
        obj = ConcreteProgressClass()
        # Should not raise any exception
        obj._report_progress(5, 10, "Halfway")

    def test_callback_exception_handling(self) -> None:
        """Test that callback exceptions are handled gracefully."""
        obj = ConcreteProgressClass()
        callback = MagicMock(side_effect=Exception("Callback error"))
        obj.set_progress_callback(callback)

        # Should not raise exception
        obj._report_progress(5, 10, "Test")
        # Callback is disabled after an error to prevent further failures
        assert obj._progress_callback is None

    def test_duplicate_progress_filtering(self) -> None:
        """Test that duplicate progress values are filtered."""
        obj = ConcreteProgressClass()
        callback = MagicMock()
        obj.set_progress_callback(callback)

        # First call should work
        obj._report_progress(5, 10, "First")
        assert callback.call_count == 1

        # Same progress value with minimum interval should be skipped
        obj._report_progress(5, 10, "Duplicate")
        assert callback.call_count == 1

        # Different progress value should work
        obj._report_progress(6, 10, "Different")
        assert callback.call_count == 2


class TestStopRequest:
    """Test stop request functionality."""

    def test_request_stop(self) -> None:
        """Test requesting stop."""
        obj = ConcreteProgressClass()
        assert obj._stop_requested is False

        obj.request_stop()
        assert obj._stop_requested is True
        assert obj.stop_requested is True  # Test property

    def test_clear_stop_request(self) -> None:
        """Test clearing stop request."""
        obj = ConcreteProgressClass()
        obj.request_stop()
        assert obj._stop_requested is True

        obj.clear_stop_request()
        assert obj._stop_requested is False
        assert obj._last_reported_progress == -1  # Should reset progress

    def test_check_stop(self) -> None:
        """Test checking stop status."""
        obj = ConcreteProgressClass()
        assert obj._check_stop() is False

        obj.request_stop()
        assert obj._check_stop() is True

    def test_stop_during_operation(self) -> None:
        """Test that stop request interrupts operation."""
        obj = ConcreteProgressClass()
        callback = MagicMock()
        obj.set_progress_callback(callback)

        # Start operation
        obj.long_operation()
        assert len(obj.operations_performed) == 10
        assert obj.operations_performed[-1] == "Processed 10"

        # Reset and test with stop
        obj.operations_performed = []
        obj.clear_stop_request()

        # Request stop after 3 items
        def stop_after_three(current, total, message) -> None:
            if current >= 3:
                obj.request_stop()

        obj.set_progress_callback(stop_after_three)
        result = obj.long_operation()
        assert result is False
        assert len(obj.operations_performed) < 10
        assert "Stopped at" in obj.operations_performed[-1]


class TestProgressReportingIntegration:
    """Test integrated progress reporting scenarios."""

    def test_complete_workflow(self) -> None:
        """Test complete progress reporting workflow."""
        obj = ConcreteProgressClass()
        progress_reports = []

        def capture_progress(current, total, message) -> None:
            progress_reports.append(
                {
                    "current": current,
                    "total": total,
                    "message": message,
                }
            )

        obj.set_progress_callback(capture_progress)
        result = obj.long_operation()

        assert result is True
        assert len(progress_reports) == 10
        assert progress_reports[-1]["current"] == 10

    def test_multiple_operations_with_reset(self) -> None:
        """Test running multiple operations with reset between."""
        obj = ConcreteProgressClass()
        callback = MagicMock()
        obj.set_progress_callback(callback)

        # First operation
        obj.long_operation()
        first_call_count = callback.call_count

        # Reset and run again
        obj.clear_stop_request()
        obj.operations_performed = []
        obj.long_operation()

        # Should have doubled the calls
        assert callback.call_count == first_call_count * 2

    def test_thread_safety_attributes(self) -> None:
        """Test that attributes exist for thread safety."""
        obj = ConcreteProgressClass()

        # These attributes should exist for thread-safe operation
        assert hasattr(obj, "_stop_requested")
        assert hasattr(obj, "_progress_callback")
        assert hasattr(obj, "_last_reported_progress")

        # Should be able to safely check stop from different contexts
        assert obj.stop_requested is False
        obj.request_stop()
        assert obj.stop_requested is True
