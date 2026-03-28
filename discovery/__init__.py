"""File, thumbnail, and plate discovery — latest-file finding.

Re-exports all public types and functions for convenient imports::

    from discovery import BaseLatestFinder, MayaLatestFinder
    from discovery import find_plate_mov_proxy, find_plate_exr_sequence
    from discovery import discover_plate_directories, safe_mkdir, find_mov_file_for_path
    from discovery import get_available_plates, get_highest_resolution_dir
    from discovery import UserSequenceFinder
    from discovery import extract_frame_range, find_main_plate
    from discovery import sanitize_username
    from discovery import find_shot_thumbnail, find_turnover_plate_thumbnail
    from discovery import find_any_publish_thumbnail
    from discovery import find_undistorted_jpeg_thumbnail, find_user_workspace_jpeg_thumbnail
    from discovery import FRAME_PATTERN, extract_frame_number, substitute_frame, to_hash_pattern
"""

from __future__ import annotations

from discovery.file_discovery import (
    discover_plate_directories,
    find_mov_file_for_path,
    find_plate_exr_sequence,
    find_plate_mov_proxy,
    safe_mkdir,
    sanitize_username,
)
from discovery.frame_range_extractor import extract_frame_range
from discovery.frame_utils import (
    FRAME_PATTERN,
    extract_frame_number,
    substitute_frame,
    to_hash_pattern,
)
from discovery.latest_finders import BaseLatestFinder, MayaLatestFinder
from discovery.plate_finders import (
    find_main_plate,
    get_available_plates,
    get_highest_resolution_dir,
)
from discovery.thumbnail_finders import (
    find_any_publish_thumbnail,
    find_shot_thumbnail,
    find_turnover_plate_thumbnail,
    find_undistorted_jpeg_thumbnail,
    find_user_workspace_jpeg_thumbnail,
)
from discovery.user_sequence_finder import UserSequenceFinder


__all__ = [
    "FRAME_PATTERN",
    "BaseLatestFinder",
    "MayaLatestFinder",
    "UserSequenceFinder",
    "discover_plate_directories",
    "extract_frame_number",
    "extract_frame_range",
    "find_any_publish_thumbnail",
    "find_main_plate",
    "find_mov_file_for_path",
    "find_plate_exr_sequence",
    "find_plate_mov_proxy",
    "find_shot_thumbnail",
    "find_turnover_plate_thumbnail",
    "find_undistorted_jpeg_thumbnail",
    "find_user_workspace_jpeg_thumbnail",
    "get_available_plates",
    "get_highest_resolution_dir",
    "safe_mkdir",
    "sanitize_username",
    "substitute_frame",
    "to_hash_pattern",
]
