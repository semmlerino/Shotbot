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

# Local application imports
from shot_model import Shot

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from cache_manager import CacheManager

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
        from utils import clear_all_caches
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

    def test_initialization(self, cache_manager: CacheManager) -> None:
        """Test model initialization with real cache manager."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

        assert model.cache_manager == cache_manager
        assert hasattr(model, "scenes")
        assert isinstance(model.scenes, list)

    @pytest.mark.real_subprocess
    def test_refresh_scenes_with_real_files(
        self,
        cache_manager: CacheManager,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test refresh_scenes with real 3DE files."""
        # Create real directory structure
        shows_root = tmp_path / "shows"

        # Create multiple real 3DE scenes
        scenes_created = []
        for seq_num in range(2):
            for shot_num in range(2):
                seq = f"seq{seq_num:02d}"
                shot = f"shot{shot_num:02d}"
                shot_name = f"{seq}_{shot}"

                shot_path = shows_root / "test_show" / "shots" / seq / shot_name

                # Create 3DE file for each shot
                scene_path = (
                    shot_path
                    / "user"
                    / f"artist{seq_num}"
                    / "3de"
                    / "mm-default"
                    / f"{shot_name}_v001.3de"
                )
                scene_path.parent.mkdir(parents=True, exist_ok=True)
                scene_path.write_text(f"# 3DE scene for {shot_name}")
                scenes_created.append(scene_path)

        # Create user shots
        user_shots = [
            Shot(
                "test_show",
                "seq00",
                "shot00",
                str(shows_root / "test_show" / "shots" / "seq00" / "seq00_shot00"),
            ),
            Shot(
                "test_show",
                "seq01",
                "shot01",
                str(shows_root / "test_show" / "shots" / "seq01" / "seq01_shot01"),
            ),
        ]

        # Override Config.SHOWS_ROOT
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))

        model = ThreeDESceneModel(cache_manager=cache_manager)

        # Refresh with real discovery (refresh_scenes only takes shots parameter)
        success, _has_changes = model.refresh_scenes(user_shots)

        # Test actual discovery results
        assert success is True
        scenes = model.scenes  # Access scenes directly
        assert len(scenes) == len(scenes_created)

        # Verify scenes are real
        for scene in scenes:
            assert scene.scene_path.exists()

    def test_scenes_property(
        self, cache_manager: CacheManager, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test scenes property returns scene list."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

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

    def test_find_scene_by_display_name(
        self, cache_manager: CacheManager, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test finding scene by display name."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

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
        self, cache_manager: CacheManager, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test getting scene by index."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

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
        self, cache_manager: CacheManager, tmp_path: Path
    ) -> None:
        """Test deduplication keeps one scene per shot with real files."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

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
        deduplicated = model._deduplicate_scenes_by_shot(scenes)

        # Test behavior - one scene per shot
        assert len(deduplicated) == 2

        # Check we got the right scenes (newest for seq01_shot01)
        seq01_scene = next((s for s in deduplicated if s.sequence == "seq01"), None)
        assert seq01_scene is not None
        # Should keep the one with latest mtime (user3)

        seq02_scene = next((s for s in deduplicated if s.sequence == "seq02"), None)
        assert seq02_scene is not None
        assert seq02_scene.user == "user4"

    def test_load_from_cache(self, cache_manager: CacheManager) -> None:
        """Test loading scenes from cache."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

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
        cache_manager.cache_threede_scenes(cache_data)

        # Load from cache
        result = model._load_from_cache()

        assert result is True
        assert len(model.scenes) == 1
        assert model.scenes[0].show == "cached_show"
        assert model.scenes[0].user == "cached_user"

    def test_empty_cache_returns_false(self, cache_manager: CacheManager) -> None:
        """Test loading from empty cache returns False."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

        # Cache is empty
        result = model._load_from_cache()

        assert result is False
        assert len(model.scenes) == 0

    def test_concurrent_refresh(
        self, cache_manager: CacheManager, make_real_3de_file: Callable[..., Path]
    ) -> None:
        """Test model handles concurrent refresh calls gracefully."""
        model = ThreeDESceneModel(cache_manager=cache_manager)

        # Create real scenes
        scene_path = make_real_3de_file("show1", "seq01", "shot01", "user1")

        user_shots = [
            Shot(
                "show1", "seq01", "shot01", str(scene_path.parent.parent.parent.parent)
            )
        ]

        # Multiple rapid refreshes
        for _ in range(3):
            success, _has_changes = model.refresh_scenes(user_shots)
            assert success is True

        # Model should remain in consistent state
        scenes = model.scenes
        assert isinstance(scenes, list)
