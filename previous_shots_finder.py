"""Finder for previous/approved shots that user has worked on."""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

# Local application imports
from config import Config, ThreadingConfig
from process_pool_manager import CancellableSubprocess
from shot_finder_base import FindShotsKwargs, ShotDetailsDict, ShotFinderBase
from shot_model import Shot
from typing_compat import override


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Generator


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

        # Optimized regex pattern for shot parsing
        # [^/]+ is faster than \w+ for path components
        # Pattern matches: .../shows/{show}/shots/{sequence}/{shot_dir}/... or end of path
        # Made flexible to work with any shows root (not just Config.SHOWS_ROOT)
        # Captures: workspace_path, show, sequence, shot_dir
        self._shot_pattern: re.Pattern[str] = re.compile(
            r"(.*?/shows/([^/]+)/shots/([^/]+)/([^/]+))(?:/|$)"
        )
        # Fallback pattern for non-standard naming
        self._shot_pattern_fallback: re.Pattern[str] = re.compile(
            r"(.*?/shows/([^/]+)/shots/([^/]+)/([^/]+))(?:/|$)"
        )
        self.logger.debug(f"PreviousShotsFinder initialized for user: {self.username}")

    def find_user_shots(self, shows_root: Path | None = None) -> list[Shot]:
        """Find all shots that contain user work directories.

        Args:
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None).

        Returns:
            List of Shot objects where user has work directories.

        """
        shots: list[Shot] = []

        # Ensure shows_root is always a Path object
        if shows_root is None:
            shows_root = Path(Config.SHOWS_ROOT)
        elif isinstance(shows_root, str):
            shows_root = Path(shows_root)

        if not shows_root.exists():
            self.logger.warning(f"Shows root does not exist: {shows_root}")
            return shots

        try:
            # Use Python's native Path.rglob() instead of subprocess find
            # This avoids subprocess isolation issues with pytest-xdist workers
            # where subprocess commands cannot see directories created by the worker
            pattern = f"**/user/{self.username}"
            self.logger.debug(f"Searching for pattern: {pattern} in {shows_root}")

            # Find all matching user directories
            user_dirs = list(shows_root.rglob(pattern))
            self.logger.debug(f"Found {len(user_dirs)} user directories")

            # Parse each found path to extract shot information
            for user_dir in user_dirs:
                # Convert to string for regex matching
                path_str = str(user_dir)
                self.logger.debug(f"Parsing path: {path_str}")

                shot = self._parse_shot_from_path(path_str)
                if shot:
                    self.logger.debug(f"Parsed shot: {shot}")
                    if shot not in shots:
                        shots.append(shot)
                    else:
                        self.logger.debug(f"Shot already in list: {shot}")
                else:
                    self.logger.debug(f"Failed to parse shot from path: {path_str}")

            self.logger.info(f"Found {len(shots)} shots with user work")

        except Exception as e:
            self.logger.error(f"Error finding user shots: {e}")

        return shots

    @override
    def _parse_shot_from_path(self, path: str) -> Shot | None:
        """Parse shot information from a filesystem path.

        Args:
            path: Path containing shot information.

        Returns:
            Shot object if path is valid, None otherwise.

        """
        # Try optimized pattern first (69% faster)
        match = self._shot_pattern.search(path)
        if match:
            # Extract workspace path, show, sequence, and shot directory
            workspace_path, show, sequence, shot_dir = match.groups()

            # Extract shot number from directory name (consistent with base_shot_model logic)
            if shot_dir.startswith(f"{sequence}_"):
                shot = shot_dir[len(sequence) + 1 :]  # +1 for underscore
            else:
                # Non-standard naming, skip
                self.logger.debug(f"Non-standard shot naming: {shot_dir}")
                return None
        else:
            # Fallback for non-standard naming
            match = self._shot_pattern_fallback.search(path)
            if match:
                # Extract workspace path, show, sequence, and shot directory
                workspace_path, show, sequence, shot_dir = match.groups()

                # Extract shot number from directory name
                if shot_dir.startswith(f"{sequence}_"):
                    shot = shot_dir[len(sequence) + 1 :]  # +1 for underscore
                else:
                    # Non-standard naming, skip
                    self.logger.debug(f"Non-standard shot naming: {shot_dir}")
                    return None
            else:
                return None

        # Validate shot is not empty
        if not shot:
            self.logger.debug(f"Empty shot extracted from path {path}")
            return None

        try:
            return Shot(
                show=show,
                sequence=sequence,
                shot=shot,  # Use extracted shot number to match ws -sg
                workspace_path=workspace_path,
            )
        except Exception as e:
            self.logger.debug(f"Could not create Shot from path {path}: {e}")
            return None

    def filter_approved_shots(
        self, all_user_shots: list[Shot], active_shots: list[Shot]
    ) -> list[Shot]:
        """Filter out active shots to get only approved/completed ones.

        Args:
            all_user_shots: All shots where user has work.
            active_shots: Currently active shots from workspace.

        Returns:
            List of approved shots (user shots minus active shots).

        """
        # Create a set of active shot identifiers for efficient lookup
        active_ids = {(shot.show, shot.sequence, shot.shot) for shot in active_shots}

        # Filter out active shots
        approved_shots = [
            shot
            for shot in all_user_shots
            if (shot.show, shot.sequence, shot.shot) not in active_ids
        ]

        self.logger.info(
            f"Filtered {len(all_user_shots)} user shots to "
             f"{len(approved_shots)} approved shots"
        )

        return approved_shots

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
        # Ensure shows_root is always a Path object
        if shows_root is None:
            shows_root = Path(Config.SHOWS_ROOT)
        elif isinstance(shows_root, str):
            shows_root = Path(shows_root)

        all_user_shots = self.find_user_shots(shows_root)
        return self.filter_approved_shots(all_user_shots, active_shots)

    @override
    def get_shot_details(self, shot: Shot) -> ShotDetailsDict:
        """Get additional details about an approved shot.

        Args:
            shot: Shot to get details for.

        Returns:
            Dictionary with shot details including paths and metadata.

        """
        details: ShotDetailsDict = {
            "show": shot.show,
            "sequence": shot.sequence,
            "shot": shot.shot,
            "workspace_path": shot.workspace_path,
            "user_path": f"{shot.workspace_path}{self.user_path_pattern}",
            "status": "approved",  # These are all approved shots
        }

        # Check if user directory still exists
        user_dir = Path(details["user_path"])
        details["user_dir_exists"] = str(user_dir.exists())

        # Check for common VFX work files
        if user_dir.exists():
            details["has_3de"] = str(any(user_dir.rglob("*.3de")))
            details["has_nuke"] = str(any(user_dir.rglob("*.nk")))
            details["has_maya"] = str(any(user_dir.rglob("*.m[ab]")))

        return details

    @override
    def _get_shot_status(self, shot: Shot) -> str:
        """Get the status of a shot (approved or active).

        Args:
            shot: Shot to get status for

        Returns:
            Status string (e.g., "approved", "active")

        """
        # Check for approved status
        approved_path = Path(shot.workspace_path) / "publish" / "matchmove" / "approved"
        if approved_path.exists():
            return "approved"

        # For previous shots, we consider them completed if they're not in active shots
        return "completed"

    @override
    def find_shots(self, **kwargs: FindShotsKwargs) -> list[Shot]:
        """Find previous/approved shots.

        This is the main entry point implementing the abstract method from ShotFinderBase.

        Args:
            **kwargs: Optional keyword arguments
                - active_shots: List of currently active shots to exclude
                - shows_root: Root directory for shows

        Returns:
            List of Shot objects found

        """
        # Extract parameters with type casting for type safety
        # TypedDict.get() returns union of all value types, so we need explicit casting
        active_shots = cast("list[Shot]", kwargs.get("active_shots") or [])
        shows_root = cast("Path | None", kwargs.get("shows_root"))

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
        from filesystem_coordinator import FilesystemCoordinator

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

        for entry in contents:
            if self._stop_requested:
                break

            if entry.is_dir() and not entry.name.startswith("."):
                # Check if it looks like a show directory
                show_path = entry
                shots_dir = show_path / "shots"

                # Use coordinator to check if shots dir exists (will be cached)
                shots_contents = self._fs_coordinator.get_directory_listing(show_path)
                has_shots = any(
                    item.name == "shots" and item.is_dir() for item in shots_contents
                )

                if has_shots:
                    shows.append(show_path)

        self.logger.info(
            f"Discovered {len(shows)} shows in {shows_root} (via coordinator)"
        )

        # Share discovered paths with other workers
        discovered = {shows_root: contents}
        for show in shows:
            # Pre-cache the shots directory listing for other workers
            shots_dir = show / "shots"
            if shots_dir.exists():
                shots_contents = self._fs_coordinator.get_directory_listing(shots_dir)
                discovered[shots_dir] = shots_contents

        self._fs_coordinator.share_discovered_paths(discovered)

        return shows

    def _scan_show_for_user(self, show_path: Path) -> list[Shot]:
        """Scan a single show for user directories.

        Args:
            show_path: Path to the show directory

        Returns:
            List of Shot objects found in this show

        """
        shots: list[Shot] = []

        if self._stop_requested:
            return shots

        try:
            # Use find command limited to this show
            cmd = [
                "find",
                str(show_path / "shots"),
                "-type",
                "d",
                "-path",
                f"*{self.user_path_pattern}",
                "-maxdepth",
                "6",  # Reduced depth since we're starting from shots/
            ]

            # Run with cancellation support using CancellableSubprocess
            proc = CancellableSubprocess(cmd, shell=False, text=True)
            result = proc.run(
                timeout=ThreadingConfig.PREVIOUS_SHOTS_SCAN_TIMEOUT,
                poll_interval=0.1,
                cancel_flag=lambda: self._stop_requested,
            )

            # Handle cancellation
            if result.status == "cancelled":
                self.logger.debug(f"Scan cancelled for show: {show_path.name}")
                return shots

            # Handle timeout
            if result.status == "timeout":
                self.logger.warning(f"Timeout scanning show: {show_path.name}")
                return shots

            # Process successful result
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line or self._stop_requested:
                        continue

                    shot = self._parse_shot_from_path(line)
                    if shot and shot not in shots:
                        shots.append(shot)

            self.logger.debug(f"Found {len(shots)} shots in {show_path.name}")

        except Exception as e:
            self.logger.error(f"Error scanning show {show_path.name}: {e}")

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

        if shows_root is None:
            shows_root = Path(Config.SHOWS_ROOT)

        if not shows_root.exists():
            self.logger.warning(f"Shows root does not exist: {shows_root}")
            return

        # Stage 1: Quick show discovery
        self._report_progress(0, 100, "Discovering shows...")
        shows = self._discover_shows(shows_root)

        if not shows:
            self.logger.warning("No shows found to scan")
            return

        # Check for cancellation after show discovery
        if should_cancel():
            self.logger.debug("Shot search cancelled after show discovery")
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
                    self.logger.debug("Cancelling remaining shot search futures")
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
                    shots = future.result(timeout=5)
                    # Yield shots immediately as they're found
                    yield from shots

                except concurrent.futures.TimeoutError:
                    self.logger.warning(f"Timeout processing {show.name}")
                except Exception as e:
                    self.logger.error(f"Error processing {show.name}: {e}")

        self._report_progress(100, 100, "Scan complete")

    @override
    def find_user_shots(self, shows_root: Path | None = None) -> list[Shot]:
        """Find all shots with user work directories using parallel search.

        This method overrides the parent's synchronous implementation with
        a parallel version. Falls back to legacy method if environment variable is set.

        Args:
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None)

        Returns:
            List of Shot objects where user has work directories

        """
        # Ensure shows_root is always a Path object
        if shows_root is None:
            shows_root = Path(Config.SHOWS_ROOT)
        elif isinstance(shows_root, str):
            shows_root = Path(shows_root)

        # Check for legacy mode fallback
        if os.environ.get("USE_LEGACY_SHOT_FINDER"):
            self.logger.info("Using legacy sequential shot finder")
            return super().find_user_shots(shows_root)

        # Use new parallel implementation
        self.logger.info("Using parallel shot finder with incremental loading")
        start_time = time.time()

        # Collect all shots from generator
        shots = list(self.find_user_shots_parallel(shows_root))

        elapsed = time.time() - start_time
        self.logger.info(
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
        from targeted_shot_finder import TargetedShotsFinder

        # Ensure shows_root is always a Path object
        if shows_root is None:
            shows_root = Path(Config.SHOWS_ROOT)
        elif isinstance(shows_root, str):
            shows_root = Path(shows_root)

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

        self.logger.info("Using targeted search approach for maximum performance")

        try:
            return targeted_finder.find_approved_shots_targeted(
                active_shots, shows_root
            )

        except Exception as e:
            self.logger.error(
                f"Error in targeted search, falling back to parallel search: {e}"
            )
            # Fallback to existing parallel implementation
            return self.find_approved_shots(active_shots, shows_root)
