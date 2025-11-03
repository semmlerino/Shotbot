"""Simplified mock system using Strategy pattern.

This refactoring reduces complexity by using a clear strategy pattern
for different mock data sources.
"""

from __future__ import annotations

# Standard library imports
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import cast

# Local application imports
from logging_mixin import LoggingMixin, get_module_logger


# Module-level logger for static methods
logger = get_module_logger(__name__)


class MockDataStrategy(ABC, LoggingMixin):
    """Abstract strategy for loading mock shot data."""

    @abstractmethod
    def load_shots(self) -> list[str]:
        """Load mock shot data.

        Returns:
            List of workspace command outputs
        """


class FilesystemMockStrategy(MockDataStrategy):
    """Load mock data from filesystem structure."""

    def __init__(self, mock_root: Path | None = None) -> None:
        """Initialize filesystem strategy.

        Args:
            mock_root: Root of mock VFX filesystem
        """
        super().__init__()
        self.mock_root = mock_root or Path("/tmp/mock_vfx")

    def load_shots(self) -> list[str]:
        """Scan mock filesystem for shots.

        Returns:
            List of workspace paths
        """
        shots: list[str] = []
        shows_dir = self.mock_root / "shows"

        if not shows_dir.exists():
            self.logger.warning(f"Shows directory not found: {shows_dir}")
            return shots

        # Scan shows/sequences/shots
        for show_dir in shows_dir.iterdir():
            if not show_dir.is_dir():
                continue

            shots_dir = show_dir / "shots"
            if not shots_dir.exists():
                continue

            for seq_dir in shots_dir.iterdir():
                if not seq_dir.is_dir():
                    continue

                for shot_dir in seq_dir.iterdir():
                    if not shot_dir.is_dir():
                        continue

                    # Validate shot naming pattern
                    if self._is_valid_shot(seq_dir.name, shot_dir.name):
                        workspace_path = f"/shows/{show_dir.name}/shots/{seq_dir.name}/{shot_dir.name}"
                        shots.append(f"workspace {workspace_path}")

        self.logger.info(f"Loaded {len(shots)} shots from filesystem")
        return shots

    @staticmethod
    def _is_valid_shot(sequence: str, shot_name: str) -> bool:
        """Check if directory name is a valid shot.

        Args:
            sequence: Sequence name
            shot_name: Shot directory name

        Returns:
            True if valid shot directory
        """
        # Must contain underscore and start with sequence
        if "_" not in shot_name:
            return False

        # Skip non-shot directories
        if shot_name in ("config", "tools", "resources"):
            return False

        # Should start with sequence prefix
        return shot_name.startswith(f"{sequence}_")


class JSONMockStrategy(MockDataStrategy):
    """Load mock data from JSON file."""

    def __init__(self, json_path: Path | str | None = None) -> None:
        """Initialize JSON strategy.

        Args:
            json_path: Path to JSON file with shot data
        """
        super().__init__()
        if json_path is None:
            json_path = Path(__file__).parent / "demo_shots.json"
        self.json_path = Path(json_path)

    def load_shots(self) -> list[str]:
        """Load shots from JSON file.

        Returns:
            List of workspace paths
        """
        if not self.json_path.exists():
            self.logger.warning(f"JSON file not found: {self.json_path}")
            return self._get_fallback_shots()

        try:
            with open(self.json_path) as f:
                # json.load returns Any - we validate with isinstance below
                data: object = json.load(f)  # pyright: ignore[reportAny]

            shots: list[str] = []
            # Type narrow: data should be dict with "shots" key
            if isinstance(data, dict):
                # Cast after isinstance check for type checker
                data_dict = cast("dict[str, object]", data)
                shot_list = data_dict.get("shots", [])
                if isinstance(shot_list, list):
                    # Cast list to typed list after isinstance check
                    shot_list_typed = cast("list[object]", shot_list)
                    for shot_item in shot_list_typed:
                        if isinstance(shot_item, dict):
                            # Cast dict items after isinstance checks
                            shot_dict = cast("dict[str, object]", shot_item)
                            show = shot_dict.get("show", "demo")
                            seq = shot_dict.get("seq", "seq01")
                            shot_num = shot_dict.get("shot", "0010")
                            # Type narrow: ensure string values
                            if (
                                isinstance(show, str)
                                and isinstance(seq, str)
                                and isinstance(shot_num, str)
                            ):
                                workspace_path = (
                                    f"/shows/{show}/shots/{seq}/{seq}_{shot_num}"
                                )
                                shots.append(f"workspace {workspace_path}")

            self.logger.info(f"Loaded {len(shots)} shots from JSON")
            return shots

        except Exception as e:
            self.logger.error(f"Error loading JSON: {e}")
            return self._get_fallback_shots()

    @staticmethod
    def _get_fallback_shots() -> list[str]:
        """Get minimal fallback shot data.

        Returns:
            List of demo workspace paths
        """
        return [
            "workspace /shows/demo/shots/seq01/seq01_0010",
            "workspace /shows/demo/shots/seq01/seq01_0020",
            "workspace /shows/demo/shots/seq01/seq01_0030",
        ]


