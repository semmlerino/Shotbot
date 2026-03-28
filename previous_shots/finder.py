"""Finder for previous/approved shots that user has worked on."""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, final

from typing_extensions import Unpack, override

# Local application imports
from config import ThreadingConfig
from paths import resolve_shows_root
from shots.shot_finder_base import FindShotsKwargs, ShotFinderBase
from timeout_config import TimeoutConfig


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Generator

    # Local application imports
    from type_definitions import Shot


class PreviousShotsFinder(ShotFinderBase):
    """Finds shots that user has worked on but are no longer active.

    This class scans the filesystem for shots containing user work directories
    and filters out currently active shots to show only approved/completed ones.
    """

    def __init__(self, username: str | None = None) -> None:
        """Initialize the previous shots finder.

        Args:
            username: Username to search for. If None, uses current user.

        """
        # Initialize parent class (ShotFinderBase) which handles username sanitization
        super().__init__(username=username)

        logger.debug(f"PreviousShotsFinder initialized for user: {self.username}")

    def find_user_shots(self, shows_root: Path | None = None) -> list[Shot]:
        """Find all shots that contain user work directories.

        Args:
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None).

        Returns:
            List of Shot objects where user has work directories.

        """
        shots: list[Shot] = []

        root = resolve_shows_root(shows_root)

        if not root.exists():
            logger.warning(f"Shows root does not exist: {root}")
            return shots

        try:
            # Use Python's native Path.rglob() instead of subprocess find
            # This avoids subprocess isolation issues with pytest-xdist workers
            # where subprocess commands cannot see directories created by the worker
            pattern = f"**/user/{self.username}"
            logger.debug(f"Searching for pattern: {pattern} in {root}")

            # Find all matching user directories
            user_dirs = list(root.rglob(pattern))
            logger.debug(f"Found {len(user_dirs)} user directories")

            # Parse each found path to extract shot information
            for user_dir in user_dirs:
                # Convert to string for regex matching
                path_str = str(user_dir)
                logger.debug(f"Parsing path: {path_str}")

                shot = self._parse_shot_from_path(path_str)
                if shot:
                    logger.debug(f"Parsed shot: {shot}")
                    if shot not in shots:
                        shots.append(shot)
                    else:
                        logger.debug(f"Shot already in list: {shot}")
                else:
                    logger.debug(f"Failed to parse shot from path: {path_str}")

            logger.info(f"Found {len(shots)} shots with user work")

        except Exception:
            logger.exception("Error finding user shots")

        return shots

    def find_approved_shots(
        self, active_shots: list[Shot], shows_root: Path | None = None
    ) -> list[Shot]:
        """Find all approved shots for the user.

        This is a convenience method that combines finding user shots
        and filtering out active ones.

        Args:
            active_shots: Currently active shots from workspace.
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None).

        Returns:
            List of approved/completed shots.

        """
        root = resolve_shows_root(shows_root)
        all_user_shots = self.find_user_shots(root)
        return self.filter_approved_shots(all_user_shots, active_shots)

    @override
    def _get_unapproved_status(self, shot: Shot) -> str:
        """Get the status of a shot that is not approved.

        For previous shots, we consider them completed if they're not in active shots.

        Args:
            shot: Shot to get status for

        Returns:
            "completed"

        """
        return "completed"

    @override
    def find_shots(self, **kwargs: Unpack[FindShotsKwargs]) -> list[Shot]:
        """Find previous/approved shots.

        This is the main entry point implementing the abstract method from ShotFinderBase.

        Args:
            **kwargs: Optional keyword arguments
                - active_shots: List of currently active shots to exclude
                - shows_root: Root directory for shows

        Returns:
            List of Shot objects found

        """
        active_shots = kwargs.get("active_shots") or []
        shows_root = kwargs.get("shows_root")

        # Use the main search method
        return self.find_approved_shots(active_shots, shows_root)


