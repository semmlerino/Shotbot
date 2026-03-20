"""Notes manager for tracking and persisting per-shot notes.

This module provides NotesManager which handles:
- Tracking notes for shots
- Persistence to cache (survives application restarts)
- Debounced saving to avoid disk thrashing
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, QTimer

from cache import atomic_json_write
from logging_mixin import LoggingMixin
from managers._shot_key import key_from_workspace_path, shot_key


if TYPE_CHECKING:
    from type_definitions import Shot


# Cache key for shot notes
SHOT_NOTES_CACHE_KEY = "shot_notes"


class NotesManager(LoggingMixin, QObject):
    """Manages per-shot notes tracking and persistence.

    Tracks notes by composite key (show, sequence, shot) to handle
    Shot objects which may be recreated between sessions.

    Uses debounced saving (2 second delay after last edit) to avoid
    disk thrashing during rapid edits.
    """

    # Debounce delay in milliseconds
    SAVE_DEBOUNCE_MS: int = 2000

    _cache_dir: Path
    _notes_by_key: dict[tuple[str, str, str], str]
    _save_timer: QTimer | None
    _save_pending: bool

    def __init__(
        self,
        cache_dir: Path,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the notes manager.

        Args:
            cache_dir: Directory for cache persistence
            parent: Optional parent QObject

        """
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._notes_by_key = {}
        self._save_timer = None
        self._save_pending = False
        self._load_notes()

    def _load_notes(self) -> None:
        """Load notes from cache."""
        cache_file = self._cache_dir / f"{SHOT_NOTES_CACHE_KEY}.json"

        if not cache_file.exists():
            self._notes_by_key = {}
            return

        try:
            with cache_file.open() as f:
                raw_data: object = json.load(f)  # pyright: ignore[reportAny] - json.load returns Any

            if not isinstance(raw_data, dict):
                self.logger.warning(f"Invalid notes cache format: {type(raw_data)}")
                self._notes_by_key = {}
                return

            # Cast to expected type for iteration
            data = cast("dict[str, object]", raw_data)

            # Parse keys from "show|sequence|shot" format
            self._notes_by_key = {}
            for key_str, note_text in data.items():
                if not isinstance(note_text, str):
                    continue
                parts = key_str.split("|")
                if len(parts) == 3:
                    key = (parts[0], parts[1], parts[2])
                    if note_text.strip():  # Only store non-empty notes
                        self._notes_by_key[key] = note_text

            self.logger.info(f"Loaded {len(self._notes_by_key)} shot notes from cache")

        except (json.JSONDecodeError, OSError):
            self.logger.warning("Failed to load shot notes", exc_info=True)
            self._notes_by_key = {}

    def _schedule_save(self) -> None:
        """Schedule a debounced save."""
        self._save_pending = True

        if self._save_timer is None:
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            _ = self._save_timer.timeout.connect(self._do_save)

        # Restart timer on each edit
        self._save_timer.start(self.SAVE_DEBOUNCE_MS)

    def _do_save(self) -> None:
        """Actually write notes to disk."""
        if not self._save_pending:
            return

        self._save_pending = False
        cache_file = self._cache_dir / f"{SHOT_NOTES_CACHE_KEY}.json"

        # Convert keys to "show|sequence|shot" format
        data = {
            f"{show}|{seq}|{shot}": note
            for (show, seq, shot), note in self._notes_by_key.items()
        }

        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(cache_file, data, indent=2, fsync=False)
            self.logger.debug(f"Saved {len(self._notes_by_key)} shot notes to cache")
        except OSError:
            self.logger.exception("Failed to save shot notes")

    def flush(self) -> None:
        """Force immediate save (call on app shutdown).

        Cancels any pending debounced save and writes immediately.
        """
        if self._save_timer is not None:
            self._save_timer.stop()
        if self._save_pending:
            self._do_save()

    def get_note(self, shot: Shot) -> str:
        """Get note for a shot.

        Args:
            shot: Shot to get note for

        Returns:
            Note text, or empty string if no note

        """
        return self._notes_by_key.get(shot_key(shot), "")

    def set_note(self, shot: Shot, note: str) -> None:
        """Set note for a shot.

        Empty notes are removed from storage (sparse storage).
        Saves are debounced to avoid disk thrashing.

        Args:
            shot: Shot to set note for
            note: Note text (empty string removes note)

        """
        key = shot_key(shot)
        old_note = self._notes_by_key.get(key, "")

        if note.strip():
            self._notes_by_key[key] = note
        else:
            _ = self._notes_by_key.pop(key, None)  # Remove empty notes

        # Only save if changed
        if note != old_note:
            self._schedule_save()

    def has_note(self, shot: Shot) -> bool:
        """Check if a shot has a non-empty note.

        This is an O(1) operation for efficient use during paint.

        Args:
            shot: Shot to check

        Returns:
            True if shot has a note

        """
        key = shot_key(shot)
        note = self._notes_by_key.get(key, "")
        return bool(note.strip())

    def has_note_by_path(self, workspace_path: str) -> bool:
        """Check if a shot has a note by workspace path.

        Args:
            workspace_path: Full workspace path

        Returns:
            True if shot has a note

        """
        key = self._key_from_path(workspace_path)
        if not key:
            return False
        note = self._notes_by_key.get(key, "")
        return bool(note.strip())

    def get_note_by_path(self, workspace_path: str) -> str:
        """Get note for a shot by workspace path.

        Args:
            workspace_path: Full workspace path

        Returns:
            Note text, or empty string if no note

        """
        key = self._key_from_path(workspace_path)
        if not key:
            return ""
        return self._notes_by_key.get(key, "")

    def set_note_by_path(self, workspace_path: str, note: str) -> None:
        """Set note for a shot by workspace path.

        Args:
            workspace_path: Full workspace path
            note: Note text (empty string removes note)

        """
        key = self._key_from_path(workspace_path)
        if not key:
            return

        old_note = self._notes_by_key.get(key, "")

        if note.strip():
            self._notes_by_key[key] = note
        else:
            _ = self._notes_by_key.pop(key, None)

        if note != old_note:
            self._schedule_save()

    def _key_from_path(self, workspace_path: str) -> tuple[str, str, str] | None:
        """Extract (show, sequence, shot) key from workspace path.

        Path format: /shows/{show}/shots/{seq}/{seq}_{shot}

        Args:
            workspace_path: Full workspace path

        Returns:
            Tuple key or None if path can't be parsed

        """
        key = key_from_workspace_path(workspace_path)
        if key is None:
            _ = self.logger.warning(f"Could not parse workspace path: {workspace_path}")
        return key

    def get_notes_count(self) -> int:
        """Get the number of shots with notes.

        Returns:
            Number of shots with notes

        """
        return len(self._notes_by_key)

    def clear_notes(self) -> None:
        """Clear all notes."""
        self._notes_by_key.clear()
        self._schedule_save()
        _ = self.logger.info("Cleared all shot notes")
