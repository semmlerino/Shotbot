"""SceneDiscoveryCoordinator - Template Method Pattern implementation

This module provides the main coordinator that orchestrates scene discovery using
all the extracted components (FileSystemScanner, SceneParser, SceneCache, and
SceneDiscoveryStrategy). It implements the Template Method pattern to provide
a unified interface while maintaining backward compatibility.

Part of the Phase 2 refactoring to break down the monolithic scene finder.
"""
# pyright: reportImportCycles=false
# Import cycles are broken at runtime by lazy imports in __init__ and switch_strategy.
# The cycles exist at module level due to: scene_cache → threede_scene_model → threede_scene_finder
# → threede_scene_finder_optimized → scene_discovery_coordinator → scene_cache (and similar chains
# through filesystem_scanner and scene_parser). All imports are deferred to method execution time.

from __future__ import annotations

# Standard library imports
import concurrent.futures
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Unpack, final


_logger = logging.getLogger(__name__)

# Local application imports
from logging_mixin import LoggingMixin, log_execution


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Generator

    # Local application imports
    from scene_discovery_strategy import StrategyKwargs
    from shot_model import Shot
    from threede_scene_model import ThreeDEScene


@final
class SceneDiscoveryCoordinator(LoggingMixin):
    """Main coordinator for scene discovery using Template Method pattern.

    This class orchestrates all the extracted components to provide a unified
    interface for scene discovery while maintaining backward compatibility with
    the original monolithic scene finder.

    The Template Method pattern is used to define the algorithm skeleton while
    allowing different strategies to be plugged in for specific steps.
    """

    def __init__(
        self,
        strategy_type: str = "local",
        enable_caching: bool = True,
        cache_ttl: int = 1800,  # 30 minutes
        **strategy_kwargs: Unpack[StrategyKwargs],
    ) -> None:
        """Initialize scene discovery coordinator.

        Args:
            strategy_type: Discovery strategy to use ("local", "progressive")
            enable_caching: Whether to enable result caching
            cache_ttl: Cache TTL in seconds
            **strategy_kwargs: Additional arguments for strategy initialization

        """
        super().__init__()

        # Lazy imports to break circular dependencies
        # Import only when needed at runtime, not at module load time
        from filesystem_scanner import (
            FileSystemScanner,
        )
        from scene_cache import SceneCache
        from scene_discovery_strategy import (
            create_discovery_strategy,
        )
        from scene_parser import (
            SceneParser,
        )

        # Core components
        self.scanner = FileSystemScanner()
        self.parser = SceneParser()
        self.cache = SceneCache(default_ttl=cache_ttl) if enable_caching else None
        self.strategy = create_discovery_strategy(strategy_type, **strategy_kwargs)

        self.enable_caching = enable_caching

        # Statistics
        self.stats = {
            "scenes_discovered": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
        }

        self.logger.info(
            f"Initialized SceneDiscoveryCoordinator with {strategy_type} strategy"
        )

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
        2. Check cache (if enabled)
        3. Discover scenes using strategy
        4. Parse and validate results
        5. Update cache (if enabled)
        6. Return results

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

            # Normalize excluded_users for cache key
            frozen_excluded = frozenset(excluded_users) if excluded_users else None

            # Step 2: Check cache (if enabled)
            if self.enable_caching and self.cache:
                cached_result = self.cache.get_scenes_for_shot(
                    show, sequence, shot,
                    shot_workspace_path=shot_workspace_path,
                    excluded_users=frozen_excluded,
                )
                if cached_result is not None:
                    self.stats["cache_hits"] += 1
                    self.logger.debug(f"Cache hit for {show}/{sequence}/{shot}")
                    return cached_result
                self.stats["cache_misses"] += 1

            # Step 3: Discover scenes using strategy
            with self.logger.context(
                operation="scene_discovery", shot=f"{show}/{sequence}/{shot}"
            ):
                scenes = self.strategy.find_scenes_for_shot(
                    shot_workspace_path, show, sequence, shot, excluded_users
                )

            # Step 4: Validate and filter results
            valid_scenes = self._validate_and_filter_scenes(scenes)

            # Step 5: Update cache (if enabled)
            if self.enable_caching and self.cache:
                self.cache.cache_scenes_for_shot(
                    show, sequence, shot, valid_scenes,
                    shot_workspace_path=shot_workspace_path,
                    excluded_users=frozen_excluded,
                )

            # Step 6: Update statistics and return results
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
                excluded_frozen = frozenset(excluded_users) if excluded_users else None
                for show in shows:
                    with self.logger.context(operation="show_discovery", show=show):
                        # Check cache first (if enabled)
                        if self.cache:
                            cached_result = self.cache.get_scenes_for_show(
                                show, show_root=show_root, excluded_users=excluded_frozen
                            )
                            if cached_result is not None:
                                self.stats["cache_hits"] += 1
                                self.logger.debug(f"Cache hit for show {show}")
                                all_scenes.extend(cached_result)
                                continue
                            self.stats["cache_misses"] += 1

                        # Discover scenes using strategy
                        show_scenes = self.strategy.find_all_scenes_in_show(
                            show_root, show, excluded_users
                        )

                        # Validate and filter results
                        valid_scenes = self._validate_and_filter_scenes(show_scenes)

                        # Update cache (if enabled)
                        if self.cache:
                            self.cache.cache_scenes_for_show(
                                show, valid_scenes,
                                show_root=show_root, excluded_users=excluded_frozen,
                            )

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

    def find_scenes_progressive(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
        batch_size: int = 10,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> Generator[tuple[list[ThreeDEScene], int, int, str], None, None]:
        """Progressive scene discovery with batch processing and progress updates.

        Args:
            show_root: Root path for shows
            show: Show name
            excluded_users: Set of usernames to exclude
            batch_size: Number of scenes per batch
            progress_callback: Optional callback for progress updates

        Yields:
            Tuple of (scene_batch, current_shot, total_shots, status_message)

        """
        try:
            # Use progressive strategy if available
            # Local application imports
            from scene_discovery_strategy import ProgressiveDiscoveryStrategy

            if not isinstance(self.strategy, ProgressiveDiscoveryStrategy):
                # Fallback: create progressive strategy temporarily
                progressive_strategy = ProgressiveDiscoveryStrategy()
                scene_generator = progressive_strategy.find_scenes_progressive(
                    show_root, show, excluded_users, batch_size
                )
            else:
                scene_generator = self.strategy.find_scenes_progressive(
                    show_root, show, excluded_users, batch_size
                )

            # Process batches and call progress callback if provided
            for scene_batch, current_shot, total_shots, status in scene_generator:
                # Validate scenes in batch
                valid_scenes = self._validate_and_filter_scenes(scene_batch)

                # Update statistics
                self.stats["scenes_discovered"] += len(valid_scenes)

                # Call progress callback if provided
                if progress_callback:
                    progress_callback(current_shot, total_shots, status)

                yield valid_scenes, current_shot, total_shots, status

        except Exception as e:
            self.stats["errors"] += 1
            self.logger.exception("Error in progressive scene discovery")
            yield [], 0, 0, f"Error: {e}"

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
        stats = self.stats.copy()

        # Add cache statistics if caching is enabled
        if self.enable_caching and self.cache:
            cache_stats = self.cache.get_cache_stats()
            cache_updates = {
                f"cache_{k}": int(v)
                for k, v in cache_stats.items()
                if k not in ["hit_rate_percent", "average_age_seconds"]
            }
            stats.update(cache_updates)

        return stats

    def clear_cache(self) -> int:
        """Clear all cached results.

        Returns:
            Number of entries cleared

        """
        if self.enable_caching and self.cache:
            return self.cache.clear_cache()
        return 0

    def invalidate_shot(
        self,
        show: str,
        sequence: str,
        shot: str,
        shot_workspace_path: str | None = None,
    ) -> bool:
        """Invalidate cached results for a specific shot.

        Returns:
            True if entry was invalidated, False if not found

        """
        if self.enable_caching and self.cache:
            return self.cache.invalidate_shot(
                show, sequence, shot, shot_workspace_path=shot_workspace_path
            )
        return False

    def invalidate_show(self, show: str) -> int:
        """Invalidate all cached results for a show.

        Returns:
            Number of entries invalidated

        """
        if self.enable_caching and self.cache:
            return self.cache.invalidate_show(show)
        return 0

    def switch_strategy(
        self, strategy_type: str, **strategy_kwargs: Unpack[StrategyKwargs]
    ) -> None:
        """Switch to a different discovery strategy.

        Args:
            strategy_type: New strategy type ("local", "progressive")
            **strategy_kwargs: Additional arguments for strategy initialization

        """
        # Lazy import to break circular dependency
        from scene_discovery_strategy import create_discovery_strategy

        old_strategy = self.strategy.get_strategy_name()
        self.strategy = create_discovery_strategy(strategy_type, **strategy_kwargs)
        self.logger.info(f"Switched strategy from {old_strategy} to {strategy_type}")

    def get_strategy_name(self) -> str:
        """Get the name of the current discovery strategy."""
        return self.strategy.get_strategy_name()

    @staticmethod
    def find_all_scenes_in_shows_truly_efficient(
        user_shots: list[Shot],
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes across shows using the local strategy."""
        coordinator = SceneDiscoveryCoordinator(
            strategy_type="local",
            enable_caching=True,
            cache_ttl=1800,
        )
        return coordinator.find_all_scenes_in_shows(user_shots, excluded_users)

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
    def _build_threede_scene(
        scene_path: object,
        show_name: str,
        seq: str,
        shot: str,
        user: str,
        plate: str,
        workspace_path: str,
    ) -> ThreeDEScene:
        """Construct a ThreeDEScene from raw file-tuple components.

        Args:
            scene_path: Path object for the .3de file.
            show_name: Show name extracted from the file path.
            seq: Sequence name extracted from the file path.
            shot: Shot name extracted from the file path.
            user: Owner username extracted from the file path.
            plate: Plate name extracted from the file path.
            workspace_path: Resolved workspace path for this shot.

        Returns:
            Populated ThreeDEScene instance.

        """
        # Standard library imports
        from pathlib import Path as _Path

        # Local application imports
        from frame_range_extractor import extract_frame_range
        from threede_scene_model import ThreeDEScene

        scene_path = _Path(scene_path) if not isinstance(scene_path, _Path) else scene_path  # type: ignore[arg-type]

        # Get file modification time for sorting (0.0 if unavailable)
        try:
            modified_time = scene_path.stat().st_mtime  # type: ignore[union-attr]
        except OSError:
            modified_time = 0.0

        # Extract frame range for scrub preview
        frame_range = extract_frame_range(workspace_path)
        frame_start = frame_range[0] if frame_range else None
        frame_end = frame_range[1] if frame_range else None

        return ThreeDEScene(
            show=show_name,
            sequence=seq,
            shot=shot,
            workspace_path=workspace_path,
            user=user,
            plate=plate,
            scene_path=scene_path,  # type: ignore[arg-type]
            modified_time=modified_time,
            frame_start=frame_start,
            frame_end=frame_end,
        )

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

            scene = SceneDiscoveryCoordinator._build_threede_scene(
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
