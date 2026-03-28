"""Parameterized contract tests for pin managers.

Tests shared behavioral contracts of FilePinManager and ShotPinManager via
adapter fixtures. Each contract test runs twice — once for each manager type.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from config import Config
from managers.file_pin_manager import PINNED_FILES_CACHE_KEY, FilePinManager
from managers.shot_pin_manager import PINNED_SHOTS_CACHE_KEY, ShotPinManager
from type_definitions import Shot


if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from pytestqt.qtbot import QtBot


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
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = FilePinManager(cache_dir)
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


def _make_shot_adapter(cache_dir: Path) -> tuple[PinManagerAdapter, ShotPinManager]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = ShotPinManager(cache_dir)
    items: list[Any] = [
        Shot(
            "test_show",
            "seq01",
            "shot010",
            f"{Config.SHOWS_ROOT}/test_show/seq01/shot010",
        ),
        Shot(
            "test_show",
            "seq01",
            "shot020",
            f"{Config.SHOWS_ROOT}/test_show/seq01/shot020",
        ),
        Shot(
            "test_show",
            "seq02",
            "shot030",
            f"{Config.SHOWS_ROOT}/test_show/seq02/shot030",
        ),
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
def pin_adapter(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Generator[PinManagerAdapter, None, None]:
    """Yield a PinManagerAdapter for either FilePinManager or ShotPinManager."""
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

    def factory(cache_dir: Path) -> tuple[PinManagerAdapter, ShotPinManager]:  # type: ignore[misc]
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
        cache_key = (
            PINNED_FILES_CACHE_KEY if param == "file" else PINNED_SHOTS_CACHE_KEY
        )
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

        cache_key = (
            PINNED_FILES_CACHE_KEY if param == "file" else PINNED_SHOTS_CACHE_KEY
        )
        cache_file = cache_dir / f"{cache_key}.json"

        # FilePinManager expects a dict; ShotPinManager expects a list — give each the wrong type
        wrong_content = json.dumps(
            [{"wrong": "format"}] if param == "file" else {"wrong": "format"}
        )
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

        cache_key = (
            PINNED_FILES_CACHE_KEY if param == "file" else PINNED_SHOTS_CACHE_KEY
        )
        cache_file = cache_dir / f"{cache_key}.json"

        if param == "file":
            # FilePinManager: dict format, one entry has a non-dict value (invalid)
            data: Any = {
                "/path/to/valid.3de": {"comment": "ok", "pinned_at": "2025-01-01"},
                "/path/to/invalid.3de": "not a dict",
                "/path/to/also_valid.mb": {
                    "comment": "also ok",
                    "pinned_at": "2025-01-01",
                },
            }
            cache_file.write_text(json.dumps(data))
            adapter, mgr = factory(cache_dir)
            assert adapter.get_count() == 2
        else:
            # ShotPinManager: list format, one entry is missing required fields
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


# ---------------------------------------------------------------------------
# ShotPinManager-specific fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def shot_pin_manager(tmp_path: Path) -> ShotPinManager:
    """Create a ShotPinManager with a temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return ShotPinManager(cache_dir)


@pytest.fixture
def sample_shots() -> list[Shot]:
    """Provide realistic shot data for testing."""
    return [
        Shot(
            "test_show",
            "seq01",
            "shot010",
            f"{Config.SHOWS_ROOT}/test_show/seq01/shot010",
        ),
        Shot(
            "test_show",
            "seq01",
            "shot020",
            f"{Config.SHOWS_ROOT}/test_show/seq01/shot020",
        ),
        Shot(
            "test_show",
            "seq02",
            "shot030",
            f"{Config.SHOWS_ROOT}/test_show/seq02/shot030",
        ),
    ]


