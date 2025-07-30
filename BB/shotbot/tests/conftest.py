"""Shared fixtures for pytest tests."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shot_model import Shot, ShotModel


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for GUI tests."""
    # Import here to avoid issues when not testing GUI
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Don't quit the app, let pytest handle it


@pytest.fixture
def sample_shot():
    """Create a sample Shot instance."""
    return Shot(
        show="testshow",
        sequence="101_ABC",
        shot="0010",
        workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
    )


@pytest.fixture
def temp_thumbnail_dir(tmp_path):
    """Create temporary directory structure for thumbnail testing."""
    # Create the expected directory structure
    thumb_dir = (
        tmp_path
        / "shows"
        / "testshow"
        / "shots"
        / "101_ABC"
        / "101_ABC_0010"
        / "publish"
        / "editorial"
        / "cutref"
        / "v001"
        / "jpg"
        / "1920x1080"
    )
    thumb_dir.mkdir(parents=True)

    # Create some test image files
    (thumb_dir / "thumbnail_001.jpg").touch()
    (thumb_dir / "thumbnail_002.jpg").touch()
    (thumb_dir / "preview.jpeg").touch()
    (thumb_dir / "not_an_image.txt").touch()

    return thumb_dir


@pytest.fixture
def mock_ws_output():
    """Sample output from ws -sg command."""
    return """workspace /shows/ygsk/shots/108_BQS/108_BQS_0005
workspace /shows/ygsk/shots/108_BQS/108_BQS_0010  
workspace /shows/ygsk/shots/109_ABC/109_ABC_0020
invalid line without workspace
workspace /invalid/path/format
workspace /shows/proj2/shots/201_XYZ/201_XYZ_0100
workspace /shows/test/shots/300_TEST/SIMPLE"""


@pytest.fixture
def shot_model_with_shots(qapp, monkeypatch):
    """Create a ShotModel with pre-populated shots."""
    # Mock cache manager
    from unittest.mock import Mock

    mock_cache_manager = Mock()
    mock_cache_manager.get_cached_shots.return_value = None
    monkeypatch.setattr("shot_model.CacheManager", lambda: mock_cache_manager)

    model = ShotModel()
    model.shots = [
        Shot("ygsk", "108_BQS", "0005", "/shows/ygsk/shots/108_BQS/108_BQS_0005"),
        Shot("ygsk", "108_BQS", "0010", "/shows/ygsk/shots/108_BQS/108_BQS_0010"),
        Shot("ygsk", "109_ABC", "0020", "/shows/ygsk/shots/109_ABC/109_ABC_0020"),
    ]
    return model


@pytest.fixture
def mock_subprocess_success(monkeypatch):
    """Mock subprocess.run for successful ws -sg execution."""

    def mock_run(*args, **kwargs):
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """workspace /shows/ygsk/shots/108_BQS/108_BQS_0005
workspace /shows/ygsk/shots/108_BQS/108_BQS_0010"""
        mock_result.stderr = ""
        return mock_result

    monkeypatch.setattr("subprocess.run", mock_run)
    return mock_run


@pytest.fixture
def mock_subprocess_failure(monkeypatch):
    """Mock subprocess.run for failed ws -sg execution."""

    def mock_run(*args, **kwargs):
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ws: command not found"
        return mock_result

    monkeypatch.setattr("subprocess.run", mock_run)
    return mock_run


@pytest.fixture
def mock_shot_model():
    """Mock shot model with test shots."""
    from tests.fixtures.test_data import TEST_SHOTS

    model = Mock()
    model.shots = TEST_SHOTS
    model.get_shot_by_index = (
        lambda idx: TEST_SHOTS[idx] if 0 <= idx < len(TEST_SHOTS) else None
    )
    model.find_shot_by_name = lambda name: next(
        (s for s in TEST_SHOTS if s.full_name == name), None
    )
    return model


@pytest.fixture
def mock_shot_model_empty():
    """Mock shot model with no shots."""
    model = Mock()
    model.shots = []
    model.get_shot_by_index = lambda idx: None
    model.find_shot_by_name = lambda name: None
    return model
