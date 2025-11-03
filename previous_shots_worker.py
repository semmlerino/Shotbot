"""Background worker for scanning previous/approved shots."""

from __future__ import annotations

# Standard library imports
import time
from pathlib import Path

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from previous_shots_finder import ParallelShotsFinder
from shot_model import Shot
from thread_safe_worker import ThreadSafeWorker


class PreviousShotsWorker(ThreadSafeWorker):
    """Background worker thread for finding approved shots.

    This worker runs in a separate thread to avoid blocking the UI
    while scanning the filesystem for user shots.

    Inherits from ThreadSafeWorker for proper lifecycle management
    and thread safety guarantees.
    """

    # Signals
    started = Signal()  # Emitted when scan starts
    shot_found = Signal(dict)  # Emitted for each shot found
    scan_progress = Signal(int, int, str)  # current, total, current_operation
    scan_finished = Signal(list)  # List of all shots found
    error_occurred = Signal(str)  # Error message

    def __init__(
        self,
        active_shots: list[Shot],
        username: str | None = None,
        shows_root: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the worker thread.

        Args:
            active_shots: List of currently active shots to filter out.
            username: Username to search for (uses current if None).
            shows_root: Root directory to search (defaults to /shows).
            parent: parent QObject.
        """
        super().__init__(parent)

        self._active_shots = active_shots
        self._shows_root = shows_root if shows_root is not None else Path("/shows")

        # Use new ParallelShotsFinder for improved performance
        self._finder = ParallelShotsFinder(username)  # Uses config defaults
        self._finder.set_progress_callback(self._on_finder_progress)

        # No need for _should_stop, use base class should_stop() method
        self._found_shots: list[Shot] = []

        self.logger.info(
            f"PreviousShotsWorker initialized for user: {self._finder.username}"
        )

    def _on_finder_progress(self, current: int, total: int, message: str) -> None:
        """Handle progress updates from the parallel finder.

        Args:
            current: Current progress value
            total: Total progress value
            message: Progress message
        """
        # Forward progress to our own signal
        self.scan_progress.emit(current, total, message)

    def stop(self) -> None:
        """Request the worker to stop safely."""
        self.request_stop()  # Use base class method for proper state transition
        if hasattr(self._finder, "request_stop"):
            self._finder.request_stop()  # Also stop the parallel finder
        self.logger.debug("Stop requested for PreviousShotsWorker")

    def do_work(self) -> None:
        """Perform the background scanning process.

        This method is called by the base class after proper state transitions.
        The base class handles state management, so we don't need to manage it here.
        """
        self.logger.info("Starting previous shots scan")
        start_time = time.time()

        # Emit started signal - base class already emits worker_started
        self.started.emit()

        try:
            # Emit initial progress
            self.scan_progress.emit(0, 100, "Initializing scan...")

            # Track whether shot_found signals have already been emitted
            signals_already_emitted = False

            # Use new targeted search for maximum performance
            # This searches only in shows where user has active shots
            if hasattr(self._finder, "find_approved_shots_targeted"):
                self.logger.info("Using targeted search approach")
                approved_shots = self._finder.find_approved_shots_targeted(
                    self._active_shots, self._shows_root
                )

                # Emit individual shots as found for UI updates
                for shot in approved_shots:
                    if self.should_stop():
                        break
                    self.shot_found.emit(shot.to_dict())

                signals_already_emitted = True  # Signals emitted in targeted search

            else:
                # Fallback to original two-step process
                self.logger.info("Using fallback two-step approach")

                # Use parallel finder with incremental loading
                all_user_shots: list[Shot] = []

                # Collect shots incrementally from the generator
                if hasattr(self._finder, "find_user_shots_parallel"):
                    # Use generator for incremental results
                    for shot in self._finder.find_user_shots_parallel(self._shows_root):
                        if self.should_stop():
                            break
                        all_user_shots.append(shot)
                        # Emit individual shot as it's found
                        self.shot_found.emit(shot.to_dict())

                    signals_already_emitted = True  # Signals emitted in parallel search

                else:
                    # Fallback to regular method - no signals emitted yet
                    self.scan_progress.emit(10, 100, "Scanning filesystem...")
                    all_user_shots = self._finder.find_user_shots(self._shows_root)
                    signals_already_emitted = False  # No signals emitted yet

                if self.should_stop():
                    self.logger.info("Scan stopped by user request")
                    return

                self.scan_progress.emit(50, 100, "Filtering approved shots...")
                # Filter to get only approved shots
                approved_shots = self._finder.filter_approved_shots(
                    all_user_shots, self._active_shots
                )

            # Convert to dictionaries for signal emission
            shot_dicts: list[dict[str, str]] = []
            total_shots = len(approved_shots)

            # Only emit shot_found signals if they haven't been emitted already
            # This fixes the double emission bug
            if not signals_already_emitted:
                self.logger.debug("Emitting shot_found signals for individual shots")
                for i, shot in enumerate(approved_shots):
                    if self.should_stop():
                        break

                    # Emit progress for processing each shot
                    progress = 50 + int((i / total_shots) * 40)  # 50-90% range
                    self.scan_progress.emit(
                        progress, 100, f"Processing shot {i + 1} of {total_shots}"
                    )

                    shot_dict = {
                        "show": shot.show,
                        "sequence": shot.sequence,
                        "shot": shot.shot,
                        "workspace_path": shot.workspace_path,
                    }
                    shot_dicts.append(shot_dict)
                    self.shot_found.emit(shot_dict)
            else:
                self.logger.debug(
                    "Skipping shot_found emission - signals already emitted"
                )
                # Still need to build shot_dicts for final emission
                for shot in approved_shots:
                    shot_dict = {
                        "show": shot.show,
                        "sequence": shot.sequence,
                        "shot": shot.shot,
                        "workspace_path": shot.workspace_path,
                    }
                    shot_dicts.append(shot_dict)

            # Final progress update
            self.scan_progress.emit(100, 100, "Scan completed")

            elapsed = time.time() - start_time
            self.logger.info(
                (f"Previous shots scan completed in {elapsed:.2f}s. "
                f"Found {len(approved_shots)} approved shots.")
            )

            # Emit final results
            self.scan_finished.emit(shot_dicts)

            # Base class handles state transition and worker_stopped signal

        except Exception as e:
            error_msg = f"Error during previous shots scan: {e}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            # Re-raise to let base class handle error state
            raise

    def _scan_for_user_shots(self) -> list[Shot]:
        """DEPRECATED: Use self._finder.find_user_shots() instead.

        This method duplicates functionality already in PreviousShotsFinder.
        Kept for backwards compatibility but should not be used.

        Returns:
            List of Shot objects where user has work.
        """
        shots: list[Shot] = []

        try:
            # For progress tracking, we'll estimate based on shows
            if self._shows_root.exists():
                show_dirs = [
                    d
                    for d in self._shows_root.iterdir()
                    if d.is_dir() and not d.name.startswith(".")
                ]
                total_shows = len(show_dirs)

                self.logger.debug(f"Scanning {total_shows} shows for user work")

                for index, show_dir in enumerate(show_dirs):
                    if self.should_stop():
                        break

                    # Emit progress
                    self.scan_progress.emit(index + 1, total_shows)

                    # Find shots in this show
                    show_shots = self._find_shots_in_show(show_dir)
                    shots.extend(show_shots)

                    self.logger.debug(
                        f"Found {len(show_shots)} user shots in {show_dir.name}"
                    )

        except Exception as e:
            self.logger.error(f"Error scanning for user shots: {e}")

        return shots

    def _find_shots_in_show(self, show_dir: Path) -> list[Shot]:
        """Find user shots within a specific show.

        Args:
            show_dir: Show directory to search.

        Returns:
            List of Shot objects with user work.
        """
        shots: list[Shot] = []

        try:
            shots_dir = show_dir / "shots"
            if not shots_dir.exists():
                return shots

            # Look for user directories in shot paths

            for sequence_dir in shots_dir.iterdir():
                if self.should_stop():
                    break

                if not sequence_dir.is_dir():
                    continue

                for shot_dir in sequence_dir.iterdir():
                    if self.should_stop():
                        break

                    if not shot_dir.is_dir():
                        continue

                    # Check if user has work in this shot
                    user_dir = shot_dir / "user" / self._finder.username
                    if user_dir.exists():
                        shot = Shot(
                            show=show_dir.name,
                            sequence=sequence_dir.name,
                            shot=shot_dir.name,
                            workspace_path=str(shot_dir),
                        )
                        shots.append(shot)

                        # Emit individual shot found
                        shot_dict = {
                            "show": shot.show,
                            "sequence": shot.sequence,
                            "shot": shot.shot,
                            "workspace_path": shot.workspace_path,
                        }
                        self.shot_found.emit(shot_dict)

        except Exception as e:
            self.logger.error(f"Error scanning show {show_dir}: {e}")

        return shots

    def get_found_shots(self) -> list[Shot]:
        """Get the list of shots found so far.

        Returns:
            List of Shot objects found during scanning.
        """
        return self._found_shots.copy()
