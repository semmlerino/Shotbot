"""3DE scene data model for tracking scenes from other users."""

from __future__ import annotations

# Standard library imports
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

# Local application imports
from cache.scene_cache_disk import SceneDiskCache
from config import Config
from path_builders import PathBuilders
from thumbnail_finders import ThumbnailFinders
from utils import ValidationUtils


logger = logging.getLogger(__name__)

# Sentinel value to distinguish between "not searched" and "searched but found nothing"
_NOT_SEARCHED = object()


@dataclass
class ThreeDEScene:
    """Represents a 3DE scene file from another user."""

    show: str
    sequence: str
    shot: str
    workspace_path: str
    user: str
    plate: str
    scene_path: Path
    modified_time: float = 0.0  # Unix timestamp from file mtime (for sorting)
    frame_start: int | None = None  # First frame of main plate (for scrub preview)
    frame_end: int | None = None  # Last frame of main plate (for scrub preview)
    _cached_thumbnail_path: object | Path | None = field(
        default=_NOT_SEARCHED,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def full_name(self) -> str:
        """Get full shot name."""
        return f"{self.sequence}_{self.shot}"

    @property
    def display_name(self) -> str:
        """Get display name (simplified for deduplicated scenes)."""
        # Since we show only one scene per shot, we don't need plate info
        return f"{self.full_name} - {self.user}"

    @property
    def thumbnail_dir(self) -> Path:
        """Get thumbnail directory path (same as regular shots)."""
        return PathBuilders.build_thumbnail_path(
            Config.SHOWS_ROOT,
            self.show,
            self.sequence,
            self.shot,
        )

    def get_thumbnail_path(self) -> Path | None:
        """Get first available thumbnail or None.

        Uses the unified thumbnail discovery logic from PathUtils.find_shot_thumbnail()
        to ensure consistent thumbnails across all views.

        Results are cached after the first search to avoid repeated
        expensive filesystem operations.
        """
        # Return cached result if we've already searched
        if self._cached_thumbnail_path is not _NOT_SEARCHED:
            # Type narrowing: if it's not the sentinel, it must be Path | None
            return cast("Path | None", self._cached_thumbnail_path)

        # DEBUG: Log thumbnail search for 3DE scenes
        logger.debug(
            f"ThreeDEScene.get_thumbnail_path() called for {self.full_name} (show={self.show}, seq={self.sequence}, shot={self.shot})"
        )

        # Use the unified thumbnail discovery method
        thumbnail = ThumbnailFinders.find_shot_thumbnail(
            Config.SHOWS_ROOT,
            self.show,
            self.sequence,
            self.shot,
        )

        # DEBUG: Log result
        if thumbnail:
            logger.info(
                f"✅ Found thumbnail for 3DE scene {self.full_name}: {thumbnail}"
            )
        else:
            logger.warning(f"❌ No thumbnail found for 3DE scene {self.full_name}")

        # Cache the result (even if None) to avoid repeated searches
        self._cached_thumbnail_path = thumbnail
        return thumbnail

    def to_dict(self) -> dict[str, str | float | Path | int | None]:
        """Convert scene to dictionary for caching.

        Includes thumbnail_path if it has been discovered (not sentinel).
        This reduces filesystem I/O on subsequent loads.
        """
        data: dict[str, str | float | Path | int | None] = {
            "show": self.show,
            "sequence": self.sequence,
            "shot": self.shot,
            "workspace_path": self.workspace_path,
            "user": self.user,
            "plate": self.plate,
            "scene_path": str(self.scene_path),
            "modified_time": self.modified_time,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
        }
        # Persist thumbnail path if discovered (not sentinel)
        if self._cached_thumbnail_path is not _NOT_SEARCHED and self._cached_thumbnail_path:
            data["thumbnail_path"] = str(self._cached_thumbnail_path)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str | float | Path | int | None]) -> ThreeDEScene:
        """Create from dictionary.

        Note: modified_time defaults to 0.0 for cache migration of old entries.
        Frame range fields default to None for cache migration compatibility.
        Restores thumbnail_path if present AND file still exists (validated).
        """
        # Extract frame range with proper type handling
        frame_start_raw = data.get("frame_start")
        frame_end_raw = data.get("frame_end")
        # Handle numeric types only (int/float from cache)
        frame_start: int | None = None
        frame_end: int | None = None
        if isinstance(frame_start_raw, (int, float)):
            frame_start = int(frame_start_raw)
        if isinstance(frame_end_raw, (int, float)):
            frame_end = int(frame_end_raw)

        instance = cls(
            show=str(data["show"]),
            sequence=str(data["sequence"]),
            shot=str(data["shot"]),
            workspace_path=str(data["workspace_path"]),
            user=str(data["user"]),
            plate=str(data["plate"]),
            scene_path=Path(str(data["scene_path"])),
            modified_time=float(data.get("modified_time", 0.0)),  # type: ignore[arg-type]
            frame_start=frame_start,
            frame_end=frame_end,
        )
        # Restore thumbnail path if present AND file still exists
        if "thumbnail_path" in data:
            cached_path = Path(str(data["thumbnail_path"]))
            if cached_path.exists():
                instance._cached_thumbnail_path = cached_path
            # else: leave as _NOT_SEARCHED for re-discovery
        return instance


