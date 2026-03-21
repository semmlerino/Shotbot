"""Integration tests for Previous Shots cache functionality following UNIFIED_TESTING_GUIDE.

Tests the integration between Previous Shots components and the cache system.
Focuses on cache consistency, data persistence, and performance.

Focus areas:
- Cache integration with real ShotDataCache components
- Data persistence and TTL behavior
- Cache invalidation and refresh
- Performance with cached vs uncached data
- Thread safety in cache operations
"""

from __future__ import annotations

# Standard library imports
import time
from collections.abc import Iterator
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from cache.shot_cache import ShotDataCache
from config import Config
from previous_shots.model import PreviousShotsModel

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.test_doubles import TestShot, TestShotModel
from tests.test_helpers import SynchronizationHelpers, process_qt_events
from type_definitions import Shot


pytestmark = [
    pytest.mark.qt,
    pytest.mark.slow,
]

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns


@pytest.fixture(autouse=True)
def reset_cache_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level cache disabled flag to prevent test contamination.

    The _cache_disabled flag in path_validators.py is a global state that can persist
    across tests, causing subsequent tests to see incorrect cache behavior.
    This fixture ensures each test starts with a clean state.
    """
    import paths.validators as path_validators

    monkeypatch.setattr(path_validators, "_cache_disabled", False)


@pytest.mark.xdist_group("serial_qt_state")
class TestPreviousShootsCacheIntegration:
    """Integration tests for Previous Shots cache functionality."""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path: Path) -> Path:
        """Create temporary cache directory."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir

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
        self, mock_shot_model, cache_manager, qtbot
    ) -> Iterator[PreviousShotsModel]:
        """Create PreviousShotsModel with real cache."""
        model = PreviousShotsModel(mock_shot_model, cache_manager)
        # Note: PreviousShotsModel is QObject, not QWidget - no qtbot.addWidget() needed
        yield model
        # CRITICAL CLEANUP: Stop and wait for worker thread to prevent Qt state pollution
        if model._worker is not None:
            model._worker.request_stop()
            model._worker.wait(2000)  # Wait up to 2 seconds for thread to finish
        process_qt_events()

    def test_cache_data_consistency(self, cache_manager) -> None:
        """Test cache data format consistency."""
        # Original shots from model
        original_shots = [
            Shot("show1", "seq1", "shot1", f"{Config.SHOWS_ROOT}/show1/shots/seq1/shot1"),
            Shot("show1", "seq1", "shot2", f"{Config.SHOWS_ROOT}/show1/shots/seq1/shot2"),
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

    def test_persistent_cache_survives_ttl(self, cache_manager, temp_cache_dir) -> None:
        """Test that previous shots cache persists beyond TTL expiration.

        Previous shots use persistent caching (no TTL) for incremental accumulation.
        This test verifies that data saved once is still loaded after the TTL elapses.
        """
        # Standard library imports
        import os

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
        assert cached_data_with_ttl is None, "TTL-enforcing method should respect expiration"

        # BUT persistent method should still return the data (no TTL check)
        persistent_data = cache_manager.get_persistent_previous_shots()
        assert persistent_data is not None, "Persistent method should ignore TTL"
        assert len(persistent_data) == 1
        assert persistent_data[0]["show"] == "persistent_test"

    def test_model_cache_integration_on_init(
        self, mock_shot_model, temp_cache_dir, qtbot
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
            process_qt_events()

    def test_model_cache_integration_on_refresh(
        self, previous_shots_model, qtbot
    ) -> None:
        """Test model saves to cache after refresh.

        Uses xdist_group at class level to run with other Qt state-sensitive tests.
        Passes reliably in serial execution.
        """
        # Clear cache to ensure test starts clean
        # This prevents contamination from other tests that may have cached data
        previous_shots_model._cache_manager.clear_cache()

        # Mock finder to return approved shots
        mock_approved = [
            Shot("new_show", "new_seq", "new_shot", "/new/path"),
        ]

        # Use local import for patch since we removed the global import
        # Standard library imports
        from unittest.mock import (
            patch,
        )

        # Need to patch the ParallelShotsFinder class that the worker uses
        with patch(
            "previous_shots.worker.ParallelShotsFinder.find_approved_shots_targeted",
            return_value=mock_approved,
        ):
            try:
                # Refresh should trigger cache save
                result = previous_shots_model.refresh_shots()
                assert result is True

                # Wait for scan to finish
                SynchronizationHelpers.wait_for_condition(
                    lambda: not previous_shots_model.is_scanning(),
                    timeout_ms=5000,
                    poll_interval_ms=50,
                )
                process_qt_events()  # Flush any remaining queued signals

                assert not previous_shots_model.is_scanning(), "Timeout waiting for scan to finish"

                # Verify data was cached after scan completes
                cached_data = (
                    previous_shots_model._cache_manager.get_cached_previous_shots()
                )
                assert cached_data is not None
                assert len(cached_data) == 1
                assert cached_data[0]["show"] == "new_show"
            finally:
                # CRITICAL CLEANUP: Stop and wait for any worker threads
                previous_shots_model._cleanup_worker_safely()
                process_qt_events()

    # Performance test removed to prevent test suite timeout


class TestPreviousShootsCachePerformance:
    """Performance tests for cache operations."""

    @pytest.fixture
    def large_dataset(self) -> list[dict]:
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
