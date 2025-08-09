"""QThread-based worker for background 3DE scene discovery."""

import logging
import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional, Set, Tuple

from PySide6.QtCore import QMutex, QThread, QWaitCondition, Signal

from config import Config
from shot_model import Shot
from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDEScene
from utils import ValidationUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class ProgressCalculator:
    """Helper class for calculating progress and ETA during file scanning."""

    def __init__(self, smoothing_window: Optional[int] = None):
        """Initialize progress calculator.

        Args:
            smoothing_window: Number of samples for ETA smoothing
        """
        self.smoothing_window = smoothing_window or Config.PROGRESS_ETA_SMOOTHING_WINDOW
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.processing_times: Deque[float] = deque(maxlen=self.smoothing_window)
        self.files_processed = 0
        self.total_files_estimate = 0

    def update(
        self, files_processed: int, total_estimate: Optional[int] = None
    ) -> Tuple[float, str]:
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
                100.0, (files_processed / self.total_files_estimate) * 100
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
        if not Config.PROGRESS_ENABLE_ETA:
            return ""

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
        elif eta_seconds < 3600:
            minutes = int(eta_seconds / 60)
            return f"~{minutes}m remaining"
        else:
            hours = int(eta_seconds / 3600)
            minutes = int((eta_seconds % 3600) / 60)
            return f"~{hours}h {minutes}m remaining"


