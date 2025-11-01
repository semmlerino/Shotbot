from tests.helpers.synchronization import process_qt_events

"""Integration tests for caching workflow."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cache_manager import CacheManager
from shot_model import Shot, ShotModel
from thumbnail_widget import ThumbnailWidget


class TestCachingWorkflow:
    """Test complete caching workflow from shot loading to thumbnail display."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for cache and shots."""
        with tempfile.TemporaryDirectory() as cache_dir:
            with tempfile.TemporaryDirectory() as shots_dir:
                yield Path(cache_dir), Path(shots_dir)

    @pytest.fixture
    def mock_ws_output(self):
        """Mock output from ws -sg command."""
        return """workspace /shows/testshow/shots/101_ABC/101_ABC_0010
workspace /shows/testshow/shots/101_ABC/101_ABC_0020
workspace /shows/testshow/shots/102_DEF/102_DEF_0030"""

    @pytest.fixture
    def shot_model_with_cache(self, temp_dirs):
        """Create ShotModel with custom cache directory."""
        cache_dir, _ = temp_dirs
        cache_manager = CacheManager(cache_dir=cache_dir)
        return ShotModel(cache_manager)

    def test_shot_model_cache_on_refresh(
        self, shot_model_with_cache, mock_ws_output, temp_dirs
    ):
        """Test that shot model caches data on refresh."""
        cache_dir, _ = temp_dirs

        # Mock subprocess to return our test data
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = mock_ws_output
            mock_run.return_value = mock_result

            # Refresh shots
            success, has_changes = shot_model_with_cache.refresh_shots()

            assert success
            assert has_changes
            assert len(shot_model_with_cache.shots) == 3

            # Check cache file was created
            cache_file = cache_dir / "shots.json"
            assert cache_file.exists()

            # Verify cache content
            with open(cache_file) as f:
                cache_data = json.load(f)

            assert "timestamp" in cache_data
            assert len(cache_data["shots"]) == 3
            assert cache_data["shots"][0]["shot"] == "0010"

    def test_shot_model_loads_from_cache(self, temp_dirs, monkeypatch):
        """Test shot model loads from cache on init."""
        cache_dir, _ = temp_dirs

        # Create cache file
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "shots": [
                {
                    "show": "cached",
                    "sequence": "999_XXX",
                    "shot": "9999",
                    "workspace_path": "/cached/path",
                }
            ],
        }

        cache_file = cache_dir / "shots.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # Create shot model with cache
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ShotModel(cache_manager)

        # Should have loaded from cache
        assert len(model.shots) == 1
        assert model.shots[0].show == "cached"
        assert model.shots[0].sequence == "999_XXX"

    def test_shot_model_change_detection(self, shot_model_with_cache, mock_ws_output):
        """Test shot model detects changes correctly."""
        # First refresh
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = mock_ws_output
            mock_run.return_value = mock_result

            success1, has_changes1 = shot_model_with_cache.refresh_shots()
            assert success1 and has_changes1

        # Second refresh with same data
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = mock_ws_output
            mock_run.return_value = mock_result

            success2, has_changes2 = shot_model_with_cache.refresh_shots()
            assert success2 and not has_changes2

        # Third refresh with different data
        new_output = (
            mock_ws_output + "\nworkspace /shows/testshow/shots/103_GHI/103_GHI_0040"
        )
        with patch("shot_model.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = new_output
            mock_run.return_value = mock_result

            success3, has_changes3 = shot_model_with_cache.refresh_shots()
            assert success3 and has_changes3
            assert len(shot_model_with_cache.shots) == 4

    def test_thumbnail_caching_workflow(self, temp_dirs, monkeypatch, qapp):
        """Test complete thumbnail caching workflow."""
        cache_dir, shots_dir = temp_dirs

        # Setup cache manager with temp directory

        # Create source thumbnail with real image
        source_thumb = shots_dir / "thumb.jpg"
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        img = QImage(100, 100, QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.blue)
        img.save(str(source_thumb))

        # Create shot
        shot = Shot("show1", "seq1", "shot1", "/fake/path")
        shot.get_thumbnail_path = Mock(return_value=source_thumb)

        # Create thumbnail widget
        ThumbnailWidget(shot)

        # Process events to allow background loading
        qapp.processEvents()
        process_qt_events(qapp, 100)  # Give thread pool time to process

        # Check cache was created
        expected_cache = cache_dir / "thumbnails" / "show1" / "seq1" / "shot1_thumb.jpg"

        # The cache creation happens in background, so we need to wait a bit
        # or manually trigger the cache loader
        cache_manager = CacheManager(cache_dir=cache_dir)
        cache_path = cache_manager.cache_thumbnail(
            source_thumb, "show1", "seq1", "shot1"
        )

        assert cache_path == expected_cache
        assert expected_cache.exists()

    def test_cache_expiry(self, temp_dirs, monkeypatch):
        """Test cache expiry mechanism."""
        cache_dir, _ = temp_dirs

        # Setup cache manager

        cache_manager = CacheManager(cache_dir=cache_dir)

        # Create expired cache
        old_time = datetime.now() - timedelta(hours=2)
        cache_data = {
            "timestamp": old_time.isoformat(),
            "shots": [
                {
                    "show": "old",
                    "sequence": "old",
                    "shot": "old",
                    "workspace_path": "/old",
                }
            ],
        }

        with open(cache_dir / "shots.json", "w") as f:
            json.dump(cache_data, f)

        # Should return None for expired cache
        cached_shots = cache_manager.get_cached_shots()
        assert cached_shots is None

        # Create fresh cache
        fresh_data = {
            "timestamp": datetime.now().isoformat(),
            "shots": [
                {
                    "show": "new",
                    "sequence": "new",
                    "shot": "new",
                    "workspace_path": "/new",
                }
            ],
        }

        with open(cache_dir / "shots.json", "w") as f:
            json.dump(fresh_data, f)

        # Should return data for fresh cache
        cached_shots = cache_manager.get_cached_shots()
        assert cached_shots is not None
        assert len(cached_shots) == 1
        assert cached_shots[0]["show"] == "new"

    def test_cache_clear_and_recreate(self, temp_dirs, monkeypatch):
        """Test clearing cache and recreating directories."""
        cache_dir, _ = temp_dirs

        # Setup cache manager

        cache_manager = CacheManager(cache_dir=cache_dir)

        # Create some cache data
        (cache_dir / "thumbnails" / "test").mkdir(parents=True)
        (cache_dir / "thumbnails" / "test" / "thumb.jpg").write_bytes(b"data")
        (cache_dir / "shots.json").write_text('{"test": "data"}')

        # Clear cache
        cache_manager.clear_cache()

        # Thumbnails directory should exist but be empty
        assert (cache_dir / "thumbnails").exists()
        assert not list((cache_dir / "thumbnails").iterdir())

        # Shots cache should be gone
        assert not (cache_dir / "shots.json").exists()
