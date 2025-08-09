"""Shot data model and parser for ws -sg output."""

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Optional

if TYPE_CHECKING:
    from cache_manager import CacheManager

from config import Config
from utils import FileUtils, PathUtils, ValidationUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class RefreshResult(NamedTuple):
    """Result of shot refresh operation with success status and change detection.

    This NamedTuple provides type-safe results from ShotModel.refresh_shots() operations,
    allowing callers to determine both operation success and whether the shot list
    actually changed. This enables efficient UI updates that only occur when needed.

    Attributes:
        success (bool): Whether the refresh operation completed successfully.
            True indicates the workspace command executed without errors and
            the shot list was parsed. False indicates command failure, timeout,
            or parsing errors that prevented shot list updates.

        has_changes (bool): Whether the shot list changed compared to the previous
            refresh. True indicates new shots were added, existing shots were
            removed, or shot metadata changed. False indicates the shot list
            is identical to the previous state. Only meaningful when success=True.

    Examples:
        Basic usage with tuple unpacking:
            >>> result = shot_model.refresh_shots()
            >>> success, has_changes = result
            >>> if success and has_changes:
            ...     update_ui_with_new_shots()

        Explicit attribute access:
            >>> result = shot_model.refresh_shots()
            >>> if result.success:
            ...     logger.info(f"Refresh successful, changes: {result.has_changes}")
            ... else:
            ...     logger.error("Shot refresh failed")

        Conditional UI updates:
            >>> result = shot_model.refresh_shots()
            >>> if result.success and result.has_changes:
            ...     shot_grid.update_shots(shot_model.get_shots())
            ... elif result.success:
            ...     logger.debug("Shot list unchanged, skipping UI update")
            ... else:
            ...     show_error_dialog("Failed to refresh shots")

    Type Safety:
        This NamedTuple enforces type safety at runtime and provides IDE
        autocompletion. It replaces the previous tuple return type:

        Before: tuple[bool, bool]  # Unclear which bool means what
        After:  RefreshResult      # Self-documenting with named fields
    """

    success: bool
    has_changes: bool


