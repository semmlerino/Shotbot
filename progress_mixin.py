"""Mixin for progress reporting functionality.

This module provides a reusable mixin that adds progress reporting
capabilities to any finder class, eliminating duplication of progress
tracking code across multiple finder implementations.
"""

from __future__ import annotations

# Standard library imports
import contextlib
from collections.abc import Callable
from typing import TypeVar

# Local application imports
from logging_mixin import LoggingMixin


T = TypeVar("T")


class ProgressReportingMixin(LoggingMixin):
    """Mixin to add progress reporting capabilities to finders.

    This mixin provides:
    - Progress callback management
    - Stop request handling
    - Safe progress reporting with error handling
    - Thread-safe operation tracking

    Usage:
        class MyFinder(BaseFinder, ProgressReportingMixin):
            def find_items(self):
                for i, item in enumerate(items):
                    if self._check_stop():
                        break
                    self._report_progress(i, len(items), f"Processing {item}")
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize progress tracking attributes."""
        super().__init__(*args, **kwargs)
        self._stop_requested: bool = False
        self._progress_callback: Callable[[int, int, str], None] | None = None
        self._last_reported_progress: int = (
            -1
        )  # Track last reported to avoid duplicates

    def set_progress_callback(self, callback: Callable[[int, int, str], None]) -> None:
        """Set callback for progress reporting.

        The callback will be called with (current, total, message) arguments
        whenever progress is reported.

        Args:
            callback: Function to call with progress updates
                     Signature: (current: int, total: int, message: str) -> None

        """
        self._progress_callback = callback
        self.logger.debug(f"Progress callback set for {self.__class__.__name__}")

    def clear_progress_callback(self) -> None:
        """Clear the progress callback."""
        self._progress_callback = None
        self.logger.debug(f"Progress callback cleared for {self.__class__.__name__}")

    def request_stop(self) -> None:
        """Request the current operation to stop.

        This sets a flag that should be checked periodically during
        long-running operations using _check_stop().
        """
        self._stop_requested = True
        self.logger.info(f"Stop requested for {self.__class__.__name__}")

    def clear_stop_request(self) -> None:
        """Clear any pending stop request.

        Should be called at the start of a new operation to reset
        the stop flag from previous operations.
        """
        self._stop_requested = False
        self._last_reported_progress = -1
        self.logger.debug(f"Stop request cleared for {self.__class__.__name__}")

    @property
    def stop_requested(self) -> bool:
        """Check if stop has been requested.

        Returns:
            True if stop has been requested, False otherwise

        """
        return self._stop_requested

    def _report_progress(self, current: int, total: int, message: str = "") -> None:
        """Report progress if callback is set.

        Includes safety checks to prevent callback errors from
        disrupting the main operation.

        Args:
            current: Current progress value (0 to total)
            total: Total progress value
            message: Optional progress message

        """
        if not self._progress_callback:
            return

        # Avoid reporting the same progress multiple times
        if current == self._last_reported_progress and total > 0:
            return

        self._last_reported_progress = current

        try:
            self._progress_callback(current, total, message)
        except Exception as e:
            # Log error but don't disrupt the operation
            self.logger.error(f"Error in progress callback: {e}", exc_info=True)
            # Disable callback to prevent further errors
            self._progress_callback = None

    def _calculate_percentage(self, current: int, total: int) -> int:
        """Calculate progress percentage safely.

        Handles edge cases like division by zero and invalid values.

        Args:
            current: Current progress value
            total: Total progress value

        Returns:
            Percentage as integer (0-100)

        """
        if total <= 0 or current < 0:
            return 0
        if current >= total:
            return 100
        return int((current / total) * 100)

    def _report_progress_percentage(self, percentage: float, message: str = "") -> None:
        """Report progress as a percentage.

        Convenience method for reporting progress as a percentage
        rather than absolute values.

        Args:
            percentage: Progress percentage (0.0 to 100.0)
            message: Optional progress message

        """
        # Convert percentage to current/total values
        current = int(percentage)
        total = 100
        self._report_progress(current, total, message)

    def _check_stop(self) -> bool:
        """Check if operation should stop.

        This should be called periodically during long-running operations
        to allow for graceful cancellation.

        Returns:
            True if stop requested and operation should halt, False otherwise

        """
        if self._stop_requested:
            self.logger.info(
                f"Operation stopped by user request in {self.__class__.__name__}"
            )
            # Report final progress as cancelled
            if self._progress_callback:
                with contextlib.suppress(Exception):
                    # Report current state with cancellation message
                    self._progress_callback(
                        self._last_reported_progress, 100, "Operation cancelled by user"
                    )
            return True
        return False

    def _with_progress_tracking(
        self,
        items: list[T],
        operation: Callable[[T], object],
        message_formatter: Callable[[int, T], str] | None = None,
    ) -> list[object]:
        """Process items with automatic progress tracking.

        Utility method to process a list of items with automatic
        progress reporting and stop checking.

        Args:
            items: List of items to process
            operation: Function to call for each item
            message_formatter: Optional function to format progress message
                             Signature: (index: int, item: any) -> str

        Returns:
            List of results from operation (None for stopped items)

        """
        results: list[object] = []
        total = len(items)

        for i, item in enumerate(items):
            # Check for stop request
            if self._check_stop():
                # Return partial results
                break

            # Format message
            if message_formatter:
                message = message_formatter(i, item)
            else:
                message = f"Processing item {i + 1} of {total}"

            # Report progress
            self._report_progress(i, total, message)

            # Process item
            try:
                result = operation(item)
                results.append(result)
            except Exception as e:
                self.logger.error(f"Error processing item {i}: {e}")
                results.append(None)

        # Report completion
        if not self._stop_requested:
            self._report_progress(total, total, "Complete")

        return results

    def _estimate_remaining_time(
        self, current: int, total: int, elapsed_seconds: float
    ) -> float:
        """Estimate remaining time based on current progress.

        Args:
            current: Current progress value
            total: Total progress value
            elapsed_seconds: Time elapsed so far in seconds

        Returns:
            Estimated remaining time in seconds

        """
        if current <= 0 or total <= 0:
            return 0.0

        rate = current / elapsed_seconds  # items per second
        remaining = total - current

        if rate > 0:
            return remaining / rate
        return 0.0

    def _format_time_estimate(self, seconds: float) -> str:
        """Format time estimate for display.

        Args:
            seconds: Time in seconds

        Returns:
            Human-readable time string (e.g., "2m 30s")

        """
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"
