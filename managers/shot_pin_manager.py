"""Pin manager for tracking and persisting pinned shots.

This module provides ShotPinManager which handles:
- Tracking which shots are pinned
- Persistence to cache (survives application restarts)
- Pin ordering (most recently pinned first)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from logging_mixin import LoggingMixin
from managers._keyed_list_store import KeyedListStore
from managers._shot_key import key_from_workspace_path, shot_key


if TYPE_CHECKING:
    from type_definitions import Shot


# Cache key for pinned shots
PINNED_SHOTS_CACHE_KEY = "pinned_shots"


class ShotPinManager(LoggingMixin):
    """Manages pinned shot tracking and persistence.

    Tracks shots by composite key (show, sequence, shot) to handle
    Shot objects which may be recreated between sessions.

    Pin order is most-recently-pinned-first.
    """

    _store: KeyedListStore

    def __init__(self, cache_dir: Path) -> None:
        """Initialize the pin manager.

        Args:
            cache_dir: Directory for cache persistence

        """
        super().__init__()
        self._store = KeyedListStore(cache_dir, PINNED_SHOTS_CACHE_KEY, self.logger)

    def pin_shot(self, shot: Shot) -> None:
        """Pin a shot (adds to front of list).

        If shot is already pinned, moves it to the front.

        Args:
            shot: Shot to pin

        """
        key = shot_key(shot)

        if self._store.contains(key):
            self.logger.debug(f"Moving pinned shot to front: {shot.full_name}")
        else:
            self.logger.info(f"Pinning shot: {shot.full_name}")

        self._store.add_front(key)
        self._store.save()

    def unpin_shot(self, shot: Shot) -> None:
        """Unpin a shot.

        Args:
            shot: Shot to unpin

        """
        key = shot_key(shot)

        if self._store.remove(key):
            self.logger.info(f"Unpinned shot: {shot.full_name}")
            self._store.save()

    def is_pinned(self, shot: Shot) -> bool:
        """Check if a shot is pinned.

        Args:
            shot: Shot to check

        Returns:
            True if shot is pinned

        """
        return self._store.contains(shot_key(shot))

    def is_pinned_by_path(self, workspace_path: str) -> bool:
        """Check if a shot is pinned by workspace path.

        Extracts show/sequence/shot from path format: .../shots/{seq}/{seq}_{shot}

        Args:
            workspace_path: Full workspace path

        Returns:
            True if shot is pinned

        """
        key = key_from_workspace_path(workspace_path)
        if key is None:
            self.logger.warning(f"Could not parse workspace path: {workspace_path}")
        return self._store.contains(key) if key else False

    def pin_by_path(self, workspace_path: str) -> None:
        """Pin a shot by workspace path.

        Args:
            workspace_path: Full workspace path

        """
        key = key_from_workspace_path(workspace_path)
        if key is None:
            self.logger.warning(f"Could not parse workspace path: {workspace_path}")
        if not key:
            return

        if self._store.contains(key):
            self.logger.debug(f"Moving pinned shot to front: {workspace_path}")
        else:
            self.logger.info(f"Pinning shot: {workspace_path}")

        self._store.add_front(key)
        self._store.save()

    def unpin_by_path(self, workspace_path: str) -> None:
        """Unpin a shot by workspace path.

        Args:
            workspace_path: Full workspace path

        """
        key = key_from_workspace_path(workspace_path)
        if key is None:
            self.logger.warning(f"Could not parse workspace path: {workspace_path}")
        if not key:
            return

        if self._store.remove(key):
            self.logger.info(f"Unpinned shot: {workspace_path}")
            self._store.save()

    def get_pin_order(self, shot: Shot) -> int:
        """Get pin order for a shot.

        Args:
            shot: Shot to check

        Returns:
            Pin order (0 = most recent), or -1 if not pinned

        """
        return self._store.index_of(shot_key(shot))

    def get_pinned_count(self) -> int:
        """Get the number of pinned shots.

        Returns:
            Number of pinned shots

        """
        return self._store.count()

    def clear_pins(self) -> None:
        """Clear all pinned shots."""
        self._store.clear()
        self._store.save()
        self.logger.info("Cleared all pinned shots")
