"""Parameterized contract tests for MayaLatestFinder and ThreeDELatestFinder.

These tests verify shared behavior from VersionHandlingMixin and common
find_latest / find_all semantics that both finders must satisfy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from discovery import MayaLatestFinder
from threede import ThreeDELatestFinder
from utils import get_current_username
from version_mixin import VersionHandlingMixin


_USERNAME: str = get_current_username()


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class FinderAdapter:
    """Adapter normalizing finder APIs for contract testing."""

    finder: Any
    find_latest: Callable[..., Path | None]
    find_all: Callable[..., list[Path]]
    version_pattern_str: str
    app_name: str  # "Maya" or "3DE"
    create_scene_dir: Callable[..., Path]
    create_versioned_file: Callable[[Path, int], Path]


# ---------------------------------------------------------------------------
# Directory / file helpers
# ---------------------------------------------------------------------------


def _create_maya_dir(workspace: Path, username: str = _USERNAME) -> Path:
    scenes = workspace / "user" / username / "mm" / "maya" / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    return scenes


def _create_threede_dir(workspace: Path, username: str = _USERNAME) -> Path:
    scenes = (
        workspace
        / "user"
        / username
        / "mm"
        / "3de"
        / "mm-default"
        / "scenes"
        / "scene"
        / "FG01"
    )
    scenes.mkdir(parents=True, exist_ok=True)
    return scenes


def _create_maya_file(scenes_dir: Path, version: int) -> Path:
    f = scenes_dir / f"scene_v{version:03d}.ma"
    f.touch()
    return f


def _create_threede_file(scenes_dir: Path, version: int) -> Path:
    f = scenes_dir / f"track_v{version:03d}.3de"
    f.touch()
    return f


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(params=["maya", "threede"])
def finder_adapter(request: pytest.FixtureRequest) -> FinderAdapter:
    """Parameterized fixture yielding a FinderAdapter for each finder type."""
    if request.param == "maya":
        finder = MayaLatestFinder()
        return FinderAdapter(
            finder=finder,
            find_latest=finder.find_latest_scene,
            find_all=MayaLatestFinder.find_all_scenes,
            version_pattern_str=r"_v(\d{3})\.(ma|mb)$",
            app_name="Maya",
            create_scene_dir=_create_maya_dir,
            create_versioned_file=_create_maya_file,
        )
    finder = ThreeDELatestFinder()
    return FinderAdapter(
        finder=finder,
        find_latest=finder.find_latest_scene,
        find_all=ThreeDELatestFinder.find_all_scenes,
        version_pattern_str=r"_v(\d{3})\.3de$",
        app_name="3DE",
        create_scene_dir=_create_threede_dir,
        create_versioned_file=_create_threede_file,
    )


# ---------------------------------------------------------------------------
# Contract: initialization
# ---------------------------------------------------------------------------


class TestFinderInitContract:
    """Contract: both finders share the same initialization guarantees."""

    def test_initialization(self, finder_adapter: FinderAdapter) -> None:
        """Finder initializes and exposes logger and VERSION_PATTERN."""
        finder = finder_adapter.finder
        assert finder is not None
        assert hasattr(finder, "logger")
        assert hasattr(finder, "VERSION_PATTERN")

    def test_has_version_pattern(self, finder_adapter: FinderAdapter) -> None:
        """VERSION_PATTERN matches the expected app-specific pattern string."""
        finder = finder_adapter.finder
        assert finder.VERSION_PATTERN.pattern == finder_adapter.version_pattern_str

    def test_inherits_version_mixin(self, finder_adapter: FinderAdapter) -> None:
        """Finder inherits all VersionHandlingMixin methods."""
        finder = finder_adapter.finder
        assert isinstance(finder, VersionHandlingMixin)
        assert hasattr(finder, "_extract_version")
        assert hasattr(finder, "_find_latest_by_version")
        assert hasattr(finder, "_sort_files_by_version")


# ---------------------------------------------------------------------------
# Contract: find_latest
# ---------------------------------------------------------------------------


class TestFindLatestContract:
    """Contract: find_latest returns expected results for shared edge cases."""

    def test_find_latest_single_file(
        self, finder_adapter: FinderAdapter, tmp_path: Path
    ) -> None:
        """Single versioned file is returned as the latest."""
        scenes_dir = finder_adapter.create_scene_dir(tmp_path)
        created = finder_adapter.create_versioned_file(scenes_dir, 1)

        result = finder_adapter.find_latest(str(tmp_path))

        assert result is not None
        assert result == created

    def test_find_latest_picks_highest_version(
        self, finder_adapter: FinderAdapter, tmp_path: Path
    ) -> None:
        """Highest version number wins regardless of creation order."""
        scenes_dir = finder_adapter.create_scene_dir(tmp_path)
        finder_adapter.create_versioned_file(scenes_dir, 1)
        finder_adapter.create_versioned_file(scenes_dir, 3)
        finder_adapter.create_versioned_file(scenes_dir, 2)

        result = finder_adapter.find_latest(str(tmp_path))

        assert result is not None
        assert "v003" in result.name

    def test_find_latest_across_users(
        self, finder_adapter: FinderAdapter, tmp_path: Path
    ) -> None:
        """Only files from the current user are found; other users are filtered out."""
        scenes_other = finder_adapter.create_scene_dir(
            tmp_path, username="other-artist"
        )
        finder_adapter.create_versioned_file(scenes_other, 5)

        scenes_me = finder_adapter.create_scene_dir(tmp_path, username=_USERNAME)
        finder_adapter.create_versioned_file(scenes_me, 2)

        result = finder_adapter.find_latest(str(tmp_path))

        assert result is not None
        assert "v002" in result.name
        assert _USERNAME in str(result)

    def test_empty_workspace_returns_none(
        self, finder_adapter: FinderAdapter, tmp_path: Path
    ) -> None:
        """An existing but empty workspace directory returns None."""
        workspace = tmp_path / "empty_workspace"
        workspace.mkdir()

        result = finder_adapter.find_latest(str(workspace))

        assert result is None

    def test_nonexistent_workspace_returns_none(
        self, finder_adapter: FinderAdapter
    ) -> None:
        """A path that does not exist on disk returns None."""
        result = finder_adapter.find_latest("/nonexistent/path/does/not/exist")

        assert result is None

    def test_empty_path_returns_none(self, finder_adapter: FinderAdapter) -> None:
        """An empty string as workspace path returns None."""
        result = finder_adapter.find_latest("")

        assert result is None

    def test_no_user_directory_returns_none(
        self, finder_adapter: FinderAdapter, tmp_path: Path
    ) -> None:
        """Workspace exists but has no 'user' subdirectory returns None."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Deliberately no 'user' subdirectory

        result = finder_adapter.find_latest(str(workspace))

        assert result is None


