"""Cache adapter for 3DE scene persistence.

Handles loading and saving ThreeDEScene objects to/from the disk cache.
Extracted from ThreeDEController to isolate cache I/O from orchestration logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from logging_mixin import LoggingMixin
from type_definitions import ThreeDEScene


if TYPE_CHECKING:
    from cache import SceneDiskCache
    from threede.scene_model import ThreeDESceneModel


@final
class ThreeDECacheAdapter(LoggingMixin):
    """Handles loading and saving 3DE scenes to/from the persistent disk cache.

    Decouples cache I/O from the controller's orchestration logic.
    All methods are pure in the sense that they do not mutate the scene model;
    the controller is responsible for applying returned data.

    Args:
        scene_disk_cache: Disk cache for persistent scene storage.
        threede_scene_model: Scene model used to serialise scenes for writing.

    """

    def __init__(
        self,
        scene_disk_cache: SceneDiskCache,
        threede_scene_model: ThreeDESceneModel,
    ) -> None:
        super().__init__()
        self._scene_disk_cache: SceneDiskCache = scene_disk_cache
        self._threede_scene_model: ThreeDESceneModel = threede_scene_model

    def load_cached_scenes(self) -> list[ThreeDEScene]:
        """Load 3DE scenes from the persistent disk cache.

        Fetches raw cached dicts, deserialises each to a ThreeDEScene (skipping
        invalid entries), and returns the resulting list.  The caller is
        responsible for applying the scenes to the model and updating the UI.

        Returns:
            List of successfully deserialised ThreeDEScene objects, or an empty
            list when there is no cache or no valid entries.

        """
        cached_data = self._scene_disk_cache.get_persistent_threede_scenes()
        if not cached_data:
            return []

        scenes: list[ThreeDEScene] = []
        for scene_data in cached_data:
            try:
                scenes.append(ThreeDEScene.from_dict(scene_data))
            except (KeyError, TypeError, ValueError) as e:
                self.logger.debug(f"Skipping invalid cached 3DE scene: {e}")

        if scenes:
            self.logger.info(
                f"Loaded {len(scenes)} cached 3DE scenes "
                "(scanning for updates in background)"
            )

        return scenes

    def cache_scenes(self) -> None:
        """Persist the current scene model state to the disk cache.

        Serialises all scenes in the model via ``to_dict()`` and writes them
        to the persistent cache.  Failures are logged as warnings; they do not
        propagate to the caller.

        """
        try:
            self._scene_disk_cache.cache_threede_scenes(
                self._threede_scene_model.to_dict(),
            )
        except Exception:  # noqa: BLE001
            self.logger.warning("Failed to cache 3DE scenes", exc_info=True)
