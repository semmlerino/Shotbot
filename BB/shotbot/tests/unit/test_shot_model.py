"""Unit tests for shot_model.py"""

import subprocess
from pathlib import Path

from shot_model import Shot, ShotModel


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

    def test_thumbnail_dir_property(self, sample_shot):
        """Test thumbnail directory path construction."""
        thumb_dir = sample_shot.thumbnail_dir
        assert isinstance(thumb_dir, Path)
        expected = "/shows/testshow/shots/101_ABC/101_ABC_0010/publish/editorial/cutref/v001/jpg/1920x1080"
        assert str(thumb_dir) == expected

    def test_get_thumbnail_path_with_jpg(self, tmp_path, monkeypatch):
        """Test getting thumbnail when jpg files exist."""
        import config

        # Create exact directory structure expected
        shows_root = tmp_path / "mock_shows"
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

        # Create test files
        (thumb_dir / "thumbnail_001.jpg").touch()
        (thumb_dir / "thumbnail_002.jpg").touch()

        # Monkeypatch SHOWS_ROOT
        monkeypatch.setattr(config.Config, "SHOWS_ROOT", str(shows_root))

        # Create shot
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )

        thumb_path = shot.get_thumbnail_path()
        assert thumb_path is not None
        assert thumb_path.name == "thumbnail_001.jpg"  # Should return first jpg
        assert thumb_path.exists()

    def test_get_thumbnail_path_with_only_jpeg(self, tmp_path, monkeypatch):
        """Test getting thumbnail when only jpeg files exist."""
        import config

        # Create exact directory structure expected
        shows_root = tmp_path / "mock_shows"
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

        # Create only jpeg files
        (thumb_dir / "preview.jpeg").touch()
        (thumb_dir / "another.jpeg").touch()

        # Monkeypatch SHOWS_ROOT
        monkeypatch.setattr(config.Config, "SHOWS_ROOT", str(shows_root))

        # Create shot
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )

        thumb_path = shot.get_thumbnail_path()
        assert thumb_path is not None
        assert thumb_path.suffix == ".jpeg"  # Should be a jpeg file
        assert thumb_path.name in ["preview.jpeg", "another.jpeg"]  # Could be either
        assert thumb_path.exists()

    def test_get_thumbnail_path_no_images(self, temp_thumbnail_dir, monkeypatch):
        """Test getting thumbnail when no image files exist."""
        # Remove all image files
        for img in temp_thumbnail_dir.glob("*.jp*"):
            img.unlink()

        # Monkeypatch Config.SHOWS_ROOT to use our temp directory
        import config

        monkeypatch.setattr(
            config.Config,
            "SHOWS_ROOT",
            str(temp_thumbnail_dir.parent.parent.parent.parent.parent),
        )

        # Create shot with matching path
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )

        thumb_path = shot.get_thumbnail_path()
        assert thumb_path is None

    def test_get_thumbnail_path_nonexistent_dir(self, tmp_path, monkeypatch):
        """Test getting thumbnail when directory doesn't exist."""
        # Monkeypatch Config.SHOWS_ROOT to use our temp directory
        import config

        monkeypatch.setattr(config.Config, "SHOWS_ROOT", str(tmp_path / "nonexistent"))

        # Create shot - the directory won't exist
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )

        thumb_path = shot.get_thumbnail_path()
        assert thumb_path is None


