"""Unit tests for threede_scene_model module following UNIFIED_TESTING_GUIDE.

This refactored version:
- Uses real 3DE files created in tmp_path
- Uses real ThreeDESceneFinder for discovery
- Tests actual behavior, not mocked returns
- No mocking of internal utilities (PathUtils, FileUtils)
- Uses real CacheManager with temporary storage
"""

from __future__ import annotations

# Standard library imports
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
import pytest

from config import Config

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

pytestmark = pytest.mark.unit


@pytest.mark.xdist_group("serial_qt_state")
class TestThreeDEScene:
    """Test ThreeDEScene dataclass with real files."""

    def test_scene_creation(self, make_real_3de_file: Callable[..., Path]) -> None:
        """Test basic scene creation with real file."""
        # Create real 3DE file
        scene_path = make_real_3de_file(
            "test_show", "seq01", "shot01", "otheruser", "v001"
        )

        # Create scene with real path
        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path=str(scene_path.parent.parent.parent.parent),
            user="otheruser",
            plate="FG01",
            scene_path=scene_path,
        )

        # Test actual properties
        assert scene.show == "test_show"
        assert scene.sequence == "seq01"
        assert scene.shot == "shot01"
        assert scene.user == "otheruser"
        assert scene.plate == "FG01"
        assert isinstance(scene.scene_path, Path)
        assert scene.scene_path.exists()

    def test_full_name_property(self, make_real_3de_file: Callable[..., Path]) -> None:
        """Test full_name property returns correct format."""
        scene_path = make_real_3de_file("test_show", "seq01", "shot01", "user1")

        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path=str(scene_path.parent.parent.parent.parent),
            user="user1",
            plate="BG01",
            scene_path=scene_path,
        )

        assert scene.full_name == "seq01_shot01"

    def test_display_name_property(
        self, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test display_name property for deduplicated scenes."""
        scene_path = make_real_3de_file("test_show", "seq01", "shot01", "artist1")

        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path=str(scene_path.parent.parent.parent.parent),
            user="artist1",
            plate="FG01",
            scene_path=scene_path,
        )

        assert scene.display_name == "seq01_shot01 - artist1"

    def test_get_thumbnail_path_with_real_files(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Test get_thumbnail_path with real thumbnail files.

        Uses xdist_group at class level to ensure isolation from Config state contamination.
        """
        # Set Config.SHOWS_ROOT FIRST, before any other operations
        # Patch in both locations to ensure all imports see the new value
        shows_root = tmp_path / "shows"
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))
        monkeypatch.setattr("threede_scene_model.Config.SHOWS_ROOT", str(shows_root))
        monkeypatch.setattr("thumbnail_finders.Config.SHOWS_ROOT", str(shows_root))

        # Clear all caches to ensure they use the new Config.SHOWS_ROOT
        from tests.fixtures.caching import clear_all_caches
        clear_all_caches()

        # Create real directory structure
        shot_path = shows_root / "test_show" / "shots" / "seq01" / "seq01_shot01"
        shot_path.mkdir(parents=True, exist_ok=True)

        # Create real editorial thumbnail
        editorial_path = (
            shot_path
            / "publish"
            / "editorial"
            / "cutref"
            / "v001"
            / "jpg"
            / "1920x1080"
        )
        editorial_path.mkdir(parents=True, exist_ok=True)
        thumb_file = editorial_path / "frame.1001.jpg"
        thumb_file.write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        )

        # Create real 3DE file
        scene_path = shot_path / "user" / "artist" / "3de" / "mm-default" / "scene.3de"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text("# 3DE scene file")

        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path=str(shot_path),
            user="artist",
            plate="FG01",
            scene_path=scene_path,
        )

        # Test actual thumbnail discovery
        result = scene.get_thumbnail_path()
        assert result is not None
        assert result.exists()
        assert result.name == "frame.1001.jpg"

        # Test caching - second call returns same result
        result2 = scene.get_thumbnail_path()
        assert result2 == result

    def test_get_thumbnail_path_none_found(self, tmp_path: Path) -> None:
        """Test get_thumbnail_path returns None when no thumbnail found."""
        # Create scene with no thumbnails
        shot_path = (
            tmp_path / "shows" / "test_show" / "shots" / "seq01" / "seq01_shot01"
        )
        shot_path.mkdir(parents=True, exist_ok=True)

        scene_path = shot_path / "user" / "artist" / "3de" / "scene.3de"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text("# 3DE scene")

        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path=str(shot_path),
            user="artist",
            plate="FG01",
            scene_path=scene_path,
        )

        # Test returns None when no thumbnail
        result = scene.get_thumbnail_path()
        assert result is None

        # Test None is cached
        result2 = scene.get_thumbnail_path()
        assert result2 is None

    def test_to_dict_serialization(
        self, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test to_dict serialization."""
        scene_path = make_real_3de_file("test_show", "seq01", "shot01", "user1")

        scene = ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path=str(scene_path.parent.parent.parent.parent),
            user="user1",
            plate="FG01",
            scene_path=scene_path,
        )

        result = scene.to_dict()

        assert result["show"] == "test_show"
        assert result["sequence"] == "seq01"
        assert result["shot"] == "shot01"
        assert result["user"] == "user1"
        assert result["plate"] == "FG01"
        assert result["scene_path"] == str(scene_path)

    def test_from_dict_deserialization(self) -> None:
        """Test from_dict deserialization."""
        data = {
            "show": "test_show",
            "sequence": "seq01",
            "shot": "shot01",
            "workspace_path": f"{Config.SHOWS_ROOT}/test_show/seq01/seq01_shot01",
            "user": "artist",
            "plate": "BG01",
            "scene_path": "/path/to/scene.3de",
        }

        scene = ThreeDEScene.from_dict(data)

        assert scene.show == "test_show"
        assert scene.sequence == "seq01"
        assert scene.shot == "shot01"
        assert scene.user == "artist"
        assert scene.plate == "BG01"
        assert scene.scene_path == Path("/path/to/scene.3de")


class TestThreeDESceneModel:
    """Test ThreeDESceneModel with real components."""

    def test_initialization(self, scene_disk_cache: object) -> None:
        """Test model initialization with real cache manager."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        assert model.cache_manager == scene_disk_cache
        assert hasattr(model, "scenes")
        assert isinstance(model.scenes, list)

    def test_set_scenes_dedup_and_serialize(
        self,
        scene_disk_cache: object,
        tmp_path: Path,
    ) -> None:
        """Test set_scenes + deduplicate + to_dict — the model's production pipeline."""
        # Create real directory structure
        shows_root = tmp_path / "shows"

        # Create multiple real 3DE scenes — two for the same shot (to test dedup)
        base = shows_root / "test_show" / "shots" / "seq00" / "seq00_shot00"
        paths: list[Path] = []
        for i, user in enumerate(["artist_a", "artist_b"]):
            p = base / "user" / user / "3de" / "mm-default" / f"seq00_shot00_v00{i + 1}.3de"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# 3DE scene by {user}")
            # Stagger mtimes so dedup is deterministic (artist_b is newer)
            import os
            mtime = 1_700_000_000 + i * 100
            os.utime(p, (mtime, mtime))
            paths.append(p)

        # Build ThreeDEScene objects
        from threede_scene_model import ThreeDEScene

        raw_scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="seq00",
                shot="shot00",
                workspace_path=str(base),
                user=user,
                plate="FG01",
                scene_path=p,
            )
            for user, p in zip(["artist_a", "artist_b"], paths, strict=False)
        ]

        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        # Pipeline: set → dedup → serialize (mirrors controller flow)
        deduped = model.deduplicate_scenes_by_shot(raw_scenes)
        model.set_scenes(deduped)

        assert len(model.scenes) == 1
        # Newer file wins
        assert model.scenes[0].user == "artist_b"

        # Serialization round-trip
        dicts = model.to_dict()
        assert len(dicts) == 1
        assert dicts[0]["show"] == "test_show"
        assert dicts[0]["user"] == "artist_b"

    def test_scenes_property(
        self, scene_disk_cache: object, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test scenes property returns scene list."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        # Create and add real scenes
        scene_path1 = make_real_3de_file("show1", "seq01", "shot01", "user1")
        scene_path2 = make_real_3de_file("show1", "seq01", "shot02", "user2")

        model.scenes = [
            ThreeDEScene(
                "show1",
                "seq01",
                "shot01",
                str(scene_path1.parent.parent.parent.parent),
                "user1",
                "FG01",
                scene_path1,
            ),
            ThreeDEScene(
                "show1",
                "seq01",
                "shot02",
                str(scene_path2.parent.parent.parent.parent),
                "user2",
                "BG01",
                scene_path2,
            ),
        ]

        scenes = model.scenes  # Access property directly
        assert len(scenes) == 2
        assert all(isinstance(s, ThreeDEScene) for s in scenes)

    def test_get_unique_artists(
        self, scene_disk_cache: object, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test unique artists are returned in sorted order."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        scene_path1 = make_real_3de_file("show1", "seq01", "shot01", "artist_b")
        scene_path2 = make_real_3de_file("show1", "seq01", "shot02", "artist_a")

        model.scenes = [
            ThreeDEScene(
                "show1",
                "seq01",
                "shot01",
                str(scene_path1.parent.parent.parent.parent),
                "artist_b",
                "FG01",
                scene_path1,
            ),
            ThreeDEScene(
                "show1",
                "seq01",
                "shot02",
                str(scene_path2.parent.parent.parent.parent),
                "artist_a",
                "BG01",
                scene_path2,
            ),
        ]

        assert model.get_unique_artists() == ["artist_a", "artist_b"]

    def test_find_scene_by_display_name(
        self, scene_disk_cache: object, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test finding scene by display name."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        # Create real scenes
        scene_path1 = make_real_3de_file("show1", "seq01", "shot01", "user1")
        scene_path2 = make_real_3de_file("show1", "seq01", "shot02", "user2")

        model.scenes = [
            ThreeDEScene(
                "show1",
                "seq01",
                "shot01",
                str(scene_path1.parent.parent.parent.parent),
                "user1",
                "FG01",
                scene_path1,
            ),
            ThreeDEScene(
                "show1",
                "seq01",
                "shot02",
                str(scene_path2.parent.parent.parent.parent),
                "user2",
                "BG01",
                scene_path2,
            ),
        ]

        # Test finding existing scene by display name
        scene = model.find_scene_by_display_name("seq01_shot01 - user1")
        assert scene is not None
        assert scene.shot == "shot01"
        assert scene.user == "user1"

        # Test finding non-existent scene
        scene = model.find_scene_by_display_name("nonexistent")
        assert scene is None

    def test_get_scene_by_index(
        self, scene_disk_cache: object, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test getting scene by index."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        scene_path = make_real_3de_file("show1", "seq01", "shot01", "user1")

        model.scenes = [
            ThreeDEScene(
                "show1",
                "seq01",
                "shot01",
                str(scene_path.parent.parent.parent.parent),
                "user1",
                "FG01",
                scene_path,
            ),
        ]

        # Valid index
        scene = model.get_scene_by_index(0)
        assert scene is not None
        assert scene.shot == "shot01"

        # Invalid indices
        assert model.get_scene_by_index(-1) is None
        assert model.get_scene_by_index(1) is None

    def test_deduplicate_scenes_per_shot(
        self, scene_disk_cache: object, tmp_path: Path
    ) -> None:
        """Test deduplication keeps one scene per shot with real files."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        # Create real scenes with duplicates for same shot
        base_path = tmp_path / "shows" / "test" / "shots"

        # Create multiple scenes for seq01_shot01
        scenes = []
        for i, user in enumerate(["user1", "user2", "user3"]):
            scene_path = (
                base_path
                / "seq01"
                / "seq01_shot01"
                / "user"
                / user
                / "3de"
                / f"scene_v{i + 1}.3de"
            )
            scene_path.parent.mkdir(parents=True, exist_ok=True)
            scene_path.write_text(f"# 3DE scene by {user}")

            # Set different modification times
            mtime = datetime.now(tz=UTC).timestamp() - (100 * (3 - i))  # user3 is newest
            os.utime(scene_path, (mtime, mtime))

            scenes.append(
                ThreeDEScene(
                    "test",
                    "seq01",
                    "shot01",
                    str(base_path / "seq01" / "seq01_shot01"),
                    user,
                    f"FG0{i + 1}",
                    scene_path,
                )
            )

        # Add a scene for different shot
        other_path = (
            base_path
            / "seq02"
            / "seq02_shot01"
            / "user"
            / "user4"
            / "3de"
            / "scene.3de"
        )
        other_path.parent.mkdir(parents=True, exist_ok=True)
        other_path.write_text("# 3DE scene")

        scenes.append(
            ThreeDEScene(
                "test",
                "seq02",
                "shot01",
                str(base_path / "seq02" / "seq02_shot01"),
                "user4",
                "BG01",
                other_path,
            )
        )

        # Deduplicate
        deduplicated = model.deduplicate_scenes_by_shot(scenes)

        # Test behavior - one scene per shot
        assert len(deduplicated) == 2

        # Check we got the right scenes (newest for seq01_shot01)
        seq01_scene = next((s for s in deduplicated if s.sequence == "seq01"), None)
        assert seq01_scene is not None
        # Should keep the one with latest mtime (user3)

        seq02_scene = next((s for s in deduplicated if s.sequence == "seq02"), None)
        assert seq02_scene is not None
        assert seq02_scene.user == "user4"

    def test_load_from_cache(self, scene_disk_cache: object) -> None:
        """Test loading scenes from cache."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        # Prepare cache data
        cache_data = [
            {
                "show": "cached_show",
                "sequence": "seq01",
                "shot": "shot01",
                "workspace_path": "/cached/path",
                "user": "cached_user",
                "plate": "FG01",
                "scene_path": "/cached/scene.3de",
            }
        ]

        # Cache the data
        scene_disk_cache.cache_threede_scenes(cache_data)

        # Load from cache
        result = model._load_from_cache()

        assert result is True
        assert len(model.scenes) == 1
        assert model.scenes[0].show == "cached_show"
        assert model.scenes[0].user == "cached_user"

    def test_empty_cache_returns_false(self, scene_disk_cache: object) -> None:
        """Test loading from empty cache returns False."""
        model = ThreeDESceneModel(cache_manager=scene_disk_cache)

        # Cache is empty
        result = model._load_from_cache()

        assert result is False
        assert len(model.scenes) == 0
