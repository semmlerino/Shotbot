"""Comprehensive tests for ShotPinManager.

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
from config import Config
from managers.shot_pin_manager import PINNED_SHOTS_CACHE_KEY, ShotPinManager
from type_definitions import Shot


pytestmark = [
    pytest.mark.unit,
]


# Test fixtures following UNIFIED_TESTING_GUIDE patterns


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    d = tmp_path / "test_cache"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def pin_manager(cache_dir: Path) -> ShotPinManager:
    """Create ShotPinManager with test cache directory."""
    return ShotPinManager(cache_dir)


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
        self, pin_manager: ShotPinManager, sample_shots: list[Shot]
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
        self, pin_manager: ShotPinManager, sample_shots: list[Shot]
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


class TestUnpinShot:
    """Tests for unpin_shot() method."""

    def test_unpin_shot_updates_order(
        self, pin_manager: ShotPinManager, sample_shots: list[Shot]
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


class TestGetPinOrder:
    """Tests for get_pin_order() method."""

    def test_get_pin_order_returns_negative_for_unpinned(
        self, pin_manager: ShotPinManager, sample_shots: list[Shot]
    ) -> None:
        """Unpinned shots should return -1."""
        shot = sample_shots[0]
        assert pin_manager.get_pin_order(shot) == -1

    def test_get_pin_order_returns_correct_index(
        self, pin_manager: ShotPinManager, sample_shots: list[Shot]
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


# ============= Persistence Tests =============


class TestPersistence:
    """Tests for cache persistence."""

    def test_pin_order_persists(
        self, cache_dir: Path, sample_shots: list[Shot]
    ) -> None:
        """Pin order should persist across instances."""
        shot1, shot2, shot3 = sample_shots

        # Pin shots in specific order
        pm1 = ShotPinManager(cache_dir)
        pm1.pin_shot(shot1)
        pm1.pin_shot(shot2)
        pm1.pin_shot(shot3)

        # Create new instance
        pm2 = ShotPinManager(cache_dir)

        # Order should be preserved (most recent first)
        assert pm2.get_pin_order(shot3) == 0
        assert pm2.get_pin_order(shot2) == 1
        assert pm2.get_pin_order(shot1) == 2

    def test_cache_file_format(
        self, cache_dir: Path, sample_shots: list[Shot]
    ) -> None:
        """Cache file should be valid JSON with expected format."""
        shot = sample_shots[0]

        pm = ShotPinManager(cache_dir)
        pm.pin_shot(shot)

        # Read the cache file
        cache_file = cache_dir / f"{PINNED_SHOTS_CACHE_KEY}.json"
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



# ============= Edge Case Tests =============


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_different_shot_objects_same_key(
        self, pin_manager: ShotPinManager
    ) -> None:
        """Different Shot objects with same key should be treated as same."""
        shot1 = Shot("show", "seq", "shot", "/path1")
        shot2 = Shot("show", "seq", "shot", "/path2")  # Different path, same key

        pin_manager.pin_shot(shot1)
        assert pin_manager.is_pinned(shot2)  # Should match on key, not object identity

        pin_manager.unpin_shot(shot2)
        assert not pin_manager.is_pinned(shot1)  # Should unpin both
