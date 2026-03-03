"""Data factory fixtures for creating test data.

This module provides factory fixtures for creating test data instances
including shots, 3DE scenes, and VFX directory structures.

Fixtures:
    make_test_shot: Factory for creating Shot instances
    make_test_filesystem: Factory for creating TestFileSystem instances
    make_real_3de_file: Factory for creating 3DE files in VFX structure
    real_shot_model: Factory for creating ShotModel instances
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ==============================================================================
# Factory Fixtures
# ==============================================================================


@pytest.fixture
def make_test_shot(tmp_path: Path):
    """Factory fixture for creating test Shot instances.

    Implements TestShotFactory protocol from test_protocols.py.

    Example:
        def test_something(make_test_shot):
            shot = make_test_shot(show="TestShow", with_thumbnail=True)

    """
    from shot_model import Shot

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
    from tests.fixtures.test_doubles import TestFileSystem

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
    from shot_model import ShotModel

    # Create shows root
    shows_root = tmp_path / "shows"
    shows_root.mkdir(exist_ok=True)

    # Create ShotModel instance with the shot_cache sub-manager
    model = ShotModel(cache_manager=cache_manager.shot_cache, process_pool=test_process_pool)
    model._force_sync_refresh = True
    return model

