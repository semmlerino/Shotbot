"""3DE scene data model for tracking scenes from other users."""

from __future__ import annotations

# Standard library imports
import logging
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

    def get_unique_shows(self) -> list[str]:
        """Get sorted list of unique shows from all scenes."""
        shows = {scene.show for scene in self.scenes}
        return sorted(shows)

    def get_unique_artists(self) -> list[str]:
        """Get sorted list of unique artist names from all scenes."""
        artists = {scene.user for scene in self.scenes}
        return sorted(artists, key=str.casefold)