# ---------------------------------------------------------------------------
# FilePinManager-specific fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_pin_manager(tmp_path: Path) -> Generator[FilePinManager, None, None]:
    """Create a FilePinManager with a temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    manager = FilePinManager(cache_dir)
    yield manager
    manager.deleteLater()


@pytest.fixture
def sample_file_paths() -> list[Path]:
    """Provide realistic file paths for testing."""
    return [
        Path("/shows/test_show/shots/seq01/seq01_shot010/3de/scene_v001.3de"),
        Path("/shows/test_show/shots/seq01/seq01_shot010/maya/scene_v002.mb"),
        Path("/shows/test_show/shots/seq01/seq01_shot020/nuke/comp_v003.nk"),
    ]


# ---------------------------------------------------------------------------
# ShotPinManager-specific tests
# ---------------------------------------------------------------------------


class TestShotPinOrdering:
    """Tests for ordering behavior: pins add to front, move to front on re-pin."""

    def test_pin_shot_adds_to_front(
        self, shot_pin_manager: ShotPinManager, sample_shots: list[Shot]
    ) -> None:
        """Pinning a shot should add it to the front of the list."""
        shot1, shot2, shot3 = sample_shots

        shot_pin_manager.pin_shot(shot1)
        shot_pin_manager.pin_shot(shot2)
        shot_pin_manager.pin_shot(shot3)

        # Most recently pinned should be at index 0
        assert shot_pin_manager.get_pin_order(shot3) == 0
        assert shot_pin_manager.get_pin_order(shot2) == 1
        assert shot_pin_manager.get_pin_order(shot1) == 2

    def test_pin_shot_moves_existing_to_front(
        self, shot_pin_manager: ShotPinManager, sample_shots: list[Shot]
    ) -> None:
        """Re-pinning an already pinned shot should move it to the front."""
        shot1, shot2, shot3 = sample_shots

        shot_pin_manager.pin_shot(shot1)
        shot_pin_manager.pin_shot(shot2)
        shot_pin_manager.pin_shot(shot3)

        # Re-pin shot1 (currently at index 2)
        shot_pin_manager.pin_shot(shot1)

        # shot1 should now be at front
        assert shot_pin_manager.get_pin_order(shot1) == 0
        assert shot_pin_manager.get_pin_order(shot3) == 1
        assert shot_pin_manager.get_pin_order(shot2) == 2

    def test_get_pin_order_returns_correct_index(
        self, shot_pin_manager: ShotPinManager, sample_shots: list[Shot]
    ) -> None:
        """Pin order should reflect position in list (most-recently-pinned first)."""
        shot1, shot2, shot3 = sample_shots

        shot_pin_manager.pin_shot(shot1)
        shot_pin_manager.pin_shot(shot2)
        shot_pin_manager.pin_shot(shot3)

        assert shot_pin_manager.get_pin_order(shot3) == 0
        assert shot_pin_manager.get_pin_order(shot2) == 1
        assert shot_pin_manager.get_pin_order(shot1) == 2


class TestShotPinEdgeCases:
    """ShotPinManager-specific edge cases."""

    def test_different_shot_objects_same_key(
        self, shot_pin_manager: ShotPinManager
    ) -> None:
        """Different Shot objects with same key should be treated as the same pin."""
        shot1 = Shot("show", "seq", "shot", "/path1")
        shot2 = Shot("show", "seq", "shot", "/path2")  # Different path, same key

        shot_pin_manager.pin_shot(shot1)
        assert shot_pin_manager.is_pinned(shot2)  # Should match on key, not identity

        shot_pin_manager.unpin_shot(shot2)
        assert not shot_pin_manager.is_pinned(shot1)

    def test_shot_cache_file_format(
        self, tmp_path: Path, sample_shots: list[Shot]
    ) -> None:
        """ShotPinManager cache file should be a JSON list of dicts with show/sequence/shot keys."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        shot = sample_shots[0]

        pm = ShotPinManager(cache_dir)
        pm.pin_shot(shot)

        cache_file = cache_dir / f"{PINNED_SHOTS_CACHE_KEY}.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["show"] == shot.show
        assert data[0]["sequence"] == shot.sequence
        assert data[0]["shot"] == shot.shot


# ---------------------------------------------------------------------------
# FilePinManager-specific tests
# ---------------------------------------------------------------------------


