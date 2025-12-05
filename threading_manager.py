"""Centralized thread coordination for MainWindow.

This module manages all worker threads, provides proper cleanup, and handles
thread synchronization to prevent race conditions and resource leaks.
"""

from __future__ import annotations

# Standard library imports
import logging
from typing import TYPE_CHECKING, Protocol, cast, final

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    QThread,
    QTimer,
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


@final
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

        # Zombie worker tracking - workers that failed to stop gracefully
        self._zombie_workers: list[QThread] = []

        # Cleanup timer storage - prevents GC of timers before they fire
        self._cleanup_timers: dict[int, QTimer] = {}

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
        # Phase 1: Check state, claim ownership, and grab old worker reference
        old_worker: ThreeDESceneWorker | None = None
        with QMutexLocker(self._mutex):
            if self._threede_discovery_active:
                logger.warning("3DE discovery already in progress")
                return False

            # Claim ownership IMMEDIATELY (prevents TOCTOU race condition)
            self._threede_discovery_active = True

            # Grab reference to old worker for cleanup outside lock
            old_worker = self._current_threede_worker
            self._current_threede_worker = None
            _ = self._workers.pop("threede_discovery", None)

        # Phase 2: Stop old worker OUTSIDE lock (non-blocking cleanup)
        if old_worker is not None:
            worker_to_cleanup = old_worker  # Capture for lambda (typed narrowing)
            if worker_to_cleanup.isRunning():
                logger.debug("Stopping existing 3DE worker")
                worker_to_cleanup.stop()
                # Non-blocking cleanup using signals - never blocks UI thread
                self._schedule_worker_cleanup_with_timeout(worker_to_cleanup)
            else:
                worker_to_cleanup.deleteLater()

        # Phase 3: Create new worker under lock
        try:
            with QMutexLocker(self._mutex):
                # Import here to avoid circular imports
                # Local application imports
                from threede_scene_worker import ThreeDESceneWorker

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
                _ = self._current_threede_worker.progress.connect(
                    self._on_progress_update
                )
                _ = self._current_threede_worker.batch_ready.connect(
                    self.threede_discovery_batch_ready.emit
                )
                # Signal is defined as Signal(list) without type parameter
                # Our slot is properly typed as list[ThreeDEScene], runtime is correct
                _ = self._current_threede_worker.finished.connect(
                    self._on_threede_discovery_finished
                )
                _ = self._current_threede_worker.error.connect(
                    self._on_threede_discovery_error
                )
                _ = self._current_threede_worker.paused.connect(
                    self.threede_discovery_paused.emit
                )
                _ = self._current_threede_worker.resumed.connect(
                    self.threede_discovery_resumed.emit
                )

                # Start worker thread
                self._current_threede_worker.start()
                self._workers[worker_name] = self._current_threede_worker

                logger.info("Started 3DE scene discovery thread")
                return True
        except Exception as e:
            # Reset flag on failure so discovery can be retried
            with QMutexLocker(self._mutex):
                self._threede_discovery_active = False
            logger.error(f"Failed to start 3DE discovery: {e}")
            return False

    def _schedule_worker_cleanup_with_timeout(self, worker: QThread) -> None:
        """Non-blocking cleanup using finished signal + timeout fallback.

        This method is truly non-blocking - it uses Qt signals instead of
        worker.wait() which would block the UI thread.

        Args:
            worker: The worker thread to clean up
        """
        # Connect finished signal for cleanup (safe even if already finished)
        _ = worker.finished.connect(worker.deleteLater)

        if not worker.isRunning():
            # Already finished, schedule deletion
            worker.deleteLater()
            return

        # Set up timeout fallback - if worker doesn't finish in time, track as zombie
        # Use self as parent and store reference to prevent GC before timeout fires
        cleanup_timer = QTimer(self)
        cleanup_timer.setSingleShot(True)
        worker_id = id(worker)
        self._cleanup_timers[worker_id] = cleanup_timer

        def on_timeout() -> None:
            # Remove stored reference
            self._cleanup_timers.pop(worker_id, None)
            cleanup_timer.deleteLater()
            if worker.isRunning():
                logger.warning("3DE worker did not stop gracefully within timeout")
                with QMutexLocker(self._mutex):
                    self._zombie_workers.append(worker)
            # Note: deleteLater already connected to finished signal

        def on_finished() -> None:
            # Worker finished before timeout - stop the timer and remove reference
            self._cleanup_timers.pop(worker_id, None)
            cleanup_timer.stop()
            cleanup_timer.deleteLater()

        _ = cleanup_timer.timeout.connect(on_timeout)
        _ = worker.finished.connect(on_finished)
        cleanup_timer.start(5000)  # 5 second timeout

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

    def _schedule_worker_cleanup(self, worker_name: str) -> None:
        """Schedule delayed cleanup of worker thread.

        Args:
            worker_name: Name of worker to clean up
        """
        # Pop from dict under lock to prevent race condition
        with QMutexLocker(self._mutex):
            worker = self._workers.pop(worker_name, None)

        # Use Qt's deleteLater for safe cleanup (outside lock - we own the reference)
        if worker:
            worker.deleteLater()

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

        # Phase 1: Stop all workers and grab references under lock
        workers_to_wait: list[tuple[str, QThread]] = []
        with QMutexLocker(self._mutex):
            # Stop 3DE discovery if active
            if self._current_threede_worker:
                self._current_threede_worker.stop()
                self._threede_discovery_active = False

            # Grab references and issue stop commands
            for name, worker in self._workers.items():
                workers_to_wait.append((name, worker))
                # Issue stop command if worker has stop method
                if hasattr(worker, "stop"):
                    worker_with_stop = cast("WorkerWithStopProtocol", cast("object", worker))
                    worker_with_stop.stop()

            # Clear state under lock
            self._workers.clear()
            self._current_threede_worker = None

        # Phase 2: Wait for all threads OUTSIDE lock (avoids multi-second UI freeze)
        for name, worker in workers_to_wait:
            if worker.isRunning():
                logger.debug(f"Waiting for {name} thread to finish")
                if not worker.wait(3000):  # 3 second timeout per thread
                    logger.warning(
                        f"Thread {name} did not finish gracefully - tracking as zombie"
                    )
                    # Track as zombie like remove_worker() does
                    with QMutexLocker(self._mutex):
                        self._zombie_workers.append(worker)
                    # DON'T call deleteLater on still-running thread - it will be
                    # cleaned up in Phase 3 or by periodic zombie cleanup
                    continue

            # Only deleteLater if actually stopped
            worker.deleteLater()

        # Phase 3: Force-cleanup any zombie workers from previous operations
        # Grab zombie list under lock, then clean up outside
        with QMutexLocker(self._mutex):
            zombies_to_cleanup = list(self._zombie_workers)
            self._zombie_workers.clear()

        if zombies_to_cleanup:
            logger.info(f"Cleaning up {len(zombies_to_cleanup)} zombie worker(s)")
            for zombie in zombies_to_cleanup:
                if zombie.isRunning():
                    logger.warning("Force-terminating zombie worker")
                    zombie.terminate()
                    _ = zombie.wait(1000)  # Brief wait after terminate
                zombie.deleteLater()

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

        Uses two-phase pattern to avoid holding mutex during blocking wait().

        Args:
            name: Name of worker to remove

        Returns:
            True if removed successfully, False if not found
        """
        # Phase 1: Grab reference and remove from dict under lock
        worker: QThread | None = None
        is_threede = name == "threede_discovery"

        with QMutexLocker(self._mutex):
            worker = self._workers.get(name)
            if not worker:
                return False

            # Remove from dict and update state while we have the lock
            del self._workers[name]
            if is_threede:
                self._current_threede_worker = None
                self._threede_discovery_active = False

        # Phase 2: Stop and wait OUTSIDE lock (avoids UI freeze)
        if worker.isRunning():
            # Try to stop the worker using known patterns
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
                logger.warning(f"Worker {name} did not stop gracefully - tracking as zombie")
                # Protect zombie list access with mutex
                with QMutexLocker(self._mutex):
                    self._zombie_workers.append(worker)
                # DON'T call deleteLater on zombies - they're still running
                # Zombie cleanup happens in shutdown_all_threads()
                logger.debug(f"Worker {name} tracked as zombie - skipping deleteLater")
                return True

        # Only schedule for deletion if worker actually stopped
        worker.deleteLater()
        logger.debug(f"Removed worker: {name}")
        return True
