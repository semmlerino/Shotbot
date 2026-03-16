"""Hide manager for tracking and persisting hidden shots.

This module provides HideManager which handles:
- Tracking which shots are hidden
- Persistence to cache (survives application restarts)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from type_definitions import Shot


# Cache key for hidden shots
HIDDEN_SHOTS_CACHE_KEY = "hidden_shots"


class HideManager(LoggingMixin):
    """Manages hidden shot tracking and persistence.

    Tracks shots by composite key (show, sequence, shot) to handle
    Shot objects which may be recreated between sessions.
    """

    _cache_dir: Path
    _hidden_keys: list[tuple[str, str, str]]

    def __init__(self, cache_dir: Path) -> None:
        """Initialize the hide manager.

        Args:
            cache_dir: Directory for cache persistence

        """
        super().__init__()
        self._cache_dir = cache_dir
        self._hidden_keys = []  # (show, seq, shot)
        self._load_hidden()

    def _load_hidden(self) -> None:
        """Load hidden shots from cache."""
        cache_file = self._cache_dir / f"{HIDDEN_SHOTS_CACHE_KEY}.json"

        if not cache_file.exists():
            self._hidden_keys = []
            return

        try:
            with cache_file.open() as f:
                raw_data: Any = json.load(f)  # pyright: ignore[reportAny]

            if not isinstance(raw_data, list):
                self.logger.warning(f"Invalid hidden shots cache format: {type(raw_data)}")  # pyright: ignore[reportAny]
                self._hidden_keys = []
                return

            data = cast("list[dict[str, str] | list[str]]", raw_data)

            self._hidden_keys = []
            for item in data:
                if isinstance(item, dict):
                    try:
                        show_val = item.get("show")
                        seq_val = item.get("sequence")
                        shot_val = item.get("shot")
                        if isinstance(show_val, str) and isinstance(seq_val, str) and isinstance(shot_val, str):
                            self._hidden_keys.append((show_val, seq_val, shot_val))
                    except (KeyError, TypeError):
                        self.logger.warning("Invalid hidden shot entry", exc_info=True)
                elif isinstance(item, list) and len(item) == 3:  # pyright: ignore[reportUnnecessaryIsInstance]
                    v0, v1, v2 = item[0], item[1], item[2]
                    if isinstance(v0, str) and isinstance(v1, str) and isinstance(v2, str):  # pyright: ignore[reportUnnecessaryIsInstance]
                        self._hidden_keys.append((v0, v1, v2))

            self.logger.info(f"Loaded {len(self._hidden_keys)} hidden shots from cache")

        except (json.JSONDecodeError, OSError):
            self.logger.warning("Failed to load hidden shots", exc_info=True)
            self._hidden_keys = []

    def _save_hidden(self) -> None:
        """Save hidden shots to cache."""
        cache_file = self._cache_dir / f"{HIDDEN_SHOTS_CACHE_KEY}.json"

        hidden_dicts = [
            {"show": show, "sequence": seq, "shot": shot}
            for show, seq, shot in self._hidden_keys
        ]

        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=cache_file.parent,
                suffix=".tmp",
                delete=False,
            ) as f:
                json.dump(hidden_dicts, f, indent=2)
                temp_path = f.name

            _ = Path(temp_path).replace(cache_file)
            self.logger.debug(f"Saved {len(self._hidden_keys)} hidden shots to cache")
        except OSError:
            self.logger.exception("Failed to save hidden shots")

    def _get_key(self, shot: Shot) -> tuple[str, str, str]:
        """Get composite key for shot.

        Args:
            shot: Shot object

        Returns:
            Tuple of (show, sequence, shot) for uniqueness

        """
        return (shot.show, shot.sequence, shot.shot)

    def hide_shot(self, shot: Shot) -> None:
        """Hide a shot.

        If shot is already hidden, does nothing.

        Args:
            shot: Shot to hide

        """
        key = self._get_key(shot)

        if key not in self._hidden_keys:
            self.logger.info(f"Hiding shot: {shot.full_name}")
            self._hidden_keys.append(key)
            self._save_hidden()

    def unhide_shot(self, shot: Shot) -> None:
        """Unhide a shot.

        Args:
            shot: Shot to unhide

        """
        key = self._get_key(shot)

        if key in self._hidden_keys:
            self._hidden_keys.remove(key)
            self.logger.info(f"Unhid shot: {shot.full_name}")
            self._save_hidden()

    def is_hidden(self, shot: Shot) -> bool:
        """Check if a shot is hidden.

        Args:
            shot: Shot to check

        Returns:
            True if shot is hidden

        """
        return self._get_key(shot) in self._hidden_keys

    def get_hidden_count(self) -> int:
        """Get the number of hidden shots.

        Returns:
            Number of hidden shots

        """
        return len(self._hidden_keys)

    def clear_hidden(self) -> None:
        """Clear all hidden shots."""
        self._hidden_keys.clear()
        self._save_hidden()
        self.logger.info("Cleared all hidden shots")
