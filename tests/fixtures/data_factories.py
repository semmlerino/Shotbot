"""Data factory fixtures for creating test data.

This module provides factory fixtures for creating test data instances
including shots, 3DE scenes, and VFX directory structures.

Fixtures:
    sample_shot_data: Sample shot dictionary
    sample_threede_scene_data: Sample 3DE scene dictionary
    make_test_shot: Factory for creating Shot instances
    make_test_filesystem: Factory for creating TestFileSystem instances
    make_real_3de_file: Factory for creating 3DE files in VFX structure
    real_shot_model: Factory for creating ShotModel instances
    mock_subprocess_workspace: Mock subprocess for VFX workspace commands
    mock_environment: Mock environment variables
    isolated_test_environment: Environment with cache clearing
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator

    from PySide6.QtWidgets import QApplication


# ==============================================================================
# Sample Data Fixtures
# ==============================================================================


@pytest.fixture
def sample_shot_data() -> dict[str, object]:
    """Sample shot data for testing."""
    return {
        "show": "TestShow",
        "sequence": "SEQ001",
        "shot": "0010",
        "workspace_path": "/shows/TestShow/shots/SEQ001/SEQ001_0010",
    }


@pytest.fixture
def sample_threede_scene_data() -> dict[str, object]:
    """Sample 3DE scene data for testing."""
    return {
        "filepath": "/shows/TestShow/shots/SEQ001/SEQ001_0010/user/test_user/3de/SEQ001_0010_v001.3de",
        "show": "TestShow",
        "sequence": "SEQ001",
        "shot": "0010",
        "user": "test_user",
        "filename": "SEQ001_0010_v001.3de",
        "modified_time": 1234567890.0,
        "workspace_path": "/shows/TestShow/shots/SEQ001/SEQ001_0010",
    }


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
    from tests.fixtures.doubles_extended import TestFileSystem

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
        cache_manager: CacheManager fixture from temp_directories

    """
    from shot_model import ShotModel

    # Create shows root
    shows_root = tmp_path / "shows"
    shows_root.mkdir(exist_ok=True)

    # Create ShotModel instance with test process pool and shared cache manager
    return ShotModel(cache_manager=cache_manager, process_pool=test_process_pool)


# ==============================================================================
# Mock Fixtures
# ==============================================================================


@pytest.fixture
def mock_subprocess_workspace() -> Iterator[None]:
    """Mock subprocess.run for tests that call VFX workspace commands.

    Use this fixture explicitly in tests that need subprocess mocking.
    Most tests don't need subprocess mocking at all.

    Provides:
    - Mock responses for 'ws' (workspace) commands
    - Prevents "ws: command not found" errors
    - Returns realistic workspace command output
    """

    def mock_run_side_effect(*args, **kwargs):
        """Mock subprocess.run with realistic workspace command responses."""
        # Extract the command being run
        cmd = args[0] if args else kwargs.get("args", [])

        # Normalize to string for matching (handle both list and string forms)
        text = " ".join(cmd) if isinstance(cmd, list) else (cmd or "")

        # Handle workspace commands (ws)
        if " ws " in f" {text} " or text.strip().startswith("ws"):
            # Return realistic workspace command output
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "workspace /shows/test_show/shots/seq01/seq01_0010"
            mock_result.stderr = ""
            return mock_result

        # Default: return empty but successful result
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        return mock_result

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        yield


@pytest.fixture
def mock_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Set up mock environment variables for testing.

    Uses monkeypatch.setenv for safer environment manipulation that
    doesn't clear the entire environment mapping (which can surprise
    other threads).
    """
    # Set test environment using monkeypatch (safer than clearing os.environ)
    monkeypatch.setenv("SHOTBOT_MODE", "test")
    monkeypatch.setenv("USER", "test_user")

    # Cleanup is automatic via monkeypatch
    return {
        "SHOTBOT_MODE": "test",
        "USER": "test_user",
    }


@pytest.fixture
def isolated_test_environment(qapp: QApplication) -> Iterator[None]:
    """Provide isolated test environment with cache clearing for Qt widgets.

    This fixture ensures complete test isolation by:
    1. Clearing all utility caches (VersionUtils, path cache, etc.)
    2. Processing Qt events to ensure clean state
    3. Providing proper cleanup after test execution

    Critical for parallel test execution with pytest-xdist to prevent
    cache pollution between tests running in different workers.

    Args:
        qapp: QApplication fixture from qt_bootstrap

    """
    from PySide6.QtCore import QCoreApplication, QEvent

    from utils import clear_all_caches

    # Clear all utility caches before test
    clear_all_caches()

    # Process Qt events for clean state
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    yield

    # Clear caches after test for next test's isolation
    clear_all_caches()

    # Final Qt cleanup
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
