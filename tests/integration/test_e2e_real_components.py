"""End-to-end tests using real components instead of test doubles.

These tests verify that the application works correctly with real:
- Filesystem operations (not mocked)
- Cache persistence (real JSON files)
- Settings persistence (real QSettings)
- Path validation (real filesystem checks)

The goal is to catch integration bugs that mocks might hide.

Run these tests serially for most reliable results:
    pytest tests/integration/test_e2e_real_components.py -n 0 -v
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from cache.shot_cache import ShotDataCache
from config import Config
from previous_shots.model import PreviousShotsModel
from tests.fixtures.model_fixtures import TestShot, TestShotModel
from type_definitions import Shot


pytestmark = [pytest.mark.qt]


# ==============================================================================
# E2E Cache Manager Tests
# ==============================================================================


class TestCacheManagerE2E:
    """End-to-end tests for ShotDataCache with real filesystem."""

    @pytest.fixture
    def real_cache_dir(self, tmp_path: Path) -> Path:
        """Create a real temporary cache directory."""
        cache_dir = tmp_path / "shotbot_e2e_cache"
        cache_dir.mkdir()
        return cache_dir

    @pytest.fixture
    def real_cache_manager(
        self, real_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> ShotDataCache:
        """Create a ShotDataCache with real filesystem operations."""
        # Point to our test cache directory
        monkeypatch.setenv("SHOTBOT_TEST_CACHE_DIR", str(real_cache_dir))

        return ShotDataCache(real_cache_dir)

    def test_shots_cache_persists_to_disk(
        self, real_cache_manager: ShotDataCache
    ) -> None:
        """Verify shot data is actually written to disk."""
        # Create test shot data
        shots = [
            {"show": "TESTSHOW", "sequence": "SQ010", "shot": "SH0010"},
            {"show": "TESTSHOW", "sequence": "SQ010", "shot": "SH0020"},
        ]

        # Cache the shots
        real_cache_manager.cache_shots(shots)

        # Verify cache file exists on disk
        cache_file = real_cache_manager.shots_cache_file
        assert cache_file.exists(), "Cache file should be created on disk"

        # Verify file contains correct data
        with cache_file.open() as f:
            cached_data = json.load(f)

        # Cache format: {"data": [...], "cached_at": "..."}
        assert "data" in cached_data
        assert len(cached_data["data"]) == 2

    def test_shots_cache_survives_manager_recreation(
        self, real_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify cached shots survive creating a new ShotDataCache instance."""
        monkeypatch.setenv("SHOTBOT_TEST_CACHE_DIR", str(real_cache_dir))

        # First manager caches shots
        manager1 = ShotDataCache(real_cache_dir)
        shots = [{"show": "SURVIVALTEST", "sequence": "SQ001", "shot": "SH0001"}]
        manager1.cache_shots(shots)

        # Create new manager pointing to same directory
        manager2 = ShotDataCache(real_cache_dir)

        # New manager should find cached shots
        cached = manager2.get_shots_with_ttl()
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["show"] == "SURVIVALTEST"

    def test_cache_ttl_expiration_real_time(
        self, real_cache_manager: ShotDataCache
    ) -> None:
        """Verify TTL expiration works with real time passage."""
        shots = [{"show": "TTLTEST", "sequence": "SQ001", "shot": "SH0001"}]
        real_cache_manager.cache_shots(shots)

        # TTL is checked via file mtime, not JSON content
        cache_file = real_cache_manager.shots_cache_file

        # Set file mtime to 1 hour ago (beyond default 30min TTL)
        old_time = time.time() - 3600
        os.utime(cache_file, (old_time, old_time))

        # Cache should now be expired
        cached = real_cache_manager.get_shots_with_ttl()
        assert cached is None, "Expired cache should return None"

    def test_previous_shots_cache_replacement(
        self, real_cache_manager: ShotDataCache
    ) -> None:
        """Verify previous shots cache replaces old data on write."""
        # First batch
        batch1 = [{"show": "SHOW1", "sequence": "SQ001", "shot": "SH0001"}]
        real_cache_manager.cache_previous_shots(batch1)

        # Verify first batch cached
        cached1 = real_cache_manager.get_cached_previous_shots()
        assert cached1 is not None
        assert len(cached1) == 1
        assert cached1[0]["show"] == "SHOW1"

        # Second batch replaces first
        batch2 = [{"show": "SHOW2", "sequence": "SQ002", "shot": "SH0002"}]
        real_cache_manager.cache_previous_shots(batch2)

        # Should only have second batch
        cached2 = real_cache_manager.get_cached_previous_shots()
        assert cached2 is not None
        assert len(cached2) == 1
        assert cached2[0]["show"] == "SHOW2"


