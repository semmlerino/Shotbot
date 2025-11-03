"""Centralized thread coordination for MainWindow.

This module manages all worker threads, provides proper cleanup, and handles
thread synchronization to prevent race conditions and resource leaks.
"""

from __future__ import annotations

# Standard library imports
import logging
from typing import TYPE_CHECKING, Protocol, cast

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    QThread,
    Signal,
)


if TYPE_CHECKING:
    # Local application imports
    from base_shot_model import BaseShotModel
    from threede_scene_model import ThreeDEScene, ThreeDESceneModel
    from threede_scene_worker import ThreeDESceneWorker


class WorkerWithStopProtocol(Protocol):
    """Protocol for workers with stop/request_stop methods."""

    def stop(self) -> None: ...
    def request_stop(self) -> None: ...
    def isRunning(self) -> bool: ...
    def wait(self, timeout: int) -> bool: ...
    def deleteLater(self) -> None: ...


logger = logging.getLogger(__name__)


class ThreadingManager(QObject):
    """Centralized manager for all worker threads in the application.

    This class provides:
    - Safe thread creation and cleanup
    - Progress reporting coordination
    - Resource leak prevention
    - Proper synchronization
    """

    # Consolidated signals for all threading operations
    threede_discovery_started = Signal()
    threede_discovery_progress = Signal(int, int, str)  # current, total, status
    threede_discovery_batch_ready = Signal(list)  # scenes batch
    threede_discovery_finished = Signal(list)  # all scenes
    threede_discovery_error = Signal(str)  # error message
    threede_discovery_paused = Signal()
    threede_discovery_resumed = Signal()

    def __init__(self) -> None:
        """Initialize threading manager."""
        super().__init__()

        # Thread tracking with mutex protection
        self._workers: dict[str, QThread] = {}
        self._mutex = QMutex()

        # Current 3DE worker tracking
        self._current_threede_worker: ThreeDESceneWorker | None = None
        self._threede_discovery_active = False

        logger.debug("ThreadingManager initialized")

    def start_threede_discovery(
        self,
        _threede_model: ThreeDESceneModel,
        shot_model: BaseShotModel,
    ) -> bool:
        """Start 3DE scene discovery in background thread.

        Args:
            threede_model: Model to populate with discovered scenes
            shot_model: Shot model for context

        Returns:
            True if discovery started, False if already running
        """
        with QMutexLocker(self._mutex):
            if self._threede_discovery_active:
                logger.warning("3DE discovery already in progress")
                return False

            # Import here to avoid circular imports
            # Local application imports
            from threede_scene_worker import ThreeDESceneWorker

            # Clean up any existing worker
            self._cleanup_threede_worker()

            # Create new worker
            worker_name = "threede_discovery"
            self._current_threede_worker = ThreeDESceneWorker(
                shots=shot_model.get_shots(),
                excluded_users=None,  # Use default excluded users
            )

            # Connect worker signals to our consolidated signals
            _ = self._current_threede_worker.started.connect(
                self.threede_discovery_started.emit
            )
            # ThreeDESceneWorker has 'progress' signal (int, int, float, str, str)
            # We map it to our threede_discovery_progress (int, int, str) by using a slot
            # The progress_update signal doesn't exist on ThreeDESceneWorker
            # Instead, connect the 'progress' signal directly
            _ = self._current_threede_worker.progress.connect(self._on_progress_update)
            _ = self._current_threede_worker.batch_ready.connect(
                self.threede_discovery_batch_ready.emit
            )
            # Signal is defined as Signal(list) without type parameter, causing Unknown inference
            # Our slot is properly typed as list[ThreeDEScene], runtime behavior is correct
            _ = self._current_threede_worker.finished.connect(
                self._on_threede_discovery_finished
            )
            _ = self._current_threede_worker.error.connect(self._on_threede_discovery_error)
            _ = self._current_threede_worker.paused.connect(
                self.threede_discovery_paused.emit
            )
            _ = self._current_threede_worker.resumed.connect(
                self.threede_discovery_resumed.emit
            )

            # Start worker thread
            self._current_threede_worker.start()
            self._workers[worker_name] = self._current_threede_worker
            self._threede_discovery_active = True

            logger.info("Started 3DE scene discovery thread")
            return True

    def _on_progress_update(
        self,
        current: int,
        total: int,
        _percentage: float,
        description: str,
        _eta: str,
    ) -> None:
        """Map worker progress signal to our simplified signal.

        Args:
            current: Current item count
            total: Total item count
            percentage: Progress percentage (unused)
            description: Status description
            eta: ETA string (unused)
        """
        # Emit our simplified progress signal
        self.threede_discovery_progress.emit(current, total, description)

    def _on_threede_discovery_finished(self, scenes: list[ThreeDEScene]) -> None:
        """Handle 3DE discovery completion.

        Args:
            scenes: List of discovered scenes
        """
        with QMutexLocker(self._mutex):
            self._threede_discovery_active = False

        # Forward signal
        self.threede_discovery_finished.emit(scenes)

        # Schedule cleanup
        self._schedule_worker_cleanup("threede_discovery")

    def _on_threede_discovery_error(self, error_message: str) -> None:
        """Handle 3DE discovery error.

        Args:
            error_message: Error description
        """
        with QMutexLocker(self._mutex):
            self._threede_discovery_active = False

        # Forward signal
        self.threede_discovery_error.emit(error_message)

        # Schedule cleanup
        self._schedule_worker_cleanup("threede_discovery")

    def pause_threede_discovery(self) -> bool:
        """Pause 3DE scene discovery.

        Returns:
            True if paused successfully, False if not running
        """
        with QMutexLocker(self._mutex):
            if self._current_threede_worker and self._threede_discovery_active:
                self._current_threede_worker.pause()
                return True
            return False

    def resume_threede_discovery(self) -> bool:
        """Resume 3DE scene discovery.

        Returns:
            True if resumed successfully, False if not paused
        """
        with QMutexLocker(self._mutex):
            if self._current_threede_worker and self._threede_discovery_active:
                self._current_threede_worker.resume()
                return True
            return False

    def stop_threede_discovery(self) -> bool:
        """Stop 3DE scene discovery gracefully.

        Returns:
            True if stopped successfully, False if not running
        """
        with QMutexLocker(self._mutex):
            if self._current_threede_worker and self._threede_discovery_active:
                self._current_threede_worker.stop()
                self._threede_discovery_active = False
                return True
            return False

    def is_threede_discovery_active(self) -> bool:
        """Check if 3DE discovery is currently active.

        Returns:
            True if discovery is running, False otherwise
        """
        with QMutexLocker(self._mutex):
            return self._threede_discovery_active

    def _cleanup_threede_worker(self) -> None:
        """Clean up current 3DE worker (called with mutex held)."""
        if self._current_threede_worker:
            if self._current_threede_worker.isRunning():
                logger.debug("Stopping existing 3DE worker")
                self._current_threede_worker.stop()
                if not self._current_threede_worker.wait(5000):  # 5 second timeout
                    logger.warning("3DE worker did not stop gracefully")

            # Clean up worker
            self._current_threede_worker.deleteLater()
            self._current_threede_worker = None

            # Remove from workers dict
            _ = self._workers.pop("threede_discovery", None)

    def _schedule_worker_cleanup(self, worker_name: str) -> None:
        """Schedule delayed cleanup of worker thread.

        Args:
            worker_name: Name of worker to clean up
        """
        # Use Qt's deleteLater for safe cleanup
        worker = self._workers.get(worker_name)
        if worker:
            worker.deleteLater()
            with QMutexLocker(self._mutex):
                _ = self._workers.pop(worker_name, None)

    def get_active_thread_count(self) -> int:
        """Get number of currently active threads.

        Returns:
            Number of active worker threads
        """
        with QMutexLocker(self._mutex):
            active_count = 0
            for worker in self._workers.values():
                if worker.isRunning():
                    active_count += 1
            return active_count

    def get_thread_status(self) -> dict[str, str]:
        """Get status of all managed threads.

        Returns:
            Dictionary mapping thread names to status strings
        """
        with QMutexLocker(self._mutex):
            status: dict[str, str] = {}
            for name, worker in self._workers.items():
                if worker.isRunning():
                    status[name] = "running"
                elif worker.isFinished():
                    status[name] = "finished"
                else:
                    status[name] = "ready"
            return status

    def shutdown_all_threads(self) -> None:
        """Shutdown all worker threads gracefully.

        This method should be called during application shutdown to ensure
        proper cleanup and prevent resource leaks.
        """
        logger.info("Shutting down all worker threads")

        with QMutexLocker(self._mutex):
            # Stop 3DE discovery if active
            if self._current_threede_worker:
                self._current_threede_worker.stop()
                self._threede_discovery_active = False

            # Wait for all threads to finish
            for name, worker in self._workers.items():
                if worker.isRunning():
                    logger.debug(f"Waiting for {name} thread to finish")
                    if not worker.wait(3000):  # 3 second timeout per thread
                        logger.warning(f"Thread {name} did not finish gracefully")

                # Schedule for deletion
                worker.deleteLater()

            # Clear all workers
            self._workers.clear()
            self._current_threede_worker = None

        logger.info("All worker threads shutdown complete")

    def add_custom_worker(self, name: str, worker: QThread) -> bool:
        """Add a custom worker thread to management.

        Args:
            name: Unique name for the worker
            worker: QThread instance to manage

        Returns:
            True if added successfully, False if name already exists
        """
        with QMutexLocker(self._mutex):
            if name in self._workers:
                logger.warning(f"Worker {name} already exists")
                return False

            self._workers[name] = worker
            worker.start()
            logger.debug(f"Added custom worker: {name}")
            return True

    def remove_worker(self, name: str) -> bool:
        """Remove and cleanup a specific worker.

        Args:
            name: Name of worker to remove

        Returns:
            True if removed successfully, False if not found
        """
        with QMutexLocker(self._mutex):
            worker = self._workers.get(name)
            if not worker:
                return False

            # Stop if running - use Protocol for type safety
            if worker.isRunning():
                # Try to stop the worker using known patterns
                # Cast through object to Protocol for type-safe attribute access
                if hasattr(worker, "request_stop"):
                    worker_with_stop = cast(
                        "WorkerWithStopProtocol", cast("object", worker)
                    )
                    worker_with_stop.request_stop()
                elif hasattr(worker, "stop"):
                    worker_with_stop = cast(
                        "WorkerWithStopProtocol", cast("object", worker)
                    )
                    worker_with_stop.stop()
                if not worker.wait(2000):
                    logger.warning(f"Worker {name} did not stop gracefully")

            # Clean up
            worker.deleteLater()
            del self._workers[name]

            # Special handling for 3DE worker
            if name == "threede_discovery":
                self._current_threede_worker = None
                self._threede_discovery_active = False

            logger.debug(f"Removed worker: {name}")
            return True
