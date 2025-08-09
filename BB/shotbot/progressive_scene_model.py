"""Progressive Qt Model/View implementation for 3DE scene display.

This module provides a QAbstractListModel implementation that supports
progressive loading, virtual scrolling, and efficient memory management
for handling thousands of 3DE scenes.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QMutex,
    QMutexLocker,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QIcon, QPixmap

from cache_manager import CacheManager
from config import Config
from threede_scene_model import ThreeDEScene

logger = logging.getLogger(__name__)


@dataclass
class SceneItem:
    """Wrapper for scene data with loading state."""

    scene: ThreeDEScene
    thumbnail: Optional[QPixmap] = None
    thumbnail_loading: bool = False
    thumbnail_loaded: bool = False
    is_placeholder: bool = False

    def __hash__(self):
        """Make hashable for deduplication."""
        return hash((self.scene.full_name, self.scene.user, str(self.scene.scene_path)))


class ThumbnailLoader(QRunnable):
    """Background thumbnail loader."""

    class Signals(QObject):
        loaded = Signal(int, QPixmap)  # row, pixmap
        failed = Signal(int)  # row

    def __init__(self, row: int, scene: ThreeDEScene, size: int):
        super().__init__()
        self.row = row
        self.scene = scene
        self.size = size
        self.signals = self.Signals()

    def run(self):
        """Load thumbnail in background."""
        try:
            thumb_path = self.scene.get_thumbnail_path()
            if thumb_path and thumb_path.exists():
                pixmap = QPixmap(str(thumb_path))
                if not pixmap.isNull():
                    # Scale to requested size
                    scaled = pixmap.scaled(
                        self.size,
                        self.size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.signals.loaded.emit(self.row, scaled)
                    return

            self.signals.failed.emit(self.row)

        except Exception as e:
            logger.debug(f"Error loading thumbnail: {e}")
            self.signals.failed.emit(self.row)


class ProgressiveSceneModel(QAbstractListModel):
    """Progressive loading model for 3DE scenes."""

    # Custom roles
    SceneRole = Qt.ItemDataRole.UserRole + 1
    ThumbnailRole = Qt.ItemDataRole.UserRole + 2
    LoadingRole = Qt.ItemDataRole.UserRole + 3
    PlaceholderRole = Qt.ItemDataRole.UserRole + 4

    # Signals
    scanStarted = Signal()
    scanProgress = Signal(int, int, str)  # current, total, message
    scanFinished = Signal(int)  # total scenes
    batchLoaded = Signal(int)  # number of new scenes

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        super().__init__()

        # Data storage
        self._items: List[SceneItem] = []
        self._dedup_set: Set[SceneItem] = set()
        self._mutex = QMutex()

        # Loading state
        self._is_loading = False
        self._total_expected = 0
        self._visible_range = (0, 50)  # Track visible items for lazy loading

        # Thumbnail management
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE
        self._thumbnail_pool = QThreadPool()
        self._thumbnail_pool.setMaxThreadCount(4)
        self._thumbnail_cache: Dict[str, QPixmap] = {}

        # Placeholder pixmap
        self._placeholder = self._create_placeholder()

        # Cache manager
        self.cache_manager = cache_manager or CacheManager()

        # Performance metrics
        self._last_update_time = 0.0
        self._update_interval = 0.1  # Minimum seconds between updates

        # Batch update timer
        self._batch_timer = QTimer()
        self._batch_timer.timeout.connect(self._process_batch_queue)
        self._batch_timer.setInterval(50)  # 50ms batching
        self._batch_queue: List[SceneItem] = []

        # Load from cache if available
        self._load_from_cache()

    def _create_placeholder(self) -> QPixmap:
        """Create a placeholder pixmap."""
        pixmap = QPixmap(self._thumbnail_size, self._thumbnail_size)
        pixmap.fill(Qt.GlobalColor.darkGray)
        return pixmap

    def _load_from_cache(self) -> bool:
        """Load scenes from cache."""
        try:
            cached_data = self.cache_manager.get_cached_threede_scenes()
            if cached_data:
                scenes = []
                for scene_data in cached_data:
                    try:
                        scene = ThreeDEScene.from_dict(scene_data)
                        scenes.append(scene)
                    except Exception as e:
                        logger.debug(f"Skipping invalid cached scene: {e}")

                if scenes:
                    # Add all at once
                    self.beginResetModel()
                    for scene in scenes:
                        item = SceneItem(scene=scene)
                        self._items.append(item)
                        self._dedup_set.add(item)
                    self.endResetModel()

                    # Start loading visible thumbnails
                    self._load_visible_thumbnails()
                    return True

        except Exception as e:
            logger.error(f"Error loading from cache: {e}")

        return False

    # Qt Model interface

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of rows."""
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for the given role."""
        if not index.isValid() or index.row() >= len(self._items):
            return None

        item = self._items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.scene.display_name
        elif role == Qt.ItemDataRole.ToolTipRole:
            return f"{item.scene.display_name}\n{item.scene.scene_path}"
        elif role == self.SceneRole:
            return item.scene
        elif role == self.ThumbnailRole:
            return item.thumbnail or self._placeholder
        elif role == self.LoadingRole:
            return item.thumbnail_loading
        elif role == self.PlaceholderRole:
            return item.is_placeholder
        elif role == Qt.ItemDataRole.DecorationRole:
            # Return icon-sized thumbnail for list views
            thumb = item.thumbnail or self._placeholder
            return QIcon(thumb)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)
        item = self._items[index.row()]

        # Disable selection for placeholders
        if item.is_placeholder:
            flags &= ~Qt.ItemFlag.ItemIsSelectable
            flags &= ~Qt.ItemFlag.ItemIsEnabled

        return flags

    # Progressive loading interface

    def add_scenes_batch(self, scenes: List[ThreeDEScene]) -> None:
        """Add a batch of scenes to the model.

        Args:
            scenes: Batch of scenes to add
        """
        if not scenes:
            return

        # Add to batch queue
        with QMutexLocker(self._mutex):
            for scene in scenes:
                item = SceneItem(scene=scene)
                if item not in self._dedup_set:
                    self._batch_queue.append(item)
                    self._dedup_set.add(item)

        # Start batch timer if not running
        if not self._batch_timer.isActive():
            self._batch_timer.start()

    @Slot()
    def _process_batch_queue(self) -> None:
        """Process the batch queue."""
        if not self._batch_queue:
            self._batch_timer.stop()
            return

        # Check if enough time has passed since last update
        current_time = time.time()
        if current_time - self._last_update_time < self._update_interval:
            return

        # Process batch
        with QMutexLocker(self._mutex):
            batch = self._batch_queue[:50]  # Process up to 50 at a time
            self._batch_queue = self._batch_queue[50:]

        if batch:
            # Add to model
            first_row = len(self._items)
            last_row = first_row + len(batch) - 1

            self.beginInsertRows(QModelIndex(), first_row, last_row)
            self._items.extend(batch)
            self.endInsertRows()

            self._last_update_time = current_time
            self.batchLoaded.emit(len(batch))

            # Load thumbnails for newly added items if visible
            self._load_visible_thumbnails()

    def set_visible_range(self, start: int, end: int) -> None:
        """Set the visible range for lazy loading.

        Args:
            start: First visible row
            end: Last visible row
        """
        self._visible_range = (start, end)
        self._load_visible_thumbnails()

    def _load_visible_thumbnails(self) -> None:
        """Load thumbnails for visible items."""
        start, end = self._visible_range

        for row in range(max(0, start), min(end + 1, len(self._items))):
            item = self._items[row]

            # Skip if already loaded or loading
            if item.thumbnail_loaded or item.thumbnail_loading:
                continue

            # Check cache first
            cache_key = f"{item.scene.full_name}_{item.scene.user}"
            if cache_key in self._thumbnail_cache:
                item.thumbnail = self._thumbnail_cache[cache_key]
                item.thumbnail_loaded = True
                # Emit data changed
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.ThumbnailRole])
                continue

            # Start loading
            item.thumbnail_loading = True
            loader = ThumbnailLoader(row, item.scene, self._thumbnail_size)
            loader.signals.loaded.connect(self._on_thumbnail_loaded)
            loader.signals.failed.connect(self._on_thumbnail_failed)
            self._thumbnail_pool.start(loader)

    @Slot(int, QPixmap)
    def _on_thumbnail_loaded(self, row: int, pixmap: QPixmap) -> None:
        """Handle loaded thumbnail."""
        if row >= len(self._items):
            return

        item = self._items[row]
        item.thumbnail = pixmap
        item.thumbnail_loading = False
        item.thumbnail_loaded = True

        # Cache it
        cache_key = f"{item.scene.full_name}_{item.scene.user}"
        self._thumbnail_cache[cache_key] = pixmap

        # Emit data changed
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.ThumbnailRole, self.LoadingRole])

    @Slot(int)
    def _on_thumbnail_failed(self, row: int) -> None:
        """Handle failed thumbnail load."""
        if row >= len(self._items):
            return

        item = self._items[row]
        item.thumbnail_loading = False
        item.thumbnail_loaded = True  # Mark as loaded to avoid retrying

        # Emit data changed
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.LoadingRole])

    # Utility methods

    def clear(self) -> None:
        """Clear all scenes."""
        self.beginResetModel()
        self._items.clear()
        self._dedup_set.clear()
        self._batch_queue.clear()
        self.endResetModel()

    def get_scene_at(self, row: int) -> Optional[ThreeDEScene]:
        """Get scene at given row."""
        if 0 <= row < len(self._items):
            return self._items[row].scene
        return None

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size and reload."""
        if size == self._thumbnail_size:
            return

        self._thumbnail_size = size
        self._placeholder = self._create_placeholder()
        self._thumbnail_cache.clear()

        # Mark all as not loaded
        for item in self._items:
            item.thumbnail = None
            item.thumbnail_loaded = False
            item.thumbnail_loading = False

        # Reload visible
        self._load_visible_thumbnails()

        # Emit data changed for all
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._items) - 1, 0),
                [self.ThumbnailRole],
            )

    def save_to_cache(self) -> None:
        """Save current scenes to cache."""
        try:
            scenes_data = [item.scene.to_dict() for item in self._items]
            self.cache_manager.cache_threede_scenes(scenes_data)
        except Exception as e:
            logger.error(f"Error saving to cache: {e}")

    # Deduplication

    def deduplicate_by_shot(self) -> None:
        """Deduplicate scenes keeping best per shot."""
        scenes_by_shot = defaultdict(list)

        for item in self._items:
            shot_key = f"{item.scene.show}/{item.scene.sequence}/{item.scene.shot}"
            scenes_by_shot[shot_key].append(item)

        # Select best from each group
        deduplicated = []
        for shot_items in scenes_by_shot.values():
            if len(shot_items) == 1:
                deduplicated.append(shot_items[0])
            else:
                best = self._select_best_item(shot_items)
                deduplicated.append(best)

        # Update model
        self.beginResetModel()
        self._items = deduplicated
        self._dedup_set = set(deduplicated)
        self.endResetModel()

    def _select_best_item(self, items: List[SceneItem]) -> SceneItem:
        """Select best item from duplicates."""

        def get_mtime(item):
            try:
                return item.scene.scene_path.stat().st_mtime
            except OSError:
                return 0

        plate_priority = {"fg01": 3, "bg01": 2}

        def item_score(item):
            mtime = get_mtime(item)
            plate_score = plate_priority.get(item.scene.plate.lower(), 1)
            return (mtime, plate_score, item.scene.plate)

        return max(items, key=item_score)

    # Performance monitoring

    def get_memory_usage(self) -> Dict[str, int]:
        """Get memory usage statistics."""
        return {
            "scenes": len(self._items),
            "thumbnails_cached": len(self._thumbnail_cache),
            "batch_queue": len(self._batch_queue),
            "thread_pool_active": self._thumbnail_pool.activeThreadCount(),
        }
