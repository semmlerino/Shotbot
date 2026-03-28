"""Background worker for scanning previous/approved shots."""

from __future__ import annotations

# Standard library imports
import time
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QObject, Signal
from typing_extensions import override

# Local application imports
from previous_shots.finder import ParallelShotsFinder
from workers.thread_safe_worker import ThreadSafeWorker


if TYPE_CHECKING:
    from type_definitions import Shot


@final
class PreviousShotsWorker(ThreadSafeWorker):
    """Background worker thread for finding approved shots.

    This worker runs in a separate thread to avoid blocking the UI
    while scanning the filesystem for user shots.

    Inherits from ThreadSafeWorker for proper lifecycle management
    and thread safety guarantees.
    """

    # Signals
    scan_progress = Signal(int, int, str)  # current, total, current_operation
    scan_finished = Signal(object)  # List of all shots found

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
        _ = self.request_stop()  # Use base class method for proper state transition
        self._finder.request_stop()  # Also stop the parallel finder
        self.logger.debug("Stop requested for PreviousShotsWorker")

    @override
    def do_work(self) -> None:
        """Perform the background scanning process.

        This method is called by the base class after proper state transitions.
        The base class handles state management, so we don't need to manage it here.
        """
        self.logger.info("Starting previous shots scan")
        start_time = time.time()

        try:
            # Emit initial progress
            self.scan_progress.emit(0, 100, "Initializing scan...")

            # Use targeted search for maximum performance
            # This searches only in shows where user has active shots
            self.logger.info("Using targeted search approach")
            approved_shots = self._finder.find_approved_shots_targeted(
                self._active_shots, self._shows_root
            )

            # Convert to dictionaries for signal emission
            shot_dicts: list[dict[str, str]] = []

            # Build shot_dicts for final emission (signals already emitted in targeted search)
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
                f"Previous shots scan completed in {elapsed:.2f}s. "
                f"Found {len(approved_shots)} approved shots."
            )

            # Emit final results
            self.scan_finished.emit(shot_dicts)

            # Base class handles state transition and worker_stopped signal

        except Exception as e:
            self.logger.error(f"Error during previous shots scan: {e}")
            # Re-raise to let base class handle error state and emit worker_error
            raise

    def get_found_shots(self) -> list[Shot]:
        """Get the list of shots found so far.

        Returns:
            List of Shot objects found during scanning.

        """
        return self._found_shots.copy()
