"""
Refactored version of test_shot_model.py with extracted fixtures.

This demonstrates how to reduce repetitive mock setup by extracting
common patterns into reusable fixtures.
"""

import subprocess
from unittest.mock import Mock

import pytest

from shot_model import Shot, ShotModel

# ============================================================================
# Common Fixtures - Extract repetitive mock patterns
# ============================================================================


@pytest.fixture
def mock_cache_manager(monkeypatch):
    """Common mock cache manager fixture for test isolation."""
    mock_cache = Mock()
    mock_cache.get_cached_shots.return_value = None
    mock_cache.cache_shots = Mock()

    # Patch at the module level where it's imported
    monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache)

    return mock_cache


@pytest.fixture
def shot_model_with_mock_cache(mock_cache_manager):
    """Create ShotModel with mocked cache manager."""
    return ShotModel(), mock_cache_manager


@pytest.fixture
def mock_ws_output():
    """Standard workspace command output for testing."""
    return Mock(
        stdout="""workspace /shows/testshow/shots/101_ABC/101_ABC_0010
workspace /shows/testshow/shots/101_ABC/101_ABC_0020
workspace /shows/testshow/shots/101_ABC/101_ABC_0030""",
        returncode=0,
    )


@pytest.fixture
def mock_subprocess_run(monkeypatch, mock_ws_output):
    """Mock subprocess.run with standard workspace output."""
    mock_run = Mock(return_value=mock_ws_output)
    monkeypatch.setattr("subprocess.run", mock_run)
    return mock_run


# ============================================================================
# Test Shot class
# ============================================================================


