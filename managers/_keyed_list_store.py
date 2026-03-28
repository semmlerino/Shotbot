"""Shared JSON-backed list store for (show, sequence, shot) key tuples.

Used by ShotPinManager and HideManager to avoid duplicating load/save/mutation
logic for the same list[tuple[str, str, str]] data shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from cache import atomic_json_write


if TYPE_CHECKING:
    from logging_mixin import ContextualLogger


ShotKey = tuple[str, str, str]


class KeyedListStore:
    """Persistent ordered list of (show, sequence, shot) key tuples.

    Handles JSON load/save with full type validation, plus common
    mutation helpers used by pin and hide managers.
    """

    _cache_dir: Path
    _cache_key: str
    _logger: ContextualLogger
    _keys: list[ShotKey]

    def __init__(
        self, cache_dir: Path, cache_key: str, logger: ContextualLogger
    ) -> None:
        """Initialise and load from cache.

        Args:
            cache_dir: Directory for cache persistence.
            cache_key: Filename stem used for the JSON cache file.
            logger: Caller-supplied logger (typically ``self.logger`` from LoggingMixin).

        """
        self._cache_dir = cache_dir
        self._cache_key = cache_key
        self._logger = logger
        self._keys = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load keys from the JSON cache file."""
        cache_file = self._cache_dir / f"{self._cache_key}.json"

        if not cache_file.exists():
            self._keys = []
            return

        try:
            with cache_file.open() as f:
                raw_data: Any = json.load(f)  # pyright: ignore[reportAny]

            if not isinstance(raw_data, list):
                self._logger.warning(
                    f"Invalid {self._cache_key} cache format: {type(raw_data)}"  # pyright: ignore[reportAny]
                )
                self._keys = []
                return

            data = cast("list[dict[str, object] | list[object]]", raw_data)

            self._keys = []
            for item in data:
                if isinstance(item, dict):
                    try:
                        show_val = item.get("show")
                        seq_val = item.get("sequence")
                        shot_val = item.get("shot")
                        if (
                            isinstance(show_val, str)
                            and isinstance(seq_val, str)
                            and isinstance(shot_val, str)
                        ):
                            self._keys.append((show_val, seq_val, shot_val))
                    except (KeyError, TypeError):
                        self._logger.warning(
                            f"Invalid {self._cache_key} entry", exc_info=True
                        )
                elif isinstance(item, list) and len(item) == 3:  # pyright: ignore[reportUnnecessaryIsInstance]
                    v0, v1, v2 = item[0], item[1], item[2]
                    if (
                        isinstance(v0, str)
                        and isinstance(v1, str)
                        and isinstance(v2, str)
                    ):
                        self._keys.append((v0, v1, v2))

            self._logger.info(f"Loaded {len(self._keys)} {self._cache_key} from cache")

        except (json.JSONDecodeError, OSError):
            self._logger.warning(f"Failed to load {self._cache_key}", exc_info=True)
            self._keys = []

    def save(self) -> None:
        """Persist current keys to the JSON cache file."""
        cache_file = self._cache_dir / f"{self._cache_key}.json"
        dicts = [{"show": s, "sequence": q, "shot": t} for s, q, t in self._keys]
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(cache_file, dicts, indent=2, fsync=False)
            self._logger.debug(f"Saved {len(self._keys)} {self._cache_key} to cache")
        except OSError:
            self._logger.exception(f"Failed to save {self._cache_key}")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def contains(self, key: ShotKey) -> bool:
        """Return True if *key* is present in the list."""
        return key in self._keys

    def count(self) -> int:
        """Return the number of keys currently stored."""
        return len(self._keys)

    def index_of(self, key: ShotKey) -> int:
        """Return the 0-based index of *key*, or -1 if absent."""
        try:
            return self._keys.index(key)
        except ValueError:
            return -1

    # ------------------------------------------------------------------
    # Mutation helpers (callers must call save() when appropriate)
    # ------------------------------------------------------------------

    def add(self, key: ShotKey) -> None:
        """Append *key* to the end of the list (no-op if already present)."""
        if key not in self._keys:
            self._keys.append(key)

    def add_front(self, key: ShotKey) -> None:
        """Insert *key* at position 0, removing any existing occurrence first."""
        if key in self._keys:
            self._keys.remove(key)
        self._keys.insert(0, key)

    def remove(self, key: ShotKey) -> bool:
        """Remove *key* from the list.

        Returns:
            True if the key was present and removed, False otherwise.

        """
        if key in self._keys:
            self._keys.remove(key)
            return True
        return False

    def clear(self) -> None:
        """Remove all keys from the list."""
        self._keys.clear()
