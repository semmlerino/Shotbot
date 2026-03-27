"""Thread-safe worker for background 3DE scene discovery."""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, ClassVar, final

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    Qt,
    QThread,
    QWaitCondition,
    Signal,
)

# Local application imports
from config import Config
from threede.progress_tracker import ProgressCalculator, QtProgressReporter
from threede.scene_discovery_coordinator import SceneDiscoveryCoordinator
from typing_compat import override
from utils import get_excluded_users
from workers.thread_safe_worker import ThreadSafeWorker


if TYPE_CHECKING:
    # Local application imports
    from type_definitions import Shot, ThreeDEScene

# Set up logger for this module


@final
class ThreeDESceneWorker(ThreadSafeWorker):
    """Thread-safe worker for progressive 3DE scene discovery.

    This worker inherits from ThreadSafeWorker to provide:
    - Thread-safe state management
    - Safe signal connection tracking
    - Proper lifecycle management
    - Race condition prevention

    Additional features:
    - Progressive/batched file scanning for responsive UI
    - Cancellation and pause/resume functionality
    - Detailed progress reporting with ETA calculation
    - Memory-aware processing with configurable limits
    """

    # Enhanced signals specific to 3DE discovery
    worker_discovery_started: ClassVar[Signal] = (
        Signal()
    )  # Emitted when discovery starts
    progress: ClassVar[Signal] = Signal(
        int,
        int,
        float,
        str,
        str,
    )  # (current, total, percentage, description, eta)
    scan_progress: ClassVar[Signal] = Signal(
        int, int, str
    )  # Emitted during individual shot scanning
    discovery_finished: ClassVar[Signal] = Signal(
        object
    )  # Emitted with complete list of scenes
    error: ClassVar[Signal] = Signal(str)  # Emitted when an error occurs

    def __init__(
        self,
        shots: list[Shot],
        excluded_users: set[str] | None = None,
        batch_size: int | None = None,
    ) -> None:
        """Initialize the enhanced worker with shots to search.

        Args:
            shots: List of shots to use for determining shows to search
            excluded_users: Set of usernames to exclude from search
            batch_size: Number of scenes per batch for progressive scanning

        """
        super().__init__()
        self.shots = shots
        self.user_shots = shots  # Keep track of user's shots for filtering
        self.excluded_users = excluded_users or get_excluded_users()
        self.batch_size = batch_size or Config.PROGRESSIVE_SCAN_BATCH_SIZE

        # Control flags
        self._is_paused = False  # Only pause flag needed, stop is managed by base class

        # Thread synchronization
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()

        # Progress tracking
        self._progress_calculator = ProgressCalculator()
        self._last_progress_time = 0.0
        self._all_scenes: list[ThreeDEScene] = []
        self._files_processed = 0
        # Progress reporter will be created in do_work() to prevent race condition
        self._progress_reporter: QtProgressReporter | None = None

        # Error count from scene discovery coordinator (read by controller after signal fires)
        self.discovery_errors: int = 0

        # Thread safety for finished signal emission (simplified)
        self._finished_mutex = QMutex()
        self._finished_emitted = False

        # Store desired priority for setting after thread starts
        priority_map = {
            -1: QThread.Priority.LowPriority,
            0: QThread.Priority.NormalPriority,
            1: QThread.Priority.HighPriority,
        }
        self._desired_priority = priority_map.get(
            Config.WORKER_THREAD_PRIORITY,
            QThread.Priority.NormalPriority,
        )

    @override
    def run(self) -> None:
        """Override run to ensure finished signal is always emitted.

        This ensures that the finished signal is emitted even when the thread
        is interrupted via requestInterruption(), not just when stopped normally.
        """
        # Reset finished flag at start
        with QMutexLocker(self._finished_mutex):
            self._finished_emitted = False

        try:
            # Call parent's run() which manages state and calls do_work()
            super().run()  # pyright: ignore[reportAny]
        finally:
            # Ensure finished signal is emitted exactly once
            _ = self._emit_finished_signal_once()

    def _emit_finished_signal_once(
        self, scenes: list[ThreeDEScene] | None = None
    ) -> bool:
        """Emit finished signal exactly once, thread-safely.

        Args:
            scenes: Optional list of scenes to emit. If None, uses self._all_scenes

        Returns:
            bool: True if signal was emitted, False if already emitted

        """
        with QMutexLocker(self._finished_mutex):
            if self._finished_emitted:
                return False
            self._finished_emitted = True

        # Emit outside the lock to prevent deadlocks
        scenes_to_emit = scenes if scenes is not None else (self._all_scenes or [])

        if not scenes_to_emit:
            self.logger.debug(
                "Worker finishing, emitting finished signal with empty list"
            )
        else:
            self.logger.debug(
                f"Worker finishing, emitting finished signal with {len(scenes_to_emit)} scenes"
            )

        self.discovery_finished.emit(scenes_to_emit)
        return True

    def _handle_progress_update(self, files_found: int, status: str) -> None:
        """Handle progress updates from the reporter.

        This method runs in the worker's QThread and can safely emit Qt signals.
        It's called via queued connection from the progress reporter.

        Args:
            files_found: Number of files found so far
            status: Current status message

        """
        # Check if worker is still active
        if not self.should_stop():
            # Emit the progress signals safely from the worker thread
            self.progress.emit(
                files_found,  # current files found
                0,  # total unknown during scanning
                0.0,  # percentage unknown during scanning
                status,  # current status message
                "",  # ETA not available during parallel scan
            )

            # Also emit scan progress for compatibility
            self.scan_progress.emit(files_found, 0, status)

    @override
    def do_work(self) -> None:
        """Enhanced main worker thread execution with progressive scanning.

        This replaces the run() method to follow ThreadSafeWorker pattern.
        The base class run() method handles state management and calls this.
        """
        try:
            # Set thread priority now that thread is running
            self.setPriority(self._desired_priority)

            # Create progress reporter in worker thread to prevent race condition
            # This ensures it's created in the correct thread context from the start
            self._progress_reporter = QtProgressReporter()

            # Connect the reporter's signal to our handler with QueuedConnection
            # This ensures all signal emission happens in the correct Qt thread
            _ = self._progress_reporter.progress_update.connect(
                self._handle_progress_update, Qt.ConnectionType.QueuedConnection
            )
            self.logger.debug(
                "Progress reporter created and connected in worker thread"
            )

            # Emit started signal (specific discovery mode will be logged by sub-methods)
            self.worker_discovery_started.emit()

            if not self.shots:
                self.logger.warning("No shots provided for 3DE scene discovery")
                _ = self._emit_finished_signal_once([])
                return

            # Check for initial cancellation using base class method
            if self.should_stop():
                self.logger.info("3DE scene discovery cancelled before starting")
                _ = self._emit_finished_signal_once([])
                return

            # Perform progressive scene discovery
            scenes = self._discover_all_scenes_in_shows()

            # Final cancellation check
            if self.should_stop():
                self.logger.info("3DE scene discovery cancelled during processing")
                # Return partial results
                _ = self._emit_finished_signal_once()
                return

            self.logger.info(
                f"Enhanced 3DE scene discovery completed: {len(scenes)} scenes found",
            )
            # Emit final results
            _ = self._emit_finished_signal_once(scenes)

        except Exception as e:
            self.logger.exception("Error in enhanced 3DE scene discovery worker")
            self.error.emit(str(e))
            # Re-raise to trigger worker_error signal from base class
            raise

    def _discover_all_scenes_in_shows(self) -> list[ThreeDEScene]:
        """Discover ALL 3DE scenes in the shows using parallel scanning.

        This uses the new parallel file-first discovery to find ALL 3DE files
        with frequent progress updates, then filters out user's shots.

        Returns:
            List of all discovered ThreeDEScene objects

        """
        self.logger.info(
            "Discovering ALL 3DE scenes in shows using parallel file-first strategy"
        )

        # Create progress callback that uses the Qt progress reporter
        def progress_callback(files_found: int, status: str) -> None:
            """Forward progress updates to UI with cancellation check.

            This callback runs in ThreadPoolExecutor worker threads, so it uses
            the progress reporter which handles thread-safe signal emission via
            Qt's queued connection mechanism.
            """
            if self.should_stop():
                return

            # Use the progress reporter which will queue the signal emission
            # This ensures thread-safe delivery without complex workarounds
            # Add null check to prevent race condition with reporter creation
            if self._progress_reporter is not None:
                self._progress_reporter.report_progress(files_found, status)

        # Create cancel flag callback
        def cancel_flag() -> bool:
            """Check if scan should be cancelled."""
            return self.should_stop()

        # Use the new parallel file-first discovery
        self.logger.info("Using parallel discovery with progress reporting")
        all_scenes = (
            SceneDiscoveryCoordinator.find_all_scenes_in_shows_truly_efficient_parallel(
                self.user_shots,  # Used to determine which shows to search
                self.excluded_users,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
            )
        )

        # Check for cancellation after scan
        if self.should_stop():
            self.logger.info("3DE scene discovery cancelled during parallel scan")
            return []

        # Keep ALL scenes from other users in the shows where user works
        other_scenes = all_scenes

        self.logger.info(
            f"Found {len(all_scenes)} total scenes using parallel scan, keeping all {len(other_scenes)} scenes from other users",
        )

        # Emit final progress update
        if not self.should_stop():
            status_msg = f"Completed: Found {len(other_scenes)} scenes from other users in all shows"

            self.progress.emit(
                len(other_scenes),
                len(all_scenes),
                100.0,
                status_msg,
                "",
            )

        return other_scenes
