"""SceneDiscoveryStrategy module - Strategy pattern for different scene discovery approaches

This module defines the interface and implementations for different scene discovery
strategies (local, network, parallel, etc.) providing flexibility and extensibility
for various VFX pipeline requirements.

Part of the Phase 2 refactoring to break down the monolithic scene finder.
"""

from __future__ import annotations

# Standard library imports
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict, Unpack, final

# Local application imports
from logging_mixin import LoggingMixin
from typing_compat import override


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator
    from pathlib import Path

    # Local application imports
    # Note: FileSystemScanner, SceneCache, SceneParser imported lazily in __init__
    from filesystem_scanner import FileSystemScanner
    from scene_cache import SceneCache
    from scene_parser import SceneParser
    from threede_scene_model import ThreeDEScene


class SceneDiscoveryStrategy(ABC, LoggingMixin):
    """Abstract base class for scene discovery strategies.

    This defines the interface that all discovery strategies must implement,
    allowing different approaches (local, network, parallel) to be used
    interchangeably.
    """

    # Type annotations for lazy-loaded attributes
    scanner: FileSystemScanner
    parser: SceneParser
    cache: SceneCache

    def __init__(self) -> None:
        """Initialize base strategy."""
        super().__init__()

        # Lazy imports to break circular dependencies
        # Cycle: scene_cache → threede_scene_model → threede_scene_finder →
        # threede_scene_finder_optimized → scene_discovery_coordinator → scene_discovery_strategy → scene_cache
        from filesystem_scanner import (
            FileSystemScanner,
        )
        from scene_cache import SceneCache
        from scene_parser import (
            SceneParser,
        )

        self.scanner = FileSystemScanner()
        self.parser = SceneParser()
        self.cache = SceneCache()

    @abstractmethod
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes for a specific shot.

        Args:
            shot_workspace_path: Path to shot workspace
            show: Show name
            sequence: Sequence name
            shot: Shot name
            excluded_users: Set of usernames to exclude

        Returns:
            List of ThreeDEScene objects

        """

    @abstractmethod
    def find_all_scenes_in_show(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in a show.

        Args:
            show_root: Root path for shows
            show: Show name
            excluded_users: Set of usernames to exclude

        Returns:
            List of all ThreeDEScene objects in the show

        """

    def get_strategy_name(self) -> str:
        """Get the name of this strategy."""
        return self.__class__.__name__


@final
class LocalFileSystemStrategy(SceneDiscoveryStrategy):
    """Local filesystem-based scene discovery strategy.

    Uses direct filesystem access with optimized scanning and caching.
    This is the default strategy for most VFX environments.
    """

    @override
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for a shot using local filesystem scanning."""
        # Check cache first
        cached_scenes = self.cache.get_scenes_for_shot(show, sequence, shot)
        if cached_scenes is not None:
            self.logger.debug(f"Using cached scenes for {show}/{sequence}/{shot}")
            return cached_scenes

        scenes: list[ThreeDEScene] = []

        try:
            # Standard library imports
            from pathlib import Path

            # Local application imports
            from utils import ValidationUtils

            # Input validation
            if not ValidationUtils.validate_shot_components(show, sequence, shot):
                self.logger.warning("Invalid shot components provided")
                return []

            if not shot_workspace_path:
                self.logger.warning("Empty shot workspace path provided")
                return []

            if excluded_users is None:
                excluded_users = ValidationUtils.get_excluded_users()

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

                    except Exception as e:
                        self.logger.warning(f"Error processing {threede_file}: {e}")
                        continue

            # Also scan publish directory
            publish_dir = shot_path / "publish"
            if publish_dir.exists():
                self.logger.debug(f"Scanning publish directory: {publish_dir}")
                publish_scenes = self._scan_publish_directory(
                    publish_dir, show, sequence, shot, shot_workspace_path
                )
                scenes.extend(publish_scenes)

            # Cache the results
            self.cache.cache_scenes_for_shot(show, sequence, shot, scenes)

            self.logger.info(
                f"Found {len(scenes)} total scenes for {show}/{sequence}/{shot}"
            )

        except Exception as e:
            self.logger.error(f"Error finding scenes for {show}/{sequence}/{shot}: {e}")

        return scenes

    @override
    def find_all_scenes_in_show(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in a show using local filesystem scanning."""
        # Check cache first
        cached_scenes = self.cache.get_scenes_for_show(show)
        if cached_scenes is not None:
            self.logger.debug(f"Using cached scenes for show {show}")
            return cached_scenes

        scenes: list[ThreeDEScene] = []

        try:
            # Standard library imports
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

            # Cache the results
            self.cache.cache_scenes_for_show(show, scenes)

            self.logger.info(f"Found {len(scenes)} total scenes in show {show}")

        except Exception as e:
            self.logger.error(f"Error finding scenes in show {show}: {e}")

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
        # Local application imports

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

                except Exception as e:
                    self.logger.debug(
                        f"Error processing published file {threede_file}: {e}"
                    )
                    continue

        except Exception as e:
            self.logger.debug(f"Error scanning publish directory: {e}")

        return scenes


