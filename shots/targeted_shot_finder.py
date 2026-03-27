#!/usr/bin/env python3
"""Targeted shot finder that only searches in shows where user has active shots.

This module provides a highly optimized shot finder that dramatically reduces
search time by only looking in shows where the user has active shots from ws -sg.
This reduces the search space by 95%+ compared to scanning all shows.
"""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import re
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import Unpack

# Local application imports
from config import Config, ThreadingConfig
from paths import build_workspace_path, resolve_shows_root
from paths.shot_dir_parser import parse_shot_from_dir
from shots.shot_finder_base import FindShotsKwargs, ShotFinderBase
from timeout_config import TimeoutConfig
from type_definitions import Shot
from typing_compat import override
from workers.process_pool_manager import CancellableSubprocess


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator


class TargetedShotsFinder(ShotFinderBase):
    """Finds shots by targeting only shows containing user's active shots.

    This class provides dramatic performance improvements over scanning all shows
    by extracting the list of shows from active shots and only searching within
    those specific show directories.

    Performance: Reduces search time from 60-120s to 5-10s by limiting scope.
    """

    def __init__(
        self, username: str | None = None, max_workers: int | None = None
    ) -> None:
        """Initialize the targeted shots finder.

        Args:
            username: Username to search for. If None, uses current user.
            max_workers: Maximum number of parallel workers (default: from config)

        """
        # Initialize parent class (ShotFinderBase) which handles username sanitization
        super().__init__(username=username)

        # Additional initialization specific to TargetedShotsFinder
        self.max_workers: int = (
            max_workers or ThreadingConfig.PREVIOUS_SHOTS_PARALLEL_WORKERS
        )

        # Pattern for parsing shot paths (dynamic based on configured SHOWS_ROOT)
        shows_root_escaped = re.escape(Config.SHOWS_ROOT)
        self._shot_pattern: re.Pattern[str] = re.compile(
            rf"{shows_root_escaped}/([^/]+)/shots/([^/]+)/([^/]+)/"
        )

        self.logger.debug(f"TargetedShotsFinder initialized for user: {self.username}")

    # Progress methods are inherited from ShotFinderBase (ProgressReportingMixin):
    # - set_progress_callback()
    # - request_stop()
    # - _report_progress()
    # - _check_stop()

    def extract_shows_from_active_shots(self, active_shots: list[Shot]) -> set[str]:
        """Extract unique show names from active shots.

        Args:
            active_shots: List of active shots from ws -sg

        Returns:
            Set of unique show names

        """
        shows = {shot.show for shot in active_shots}
        self.logger.info(
            f"Extracted {len(shows)} unique shows from {len(active_shots)} active shots"
        )
        self.logger.debug(f"Shows: {sorted(shows)}")
        return shows

    def _scan_show_for_user(
        self, show_name: str, shows_root: Path | None = None
    ) -> list[Shot]:
        """Scan a specific show for user directories.

        Args:
            show_name: Name of the show to scan
            shows_root: Root directory containing shows (uses Config.SHOWS_ROOT if None)

        Returns:
            List of Shot objects found in this show

        """
        shots: list[Shot] = []

        if self._stop_requested:
            return shots

        root = resolve_shows_root(shows_root)
        show_path = root / show_name / "shots"
        if not show_path.exists():
            self.logger.debug(f"Shots directory does not exist: {show_path}")
            return shots

        try:
            # Use targeted find command for this specific show
            cmd = [
                "find",
                str(show_path),
                "-type",
                "d",
                "-path",
                f"*{self.user_path_pattern}",
                "-maxdepth",
                "4",  # Reduced depth since we're starting from shots/
            ]

            self.logger.debug(f"Scanning show {show_name}: {' '.join(cmd)}")

            # Run with cancellation support using CancellableSubprocess
            proc = CancellableSubprocess(cmd, shell=False, text=True)
            result = proc.run(
                timeout=TimeoutConfig.PREVIOUS_SHOTS_SCAN_SEC,
                poll_interval=0.1,
                cancel_flag=lambda: self._stop_requested,
            )

            # Handle cancellation
            if result.status == "cancelled":
                self.logger.debug(f"Scan cancelled for show: {show_name}")
                return shots

            # Handle timeout
            if result.status == "timeout":
                self.logger.warning(f"Timeout scanning show: {show_name}")
                return shots

            # Process successful result
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line or self._stop_requested:
                        continue

                    shot = self._parse_shot_from_path(line)
                    if shot and shot not in shots:
                        shots.append(shot)

            self.logger.debug(f"Found {len(shots)} shots in show {show_name}")

        except Exception:
            self.logger.exception(f"Error scanning show {show_name}")

        return shots

    @override
    def _parse_shot_from_path(self, path: str) -> Shot | None:
        """Parse shot information from a filesystem path.

        Args:
            path: Path containing shot information

        Returns:
            Shot object if path is valid, None otherwise

        """
        match = self._shot_pattern.search(path)
        if match:
            show, sequence, shot_dir = match.groups()

            # Extract shot number from directory name using canonical parser
            shot = parse_shot_from_dir(sequence, shot_dir)

            # Validate shot is not empty
            if not shot:
                self.logger.debug(f"Empty shot extracted from path {path}")
                return None

            workspace_path = str(build_workspace_path(Config.SHOWS_ROOT, show, sequence, shot))

            try:
                return Shot(
                    show=show,
                    sequence=sequence,
                    shot=shot,  # Use extracted shot number to match ws -sg
                    workspace_path=workspace_path,
                )
            except Exception as e:  # noqa: BLE001
                self.logger.debug(f"Could not create Shot from path {path}: {e}")

        return None

    def find_user_shots_in_shows(
        self, target_shows: set[str], shows_root: Path | None = None
    ) -> Generator[Shot, None, None]:
        """Find user shots in the specified shows using parallel search.

        Args:
            target_shows: Set of show names to search in
            shows_root: Root directory containing shows (uses Config.SHOWS_ROOT if None)

        Yields:
            Shot objects as they are discovered

        """
        if not target_shows:
            self.logger.warning("No target shows provided for search")
            return

        root = resolve_shows_root(shows_root)
        if not root.exists():
            self.logger.warning(f"Shows root does not exist: {root}")
            return

        total_shows = len(target_shows)
        completed_shows = 0

        # Report initial progress
        self._report_progress(0, 100, f"Searching in {total_shows} targeted shows...")

        # Parallel search within targeted shows only
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            # Submit search tasks for each target show
            future_to_show = {
                executor.submit(self._scan_show_for_user, show, root): show
                for show in target_shows
            }

            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_show):
                if self._stop_requested:
                    # Cancel remaining futures
                    for f in future_to_show:
                        _ = f.cancel()
                    break

                show = future_to_show[future]
                completed_shows += 1

                # Update progress
                progress = int(
                    (completed_shows / total_shows) * 90
                )  # Use 90% for search phase
                self._report_progress(
                    progress, 100, f"Processed {show} ({completed_shows}/{total_shows})"
                )

                try:
                    shots = future.result(timeout=TimeoutConfig.FUTURE_RESULT_QUICK)
                    # Yield shots immediately as they're found
                    yield from shots

                except concurrent.futures.TimeoutError:
                    self.logger.warning(f"Timeout processing {show}")
                except Exception:
                    self.logger.exception(f"Error processing {show}")

        self._report_progress(100, 100, "Targeted search complete")

    def find_approved_shots_targeted(
        self, active_shots: list[Shot], shows_root: Path | None = None
    ) -> list[Shot]:
        """Find approved shots using targeted search approach.

        This method combines show extraction and targeted searching for maximum efficiency.
        Only searches in shows where the user has active shots.

        Args:
            active_shots: Currently active shots from workspace
            shows_root: Root directory to search for shots (uses Config.SHOWS_ROOT if None)

        Returns:
            List of approved/completed shots

        """
        # Standard library imports
        import time

        start_time = time.time()

        root = resolve_shows_root(shows_root)

        # Extract target shows from active shots
        target_shows = self.extract_shows_from_active_shots(active_shots)

        if not target_shows:
            self.logger.warning("No target shows found from active shots")
            return []

        self.logger.info(
            f"Using targeted search in {len(target_shows)} shows instead of scanning all shows"
        )

        # Find all user shots in target shows
        self._report_progress(5, 100, "Finding user shots in targeted shows...")
        all_user_shots = list(self.find_user_shots_in_shows(target_shows, root))

        if self._stop_requested:
            self.logger.info("Targeted search stopped by user request")
            return []

        # Filter to get only approved shots using base class implementation
        self._report_progress(95, 100, "Filtering approved shots...")
        approved_shots = self._filter_approved_shots(all_user_shots, active_shots)

        elapsed = time.time() - start_time
        self.logger.info(

                f"Targeted search found {len(approved_shots)} approved shots "
                f"in {elapsed:.1f} seconds (was 60-120s with global search)"

        )

        self._report_progress(100, 100, "Targeted search complete")
        return approved_shots

    @override
    def _get_unapproved_status(self, shot: Shot) -> str:
        """Get the status of a shot that is not approved.

        Args:
            shot: Shot to get status for

        Returns:
            "active" if user has work in this shot, otherwise "unknown"

        """
        user_path = Path(shot.workspace_path) / "user" / self.username
        if user_path.exists():
            return "active"
        return "unknown"

    @override
    def find_shots(self, **kwargs: Unpack[FindShotsKwargs]) -> list[Shot]:
        """Find shots using targeted search.

        This is the main entry point implementing the abstract method from ShotFinderBase.

        Args:
            **kwargs: Typed keyword arguments (see FindShotsKwargs)
                - target_shows: Set of show names to search in
                - shows_root: Root directory for shows (uses Config.SHOWS_ROOT if None)
                - active_shots: List of active shots to extract shows from

        Returns:
            List of Shot objects found

        """
        # Extract parameters with proper type annotations for type checker
        shows_to_search: set[str] = kwargs.get("target_shows") or set()
        root_dir: Path | None = kwargs.get("shows_root")
        shots_list: list[Shot] = kwargs.get("active_shots", [])

        # If we have active shots but no target shows, extract them
        if shots_list and not shows_to_search:
            shows_to_search = self.extract_shows_from_active_shots(shots_list)

        # Use the main search method
        if shows_to_search:
            return list(self.find_user_shots_in_shows(shows_to_search, root_dir))
        self.logger.warning("No target shows provided for search")
        return []
