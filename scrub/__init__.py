"""Scrub and preview components for shot frame playback.

This package contains focused components for scrubbing and previewing shot frames:
- ScrubEventFilter: Event filter for scrub widget key/scroll handling
- ScrubFrameCache: Cache for preloaded plate frames
- ScrubPreviewManager: Manager for scrub preview widget state and updates
- PlateFrameProvider: Provider for loading plate frames from disk
- PlateSource: Data class holding plate source configuration
"""

from scrub.plate_frame_provider import PlateFrameProvider, PlateSource
from scrub.scrub_event_filter import ScrubEventFilter
from scrub.scrub_frame_cache import ScrubFrameCache
from scrub.scrub_preview_manager import ScrubPreviewManager


__all__ = [
    "PlateFrameProvider",
    "PlateSource",
    "ScrubEventFilter",
    "ScrubFrameCache",
    "ScrubPreviewManager",
]
