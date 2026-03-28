"""File, thumbnail, and plate discovery — latest-file finding.

Re-exports all public types and functions for convenient imports::

    from discovery import BaseLatestFinder, MayaLatestFinder
    from discovery import FileDiscovery, PlateDiscovery
    from discovery import UserSequenceFinder
    from discovery import extract_frame_range, find_main_plate
    from discovery import sanitize_username
    from discovery import find_shot_thumbnail, find_turnover_plate_thumbnail
    from discovery import find_any_publish_thumbnail
    from discovery import find_undistorted_jpeg_thumbnail, find_user_workspace_jpeg_thumbnail
    from discovery import FRAME_PATTERN, extract_frame_number, substitute_frame, to_hash_pattern
"""

from __future__ import annotations

from discovery.file_discovery import FileDiscovery, sanitize_username
from discovery.frame_range_extractor import extract_frame_range
from discovery.frame_utils import (
    FRAME_PATTERN,
    extract_frame_number,
    substitute_frame,
    to_hash_pattern,
)
from discovery.latest_finders import BaseLatestFinder, MayaLatestFinder
from discovery.plate_finders import PlateDiscovery, find_main_plate
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
    "FileDiscovery",
    "MayaLatestFinder",
    "PlateDiscovery",
    "UserSequenceFinder",
    "extract_frame_number",
    "extract_frame_range",
    "find_any_publish_thumbnail",
    "find_main_plate",
    "find_shot_thumbnail",
    "find_turnover_plate_thumbnail",
    "find_undistorted_jpeg_thumbnail",
    "find_user_workspace_jpeg_thumbnail",
    "sanitize_username",
    "substitute_frame",
    "to_hash_pattern",
]
