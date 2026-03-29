"""Progress tracking helpers for ThreeDESceneWorker."""

from __future__ import annotations

import logging

# Standard library imports
import time
from collections import deque
from typing import final

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from config import Config


logger = logging.getLogger(__name__)


@final
class QtProgressReporter(QObject):
    """Simple Qt-based progress reporter for thread-safe signal emission.

    This class provides a clean way to emit progress signals from any thread,
    including ThreadPoolExecutor worker threads. It uses Qt's built-in queued
    connection mechanism for thread safety instead of complex workarounds.

    The reporter is created in the worker's QThread and uses queued signals
    to ensure all emissions happen in the correct thread context.
    """

    # Signal that will be emitted with progress updates
    # Using queued connection ensures thread-safe delivery
    progress_update = Signal(int, str)  # files_found, status

    def __init__(self) -> None:
        """Initialize the progress reporter."""
        super().__init__()
        logger.debug("QtProgressReporter created in thread: %s", self.thread())

    def report_progress(self, files_found: int, status: str) -> None:
        """Report progress from any thread.

        This method can be safely called from ThreadPoolExecutor threads or any
        other thread. The signal emission will be queued and delivered in the
        correct Qt thread.

        Args:
            files_found: Number of files found so far
            status: Current status message

        """
        # Simply emit the signal - Qt handles thread-safe delivery via queued connection
        self.progress_update.emit(files_found, status)


@final
class ProgressCalculator:
    """Helper class for calculating progress and ETA during file scanning."""

    def __init__(self, smoothing_window: int | None = None) -> None:
        """Initialize progress calculator.

        Args:
            smoothing_window: Number of samples for ETA smoothing

        """
        super().__init__()
        self.smoothing_window = smoothing_window or Config.PROGRESS_ETA_SMOOTHING_WINDOW
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.processing_times: deque[float] = deque(maxlen=self.smoothing_window)
        self.files_processed = 0
        self.total_files_estimate = 0

    def update(
        self,
        files_processed: int,
        total_estimate: int | None = None,
    ) -> tuple[float, str]:
        """Update progress and calculate ETA.

        Args:
            files_processed: Number of files processed so far
            total_estimate: Updated total file estimate (if available)

        Returns:
            Tuple of (progress_percentage, eta_string)

        """
        current_time = time.time()

        if total_estimate is not None:
            self.total_files_estimate = total_estimate

        # Calculate progress percentage
        if self.total_files_estimate > 0:
            progress_pct = min(
                100.0,
                (files_processed / self.total_files_estimate) * 100,
            )
        else:
            progress_pct = 0.0

        # Update processing rate for ETA calculation
        if files_processed > self.files_processed:
            time_delta = current_time - self.last_update_time
            if time_delta > 0:
                files_delta = files_processed - self.files_processed
                rate = files_delta / time_delta  # files per second
                self.processing_times.append(rate)

        self.files_processed = files_processed
        self.last_update_time = current_time

        # Calculate ETA
        eta_str = self._calculate_eta()

        return progress_pct, eta_str

    def _calculate_eta(self) -> str:
        """Calculate estimated time to completion.

        Returns:
            Human-readable ETA string

        """
        if (
            self.total_files_estimate <= 0
            or self.files_processed >= self.total_files_estimate
            or len(self.processing_times) == 0
        ):
            return ""

        # Calculate average processing rate
        avg_rate = sum(self.processing_times) / len(self.processing_times)

        if avg_rate <= 0:
            return ""

        remaining_files = self.total_files_estimate - self.files_processed
        eta_seconds = remaining_files / avg_rate

        # Format ETA
        if eta_seconds < 60:
            return f"~{int(eta_seconds)}s remaining"
        if eta_seconds < 3600:
            minutes = int(eta_seconds / 60)
            return f"~{minutes}m remaining"
        hours = int(eta_seconds / 3600)
        minutes = int((eta_seconds % 3600) / 60)
        return f"~{hours}h {minutes}m remaining"
