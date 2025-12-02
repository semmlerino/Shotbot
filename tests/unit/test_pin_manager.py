"""Comprehensive tests for PinManager.

This test suite validates pin_manager.py following
UNIFIED_TESTING_GUIDE.md principles:
- Test behavior, not implementation
- Use real components with temporary storage
- Persistence validation
"""

from __future__ import annotations

# Standard library imports
import json
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from cache_manager import CacheManager
from config import Config
from pin_manager import PINNED_SHOTS_CACHE_KEY, PinManager
from shot_model import Shot


pytestmark = [
    pytest.mark.unit,
]


# Test fixtures following UNIFIED_TESTING_GUIDE patterns


@pytest.fixture
def cache_manager(tmp_path: Path) -> CacheManager:
    """Create CacheManager with temporary directory."""
    cache_dir = tmp_path / "test_cache"
    return CacheManager(cache_dir=cache_dir)


@pytest.fixture
def pin_manager(cache_manager: CacheManager) -> PinManager:
    """Create PinManager with test cache manager."""
    return PinManager(cache_manager)


@pytest.fixture
def sample_shots() -> list[Shot]:
    """Provide realistic shot data for testing."""
    return [
        Shot("test_show", "seq01", "shot010", f"{Config.SHOWS_ROOT}/test_show/seq01/shot010"),
        Shot("test_show", "seq01", "shot020", f"{Config.SHOWS_ROOT}/test_show/seq01/shot020"),
        Shot("test_show", "seq02", "shot030", f"{Config.SHOWS_ROOT}/test_show/seq02/shot030"),
    ]


# ============= Core Functionality Tests =============


