"""File version pinning with optional comments.

Manages persistent pin state for individual scene files, allowing users
to mark important file versions with optional comments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, cast

from PySide6.QtCore import QObject, Signal

from cache import atomic_json_write
from logging_mixin import LoggingMixin
from managers._json_helpers import load_validated_json


# Cache key for pinned files
PINNED_FILES_CACHE_KEY = "pinned_files"


class FilePinManager(LoggingMixin, QObject):
    """Manager for file version pinning with comments.

    Provides persistence for file pins with optional comments.
    Uses file path as unique key for fast lookups.

    Signals:
        pin_changed: Emitted when any pin state changes (path: str)
    """

    # Signals
    pin_changed: ClassVar[Signal] = Signal(
        str
    )  # Emits file path when pin state changes

    # Instance variables (for type checking)
    _cache_dir: Path

    def __init__(
        self,
        cache_dir: Path,
        parent: QObject | None = None,
    ) -> None:
        """Initialize file pin manager.

        Args:
            cache_dir: Directory for cache persistence
            parent: Optional parent QObject

        """
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._pins: dict[str, dict[str, str]] = {}
        self._load_pins()

    # --- Public API ---

    def pin_file(self, file_path: str | Path, comment: str = "") -> None:
        """Pin a file version with optional comment.

        Args:
            file_path: Absolute path to the file
            comment: Optional comment for this pin

        """
        path_str = str(file_path)
        self._pins[path_str] = {
            "comment": comment.strip(),
            "pinned_at": datetime.now(UTC).isoformat(),
        }
        self._save_pins()
        self.logger.info(f"Pinned file: {Path(path_str).name}")
        self.pin_changed.emit(path_str)

    def unpin_file(self, file_path: str | Path) -> None:
        """Remove pin from a file.

        Args:
            file_path: Absolute path to the file

        """
        path_str = str(file_path)
        if path_str in self._pins:
            del self._pins[path_str]
            self._save_pins()
            self.logger.info(f"Unpinned file: {Path(path_str).name}")
            self.pin_changed.emit(path_str)

    def is_pinned(self, file_path: str | Path) -> bool:
        """Check if file is pinned.

        Args:
            file_path: Absolute path to the file

        Returns:
            True if file is pinned

        """
        return str(file_path) in self._pins

    def get_comment(self, file_path: str | Path) -> str:
        """Get comment for pinned file.

        Args:
            file_path: Absolute path to the file

        Returns:
            Comment string, or empty string if not pinned or no comment

        """
        pin_data = self._pins.get(str(file_path))
        if pin_data:
            return pin_data.get("comment", "")
        return ""

    def set_comment(self, file_path: str | Path, comment: str) -> None:
        """Update comment for already-pinned file.

        Args:
            file_path: Absolute path to the file
            comment: New comment text

        Raises:
            ValueError: If file is not pinned

        """
        path_str = str(file_path)
        if path_str not in self._pins:
            msg = f"File not pinned: {path_str}"
            raise ValueError(msg)

        self._pins[path_str]["comment"] = comment.strip()
        self._save_pins()
        self.logger.debug(f"Updated comment for: {Path(path_str).name}")
        self.pin_changed.emit(path_str)

    def get_pinned_count(self) -> int:
        """Get count of pinned files.

        Returns:
            Number of pinned files

        """
        return len(self._pins)

    def clear_pins(self) -> None:
        """Remove all pins."""
        paths = list(self._pins.keys())
        self._pins.clear()
        self._save_pins()
        self.logger.info("Cleared all pinned files")
        for path in paths:
            self.pin_changed.emit(path)

    # --- Persistence ---

    def _load_pins(self) -> None:
        """Load pins from cache file."""
        cache_file = self._cache_dir / f"{PINNED_FILES_CACHE_KEY}.json"

        data = load_validated_json(cache_file, dict, {}, self.logger)

        # Validate structure and load pins
        self._pins = {}
        for path, pin_data_raw in data.items():
            # Runtime check since JSON can have any structure
            if not isinstance(pin_data_raw, dict):
                continue
            pin_data = cast("dict[str, object]", pin_data_raw)
            comment_val = pin_data.get("comment", "")
            pinned_at_val = pin_data.get("pinned_at", "")
            self._pins[path] = {
                "comment": str(comment_val) if comment_val else "",
                "pinned_at": str(pinned_at_val) if pinned_at_val else "",
            }

        self.logger.info(f"Loaded {len(self._pins)} pinned files from cache")

    def _save_pins(self) -> None:
        """Save pins to cache file (atomic write)."""
        cache_file = self._cache_dir / f"{PINNED_FILES_CACHE_KEY}.json"

        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(cache_file, self._pins, indent=2, fsync=False)
            self.logger.debug(f"Saved {len(self._pins)} pinned files to cache")
        except OSError:
            self.logger.exception("Failed to save pinned files")