@dataclass
class Shot:
    """Represents a single shot."""

    show: str
    sequence: str
    shot: str
    workspace_path: str

    @property
    def full_name(self) -> str:
        """Get full shot name."""
        return f"{self.sequence}_{self.shot}"

    @property
    def thumbnail_dir(self) -> Path:
        """Get thumbnail directory path."""
        return PathUtils.build_thumbnail_path(
            Config.SHOWS_ROOT, self.show, self.sequence, self.shot
        )

    def get_thumbnail_path(self) -> Optional[Path]:
        """Get first available thumbnail or None."""
        if not PathUtils.validate_path_exists(
            self.thumbnail_dir, "Thumbnail directory"
        ):
            return None

        # Use utility to find first image file
        return FileUtils.get_first_image_file(self.thumbnail_dir)

    def to_dict(self) -> Dict[str, str]:
        """Convert shot to dictionary for serialization."""
        return {
            "show": self.show,
            "sequence": self.sequence,
            "shot": self.shot,
            "workspace_path": self.workspace_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Shot":
        """Create shot from dictionary data."""
        return cls(
            show=data["show"],
            sequence=data["sequence"],
            shot=data["shot"],
            workspace_path=data["workspace_path"],
        )


class ShotModel:
    """Manages shot data and parsing."""

    def __init__(
        self, cache_manager: Optional["CacheManager"] = None, load_cache: bool = True
    ):
        from cache_manager import (
            CacheManager,  # Runtime import to avoid circular dependency
        )

        self.shots: List[Shot] = []
        self.cache_manager = cache_manager or CacheManager()
        self._parse_pattern = re.compile(
            r"workspace\s+(/shows/(\w+)/shots/(\w+)/(\w+))"
        )
        # Only load cache if requested (allows tests to start clean)
        if load_cache:
            self._load_from_cache()

    def _load_from_cache(self) -> bool:
        """Load shots from cache if available."""
        cached_data = self.cache_manager.get_cached_shots()
        if cached_data:
            self.shots = [Shot.from_dict(shot_data) for shot_data in cached_data]
            return True
        return False

    def refresh_shots(self) -> RefreshResult:
        """Fetch and parse shot list from ws -sg command.

        Returns:
            RefreshResult with success status and change indicator
        """
        try:
            # Save current shots for comparison (include workspace path)
            old_shot_data = {
                (shot.full_name, shot.workspace_path) for shot in self.shots
            }

            # Run ws -sg command in interactive bash shell to load functions
            result = subprocess.run(
                ["/bin/bash", "-i", "-c", "ws -sg"],
                capture_output=True,
                text=True,
                timeout=Config.WS_COMMAND_TIMEOUT_SECONDS,
                env=os.environ.copy(),
            )

            if result.returncode != 0:
                error_msg = (
                    f"ws -sg command failed with return code {result.returncode}"
                )
                if result.stderr:
                    error_msg += f": {result.stderr.strip()}"
                logger.error(error_msg)
                return RefreshResult(success=False, has_changes=False)

            # Parse output
            try:
                new_shots = self._parse_ws_output(result.stdout)
            except ValueError as e:
                logger.error(f"Failed to parse ws -sg output: {e}")
                return RefreshResult(success=False, has_changes=False)

            new_shot_data = {
                (shot.full_name, shot.workspace_path) for shot in new_shots
            }

            # Check if there are changes (added, removed, or path changed)
            has_changes = old_shot_data != new_shot_data

            if has_changes:
                self.shots = new_shots
                logger.info(f"Shot list updated: {len(new_shots)} shots found")

                # Cache the results - pass Shot objects directly
                if self.shots:
                    try:
                        self.cache_manager.cache_shots(self.shots)  # type: ignore[arg-type]
                    except (OSError, IOError) as e:
                        logger.warning(f"Failed to cache shots: {e}")
                        # Continue without caching - not critical for operation

            return RefreshResult(success=True, has_changes=has_changes)

        except subprocess.TimeoutExpired:
            logger.error("Timeout while running ws -sg command (>10 seconds)")
            return RefreshResult(success=False, has_changes=False)
        except FileNotFoundError as e:
            if "bash" in str(e):
                logger.error("bash shell not found - cannot execute ws command")
            else:
                logger.error("ws command not found in PATH")
            return RefreshResult(success=False, has_changes=False)
        except PermissionError as e:
            logger.error(f"Permission denied while executing ws command: {e}")
            return RefreshResult(success=False, has_changes=False)
        except subprocess.SubprocessError as e:
            logger.error(f"Subprocess error while running ws -sg: {e}")
            return RefreshResult(success=False, has_changes=False)
        except MemoryError:
            logger.error("Out of memory while processing shot list")
            return RefreshResult(success=False, has_changes=False)
        except Exception as e:
            logger.exception(f"Unexpected error while fetching shots: {e}")
            return RefreshResult(success=False, has_changes=False)

    def _parse_ws_output(self, output: str) -> List[Shot]:
        """Parse ws -sg output to extract shots.

        Args:
            output: Raw output from ws -sg command

        Returns:
            List of Shot objects parsed from the output

        Raises:
            ValueError: If output is invalid or cannot be parsed
        """
        if not isinstance(output, str):
            raise ValueError(f"Expected string output, got {type(output)}")

        shots: List[Shot] = []
        lines = output.strip().split("\n")

        # If output is completely empty, that might indicate an issue
        if not output.strip():
            logger.warning("ws -sg returned empty output")
            return shots

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            match = self._parse_pattern.search(line)
            if match:
                try:
                    workspace_path = match.group(1)
                    show = match.group(2)
                    sequence = match.group(3)
                    shot_name = match.group(4)

                    # Validate extracted components using utility
                    if not ValidationUtils.validate_not_empty(
                        workspace_path,
                        show,
                        sequence,
                        shot_name,
                        names=["workspace_path", "show", "sequence", "shot_name"],
                    ):
                        logger.warning(
                            f"Line {line_num}: Missing required components in: {line}"
                        )
                        continue

                    # Extract shot number from full name (e.g., "108_BQS_0005" -> "0005")
                    shot_parts = shot_name.split("_")
                    if len(shot_parts) >= 3:
                        shot = shot_parts[-1]
                    else:
                        shot = shot_name

                    shots.append(
                        Shot(
                            show=show,
                            sequence=sequence,
                            shot=shot,
                            workspace_path=workspace_path,
                        )
                    )
                except (IndexError, AttributeError) as e:
                    logger.warning(
                        f"Line {line_num}: Failed to parse shot data from: {line} ({e})"
                    )
                    continue
            else:
                # Log unmatched lines for debugging, but don't fail
                logger.debug(f"Line {line_num}: No match for workspace pattern: {line}")

        logger.info(f"Parsed {len(shots)} shots from ws -sg output")
        return shots

    def get_shot_by_index(self, index: int) -> Optional[Shot]:
        """Get shot by index."""
        if 0 <= index < len(self.shots):
            return self.shots[index]
        return None

    def find_shot_by_name(self, full_name: str) -> Optional[Shot]:
        """Find shot by full name."""
        for shot in self.shots:
            if shot.full_name == full_name:
                return shot
        return None
