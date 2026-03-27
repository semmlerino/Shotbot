"""Worker for finding latest Maya and 3DE scene files asynchronously."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from typing_extensions import override

from discovery.latest_finders import MayaLatestFinder
from workers.thread_safe_worker import ThreadSafeWorker


if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from threede import ThreeDELatestFinder


class LatestFileFinderWorker(ThreadSafeWorker):
    """Background worker for finding latest Maya and 3DE scene files.

    This worker wraps MayaLatestFinder and ThreeDELatestFinder to perform
    filesystem scans in a background thread, preventing UI freezes on slow
    network storage.

    Signals:
        search_complete: Emitted when all searches finish (success: bool)

    Example:
        worker = LatestFileFinderWorker(
            workspace_path="/shows/myshow/shots/sq010/sh0010",
            shot_name="myshow_sq010_sh0010",
            find_maya=True,
            find_threede=False,
        )
        worker.search_complete.connect(self._on_search_complete)
        worker.start()

    """

    # Result signals - emitted from background thread, received via queued connection
    search_complete = Signal(bool)  # type: ignore[assignment]  # success

    def __init__(
        self,
        workspace_path: str,
        shot_name: str | None,
        find_maya: bool = False,
        find_threede: bool = False,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the latest file finder worker.

        Args:
            workspace_path: Full path to the shot workspace
            shot_name: Optional shot name for logging
            find_maya: Whether to search for Maya scenes
            find_threede: Whether to search for 3DE scenes
            parent: Optional parent QObject

        """
        super().__init__(parent)
        self._workspace_path: str = workspace_path
        self._shot_name: str | None = shot_name
        self._find_maya: bool = find_maya
        self._find_threede: bool = find_threede

        # Results stored for retrieval
        self._maya_result: Path | None = None
        self._threede_result: Path | None = None

        # Finders (will be created in worker thread)
        self._maya_finder: MayaLatestFinder | None = None
        self._threede_finder: ThreeDELatestFinder | None = None

    @property
    def maya_result(self) -> Path | None:
        """Get the Maya search result after completion."""
        return self._maya_result

    @property
    def threede_result(self) -> Path | None:
        """Get the 3DE search result after completion."""
        return self._threede_result

    @override
    def do_work(self) -> None:
        """Execute the file search in background thread.

        Searches for Maya and/or 3DE scene files based on configuration.
        Passes should_stop to finders for cancellation during filesystem operations.
        """
        from threede import ThreeDELatestFinder

        success = True

        try:
            # Search for 3DE scene if requested
            if self._find_threede and not self.should_stop():
                self.logger.debug(
                    f"Searching for latest 3DE scene in {self._workspace_path}"
                )
                self._threede_finder = ThreeDELatestFinder()
                # Pass should_stop as cancel_flag for responsive cancellation
                self._threede_result = self._threede_finder.find_latest_scene(
                    self._workspace_path,
                    self._shot_name,
                    cancel_flag=self.should_stop,
                )

                if self._threede_result:
                    self.logger.info(f"Found 3DE scene: {self._threede_result.name}")
                else:
                    self.logger.debug("No 3DE scene found")

            # Check for cancellation between searches
            if self.should_stop():
                self.logger.debug("Search cancelled")
                success = False
                self.search_complete.emit(success)
                return

            # Search for Maya scene if requested
            if self._find_maya and not self.should_stop():
                self.logger.debug(
                    f"Searching for latest Maya scene in {self._workspace_path}"
                )
                self._maya_finder = MayaLatestFinder()
                # Pass should_stop as cancel_flag for responsive cancellation
                self._maya_result = self._maya_finder.find_latest_scene(
                    self._workspace_path,
                    self._shot_name,
                    cancel_flag=self.should_stop,
                )

                if self._maya_result:
                    self.logger.info(f"Found Maya scene: {self._maya_result.name}")
                else:
                    self.logger.debug("No Maya scene found")

        except Exception:
            self.logger.exception("Error during file search")
            success = False

        # Signal completion
        self.search_complete.emit(success)