# ---------------------------------------------------------------------------
# Contract: find_all
# ---------------------------------------------------------------------------


class TestFindAllContract:
    """Contract: find_all returns expected results for shared edge cases."""

    def test_empty_workspace_returns_empty_list(
        self, finder_adapter: FinderAdapter, tmp_path: Path
    ) -> None:
        """Existing but empty workspace directory returns an empty list."""
        workspace = tmp_path / "empty"
        workspace.mkdir()

        result = finder_adapter.find_all(str(workspace))

        assert result == []

    def test_nonexistent_returns_empty_list(
        self, finder_adapter: FinderAdapter
    ) -> None:
        """Path that does not exist returns an empty list."""
        result = finder_adapter.find_all("/nonexistent/path/does/not/exist")

        assert result == []

    def test_empty_path_returns_empty_list(self, finder_adapter: FinderAdapter) -> None:
        """Empty string as workspace path returns an empty list."""
        result = finder_adapter.find_all("")

        assert result == []


# ---------------------------------------------------------------------------
# Maya-specific tests
# ---------------------------------------------------------------------------


class TestMayaSpecific:
    """Tests for Maya-specific behaviors not covered by the shared contract."""

    def test_find_latest_mixed_extensions(self, tmp_path: Path) -> None:
        """Mixed .ma and .mb files are all considered; highest version wins."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        (maya_scenes / "model_v001.ma").touch()
        (maya_scenes / "model_v002.mb").touch()
        (maya_scenes / "model_v003.ma").touch()

        finder = MayaLatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "model_v003.ma"

    def test_exclude_autosave_by_default(self, tmp_path: Path) -> None:
        """Autosave files are excluded from find_all_scenes results."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene_v001.ma.autosave").touch()
        (maya_scenes / "backup.autosave.mb").touch()

        all_scenes = MayaLatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "scene_v001.ma"

    def test_autosave_files_always_excluded(self, tmp_path: Path) -> None:
        """Autosave files are always excluded (no opt-in parameter exists)."""
        workspace = tmp_path / "workspace"
        maya_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        maya_scenes.mkdir(parents=True)

        (maya_scenes / "scene_v001.ma").touch()
        (maya_scenes / "scene.ma.autosave").touch()
        (maya_scenes / "model.autosave.mb").touch()

        all_scenes = MayaLatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "scene_v001.ma"

    def test_version_extraction_ma_and_mb(self, tmp_path: Path) -> None:
        """_extract_version works for both .ma and .mb files."""
        finder = MayaLatestFinder()

        ma_file = tmp_path / "scene_v042.ma"
        ma_file.touch()
        assert finder._extract_version(ma_file) == 42

        mb_file = tmp_path / "model_v007.mb"
        mb_file.touch()
        assert finder._extract_version(mb_file) == 7

        other_file = tmp_path / "scene.ma"
        other_file.touch()
        assert finder._extract_version(other_file) is None

    def test_symlinks_in_structure(self, tmp_path: Path) -> None:
        """Symlinks in the workspace structure do not surface other-user files."""
        workspace = tmp_path / "workspace"
        real_scenes = workspace / "user" / _USERNAME / "mm" / "maya" / "scenes"
        real_scenes.mkdir(parents=True)
        (real_scenes / "scene_v001.ma").touch()

        # Symlink from another user's directory into current user's maya dir
        link_target = workspace / "user" / "other-artist"
        link_target.mkdir(parents=True)
        symlink = link_target / "maya"
        symlink.symlink_to(workspace / "user" / _USERNAME / "maya")

        finder = MayaLatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert _USERNAME in str(latest)

    def test_permission_denied_raises(self, tmp_path: Path) -> None:
        """PermissionError from iterdir propagates (not silently swallowed)."""
        workspace = tmp_path / "workspace"
        (workspace / "user").mkdir(parents=True)

        finder = MayaLatestFinder()

        with (
            patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")),
            pytest.raises(PermissionError),
        ):
            finder.find_latest_scene(str(workspace))


