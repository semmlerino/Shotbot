"""Path construction utilities for VFX pipeline.

This module provides utilities for building file and directory paths
according to VFX pipeline conventions.
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Local application imports
from config import Config
from logging_mixin import get_module_logger


logger = get_module_logger(__name__)


class PathBuilders:
    """Utilities for constructing VFX pipeline paths."""

    @staticmethod
    def build_path(base_path: str | Path, *segments: str) -> Path:
        """Build a path from base path and segments.

        Args:
            base_path: Base path to start from
            *segments: Path segments to append

        Returns:
            Constructed Path object

        """
        if not base_path:
            msg = "Base path cannot be empty"
            raise ValueError(msg)

        path = Path(base_path)
        for segment in segments:
            if not segment:
                logger.warning(f"Empty segment in path construction from {base_path}")
                continue
            path = path / segment
        return path

    @staticmethod
    def build_thumbnail_path(
        shows_root: str,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path:
        """Build thumbnail directory path.

        Args:
            shows_root: Root shows directory
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to thumbnail directory

        """
        # VFX convention: shot directory is named {sequence}_{shot}
        shot_dir = f"{sequence}_{shot}"
        return PathBuilders.build_path(
            shows_root,
            show,
            "shots",
            sequence,
            shot_dir,
            *Config.THUMBNAIL_SEGMENTS,
        )

    @staticmethod
    def build_raw_plate_path(workspace_path: str) -> Path:
        """Build raw plate base path.

        Args:
            workspace_path: Shot workspace path

        Returns:
            Path to raw plate directory

        """
        return PathBuilders.build_path(workspace_path, *Config.RAW_PLATE_SEGMENTS)

