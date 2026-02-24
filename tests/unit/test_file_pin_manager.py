"""Comprehensive tests for FilePinManager.

This test suite validates file_pin_manager.py following
UNIFIED_TESTING_GUIDE.md principles:
- Test behavior, not implementation
- Use real components with temporary storage
- Persistence validation
"""

from __future__ import annotations

# Standard library imports
import json
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
import pytest


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]


if TYPE_CHECKING:
    from collections.abc import Generator

    from pytestqt.qtbot import QtBot

# Local application imports
from cache_manager import CacheManager
from file_pin_manager import PINNED_FILES_CACHE_KEY, FilePinManager


# Test fixtures following UNIFIED_TESTING_GUIDE patterns


@pytest.fixture
def cache_manager(tmp_path: Path) -> CacheManager:
    """Create CacheManager with temporary directory."""
    cache_dir = tmp_path / "test_cache"
    return CacheManager(cache_dir=cache_dir)


@pytest.fixture
def file_pin_manager(cache_manager: CacheManager) -> Generator[FilePinManager, None, None]:
    """Create FilePinManager with test cache manager."""
    manager = FilePinManager(cache_manager)
    yield manager
    # Cleanup: ensure QObject is deleted
    manager.deleteLater()


@pytest.fixture
def sample_file_paths() -> list[Path]:
    """Provide realistic file paths for testing."""
    return [
        Path("/shows/test_show/shots/seq01/seq01_shot010/3de/scene_v001.3de"),
        Path("/shows/test_show/shots/seq01/seq01_shot010/maya/scene_v002.mb"),
        Path("/shows/test_show/shots/seq01/seq01_shot020/nuke/comp_v003.nk"),
    ]


# ============= Core Functionality Tests =============


