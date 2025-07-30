"""Cache manager for shot data and thumbnails."""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QPixmap


class CacheManager(QObject):
    """Manages caching of shot data and thumbnails."""

    # Signals
    cache_updated = Signal()

    # Cache settings
    CACHE_DIR = Path.home() / ".shotbot" / "cache"
    THUMBNAILS_DIR = CACHE_DIR / "thumbnails"
    SHOTS_CACHE_FILE = CACHE_DIR / "shots.json"
    CACHE_THUMBNAIL_SIZE = 512
    CACHE_EXPIRY_MINUTES = 30

    def __init__(self):
        super().__init__()
        self._ensure_cache_dirs()

    def _ensure_cache_dirs(self):
        """Ensure cache directories exist."""
        self.THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

    def get_cached_thumbnail(
        self, show: str, sequence: str, shot: str
    ) -> Optional[Path]:
        """Get path to cached thumbnail if it exists."""
        cache_path = self.THUMBNAILS_DIR / show / sequence / f"{shot}_thumb.jpg"
        if cache_path.exists():
            return cache_path
        return None

    def cache_thumbnail(
        self, source_path: Path, show: str, sequence: str, shot: str
    ) -> Optional[Path]:
        """Cache a thumbnail from source path."""
        if not source_path.exists():
            return None

        # Create cache directory
        cache_dir = self.THUMBNAILS_DIR / show / sequence
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache file path
        cache_path = cache_dir / f"{shot}_thumb.jpg"

        try:
            # Load and resize image
            pixmap = QPixmap(str(source_path))
            if pixmap.isNull():
                return None

            # Scale to cache size
            scaled = pixmap.scaled(
                self.CACHE_THUMBNAIL_SIZE,
                self.CACHE_THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            # Save to cache
            if scaled.save(str(cache_path), "JPEG", 85):
                return cache_path
        except Exception as e:
            print(f"Error caching thumbnail: {e}")

        return None

    def get_cached_shots(self) -> Optional[List[Dict[str, str]]]:
        """Get cached shot list if valid."""
        if not self.SHOTS_CACHE_FILE.exists():
            return None

        try:
            with open(self.SHOTS_CACHE_FILE, "r") as f:
                data = json.load(f)

            # Check if cache is expired
            cache_time = datetime.fromisoformat(data.get("timestamp", "1970-01-01"))
            if datetime.now() - cache_time > timedelta(
                minutes=self.CACHE_EXPIRY_MINUTES
            ):
                return None

            return data.get("shots", [])
        except Exception as e:
            print(f"Error reading shot cache: {e}")
            return None

    def cache_shots(self, shots: List[Dict[str, str]]):
        """Cache shot list to file."""
        try:
            data: dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "shots": shots,
            }

            # Ensure directory exists
            self.SHOTS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            with open(self.SHOTS_CACHE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error caching shots: {e}")

    def clear_cache(self):
        """Clear all cached data."""
        try:
            if self.THUMBNAILS_DIR.exists():
                shutil.rmtree(self.THUMBNAILS_DIR)
            if self.SHOTS_CACHE_FILE.exists():
                self.SHOTS_CACHE_FILE.unlink()
            self._ensure_cache_dirs()
        except Exception as e:
            print(f"Error clearing cache: {e}")


class ThumbnailCacheLoader(QRunnable):
    """Background thumbnail cache loader."""

    class Signals(QObject):
        loaded = Signal(str, str, str, Path)  # show, sequence, shot, cache_path

    def __init__(
        self,
        cache_manager: CacheManager,
        source_path: Path,
        show: str,
        sequence: str,
        shot: str,
    ):
        super().__init__()
        self.cache_manager = cache_manager
        self.source_path = source_path
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.signals = self.Signals()

    def run(self):
        """Cache the thumbnail in background."""
        cache_path = self.cache_manager.cache_thumbnail(
            self.source_path, self.show, self.sequence, self.shot
        )
        if cache_path:
            self.signals.loaded.emit(self.show, self.sequence, self.shot, cache_path)
