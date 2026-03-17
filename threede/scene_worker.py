"""Thread-safe worker for background 3DE scene discovery."""

from __future__ import annotations

# Standard library imports
import time
from pathlib import Path
from typing import TYPE_CHECKING, final

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
from discovery.filesystem_scanner import FileSystemScanner
from discovery.scene_discovery_coordinator import SceneDiscoveryCoordinator
from threede.progress_tracker import ProgressCalculator, QtProgressReporter
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
    worker_discovery_started = Signal()  # Emitted when discovery starts
    batch_ready = Signal(object)  # Emitted with each batch of scenes
    progress = Signal(
        int,
        int,
        float,
        str,
        str,
    )  # (current, total, percentage, description, eta)
    scan_progress = Signal(int, int, str)  # Emitted during individual shot scanning
    discovery_finished = Signal(object)  # Emitted with complete list of scenes
    error = Signal(str)  # Emitted when an error occurs

    def __init__(
        self,
        shots: list[Shot],
        excluded_users: set[str] | None = None,
        batch_size: int | None = None,
        enable_progressive: bool = True,
        scan_all_shots: bool = False,
    ) -> None:
        """Initialize the enhanced worker with shots to search.

        Args:
            shots: List of shots to use for determining shows to search
            excluded_users: Set of usernames to exclude from search
            batch_size: Number of scenes per batch for progressive scanning
            enable_progressive: Enable progressive scanning (vs. traditional all-at-once)
            scan_all_shots: If True, scan ALL shots in shows (not just provided shots)

        """
        super().__init__()
        self.shots = shots
        self.user_shots = shots  # Keep track of user's shots for filtering
        self.scan_all_shots = scan_all_shots
        self.excluded_users = excluded_users or get_excluded_users()
        self.batch_size = batch_size or Config.PROGRESSIVE_SCAN_BATCH_SIZE
        self.enable_progressive = enable_progressive and Config.PROGRESSIVE_SCAN_ENABLED

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

    def stop(self) -> None:
        """Request the worker to stop processing.

        Uses the thread-safe base class stop mechanism.
        """
        self.logger.debug("Stop requested for 3DE scene worker")
        # Use base class thread-safe stop FIRST (sets _stop_requested = True)
        _ = self.request_stop()
        # Then wake up paused thread so it can check stop condition and exit
        self._pause_mutex.lock()
        try:
            self._pause_condition.wakeAll()
        finally:
            self._pause_mutex.unlock()

    def pause(self) -> None:
        """Request the worker to pause processing."""
        self.logger.debug("Pause requested for 3DE scene worker")
        self._pause_mutex.lock()
        try:
            self._is_paused = True
        finally:
            self._pause_mutex.unlock()

    def resume(self) -> None:
        """Resume processing if paused."""
        self.logger.debug("Resume requested for 3DE scene worker")
        self._pause_mutex.lock()
        try:
            if self._is_paused:
                self._is_paused = False
                self._pause_condition.wakeAll()
        finally:
            self._pause_mutex.unlock()

    def is_paused(self) -> bool:
        """Check if worker is currently paused."""
        self._pause_mutex.lock()
        try:
            return self._is_paused
        finally:
            self._pause_mutex.unlock()

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
        scenes_to_emit = (
            scenes
            if scenes is not None
            else (self._all_scenes or [])
        )

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

    def _check_pause_and_cancel(self) -> bool:
        """Check for pause/cancel requests and handle them.

        Returns:
            True if should continue, False if should exit

        """
        # Check for cancellation using base class method
        if self.should_stop():
            self.logger.debug("Worker received stop signal")
            return False

        # Check for pause
        self._pause_mutex.lock()
        try:
            while self._is_paused and not self.should_stop():
                self.logger.debug("Worker paused, waiting for resume...")
                _ = self._pause_condition.wait(
                    self._pause_mutex,
                    Config.WORKER_PAUSE_CHECK_INTERVAL_MS,
                )
        finally:
            self._pause_mutex.unlock()

        # Check cancellation again after pause
        return not self.should_stop()

    @override
    def do_work(self) -> None:
        """Enhanced main worker thread execution with progressive scanning.

        This replaces the run() method to follow ThreadSafeWorker pattern.
        The base class run() method handles state management and calls this.
        """
        try:
            # Set thread priority now that thread is running
            if hasattr(self, "_desired_priority"):
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

            # Choose discovery method based on configuration
            if self.enable_progressive:
                scenes = self._discover_scenes_progressive()
            else:
                scenes = self._discover_scenes_traditional()

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

    def _discover_scenes_progressive(self) -> list[ThreeDEScene]:
        """Progressive scene discovery with batch processing and detailed progress.

        Returns:
            List of all discovered ThreeDEScene objects

        """
        self.logger.info("Starting progressive 3DE scene discovery")

        if self.scan_all_shots:
            # When scanning all shots, use the efficient file-first discovery
            # This finds ALL 3DE files in the shows, then filters
            return self._discover_all_scenes_in_shows()

        # Original behavior: scan only the provided shots
        # Convert shots to the format expected by the finder
        shot_tuples: list[tuple[str, str, str, str]] = [
            (str(shot.workspace_path), shot.show, shot.sequence, shot.shot)
            for shot in self.shots
        ]

        # Get size estimation for progress calculation
        try:
            estimated_users, estimated_files = FileSystemScanner().estimate_scan_size(
                shot_tuples,
                self.excluded_users,
            )
            self.logger.debug(
                f"Scan estimate: {estimated_users} users, ~{estimated_files} files",
            )

            # Initialize progress tracking
            self._progress_calculator = ProgressCalculator()
            self._files_processed = 0

            # Emit initial progress
            progress_pct, eta_str = self._progress_calculator.update(0, estimated_files)
            self.progress.emit(
                0,
                estimated_files,
                progress_pct,
                f"Starting scan of {len(shot_tuples)} shots",
                eta_str,
            )

        except Exception:  # noqa: BLE001
            self.logger.warning("Could not estimate scan size", exc_info=True)
            estimated_files = len(shot_tuples) * 10  # Fallback estimate

        # Discover scenes per shot and emit batches with progress updates
        coordinator = SceneDiscoveryCoordinator()
        total_shots = len(shot_tuples)
        try:
            for current_shot_idx, (workspace_path, show, sequence, shot) in enumerate(
                shot_tuples, start=1
            ):
                # Check for pause/cancel between shots
                if not self._check_pause_and_cancel():
                    break

                status_msg = f"Scanning {show}/{sequence}/{shot}"
                scene_batch = coordinator.find_scenes_for_shot(
                    workspace_path, show, sequence, shot, self.excluded_users
                )

                # Add batch to accumulated results
                if scene_batch:
                    self._all_scenes.extend(scene_batch)
                    self.batch_ready.emit(scene_batch)

                    self.logger.debug(f"Processed batch of {len(scene_batch)} scenes")

                # Update progress tracking
                self._files_processed += len(scene_batch)

                # Throttle progress updates
                current_time = time.time()
                if (current_time - self._last_progress_time) >= (
                    Config.PROGRESS_UPDATE_INTERVAL_MS / 1000.0
                ):
                    progress_pct, eta_str = self._progress_calculator.update(
                        self._files_processed,
                        estimated_files,
                    )

                    detailed_status = (
                        f"{status_msg} ({len(self._all_scenes)} scenes found)"
                    )

                    self.progress.emit(
                        current_shot_idx,
                        total_shots,
                        progress_pct,
                        detailed_status,
                        eta_str,
                    )

                    self._last_progress_time = current_time

                # Emit scan progress for fine-grained updates
                self.scan_progress.emit(current_shot_idx, total_shots, status_msg)

        except Exception:
            self.logger.exception("Error in progressive discovery")
            raise

        self.discovery_errors = coordinator.stats["errors"]
        return self._all_scenes

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

        # Create a set of user's shot identifiers for filtering
        user_shot_ids: set[str] = set()
        for shot in self.user_shots:
            shot_id = f"{shot.show}/{shot.sequence}/{shot.shot}"
            user_shot_ids.add(shot_id)

        # Filter to keep only scenes from user's shots (from other users)
        other_scenes: list[ThreeDEScene] = []
        for scene in all_scenes:
            if self.should_stop():
                break

            scene_id = f"{scene.show}/{scene.sequence}/{scene.shot}"

            # When scan_all_shots=True, keep ALL scenes from other users in the shows
            # Otherwise, only keep scenes from user's specific shots
            if self.scan_all_shots:
                # Keep all scenes from other users in the shows where user works
                other_scenes.append(scene)
            elif scene_id in user_shot_ids:
                # Keep only scenes from user's specific shots
                other_scenes.append(scene)

        # Log appropriate message based on scan mode
        if self.scan_all_shots:
            self.logger.info(
                f"Found {len(all_scenes)} total scenes using parallel scan, keeping all {len(other_scenes)} scenes from other users",
            )
        else:
            self.logger.info(
                f"Found {len(all_scenes)} total scenes using parallel scan, {len(other_scenes)} are from other users on assigned shots",
            )

        # Emit final progress update
        if not self.should_stop():
            if self.scan_all_shots:
                status_msg = f"Completed: Found {len(other_scenes)} scenes from other users in all shows"
            else:
                status_msg = f"Completed: Found {len(other_scenes)} scenes from other users on your shots"

            self.progress.emit(
                len(other_scenes),
                len(all_scenes),
                100.0,
                status_msg,
                "",
            )

        return other_scenes

    def _discover_scenes_traditional(self) -> list[ThreeDEScene]:
        """Traditional scene discovery method for backward compatibility.

        Returns:
            List of discovered ThreeDEScene objects

        """
        self.logger.info("Using traditional 3DE scene discovery method")

        all_scenes: list[ThreeDEScene] = []

        # Extract unique shows and show roots
        shows_to_search: set[str] = set()
        show_roots: set[str] = set()

        for shot in self.shots:
            shows_to_search.add(shot.show)
            # Extract show root from workspace path
            workspace_parts = Path(shot.workspace_path).parts
            if "shows" in workspace_parts:
                shows_idx = workspace_parts.index("shows")
                show_root = "/".join(workspace_parts[: shows_idx + 1])
                show_roots.add(show_root)

        if not show_roots:
            # Use configured show roots or fallback
            configured_roots = (
                Config.SHOW_ROOT_PATHS
                if hasattr(Config, "SHOW_ROOT_PATHS")
                else ["/shows"]
            )
            show_roots = set(configured_roots)

        total_shows = len(shows_to_search)
        current_show = 0

        # Process each show
        for show_root in show_roots:
            for show in shows_to_search:
                if not self._check_pause_and_cancel():
                    break

                current_show += 1
                self.progress.emit(
                    current_show,
                    total_shows,
                    0.0,
                    f"Discovering shots in {show}",
                    "",
                )

                # Discover all shots in this show
                all_shots = FileSystemScanner().discover_all_shots_in_show(
                    show_root,
                    show,
                )

                if not all_shots:
                    self.logger.warning(f"No shots discovered in {show}")
                    continue

                self.progress.emit(
                    current_show,
                    total_shows,
                    0.0,
                    f"Searching {len(all_shots)} shots in {show}",
                    "",
                )

                # Search each discovered shot with periodic progress updates
                for shot_count, (workspace_path, show_name, sequence, shot) in enumerate(
                    all_shots, start=1
                ):
                    if not self._check_pause_and_cancel():
                        break

                    # Update progress every 10 shots to avoid too many signals
                    if shot_count % 10 == 0:
                        progress_pct = (shot_count / len(all_shots)) * 100
                        self.progress.emit(
                            current_show,
                            total_shows,
                            progress_pct,
                            f"Searching {show} ({shot_count}/{len(all_shots)} shots)",
                            "",
                        )

                    scenes = SceneDiscoveryCoordinator().find_scenes_for_shot(
                        workspace_path,
                        show_name,
                        sequence,
                        shot,
                        self.excluded_users,
                    )
                    all_scenes.extend(scenes)

                if not self._check_pause_and_cancel():
                    break

            if not self._check_pause_and_cancel():
                break

        # Final progress update
        if self._check_pause_and_cancel():
            self.progress.emit(
                total_shows,
                total_shows,
                100.0,
                f"Discovery complete: {len(all_scenes)} scenes found",
                "",
            )

        return all_scenes
