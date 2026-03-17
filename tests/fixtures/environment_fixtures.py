"""Environment, cache, and data factory fixtures.

Consolidated from:
- caching.py:         Cache utilities and cache-isolation fixtures
- temp_directories.py: Temp directory and CacheCoordinator fixtures
- data_factories.py:  Factory fixtures for shot data and filesystem structures

Functions (caching):
    clear_all_caches: Clear all utility caches
    disable_caching:  Disable caching for a test
    enable_caching:   Re-enable caching after a test
    CacheIsolation:   Context manager for cache isolation

Fixtures (caching):
    caching_enabled:        Enable caching with isolated temp directory
    isolated_cache_manager: CacheCoordinator with isolated temp directory

Fixtures (temp_directories):
    temp_cache_dir:  Temporary cache directory
    cache_manager:   CacheCoordinator instance with temp cache dir
    shot_cache:      ShotDataCache extracted from cache_manager
    scene_disk_cache: SceneDiskCache extracted from cache_manager

Fixtures (data_factories):
    make_test_shot:       Factory for creating Shot instances
    make_test_filesystem: Factory for creating TestFileSystem instances
    make_real_3de_file:   Factory for creating 3DE files in VFX structure
    real_shot_model:      Factory for creating ShotModel instances
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# caching contents
# ---------------------------------------------------------------------------
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    from cache import CacheCoordinator


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache management utilities (test-only infrastructure)
# ---------------------------------------------------------------------------


def clear_all_caches() -> None:
    """Clear all utility caches — useful for test isolation."""
    from paths.validators import clear_path_cache
    from version_utils import VersionUtils

    clear_path_cache()
    VersionUtils.clear_version_cache()
    VersionUtils.extract_version_from_path.cache_clear()
    _logger.debug("Cleared all utility caches")


def disable_caching() -> None:
    """Disable caching completely for a test."""
    from paths.validators import disable_path_caching

    disable_path_caching()
    clear_all_caches()
    _logger.debug("Caching disabled for testing")


def enable_caching() -> None:
    """Re-enable caching after a test."""
    from paths.validators import enable_path_caching

    enable_path_caching()
    _logger.debug("Caching re-enabled after testing")


class CacheIsolation:
    """Context manager for cache isolation in tests.

    Clears and disables all utility caches for the duration of the block,
    then re-enables caching on exit.
    """

    def __enter__(self) -> CacheIsolation:
        """Enter context with isolated cache."""
        clear_all_caches()
        disable_caching()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context and restore caching."""
        enable_caching()
        _logger.debug("Cache isolation context exited")


# ---------------------------------------------------------------------------
# pytest fixtures (caching)
# ---------------------------------------------------------------------------


