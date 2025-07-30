"""Extended unit tests for shot_model.py focusing on new caching features"""

import subprocess
from unittest.mock import Mock, patch

import pytest

from shot_model import Shot, ShotModel


class TestShotModelCaching:
    """Test ShotModel caching functionality."""

    @pytest.fixture
    def mock_cache_manager(self):
        """Create mock cache manager."""
        mock = Mock()
        mock.get_cached_shots.return_value = None
        mock.cache_shots = Mock()
        return mock

    @pytest.fixture
    def shot_model_with_mock_cache(self, mock_cache_manager, monkeypatch):
        """Create ShotModel with mocked cache manager."""
        with patch("shot_model.CacheManager") as mock_cm_class:
            mock_cm_class.return_value = mock_cache_manager
            model = ShotModel()
            model.cache_manager = mock_cache_manager
            return model

    def test_init_loads_from_cache(self, mock_cache_manager):
        """Test ShotModel loads from cache on initialization."""
        # Setup cached data
        cached_shots = [
            {
                "show": "show1",
                "sequence": "seq1",
                "shot": "0010",
                "workspace_path": "/path1",
            },
            {
                "show": "show1",
                "sequence": "seq1",
                "shot": "0020",
                "workspace_path": "/path2",
            },
        ]
        mock_cache_manager.get_cached_shots.return_value = cached_shots

        # Create model
        with patch("shot_model.CacheManager") as mock_cm_class:
            mock_cm_class.return_value = mock_cache_manager
            model = ShotModel()

        # Should have loaded from cache
        assert len(model.shots) == 2
        assert model.shots[0].shot == "0010"
        assert model.shots[1].shot == "0020"

    def test_refresh_returns_change_status(self, shot_model_with_mock_cache):
        """Test refresh_shots returns both success and change status."""
        ws_output = """workspace /shows/show1/shots/seq1/seq1_0010
workspace /shows/show1/shots/seq1/seq1_0020"""

        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output
            mock_run.return_value = mock_result

            success, has_changes = shot_model_with_mock_cache.refresh_shots()

            assert success is True
            assert has_changes is True

    def test_refresh_detects_no_changes(self, shot_model_with_mock_cache):
        """Test refresh detects when there are no changes."""
        ws_output = """workspace /shows/show1/shots/seq1/seq1_0010"""

        # First refresh
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output
            mock_run.return_value = mock_result

            success1, has_changes1 = shot_model_with_mock_cache.refresh_shots()
            assert success1 and has_changes1

        # Second refresh with same data
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output
            mock_run.return_value = mock_result

            success2, has_changes2 = shot_model_with_mock_cache.refresh_shots()
            assert success2 is True
            assert has_changes2 is False

    def test_refresh_detects_added_shots(self, shot_model_with_mock_cache):
        """Test refresh detects newly added shots."""
        ws_output1 = """workspace /shows/show1/shots/seq1/seq1_0010"""
        ws_output2 = """workspace /shows/show1/shots/seq1/seq1_0010
workspace /shows/show1/shots/seq1/seq1_0020"""

        # First refresh
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output1
            mock_run.return_value = mock_result

            shot_model_with_mock_cache.refresh_shots()

        # Second refresh with additional shot
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output2
            mock_run.return_value = mock_result

            success, has_changes = shot_model_with_mock_cache.refresh_shots()
            assert success and has_changes
            assert len(shot_model_with_mock_cache.shots) == 2

    def test_refresh_detects_removed_shots(self, shot_model_with_mock_cache):
        """Test refresh detects removed shots."""
        ws_output1 = """workspace /shows/show1/shots/seq1/seq1_0010
workspace /shows/show1/shots/seq1/seq1_0020"""
        ws_output2 = """workspace /shows/show1/shots/seq1/seq1_0010"""

        # First refresh
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output1
            mock_run.return_value = mock_result

            shot_model_with_mock_cache.refresh_shots()

        # Second refresh with removed shot
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output2
            mock_run.return_value = mock_result

            success, has_changes = shot_model_with_mock_cache.refresh_shots()
            assert success and has_changes
            assert len(shot_model_with_mock_cache.shots) == 1

    def test_refresh_detects_path_changes(self, shot_model_with_mock_cache):
        """Test refresh detects when workspace path changes."""
        ws_output1 = """workspace /shows/show1/shots/seq1/seq1_0010"""
        ws_output2 = """workspace /shows/show1/shots/seq1_v2/seq1_0010"""

        # First refresh
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output1
            mock_run.return_value = mock_result

            shot_model_with_mock_cache.refresh_shots()
            first_path = shot_model_with_mock_cache.shots[0].workspace_path

        # Second refresh with changed path
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output2
            mock_run.return_value = mock_result

            success, has_changes = shot_model_with_mock_cache.refresh_shots()
            assert success and has_changes
            assert shot_model_with_mock_cache.shots[0].workspace_path != first_path

    def test_refresh_caches_on_changes(
        self, shot_model_with_mock_cache, mock_cache_manager
    ):
        """Test refresh only caches data when there are changes."""
        ws_output = """workspace /shows/show1/shots/seq1/seq1_0010"""

        # First refresh (changes)
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output
            mock_run.return_value = mock_result

            shot_model_with_mock_cache.refresh_shots()
            assert mock_cache_manager.cache_shots.call_count == 1

        # Second refresh (no changes)
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ws_output
            mock_run.return_value = mock_result

            shot_model_with_mock_cache.refresh_shots()
            # Should not cache again
            assert mock_cache_manager.cache_shots.call_count == 1

    def test_refresh_with_subprocess_timeout(self, shot_model_with_mock_cache):
        """Test handling of subprocess timeout."""
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ws -sg", 10)

            success, has_changes = shot_model_with_mock_cache.refresh_shots()
            assert success is False
            assert has_changes is False

    def test_refresh_with_subprocess_error(self, shot_model_with_mock_cache):
        """Test handling of subprocess error."""
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 1
            mock_result.stderr = "Error: workspace not found"
            mock_run.return_value = mock_result

            success, has_changes = shot_model_with_mock_cache.refresh_shots()
            assert success is False
            assert has_changes is False

    def test_to_dict_format(self, shot_model_with_mock_cache):
        """Test to_dict returns proper format for caching."""
        # Add some shots
        shot_model_with_mock_cache.shots = [
            Shot("show1", "seq1", "0010", "/path1"),
            Shot("show2", "seq2", "0020", "/path2"),
        ]

        result = shot_model_with_mock_cache.to_dict()

        assert len(result) == 2
        assert all(isinstance(shot_dict, dict) for shot_dict in result)

        # Check first shot
        first = result[0]
        assert first["show"] == "show1"
        assert first["sequence"] == "seq1"
        assert first["shot"] == "0010"
        assert first["workspace_path"] == "/path1"
        assert first["full_name"] == "seq1_0010"
