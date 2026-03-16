"""3DE scene data model for tracking scenes from other users."""

from __future__ import annotations

# Standard library imports
import logging
from collections import defaultdict
from pathlib import Path

# Local application imports
from cache.scene_cache_disk import SceneDiskCache
from type_definitions import ThreeDEScene
from utils import get_excluded_users


logger = logging.getLogger(__name__)


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
        self._excluded_users: set[str] = get_excluded_users()
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