@pytest.fixture
def caching_enabled(tmp_path: Path) -> Iterator[Path]:
    """Enable caching with isolated temp directory for cache behavior tests.

    This fixture:
    - Creates an isolated cache directory in tmp_path
    - Sets SHOTBOT_TEST_CACHE_DIR environment variable
    - Enables path caching (re-enables if disabled)
    - Clears all caches before test

    Use this for tests that verify cache hit/miss behavior, TTL expiration,
    cache persistence, etc.

    Yields:
        Path to the isolated cache directory

    Example:
        def test_cache_hit_returns_cached_result(caching_enabled):
            cache_dir = caching_enabled
            # Test cache behavior with caching enabled

    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Save original env var if set
    original_cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")

    # Set isolated cache directory
    os.environ["SHOTBOT_TEST_CACHE_DIR"] = str(cache_dir)

    # Ensure caching is enabled and caches are clear
    clear_all_caches()
    enable_caching()

    _logger.debug("Caching enabled with isolated directory: %s", cache_dir)

    yield cache_dir

    # Cleanup: restore original state
    clear_all_caches()

    if original_cache_dir is not None:
        os.environ["SHOTBOT_TEST_CACHE_DIR"] = original_cache_dir
    else:
        os.environ.pop("SHOTBOT_TEST_CACHE_DIR", None)


@pytest.fixture
def isolated_cache_manager(tmp_path: Path) -> Iterator[CacheCoordinator]:
    """Provide a CacheCoordinator instance with isolated temp directory.

    This fixture:
    - Creates an isolated cache directory
    - Instantiates real cache sub-managers (not test doubles)
    - Properly shuts down the coordinator after test

    Use this for integration tests that need to test cache behavior
    with real file I/O but isolated from the production cache.

    Yields:
        CacheCoordinator instance with isolated cache directory

    Example:
        def test_cache_persistence(isolated_cache_manager):
            coordinator = isolated_cache_manager
            coordinator.shot_cache.cache_shots([shot_data])
            # Verify data is persisted

    """
    from cache import (
        CacheCoordinator,
        LatestFileCache,
        SceneDiskCache,
        ShotDataCache,
        ThumbnailCache,
    )

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    thumbnail_cache = ThumbnailCache(cache_dir)
    shot_cache = ShotDataCache(cache_dir)
    scene_disk_cache = SceneDiskCache(cache_dir)
    latest_file_cache = LatestFileCache(cache_dir)
    coordinator = CacheCoordinator(cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)

    _logger.debug("Created isolated CacheCoordinator at: %s", cache_dir)

    yield coordinator

    # Cleanup
    try:
        coordinator.shutdown()
    except Exception as e:  # noqa: BLE001
        _logger.debug("CacheCoordinator shutdown exception: %s", e)


# ---------------------------------------------------------------------------
# temp_directories contents
# ---------------------------------------------------------------------------

import tempfile


@pytest.fixture
def temp_cache_dir() -> Iterator[Path]:
    """Create temporary cache directory for testing.

    Yields:
        Path to a temporary directory for cache files

    """
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = Path(temp_dir)
        yield cache_dir


@pytest.fixture
def cache_manager(temp_cache_dir: Path) -> Iterator[object]:
    """Create CacheCoordinator instance for testing.

    Uses temp_cache_dir to ensure isolation between tests.

    Args:
        temp_cache_dir: Temporary cache directory fixture

    Yields:
        CacheCoordinator instance configured with temp directory

    """
    from cache import (
        CacheCoordinator,
        LatestFileCache,
        SceneDiskCache,
        ShotDataCache,
        ThumbnailCache,
    )

    thumbnail_cache = ThumbnailCache(temp_cache_dir)
    shot_cache = ShotDataCache(temp_cache_dir)
    scene_disk_cache = SceneDiskCache(temp_cache_dir)
    latest_file_cache = LatestFileCache(temp_cache_dir)
    manager = CacheCoordinator(temp_cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)
    yield manager
    # Cleanup
    manager.clear_cache()


@pytest.fixture
def shot_cache(cache_manager: object) -> object:
    """Extract ShotDataCache from the CacheCoordinator fixture."""
    return cache_manager.shot_cache  # type: ignore[attr-defined]


@pytest.fixture
def scene_disk_cache(cache_manager: object) -> object:
    """Extract SceneDiskCache from the CacheCoordinator fixture."""
    return cache_manager.scene_disk_cache  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# data_factories contents
# ---------------------------------------------------------------------------


@pytest.fixture
def make_test_shot(tmp_path: Path):
    """Factory fixture for creating test Shot instances.

    Implements TestShotFactory protocol from test_protocols.py.

    Example:
        def test_something(make_test_shot):
            shot = make_test_shot(show="TestShow", with_thumbnail=True)

    """
    from type_definitions import Shot

    def _make_shot(
        show: str = "test",
        sequence: str = "seq01",
        shot: str = "0010",
        with_thumbnail: bool = True,
    ) -> Shot:
        """Create a test Shot instance with optional thumbnail."""
        workspace_path = str(
            tmp_path / "shows" / show / "shots" / sequence / f"{sequence}_{shot}"
        )

        # Create workspace directory
        Path(workspace_path).mkdir(parents=True, exist_ok=True)

        # Create thumbnail if requested
        if with_thumbnail:
            thumbnail_dir = Path(workspace_path) / "editorial" / "thumbnails"
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail_file = thumbnail_dir / f"{sequence}_{shot}.jpg"
            thumbnail_file.write_bytes(b"fake image data")

        return Shot(
            show=show,
            sequence=sequence,
            shot=shot,
            workspace_path=workspace_path,
        )

    return _make_shot


@pytest.fixture
def make_test_filesystem(tmp_path: Path):
    """Factory fixture for creating TestFileSystem instances.

    Returns a callable that creates TestFileSystem instances for
    testing file operations with VFX directory structures.

    Example usage:
        def test_scene_discovery(make_test_filesystem):
            fs = make_test_filesystem()
            shot_path = fs.create_vfx_structure("show1", "seq01", "0010")
            fs.create_file(shot_path / "user/artist/scene.3de", "content")
    """
    from tests.fixtures.model_fixtures import TestFileSystem

    def _make_filesystem() -> TestFileSystem:
        """Create a TestFileSystem instance with tmp_path as base."""
        return TestFileSystem(base_path=tmp_path)

    return _make_filesystem


@pytest.fixture
def make_real_3de_file(tmp_path: Path):
    """Factory fixture for creating real 3DE files in VFX directory structure.

    Returns a callable that creates a complete VFX directory structure with
    a real 3DE file for testing ThreeDEScene functionality.

    Example usage:
        def test_scene(make_real_3de_file):
            scene_path = make_real_3de_file("show1", "seq01", "0010", "artist1")
            # scene_path points to the .3de file
            # scene_path.parent.parent.parent.parent is the workspace_path
    """

    def _make_3de_file(
        show: str,
        seq: str,
        shot: str,
        user: str,
        plate: str = "BG01",
        filename: str = "scene.3de",
    ) -> Path:
        """Create a real 3DE file in VFX directory structure.

        Args:
            show: Show name
            seq: Sequence name
            shot: Shot name
            user: User/artist name
            plate: Plate name (default: "BG01")
            filename: 3DE filename (default: "scene.3de")

        Returns:
            Path to the created 3DE file

        """
        # Create VFX directory structure
        # Structure: shows/{show}/shots/{seq}/{seq}_{shot}/user/{user}/3de/
        workspace_path = tmp_path / "shows" / show / "shots" / seq / f"{seq}_{shot}"
        threede_dir = workspace_path / "user" / user / "3de"
        threede_dir.mkdir(parents=True, exist_ok=True)

        # Create the 3DE file with minimal valid content
        scene_file = threede_dir / filename
        scene_file.write_text(
            f"# 3DE Scene File\n# Show: {show}\n# Seq: {seq}\n# Shot: {shot}\n# User: {user}\n# Plate: {plate}\n"
        )

        return scene_file

    return _make_3de_file


@pytest.fixture
def real_shot_model(tmp_path: Path, test_process_pool, cache_manager):
    """Factory fixture for creating real ShotModel instances with test data.

    Returns a ShotModel instance configured with a temporary shows root,
    a test process pool, and a shared cache manager.

    Args:
        tmp_path: Pytest tmp_path fixture
        test_process_pool: TestProcessPool fixture from test_doubles
        cache_manager: CacheCoordinator fixture from temp_directories

    """
    from shots.shot_model import ShotModel

    # Create shows root
    shows_root = tmp_path / "shows"
    shows_root.mkdir(exist_ok=True)

    # Create ShotModel instance with the shot_cache sub-manager
    model = ShotModel(cache_manager=cache_manager.shot_cache, process_pool=test_process_pool)
    model._force_sync_refresh = True
    return model