class TestPinFile:
    """Tests for pin_file() method."""

    def test_pin_file_with_comment(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Pinning with comment should store the comment."""
        file_path = sample_file_paths[0]
        comment = "Approved tracking version"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.is_pinned(file_path)
        assert file_pin_manager.get_comment(file_path) == comment

    def test_pin_file_without_comment(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Pinning without comment should have empty comment."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path)

        assert file_pin_manager.get_comment(file_path) == ""

    def test_pin_file_strips_comment_whitespace(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Comment whitespace should be stripped."""
        file_path = sample_file_paths[0]
        comment = "  Some comment with whitespace  \n"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == "Some comment with whitespace"

    def test_pin_file_emits_signal(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Pinning should emit pin_changed signal."""
        file_path = sample_file_paths[0]

        with qtbot.waitSignal(file_pin_manager.pin_changed, timeout=1000) as blocker:
            file_pin_manager.pin_file(file_path)

        assert blocker.args == [str(file_path)]

    def test_pin_file_accepts_string_path(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """pin_file should accept string paths."""
        file_path = str(sample_file_paths[0])

        file_pin_manager.pin_file(file_path)

        assert file_pin_manager.is_pinned(file_path)

    def test_repin_updates_comment(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Re-pinning should update the comment."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "First comment")
        file_pin_manager.pin_file(file_path, "Updated comment")

        assert file_pin_manager.get_comment(file_path) == "Updated comment"
        assert file_pin_manager.get_pinned_count() == 1


class TestUnpinFile:
    """Tests for unpin_file() method."""

    def test_unpin_file_emits_signal(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Unpinning should emit pin_changed signal."""
        file_path = sample_file_paths[0]
        file_pin_manager.pin_file(file_path)

        with qtbot.waitSignal(file_pin_manager.pin_changed, timeout=1000) as blocker:
            file_pin_manager.unpin_file(file_path)

        assert blocker.args == [str(file_path)]


class TestIsPinned:
    """Tests for is_pinned() method."""

    def test_is_pinned_accepts_string_path(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """is_pinned should accept string paths."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path)
        assert file_pin_manager.is_pinned(str(file_path))


class TestGetComment:
    """Tests for get_comment() method."""

    def test_get_comment_returns_empty_for_unpinned(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Unpinned files should return empty string."""
        file_path = sample_file_paths[0]
        assert file_pin_manager.get_comment(file_path) == ""

    def test_get_comment_returns_stored_comment(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Should return the stored comment."""
        file_path = sample_file_paths[0]
        comment = "This is my comment"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == comment


class TestSetComment:
    """Tests for set_comment() method."""

    def test_set_comment_updates_existing(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Should update comment on already-pinned file."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "Original comment")
        file_pin_manager.set_comment(file_path, "New comment")

        assert file_pin_manager.get_comment(file_path) == "New comment"

    def test_set_comment_raises_for_unpinned(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Should raise ValueError for unpinned files."""
        file_path = sample_file_paths[0]

        with pytest.raises(ValueError, match="File not pinned"):
            file_pin_manager.set_comment(file_path, "Some comment")

    def test_set_comment_emits_signal(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Setting comment should emit pin_changed signal."""
        file_path = sample_file_paths[0]
        file_pin_manager.pin_file(file_path)

        with qtbot.waitSignal(file_pin_manager.pin_changed, timeout=1000) as blocker:
            file_pin_manager.set_comment(file_path, "Updated comment")

        assert blocker.args == [str(file_path)]

    def test_set_comment_strips_whitespace(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Comment whitespace should be stripped."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path)
        file_pin_manager.set_comment(file_path, "  Whitespace comment  \n")

        assert file_pin_manager.get_comment(file_path) == "Whitespace comment"


class TestClearPins:
    """Tests for clear_pins() method."""

    def test_clear_pins_emits_signals(
        self,
        qtbot: QtBot,
        file_pin_manager: FilePinManager,
        sample_file_paths: list[Path],
    ) -> None:
        """Clear should emit signal for each removed pin."""
        file1, file2, _ = sample_file_paths
        file_pin_manager.pin_file(file1)
        file_pin_manager.pin_file(file2)

        signals_received: list[str] = []
        file_pin_manager.pin_changed.connect(signals_received.append)

        file_pin_manager.clear_pins()

        assert len(signals_received) == 2
        assert str(file1) in signals_received
        assert str(file2) in signals_received


# ============= Persistence Tests =============


class TestPersistence:
    """Tests for cache persistence."""

    def test_pins_persist_across_instances(
        self, cache_manager: CacheManager, sample_file_paths: list[Path]
    ) -> None:
        """Pinned files should persist when creating a new FilePinManager instance."""
        file1, file2, _ = sample_file_paths

        # Pin files with first instance
        pm1 = FilePinManager(cache_manager)
        pm1.pin_file(file1, "Comment 1")
        pm1.pin_file(file2, "Comment 2")
        pm1.deleteLater()

        # Create new instance
        pm2 = FilePinManager(cache_manager)

        # Pins should be loaded
        assert pm2.is_pinned(file1)
        assert pm2.is_pinned(file2)
        assert pm2.get_pinned_count() == 2
        pm2.deleteLater()

    def test_comments_persist(
        self, cache_manager: CacheManager, sample_file_paths: list[Path]
    ) -> None:
        """Comments should persist across instances."""
        file_path = sample_file_paths[0]
        comment = "This is a persistent comment"

        pm1 = FilePinManager(cache_manager)
        pm1.pin_file(file_path, comment)
        pm1.deleteLater()

        pm2 = FilePinManager(cache_manager)
        assert pm2.get_comment(file_path) == comment
        pm2.deleteLater()

    def test_cache_file_format(
        self, cache_manager: CacheManager, sample_file_paths: list[Path]
    ) -> None:
        """Cache file should be valid JSON with expected format."""
        file_path = sample_file_paths[0]
        comment = "Test comment"

        pm = FilePinManager(cache_manager)
        pm.pin_file(file_path, comment)
        pm.deleteLater()

        # Read the cache file
        cache_file = cache_manager.cache_dir / f"{PINNED_FILES_CACHE_KEY}.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            data = json.load(f)

        # Should be a dict with path as key
        assert isinstance(data, dict)
        path_str = str(file_path)
        assert path_str in data
        assert data[path_str]["comment"] == comment
        assert "pinned_at" in data[path_str]


class TestCacheRecovery:
    """Tests for handling corrupted or missing cache."""

    def test_handles_partial_cache_data(
        self, cache_manager: CacheManager
    ) -> None:
        """Should skip entries with invalid structure."""
        # Write valid JSON with some invalid entries
        cache_file = cache_manager.cache_dir / f"{PINNED_FILES_CACHE_KEY}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "/path/to/valid.3de": {"comment": "valid", "pinned_at": "2025-01-01"},
            "/path/to/invalid.3de": "not a dict",  # Invalid - should be skipped
            "/path/to/also_valid.mb": {"comment": "also valid", "pinned_at": "2025-01-01"},
        }
        cache_file.write_text(json.dumps(data))

        pm = FilePinManager(cache_manager)
        assert pm.get_pinned_count() == 2  # Only valid entries loaded
        assert pm.is_pinned("/path/to/valid.3de")
        assert not pm.is_pinned("/path/to/invalid.3de")
        assert pm.is_pinned("/path/to/also_valid.mb")
        pm.deleteLater()


# ============= Edge Case Tests =============


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_path_object_and_string_equivalent(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Path objects and strings should be treated equivalently."""
        path_obj = sample_file_paths[0]
        path_str = str(path_obj)

        # Pin with Path object
        file_pin_manager.pin_file(path_obj, "Comment")

        # Check with string
        assert file_pin_manager.is_pinned(path_str)
        assert file_pin_manager.get_comment(path_str) == "Comment"

        # Unpin with string
        file_pin_manager.unpin_file(path_str)
        assert not file_pin_manager.is_pinned(path_obj)

    def test_empty_comment_is_valid(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Empty comment should be stored correctly."""
        file_path = sample_file_paths[0]

        file_pin_manager.pin_file(file_path, "")

        assert file_pin_manager.is_pinned(file_path)
        assert file_pin_manager.get_comment(file_path) == ""

    def test_multiline_comment(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Multiline comments should be stored correctly."""
        file_path = sample_file_paths[0]
        comment = "Line 1\nLine 2\nLine 3"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == comment

    def test_unicode_comment(
        self, file_pin_manager: FilePinManager, sample_file_paths: list[Path]
    ) -> None:
        """Unicode comments should be stored correctly."""
        file_path = sample_file_paths[0]
        comment = "Contains unicode: \u2764\ufe0f \u2728 \u2705"

        file_pin_manager.pin_file(file_path, comment)

        assert file_pin_manager.get_comment(file_path) == comment

    def test_special_characters_in_path(
        self, file_pin_manager: FilePinManager
    ) -> None:
        """Paths with special characters should work."""
        file_path = Path("/shows/test show/shots/seq 01/file with spaces.3de")

        file_pin_manager.pin_file(file_path, "Comment")

        assert file_pin_manager.is_pinned(file_path)
        assert file_pin_manager.get_comment(file_path) == "Comment"