# ---------------------------------------------------------------------------
# 3DE-specific tests
# ---------------------------------------------------------------------------


class TestThreedeSpecific:
    """Tests for 3DE-specific behaviors not covered by the shared contract."""

    def _base_3de(self, workspace: Path) -> Path:
        """Return the base 3DE scenes path (without plate subdirectory)."""
        return (
            workspace
            / "user"
            / _USERNAME
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )

    def test_find_latest_across_plates(self, tmp_path: Path) -> None:
        """find_latest_scene picks the highest version across all plate directories."""
        workspace = tmp_path / "workspace"
        base = self._base_3de(workspace)

        fg_dir = base / "FG01"
        fg_dir.mkdir(parents=True)
        (fg_dir / "track_v002.3de").touch()
        (fg_dir / "track_v004.3de").touch()

        bg_dir = base / "BG01"
        bg_dir.mkdir(parents=True)
        (bg_dir / "track_v001.3de").touch()

        pl_dir = base / "PL01"
        pl_dir.mkdir(parents=True)
        (pl_dir / "track_v006.3de").touch()

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "track_v006.3de"
        assert "PL01" in str(latest.parent)

    def test_special_3de_directory_structure(self, tmp_path: Path) -> None:
        """Only files at the correct directory depth are found; shallower paths ignored."""
        workspace = tmp_path / "workspace"

        correct_path = self._base_3de(workspace) / "FG01"
        correct_path.mkdir(parents=True)
        (correct_path / "track_v001.3de").touch()

        # Wrong structure (missing several intermediate directories)
        wrong_path = workspace / "user" / _USERNAME / "3de" / "scenes"
        wrong_path.mkdir(parents=True)
        (wrong_path / "track_v002.3de").touch()

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "track_v001.3de"

    def test_find_all_across_plates(self, tmp_path: Path) -> None:
        """find_all_scenes returns one file per plate when each plate has one file."""
        workspace = tmp_path / "workspace"
        base = self._base_3de(workspace)

        for plate in ("FG01", "BG01", "PL01"):
            plate_dir = base / plate
            plate_dir.mkdir(parents=True)
            (plate_dir / "track_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 3
        parent_dirs = [s.parent.name for s in all_scenes]
        assert "FG01" in parent_dirs
        assert "BG01" in parent_dirs
        assert "PL01" in parent_dirs

    def test_version_extraction_threede(self, tmp_path: Path) -> None:
        """_extract_version works for .3de files and returns None for unversioned names."""
        finder = ThreeDELatestFinder()

        versioned = tmp_path / "track_v042.3de"
        versioned.touch()
        assert finder._extract_version(versioned) == 42

        unversioned = tmp_path / "track.3de"
        unversioned.touch()
        assert finder._extract_version(unversioned) is None

    def test_standard_plate_names(self, tmp_path: Path) -> None:
        """Standard VFX plate names (FG, BG, PL, BC, MP) are all discovered."""
        workspace = tmp_path / "workspace"
        base = self._base_3de(workspace)

        plates = ["FG01", "FG02", "BG01", "BG02", "PL01", "BC01", "MP01"]
        for plate in plates:
            plate_dir = base / plate
            plate_dir.mkdir(parents=True)
            (plate_dir / f"track_{plate}_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == len(plates)
        parent_names = {s.parent.name for s in all_scenes}
        assert parent_names == set(plates)

    def test_non_standard_plate_names(self, tmp_path: Path) -> None:
        """Non-standard plate directory names are also discovered."""
        workspace = tmp_path / "workspace"
        base = self._base_3de(workspace)

        custom_dir = base / "CustomPlate"
        custom_dir.mkdir(parents=True)
        (custom_dir / "track_v001.3de").touch()

        num_dir = base / "001"
        num_dir.mkdir(parents=True)
        (num_dir / "track_v001.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 2

    def test_deeply_nested_plates_not_found(self, tmp_path: Path) -> None:
        """Files nested deeper than the plate directory are not returned."""
        workspace = tmp_path / "workspace"
        base = self._base_3de(workspace)

        nested = base / "FG01" / "subfolder"
        nested.mkdir(parents=True)
        (nested / "track_v001.3de").touch()

        regular = base / "BG01"
        regular.mkdir(parents=True)
        (regular / "track_v002.3de").touch()

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 1
        assert all_scenes[0].name == "track_v002.3de"

    def test_symlinks_in_structure(self, tmp_path: Path) -> None:
        """Symlinked plate directories under other-user paths are filtered out."""
        workspace = tmp_path / "workspace"
        real_3de = self._base_3de(workspace) / "FG01"
        real_3de.mkdir(parents=True)
        (real_3de / "track_v001.3de").touch()

        link_base = (
            workspace
            / "user"
            / "other-artist"
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )
        link_base.mkdir(parents=True)
        symlink = link_base / "FG01"
        symlink.symlink_to(real_3de)

        all_scenes = ThreeDELatestFinder.find_all_scenes(str(workspace))

        assert len(all_scenes) == 1

    def test_special_characters_in_filenames(self, tmp_path: Path) -> None:
        """Filenames with hyphens and underscores are handled; highest version wins."""
        workspace = tmp_path / "workspace"
        scenes = self._base_3de(workspace) / "FG-01"
        scenes.mkdir(parents=True)

        (scenes / "track-final_v001.3de").touch()
        (scenes / "shot_010_track_v002.3de").touch()

        finder = ThreeDELatestFinder()
        latest = finder.find_latest_scene(str(workspace))

        assert latest is not None
        assert latest.name == "shot_010_track_v002.3de"
