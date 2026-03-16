"""SceneDiscoveryCoordinator - Template Method Pattern implementation

This module provides the main coordinator that orchestrates scene discovery using
all the extracted components (FileSystemScanner, SceneParser).
It implements the Template Method pattern to provide a unified interface while
maintaining backward compatibility.

Part of the Phase 2 refactoring to break down the monolithic scene finder.
"""
from __future__ import annotations

# Standard library imports
import concurrent.futures
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, final


_logger = logging.getLogger(__name__)

# Local application imports
from logging_mixin import LoggingMixin, log_execution


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Generator
    from pathlib import Path

    # Local application imports
    from filesystem_scanner import FileSystemScanner
    from scene_parser import SceneParser
    from type_definitions import Shot, ThreeDEScene


@final
class SceneDiscoveryCoordinator(LoggingMixin):
    """Main coordinator for scene discovery using Template Method pattern.

    This class orchestrates all the extracted components to provide a unified
    interface for scene discovery while maintaining backward compatibility with
    the original monolithic scene finder.

    The Template Method pattern is used to define the algorithm skeleton while
    allowing different strategies to be plugged in for specific steps.
    """

    # Type annotations for lazy-loaded attributes
    scanner: FileSystemScanner
    parser: SceneParser

    def __init__(
        self,
        strategy_type: str = "local",
    ) -> None:
        """Initialize scene discovery coordinator.

        Args:
            strategy_type: Discovery strategy to use ("local", "progressive")

        """
        super().__init__()

        if strategy_type not in ("local", "progressive"):
            msg = (
                f"Unknown strategy type: {strategy_type}. "
                f"Available: local, progressive"
            )
            raise ValueError(msg)

        self._use_progressive = strategy_type == "progressive"

        # Lazy imports to break circular dependencies
        # Import only when needed at runtime, not at module load time
        from filesystem_scanner import (
            FileSystemScanner,
        )
        from scene_parser import (
            SceneParser,
        )

        # Core components
        self.scanner = FileSystemScanner()
        self.parser = SceneParser()

        # Statistics
        self.stats = {
            "scenes_discovered": 0,
            "errors": 0,
        }

        self.logger.info(
            f"Initialized SceneDiscoveryCoordinator with {strategy_type} strategy"
        )

    # ------------------------------------------------------------------
    # Private strategy implementations
    # ------------------------------------------------------------------

    def _find_scenes_for_shot_local(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for a shot using local filesystem scanning."""
        scenes: list[ThreeDEScene] = []

        try:
            from pathlib import Path

            from utils import ValidationUtils, get_excluded_users

            # Input validation
            if not ValidationUtils.validate_shot_components(show, sequence, shot):
                self.logger.warning("Invalid shot components provided")
                return []

            if not shot_workspace_path:
                self.logger.warning("Empty shot workspace path provided")
                return []

            if excluded_users is None:
                excluded_users = get_excluded_users()

            shot_path = Path(shot_workspace_path)

            # Check user directory
            user_dir = shot_path / "user"
            if user_dir.exists():
                self.logger.debug(f"Scanning user directory: {user_dir}")

                # Use progressive discovery for efficiency
                file_pairs = self.scanner.find_3de_files_progressive(
                    user_dir, excluded_users
                )
                self.logger.debug(f"Found {len(file_pairs)} .3de files")

                # Convert file pairs to ThreeDEScene objects
                for username, threede_file in file_pairs:
                    try:
                        # Verify file accessibility
                        if not self.scanner.verify_scene_exists(threede_file):
                            continue

                        # Extract plate using parser
                        user_path = user_dir / username
                        plate = self.parser.extract_plate_from_path(
                            threede_file, user_path
                        )

                        # Create scene object
                        scene = self.parser.create_scene_from_file_info(
                            threede_file,
                            show,
                            sequence,
                            shot,
                            username,
                            plate,
                            shot_workspace_path,
                        )
                        scenes.append(scene)

                    except Exception:  # noqa: BLE001
                        self.logger.warning(f"Error processing {threede_file}", exc_info=True)
                        continue

            # Also scan publish directory
            publish_dir = shot_path / "publish"
            if publish_dir.exists():
                self.logger.debug(f"Scanning publish directory: {publish_dir}")
                publish_scenes = self._scan_publish_directory(
                    publish_dir, show, sequence, shot, shot_workspace_path
                )
                scenes.extend(publish_scenes)

            self.logger.info(
                f"Found {len(scenes)} total scenes for {show}/{sequence}/{shot}"
            )

        except Exception:
            self.logger.exception(f"Error finding scenes for {show}/{sequence}/{shot}")

        return scenes

    def _scan_publish_directory(
        self,
        publish_dir: Path,
        show: str,
        sequence: str,
        shot: str,
        workspace_path: str,
    ) -> list[ThreeDEScene]:
        """Scan publish directory for additional scenes."""
        scenes: list[ThreeDEScene] = []

        try:
            # Find .3de files in publish directory
            publish_files = list(publish_dir.rglob("*.3de"))
            publish_files.extend(list(publish_dir.rglob("*.3DE")))

            for threede_file in publish_files:
                if not self.scanner.verify_scene_exists(threede_file):
                    continue

                try:
                    relative_path = threede_file.relative_to(publish_dir)
                    department = (
                        relative_path.parts[0] if relative_path.parts else "unknown"
                    )
                    pseudo_user = f"published-{department}"

                    plate = self.parser.extract_plate_from_path(
                        threede_file, publish_dir
                    )

                    scene = self.parser.create_scene_from_file_info(
                        threede_file,
                        show,
                        sequence,
                        shot,
                        pseudo_user,
                        plate,
                        workspace_path,
                    )
                    scenes.append(scene)

                except Exception as e:  # noqa: BLE001
                    self.logger.debug(
                        f"Error processing published file {threede_file}: {e}"
                    )
                    continue

        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Error scanning publish directory: {e}")

        return scenes

    def _find_all_scenes_in_show_local(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in a show using local filesystem scanning."""
        scenes: list[ThreeDEScene] = []

        try:
            from pathlib import Path

            show_path = Path(show_root) / show
            if not show_path.exists():
                self.logger.warning(f"Show path does not exist: {show_path}")
                return []

            # Use targeted search for efficiency
            file_results = self.scanner.find_all_3de_files_in_show_targeted(
                show_root, show, excluded_users
            )

            self.logger.info(f"Found {len(file_results)} .3de files in {show}")

            # Convert to ThreeDEScene objects
            for file_path, show_name, sequence, shot_name, user, plate in file_results:
                workspace_path = (
                    show_path / "shots" / sequence / f"{sequence}_{shot_name}"
                )

                scene = self.parser.create_scene_from_file_info(
                    file_path,
                    show_name,
                    sequence,
                    shot_name,
                    user,
                    plate,
                    str(workspace_path),
                )
                scenes.append(scene)

            self.logger.info(f"Found {len(scenes)} total scenes in show {show}")

        except Exception:
            self.logger.exception(f"Error finding scenes in show {show}")

        return scenes

    def _find_all_scenes_in_show_progressive(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in show using progressive discovery (collects all at once)."""
        scenes: list[ThreeDEScene] = []
        for (
            scene_batch,
            _current_shot,
            _total_shots,
            _status,
        ) in self._find_scenes_progressive_impl(show_root, show, excluded_users):
            scenes.extend(scene_batch)
        return scenes

    def _find_scenes_progressive_impl(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
        batch_size: int = 10,
    ) -> Generator[tuple[list[ThreeDEScene], int, int, str], None, None]:
        """Find scenes progressively with batch updates.

        Args:
            show_root: Root path for shows
            show: Show name
            excluded_users: Set of usernames to exclude
            batch_size: Number of scenes per batch

        Yields:
            Tuple of (scene_batch, current_shot, total_shots, status_message)

        """
        try:
            # First discover all shots in the show
            shot_tuples = self.scanner.discover_all_shots_in_show(show_root, show)

            if not shot_tuples:
                yield [], 0, 0, "No shots found"
                return

            # Use scanner's progressive discovery
            for (
                file_batch,
                current_shot,
                total_shots,
                status,
            ) in self.scanner.find_all_scenes_progressive(
                shot_tuples, excluded_users, batch_size
            ):
                scenes: list[ThreeDEScene] = []
                for _username, threede_file in file_batch:
                    try:
                        from pathlib import Path

                        show_path = Path(show_root) / show

                        parsed = self.parser.parse_3de_file_path(
                            threede_file, show_path, show, excluded_users or set()
                        )

                        if parsed:
                            file_path, show_name, sequence, shot_name, user, plate = (
                                parsed
                            )
                            workspace_path = (
                                show_path
                                / "shots"
                                / sequence
                                / f"{sequence}_{shot_name}"
                            )

                            scene = self.parser.create_scene_from_file_info(
                                file_path,
                                show_name,
                                sequence,
                                shot_name,
                                user,
                                plate,
                                str(workspace_path),
                            )
                            scenes.append(scene)

                    except Exception as e:  # noqa: BLE001
                        self.logger.warning(
                            f"Error processing scene file {threede_file}: {e}"
                        )
                        continue

                yield scenes, current_shot, total_shots, status

        except Exception as e:
            self.logger.exception(f"Error in progressive discovery for {show}")
            yield [], 0, 0, f"Error: {e}"

    # ------------------------------------------------------------------
    # Template Methods
    # ------------------------------------------------------------------

    # Template Method - defines the algorithm skeleton
    @log_execution(include_args=False)  # pyright: ignore[reportUntypedFunctionDecorator]
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Template method for finding scenes in a specific shot.

        This method defines the algorithm structure:
        1. Validate input
        2. Discover scenes using strategy
        3. Parse and validate results
        4. Return results

        Args:
            shot_workspace_path: Path to shot workspace
            show: Show name
            sequence: Sequence name
            shot: Shot name
            excluded_users: Set of usernames to exclude

        Returns:
            List of ThreeDEScene objects

        """
        try:
            # Step 1: Validate input
            if not self._validate_shot_input(shot_workspace_path, show, sequence, shot):
                return []

            # Step 2: Discover scenes using strategy
            with self.logger.context(
                operation="scene_discovery", shot=f"{show}/{sequence}/{shot}"
            ):
                # Progressive strategy delegates single-shot discovery to local
                scenes = self._find_scenes_for_shot_local(
                    shot_workspace_path, show, sequence, shot, excluded_users
                )

            # Step 3: Validate and filter results
            valid_scenes = self._validate_and_filter_scenes(scenes)

            # Step 4: Update statistics and return results
            self.stats["scenes_discovered"] += len(valid_scenes)
            self.logger.info(
                f"Discovered {len(valid_scenes)} scenes for {show}/{sequence}/{shot}"
            )

            return valid_scenes

        except Exception as e:  # noqa: BLE001
            self.stats["errors"] += 1
            self.logger.error(
                f"Error discovering scenes for {show}/{sequence}/{shot}: {e}"
            )
            return []

    @log_execution(include_args=False)  # pyright: ignore[reportUntypedFunctionDecorator]
    def find_all_scenes_in_shows(
        self,
        user_shots: list[Shot],
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Template method for finding all scenes across multiple shows.

        Args:
            user_shots: List of Shot objects to determine which shows to search
            excluded_users: Set of usernames to exclude

        Returns:
            List of all ThreeDEScene objects found

        """
        if not user_shots:
            self.logger.info("No user shots provided for scene discovery")
            return []

        try:
            # Extract unique shows and their roots
            show_info = self._extract_show_information(user_shots)

            all_scenes: list[ThreeDEScene] = []

            # Process each show
            for show_root, shows in show_info.items():
                for show in shows:
                    with self.logger.context(operation="show_discovery", show=show):
                        # Discover scenes using strategy
                        if self._use_progressive:
                            show_scenes = self._find_all_scenes_in_show_progressive(
                                show_root, show, excluded_users
                            )
                        else:
                            show_scenes = self._find_all_scenes_in_show_local(
                                show_root, show, excluded_users
                            )

                        # Validate and filter results
                        valid_scenes = self._validate_and_filter_scenes(show_scenes)

                        all_scenes.extend(valid_scenes)
                        self.stats["scenes_discovered"] += len(valid_scenes)

                        self.logger.info(
                            f"Discovered {len(valid_scenes)} scenes in show {show}"
                        )

            self.logger.info(
                f"Total scenes discovered across all shows: {len(all_scenes)}"
            )
            return all_scenes

        except Exception:
            self.stats["errors"] += 1
            self.logger.exception("Error discovering scenes across shows")
            return []

    # Hook methods

    def _validate_shot_input(
        self, shot_workspace_path: str, show: str, sequence: str, shot: str
    ) -> bool:
        """Validate input parameters for shot discovery."""
        # Local application imports
        from utils import ValidationUtils

        if not ValidationUtils.validate_shot_components(show, sequence, shot):
            self.logger.warning("Invalid shot components provided")
            return False

        if not shot_workspace_path:
            self.logger.warning("Empty shot workspace path provided")
            return False

        return True

    def _validate_and_filter_scenes(
        self, scenes: list[ThreeDEScene]
    ) -> list[ThreeDEScene]:
        """Validate and filter discovered scenes."""
        valid_scenes: list[ThreeDEScene] = []

        for scene in scenes:
            if self._is_valid_scene(scene):
                valid_scenes.append(scene)
            else:
                self.logger.debug(f"Filtered out invalid scene: {scene.scene_path}")

        return valid_scenes

    def _is_valid_scene(self, scene: ThreeDEScene) -> bool:
        """Check if a scene is valid."""
        # Basic validation
        if not scene.scene_path:
            return False

        # Verify file exists and is accessible
        return self.scanner.verify_scene_exists(scene.scene_path)

    def _extract_show_information(self, user_shots: list[Shot]) -> dict[str, set[str]]:
        """Extract show roots and show names from user shots."""
        # Standard library imports
        from pathlib import Path

        show_info: dict[str, set[str]] = {}

        for shot in user_shots:
            # Extract show root from workspace path
            workspace_path = Path(shot.workspace_path)
            show_root = None

            # Find the parent directory containing "shots"
            # The show root should be the parent of the show directory (e.g., /shows)
            for i, parent in enumerate(workspace_path.parents):
                if parent.name == "shots" and i > 0:
                    # The parent of "shots" is the show directory
                    # The parent of that is the shows root
                    show_dir = parent.parent  # This is the show directory
                    if show_dir.parent:  # This is the shows root
                        show_root = str(show_dir.parent)
                    else:
                        # If there's no parent, use the show directory itself
                        show_root = str(show_dir)
                    break

            if show_root:
                if show_root not in show_info:
                    show_info[show_root] = set()
                show_info[show_root].add(shot.show)

        # Fallback if no show roots found
        if not show_info:
            self.logger.warning(
                "No show roots found from workspace paths, using default /shows"
            )
            unique_shows = {shot.show for shot in user_shots}
            show_info["/shows"] = unique_shows

        return show_info

    # Utility methods

    def get_statistics(self) -> dict[str, int]:
        """Get discovery statistics."""
        return self.stats.copy()

    @staticmethod
    def _resolve_shows_root(user_shots: list[Shot]) -> str:
        """Resolve the shows root directory from the first shot's workspace path.

        Walks up the workspace path looking for a directory named "shows" or
        a directory that contains SHOW/shots. Falls back to Config.SHOWS_ROOT.

        Args:
            user_shots: List of Shot objects to inspect.

        Returns:
            Absolute path string of the shows root directory.

        """
        # Standard library imports
        from pathlib import Path

        # Local application imports
        from config import Config

        if not user_shots or not user_shots[0].workspace_path:
            return Config.SHOWS_ROOT

        workspace_path = Path(user_shots[0].workspace_path)
        for parent in workspace_path.parents:
            if (
                parent.name == "shows"
                or (parent / user_shots[0].show / "shots").exists()
            ):
                return str(parent)

        return Config.SHOWS_ROOT

    @staticmethod
    def _process_show(
        show: str,
        shows_root: str,
        user_shots: list[Shot],
        excluded_users: set[str] | None,
        cancel_flag: Callable[[], bool],
    ) -> list[ThreeDEScene]:
        """Process a single show and return its ThreeDEScene list.

        Scans the show directory for .3de files, resolves workspace paths, and
        constructs ThreeDEScene objects. Checks cancellation every 10 files.

        Args:
            show: Show name to scan.
            shows_root: Root directory containing all shows.
            user_shots: Full list of user shots (for workspace-path resolution).
            excluded_users: Set of usernames whose files should be excluded.
            cancel_flag: Callable returning True when discovery should stop.

        Returns:
            List of ThreeDEScene objects found in this show.

        """
        # Standard library imports
        from pathlib import Path

        # Local application imports
        from filesystem_scanner import FileSystemScanner
        from scene_parser import SceneParser

        show_scenes: list[ThreeDEScene] = []

        if cancel_flag():
            return show_scenes

        show_path = Path(shows_root) / show
        if not show_path.exists():
            return show_scenes

        scanner = FileSystemScanner()
        try:
            file_tuples = scanner.find_all_3de_files_in_show_targeted(
                shows_root, show, excluded_users
            )
        except Exception:
            _logger.exception("Error scanning show %s", show)
            return show_scenes

        for i, (scene_path, show_name, seq, shot, user, plate) in enumerate(file_tuples):
            # Check cancellation every 10 items to balance responsiveness with performance
            if i % 10 == 0 and cancel_flag():
                return show_scenes

            # Find matching shot from user_shots for workspace path
            # NOTE: matching_shot might be None if this scene is from a shot
            # that isn't assigned to the current user
            matching_shot = next(
                (
                    s
                    for s in user_shots
                    if s.show == show_name and s.sequence == seq and s.shot == shot
                ),
                None,
            )

            # CRITICAL FIX: Always create the scene, regardless of whether
            # the shot is assigned to the current user. This ensures we show
            # ALL 3DE scenes from other users, not just those on assigned shots.
            # Previously, scenes were incorrectly filtered out if matching_shot was None.
            if matching_shot:
                # User is assigned to this shot - use their workspace path
                workspace_path = matching_shot.workspace_path
            else:
                # User is NOT assigned to this shot - construct a valid workspace path
                # This allows viewing 3DE work from other users on any shot in the show
                workspace_path = f"{shows_root}/{show_name}/shots/{seq}/{seq}_{shot}"

            scene = SceneParser.create_scene_from_file_info(
                scene_path, show_name, seq, shot, user, plate, workspace_path
            )
            show_scenes.append(scene)

        return show_scenes

    @staticmethod
    def _collect_parallel_results(
        executor: ThreadPoolExecutor,
        future_to_show: dict[concurrent.futures.Future[list[ThreeDEScene]], str],
        shows: set[str],
        cancel_flag: Callable[[], bool],
        progress_callback: Callable[[int, str], None] | None,
    ) -> list[ThreeDEScene]:
        """Drain the as_completed queue and collect ThreeDEScene results.

        Checks cancellation before each result. On cancellation, cancels all
        remaining futures and shuts down the executor without waiting.

        The TimeoutError retry path (timeout=0.5 then unbounded result()) is a
        known concern — do not change the behavior; it exists so callers remain
        responsive to cancellation while still collecting slow results.

        Args:
            executor: Active ThreadPoolExecutor to shut down on cancellation.
            future_to_show: Mapping from future to show name.
            shows: Full set of show names (used for progress percentage).
            cancel_flag: Callable returning True when discovery should stop.
            progress_callback: Optional (percent, message) callback.

        Returns:
            Flat list of all collected ThreeDEScene objects.

        """
        # Standard library imports
        import threading

        all_scenes: list[ThreeDEScene] = []
        results_lock = threading.Lock()
        shows_completed = 0

        def _cancel_remaining() -> None:
            for f in future_to_show:
                if not f.done():
                    _ = f.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        try:
            for future in as_completed(future_to_show):
                show = future_to_show[future]

                if cancel_flag():
                    _cancel_remaining()
                    break

                try:
                    # Use a short timeout to be more responsive to cancellation
                    show_scenes = future.result(timeout=0.5)
                    with results_lock:
                        all_scenes.extend(show_scenes)
                        shows_completed += 1
                        if progress_callback:
                            progress_callback(
                                int((shows_completed / len(shows)) * 100),
                                f"Completed {show}: found {len(show_scenes)} scenes",
                            )

                except concurrent.futures.TimeoutError:
                    # If result not ready, check cancellation again
                    if cancel_flag():
                        _cancel_remaining()
                        break
                    # Re-get the result without timeout
                    show_scenes = future.result()
                    with results_lock:
                        all_scenes.extend(show_scenes)
                        shows_completed += 1

                except Exception:
                    _logger.exception("Error processing show %s", show)
                    with results_lock:
                        shows_completed += 1

        except Exception:
            _cancel_remaining()
            raise

        return all_scenes

    @staticmethod
    def find_all_scenes_in_shows_truly_efficient_parallel(
        user_shots: list[Shot],
        excluded_users: set[str] | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes across shows using parallel discovery.

        Provides parallel scene discovery with progress and cancellation support.
        """
        # Normalize cancel_flag to eliminate None-guard branches throughout
        _cancel: Callable[[], bool] = cancel_flag or (lambda: False)

        if _cancel():
            return []

        if progress_callback:
            progress_callback(0, "Starting parallel scene discovery...")

        shows = {shot.show for shot in user_shots if shot.show}
        shows_root = SceneDiscoveryCoordinator._resolve_shows_root(user_shots)

        # Process shows in parallel using ThreadPoolExecutor
        max_workers = min(len(shows), 3)  # Limit to 3 parallel searches for network filesystem
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_show = {
                executor.submit(
                    SceneDiscoveryCoordinator._process_show,
                    show, shows_root, user_shots, excluded_users, _cancel,
                ): show
                for show in shows
            }
            all_scenes = SceneDiscoveryCoordinator._collect_parallel_results(
                executor, future_to_show, shows, _cancel, progress_callback
            )

        if progress_callback:
            progress_callback(100, f"Found {len(all_scenes)} scenes")

        return all_scenes