class TestShot:
    """Test Shot dataclass."""

    def test_shot_creation(self):
        """Test basic Shot instantiation."""
        shot = Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
        )
        assert shot.show == "testshow"
        assert shot.sequence == "101_ABC"
        assert shot.shot == "0010"
        assert shot.workspace_path == "/shows/testshow/shots/101_ABC/101_ABC_0010"

    def test_full_name_property(self):
        """Test full_name property concatenation."""
        shot = Shot("show", "101_ABC", "0010", "/path")
        assert shot.full_name == "101_ABC_0010"

        # Test with empty values
        shot_empty = Shot("", "", "", "")
        assert shot_empty.full_name == "_"

    @pytest.fixture
    def shot_with_real_thumbnails(self, tmp_path, monkeypatch):
        """Create a shot with real thumbnail directory structure."""
        import config

        # Create realistic directory structure
        shows_root = tmp_path / "shows"
        thumb_dir = (
            shows_root
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

        # Create test thumbnail files
        (thumb_dir / "thumbnail_001.jpg").touch()
        (thumb_dir / "thumbnail_002.jpg").touch()

        # Patch the config
        monkeypatch.setattr(config.Config, "SHOWS_ROOT", str(shows_root))

        # Return both the shot and the directory for verification
        shot = Shot(
            "testshow",
            "101_ABC",
            "0010",
            str(shows_root / "testshow/shots/101_ABC/101_ABC_0010"),
        )

        return shot, thumb_dir

    def test_get_thumbnail_path_with_real_files(self, shot_with_real_thumbnails):
        """Test thumbnail discovery with real filesystem."""
        shot, thumb_dir = shot_with_real_thumbnails

        thumb_path = shot.get_thumbnail_path()
        assert thumb_path is not None
        assert thumb_path.exists()
        assert thumb_path.suffix in [".jpg", ".jpeg"]
        assert thumb_path.parent == thumb_dir


# ============================================================================
# Test ShotModel class
# ============================================================================


class TestShotModelRefactored:
    """Test ShotModel with extracted fixtures."""

    def test_initialization_with_mock_cache(self, shot_model_with_mock_cache):
        """Test model initialization with mocked cache."""
        model, mock_cache = shot_model_with_mock_cache

        assert model.shots == []
        assert model.cache_manager == mock_cache
        mock_cache.get_cached_shots.assert_called_once()

    def test_refresh_shots_success(
        self, shot_model_with_mock_cache, mock_subprocess_run
    ):
        """Test successful shot refresh using fixtures."""
        model, mock_cache = shot_model_with_mock_cache

        success, has_changes = model.refresh_shots()

        assert success is True
        assert has_changes is True
        assert len(model.shots) == 3

        # Verify subprocess was called correctly
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args[0][0]
        assert "ws -sg" in " ".join(call_args)

        # Verify cache was updated
        mock_cache.cache_shots.assert_called_once()
        cached_shots = mock_cache.cache_shots.call_args[0][0]
        assert len(cached_shots) == 3

    def test_refresh_shots_no_changes(
        self, shot_model_with_mock_cache, mock_subprocess_run
    ):
        """Test refresh when shots haven't changed."""
        model, mock_cache = shot_model_with_mock_cache

        # First refresh
        success1, has_changes1 = model.refresh_shots()
        assert success1 and has_changes1

        # Second refresh - no changes
        success2, has_changes2 = model.refresh_shots()
        assert success2 is True
        assert has_changes2 is False  # No changes

        # Cache should be called twice
        assert mock_cache.cache_shots.call_count == 1  # Only on first change

    def test_refresh_shots_subprocess_error(
        self, shot_model_with_mock_cache, monkeypatch
    ):
        """Test handling of subprocess errors."""
        model, mock_cache = shot_model_with_mock_cache

        # Mock subprocess to raise error
        mock_run = Mock(side_effect=subprocess.CalledProcessError(1, "ws"))
        monkeypatch.setattr("subprocess.run", mock_run)

        success, has_changes = model.refresh_shots()

        assert success is False
        assert has_changes is False
        assert model.shots == []  # No shots loaded

    def test_refresh_shots_empty_output(self, shot_model_with_mock_cache, monkeypatch):
        """Test handling of empty workspace output."""
        model, mock_cache = shot_model_with_mock_cache

        # Mock empty output
        mock_run = Mock(return_value=Mock(stdout="", returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        success, has_changes = model.refresh_shots()

        assert success is True
        assert has_changes is False  # Empty is considered no change
        assert model.shots == []

    def test_get_shot_by_index(self, shot_model_with_mock_cache, mock_subprocess_run):
        """Test getting shot by index."""
        model, _ = shot_model_with_mock_cache

        model.refresh_shots()

        shot = model.get_shot_by_index(0)
        assert shot is not None
        assert shot.shot == "0010"

        # Test out of bounds
        assert model.get_shot_by_index(99) is None
        assert model.get_shot_by_index(-1) is None

    def test_find_shot_by_name(self, shot_model_with_mock_cache, mock_subprocess_run):
        """Test finding shot by full name."""
        model, _ = shot_model_with_mock_cache

        model.refresh_shots()

        shot = model.find_shot_by_name("101_ABC_0020")
        assert shot is not None
        assert shot.shot == "0020"

        # Test not found
        assert model.find_shot_by_name("NONEXISTENT") is None


# ============================================================================
# Integration Tests - Minimal Mocking
# ============================================================================


class TestShotModelIntegration:
    """Integration tests with minimal mocking - only external dependencies."""

    @pytest.fixture
    def real_cache_dir(self, tmp_path):
        """Create real cache directory for integration tests."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        return cache_dir

    def test_integration_with_mock_cache_and_real_filesystem(
        self, real_cache_dir, mock_subprocess_run, monkeypatch
    ):
        """Test ShotModel with real filesystem but mocked cache (PySide6 not available in test env)."""
        # Create a simple mock cache that writes to real files
        mock_cache = Mock()
        mock_cache.get_cached_shots.return_value = None
        mock_cache.cache_shots = Mock(
            side_effect=lambda shots: (real_cache_dir / "shots.json").write_text(
                str([{"show": s.show, "shot": s.shot} for s in shots])
            )
        )

        # Patch CacheManager
        monkeypatch.setattr("cache_manager.CacheManager", lambda **kwargs: mock_cache)

        # Create model with mocked cache
        model = ShotModel()

        # Refresh shots
        success, has_changes = model.refresh_shots()

        assert success is True
        assert has_changes is True
        assert len(model.shots) == 3

        # Verify cache file was created
        cache_file = real_cache_dir / "shots.json"
        assert cache_file.exists()

        # Verify mock cache was called
        mock_cache.cache_shots.assert_called_once()

    def test_integration_shot_workflow(self, tmp_path, monkeypatch):
        """Test complete shot workflow with minimal mocking."""
        import config

        # Setup real directory structure
        shows_root = tmp_path / "shows"
        shot_dir = shows_root / "testshow/shots/101_ABC/101_ABC_0010"
        shot_dir.mkdir(parents=True)

        # Create real thumbnail
        thumb_dir = shot_dir / "publish/editorial/cutref/v001/jpg/1920x1080"
        thumb_dir.mkdir(parents=True)
        (thumb_dir / "thumb.jpg").write_bytes(b"JPEG_DATA")

        # Patch config
        monkeypatch.setattr(config.Config, "SHOWS_ROOT", str(shows_root))

        # Create shot and verify thumbnail discovery
        shot = Shot("testshow", "101_ABC", "0010", str(shot_dir))

        thumb = shot.get_thumbnail_path()
        assert thumb is not None
        assert thumb.exists()
        assert thumb.read_bytes() == b"JPEG_DATA"
