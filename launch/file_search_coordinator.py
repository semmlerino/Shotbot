"""Async file search coordinator for the launch system.

Manages the lifecycle of background file searches (LatestFileFinderWorker)
that run before DCC application launches. Responsible for:
- Starting the background worker
- Storing pending launch state while the search runs
- Caching results on completion
- Emitting signals to drive UI state (spinner) and launch resumption
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal

from discovery.latest_file_finder_worker import LatestFileFinderWorker
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from cache.latest_file_cache import LatestFileCache
    from launch.command_launcher import PendingLaunch
    from type_definitions import Shot


class FileSearchCoordinator(LoggingMixin, QObject):
    """Coordinates async file searches for latest DCC scene files.

    Owns the LatestFileFinderWorker lifecycle and the pending launch state that
    must be preserved while the background thread runs.  Emits signals to
    update the UI (launch_pending / launch_ready) and to hand results back to
    CommandLauncher (search_result_ready).

    Signals:
        launch_pending: Emitted when an async search starts (show spinner).
        launch_ready: Emitted when the search ends, success or failure
            (hide spinner).
        search_result_ready: Emitted on successful search completion.
            Carries (pending_launch, maya_result, threede_result) for the
            caller to resume the launch flow.

    """

    launch_pending: Signal = Signal()
    launch_ready: Signal = Signal()
    # Emitted only on success: (pending_launch, maya_result, threede_result)
    # Types are object because PySide6 Signal doesn't accept Path | None directly.
    search_result_ready: Signal = Signal(object, object, object)

    def __init__(
        self,
        cache_manager: LatestFileCache,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the coordinator.

        Args:
            cache_manager: Cache used to store file-search results so
                subsequent launches for the same shot skip the worker.
            parent: Optional parent QObject for Qt ownership.

        """
        super().__init__(parent)
        self._cache_manager: LatestFileCache = cache_manager
        self._pending_worker: LatestFileFinderWorker | None = None
        self._pending_launch: PendingLaunch | None = None
        # Workspace stored alongside pending_launch for result caching.
        self._pending_workspace: str | None = None

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @property
    def is_search_pending(self) -> bool:
        """Return True if a background file search is in progress."""
        return self._pending_worker is not None

    def start_async_file_search(
        self,
        pending_launch: PendingLaunch,
        shot: Shot,
    ) -> None:
        """Start a background file search and store the pending launch state.

        After this returns the caller should return control to Qt; the result
        arrives via ``search_result_ready`` (on success) or the pending state
        is cleared (on failure/cancellation).

        Args:
            pending_launch: The full launch context to resume after the search.
                Stores app_name, LaunchContext flags, and the base command.
            shot: The current shot whose workspace will be scanned.

        """
        self._pending_launch = pending_launch
        self._pending_workspace = shot.workspace_path

        find_threede = (
            pending_launch.app_name == "3de"
            and pending_launch.context.open_latest_threede
        )
        find_maya = (
            pending_launch.app_name == "maya"
            and pending_launch.context.open_latest_maya
        )

        self._pending_worker = LatestFileFinderWorker(
            workspace_path=shot.workspace_path,
            shot_name=shot.full_name,
            find_maya=find_maya,
            find_threede=find_threede,
            parent=self,
        )

        _ = self._pending_worker.search_complete.connect(
            self._on_async_search_complete,
            Qt.ConnectionType.QueuedConnection,
        )

        self.launch_pending.emit()
        self._pending_worker.start()
        self.logger.debug(
            "Started async file search for %s", pending_launch.app_name
        )

    def cancel_pending_search(self) -> None:
        """Cancel any in-progress background file search."""
        if self._pending_worker is not None:
            _ = self._pending_worker.request_stop()
            _ = self._pending_worker.safe_stop(timeout_ms=1000)
            self._pending_worker = None
            self._clear_pending_state()
            self.launch_ready.emit()
            self.logger.debug("Cancelled pending file search")

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _clear_pending_state(self) -> None:
        """Clear the stored pending-launch record and workspace."""
        self._pending_launch = None
        self._pending_workspace = None

    def _on_async_search_complete(self, success: bool) -> None:
        """Handle LatestFileFinderWorker.search_complete (Qt slot, QueuedConnection).

        Caches results, cleans up the worker, emits launch_ready to hide the
        UI spinner, then either emits search_result_ready (on success) or
        clears pending state (on failure / cancellation).

        Args:
            success: Whether the worker finished without error.

        """
        if self._pending_worker is None:
            self.logger.warning("Async search complete but no pending worker")
            return

        # Collect results before cleanup
        maya_result: Path | None = self._pending_worker.maya_result
        threede_result: Path | None = self._pending_worker.threede_result

        # Cache results (even None, to avoid re-searching this session)
        if self._pending_launch is not None and self._pending_workspace is not None:
            self._store_results_in_cache(
                self._pending_workspace,
                self._pending_launch,
                maya_result,
                threede_result,
            )

        # Destroy the worker
        self._pending_worker.deleteLater()
        self._pending_worker = None

        # Always hide the spinner
        self.launch_ready.emit()

        if success:
            pending = self._pending_launch
            self._clear_pending_state()
            self.search_result_ready.emit(pending, maya_result, threede_result)
        else:
            self.logger.warning("Async file search failed or was cancelled")
            self._clear_pending_state()

    def _store_results_in_cache(
        self,
        workspace: str,
        pending_launch: PendingLaunch,
        maya_result: Path | None,
        threede_result: Path | None,
    ) -> None:
        """Write search results into the latest-file cache.

        The cache stores results (including None) so that a second launch for
        the same shot skips the background worker entirely.

        Args:
            workspace: Shot workspace path (cache key).
            pending_launch: Used to determine which file types were searched.
            maya_result: Latest Maya scene found, or None.
            threede_result: Latest 3DE scene found, or None.

        """
        if pending_launch.context.open_latest_maya:
            self._cache_manager.cache_latest_file(workspace, "maya", maya_result)
        if pending_launch.context.open_latest_threede:
            self._cache_manager.cache_latest_file(workspace, "threede", threede_result)
