"""Scene file data model for unified file representation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path


class FileType(Enum):
    """Enumeration of supported file types."""

    THREEDE = auto()
    MAYA = auto()
    NUKE = auto()


# Mapping from file type to app name for launching
_FILE_TYPE_TO_APP: dict[FileType, str] = {
    FileType.THREEDE: "3de",
    FileType.MAYA: "maya",
    FileType.NUKE: "nuke",
}

# Mapping from file type to display name
_FILE_TYPE_TO_DISPLAY: dict[FileType, str] = {
    FileType.THREEDE: "3DEqualizer",
    FileType.MAYA: "Maya",
    FileType.NUKE: "Nuke",
}

# Colors for each file type (matching launcher_panel.py)
FILE_TYPE_COLORS: dict[FileType, str] = {
    FileType.THREEDE: "#c0392b",  # Red
    FileType.MAYA: "#16a085",  # Teal
    FileType.NUKE: "#d35400",  # Orange
}


@dataclass(frozen=True, slots=True)
class SceneFile:
    """Represents a scene file for display and launching.

    Immutable data class abstracting over different file types (3DE, Maya, Nuke).
    Provides computed properties for display formatting.
    """

    path: Path
    file_type: FileType
    modified_time: datetime
    user: str
    version: int | None = None

    @property
    def name(self) -> str:
        """Return the filename."""
        return self.path.name

    @property
    def app_name(self) -> str:
        """Return the app name for launching (e.g., '3de', 'maya', 'nuke')."""
        return _FILE_TYPE_TO_APP[self.file_type]

    @property
    def display_name(self) -> str:
        """Return the display name for the file type (e.g., '3DEqualizer')."""
        return _FILE_TYPE_TO_DISPLAY[self.file_type]

    @property
    def relative_age(self) -> str:
        """Return human-readable relative age (e.g., '2 hours ago', 'yesterday').

        Returns a user-friendly string describing when the file was last modified.
        """
        now = datetime.now()  # noqa: DTZ005 - Comparing with naive local time from filesystem
        delta = now - self.modified_time

        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "just now"

        minutes = seconds // 60
        hours = minutes // 60
        days = delta.days

        if seconds < 60:
            return "just now"
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            weeks = days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        if days < 365:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"

    @property
    def formatted_time(self) -> str:
        """Return formatted modification time (e.g., '2024-01-15 14:30')."""
        return self.modified_time.strftime("%Y-%m-%d %H:%M")

    @property
    def color(self) -> str:
        """Return the color associated with this file type."""
        return FILE_TYPE_COLORS[self.file_type]


@dataclass(frozen=True, slots=True)
class ImageSequence:
    """Represents an image sequence for RV playback.

    Immutable data class for Maya playblasts and Nuke renders.
    Provides computed properties for display formatting.
    """

    path: Path  # Full path with frame pattern (e.g., /path/to/file.####.exr)
    sequence_type: str  # "maya_playblast" or "nuke_render"
    modified_time: datetime
    user: str
    version: int | None = None
    first_frame: int = 1001
    last_frame: int = 1100
    render_type: str = ""  # e.g., "Cones", "Wireframe", "lineupGeo"

    @property
    def name(self) -> str:
        """Return the filename pattern."""
        return self.path.name

    @property
    def frame_count(self) -> int:
        """Return expected frame count (assumes no gaps)."""
        return self.last_frame - self.first_frame + 1

    @property
    def frame_range_str(self) -> str:
        """Return formatted frame range (e.g., '1001-1200')."""
        return f"{self.first_frame}-{self.last_frame}"

    @property
    def display_name(self) -> str:
        """Return display name (render_type + version)."""
        if self.version is not None:
            return f"{self.render_type}_v{self.version:03d}"
        return self.render_type

    @property
    def relative_age(self) -> str:
        """Return human-readable relative age (e.g., '2 hours ago', 'yesterday')."""
        now = datetime.now()  # noqa: DTZ005 - Comparing with naive local time from filesystem
        delta = now - self.modified_time

        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "just now"

        minutes = seconds // 60
        hours = minutes // 60
        days = delta.days

        if seconds < 60:
            return "just now"
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            weeks = days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        if days < 365:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"

    @property
    def formatted_time(self) -> str:
        """Return formatted modification time (e.g., '2024-01-15 14:30')."""
        return self.modified_time.strftime("%Y-%m-%d %H:%M")