class ThreeDESceneWorker(QThread):
    """Enhanced QThread worker for progressive 3DE scene discovery.

    This worker supports:
    - Progressive/batched file scanning for responsive UI
    - Cancellation and pause/resume functionality
    - Detailed progress reporting with ETA calculation
    - Memory-aware processing with configurable limits
    """

    # Enhanced signals
    started = Signal()  # Emitted when discovery starts
    batch_ready = Signal(list)  # Emitted with each batch of scenes
    progress = Signal(
        int, int, float, str, str
    )  # (current, total, percentage, description, eta)
    scan_progress = Signal(int, int, str)  # Emitted during individual shot scanning
    finished = Signal(list)  # Emitted with complete list of scenes
    error = Signal(str)  # Emitted when an error occurs
    paused = Signal()  # Emitted when worker is paused
    resumed = Signal()  # Emitted when worker resumes

    def __init__(
        self,
        shots: List[Shot],
        excluded_users: Optional[Set[str]] = None,
        batch_size: Optional[int] = None,
        enable_progressive: bool = True,
    ):
        """Initialize the enhanced worker with shots to search.

        Args:
            shots: List of shots to use for determining shows to search
            excluded_users: Set of usernames to exclude from search
            batch_size: Number of scenes per batch for progressive scanning
            enable_progressive: Enable progressive scanning (vs. traditional all-at-once)
        """
        super().__init__()
        self.shots = shots
        self.excluded_users = excluded_users or ValidationUtils.get_excluded_users()
        self.batch_size = batch_size or Config.PROGRESSIVE_SCAN_BATCH_SIZE
        self.enable_progressive = enable_progressive and Config.PROGRESSIVE_SCAN_ENABLED

        # Control flags
        self._should_stop = False
        self._is_paused = False

        # Thread synchronization
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()

        # Progress tracking
        self._progress_calculator = ProgressCalculator()
        self._last_progress_time = 0
        self._all_scenes: List[ThreeDEScene] = []
        self._files_processed = 0

        # Set thread priority
        self.setPriority(Config.WORKER_THREAD_PRIORITY)

    def stop(self):
        """Request the worker to stop processing."""
        logger.debug("Stop requested for 3DE scene worker")
        self._should_stop = True
        # Wake up paused thread so it can exit
        self.resume()

    def pause(self):
        """Request the worker to pause processing."""
        logger.debug("Pause requested for 3DE scene worker")
        self._pause_mutex.lock()
        try:
            self._is_paused = True
            self.paused.emit()
        finally:
            self._pause_mutex.unlock()

    def resume(self):
        """Resume processing if paused."""
        logger.debug("Resume requested for 3DE scene worker")
        self._pause_mutex.lock()
        try:
            if self._is_paused:
                self._is_paused = False
                self._pause_condition.wakeAll()
                self.resumed.emit()
        finally:
            self._pause_mutex.unlock()

    def is_paused(self) -> bool:
        """Check if worker is currently paused."""
        self._pause_mutex.lock()
        try:
            return self._is_paused
        finally:
            self._pause_mutex.unlock()

    def _check_pause_and_cancel(self) -> bool:
        """Check for pause/cancel requests and handle them.

        Returns:
            True if should continue, False if should exit
        """
        # Check for cancellation
        if self._should_stop:
            logger.debug("Worker received stop signal")
            return False

        # Check for pause
        self._pause_mutex.lock()
        try:
            while self._is_paused and not self._should_stop:
                logger.debug("Worker paused, waiting for resume...")
                self._pause_condition.wait(
                    self._pause_mutex, Config.WORKER_PAUSE_CHECK_INTERVAL_MS
                )
        finally:
            self._pause_mutex.unlock()

        # Check cancellation again after pause
        return not self._should_stop

    def run(self):
        """Enhanced main worker thread execution with progressive scanning."""
        try:
            logger.info("Starting enhanced 3DE scene discovery")
            self.started.emit()

            if not self.shots:
                logger.warning("No shots provided for 3DE scene discovery")
                self.finished.emit([])
                return

            # Check for initial cancellation
            if not self._check_pause_and_cancel():
                logger.info("3DE scene discovery cancelled before starting")
                self.finished.emit([])
                return

            # Choose discovery method based on configuration
            if self.enable_progressive:
                scenes = self._discover_scenes_progressive()
            else:
                scenes = self._discover_scenes_traditional()

            # Final cancellation check
            if not self._check_pause_and_cancel():
                logger.info("3DE scene discovery cancelled during processing")
                self.finished.emit(self._all_scenes)  # Return partial results
                return

            logger.info(
                f"Enhanced 3DE scene discovery completed: {len(scenes)} scenes found"
            )
            self.finished.emit(scenes)

        except Exception as e:
            logger.error(f"Error in enhanced 3DE scene discovery worker: {e}")
            self.error.emit(str(e))

    def _discover_scenes_progressive(self) -> List[ThreeDEScene]:
        """Progressive scene discovery with batch processing and detailed progress.

        Returns:
            List of all discovered ThreeDEScene objects
        """
        logger.info("Starting progressive 3DE scene discovery")

        # Convert shots to the format expected by the finder
        shot_tuples = []
        for shot in self.shots:
            shot_tuples.append(
                (shot.workspace_path, shot.show, shot.sequence, shot.shot)
            )

        # Get size estimation for progress calculation
        try:
            estimated_users, estimated_files = ThreeDESceneFinder.estimate_scan_size(
                shot_tuples, self.excluded_users
            )
            logger.debug(
                f"Scan estimate: {estimated_users} users, ~{estimated_files} files"
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

        except Exception as e:
            logger.warning(f"Could not estimate scan size: {e}")
            estimated_files = len(shot_tuples) * 10  # Fallback estimate

        # Use the progressive finder generator
        try:
            for (
                scene_batch,
                current_shot,
                total_shots,
                status_msg,
            ) in ThreeDESceneFinder.find_all_scenes_progressive(
                shot_tuples, self.excluded_users, self.batch_size
            ):
                # Check for pause/cancel between batches
                if not self._check_pause_and_cancel():
                    break

                # Add batch to accumulated results
                if scene_batch:
                    self._all_scenes.extend(scene_batch)
                    self.batch_ready.emit(scene_batch)

                    logger.debug(f"Processed batch of {len(scene_batch)} scenes")

                # Update progress tracking
                self._files_processed += len(scene_batch)

                # Throttle progress updates
                current_time = time.time()
                if (current_time - self._last_progress_time) >= (
                    Config.PROGRESS_UPDATE_INTERVAL_MS / 1000.0
                ):
                    progress_pct, eta_str = self._progress_calculator.update(
                        self._files_processed, estimated_files
                    )

                    detailed_status = (
                        f"{status_msg} ({len(self._all_scenes)} scenes found)"
                    )

                    self.progress.emit(
                        current_shot,
                        total_shots,
                        progress_pct,
                        detailed_status,
                        eta_str,
                    )

                    self._last_progress_time = current_time

                # Emit scan progress for fine-grained updates
                self.scan_progress.emit(current_shot, total_shots, status_msg)

        except Exception as e:
            logger.error(f"Error in progressive discovery: {e}")
            raise

        return self._all_scenes

    def _discover_scenes_traditional(self) -> List[ThreeDEScene]:
        """Traditional scene discovery method for backward compatibility.

        Returns:
            List of discovered ThreeDEScene objects
        """
        logger.info("Using traditional 3DE scene discovery method")

        all_scenes: List[ThreeDEScene] = []

        # Extract unique shows and show roots
        shows_to_search: Set[str] = set()
        show_roots: Set[str] = set()

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
                    current_show, total_shows, 0.0, f"Discovering shots in {show}", ""
                )

                # Discover all shots in this show
                all_shots = ThreeDESceneFinder.discover_all_shots_in_show(
                    show_root, show
                )

                if not all_shots:
                    logger.warning(f"No shots discovered in {show}")
                    continue

                self.progress.emit(
                    current_show,
                    total_shows,
                    0.0,
                    f"Searching {len(all_shots)} shots in {show}",
                    "",
                )

                # Search each discovered shot with periodic progress updates
                shot_count = 0
                for workspace_path, show_name, sequence, shot in all_shots:
                    if not self._check_pause_and_cancel():
                        break

                    shot_count += 1

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

                    scenes = ThreeDESceneFinder.find_scenes_for_shot(
                        workspace_path, show_name, sequence, shot, self.excluded_users
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
