"""Parameterized contract tests for pin managers.

Tests shared behavioral contracts of FilePinManager and PinManager via
adapter fixtures. Each contract test runs twice — once for each manager type.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from cache_manager import CacheManager
from config import Config
from file_pin_manager import PINNED_FILES_CACHE_KEY, FilePinManager
from pin_manager import PINNED_SHOTS_CACHE_KEY, PinManager
from type_definitions import Shot


if TYPE_CHECKING:
    from collections.abc import Callable, Generator


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class PinManagerAdapter:
    """Adapter normalizing pin manager APIs for contract testing."""

    manager: Any
    items: list[Any]  # Pre-created test items (paths or shots)
    pin: Callable[[Any], None]
    unpin: Callable[[Any], None]
    is_pinned: Callable[[Any], bool]
    get_count: Callable[[], int]
    clear: Callable[[], None]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_adapter(cache_dir: Path) -> tuple[PinManagerAdapter, FilePinManager]:
    cm = CacheManager(cache_dir=cache_dir)
    mgr = FilePinManager(cm)
    items: list[Any] = [
        Path("/shows/test/shots/seq01/shot010/3de/scene_v001.3de"),
        Path("/shows/test/shots/seq01/shot010/maya/scene_v002.mb"),
        Path("/shows/test/shots/seq01/shot020/nuke/comp_v003.nk"),
    ]
    adapter = PinManagerAdapter(
        manager=mgr,
        items=items,
        pin=lambda item: mgr.pin_file(item),
        unpin=lambda item: mgr.unpin_file(item),
        is_pinned=lambda item: mgr.is_pinned(item),
        get_count=mgr.get_pinned_count,
        clear=mgr.clear_pins,
    )
    return adapter, mgr


def _make_shot_adapter(cache_dir: Path) -> tuple[PinManagerAdapter, PinManager]:
    cm = CacheManager(cache_dir=cache_dir)
    mgr = PinManager(cm)
    items: list[Any] = [
        Shot("test_show", "seq01", "shot010", f"{Config.SHOWS_ROOT}/test_show/seq01/shot010"),
        Shot("test_show", "seq01", "shot020", f"{Config.SHOWS_ROOT}/test_show/seq01/shot020"),
        Shot("test_show", "seq02", "shot030", f"{Config.SHOWS_ROOT}/test_show/seq02/shot030"),
    ]
    adapter = PinManagerAdapter(
        manager=mgr,
        items=items,
        pin=lambda item: mgr.pin_shot(item),
        unpin=lambda item: mgr.unpin_shot(item),
        is_pinned=lambda item: mgr.is_pinned(item),
        get_count=mgr.get_pinned_count,
        clear=mgr.clear_pins,
    )
    return adapter, mgr


# ---------------------------------------------------------------------------
# Main fixture
# ---------------------------------------------------------------------------


@pytest.fixture(params=["file", "shot"])
def pin_adapter(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[PinManagerAdapter, None, None]:
    """Yield a PinManagerAdapter for either FilePinManager or PinManager."""
    cache_dir = tmp_path / "cache"

    if request.param == "file":
        adapter, mgr = _make_file_adapter(cache_dir)
        yield adapter
        mgr.deleteLater()
    else:
        adapter, _mgr = _make_shot_adapter(cache_dir)
        yield adapter


# ---------------------------------------------------------------------------
# Persistence factory fixture
# ---------------------------------------------------------------------------


@pytest.fixture(params=["file", "shot"])
def pin_factory(
    request: pytest.FixtureRequest, tmp_path: Path
) -> tuple[str, Callable[[Path], tuple[PinManagerAdapter, Any]]]:
    """Yield (param_name, factory) for persistence tests that need multiple instances."""
    param: str = request.param

    if param == "file":
        def factory(cache_dir: Path) -> tuple[PinManagerAdapter, FilePinManager]:
            return _make_file_adapter(cache_dir)
        return param, factory
    def factory(cache_dir: Path) -> tuple[PinManagerAdapter, PinManager]:  # type: ignore[misc]
        return _make_shot_adapter(cache_dir)
    return param, factory


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestPinContract:
    """Core pin/unpin/is_pinned/count/clear contract shared by all managers."""

    def test_pin_marks_as_pinned(self, pin_adapter: PinManagerAdapter) -> None:
        """Pinning an item should mark it as pinned."""
        item = pin_adapter.items[0]
        assert not pin_adapter.is_pinned(item)
        pin_adapter.pin(item)
        assert pin_adapter.is_pinned(item)

    def test_pin_increments_count(self, pin_adapter: PinManagerAdapter) -> None:
        """Each unique pin should increment the count."""
        item1, item2, _ = pin_adapter.items
        pin_adapter.pin(item1)
        assert pin_adapter.get_count() == 1
        pin_adapter.pin(item2)
        assert pin_adapter.get_count() == 2

    def test_repin_same_item_no_duplicate(self, pin_adapter: PinManagerAdapter) -> None:
        """Re-pinning an already-pinned item should not create a duplicate."""
        item = pin_adapter.items[0]
        pin_adapter.pin(item)
        pin_adapter.pin(item)
        pin_adapter.pin(item)
        assert pin_adapter.get_count() == 1

    def test_unpin_removes_pin(self, pin_adapter: PinManagerAdapter) -> None:
        """Unpinning a pinned item should mark it as not pinned."""
        item = pin_adapter.items[0]
        pin_adapter.pin(item)
        assert pin_adapter.is_pinned(item)
        pin_adapter.unpin(item)
        assert not pin_adapter.is_pinned(item)

    def test_unpin_decrements_count(self, pin_adapter: PinManagerAdapter) -> None:
        """Unpinning should decrement the count."""
        item1, item2, _ = pin_adapter.items
        pin_adapter.pin(item1)
        pin_adapter.pin(item2)
        assert pin_adapter.get_count() == 2
        pin_adapter.unpin(item1)
        assert pin_adapter.get_count() == 1

    def test_unpin_nonexistent_is_noop(self, pin_adapter: PinManagerAdapter) -> None:
        """Unpinning an item that is not pinned should not raise."""
        item = pin_adapter.items[0]
        # Should not raise
        pin_adapter.unpin(item)
        assert not pin_adapter.is_pinned(item)

    def test_is_pinned_false_initially(self, pin_adapter: PinManagerAdapter) -> None:
        """Items should not be pinned before any pin operation."""
        for item in pin_adapter.items:
            assert not pin_adapter.is_pinned(item)

    def test_is_pinned_true_after_pin(self, pin_adapter: PinManagerAdapter) -> None:
        """is_pinned should return True after pinning."""
        item = pin_adapter.items[0]
        pin_adapter.pin(item)
        assert pin_adapter.is_pinned(item)

    def test_count_starts_at_zero(self, pin_adapter: PinManagerAdapter) -> None:
        """Initial count should be zero."""
        assert pin_adapter.get_count() == 0

    def test_count_tracks_pins(self, pin_adapter: PinManagerAdapter) -> None:
        """Count should accurately reflect number of pinned items."""
        for i, item in enumerate(pin_adapter.items):
            pin_adapter.pin(item)
            assert pin_adapter.get_count() == i + 1

    def test_clear_removes_all(self, pin_adapter: PinManagerAdapter) -> None:
        """clear() should remove all pinned items."""
        for item in pin_adapter.items:
            pin_adapter.pin(item)
        assert pin_adapter.get_count() == len(pin_adapter.items)

        pin_adapter.clear()

        assert pin_adapter.get_count() == 0
        for item in pin_adapter.items:
            assert not pin_adapter.is_pinned(item)

    def test_clear_resets_count(self, pin_adapter: PinManagerAdapter) -> None:
        """Count should be zero after clear()."""
        for item in pin_adapter.items:
            pin_adapter.pin(item)
        pin_adapter.clear()
        assert pin_adapter.get_count() == 0


# ---------------------------------------------------------------------------
# Persistence contract tests
# ---------------------------------------------------------------------------


class TestPinPersistenceContract:
    """Persistence and cache-recovery contract shared by all managers."""

    def test_pins_survive_new_instance(
        self,
        pin_factory: tuple[str, Callable[[Path], tuple[PinManagerAdapter, Any]]],
        tmp_path: Path,
    ) -> None:
        """Pins written by one instance should be readable by a fresh instance."""
        _param, factory = pin_factory
        cache_dir = tmp_path / "cache"

        # First instance — pin two items
        adapter1, mgr1 = factory(cache_dir)
        item0, item1, _ = adapter1.items
        adapter1.pin(item0)
        adapter1.pin(item1)
        if hasattr(mgr1, "deleteLater"):
            mgr1.deleteLater()

        # Second instance — should see persisted pins
        adapter2, mgr2 = factory(cache_dir)
        assert adapter2.is_pinned(item0)
        assert adapter2.is_pinned(item1)
        assert adapter2.get_count() == 2
        if hasattr(mgr2, "deleteLater"):
            mgr2.deleteLater()

    def test_missing_cache_handled(
        self,
        pin_factory: tuple[str, Callable[[Path], tuple[PinManagerAdapter, Any]]],
        tmp_path: Path,
    ) -> None:
        """A manager created without any existing cache file should start empty."""
        _param, factory = pin_factory
        cache_dir = tmp_path / "empty_cache"
        adapter, mgr = factory(cache_dir)
        assert adapter.get_count() == 0
        if hasattr(mgr, "deleteLater"):
            mgr.deleteLater()

    def test_corrupted_json_handled(
        self,
        pin_factory: tuple[str, Callable[[Path], tuple[PinManagerAdapter, Any]]],
        tmp_path: Path,
    ) -> None:
        """A manager should start empty and not raise when the cache file is corrupt JSON."""
        param, factory = pin_factory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Write a corrupt JSON file for whichever cache key this manager uses
        cache_key = PINNED_FILES_CACHE_KEY if param == "file" else PINNED_SHOTS_CACHE_KEY
        cache_file = cache_dir / f"{cache_key}.json"
        cache_file.write_text("not valid json {{{")

        adapter, mgr = factory(cache_dir)
        assert adapter.get_count() == 0
        if hasattr(mgr, "deleteLater"):
            mgr.deleteLater()

    def test_invalid_format_handled(
        self,
        pin_factory: tuple[str, Callable[[Path], tuple[PinManagerAdapter, Any]]],
        tmp_path: Path,
    ) -> None:
        """A manager should start empty when cache has valid JSON but wrong top-level type."""
        param, factory = pin_factory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_key = PINNED_FILES_CACHE_KEY if param == "file" else PINNED_SHOTS_CACHE_KEY
        cache_file = cache_dir / f"{cache_key}.json"

        # FilePinManager expects a dict; PinManager expects a list — give each the wrong type
        wrong_content = json.dumps([{"wrong": "format"}] if param == "file" else {"wrong": "format"})
        cache_file.write_text(wrong_content)

        adapter, mgr = factory(cache_dir)
        assert adapter.get_count() == 0
        if hasattr(mgr, "deleteLater"):
            mgr.deleteLater()

    def test_partial_data_handled(
        self,
        pin_factory: tuple[str, Callable[[Path], tuple[PinManagerAdapter, Any]]],
        tmp_path: Path,
    ) -> None:
        """A manager should skip invalid entries and load only valid ones."""
        param, factory = pin_factory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_key = PINNED_FILES_CACHE_KEY if param == "file" else PINNED_SHOTS_CACHE_KEY
        cache_file = cache_dir / f"{cache_key}.json"

        if param == "file":
            # FilePinManager: dict format, one entry has a non-dict value (invalid)
            data: Any = {
                "/path/to/valid.3de": {"comment": "ok", "pinned_at": "2025-01-01"},
                "/path/to/invalid.3de": "not a dict",
                "/path/to/also_valid.mb": {"comment": "also ok", "pinned_at": "2025-01-01"},
            }
            cache_file.write_text(json.dumps(data))
            adapter, mgr = factory(cache_dir)
            assert adapter.get_count() == 2
        else:
            # PinManager: list format, one entry is missing required fields
            data = [
                {"show": "show1", "sequence": "seq01", "shot": "shot010"},
                {"show": "show2"},  # Missing sequence and shot
                {"show": "show3", "sequence": "seq02", "shot": "shot020"},
            ]
            cache_file.write_text(json.dumps(data))
            adapter, mgr = factory(cache_dir)
            assert adapter.get_count() == 2

        if hasattr(mgr, "deleteLater"):
            mgr.deleteLater()
