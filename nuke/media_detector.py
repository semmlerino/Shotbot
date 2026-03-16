"""Detection utilities for media properties in Nuke scripts.

This module provides functions to analyze file paths and detect appropriate
settings for frame ranges, colorspaces, and resolutions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path


logger = logging.getLogger(__name__)


class NukeMediaDetector:
    """Detection utilities for media properties."""

    @staticmethod
    def detect_frame_range(plate_path: str) -> tuple[int, int]:
        """Detect actual frame range from plate files.

        Args:
            plate_path: Path to plate sequence (with #### or %04d pattern)

        Returns:
            Tuple of (first_frame, last_frame), defaults to (1001, 1100)

        """
        if not plate_path:
            return 1001, 1100  # Default VFX range

        try:
            plate_dir = Path(plate_path).parent
            if not plate_dir.exists():
                return 1001, 1100

            # Build pattern for frame detection
            base_name = Path(plate_path).name
            # Replace #### or %04d with regex pattern
            pattern = base_name.replace("####", r"(\d{4})").replace("%04d", r"(\d{4})")
            frame_regex = re.compile(pattern)

            frame_numbers: list[int] = []
            for file in plate_dir.iterdir():
                match = frame_regex.match(file.name)
                if match:
                    frame_numbers.append(int(match.group(1)))

            if frame_numbers:
                return min(frame_numbers), max(frame_numbers)

            # No frames found - log and return defaults
            logger.debug(
                f"No frame files found matching pattern in {plate_dir}, using default range"
            )

        except Exception as e:  # noqa: BLE001
            # Log the error so users know frame range may be incorrect
            logger.warning(
                f"Error detecting frame range for {plate_path}: {e}. "
                "Using default range (1001-1100)"
            )

        return 1001, 1100

    @staticmethod
    def detect_colorspace(plate_path: str) -> tuple[str, bool]:
        """Detect colorspace and raw flag from filename or path.

        Args:
            plate_path: Path to the plate file

        Returns:
            Tuple of (colorspace_name, raw_flag)
            - For linear plates: ("linear", True)
            - For other plates: (colorspace_name, False)

        """
        if not plate_path:
            return "linear", True  # Default to linear raw

        path_lower = plate_path.lower()

        # Linear plates (use raw=true with colorspace="linear")
        if "lin_" in path_lower or "linear" in path_lower:
            return "linear", True

        # Log plates (use raw=false with appropriate colorspace)
        if "logc" in path_lower or "alexa" in path_lower:
            return "logc3ei800", False
        if "log" in path_lower:
            return "log", False

        # Display-referred colorspaces
        if "rec709" in path_lower:
            return "rec709", False
        if "srgb" in path_lower:
            return "sRGB", False

        # Default to linear raw (safest for VFX plates)
        return "linear", True

    @staticmethod
    def detect_resolution(plate_path: str) -> tuple[int, int]:
        """Detect resolution from path.

        Args:
            plate_path: Path to the plate file

        Returns:
            Tuple of (width, height), defaults to (4312, 2304)

        """
        if not plate_path:
            return 4312, 2304  # Default production resolution

        # Look for patterns like 4312x2304 or 1920x1080
        resolution_pattern = re.compile(r"(\d{3,4})[x_](\d{3,4})")
        match = resolution_pattern.search(plate_path)

        if match:
            try:
                width = int(match.group(1))
                height = int(match.group(2))
                # Sanity check
                if 640 <= width <= 8192 and 480 <= height <= 4320:
                    return width, height
            except (ValueError, AttributeError):
                pass

        return 4312, 2304

    @staticmethod
    def detect_media_properties(plate_path: str) -> dict[str, int | str | bool]:
        """Detect all media properties at once.

        Args:
            plate_path: Path to the plate file

        Returns:
            Dictionary containing detected properties:
            - first_frame: int
            - last_frame: int
            - width: int
            - height: int
            - colorspace: str
            - raw_flag: bool

        """
        first_frame, last_frame = NukeMediaDetector.detect_frame_range(plate_path)
        width, height = NukeMediaDetector.detect_resolution(plate_path)
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace(plate_path)

        return {
            "first_frame": first_frame,
            "last_frame": last_frame,
            "width": width,
            "height": height,
            "colorspace": colorspace,
            "raw_flag": raw_flag,
        }

    @staticmethod
    def sanitize_shot_name(shot_name: str) -> str:
        """Sanitize shot name to prevent path traversal and ensure valid naming.

        Args:
            shot_name: Raw shot name

        Returns:
            Sanitized shot name safe for file paths and Nuke node names

        """
        return re.sub(r"[^\w\-_]", "_", shot_name)