@final
class ParallelFileSystemStrategy(SceneDiscoveryStrategy):
    """Parallel filesystem-based scene discovery strategy.

    Uses multi-threaded scanning for improved performance on large shows.
    Provides progress callbacks and cancellation support.
    """

    num_workers: int | None

    def __init__(self, num_workers: int | None = None) -> None:
        """Initialize parallel strategy.

        Args:
            num_workers: Number of parallel workers (uses config default if None)

        """
        super().__init__()
        self.num_workers = num_workers

    @override
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for a shot (delegates to local strategy for single shots)."""
        # For single shots, parallel processing doesn't provide much benefit
        # Delegate to local strategy
        local_strategy = LocalFileSystemStrategy()
        return local_strategy.find_scenes_for_shot(
            shot_workspace_path, show, sequence, shot, excluded_users
        )

    @override
    def find_all_scenes_in_show(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in a show using parallel scanning."""
        # Check cache first
        cached_scenes = self.cache.get_scenes_for_show(show)
        if cached_scenes is not None:
            self.logger.debug(f"Using cached scenes for show {show}")
            return cached_scenes

        scenes: list[ThreeDEScene] = []

        try:
            # Standard library imports
            from pathlib import Path

            show_path = Path(show_root) / show
            if not show_path.exists():
                self.logger.warning(f"Show path does not exist: {show_path}")
                return []

            # Use parallel search for efficiency - for now delegate to targeted search
            # TODO: Implement parallel version in filesystem_scanner
            file_results = self.scanner.find_all_3de_files_in_show_targeted(
                show_root, show, excluded_users
            )

            self.logger.info(
                f"Found {len(file_results)} .3de files in {show} (parallel)"
            )

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

            # Cache the results
            self.cache.cache_scenes_for_show(show, scenes)

            self.logger.info(
                f"Found {len(scenes)} total scenes in show {show} (parallel)"
            )

        except Exception as e:
            self.logger.error(f"Error finding scenes in show {show} (parallel): {e}")

        return scenes


@final
class ProgressiveDiscoveryStrategy(SceneDiscoveryStrategy):
    """Progressive scene discovery strategy with batch processing and callbacks.

    Provides incremental results and progress updates, suitable for UI applications
    that need to show progress and allow cancellation.
    """

    @override
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for a shot (delegates to local strategy for single shots)."""
        # For single shots, progressive discovery isn't needed
        local_strategy = LocalFileSystemStrategy()
        return local_strategy.find_scenes_for_shot(
            shot_workspace_path, show, sequence, shot, excluded_users
        )

    @override
    def find_all_scenes_in_show(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in show using progressive discovery."""
        # This implementation returns all scenes at once
        # For true progressive discovery, use find_scenes_progressive method
        # Local application imports

        scenes: list[ThreeDEScene] = []

        for (
            scene_batch,
            _current_shot,
            _total_shots,
            _status,
        ) in self.find_scenes_progressive(show_root, show, excluded_users):
            scenes.extend(scene_batch)

        return scenes

    def find_scenes_progressive(
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
                # Convert file pairs to ThreeDEScene objects
                # Local application imports

                scenes: list[ThreeDEScene] = []
                for _username, threede_file in file_batch:
                    try:
                        # Extract shot info from the file path
                        # Standard library imports
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

                    except Exception as e:
                        self.logger.warning(
                            f"Error processing scene file {threede_file}: {e}"
                        )
                        continue

                yield scenes, current_shot, total_shots, status

        except Exception as e:
            self.logger.error(f"Error in progressive discovery for {show}: {e}")
            yield [], 0, 0, f"Error: {e}"


@final
class NetworkAwareStrategy(SceneDiscoveryStrategy):
    """Network-aware scene discovery strategy.

    This strategy can handle network-mounted filesystems and provides
    appropriate timeouts and retry logic for network operations.
    """

    network_timeout: int

    def __init__(self, network_timeout: int = 30) -> None:
        """Initialize network-aware strategy.

        Args:
            network_timeout: Timeout for network operations in seconds

        """
        super().__init__()
        self.network_timeout = network_timeout

    @override
    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for a shot with network awareness."""
        # For now, delegate to local strategy
        # In the future, this could include network-specific optimizations
        local_strategy = LocalFileSystemStrategy()
        return local_strategy.find_scenes_for_shot(
            shot_workspace_path, show, sequence, shot, excluded_users
        )

    @override
    def find_all_scenes_in_show(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in show with network awareness."""
        # For now, delegate to local strategy
        # In the future, this could include network-specific optimizations
        local_strategy = LocalFileSystemStrategy()
        return local_strategy.find_all_scenes_in_show(show_root, show, excluded_users)


class StrategyKwargs(TypedDict, total=False):
    """Type-safe kwargs for strategy creation.

    Attributes:
        num_workers: Number of parallel workers (for ParallelFileSystemStrategy)
        network_timeout: Timeout for network operations in seconds (for NetworkAwareStrategy)

    """

    num_workers: int | None
    network_timeout: int


# Factory function for creating strategies
def create_discovery_strategy(
    strategy_type: str = "local", **kwargs: Unpack[StrategyKwargs]
) -> SceneDiscoveryStrategy:
    """Create a scene discovery strategy.

    Args:
        strategy_type: Type of strategy ("local", "parallel", "progressive", "network")
        **kwargs: Additional arguments for strategy initialization (see StrategyKwargs)
            - num_workers: Number of parallel workers (for "parallel")
            - network_timeout: Timeout for network operations (for "network")

    Returns:
        SceneDiscoveryStrategy instance

    Raises:
        ValueError: If strategy_type is not recognized

    """
    # Create strategy based on type with appropriate kwargs
    if strategy_type == "local":
        return LocalFileSystemStrategy()
    if strategy_type == "parallel":
        num_workers = kwargs.get("num_workers")
        return ParallelFileSystemStrategy(num_workers=num_workers)
    if strategy_type == "progressive":
        return ProgressiveDiscoveryStrategy()
    if strategy_type == "network":
        network_timeout = kwargs.get("network_timeout", 30)
        return NetworkAwareStrategy(network_timeout=network_timeout)
    msg = (
        f"Unknown strategy type: {strategy_type}. "
         f"Available: local, parallel, progressive, network"
    )
    raise ValueError(
        msg
    )
