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
    monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

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


# Common fixtures for refactored tests with reduced mocking


@pytest.fixture
def sample_image(tmp_path):
    """Create a simple test image file for testing image operations.

    Creates a minimal valid JPEG file with proper headers that can be
    used for testing without requiring Qt to actually load the image.
    """
    # Create a minimal valid JPEG header (SOI and EOI markers)
    jpeg_data = bytes(
        [
            0xFF,
            0xD8,  # SOI (Start of Image)
            0xFF,
            0xE0,  # APP0 marker
            0x00,
            0x10,  # Length
            0x4A,
            0x46,
            0x49,
            0x46,
            0x00,  # "JFIF\0"
            0x01,
            0x01,  # Version
            0x00,  # Units
            0x00,
            0x01,
            0x00,
            0x01,  # X/Y density
            0x00,
            0x00,  # Thumbnails
            0xFF,
            0xD9,  # EOI (End of Image)
        ]
    )

    image_path = tmp_path / "test_image.jpg"
    image_path.write_bytes(jpeg_data)
    return image_path


@pytest.fixture
def real_cache_manager(tmp_path):
    """Create a real CacheManager with temporary directory.

    This fixture provides a real CacheManager instance that uses
    actual filesystem operations instead of mocks, enabling more
    realistic testing of cache behavior.
    """
    from cache_manager import CacheManager

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return CacheManager(cache_dir=cache_dir)


@pytest.fixture
def sample_shots():
    """Create a list of sample Shot objects for testing.

    Returns a list of diverse Shot objects covering different
    shows, sequences, and shot numbers for comprehensive testing.
    """
    return [
        Shot("show1", "seq1", "0010", "/shows/show1/shots/seq1/seq1_0010"),
        Shot("show1", "seq1", "0020", "/shows/show1/shots/seq1/seq1_0020"),
        Shot("show2", "seq2", "0030", "/shows/show2/shots/seq2/seq2_0030"),
        Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        ),
        Shot(
            "testshow", "101_ABC", "0020", "/shows/testshow/shots/101_ABC/101_ABC_0020"
        ),
        Shot(
            "testshow", "102_XYZ", "0030", "/shows/testshow/shots/102_XYZ/102_XYZ_0030"
        ),
        Shot(
            "othershow",
            "201_FOO",
            "0040",
            "/shows/othershow/shots/201_FOO/201_FOO_0040",
        ),
    ]


@pytest.fixture
def real_shot_model(qtbot, real_cache_manager, sample_shots):
    """Create a real ShotModel with test data and real cache manager.

    This fixture provides a real ShotModel instance populated with
    sample shots, using a real cache manager for realistic testing
    of model behavior.
    """
    from shot_model import ShotModel

    model = ShotModel(cache_manager=real_cache_manager)
    # ShotModel is a QObject, not a widget - don't use qtbot.addWidget
    model.shots = sample_shots[:3]  # Use first 3 shots by default
    return model


@pytest.fixture
def empty_shot_model(qtbot, real_cache_manager):
    """Create an empty real ShotModel with no shots.

    Useful for testing edge cases and empty state behavior.
    """
    from shot_model import ShotModel

    model = ShotModel(cache_manager=real_cache_manager)
    model.shots = []  # Empty shot list
    return model
