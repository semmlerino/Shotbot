"""3DE scene data model for tracking scenes from other users."""

from __future__ import annotations

# Standard library imports
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

# Local application imports
from type_definitions import ThreeDEScene, ThreeDESceneDict
from utils import get_excluded_users


if TYPE_CHECKING:
    from cache.scene_cache_disk import SceneDiskCache


logger = logging.getLogger(__name__)


class ThreeDESceneModel:
    """Manages 3DE scene data and discovery."""

    def __init__(
        self,
        cache_manager: SceneDiskCache,
        load_cache: bool = True,
    ) -> None:
        super().__init__()
        self.scenes: list[ThreeDEScene] = []
        self.cache_manager: SceneDiskCache = cache_manager
        # Get excluded users dynamically (current user + any additional)
        self._excluded_users: set[str] = get_excluded_users()
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
                    self.scenes.append(ThreeDEScene.from_dict(scene_data))
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

    def to_dict(self) -> list[ThreeDESceneDict]:
        """Convert scenes to dictionary format for caching."""
        return [scene.to_dict() for scene in self.scenes]

    def deduplicate_scenes_by_shot(
        self,
        scenes: list[ThreeDEScene],
    ) -> list[ThreeDEScene]:
        """Keep only the latest/best scene per shot.

        Priority: latest mtime, then plate preference (FG01 > BG01 > others).
        """
        scenes_by_shot: dict[str, list[ThreeDEScene]] = defaultdict(list)
        for scene in scenes:
            shot_key = f"{scene.show}/{scene.sequence}/{scene.shot}"
            scenes_by_shot[shot_key].append(scene)

        deduplicated: list[ThreeDEScene] = []
        for shot_scenes in scenes_by_shot.values():
            if len(shot_scenes) == 1:
                deduplicated.append(shot_scenes[0])
            else:
                best_scene = self._select_best_scene(shot_scenes)
                deduplicated.append(best_scene)
                logger.debug(
                    f"Selected {best_scene.display_name} from {len(shot_scenes)} scenes",
                )
        return deduplicated

    def _select_best_scene(self, scenes: list[ThreeDEScene]) -> ThreeDEScene:
        """Select the best scene from multiple options for the same shot."""
        plate_priority: dict[str, int] = {"fg01": 3, "bg01": 2}

        def scene_score(scene: ThreeDEScene) -> tuple[float, int, str]:
            try:
                mtime = scene.scene_path.stat().st_mtime
            except (OSError, AttributeError):
                mtime = 0.0
            return (mtime, plate_priority.get(scene.plate.lower(), 1), scene.plate)

        return max(scenes, key=scene_score)

    def get_unique_shows(self) -> list[str]:
        """Get sorted list of unique shows from all scenes."""
        shows = {scene.show for scene in self.scenes}
        return sorted(shows)

    def get_unique_artists(self) -> list[str]:
        """Get sorted list of unique artist names from all scenes."""
        artists = {scene.user for scene in self.scenes}
        return sorted(artists, key=str.casefold)