class ProductionDataStrategy(MockDataStrategy):
    """Load real production data from captured JSON."""

    def __init__(self, capture_file: Path | str | None = None) -> None:
        """Initialize production data strategy.

        Args:
            capture_file: Path to captured VFX structure JSON
        """
        super().__init__()
        if capture_file is None:
            capture_file = Path(__file__).parent / "vfx_structure_complete.json"
        self.capture_file = Path(capture_file)

    def load_shots(self) -> list[str]:
        """Load shots from captured production structure.

        Returns:
            List of workspace paths matching production
        """
        if not self.capture_file.exists():
            self.logger.warning(f"Capture file not found: {self.capture_file}")
            return []

        try:
            with open(self.capture_file) as f:
                # json.load returns Any - we validate with isinstance below
                data: object = json.load(f)  # pyright: ignore[reportAny]

            shots: list[str] = []

            # Type narrow: data should be dict with "shows" key
            if isinstance(data, dict):
                # Cast after isinstance check for type checker
                data_dict = cast("dict[str, object]", data)
                shows_dict = data_dict.get("shows", {})
                if isinstance(shows_dict, dict):
                    # Cast nested dict
                    shows_typed = cast("dict[str, object]", shows_dict)
                    # Parse the captured structure
                    for show_name_key, show_data_val in shows_typed.items():
                        if isinstance(show_data_val, dict):
                            show_dict = cast("dict[str, object]", show_data_val)
                            shots_data = show_dict.get("shots", {})
                            if isinstance(shots_data, dict):
                                shots_typed = cast("dict[str, object]", shots_data)
                                for seq_name_key, seq_data_val in shots_typed.items():
                                    if isinstance(seq_data_val, dict):
                                        seq_dict = cast(
                                            "dict[str, object]", seq_data_val
                                        )
                                        # Each sequence has a shots list
                                        shot_list = seq_dict.get("shots", [])
                                        if isinstance(shot_list, list):
                                            # Cast list to typed list after isinstance check
                                            shot_list_typed = cast(
                                                "list[object]", shot_list
                                            )
                                            for shot_name_item in shot_list_typed:
                                                if isinstance(shot_name_item, str):
                                                    workspace_path = f"/shows/{show_name_key}/shots/{seq_name_key}/{shot_name_item}"
                                                    shots.append(
                                                        f"workspace {workspace_path}"
                                                    )

            self.logger.info(f"Loaded {len(shots)} production shots from capture")
            return shots

        except Exception as e:
            self.logger.error(f"Error loading capture file: {e}")
            return []


