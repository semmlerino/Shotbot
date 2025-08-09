"""QProcess-based implementation of ShotModel for non-blocking shot refreshing.

This module provides a QProcess-based version of ShotModel that performs
shot refresh operations in a non-blocking manner using QThread workers.
It maintains full backward compatibility with the existing API while
providing improved performance and responsiveness.
"""

import logging
import re
from typing import TYPE_CHECKING, List, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

if TYPE_CHECKING:
    from cache_manager import CacheManager

from config import Config
from qprocess_manager import ProcessState, QProcessManager
from shot_model import RefreshResult, Shot
from utils import ValidationUtils

logger = logging.getLogger(__name__)


class ShotRefreshWorker(QThread):
    """Worker thread for refreshing shots using QProcess.

    Executes the ws -sg command in a separate thread and parses the output,
    emitting signals for progress and completion.
    """

    # Signals
    refresh_started = Signal()
    refresh_progress = Signal(str)  # status message
    refresh_completed = Signal(bool, bool, list)  # success, has_changes, shots
    refresh_error = Signal(str)  # error message

    def __init__(
        self,
        process_manager: QProcessManager,
        current_shots: List[Shot],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.process_manager = process_manager
        self.current_shots = current_shots
        self._parse_pattern = re.compile(
            r"workspace\s+(/shows/(\w+)/shots/(\w+)/(\w+))"
        )
        self._output_lines: List[str] = []
        self._process_id: Optional[str] = None

    def run(self):
        """Execute the refresh operation."""
        try:
            self.refresh_started.emit()
            self.refresh_progress.emit("Starting workspace command...")

            # Execute ws -sg command using QProcess
            self._process_id = self.process_manager.execute(
                command="ws -sg",
                interactive_bash=True,  # Required for ws function
                capture_output=True,
                timeout_ms=Config.WS_COMMAND_TIMEOUT_SECONDS * 1000,
                process_id=f"ws_sg_{int(self.msleep(0))}",  # Unique ID
            )

            if not self._process_id:
                self.refresh_error.emit("Failed to start ws -sg command")
                self.refresh_completed.emit(False, False, [])
                return

            self.refresh_progress.emit("Executing workspace command...")

            # Wait for process to complete
            process_info = self.process_manager.wait_for_process(
                self._process_id, timeout_ms=Config.WS_COMMAND_TIMEOUT_SECONDS * 1000
            )

            if not process_info:
                self.refresh_error.emit("Timeout waiting for ws -sg command")
                self.refresh_completed.emit(False, False, [])
                return

            # Check process result
            if process_info.state == ProcessState.FAILED:
                error_msg = (
                    f"ws -sg command failed: {process_info.error or 'Unknown error'}"
                )
                if process_info.error_buffer:
                    error_msg += f"\nStderr: {' '.join(process_info.error_buffer[:5])}"
                self.refresh_error.emit(error_msg)
                self.refresh_completed.emit(False, False, [])
                return

            if process_info.exit_code != 0:
                error_msg = f"ws -sg command exited with code {process_info.exit_code}"
                self.refresh_error.emit(error_msg)
                self.refresh_completed.emit(False, False, [])
                return

            self.refresh_progress.emit("Parsing workspace output...")

            # Parse the output
            output = "\n".join(process_info.output_buffer)
            new_shots = self._parse_ws_output(output)

            # Check for changes
            old_shot_data = {
                (shot.full_name, shot.workspace_path) for shot in self.current_shots
            }
            new_shot_data = {
                (shot.full_name, shot.workspace_path) for shot in new_shots
            }
            has_changes = old_shot_data != new_shot_data

            status_msg = f"Found {len(new_shots)} shots"
            if has_changes:
                status_msg += " (changes detected)"
            self.refresh_progress.emit(status_msg)

            # Emit completion
            self.refresh_completed.emit(True, has_changes, new_shots)

        except Exception as e:
            logger.exception(f"Error in shot refresh worker: {e}")
            self.refresh_error.emit(f"Unexpected error: {str(e)}")
            self.refresh_completed.emit(False, False, [])

    def _parse_ws_output(self, output: str) -> List[Shot]:
        """Parse ws -sg output to extract shots.

        Args:
            output: Raw output from ws -sg command

        Returns:
            List of Shot objects parsed from the output
        """
        if not isinstance(output, str):
            logger.error(f"Expected string output, got {type(output)}")
            return []

        shots: List[Shot] = []
        lines = output.strip().split("\n")

        if not output.strip():
            logger.warning("ws -sg returned empty output")
            return shots

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            match = self._parse_pattern.search(line)
            if match:
                try:
                    workspace_path = match.group(1)
                    show = match.group(2)
                    sequence = match.group(3)
                    shot_name = match.group(4)

                    # Validate extracted components
                    if not ValidationUtils.validate_not_empty(
                        workspace_path,
                        show,
                        sequence,
                        shot_name,
                        names=["workspace_path", "show", "sequence", "shot_name"],
                    ):
                        logger.warning(
                            f"Line {line_num}: Missing required components in: {line}"
                        )
                        continue

                    # Extract shot number from full name
                    shot_parts = shot_name.split("_")
                    if len(shot_parts) >= 3:
                        shot = shot_parts[-1]
                    else:
                        shot = shot_name

                    shots.append(
                        Shot(
                            show=show,
                            sequence=sequence,
                            shot=shot,
                            workspace_path=workspace_path,
                        )
                    )
                except (IndexError, AttributeError) as e:
                    logger.warning(
                        f"Line {line_num}: Failed to parse shot data from: {line} ({e})"
                    )
                    continue
            else:
                logger.debug(f"Line {line_num}: No match for workspace pattern: {line}")

        logger.info(f"Parsed {len(shots)} shots from ws -sg output")
        return shots

    def stop(self):
        """Stop the refresh operation if running."""
        if self._process_id:
            self.process_manager.terminate_process(self._process_id)
        self.quit()
        self.wait()


class ShotModelQProcess(QObject):
    """QProcess-based shot model with non-blocking refresh.

    Drop-in replacement for ShotModel that uses QProcess for better
    integration with Qt's event loop and non-blocking operation.
    """

    # Signals
    shots_updated = Signal()
    refresh_started = Signal()
    refresh_progress = Signal(str)  # status message
    refresh_completed = Signal(bool, bool)  # success, has_changes
    refresh_error = Signal(str)  # error message

    def __init__(
        self,
        cache_manager: Optional["CacheManager"] = None,
        load_cache: bool = True,
        process_manager: Optional[QProcessManager] = None,
    ):
        super().__init__()

        from cache_manager import CacheManager  # Runtime import

        self.shots: List[Shot] = []
        self.cache_manager = cache_manager or CacheManager()
        self.process_manager = process_manager or QProcessManager()
        self._refresh_worker: Optional[ShotRefreshWorker] = None
        self._is_refreshing = False

        # Load cache if requested
        if load_cache:
            self._load_from_cache()

    def _load_from_cache(self) -> bool:
        """Load shots from cache if available."""
        cached_data = self.cache_manager.get_cached_shots()
        if cached_data:
            self.shots = [Shot.from_dict(shot_data) for shot_data in cached_data]
            return True
        return False

    def refresh_shots(self, blocking: bool = False) -> RefreshResult:
        """Fetch and parse shot list from ws -sg command.

        Args:
            blocking: If True, wait for refresh to complete (backward compatibility)
                     If False, perform non-blocking refresh (default)

        Returns:
            RefreshResult with success status and change indicator
            For non-blocking mode, returns immediately with current status
        """
        if self._is_refreshing:
            logger.warning("Refresh already in progress")
            return RefreshResult(success=False, has_changes=False)

        if blocking:
            # Synchronous mode for backward compatibility
            return self._refresh_shots_blocking()

        # Start non-blocking refresh
        self._start_refresh_worker()

        # Return immediately with pending status
        return RefreshResult(success=True, has_changes=False)

    def _refresh_shots_blocking(self) -> RefreshResult:
        """Blocking version of refresh_shots for backward compatibility."""
        # Create and configure worker
        worker = ShotRefreshWorker(self.process_manager, self.shots.copy(), parent=self)

        # Track completion
        result_data = {"success": False, "has_changes": False, "shots": []}

        def on_completed(success: bool, has_changes: bool, shots: List[Shot]):
            result_data["success"] = success
            result_data["has_changes"] = has_changes
            result_data["shots"] = shots

        worker.refresh_completed.connect(on_completed)

        # Run synchronously
        worker.run()  # Direct call, not threaded

        # Update shots if successful
        if result_data["success"] and result_data["has_changes"]:
            self.shots = result_data["shots"]
            self._cache_shots()
            self.shots_updated.emit()

        return RefreshResult(
            success=result_data["success"], has_changes=result_data["has_changes"]
        )

    def _start_refresh_worker(self):
        """Start the refresh worker thread."""
        if self._refresh_worker and self._refresh_worker.isRunning():
            logger.warning("Previous refresh worker still running")
            return

        self._is_refreshing = True

        # Create worker
        self._refresh_worker = ShotRefreshWorker(
            self.process_manager, self.shots.copy(), parent=self
        )

        # Connect signals
        self._refresh_worker.refresh_started.connect(self._on_refresh_started)
        self._refresh_worker.refresh_progress.connect(self._on_refresh_progress)
        self._refresh_worker.refresh_completed.connect(self._on_refresh_completed)
        self._refresh_worker.refresh_error.connect(self._on_refresh_error)

        # Start worker thread
        self._refresh_worker.start()

    @Slot()
    def _on_refresh_started(self):
        """Handle refresh started."""
        self.refresh_started.emit()
        logger.debug("Shot refresh started")

    @Slot(str)
    def _on_refresh_progress(self, message: str):
        """Handle refresh progress update."""
        self.refresh_progress.emit(message)
        logger.debug(f"Shot refresh progress: {message}")

    @Slot(bool, bool, list)
    def _on_refresh_completed(
        self, success: bool, has_changes: bool, new_shots: List[Shot]
    ):
        """Handle refresh completion."""
        self._is_refreshing = False

        if success and has_changes:
            self.shots = new_shots
            self._cache_shots()
            self.shots_updated.emit()
            logger.info(f"Shot list updated: {len(new_shots)} shots found")
        elif success:
            logger.info("Shot list unchanged")

        self.refresh_completed.emit(success, has_changes)

        # Clean up worker
        if self._refresh_worker:
            self._refresh_worker.deleteLater()
            self._refresh_worker = None

    @Slot(str)
    def _on_refresh_error(self, error: str):
        """Handle refresh error."""
        self._is_refreshing = False
        self.refresh_error.emit(error)
        logger.error(f"Shot refresh error: {error}")

        # Clean up worker
        if self._refresh_worker:
            self._refresh_worker.deleteLater()
            self._refresh_worker = None

    def _cache_shots(self):
        """Cache the current shots."""
        if self.shots:
            try:
                self.cache_manager.cache_shots(self.shots)  # type: ignore[arg-type]
            except (OSError, IOError) as e:
                logger.warning(f"Failed to cache shots: {e}")

    def refresh_shots_async(self) -> None:
        """Start an asynchronous shot refresh.

        This method starts the refresh in the background and returns immediately.
        Connect to the refresh_completed signal to be notified when done.
        """
        self.refresh_shots(blocking=False)

    def is_refreshing(self) -> bool:
        """Check if a refresh is currently in progress."""
        return self._is_refreshing

    def cancel_refresh(self):
        """Cancel an ongoing refresh operation."""
        if self._refresh_worker and self._refresh_worker.isRunning():
            self._refresh_worker.stop()
            self._is_refreshing = False
            logger.info("Shot refresh cancelled")

    def get_shot_by_index(self, index: int) -> Optional[Shot]:
        """Get shot by index."""
        if 0 <= index < len(self.shots):
            return self.shots[index]
        return None

    def find_shot_by_name(self, full_name: str) -> Optional[Shot]:
        """Find shot by full name."""
        for shot in self.shots:
            if shot.full_name == full_name:
                return shot
        return None

    def get_shots(self) -> List[Shot]:
        """Get list of all shots."""
        return self.shots.copy()

    def cleanup(self):
        """Clean up resources."""
        self.cancel_refresh()
        if self.process_manager:
            self.process_manager.shutdown()
