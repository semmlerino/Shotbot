"""Utility for finding raw plate files for shots."""

import logging
import re
from pathlib import Path
from typing import Optional

from config import Config
from performance_monitor import timed_operation
from utils import PathUtils, VersionUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class RawPlateFinder:
    """Finds the latest raw plate file for a shot."""

    # Pre-compiled regex patterns for performance (compiled once at class level)
    # Pattern 1: {shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.####.exr
    # Pattern 2: {shot_name}_turnover-plate_{plate_name}{color_space}_{version}.####.exr
    # These will be compiled dynamically in _get_plate_patterns() method
    _pattern_cache = {}  # Cache for compiled patterns keyed by (shot_name, plate_name, version)

    @staticmethod
    @timed_operation("find_latest_raw_plate", log_threshold_ms=50)
    def find_latest_raw_plate(
        shot_workspace_path: str, shot_name: str
    ) -> Optional[str]:
        """
        Find the latest raw plate file path for a shot.

        Args:
            shot_workspace_path: The shot's workspace path (e.g., /shows/ygsk/shots/108_CHV/108_CHV_0015)
            shot_name: The shot name (e.g., 108_CHV_0015)

        Returns:
            Path to the latest raw plate with #### for frame numbers, or None if not found
        """
        # Build base path for raw plate files (without plate name)
        base_path = PathUtils.build_raw_plate_path(shot_workspace_path)

        if not PathUtils.validate_path_exists(base_path, "Raw plate base path"):
            return None

        # Discover available plate directories (FG01, BG01, bg01, etc.)
        plate_dirs = PathUtils.discover_plate_directories(base_path)
        if not plate_dirs:
            logger.debug(f"No plate directories found in {base_path}")
            return None

        # Try each plate directory in priority order
        for plate_name, _ in plate_dirs:
            plate_path = base_path / plate_name

            # Find the latest version directory
            latest_version = VersionUtils.get_latest_version(plate_path)
            if not latest_version:
                continue

            # Check for EXR directory
            exr_base = plate_path / latest_version / "exr"
            if not exr_base.exists():
                continue

            # Find resolution directory (e.g., 4312x2304)
            resolution_dirs = [
                d for d in exr_base.iterdir() if d.is_dir() and "x" in d.name
            ]
            if not resolution_dirs:
                continue

            # Use the first resolution directory found
            resolution_dir = resolution_dirs[0]

            # Try to find an actual plate file to determine the color space
            plate_file = RawPlateFinder._find_plate_file_pattern(
                resolution_dir, shot_name, plate_name, latest_version
            )

            if plate_file:
                return plate_file

        logger.debug(f"No valid plate files found for shot {shot_name}")
        return None

    @staticmethod
    def _get_plate_patterns(shot_name: str, plate_name: str, version: str):
        """Get or create compiled regex patterns for plate matching.

        Uses caching to avoid recompiling the same patterns.

        Args:
            shot_name: Shot name
            plate_name: Plate name (FG01, BG01, etc.)
            version: Version string (v001, etc.)

        Returns:
            Tuple of (pattern1, pattern2) compiled regex objects
        """
        cache_key = (shot_name, plate_name, version)

        if cache_key not in RawPlateFinder._pattern_cache:
            # Pattern 1: {shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.####.exr
            pattern1_str = rf"{shot_name}_turnover-plate_{plate_name}_([^_]+)_{version}\.\d{{4}}\.exr"
            pattern1 = re.compile(pattern1_str, re.IGNORECASE)

            # Pattern 2: {shot_name}_turnover-plate_{plate_name}{color_space}_{version}.####.exr
            pattern2_str = rf"{shot_name}_turnover-plate_{plate_name}([^_]+)_{version}\.\d{{4}}\.exr"
            pattern2 = re.compile(pattern2_str, re.IGNORECASE)

            RawPlateFinder._pattern_cache[cache_key] = (pattern1, pattern2)

        return RawPlateFinder._pattern_cache[cache_key]

    @staticmethod
    def _find_plate_file_pattern(
        resolution_dir: Path, shot_name: str, plate_name: str, version: str
    ) -> Optional[str]:
        """Find the actual plate file pattern with correct color space.

        Args:
            resolution_dir: Directory containing plate files
            shot_name: Shot name
            plate_name: Plate name (FG01, BG01, etc.)
            version: Version string (v001, etc.)

        Returns:
            Full path with #### pattern, or None if not found
        """
        # Get pre-compiled patterns from cache
        pattern1, pattern2 = RawPlateFinder._get_plate_patterns(
            shot_name, plate_name, version
        )

        try:
            # Look for any .exr file to determine the actual naming pattern
            for file_path in resolution_dir.iterdir():
                if file_path.suffix == ".exr":
                    filename = file_path.name

                    # Try to match the pattern and extract color space
                    match = pattern1.match(filename)
                    if match:
                        color_space = match.group(1)
                        # Construct the pattern with #### for frame numbers
                        plate_pattern = f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.####.exr"
                        full_path = str(resolution_dir / plate_pattern)
                        logger.debug(f"Found plate pattern: {plate_pattern}")
                        return full_path

                    # Try alternative pattern without underscore before color space
                    match2 = pattern2.match(filename)
                    if match2:
                        color_space = match2.group(1)
                        plate_pattern = f"{shot_name}_turnover-plate_{plate_name}{color_space}_{version}.####.exr"
                        full_path = str(resolution_dir / plate_pattern)
                        logger.debug(f"Found plate pattern: {plate_pattern}")
                        return full_path

            # If no file found, try common color spaces as fallback
            for color_space in Config.COLOR_SPACE_PATTERNS:
                plate_pattern = f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.####.exr"
                test_path = resolution_dir / plate_pattern.replace("####", "1001")
                if test_path.exists():
                    full_path = str(resolution_dir / plate_pattern)
                    logger.debug(
                        f"Found plate with color space {color_space}: {plate_pattern}"
                    )
                    return full_path

        except (OSError, PermissionError) as e:
            logger.warning(f"Error scanning plate directory {resolution_dir}: {e}")

        return None

    @staticmethod
    def get_version_from_path(plate_path: str) -> Optional[str]:
        """
        Extract the version number from a raw plate file path.

        Args:
            plate_path: Path to the raw plate file

        Returns:
            Version string (e.g., "v002") or None
        """
        # Use utility function for version extraction
        return VersionUtils.extract_version_from_path(plate_path)

    # Pre-compiled regex for verify_plate_exists
    _verify_pattern_cache = {}

    @staticmethod
    @timed_operation("verify_plate_exists", log_threshold_ms=20)
    def verify_plate_exists(plate_path: str) -> bool:
        """
        Verify that at least one frame of the plate sequence exists.

        Optimized to scan directory once instead of multiple file existence checks.

        Args:
            plate_path: Path with #### pattern

        Returns:
            True if at least one frame exists
        """
        if not plate_path or "####" not in plate_path:
            logger.debug("Invalid plate path - missing or no frame pattern")
            return False

        dir_path = Path(plate_path).parent
        if not PathUtils.validate_path_exists(dir_path, "Plate directory"):
            return False

        # Extract the base filename pattern for matching
        plate_filename = Path(plate_path).name
        base_pattern = plate_filename.replace("####", r"\d{4}")

        try:
            # Use cached pattern if available
            if base_pattern not in RawPlateFinder._verify_pattern_cache:
                RawPlateFinder._verify_pattern_cache[base_pattern] = re.compile(
                    f"^{base_pattern}$"
                )
            pattern = RawPlateFinder._verify_pattern_cache[base_pattern]

            # Single directory scan - more efficient than multiple exists() calls
            for file_path in dir_path.iterdir():
                if file_path.is_file() and pattern.match(file_path.name):
                    logger.debug(f"Found matching plate frame: {file_path.name}")
                    return True

        except (OSError, PermissionError) as e:
            logger.warning(f"Error scanning plate directory {dir_path}: {e}")
            return False
        except re.error as e:
            logger.error(f"Invalid regex pattern '{base_pattern}': {e}")
            return False

        logger.debug(f"No matching frames found for pattern: {base_pattern}")
        return False