class TestPinShot:
    """Tests for pin_shot() method."""

    def test_pin_shot_adds_to_front(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Pinning a shot should add it to the front of the list."""
        shot1, shot2, shot3 = sample_shots

        pin_manager.pin_shot(shot1)
        pin_manager.pin_shot(shot2)
        pin_manager.pin_shot(shot3)

        # Most recently pinned should be at index 0
        assert pin_manager.get_pin_order(shot3) == 0
        assert pin_manager.get_pin_order(shot2) == 1
        assert pin_manager.get_pin_order(shot1) == 2

    def test_pin_shot_moves_existing_to_front(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Re-pinning an already pinned shot should move it to the front."""
        shot1, shot2, shot3 = sample_shots

        pin_manager.pin_shot(shot1)
        pin_manager.pin_shot(shot2)
        pin_manager.pin_shot(shot3)

        # Re-pin shot1 (currently at index 2)
        pin_manager.pin_shot(shot1)

        # shot1 should now be at front
        assert pin_manager.get_pin_order(shot1) == 0
        assert pin_manager.get_pin_order(shot3) == 1
        assert pin_manager.get_pin_order(shot2) == 2

    def test_pin_shot_marks_as_pinned(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Pinned shot should be marked as pinned."""
        shot = sample_shots[0]

        assert not pin_manager.is_pinned(shot)
        pin_manager.pin_shot(shot)
        assert pin_manager.is_pinned(shot)


class TestUnpinShot:
    """Tests for unpin_shot() method."""

    def test_unpin_shot_removes_from_list(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Unpinning should remove shot from pinned list."""
        shot1, shot2, _ = sample_shots

        pin_manager.pin_shot(shot1)
        pin_manager.pin_shot(shot2)

        assert pin_manager.is_pinned(shot1)
        pin_manager.unpin_shot(shot1)
        assert not pin_manager.is_pinned(shot1)

    def test_unpin_shot_updates_order(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Unpinning should update order of remaining pins."""
        shot1, shot2, shot3 = sample_shots

        pin_manager.pin_shot(shot1)
        pin_manager.pin_shot(shot2)
        pin_manager.pin_shot(shot3)

        # Remove middle pin
        pin_manager.unpin_shot(shot2)

        assert pin_manager.get_pin_order(shot3) == 0
        assert pin_manager.get_pin_order(shot1) == 1
        assert pin_manager.get_pin_order(shot2) == -1  # Not pinned

    def test_unpin_nonexistent_is_noop(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Unpinning a non-pinned shot should not raise."""
        shot = sample_shots[0]

        # Should not raise
        pin_manager.unpin_shot(shot)
        assert not pin_manager.is_pinned(shot)


class TestIsPinned:
    """Tests for is_pinned() method."""

    def test_is_pinned_returns_false_for_unpinned(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Unpinned shots should return False."""
        shot = sample_shots[0]
        assert not pin_manager.is_pinned(shot)

    def test_is_pinned_returns_true_for_pinned(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Pinned shots should return True."""
        shot = sample_shots[0]
        pin_manager.pin_shot(shot)
        assert pin_manager.is_pinned(shot)


class TestGetPinOrder:
    """Tests for get_pin_order() method."""

    def test_get_pin_order_returns_negative_for_unpinned(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Unpinned shots should return -1."""
        shot = sample_shots[0]
        assert pin_manager.get_pin_order(shot) == -1

    def test_get_pin_order_returns_correct_index(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Pin order should reflect position in list."""
        shot1, shot2, shot3 = sample_shots

        pin_manager.pin_shot(shot1)
        pin_manager.pin_shot(shot2)
        pin_manager.pin_shot(shot3)

        # Order is most-recently-pinned first
        assert pin_manager.get_pin_order(shot3) == 0
        assert pin_manager.get_pin_order(shot2) == 1
        assert pin_manager.get_pin_order(shot1) == 2


class TestGetPinnedCount:
    """Tests for get_pinned_count() method."""

    def test_get_pinned_count_starts_at_zero(
        self, pin_manager: PinManager
    ) -> None:
        """Initial count should be zero."""
        assert pin_manager.get_pinned_count() == 0

    def test_get_pinned_count_increments(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Count should increment when pinning."""
        shot1, shot2, _ = sample_shots

        pin_manager.pin_shot(shot1)
        assert pin_manager.get_pinned_count() == 1

        pin_manager.pin_shot(shot2)
        assert pin_manager.get_pinned_count() == 2

    def test_get_pinned_count_decrements_on_unpin(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Count should decrement when unpinning."""
        shot1, shot2, _ = sample_shots

        pin_manager.pin_shot(shot1)
        pin_manager.pin_shot(shot2)
        assert pin_manager.get_pinned_count() == 2

        pin_manager.unpin_shot(shot1)
        assert pin_manager.get_pinned_count() == 1


class TestClearPins:
    """Tests for clear_pins() method."""

    def test_clear_pins_removes_all(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Clear should remove all pinned shots."""
        for shot in sample_shots:
            pin_manager.pin_shot(shot)

        assert pin_manager.get_pinned_count() == 3

        pin_manager.clear_pins()

        assert pin_manager.get_pinned_count() == 0
        for shot in sample_shots:
            assert not pin_manager.is_pinned(shot)


# ============= Persistence Tests =============


class TestPersistence:
    """Tests for cache persistence."""

    def test_pins_persist_across_instances(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Pinned shots should persist when creating a new PinManager instance."""
        shot1, shot2, _ = sample_shots

        # Pin shots with first instance
        pm1 = PinManager(cache_manager)
        pm1.pin_shot(shot1)
        pm1.pin_shot(shot2)

        # Create new instance
        pm2 = PinManager(cache_manager)

        # Pins should be loaded
        assert pm2.is_pinned(shot1)
        assert pm2.is_pinned(shot2)
        assert pm2.get_pinned_count() == 2

    def test_pin_order_persists(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Pin order should persist across instances."""
        shot1, shot2, shot3 = sample_shots

        # Pin shots in specific order
        pm1 = PinManager(cache_manager)
        pm1.pin_shot(shot1)
        pm1.pin_shot(shot2)
        pm1.pin_shot(shot3)

        # Create new instance
        pm2 = PinManager(cache_manager)

        # Order should be preserved (most recent first)
        assert pm2.get_pin_order(shot3) == 0
        assert pm2.get_pin_order(shot2) == 1
        assert pm2.get_pin_order(shot1) == 2

    def test_cache_file_format(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Cache file should be valid JSON with expected format."""
        shot = sample_shots[0]

        pm = PinManager(cache_manager)
        pm.pin_shot(shot)

        # Read the cache file
        cache_file = cache_manager.cache_dir / f"{PINNED_SHOTS_CACHE_KEY}.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            data = json.load(f)

        # Should be a list of dicts with show, sequence, shot keys
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["show"] == shot.show
        assert data[0]["sequence"] == shot.sequence
        assert data[0]["shot"] == shot.shot


class TestCacheRecovery:
    """Tests for handling corrupted or missing cache."""

    def test_handles_missing_cache_file(
        self, cache_manager: CacheManager
    ) -> None:
        """Should handle missing cache file gracefully."""
        pm = PinManager(cache_manager)
        assert pm.get_pinned_count() == 0

    def test_handles_corrupted_json(
        self, cache_manager: CacheManager
    ) -> None:
        """Should handle corrupted JSON gracefully."""
        # Write corrupted JSON
        cache_file = cache_manager.cache_dir / f"{PINNED_SHOTS_CACHE_KEY}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json {{{")

        # Should not raise, should start with empty list
        pm = PinManager(cache_manager)
        assert pm.get_pinned_count() == 0

    def test_handles_invalid_cache_format(
        self, cache_manager: CacheManager
    ) -> None:
        """Should handle invalid cache format gracefully."""
        # Write valid JSON but wrong format
        cache_file = cache_manager.cache_dir / f"{PINNED_SHOTS_CACHE_KEY}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text('{"wrong": "format"}')

        # Should not raise, should start with empty list
        pm = PinManager(cache_manager)
        assert pm.get_pinned_count() == 0

    def test_handles_partial_cache_data(
        self, cache_manager: CacheManager
    ) -> None:
        """Should skip entries with missing required fields."""
        # Write valid JSON with some invalid entries
        cache_file = cache_manager.cache_dir / f"{PINNED_SHOTS_CACHE_KEY}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"show": "show1", "sequence": "seq01", "shot": "shot010"},  # Valid
            {"show": "show2"},  # Missing sequence and shot
            {"show": "show3", "sequence": "seq02", "shot": "shot020"},  # Valid
        ]
        cache_file.write_text(json.dumps(data))

        pm = PinManager(cache_manager)
        assert pm.get_pinned_count() == 2  # Only valid entries loaded


# ============= Edge Case Tests =============


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_pin_same_shot_multiple_times(
        self, pin_manager: PinManager, sample_shots: list[Shot]
    ) -> None:
        """Pinning same shot multiple times should not duplicate."""
        shot = sample_shots[0]

        pin_manager.pin_shot(shot)
        pin_manager.pin_shot(shot)
        pin_manager.pin_shot(shot)

        assert pin_manager.get_pinned_count() == 1

    def test_different_shot_objects_same_key(
        self, pin_manager: PinManager
    ) -> None:
        """Different Shot objects with same key should be treated as same."""
        shot1 = Shot("show", "seq", "shot", "/path1")
        shot2 = Shot("show", "seq", "shot", "/path2")  # Different path, same key

        pin_manager.pin_shot(shot1)
        assert pin_manager.is_pinned(shot2)  # Should match on key, not object identity

        pin_manager.unpin_shot(shot2)
        assert not pin_manager.is_pinned(shot1)  # Should unpin both
