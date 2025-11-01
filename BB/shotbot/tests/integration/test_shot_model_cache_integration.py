"""Integration tests for ShotModel and CacheManager interaction."""

import json
import time
from unittest.mock import Mock, patch

import pytest

from cache_manager import CacheManager
from shot_model import Shot, ShotModel


class TestShotModelCacheIntegration:
    """Test the integration between ShotModel and CacheManager."""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Create a temporary cache directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        return cache_dir

    @pytest.fixture
    def cache_manager(self, temp_cache_dir):
        """Create a CacheManager instance with temporary directory."""
        return CacheManager(cache_dir=temp_cache_dir)

    @pytest.fixture
    def shot_model(self, cache_manager):
        """Create a ShotModel instance with the test cache manager."""
        return ShotModel(cache_manager, load_cache=False)

    @pytest.fixture
    def sample_shots(self):
        """Create sample shots for testing."""
        shots = []
        for i in range(3):
            shot = Shot(
                show=f"testshow{i}",
                sequence=f"seq{i:03d}",
                shot=f"shot{i:03d}",
                workspace_path=f"/shows/testshow{i}/shots/seq{i:03d}/shot{i:03d}",
            )
            shots.append(shot)
        return shots

    def test_shot_caching_and_retrieval(self, shot_model, sample_shots):
        """Test that shots are properly cached and retrieved."""
        # Add shots to model
        shot_model.shots = sample_shots

        # Cache the shots - cache manager now handles Shot objects directly
        shot_model.cache_manager.cache_shots(sample_shots)

        # Clear the model's shots
        shot_model.shots.clear()

        # Retrieve from cache (returns dicts)
        cached_data = shot_model.cache_manager.get_cached_shots()

        # Verify shots were retrieved
        assert len(cached_data) == 3
        assert all(isinstance(shot_data, dict) for shot_data in cached_data)
        assert cached_data[0]["show"] == "testshow0"
        assert cached_data[1]["sequence"] == "seq001"
        assert cached_data[2]["shot"] == "shot002"

    def test_cache_expiration(self, shot_model, sample_shots, temp_cache_dir):
        """Test that expired cache is not used."""
        # Cache shots - passes Shot objects directly
        shot_model.cache_manager.cache_shots(sample_shots)

        # Manually modify cache file to be expired
        cache_file = temp_cache_dir / "shots.json"
        with open(cache_file, "r") as f:
            cache_data = json.load(f)

        # Set timestamp to 2 hours ago (beyond 30 min expiry)
        cache_data["timestamp"] = time.time() - 7200

        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # Try to retrieve - should return None due to expiration
        cached_shots = shot_model.cache_manager.get_cached_shots()
        assert cached_shots is None

    def test_refresh_with_cache(self, shot_model, sample_shots):
        """Test model refresh behavior when command fails but cache exists."""
        # Clear shots first
        shot_model.shots.clear()

        # Pre-populate cache - passes Shot objects directly
        shot_model.cache_manager.cache_shots(sample_shots)

        # Mock ws command to simulate failure
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Command failed")

            # Refresh should fail when command fails (current behavior)
            success, has_changes = shot_model.refresh_shots()

            # Should fail when command fails (actual implementation behavior)
            assert success is False
            assert has_changes is False

            # But shots should still be available from cache loaded at initialization
            # (if cache was loaded during initialization)
            # Since we cleared shots after init, they should still be empty
            assert len(shot_model.shots) == 0

    def test_refresh_updates_cache(self, shot_model):
        """Test that successful refresh updates the cache."""
        # Mock successful ws command
        with patch("shot_model.subprocess.run") as mock_run:
            mock_output = """workspace /shows/testshow1/shots/seq001/shot001
workspace /shows/testshow2/shots/seq002/shot002"""

            mock_run.return_value = Mock(returncode=0, stdout=mock_output, stderr="")

            # Refresh shots
            success, has_changes = shot_model.refresh_shots()

            assert success is True
            assert has_changes is True
            assert len(shot_model.shots) == 2

            # Verify cache was updated
            cached_shots = shot_model.cache_manager.get_cached_shots()
            assert len(cached_shots) == 2
            assert cached_shots[0]["show"] == "testshow1"
            assert cached_shots[1]["show"] == "testshow2"

    def test_cache_persistence_across_instances(self, temp_cache_dir, sample_shots):
        """Test cache persists across different instances."""
        # Create first instance and cache shots
        cache_mgr1 = CacheManager(cache_dir=temp_cache_dir)
        cache_mgr1.cache_shots(sample_shots)

        # Create second instance and retrieve cached shots
        cache_mgr2 = CacheManager(cache_dir=temp_cache_dir)
        cached_shots = cache_mgr2.get_cached_shots()

        # Verify persistence - cached_shots are dictionaries
        assert len(cached_shots) == 3
        assert all(
            shot_data["show"] == f"testshow{i}"
            for i, shot_data in enumerate(cached_shots)
        )

    def test_concurrent_cache_access(self, temp_cache_dir, sample_shots):
        """Test concurrent access to cache doesn't cause issues."""
        import threading

        results = []
        errors = []

        def cache_operation(operation_type, shots=None):
            """Perform cache operation in thread."""
            try:
                cache_mgr = CacheManager(cache_dir=temp_cache_dir)

                if operation_type == "write":
                    cache_mgr.cache_shots(shots)
                    results.append("write_success")
                else:  # read
                    cached = cache_mgr.get_cached_shots()
                    results.append(("read_success", len(cached) if cached else 0))
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads for concurrent access
        threads = []

        # Writers
        for _ in range(2):
            t = threading.Thread(target=cache_operation, args=("write", sample_shots))
            threads.append(t)

        # Readers
        for _ in range(3):
            t = threading.Thread(target=cache_operation, args=("read",))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join(timeout=5)

        # Verify no errors occurred
        assert len(errors) == 0
        # At least some operations should succeed
        assert len(results) >= 3

    def test_invalid_cache_data_handling(self, shot_model, temp_cache_dir):
        """Test handling of corrupted cache data."""
        # Clear cache first
        shot_model.cache_manager.clear_cache()

        # Write invalid JSON to cache file
        cache_file = temp_cache_dir / "shots.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("{ invalid json ]")

        # Should handle gracefully and return None
        cached_shots = shot_model.cache_manager.get_cached_shots()
        assert cached_shots is None

        # Model should still work without cache
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="workspace /shows/show1/shots/seq001/shot001",
                stderr="",
            )

            success, has_changes = shot_model.refresh_shots()
            assert success is True
            assert len(shot_model.shots) == 1

    def test_cache_with_special_characters(self, cache_manager):
        """Test caching shots with special characters in names."""
        special_shots = [
            Shot(
                show="test show",
                sequence="seq-001",
                shot="shot_001",
                workspace_path="/shows/test show/shots/seq-001/shot_001",
            ),
            Shot(
                show="test@show",
                sequence="seq#002",
                shot="shot$002",
                workspace_path="/shows/test@show/shots/seq#002/shot$002",
            ),
        ]

        # Cache and retrieve
        cache_manager.cache_shots(special_shots)
        cached = cache_manager.get_cached_shots()

        # Verify special characters are preserved - cached data are dictionaries
        assert len(cached) == 2
        assert cached[0]["show"] == "test show"
        assert cached[1]["sequence"] == "seq#002"

    def test_empty_cache_handling(self, shot_model):
        """Test model behavior with empty cache."""
        # Clear cache first to ensure it's empty
        shot_model.cache_manager.clear_cache()

        # Ensure cache is empty
        cached = shot_model.cache_manager.get_cached_shots()
        assert cached is None

        # Model should handle empty cache gracefully
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("No ws command")

            success, has_changes = shot_model.refresh_shots()
            assert success is False
            assert has_changes is False
            assert len(shot_model.shots) == 0
