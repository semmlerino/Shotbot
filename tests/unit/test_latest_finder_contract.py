"""Parameterized contract tests for MayaLatestFinder and ThreeDELatestFinder.

These tests verify shared behavior from VersionHandlingMixin and common
find_latest / find_all semantics that both finders must satisfy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