class TestShotModel:
    """Test ShotModel class."""

    def test_initialization(self, qapp, tmp_path):
        """Test ShotModel initialization."""
        # Use real CacheManager with temp directory
        import os

        os.environ["HOME"] = str(tmp_path)

        model = ShotModel(load_cache=False)  # Don't load cache for this test
        assert model.shots == []
        assert model._parse_pattern is not None
        # Test regex pattern
        assert (
            model._parse_pattern.pattern
            == r"workspace\s+(/shows/(\w+)/shots/(\w+)/(\w+))"
        )

    def test_parse_ws_output_valid_lines(self, qapp, mock_ws_output, tmp_path):
        """Test parsing valid ws -sg output."""
        # Use real CacheManager with temp directory
        import os

        os.environ["HOME"] = str(tmp_path)

        model = ShotModel(load_cache=False)
        shots = model._parse_ws_output(mock_ws_output)

        assert len(shots) == 5  # Should parse 5 valid lines

        # Check first shot
        assert shots[0].show == "ygsk"
        assert shots[0].sequence == "108_BQS"
        assert shots[0].shot == "0005"
        assert shots[0].workspace_path == "/shows/ygsk/shots/108_BQS/108_BQS_0005"
        assert shots[0].full_name == "108_BQS_0005"

        # Check shot with simple name (no underscores)
        assert shots[4].show == "test"
        assert shots[4].sequence == "300_TEST"
        assert shots[4].shot == "SIMPLE"  # Falls back to full name
        assert shots[4].full_name == "300_TEST_SIMPLE"

    def test_parse_ws_output_empty(self, qapp, tmp_path):
        """Test parsing empty output."""
        # Use real CacheManager with temp directory
        import os

        os.environ["HOME"] = str(tmp_path)

        model = ShotModel(load_cache=False)
        shots = model._parse_ws_output("")
        assert shots == []

        shots = model._parse_ws_output("\n\n\n")
        assert shots == []

    def test_parse_ws_output_mixed_content(self, qapp, monkeypatch):
        """Test parsing output with invalid lines."""
        output = """
        Some header text
        workspace /shows/valid/shots/100_TEST/100_TEST_0001
        ERROR: Invalid workspace
        workspace /invalid/format
        workspace /shows/valid/shots/200_TEST/200_TEST_0002
        """
        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        shots = model._parse_ws_output(output)

        assert len(shots) == 2
        assert shots[0].shot == "0001"
        assert shots[1].shot == "0002"

    def test_refresh_shots_success(self, qapp, mock_subprocess_success, monkeypatch):
        """Test successful refresh_shots execution."""
        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        mock_cache_manager.cache_shots = Mock()
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        success, has_changes = model.refresh_shots()

        assert success is True
        assert has_changes is True  # First refresh always has changes
        assert len(model.shots) == 2
        assert model.shots[0].show == "ygsk"

    def test_refresh_shots_command_not_found(self, qapp, monkeypatch):
        """Test refresh_shots when ws command doesn't exist."""

        def mock_run(*args, **kwargs):
            raise FileNotFoundError("ws command not found")

        monkeypatch.setattr("subprocess.run", mock_run)

        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        success, has_changes = model.refresh_shots()

        assert success is False
        assert has_changes is False
        assert model.shots == []

    def test_refresh_shots_timeout(self, qapp, monkeypatch):
        """Test refresh_shots with timeout."""

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired("ws", 10)

        monkeypatch.setattr("subprocess.run", mock_run)

        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        success, has_changes = model.refresh_shots()

        assert success is False
        assert has_changes is False
        assert model.shots == []

    def test_refresh_shots_nonzero_return(
        self, qapp, mock_subprocess_failure, monkeypatch
    ):
        """Test refresh_shots with non-zero return code."""
        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        success, has_changes = model.refresh_shots()

        assert success is False
        assert has_changes is False
        assert model.shots == []

    def test_refresh_shots_generic_exception(self, qapp, monkeypatch):
        """Test refresh_shots with unexpected exception."""

        def mock_run(*args, **kwargs):
            raise RuntimeError("Unexpected error")

        monkeypatch.setattr("subprocess.run", mock_run)

        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        success, has_changes = model.refresh_shots()

        assert success is False
        assert has_changes is False
        assert model.shots == []

    def test_get_shot_by_index_valid(self, shot_model_with_shots):
        """Test getting shot by valid index."""
        shot = shot_model_with_shots.get_shot_by_index(0)
        assert shot is not None
        assert shot.shot == "0005"

        shot = shot_model_with_shots.get_shot_by_index(2)
        assert shot is not None
        assert shot.shot == "0020"

    def test_get_shot_by_index_invalid(self, shot_model_with_shots):
        """Test getting shot by invalid index."""
        assert shot_model_with_shots.get_shot_by_index(-1) is None
        assert shot_model_with_shots.get_shot_by_index(3) is None
        assert shot_model_with_shots.get_shot_by_index(100) is None

    def test_get_shot_by_index_empty_list(self, monkeypatch):
        """Test getting shot from empty model."""
        # Mock cache manager to return no cached shots
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        assert model.get_shot_by_index(0) is None

    def test_find_shot_by_name_exists(self, shot_model_with_shots):
        """Test finding shot by name when it exists."""
        shot = shot_model_with_shots.find_shot_by_name("108_BQS_0010")
        assert shot is not None
        assert shot.shot == "0010"
        assert shot.sequence == "108_BQS"

    def test_find_shot_by_name_not_exists(self, shot_model_with_shots):
        """Test finding shot by name when it doesn't exist."""
        shot = shot_model_with_shots.find_shot_by_name("NONEXISTENT_0001")
        assert shot is None

        # Test case sensitivity
        shot = shot_model_with_shots.find_shot_by_name("108_bqs_0010")
        assert shot is None

    def test_find_shot_by_name_empty_list(self, qapp, monkeypatch):
        """Test finding shot in empty model."""
        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()
        shot = model.find_shot_by_name("ANY_NAME")
        assert shot is None

    def test_shot_to_dict(self, shot_model_with_shots):
        """Test converting individual shots to dictionary format."""
        shot = shot_model_with_shots.shots[0]
        result = shot.to_dict()

        assert isinstance(result, dict)

        # Check shot dict content
        assert result["show"] == "ygsk"
        assert result["sequence"] == "108_BQS"
        assert result["shot"] == "0005"
        assert result["workspace_path"] == "/shows/ygsk/shots/108_BQS/108_BQS_0005"

        # Verify all required keys (note: full_name is not stored, it's a property)
        required_keys = {"show", "sequence", "shot", "workspace_path"}
        assert set(result.keys()) == required_keys

    def test_shot_from_dict(self):
        """Test creating shot from dictionary (deserialization)."""
        shot_data = {
            "show": "testshow",
            "sequence": "seq001",
            "shot": "shot001",
            "workspace_path": "/path/to/workspace",
        }

        shot = Shot.from_dict(shot_data)

        assert shot.show == "testshow"
        assert shot.sequence == "seq001"
        assert shot.shot == "shot001"
        assert shot.workspace_path == "/path/to/workspace"
        assert shot.full_name == "seq001_shot001"

    def test_shot_serialization_roundtrip(self, shot_model_with_shots):
        """Test that Shot serialization/deserialization is bidirectional."""
        original_shot = shot_model_with_shots.shots[0]

        # Serialize to dict
        shot_dict = original_shot.to_dict()

        # Deserialize back to Shot
        recreated_shot = Shot.from_dict(shot_dict)

        # Verify roundtrip preserves all data
        assert recreated_shot.show == original_shot.show
        assert recreated_shot.sequence == original_shot.sequence
        assert recreated_shot.shot == original_shot.shot
        assert recreated_shot.workspace_path == original_shot.workspace_path
        assert recreated_shot.full_name == original_shot.full_name

    def test_shot_parsing_edge_cases(self, qapp, monkeypatch):
        """Test edge cases in shot name parsing."""
        # Mock cache manager
        from unittest.mock import Mock

        mock_cache_manager = Mock()
        mock_cache_manager.get_cached_shots.return_value = None
        monkeypatch.setattr("cache_manager.CacheManager", lambda: mock_cache_manager)

        model = ShotModel()

        # Test with various underscore patterns
        edge_cases = """
        workspace /shows/test/shots/A/A
        workspace /shows/test/shots/A_B/A_B
        workspace /shows/test/shots/A_B_C/A_B_C
        workspace /shows/test/shots/A_B_C_D/A_B_C_D
        """

        shots = model._parse_ws_output(edge_cases)
        assert len(shots) == 4

        # Single part name
        assert shots[0].shot == "A"
        assert shots[0].full_name == "A_A"

        # Two part name
        assert shots[1].shot == "A_B"
        assert shots[1].full_name == "A_B_A_B"

        # Three part name (standard format)
        assert shots[2].shot == "C"
        assert shots[2].full_name == "A_B_C_C"

        # Four part name
        assert shots[3].shot == "D"
        assert shots[3].full_name == "A_B_C_D_D"
