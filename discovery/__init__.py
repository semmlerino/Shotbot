"""File, thumbnail, and plate discovery — latest-file finding.

Re-exports all public types and functions for convenient imports::

    from discovery import BaseLatestFinder, MayaLatestFinder
    from discovery import FileDiscovery, PlateDiscovery
    from discovery import UserSequenceFinder
    from discovery import extract_frame_range, find_main_plate
    from discovery import load_maya_comments, save_maya_comment
    from discovery import sanitize_username
    from discovery import find_shot_thumbnail, find_turnover_plate_thumbnail
    from discovery import find_any_publish_thumbnail
    from discovery import find_undistorted_jpeg_thumbnail, find_user_workspace_jpeg_thumbnail
"""

from __future__ import annotations

from dcc.maya_comment_reader import load_maya_comments, save_maya_comment
from discovery.file_discovery import FileDiscovery, sanitize_username
from discovery.frame_range_extractor import extract_frame_range
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
    "BaseLatestFinder",
    "FileDiscovery",
    "MayaLatestFinder",
    "PlateDiscovery",
    "UserSequenceFinder",
    "extract_frame_range",
    "find_any_publish_thumbnail",
    "find_main_plate",
    "find_shot_thumbnail",
    "find_turnover_plate_thumbnail",
    "find_undistorted_jpeg_thumbnail",
    "find_user_workspace_jpeg_thumbnail",
    "load_maya_comments",
    "sanitize_username",
    "save_maya_comment",
]
