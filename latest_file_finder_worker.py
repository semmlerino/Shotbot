"""Worker for finding latest Maya and 3DE scene files asynchronously."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import override

from PySide6.QtCore import Signal

from maya_latest_finder import MayaLatestFinder
from thread_safe_worker import ThreadSafeWorker
from threede_latest_finder import ThreeDELatestFinder


if TYPE_CHECKING:
    from PySide6.QtCore import QObject


class LatestFileFinderWorker(ThreadSafeWorker):
    """Background worker for finding latest Maya and 3DE scene files.

    This worker wraps MayaLatestFinder and ThreeDELatestFinder to perform
    filesystem scans in a background thread, preventing UI freezes on slow
    network storage.

    Signals:
        maya_found: Emitted when Maya scene search completes (Path | None)
        threede_found: Emitted when 3DE scene search completes (Path | None)
        search_complete: Emitted when all searches finish (success: bool)

    Example:
        worker = LatestFileFinderWorker(
            workspace_path="/shows/myshow/shots/sq010/sh0010",
            shot_name="myshow_sq010_sh0010",
            find_maya=True,
            find_threede=False,
        )
        worker.maya_found.connect(self._on_maya_found)
        worker.search_complete.connect(self._on_search_complete)
        worker.start()
    """

    # Result signals - emitted from background thread, received via queued connection
    maya_found = Signal(object)  # type: ignore[assignment]  # Path | None
    threede_found = Signal(object)  # type: ignore[assignment]  # Path | None
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
        Checks should_stop() between operations to support cancellation.
        """
        success = True

        try:
            # Search for 3DE scene if requested
            if self._find_threede and not self.should_stop():
                self.logger.debug(
                    f"Searching for latest 3DE scene in {self._workspace_path}"
                )
                self._threede_finder = ThreeDELatestFinder()
                self._threede_result = self._threede_finder.find_latest_threede_scene(
                    self._workspace_path,
                    self._shot_name,
                )
                self.threede_found.emit(self._threede_result)

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
                self._maya_result = self._maya_finder.find_latest_maya_scene(
                    self._workspace_path,
                    self._shot_name,
                )
                self.maya_found.emit(self._maya_result)

                if self._maya_result:
                    self.logger.info(f"Found Maya scene: {self._maya_result.name}")
                else:
                    self.logger.debug("No Maya scene found")

        except Exception:
            self.logger.exception("Error during file search")
            success = False

        # Signal completion
        self.search_complete.emit(success)
