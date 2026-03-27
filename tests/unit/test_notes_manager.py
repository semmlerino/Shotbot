"""Comprehensive tests for NotesManager.

This test suite validates notes_manager.py following
UNIFIED_TESTING_GUIDE.md principles:
- Test behavior, not implementation
- Use real components with temporary storage
- Persistence validation
"""

from __future__ import annotations

# Standard library imports
import json
from pathlib import Path

# Standard library imports
import pytest

# Local application imports
from config import Config
from managers.notes_manager import SHOT_NOTES_CACHE_KEY, NotesManager
from type_definitions import Shot


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# Test fixtures following UNIFIED_TESTING_GUIDE patterns


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    path = tmp_path / "test_cache"
    path.mkdir()
    return path


@pytest.fixture
def notes_manager(cache_dir: Path) -> NotesManager:
    """Create NotesManager with test cache directory."""
    return NotesManager(cache_dir)


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


# ============= Core Functionality Tests =============


class TestSetNote:
    """Tests for set_note() method."""

    def test_set_note_stores_note(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Setting a note should store it."""
        shot = sample_shots[0]

        notes_manager.set_note(shot, "This is a test note")

        assert notes_manager.get_note(shot) == "This is a test note"

    def test_set_note_updates_existing(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Setting a note should update existing note."""
        shot = sample_shots[0]

        notes_manager.set_note(shot, "First note")
        notes_manager.set_note(shot, "Updated note")

        assert notes_manager.get_note(shot) == "Updated note"

    def test_set_empty_note_removes(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Setting empty note should remove it (sparse storage)."""
        shot = sample_shots[0]

        notes_manager.set_note(shot, "Some note")
        assert notes_manager.has_note(shot)

        notes_manager.set_note(shot, "")
        assert not notes_manager.has_note(shot)

    def test_set_whitespace_note_removes(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Setting whitespace-only note should remove it."""
        shot = sample_shots[0]

        notes_manager.set_note(shot, "Some note")
        notes_manager.set_note(shot, "   \n\t  ")
        assert not notes_manager.has_note(shot)


class TestGetNote:
    """Tests for get_note() method."""

    def test_get_note_returns_empty_for_no_note(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """get_note should return empty string for shots without notes."""
        shot = sample_shots[0]
        assert notes_manager.get_note(shot) == ""

    def test_get_note_returns_stored_note(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """get_note should return the stored note."""
        shot = sample_shots[0]
        notes_manager.set_note(shot, "My test note")
        assert notes_manager.get_note(shot) == "My test note"


class TestHasNote:
    """Tests for has_note() method."""

    def test_has_note_returns_false_for_no_note(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """has_note should return False for shots without notes."""
        shot = sample_shots[0]
        assert not notes_manager.has_note(shot)

    def test_has_note_returns_true_for_note(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """has_note should return True for shots with notes."""
        shot = sample_shots[0]
        notes_manager.set_note(shot, "Some note")
        assert notes_manager.has_note(shot)


class TestGetNotesCount:
    """Tests for get_notes_count() method."""

    def test_get_notes_count_starts_at_zero(self, notes_manager: NotesManager) -> None:
        """Initial count should be zero."""
        assert notes_manager.get_notes_count() == 0

    def test_get_notes_count_increments(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Count should increment when adding notes."""
        shot1, shot2, _ = sample_shots

        notes_manager.set_note(shot1, "Note 1")
        assert notes_manager.get_notes_count() == 1

        notes_manager.set_note(shot2, "Note 2")
        assert notes_manager.get_notes_count() == 2

    def test_get_notes_count_decrements_on_remove(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Count should decrement when removing notes."""
        shot1, shot2, _ = sample_shots

        notes_manager.set_note(shot1, "Note 1")
        notes_manager.set_note(shot2, "Note 2")
        assert notes_manager.get_notes_count() == 2

        notes_manager.set_note(shot1, "")  # Remove
        assert notes_manager.get_notes_count() == 1


class TestClearNotes:
    """Tests for clear_notes() method."""

    def test_clear_notes_removes_all(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """clear_notes should remove all notes."""
        for i, shot in enumerate(sample_shots):
            notes_manager.set_note(shot, f"Note {i}")

        assert notes_manager.get_notes_count() == 3

        notes_manager.clear_notes()

        assert notes_manager.get_notes_count() == 0
        for shot in sample_shots:
            assert not notes_manager.has_note(shot)


# ============= Persistence Tests =============


class TestPersistence:
    """Tests for cache persistence."""

    def test_notes_persist_across_instances(
        self, cache_dir: Path, sample_shots: list[Shot]
    ) -> None:
        """Notes should persist when creating a new NotesManager instance."""
        shot1, shot2, _ = sample_shots

        # Set notes with first instance
        nm1 = NotesManager(cache_dir)
        nm1.set_note(shot1, "Note 1")
        nm1.set_note(shot2, "Note 2")

        # Force flush to disk
        nm1.flush()

        # Create new instance
        nm2 = NotesManager(cache_dir)

        # Notes should be loaded
        assert nm2.has_note(shot1)
        assert nm2.has_note(shot2)
        assert nm2.get_note(shot1) == "Note 1"
        assert nm2.get_note(shot2) == "Note 2"
        assert nm2.get_notes_count() == 2

    def test_cache_file_format(self, cache_dir: Path, sample_shots: list[Shot]) -> None:
        """Cache file should be valid JSON with expected format."""
        shot = sample_shots[0]

        nm = NotesManager(cache_dir)
        nm.set_note(shot, "Test note content")
        nm.flush()

        # Read the cache file
        cache_file = cache_dir / f"{SHOT_NOTES_CACHE_KEY}.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            data = json.load(f)

        # Should be a dict with "show|sequence|shot" key format
        assert isinstance(data, dict)
        expected_key = f"{shot.show}|{shot.sequence}|{shot.shot}"
        assert expected_key in data
        assert data[expected_key] == "Test note content"


class TestCacheRecovery:
    """Tests for handling corrupted or missing cache."""

    def test_handles_missing_cache_file(self, cache_dir: Path) -> None:
        """Should handle missing cache file gracefully."""
        nm = NotesManager(cache_dir)
        assert nm.get_notes_count() == 0

    def test_handles_corrupted_json(self, cache_dir: Path) -> None:
        """Should handle corrupted JSON gracefully."""
        # Write corrupted JSON
        cache_file = cache_dir / f"{SHOT_NOTES_CACHE_KEY}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json {{{")

        # Should not raise, should start with empty dict
        nm = NotesManager(cache_dir)
        assert nm.get_notes_count() == 0

    def test_handles_invalid_cache_format(self, cache_dir: Path) -> None:
        """Should handle invalid cache format gracefully."""
        # Write valid JSON but wrong format (list instead of dict)
        cache_file = cache_dir / f"{SHOT_NOTES_CACHE_KEY}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("[1, 2, 3]")

        # Should not raise, should start with empty dict
        nm = NotesManager(cache_dir)
        assert nm.get_notes_count() == 0


# ============= Edge Case Tests =============


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_different_shot_objects_same_key(self, notes_manager: NotesManager) -> None:
        """Different Shot objects with same key should share notes."""
        shot1 = Shot("show", "seq", "shot", "/path1")
        shot2 = Shot("show", "seq", "shot", "/path2")  # Different path, same key

        notes_manager.set_note(shot1, "Test note")
        assert notes_manager.has_note(shot2)  # Should match on key
        assert notes_manager.get_note(shot2) == "Test note"

    def test_multiline_notes(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Should handle multiline notes correctly."""
        shot = sample_shots[0]
        multiline_note = "Line 1\nLine 2\nLine 3"

        notes_manager.set_note(shot, multiline_note)
        notes_manager.flush()

        # Reload and verify
        from managers.notes_manager import NotesManager as NotesManagerReload

        nm2 = NotesManagerReload(notes_manager._cache_dir)
        assert nm2.get_note(shot) == multiline_note

    def test_unicode_notes(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Should handle unicode characters in notes."""
        shot = sample_shots[0]
        unicode_note = "Test with emoji and symbols"

        notes_manager.set_note(shot, unicode_note)
        notes_manager.flush()

        # Reload and verify
        from managers.notes_manager import NotesManager as NotesManagerReload

        nm2 = NotesManagerReload(notes_manager._cache_dir)
        assert nm2.get_note(shot) == unicode_note


# ============= State Change Tests =============


class TestStateChanges:
    """Tests for state changes after mutation operations."""

    def test_set_note_stores_note_state(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """set_note should update manager state immediately."""
        shot = sample_shots[0]
        notes_manager.set_note(shot, "New note")
        assert notes_manager.get_note(shot) == "New note"
        assert notes_manager.has_note(shot)

    def test_clear_notes_empties_state(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """clear_notes should remove all notes from manager state."""
        shot = sample_shots[0]
        notes_manager.set_note(shot, "Note")
        assert notes_manager.get_notes_count() == 1

        notes_manager.clear_notes()

        assert notes_manager.get_notes_count() == 0
        assert not notes_manager.has_note(shot)

    def test_same_note_does_not_change_state(
        self, notes_manager: NotesManager, sample_shots: list[Shot]
    ) -> None:
        """Setting the exact same note value should leave state unchanged."""
        shot = sample_shots[0]
        notes_manager.set_note(shot, "Test note")
        assert notes_manager.get_notes_count() == 1

        notes_manager.set_note(shot, "Test note")  # Same note

        # State should be identical: still one note, same text
        assert notes_manager.get_notes_count() == 1
        assert notes_manager.get_note(shot) == "Test note"
