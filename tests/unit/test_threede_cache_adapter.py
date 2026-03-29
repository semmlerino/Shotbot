"""Unit tests for controllers/threede_cache_adapter.py.

Tests for ThreeDECacheAdapter which handles loading and saving 3DE scene
data to/from the persistent disk cache.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from controllers.threede_cache_adapter import ThreeDECacheAdapter
from type_definitions import ThreeDEScene


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ============================================================================
# Test Doubles
# ============================================================================


class SceneDiskCacheDouble:
    """Test double for SceneDiskCache."""

    __test__ = False

    def __init__(self) -> None:
        self._persistent_scenes: list[dict[str, Any]] = []
        self._cached_scenes: list[dict[str, Any]] = []

    def get_persistent_threede_scenes(self) -> list[dict[str, Any]]:
        return self._persistent_scenes

    def cache_threede_scenes(
        self, scenes: list[dict[str, Any]], immediate: bool = False
    ) -> None:
        self._cached_scenes = scenes


class ThreeDESceneModelDouble:
    """Test double for ThreeDESceneModel."""

    __test__ = False

    def __init__(self) -> None:
        self._scenes: list[ThreeDEScene] = []

    @property
    def scenes(self) -> list[ThreeDEScene]:
        return self._scenes

    def set_scenes(self, scenes: list[ThreeDEScene]) -> None:
        self._scenes = scenes

    def to_dict(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._scenes]


# ============================================================================
# Factory helpers
# ============================================================================


def make_scene(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "sh0010",
    user: str = "testuser",
    plate: str = "plate_main",
    modified_time: float | None = None,
    scene_path: str | None = None,
) -> ThreeDEScene:
    if modified_time is None:
        modified_time = time.time()
    if scene_path is None:
        scene_path = f"/shows/{show}/shots/{sequence}/{shot}/3de/{user}_{plate}.3de"
    return ThreeDEScene(
        show=show,
        sequence=sequence,
        shot=shot,
        workspace_path=f"/shows/{show}/shots/{sequence}/{shot}",
        user=user,
        plate=plate,
        scene_path=Path(scene_path),
        modified_time=modified_time,
    )


def make_scene_dict(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "sh0010",
    user: str = "testuser",
    plate: str = "plate_main",
    modified_time: float | None = None,
    scene_path: str | None = None,
) -> dict[str, Any]:
    if modified_time is None:
        modified_time = time.time()
    if scene_path is None:
        scene_path = f"/shows/{show}/shots/{sequence}/{shot}/3de/{user}_{plate}.3de"
    return {
        "show": show,
        "sequence": sequence,
        "shot": shot,
        "workspace_path": f"/shows/{show}/shots/{sequence}/{shot}",
        "user": user,
        "plate": plate,
        "scene_path": scene_path,
        "modified_time": modified_time,
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def scene_disk_cache() -> SceneDiskCacheDouble:
    return SceneDiskCacheDouble()


@pytest.fixture
def scene_model() -> ThreeDESceneModelDouble:
    return ThreeDESceneModelDouble()


@pytest.fixture
def adapter(
    scene_disk_cache: SceneDiskCacheDouble,
    scene_model: ThreeDESceneModelDouble,
) -> ThreeDECacheAdapter:
    return ThreeDECacheAdapter(
        scene_disk_cache=scene_disk_cache,  # type: ignore[arg-type]
        threede_scene_model=scene_model,  # type: ignore[arg-type]
    )


# ============================================================================
# Test Cache Operations
# ============================================================================


class TestCacheOperations:
    """Test cache loading and saving operations."""

    def test_cache_scenes_serializes_scenes_as_dicts(
        self,
        adapter: ThreeDECacheAdapter,
        scene_disk_cache: SceneDiskCacheDouble,
        scene_model: ThreeDESceneModelDouble,
    ) -> None:
        """Test that cache_scenes serializes all scenes as dicts to cache manager."""
        scenes = [
            make_scene(show="testshow", sequence="sq010", shot="sh0010"),
            make_scene(show="testshow", sequence="sq010", shot="sh0020"),
        ]
        scene_model.set_scenes(scenes)

        adapter.cache_scenes()

        cached = scene_disk_cache._cached_scenes
        assert len(cached) == 2
        assert cached[0]["show"] == "testshow"
        assert cached[0]["sequence"] == "sq010"

    def test_cache_scenes_handles_exception_gracefully(
        self,
        mocker,
        adapter: ThreeDECacheAdapter,
        scene_disk_cache: SceneDiskCacheDouble,
    ) -> None:
        """Test that cache_scenes swallows exceptions and logs a warning."""
        scene_disk_cache.cache_threede_scenes = mocker.MagicMock(  # type: ignore[method-assign]
            side_effect=OSError("disk full")
        )
        # Should not raise
        adapter.cache_scenes()

    def test_load_cached_scenes_returns_empty_when_no_cache(
        self,
        adapter: ThreeDECacheAdapter,
        scene_disk_cache: SceneDiskCacheDouble,
    ) -> None:
        """Test that load_cached_scenes returns [] when cache is empty."""
        scene_disk_cache._persistent_scenes = []

        result = adapter.load_cached_scenes()

        assert result == []

    def test_load_cached_scenes_deserializes_valid_entries(
        self,
        adapter: ThreeDECacheAdapter,
        scene_disk_cache: SceneDiskCacheDouble,
    ) -> None:
        """Test that load_cached_scenes returns ThreeDEScene objects for valid dicts."""
        scene_disk_cache._persistent_scenes = [
            make_scene_dict(shot="sh0010"),
            make_scene_dict(shot="sh0020"),
        ]

        result = adapter.load_cached_scenes()

        assert len(result) == 2
        assert all(isinstance(s, ThreeDEScene) for s in result)
        shots = {s.shot for s in result}
        assert shots == {"sh0010", "sh0020"}

    def test_load_cached_scenes_skips_invalid_entries(
        self,
        adapter: ThreeDECacheAdapter,
        scene_disk_cache: SceneDiskCacheDouble,
    ) -> None:
        """Test that load_cached_scenes skips entries that fail to deserialise."""
        valid_dict = make_scene_dict(shot="sh0010")
        invalid_dict: dict[str, Any] = {"bad_key": "no data here"}
        scene_disk_cache._persistent_scenes = [valid_dict, invalid_dict]

        result = adapter.load_cached_scenes()

        assert len(result) == 1
        assert result[0].shot == "sh0010"

    def test_load_cached_scenes_does_not_mutate_model(
        self,
        adapter: ThreeDECacheAdapter,
        scene_disk_cache: SceneDiskCacheDouble,
        scene_model: ThreeDESceneModelDouble,
    ) -> None:
        """Test that load_cached_scenes returns data without touching the model."""
        scene_disk_cache._persistent_scenes = [make_scene_dict()]
        initial_scenes = list(scene_model.scenes)

        result = adapter.load_cached_scenes()

        # Model should be unchanged — controller applies the result
        assert scene_model.scenes == initial_scenes
        assert len(result) == 1