# ==============================================================================
# Previous Shots Cache Integration Tests
# ==============================================================================


@pytest.fixture(autouse=True)
def reset_cache_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level cache disabled flag to prevent test contamination.

    The _cache_disabled flag in path_validators.py is a global state that can persist
    across tests, causing subsequent tests to see incorrect cache behavior.
    This fixture ensures each test starts with a clean state.
    """
    import paths.validators as path_validators

    monkeypatch.setattr(path_validators, "_cache_disabled", False)


@pytest.mark.slow
@pytest.mark.xdist_group("serial_qt_state")
class TestPreviousShootsCacheIntegration:
    """Integration tests for Previous Shots cache functionality."""

    @pytest.fixture
    def cache_manager(self, temp_cache_dir: Path) -> ShotDataCache:
        """Create real ShotDataCache with temporary storage."""
        return ShotDataCache(temp_cache_dir)

    @pytest.fixture
    def mock_shot_model(self) -> TestShotModel:
        """Create test double ShotModel."""
        mock_model = TestShotModel()
        # TestShotModel has real methods, not mocked ones
        # Add shots directly to the model
        test_shot = TestShot("active_show", "seq1", "shot1")
        test_shot.workspace_path = f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot1"
        mock_model.add_shot(test_shot)
        return mock_model

    @pytest.fixture
    def previous_shots_model(
        self,
        mock_shot_model: TestShotModel,
        cache_manager: ShotDataCache,
        qtbot: object,
    ) -> Iterator[PreviousShotsModel]:
        """Create PreviousShotsModel with real cache."""
        model = PreviousShotsModel(mock_shot_model, cache_manager)
        # Note: PreviousShotsModel is QObject, not QWidget - no qtbot.addWidget() needed
        yield model
        # CRITICAL CLEANUP: Stop and wait for worker thread to prevent Qt state pollution
        worker = model._worker_host.take()
        if worker is not None:
            worker.request_stop()
            worker.wait(2000)  # Wait up to 2 seconds for thread to finish
        qtbot.wait(1)

    def test_cache_data_consistency(self, cache_manager: ShotDataCache) -> None:
        """Test cache data format consistency."""
        # Original shots from model
        original_shots = [
            Shot(
                "show1", "seq1", "shot1", f"{Config.SHOWS_ROOT}/show1/shots/seq1/shot1"
            ),
            Shot(
                "show1", "seq1", "shot2", f"{Config.SHOWS_ROOT}/show1/shots/seq1/shot2"
            ),
        ]

        # Convert to cache format (as done by model)
        cache_data = [
            {
                "show": s.show,
                "sequence": s.sequence,
                "shot": s.shot,
                "workspace_path": s.workspace_path,
            }
            for s in original_shots
        ]

        # Cache and retrieve
        cache_manager.cache_previous_shots(cache_data)
        retrieved_data = cache_manager.get_cached_previous_shots()

        # Should be identical
        assert retrieved_data == cache_data

        # Convert back to Shot objects
        reconstructed_shots = [
            Shot(
                show=s["show"],
                sequence=s["sequence"],
                shot=s["shot"],
                workspace_path=s["workspace_path"],
            )
            for s in retrieved_data
        ]

        # Should match original shots
        for orig, recon in zip(original_shots, reconstructed_shots, strict=False):
            assert orig.show == recon.show
            assert orig.sequence == recon.sequence
            assert orig.shot == recon.shot
            assert orig.workspace_path == recon.workspace_path

    def test_persistent_cache_survives_ttl(
        self, cache_manager: ShotDataCache, temp_cache_dir: Path
    ) -> None:
        """Test that previous shots cache persists beyond TTL expiration.

        Previous shots use persistent caching (no TTL) for incremental accumulation.
        This test verifies that data saved once is still loaded after the TTL elapses.
        """
        # Cache some data
        test_data = [
            {
                "show": "persistent_test",
                "sequence": "seq",
                "shot": "shot",
                "workspace_path": "/path",
            }
        ]
        cache_manager.cache_previous_shots(test_data)

        # Verify data is cached with TTL-enforcing method
        assert cache_manager.get_cached_previous_shots() is not None

        # Manually modify file modification time to simulate expiration
        cache_file = temp_cache_dir / "previous_shots.json"

        # Set file modification time to 2 hours ago (beyond 30 minute TTL)
        old_timestamp = time.time() - (2 * 60 * 60)  # 2 hours ago
        os.utime(cache_file, (old_timestamp, old_timestamp))

        # TTL-enforcing method should return None for expired cache
        cached_data_with_ttl = cache_manager.get_cached_previous_shots()
        assert cached_data_with_ttl is None, (
            "TTL-enforcing method should respect expiration"
        )

        # BUT persistent method should still return the data (no TTL check)
        persistent_data = cache_manager.get_persistent_previous_shots()
        assert persistent_data is not None, "Persistent method should ignore TTL"
        assert len(persistent_data) == 1
        assert persistent_data[0]["show"] == "persistent_test"

    def test_model_cache_integration_on_init(
        self, mock_shot_model: TestShotModel, temp_cache_dir: Path, qtbot: object
    ) -> None:
        """Test model loads from cache on initialization."""
        # Pre-populate cache
        cache_manager = ShotDataCache(temp_cache_dir)
        test_data = [
            {
                "show": "cached_show",
                "sequence": "cached_seq",
                "shot": "cached_shot",
                "workspace_path": "/cached/path",
            }
        ]
        cache_manager.cache_previous_shots(test_data)

        # Create model - should load from cache
        model = PreviousShotsModel(mock_shot_model, cache_manager)
        # Note: PreviousShotsModel is QObject, not QWidget - no qtbot.addWidget needed

        try:
            # Should have loaded cached data
            shots = model.get_shots()
            assert len(shots) == 1
            assert shots[0].show == "cached_show"
            assert shots[0].shot == "cached_shot"
        finally:
            # CRITICAL CLEANUP: Stop and wait for any worker threads
            model._cleanup_worker_safely()
            qtbot.wait(1)

    def test_model_cache_integration_on_refresh(
        self, previous_shots_model: PreviousShotsModel, qtbot: object, mocker
    ) -> None:
        """Test model saves to cache after refresh.

        Uses xdist_group at class level to run with other Qt state-sensitive tests.
        Passes reliably in serial execution.
        """
        # Clear cache to ensure test starts clean
        # This prevents contamination from other tests that may have cached data
        previous_shots_model.cache_manager.clear_cache()

        # Mock finder to return approved shots
        mock_approved = [
            Shot("new_show", "new_seq", "new_shot", "/new/path"),
        ]

        # Need to patch the ParallelShotsFinder class that the worker uses
        mocker.patch(
            "previous_shots.worker.ParallelShotsFinder.find_approved_shots_targeted",
            return_value=mock_approved,
        )
        try:
            # Refresh should trigger cache save
            result = previous_shots_model.refresh_shots()
            assert result is True

            # Wait for scan to finish
            qtbot.waitUntil(
                lambda: not previous_shots_model.is_scanning(),
                timeout=5000,
            )
            qtbot.wait(1)  # Flush any remaining queued signals

            assert not previous_shots_model.is_scanning(), (
                "Timeout waiting for scan to finish"
            )

            # Verify data was cached after scan completes
            cached_data = (
                previous_shots_model.cache_manager.get_cached_previous_shots()
            )
            assert cached_data is not None
            assert len(cached_data) == 1
            assert cached_data[0]["show"] == "new_show"
        finally:
            # CRITICAL CLEANUP: Stop and wait for any worker threads
            previous_shots_model._cleanup_worker_safely()
            qtbot.wait(1)


@pytest.mark.slow
class TestPreviousShootsCachePerformance:
    """Performance tests for cache operations."""

    @pytest.fixture
    def large_dataset(self) -> list[dict]:  # type: ignore[type-arg]
        """Create large dataset for performance testing."""
        return [
            {
                "show": f"show_{i:03d}",
                "sequence": f"seq_{j:03d}",
                "shot": f"shot_{k:04d}",
                "workspace_path": f"{Config.SHOWS_ROOT}/show_{i:03d}/shots/seq_{j:03d}/shot_{k:04d}",
            }
            for i in range(10)  # 10 shows
            for j in range(5)  # 5 sequences per show
            for k in range(20)  # 20 shots per sequence
        ]  # Total: 1000 shots

    # Performance tests removed to prevent test suite timeout
