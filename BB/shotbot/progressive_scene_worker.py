"""Enhanced QThread worker for progressive 3DE scene discovery.

This module provides a pausable, cancellable worker thread that performs
progressive scene discovery with batch emission and memory-efficient scanning.
"""

import logging
import time
from enum import Enum
from typing import List, Optional, Set

from PySide6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, Signal

from progressive_scene_finder import (
    ProgressiveSceneFinder,
    ShowWideProgressiveFinder,
)
from shot_model import Shot
from utils import ValidationUtils

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """Worker thread states."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FINISHED = "finished"
    ERROR = "error"


class ProgressiveSceneWorker(QThread):
    """Enhanced worker thread for progressive 3DE scene discovery.

    Features:
    - Progressive scene discovery with batched results
    - Pause/resume functionality
    - Cancellation support
    - Memory-efficient scanning
    - Detailed progress reporting with ETA
    """

    # Signals
    stateChanged = Signal(str)  # WorkerState value
    scanStarted = Signal()
    scanProgress = Signal(dict)  # Progress dictionary
    batchFound = Signal(list)  # Batch of ThreeDEScene objects
    scanFinished = Signal(int)  # Total scenes found
    scanError = Signal(str)  # Error message

    # Performance metrics
    metricsUpdated = Signal(dict)  # Performance metrics

    def __init__(
        self,
        shots: List[Shot],
        excluded_users: Optional[Set[str]] = None,
        batch_size: int = 10,
        yield_interval: float = 0.05,
    ):
        """Initialize the worker.

        Args:
            shots: List of shots to search
            excluded_users: Users to exclude
            batch_size: Number of scenes per batch
            yield_interval: Minimum time between yields (seconds)
        """
        super().__init__()

        self.shots = shots
        self.excluded_users = excluded_users or ValidationUtils.get_excluded_users()
        self.batch_size = batch_size
        self.yield_interval = yield_interval

        # State management
        self._state = WorkerState.IDLE
        self._state_mutex = QMutex()
        self._pause_condition = QWaitCondition()
        self._is_paused = False

        # Statistics
        self._total_scenes = 0
        self._start_time = 0.0
        self._pause_time = 0.0
        self._total_pause_duration = 0.0

        # Finder instances
        self._finder = ProgressiveSceneFinder(
            batch_size=batch_size, yield_interval=yield_interval, use_cache=True
        )
        self._show_finder = ShowWideProgressiveFinder(self._finder)

    # State management

    @property
    def state(self) -> WorkerState:
        """Get current state thread-safely."""
        with QMutexLocker(self._state_mutex):
            return self._state

    def _set_state(self, state: WorkerState) -> None:
        """Set state and emit signal."""
        with QMutexLocker(self._state_mutex):
            if self._state != state:
                self._state = state
                self.stateChanged.emit(state.value)

    def pause(self) -> None:
        """Pause the scanning operation."""
        if self.state == WorkerState.RUNNING:
            with QMutexLocker(self._state_mutex):
                self._is_paused = True
                self._pause_time = time.time()
            self._set_state(WorkerState.PAUSED)
            logger.info("Scene discovery paused")

    def resume(self) -> None:
        """Resume the scanning operation."""
        if self.state == WorkerState.PAUSED:
            with QMutexLocker(self._state_mutex):
                self._is_paused = False
                if self._pause_time > 0:
                    self._total_pause_duration += time.time() - self._pause_time
                    self._pause_time = 0.0
                self._pause_condition.wakeAll()
            self._set_state(WorkerState.RUNNING)
            logger.info("Scene discovery resumed")

    def cancel(self) -> None:
        """Cancel the scanning operation."""
        logger.info("Cancellation requested")
        self._set_state(WorkerState.CANCELLING)

        # Cancel finder
        self._finder.cancel()
        self._show_finder.cancel()

        # Wake if paused
        if self._is_paused:
            with QMutexLocker(self._state_mutex):
                self._is_paused = False
                self._pause_condition.wakeAll()

    def _check_pause(self) -> bool:
        """Check if paused and wait if necessary.

        Returns:
            True if should continue, False if cancelled
        """
        with QMutexLocker(self._state_mutex):
            while self._is_paused:
                self._pause_condition.wait(self._state_mutex)

                # Check if cancelled while paused
                if self.state == WorkerState.CANCELLING:
                    return False

        # Check cancellation
        return self.state != WorkerState.CANCELLING

    # Main execution

    def run(self) -> None:
        """Main worker thread execution."""
        try:
            self._start_time = time.time()
            self._total_scenes = 0
            self._total_pause_duration = 0.0

            self._set_state(WorkerState.RUNNING)
            self.scanStarted.emit()

            logger.info(
                f"Starting progressive 3DE scene discovery for {len(self.shots)} shots"
            )

            if not self.shots:
                logger.warning("No shots provided")
                self._finish_scan()
                return

            # Check initial pause/cancel
            if not self._check_pause():
                self._handle_cancellation()
                return

            # Perform progressive discovery
            self._discover_scenes_progressive()

            # Check final state
            if self.state == WorkerState.CANCELLING:
                self._handle_cancellation()
            else:
                self._finish_scan()

        except Exception as e:
            logger.error(f"Error in progressive scene worker: {e}")
            self._set_state(WorkerState.ERROR)
            self.scanError.emit(str(e))

    def _discover_scenes_progressive(self) -> None:
        """Perform progressive scene discovery."""
        last_metrics_time = time.time()
        metrics_interval = 1.0  # Update metrics every second

        # Use show-wide progressive finder
        for batch, progress in self._show_finder.find_all_scenes_progressive(
            self.shots, self.excluded_users
        ):
            # Check pause/cancel
            if not self._check_pause():
                return

            # Process batch
            if batch:
                self._total_scenes += len(batch)
                self.batchFound.emit(batch)

                # Emit progress
                progress_dict = {
                    "total_directories": progress.total_directories,
                    "scanned_directories": progress.scanned_directories,
                    "total_files": progress.total_files,
                    "scanned_files": progress.scanned_files,
                    "scenes_found": self._total_scenes,
                    "current_path": progress.current_path,
                    "progress_percent": progress.progress_percent,
                    "eta_seconds": progress.eta_seconds,
                    "scan_rate": progress.scan_rate,
                }
                self.scanProgress.emit(progress_dict)

            # Update performance metrics periodically
            current_time = time.time()
            if current_time - last_metrics_time >= metrics_interval:
                self._emit_metrics()
                last_metrics_time = current_time

    def _finish_scan(self) -> None:
        """Finish the scanning operation."""
        self._set_state(WorkerState.FINISHED)
        self.scanFinished.emit(self._total_scenes)

        # Final metrics
        self._emit_metrics()

        elapsed = time.time() - self._start_time - self._total_pause_duration
        logger.info(
            f"Progressive scan completed: {self._total_scenes} scenes in {elapsed:.1f}s"
        )

    def _handle_cancellation(self) -> None:
        """Handle scan cancellation."""
        self._set_state(WorkerState.CANCELLED)
        logger.info(f"Scan cancelled after finding {self._total_scenes} scenes")

        # Emit partial results
        self.scanFinished.emit(self._total_scenes)

    def _emit_metrics(self) -> None:
        """Emit performance metrics."""
        elapsed = time.time() - self._start_time - self._total_pause_duration

        metrics = {
            "total_scenes": self._total_scenes,
            "elapsed_seconds": elapsed,
            "pause_duration": self._total_pause_duration,
            "scenes_per_second": self._total_scenes / elapsed if elapsed > 0 else 0,
            "state": self.state.value,
        }

        self.metricsUpdated.emit(metrics)


class ProgressiveSceneManager:
    """Manager for progressive scene discovery operations."""

    def __init__(self):
        """Initialize the manager."""
        self._worker: Optional[ProgressiveSceneWorker] = None
        self._worker_mutex = QMutex()

    def start_discovery(
        self,
        shots: List[Shot],
        excluded_users: Optional[Set[str]] = None,
        batch_size: int = 10,
    ) -> ProgressiveSceneWorker:
        """Start a new discovery operation.

        Args:
            shots: Shots to search
            excluded_users: Users to exclude
            batch_size: Scenes per batch

        Returns:
            The worker thread instance
        """
        with QMutexLocker(self._worker_mutex):
            # Cancel existing worker if any
            if self._worker and self._worker.isRunning():
                self._worker.cancel()
                self._worker.wait(5000)  # Wait up to 5 seconds

            # Create new worker
            self._worker = ProgressiveSceneWorker(
                shots=shots, excluded_users=excluded_users, batch_size=batch_size
            )

            # Connect cleanup
            self._worker.finished.connect(self._on_worker_finished)

            # Start discovery
            self._worker.start()

            return self._worker

    def pause_discovery(self) -> None:
        """Pause the current discovery operation."""
        with QMutexLocker(self._worker_mutex):
            if self._worker:
                self._worker.pause()

    def resume_discovery(self) -> None:
        """Resume the current discovery operation."""
        with QMutexLocker(self._worker_mutex):
            if self._worker:
                self._worker.resume()

    def cancel_discovery(self) -> None:
        """Cancel the current discovery operation."""
        with QMutexLocker(self._worker_mutex):
            if self._worker:
                self._worker.cancel()

    def get_worker(self) -> Optional[ProgressiveSceneWorker]:
        """Get the current worker instance."""
        with QMutexLocker(self._worker_mutex):
            return self._worker

    def _on_worker_finished(self) -> None:
        """Handle worker completion."""
        logger.info("Progressive scene discovery worker finished")
