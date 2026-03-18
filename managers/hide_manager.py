"""Hide manager for tracking and persisting hidden shots.

This module provides HideManager which handles:
- Tracking which shots are hidden
- Persistence to cache (survives application restarts)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from logging_mixin import LoggingMixin
from managers._keyed_list_store import KeyedListStore
from managers._shot_key import shot_key


if TYPE_CHECKING:
    from type_definitions import Shot


# Cache key for hidden shots
HIDDEN_SHOTS_CACHE_KEY = "hidden_shots"


class HideManager(LoggingMixin):
    """Manages hidden shot tracking and persistence.

    Tracks shots by composite key (show, sequence, shot) to handle
    Shot objects which may be recreated between sessions.
    """

    _store: KeyedListStore

    def __init__(self, cache_dir: Path) -> None:
        """Initialize the hide manager.

        Args:
            cache_dir: Directory for cache persistence

        """
        super().__init__()
        self._store = KeyedListStore(cache_dir, HIDDEN_SHOTS_CACHE_KEY, self.logger)

    def hide_shot(self, shot: Shot) -> None:
        """Hide a shot.

        If shot is already hidden, does nothing.

        Args:
            shot: Shot to hide

        """
        key = shot_key(shot)

        if not self._store.contains(key):
            self.logger.info(f"Hiding shot: {shot.full_name}")
            self._store.add(key)
            self._store.save()

    def unhide_shot(self, shot: Shot) -> None:
        """Unhide a shot.

        Args:
            shot: Shot to unhide

        """
        key = shot_key(shot)

        if self._store.remove(key):
            self.logger.info(f"Unhid shot: {shot.full_name}")
            self._store.save()

    def is_hidden(self, shot: Shot) -> bool:
        """Check if a shot is hidden.

        Args:
            shot: Shot to check

        Returns:
            True if shot is hidden

        """
        return self._store.contains(shot_key(shot))

    def get_hidden_count(self) -> int:
        """Get the number of hidden shots.

        Returns:
            Number of hidden shots

        """
        return self._store.count()

    def clear_hidden(self) -> None:
        """Clear all hidden shots."""
        self._store.clear()
        self._store.save()
        self.logger.info("Cleared all hidden shots")
