"""Mixin for progress reporting functionality.

This module provides a reusable mixin that adds progress reporting
capabilities to any finder class, eliminating duplication of progress
tracking code across multiple finder implementations.
"""

from __future__ import annotations

# Standard library imports
import contextlib
from collections.abc import Callable

# Local application imports
from logging_mixin import LoggingMixin


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
        except Exception:
            # Log error but don't disrupt the operation
            self.logger.exception("Error in progress callback")
            # Disable callback to prevent further errors
            self._progress_callback = None

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