class UnifiedMockPool(LoggingMixin):
    """Unified mock pool using strategy pattern for data sources."""

    def __init__(self, strategy: MockDataStrategy | None = None) -> None:
        """Initialize mock pool with data loading strategy.

        Args:
            strategy: Data loading strategy (auto-detect if None)
        """
        super().__init__()
        self.strategy = strategy or self._auto_detect_strategy()
        self.shots = self.strategy.load_shots()
        self._cache: dict[str, str] = {}
        self.commands_executed: list[str] = []

        self.logger.info(

                f"UnifiedMockPool initialized with {len(self.shots)} shots "
                f"using {self.strategy.__class__.__name__}"

        )

    @staticmethod
    def _auto_detect_strategy() -> MockDataStrategy:
        """Auto-detect the best available strategy.

        Returns:
            Most appropriate mock data strategy
        """
        # Priority order:
        # 1. Filesystem mock if exists
        # 2. Production capture if exists
        # 3. Demo JSON
        # 4. Fallback demo data

        filesystem_root = Path("/tmp/mock_vfx")
        if filesystem_root.exists():
            logger.info("Using filesystem mock strategy")
            return FilesystemMockStrategy(filesystem_root)

        capture_file = Path(__file__).parent / "vfx_structure_complete.json"
        if capture_file.exists():
            logger.info("Using production data strategy")
            return ProductionDataStrategy(capture_file)

        demo_file = Path(__file__).parent / "demo_shots.json"
        if demo_file.exists():
            logger.info("Using JSON demo strategy")
            return JSONMockStrategy(demo_file)

        logger.info("Using JSON strategy with fallback data")
        return JSONMockStrategy()  # Will use fallback

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        _timeout: int | None = None,
    ) -> str:
        """Execute workspace command.

        Args:
            command: Command to execute
            cache_ttl: Cache time-to-live
            timeout: Timeout in seconds

        Returns:
            Command output
        """
        self.commands_executed.append(command)

        # Check cache
        if command in self._cache:
            return self._cache[command]

        result = ""

        if command == "ws -sg":
            # Return all shots
            result = "\n".join(self.shots)
        elif command.startswith("echo"):
            # Warming command
            result = command.replace("echo ", "")
        else:
            # Default response
            result = f"Mock output for: {command}"

        # Cache if requested
        if cache_ttl > 0:
            self._cache[command] = result

        return result

    def batch_execute(
        self,
        commands: list[str],
        cache_ttl: int = 30,
        _session_type: str = "workspace",  # type: ignore[reportUnusedParameter]
    ) -> dict[str, str | None]:
        """Execute multiple commands.

        Args:
            commands: List of commands
            cache_ttl: Cache TTL
            session_type: Session type

        Returns:
            Command outputs
        """
        results: dict[str, str | None] = {}
        for command in commands:
            try:
                results[command] = self.execute_workspace_command(command, cache_ttl)
            except Exception as e:
                self.logger.error(f"Error executing {command}: {e}")
                results[command] = None

        return results

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            pattern: Pattern to match (None = clear all)
        """
        if pattern is None:
            self._cache.clear()
        else:
            to_remove = [k for k in self._cache if pattern in k]
            for key in to_remove:
                del self._cache[key]

    def shutdown(self) -> None:
        """Shutdown the pool."""
        self._cache.clear()
        self.logger.info("UnifiedMockPool shutdown complete")


def create_mock_pool(mode: str = "auto") -> UnifiedMockPool:
    """Factory function to create mock pool with specific mode.

    Args:
        mode: "filesystem", "json", "production", or "auto"

    Returns:
        Configured mock pool
    """
    strategies = {
        "filesystem": FilesystemMockStrategy,
        "json": JSONMockStrategy,
        "production": ProductionDataStrategy,
    }

    if mode == "auto":
        return UnifiedMockPool()  # Auto-detect

    strategy_class = strategies.get(mode)
    if strategy_class:
        return UnifiedMockPool(strategy_class())

    raise ValueError(f"Unknown mode: {mode}. Use: {list(strategies.keys())}")