class ThreeDESceneModel:
    """Manages 3DE scene data and discovery."""

    def __init__(
        self,
        cache_manager: SceneDiskCache | None = None,
        load_cache: bool = True,
    ) -> None:
        super().__init__()
        self.scenes: list[ThreeDEScene] = []
        if cache_manager is None:
            import os
            import sys
            test_dir = os.getenv("SHOTBOT_TEST_CACHE_DIR")
            if test_dir:
                default_dir = Path(test_dir)
            elif "pytest" in sys.modules or os.getenv("SHOTBOT_MODE") == "test":
                default_dir = Path.home() / ".shotbot" / "cache_test"
            elif os.getenv("SHOTBOT_MODE") == "mock":
                default_dir = Path.home() / ".shotbot" / "cache" / "mock"
            else:
                default_dir = Path.home() / ".shotbot" / "cache" / "production"
            default_dir.mkdir(parents=True, exist_ok=True)
            cache_manager = SceneDiskCache(default_dir)
        self.cache_manager: SceneDiskCache = cache_manager
        # Get excluded users dynamically (current user + any additional)
        self._excluded_users: set[str] = ValidationUtils.get_excluded_users()
        # Show filtering
        self._filter_show: str | None = None
        self._filter_artist: str | None = None
        self._filter_text: str | None = None  # Text filter for real-time search
        # Only load cache if requested (allows tests to start clean)
        if load_cache:
            _ = self._load_from_cache()

    def _load_from_cache(self) -> bool:
        """Load 3DE scenes from cache if available."""
        cached_data = self.cache_manager.get_cached_threede_scenes()
        if cached_data:
            self.scenes = []
            for scene_data in cached_data:
                try:
                    # Skip invalid cached entries (e.g., from old format)
                    # Note: cached_data is ThreeDESceneDict but from_dict expects dict[str, str | Path]
                    # The structures differ but from_dict extracts only the fields it needs
                    self.scenes.append(ThreeDEScene.from_dict(scene_data))  # pyright: ignore[reportArgumentType]
                except (KeyError, TypeError, ValueError):
                    # Skip invalid cached entry
                    logger.warning("Skipping invalid cached 3DE scene", exc_info=True)
                    continue
            return len(self.scenes) > 0
        return False

    def set_scenes(self, scenes: list[ThreeDEScene]) -> None:
        """Replace the current scene list.

        Prefer this over direct ``self.scenes = ...`` assignment so that
        future validation or notification logic has a single entry point.

        Args:
            scenes: New list of 3DE scenes.

        """
        self.scenes = scenes

    def get_scene_by_index(self, index: int) -> ThreeDEScene | None:
        """Get scene by index."""
        if 0 <= index < len(self.scenes):
            return self.scenes[index]
        return None

    def find_scene_by_display_name(self, display_name: str) -> ThreeDEScene | None:
        """Find scene by display name."""
        for scene in self.scenes:
            if scene.display_name == display_name:
                return scene
        return None

    def to_dict(self) -> list[dict[str, str | float | Path | int | None]]:
        """Convert scenes to dictionary format for caching."""
        return [scene.to_dict() for scene in self.scenes]

    # Show filtering methods

    def get_unique_shows(self) -> list[str]:
        """Get sorted list of unique shows from all scenes."""
        shows = {scene.show for scene in self.scenes}
        return sorted(shows)

    def get_unique_artists(self) -> list[str]:
        """Get sorted list of unique artist names from all scenes."""
        artists = {scene.user for scene in self.scenes}
        return sorted(artists, key=str.casefold)

    def set_show_filter(self, show: str | None) -> None:
        """Set the show filter.

        Args:
            show: Show name to filter by, or None for no filtering

        """
        self._filter_show = show

    def get_show_filter(self) -> str | None:
        """Get the current show filter."""
        return self._filter_show

    def set_artist_filter(self, artist: str | None) -> None:
        """Set the artist filter.

        Args:
            artist: Artist name to filter by, or None for no filtering

        """
        self._filter_artist = artist

    def get_artist_filter(self) -> str | None:
        """Get the current artist filter."""
        return self._filter_artist

    def set_text_filter(self, text: str | None) -> None:
        """Set the text filter for real-time search.

        Args:
            text: Text to filter by (case-insensitive substring match) or None for no filter

        """
        self._filter_text = text
        logger.info(f"Text filter set to: '{text or ''}'")

    def get_text_filter(self) -> str | None:
        """Get the current text filter."""
        return self._filter_text

    def get_filtered_scenes(self) -> list[ThreeDEScene]:
        """Get scenes filtered by show, artist, and text filters.

        Applies all active filters using AND logic.

        Returns:
            List of scenes matching the filters, or all scenes if no filters

        """
        scenes = self.scenes

        # Apply show filter
        if self._filter_show is not None:
            scenes = [scene for scene in scenes if scene.show == self._filter_show]

        # Apply artist filter
        if self._filter_artist is not None:
            scenes = [scene for scene in scenes if scene.user == self._filter_artist]

        # Apply text filter (case-insensitive substring match on full_name)
        if self._filter_text:
            filter_lower = self._filter_text.lower()
            scenes = [
                scene for scene in scenes if filter_lower in scene.full_name.lower()
            ]

        logger.debug(
            "Filtered %s scenes to %s (show=%r, artist=%r, text=%r)",
            len(self.scenes),
            len(scenes),
            self._filter_show,
            self._filter_artist,
            self._filter_text,
        )
        return scenes

    def deduplicate_scenes_by_shot(
        self,
        scenes: list[ThreeDEScene],
    ) -> list[ThreeDEScene]:
        """Keep only the latest/best scene per shot.

        Priority order:
        1. Latest file modification time
        2. Specific plate preference (FG01 > BG01 > others)
        3. Alphabetical plate name as tiebreaker

        Args:
            scenes: List of all discovered scenes

        Returns:
            Deduplicated list with one scene per shot

        """
        # Group scenes by shot
        scenes_by_shot: dict[str, list[ThreeDEScene]] = defaultdict(list)
        for scene in scenes:
            shot_key = f"{scene.show}/{scene.sequence}/{scene.shot}"
            scenes_by_shot[shot_key].append(scene)

        deduplicated: list[ThreeDEScene] = []
        for shot_scenes in scenes_by_shot.values():
            if len(shot_scenes) == 1:
                deduplicated.append(shot_scenes[0])
            else:
                # Select best scene for this shot
                best_scene = self._select_best_scene(shot_scenes)
                deduplicated.append(best_scene)
                logger.debug(
                    f"Selected {best_scene.display_name} from {len(shot_scenes)} scenes",
                )

        return deduplicated

    def _select_best_scene(self, scenes: list[ThreeDEScene]) -> ThreeDEScene:
        """Select the best scene from multiple options.

        Args:
            scenes: List of scenes for the same shot

        Returns:
            Best scene based on priority criteria

        """

        # Priority 1: Latest modification time
        def get_mtime(scene: ThreeDEScene) -> float:
            try:
                return scene.scene_path.stat().st_mtime
            except (OSError, AttributeError):
                return 0

        # Priority 2: Plate preference
        plate_priority: dict[str, int] = {
            "fg01": 3,
            "bg01": 2,
        }  # lowercase for case-insensitive comparison

        def scene_score(scene: ThreeDEScene) -> tuple[float, int, str]:
            mtime = get_mtime(scene)
            plate_score = plate_priority.get(scene.plate.lower(), 1)
            return (mtime, plate_score, scene.plate)

        return max(scenes, key=scene_score)