@final
class ParallelShotsFinder(PreviousShotsFinder):
    """Parallel implementation of PreviousShotsFinder for improved performance.

    This class uses ThreadPoolExecutor to search multiple shows in parallel,
    reducing scan time from 120+ seconds to ~30-40 seconds.
    """

    def __init__(
        self, username: str | None = None, max_workers: int | None = None
    ) -> None:
        """Initialize the parallel shots finder.

        Args:
            username: Username to search for. If None, uses current user.
            max_workers: Maximum number of parallel workers (default: from config)

        """
        super().__init__(username)
        self.max_workers = (
            max_workers or ThreadingConfig.PREVIOUS_SHOTS_PARALLEL_WORKERS
        )
        # _stop_requested and _progress_callback are inherited from ProgressReportingMixin
        self._show_cache: dict[str, float] = {}  # Cache show list with timestamps
        self._cache_ttl = ThreadingConfig.PREVIOUS_SHOTS_CACHE_TTL

        # Use FilesystemCoordinator for shared directory caching
        from paths.filesystem_coordinator import FilesystemCoordinator

        self._fs_coordinator = FilesystemCoordinator()

    # Progress methods are inherited from ShotFinderBase (ProgressReportingMixin):
    # - set_progress_callback()
    # - request_stop()
    # - _report_progress()
    # - _check_stop()

    def _discover_shows(self, shows_root: Path) -> list[Path]:
        """Quickly discover all shows in the root directory using FilesystemCoordinator.

        Args:
            shows_root: Root directory containing shows

        Returns:
            List of show directory paths

        """
        shows: list[Path] = []

        # Use FilesystemCoordinator for cached directory listing
        contents = self._fs_coordinator.get_directory_listing(shows_root)

        for name, is_dir, _ in contents:
            if self._stop_requested:
                break

            if is_dir and not name.startswith("."):
                # Check if it looks like a show directory
                show_path = shows_root / name

                # Use coordinator to check if shots dir exists (will be cached)
                show_contents = self._fs_coordinator.get_directory_listing(show_path)
                has_shots = any(
                    item_name == "shots" and item_is_dir
                    for item_name, item_is_dir, _ in show_contents
                )

                if has_shots:
                    shows.append(show_path)

        logger.info(
            f"Discovered {len(shows)} shows in {shows_root} (via coordinator)"
        )

        # Share discovered paths with other workers
        discovered: dict[Path, list[tuple[str, bool, bool]]] = {shows_root: contents}
        for show in shows:
            # Pre-cache the shots directory listing for other workers
            shots_dir = show / "shots"
            if shots_dir.exists():
                shots_contents = self._fs_coordinator.get_directory_listing(shots_dir)
                discovered[shots_dir] = shots_contents

        self._fs_coordinator.share_discovered_paths(discovered)

        return shows

    def _scan_show_for_user(self, show_path: Path) -> list[Shot]:
        """Scan a single show for user directories."""
        if self._stop_requested:
            return []
        shots = self._run_find_scan(show_path / "shots", maxdepth=6)
        logger.debug(f"Found {len(shots)} shots in {show_path.name}")
        return shots

    def find_user_shots_parallel(
        self,
        shows_root: Path | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Generator[Shot, None, None]:
        """Find user shots using parallel search with incremental yielding.

        Args:
            shows_root: Root directory to search for shots
            cancel_flag: Optional callable returning True if operation should cancel

        Yields:
            Shot objects as they are discovered

        """

        # Helper to check both internal and external cancellation
        def should_cancel() -> bool:
            return self._stop_requested or (cancel_flag is not None and cancel_flag())

        root = resolve_shows_root(shows_root)

        if not root.exists():
            logger.warning(f"Shows root does not exist: {root}")
            return

        # Stage 1: Quick show discovery
        self._report_progress(0, 100, "Discovering shows...")
        shows = self._discover_shows(root)

        if not shows:
            logger.warning("No shows found to scan")
            return

        # Check for cancellation after show discovery
        if should_cancel():
            logger.debug("Shot search cancelled after show discovery")
            return

        total_shows = len(shows)
        completed_shows = 0

        # Stage 2: Parallel search with incremental results
        self._report_progress(10, 100, f"Scanning {total_shows} shows in parallel...")

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            # Submit all show scans
            future_to_show = {
                executor.submit(self._scan_show_for_user, show): show for show in shows
            }

            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_show):
                if should_cancel():
                    # Cancel remaining futures
                    logger.debug("Cancelling remaining shot search futures")
                    for f in future_to_show:
                        _ = f.cancel()
                    break

                show = future_to_show[future]
                completed_shows += 1

                # Update progress
                progress = 10 + int((completed_shows / total_shows) * 80)
                self._report_progress(
                    progress,
                    100,
                    f"Processed {show.name} ({completed_shows}/{total_shows})",
                )

                try:
                    shots = future.result(timeout=TimeoutConfig.FUTURE_RESULT_QUICK)
                    # Yield shots immediately as they're found
                    yield from shots

                except concurrent.futures.TimeoutError:
                    logger.warning(f"Timeout processing {show.name}")
                except Exception:
                    logger.exception(f"Error processing {show.name}")

        self._report_progress(100, 100, "Scan complete")

    @override
    def find_user_shots(self, shows_root: Path | None = None) -> list[Shot]:
        """Find all shots with user work directories using parallel search.

        This method overrides the parent's synchronous implementation with
        a parallel version.

        Args:
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None)

        Returns:
            List of Shot objects where user has work directories

        """
        root = resolve_shows_root(shows_root)

        # Use parallel implementation
        logger.info("Using parallel shot finder with incremental loading")
        start_time = time.time()

        # Collect all shots from generator
        shots = list(self.find_user_shots_parallel(root))

        elapsed = time.time() - start_time
        logger.info(
            f"Parallel scan found {len(shots)} shots in {elapsed:.1f} seconds"
        )

        return shots

    def find_approved_shots_targeted(
        self, active_shots: list[Shot], shows_root: Path | None = None
    ) -> list[Shot]:
        """Find approved shots using targeted search for maximum performance.

        This method uses the new TargetedShotsFinder which only searches in shows
        where the user has active shots, providing 95%+ performance improvement
        over scanning all shows.

        Args:
            active_shots: Currently active shots from workspace command
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None)

        Returns:
            List of approved/completed shots

        """
        # Local application imports
        from shots.targeted_shot_finder import TargetedShotsFinder

        root = resolve_shows_root(shows_root)

        # Create targeted finder with same settings
        targeted_finder = TargetedShotsFinder(
            username=self.username, max_workers=self.max_workers
        )

        # Set progress callback to forward to our callback
        if self._progress_callback:
            targeted_finder.set_progress_callback(self._progress_callback)

        # Forward stop request
        if self._stop_requested:
            targeted_finder.request_stop()

        logger.info("Using targeted search approach for maximum performance")

        try:
            return targeted_finder.find_approved_shots_targeted(active_shots, root)

        except Exception as e:  # noqa: BLE001
            logger.error(
                f"Error in targeted search, falling back to parallel search: {e}"
            )
            # Fallback to existing parallel implementation
            return self.find_approved_shots(active_shots, root)
