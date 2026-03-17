"""Tests for HideManager.

Validates hide_manager.py behavior:
- Test behavior, not implementation
- Use real components with temporary storage
- Persistence validation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Config
from managers.hide_manager import HIDDEN_SHOTS_CACHE_KEY, HideManager
from type_definitions import Shot


pytestmark = [
    pytest.mark.unit,
]


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    d = tmp_path / "test_cache"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def hide_manager(cache_dir: Path) -> HideManager:
    """Create HideManager with test cache directory."""
    return HideManager(cache_dir)


@pytest.fixture
def sample_shots() -> list[Shot]:
    """Provide realistic shot data for testing."""
    return [
        Shot("test_show", "seq01", "shot010", f"{Config.SHOWS_ROOT}/test_show/seq01/shot010"),
        Shot("test_show", "seq01", "shot020", f"{Config.SHOWS_ROOT}/test_show/seq01/shot020"),
        Shot("test_show", "seq02", "shot030", f"{Config.SHOWS_ROOT}/test_show/seq02/shot030"),
    ]


class TestHideShot:
    """Tests for hide_shot() method."""

    def test_hide_shot_marks_as_hidden(
        self, hide_manager: HideManager, sample_shots: list[Shot]
    ) -> None:
        """Hiding a shot should mark it as hidden."""
        shot = sample_shots[0]
        hide_manager.hide_shot(shot)
        assert hide_manager.is_hidden(shot)

    def test_hide_shot_idempotent(
        self, hide_manager: HideManager, sample_shots: list[Shot]
    ) -> None:
        """Hiding an already hidden shot should not duplicate it."""
        shot = sample_shots[0]
        hide_manager.hide_shot(shot)
        hide_manager.hide_shot(shot)
        assert hide_manager.get_hidden_count() == 1

    def test_hide_multiple_shots(
        self, hide_manager: HideManager, sample_shots: list[Shot]
    ) -> None:
        """Hiding multiple shots increments the count correctly."""
        for shot in sample_shots:
            hide_manager.hide_shot(shot)
        assert hide_manager.get_hidden_count() == len(sample_shots)


class TestUnhideShot:
    """Tests for unhide_shot() method."""

    def test_unhide_shot(
        self, hide_manager: HideManager, sample_shots: list[Shot]
    ) -> None:
        """Unhiding a shot should remove the hidden status."""
        shot = sample_shots[0]
        hide_manager.hide_shot(shot)
        hide_manager.unhide_shot(shot)
        assert not hide_manager.is_hidden(shot)

    def test_unhide_non_hidden_shot_is_noop(
        self, hide_manager: HideManager, sample_shots: list[Shot]
    ) -> None:
        """Unhiding a shot that was never hidden should not error."""
        shot = sample_shots[0]
        hide_manager.unhide_shot(shot)  # Should not raise
        assert not hide_manager.is_hidden(shot)


class TestPersistence:
    """Tests for cache persistence."""

    def test_hide_shot_persists(
        self, cache_dir: Path, sample_shots: list[Shot]
    ) -> None:
        """Hiding a shot should persist across manager instances."""
        shot = sample_shots[0]

        hm1 = HideManager(cache_dir)
        hm1.hide_shot(shot)

        hm2 = HideManager(cache_dir)
        assert hm2.is_hidden(shot)

    def test_unhide_shot_persists(
        self, cache_dir: Path, sample_shots: list[Shot]
    ) -> None:
        """Unhiding a shot should persist across manager instances."""
        shot = sample_shots[0]

        hm1 = HideManager(cache_dir)
        hm1.hide_shot(shot)
        hm1.unhide_shot(shot)

        hm2 = HideManager(cache_dir)
        assert not hm2.is_hidden(shot)

    def test_hide_manager_persistence_json_format(
        self, cache_dir: Path, sample_shots: list[Shot]
    ) -> None:
        """Cache file should be valid JSON with expected format."""
        shot = sample_shots[0]

        hm = HideManager(cache_dir)
        hm.hide_shot(shot)

        cache_file = cache_dir / f"{HIDDEN_SHOTS_CACHE_KEY}.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["show"] == shot.show
        assert data[0]["sequence"] == shot.sequence
        assert data[0]["shot"] == shot.shot


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_different_shot_objects_same_key(
        self, hide_manager: HideManager
    ) -> None:
        """Different Shot objects with same key should be treated as same."""
        shot1 = Shot("show", "seq", "shot", "/path1")
        shot2 = Shot("show", "seq", "shot", "/path2")  # Different path, same key

        hide_manager.hide_shot(shot1)
        assert hide_manager.is_hidden(shot2)

        hide_manager.unhide_shot(shot2)
        assert not hide_manager.is_hidden(shot1)

    def test_empty_manager_returns_false(
        self, hide_manager: HideManager, sample_shots: list[Shot]
    ) -> None:
        """is_hidden should return False for any shot in a fresh manager."""
        for shot in sample_shots:
            assert not hide_manager.is_hidden(shot)

    def test_get_hidden_count_empty(self, hide_manager: HideManager) -> None:
        """Fresh manager should have zero hidden shots."""
        assert hide_manager.get_hidden_count() == 0