class TestFilePinComment:
    """Tests for FilePinManager comment handling: pin_file, get_comment, set_comment."""

    def test_pin_file_with_comment(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Pinning with a comment should store it."""
        file_path = sample_file_paths[0]
        comment = "Approved tracking version"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.is_pinned(file_path)
        assert file_pin_manager.get_comment(file_path) == comment

    def test_pin_file_without_comment(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Pinning without a comment should default to an empty string."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path)

        assert file_pin_manager.get_comment(file_path) == ""

    def test_pin_file_strips_comment_whitespace(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Leading/trailing whitespace in the comment should be stripped on pin."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "  Some comment with whitespace  \n")

        assert file_pin_manager.get_comment(file_path) == "Some comment with whitespace"

    def test_pin_file_emits_signal(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """pin_file should emit pin_changed with the path string."""
        file_path = sample_file_paths[0]

        with qtbot.waitSignal(file_pin_manager.pin_changed, timeout=1000) as blocker:
            file_pin_manager.pin_file(file_path)

        assert blocker.args == [str(file_path)]

    def test_pin_file_accepts_string_path(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """pin_file should accept a plain string path."""
        file_path_str = str(sample_file_paths[0])

        file_pin_manager.pin_file(file_path_str)

        assert file_pin_manager.is_pinned(file_path_str)

    def test_repin_updates_comment(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Re-pinning an already-pinned file should update the comment and keep count at 1."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "First comment")
        file_pin_manager.pin_file(file_path, "Updated comment")

        assert file_pin_manager.get_comment(file_path) == "Updated comment"
        assert file_pin_manager.get_pinned_count() == 1

    def test_get_comment_returns_empty_for_unpinned(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """get_comment on an unpinned file should return empty string."""
        assert file_pin_manager.get_comment(sample_file_paths[0]) == ""

    def test_get_comment_returns_stored_comment(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """get_comment should return the exact comment that was stored."""
        file_path = sample_file_paths[0]
        comment = "This is my comment"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == comment

    def test_set_comment_updates_existing(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """set_comment should overwrite the previous comment on a pinned file."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "Original comment")
        file_pin_manager.set_comment(file_path, "New comment")

        assert file_pin_manager.get_comment(file_path) == "New comment"

    def test_set_comment_raises_for_unpinned(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """set_comment on an unpinned file should raise ValueError."""
        with pytest.raises(ValueError, match="File not pinned"):
            file_pin_manager.set_comment(sample_file_paths[0], "Some comment")

    def test_set_comment_emits_signal(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """set_comment should emit pin_changed with the path string."""
        file_path = sample_file_paths[0]
        file_pin_manager.pin_file(file_path)

        with qtbot.waitSignal(file_pin_manager.pin_changed, timeout=1000) as blocker:
            file_pin_manager.set_comment(file_path, "Updated comment")

        assert blocker.args == [str(file_path)]

    def test_set_comment_strips_whitespace(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """set_comment should strip leading/trailing whitespace."""
        file_path = sample_file_paths[0]
        file_pin_manager.pin_file(file_path)
        file_pin_manager.set_comment(file_path, "  Whitespace comment  \n")

        assert file_pin_manager.get_comment(file_path) == "Whitespace comment"

    def test_clear_pins_emits_signals(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """clear_pins should emit pin_changed once for each removed pin."""
        file1, file2, _ = sample_file_paths
        file_pin_manager.pin_file(file1)
        file_pin_manager.pin_file(file2)

        signals_received: list[str] = []
        file_pin_manager.pin_changed.connect(signals_received.append)

        file_pin_manager.clear_pins()

        assert len(signals_received) == 2
        assert str(file1) in signals_received
        assert str(file2) in signals_received


class TestFilePinPersistence:
    """FilePinManager-specific persistence tests."""

    def test_comments_persist_across_instances(
        self, tmp_path: Path, sample_file_paths: list[Path]
    ) -> None:
        """Comments written by one instance should be readable by a fresh instance."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        file_path = sample_file_paths[0]
        comment = "This is a persistent comment"

        pm1 = FilePinManager(cache_dir)
        pm1.pin_file(file_path, comment)
        pm1.deleteLater()

        pm2 = FilePinManager(cache_dir)
        assert pm2.get_comment(file_path) == comment
        pm2.deleteLater()

    def test_file_cache_file_format(
        self, tmp_path: Path, sample_file_paths: list[Path]
    ) -> None:
        """FilePinManager cache file should be a JSON dict keyed by path with comment and pinned_at fields."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        file_path = sample_file_paths[0]
        comment = "Test comment"

        pm = FilePinManager(cache_dir)
        pm.pin_file(file_path, comment)
        pm.deleteLater()

        cache_file = cache_dir / f"{PINNED_FILES_CACHE_KEY}.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            data = json.load(f)

        assert isinstance(data, dict)
        path_str = str(file_path)
        assert path_str in data
        assert data[path_str]["comment"] == comment
        assert "pinned_at" in data[path_str]


class TestFilePinEdgeCases:
    """FilePinManager-specific edge cases."""

    def test_path_object_and_string_equivalent(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Path objects and plain strings should be interchangeable."""
        path_obj = sample_file_paths[0]
        path_str = str(path_obj)

        file_pin_manager.pin_file(path_obj, "Comment")

        assert file_pin_manager.is_pinned(path_str)
        assert file_pin_manager.get_comment(path_str) == "Comment"

        file_pin_manager.unpin_file(path_str)
        assert not file_pin_manager.is_pinned(path_obj)

    def test_empty_comment_is_valid(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """An empty string comment should be stored and returned correctly."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "")

        assert file_pin_manager.is_pinned(file_path)
        assert file_pin_manager.get_comment(file_path) == ""

    def test_multiline_comment(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Multiline comments should round-trip without modification."""
        file_path = sample_file_paths[0]
        comment = "Line 1\nLine 2\nLine 3"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == comment

    def test_unicode_comment(
        self,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Unicode characters in comments should round-trip correctly."""
        file_path = sample_file_paths[0]
        comment = "Contains unicode: \u2764\ufe0f \u2728 \u2705"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == comment

    def test_special_characters_in_path(
        self, file_pin_manager: FilePinManager
    ) -> None:
        """Paths containing spaces and special characters should work correctly."""
        file_path = Path("/shows/test show/shots/seq 01/file with spaces.3de")

        file_pin_manager.pin_file(file_path, "Comment")

        assert file_pin_manager.is_pinned(file_path)
        assert file_pin_manager.get_comment(file_path) == "Comment"
