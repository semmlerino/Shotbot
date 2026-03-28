#!/usr/bin/env python3
"""Enhanced mock ProcessPool that properly simulates workspace commands.

This module provides a more realistic mock that returns all shots at once,
just like the real 'ws -sg' command would.
"""

from __future__ import annotations

import logging

# Standard library imports
from pathlib import Path
from typing import cast


logger = logging.getLogger(__name__)


# Local application imports


class MockWorkspacePool:
    """Mock ProcessPool that simulates real workspace commands."""

    def __init__(self, demo_shots_path: Path | None = None) -> None:
        """Initialize mock workspace pool.

        Args:
            demo_shots_path: Optional path to demo_shots.json for testing (default: ./demo_shots.json)

        """
        super().__init__()
        self.shots: list[str] = []
        self._cache: dict[str, str] = {}
        self.commands_executed: list[str] = []
        self.mock_root: Path = Path("/tmp/mock_vfx")
        # Use Config.SHOWS_ROOT for workspace paths (what parser expects)
        # Local application imports
        from config import (
            Config,
        )

        self.shows_root_for_parser: str = Config.SHOWS_ROOT
        # Actual filesystem location for file operations
        self.shows_root: Path = self.mock_root / "shows"
        # Demo shots path for testing flexibility
        self.demo_shots_path: Path = demo_shots_path or (
            Path(__file__).parent / "demo_shots.json"
        )

    def set_shots_from_filesystem(self, mock_root: Path | None = None) -> None:
        """Scan the mock filesystem and set up all available shots.

        Args:
            mock_root: Root of mock VFX filesystem (default: /tmp/mock_vfx)

        """
        if mock_root is not None:
            self.mock_root = mock_root
            self.shows_root = mock_root / "shows"

        self.shots = []
        shows_dir = self.shows_root

        if not shows_dir.exists():
            logger.warning(f"Shows directory not found: {shows_dir}")
            return

        # Scan each show
        for show_dir in shows_dir.iterdir():
            if not show_dir.is_dir():
                continue

            show_name = show_dir.name
            shots_dir = show_dir / "shots"

            if not shots_dir.exists():
                continue

            # Scan each sequence
            for seq_dir in shots_dir.iterdir():
                if not seq_dir.is_dir():
                    continue

                seq_name = seq_dir.name

                # Scan each shot
                for shot_dir in seq_dir.iterdir():
                    if not shot_dir.is_dir():
                        continue

                    shot_name = shot_dir.name

                    # Skip non-shot directories (config, tools, etc.)
                    # Shot directories follow pattern: SEQUENCE_SHOTNUMBER
                    # e.g., "BRX_118_0010", "012_DC_1000"
                    if "_" not in shot_name or shot_name in ("config", "tools"):
                        continue

                    # Verify it looks like a shot (has sequence prefix)
                    if not shot_name.startswith(f"{seq_name}_"):
                        continue

                    # Build workspace path using Config.SHOWS_ROOT (what parser expects)
                    workspace_path = f"{self.shows_root_for_parser}/{show_name}/shots/{seq_name}/{shot_name}"
                    self.shots.append(f"workspace {workspace_path}")

        logger.info(f"Loaded {len(self.shots)} shots from mock filesystem")

    def set_shots_from_demo(self, demo_shots: list[dict[str, str]]) -> None:
        """Set shots from demo data.

        Args:
            demo_shots: List of shot dictionaries with show/seq/shot keys

        """
        self.shots = []
        for shot in demo_shots:
            show = shot.get("show", "demo")
            seq = shot.get("seq", "seq01")
            shot_num = shot.get("shot", "0010")
            # Use Config.SHOWS_ROOT for workspace paths (what parser expects)
            workspace_path = (
                f"{self.shows_root_for_parser}/{show}/shots/{seq}/{seq}_{shot_num}"
            )
            self.shots.append(f"workspace {workspace_path}")

        logger.info(f"Loaded {len(self.shots)} demo shots")

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        timeout: int | None = None,  # pyright: ignore[reportUnusedParameter]
        use_login_shell: bool = False,  # pyright: ignore[reportUnusedParameter]
        cancel_flag: object = None,  # pyright: ignore[reportUnusedParameter]
    ) -> str:
        """Execute workspace command.

        For 'ws -sg', returns all shots joined with newlines,
        just like the real command would.

        Args:
            command: Command to execute
            cache_ttl: Cache time-to-live
            timeout: Timeout in seconds
            use_login_shell: Ignored for mock (always compatible)

        Returns:
            Command output

        """
        # Preserve signature compatibility with ProcessPoolManager.
        _ = timeout, use_login_shell
        self.commands_executed.append(command)

        # Check cache first
        if command in self._cache:
            return self._cache[command]

        result = ""

        if command == "ws -sg":
            # Return all shots joined with newlines
            result = "\n".join(self.shots)
        elif command.startswith("echo"):
            # For warming commands
            result = command.replace("echo ", "")
        else:
            # Default response
            result = f"Mock output for: {command}"

        # Cache result
        if cache_ttl > 0:
            self._cache[command] = result

        return result

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            pattern: Pattern to match (clears all if None)

        """
        if pattern is None:
            self._cache.clear()
        else:
            keys_to_remove = [k for k in self._cache if pattern in k]
            for key in keys_to_remove:
                del self._cache[key]

    def shutdown(self) -> None:
        """Shutdown the pool (no-op for mock)."""


def create_mock_pool_from_filesystem(
    demo_shots_path: Path | None = None,
) -> MockWorkspacePool:
    """Create a mock pool that simulates user-assigned shots only.

    In a real VFX environment, 'ws -sg' only returns shots assigned to the
    current user, not all shots in the facility. We simulate this by using
    the curated demo shots that represent a realistic user workload.

    Args:
        demo_shots_path: Optional path to demo_shots.json for testing (default: ./demo_shots.json)

    Returns:
        MockWorkspacePool configured with user's assigned shots only

    """
    # Standard library imports
    import json
    import logging

    logger = logging.getLogger(__name__)
    pool = MockWorkspacePool(demo_shots_path=demo_shots_path)

    # Use demo shots first (realistic user assignment of ~12 shots)
    if pool.demo_shots_path.exists():
        logger.info("Loading demo shots for user-assigned simulation")
        try:
            with pool.demo_shots_path.open(encoding="utf-8") as f:
                # json.load() returns Any - cast to object for type safety
                raw_data = cast("object", json.load(f))

            # Runtime validation before casting
            if not isinstance(raw_data, dict):
                msg = f"Expected dict, got {type(raw_data).__name__}"
                raise ValueError(msg)

            # After isinstance check, cast to expected structure
            demo_data = cast("dict[str, object]", raw_data)

            if "shots" not in demo_data:
                msg = "Missing 'shots' key in demo data"
                raise ValueError(msg)

            raw_shots = demo_data["shots"]
            if not isinstance(raw_shots, list):
                msg = f"'shots' must be a list, got {type(raw_shots).__name__}"
                raise ValueError(msg)

            # After isinstance check, cast to list of objects
            shots_data = cast("list[object]", raw_shots)

            # Validate each shot has required fields - builds typed list
            validated_shots: list[dict[str, str]] = []
            for i, shot_item in enumerate(shots_data):
                if not isinstance(shot_item, dict):
                    msg = f"Shot {i} is not a dict"
                    raise ValueError(msg)
                # Cast after runtime validation
                shot_dict = cast("dict[str, object]", shot_item)
                required_fields = ["show", "seq", "shot"]
                missing = [f for f in required_fields if f not in shot_dict]
                if missing:
                    msg = f"Shot {i} missing fields: {missing}"
                    raise ValueError(msg)
                # After validation, cast to typed dict
                validated_shots.append(cast("dict[str, str]", shot_dict))

            # Assign only a subset of shots to gabriel-h to simulate realistic user workload
            # while still allowing "Other 3DE Scenes" to find many unassigned 3DE files
            assigned_shots: list[dict[str, str]] = validated_shots[
                :4
            ]  # Take first 4 shots for gabriel-h
            logger.info(
                f"Assigning {len(assigned_shots)} of {len(validated_shots)} demo shots to gabriel-h"
            )

            pool.set_shots_from_demo(assigned_shots)
            if pool.shots:
                logger.info(f"✅ Gabriel-h assigned to {len(pool.shots)} shots:")
                for shot_path in pool.shots:
                    logger.info(f"   📋 {shot_path}")
                logger.info(
                    f"🎯 This leaves {len(validated_shots) - len(assigned_shots)} shots unassigned for 'Other 3DE Scenes'"
                )
                return pool
            logger.warning("Demo shots loaded but pool is empty")

        except json.JSONDecodeError:
            logger.exception("Invalid JSON in demo_shots.json")
        except OSError:
            logger.exception("Failed to read demo_shots.json")
        except ValueError:
            logger.exception("Invalid demo shots structure")
        except Exception:
            logger.exception("Unexpected error loading demo shots")

    # Do NOT fall back to filesystem - this was causing ALL shots to be
    # considered assigned to gabriel-h, which filtered out all "Other 3DE Scenes"
    logger.error("Demo shots are required for realistic mock environment")
    logger.error("Without demo_shots.json, mock will have no assigned shots")
    logger.error(
        "This ensures 'Other 3DE Scenes' can find 3DE files from non-assigned shots"
    )

    return pool


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    # Create pool from filesystem
    pool = create_mock_pool_from_filesystem()

    # Test ws -sg command
    output = pool.execute_workspace_command("ws -sg")
    shots = output.split("\n")

    print(f"Found {len(shots)} shots:")
    for i, shot in enumerate(shots[:10], 1):  # Show first 10
        print(f"  {i}. {shot}")

    if len(shots) > 10:
        print(f"  ... and {len(shots) - 10} more")
