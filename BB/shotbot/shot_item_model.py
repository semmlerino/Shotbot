"""Qt Model/View implementation for shot data using QAbstractItemModel.

This module provides a proper Qt Model/View implementation that replaces
the current plain Python class approach, enabling efficient data handling,
virtualization, and proper update notifications.
"""

import logging
from enum import IntEnum
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QIcon, QPixmap

from cache_manager import CacheManager
from config import Config
from shot_model import RefreshResult, Shot

logger = logging.getLogger(__name__)


class ShotRole(IntEnum):
    """Custom roles for shot data access."""

    # Standard roles
    DisplayRole = Qt.ItemDataRole.DisplayRole
    DecorationRole = Qt.ItemDataRole.DecorationRole
    ToolTipRole = Qt.ItemDataRole.ToolTipRole
    SizeHintRole = Qt.ItemDataRole.SizeHintRole

    # Custom roles starting from UserRole
    ShotObjectRole = Qt.ItemDataRole.UserRole + 1
    ShowRole = Qt.ItemDataRole.UserRole + 2
    SequenceRole = Qt.ItemDataRole.UserRole + 3
    ShotNameRole = Qt.ItemDataRole.UserRole + 4
    FullNameRole = Qt.ItemDataRole.UserRole + 5
    WorkspacePathRole = Qt.ItemDataRole.UserRole + 6
    ThumbnailPathRole = Qt.ItemDataRole.UserRole + 7
    ThumbnailPixmapRole = Qt.ItemDataRole.UserRole + 8
    LoadingStateRole = Qt.ItemDataRole.UserRole + 9
    IsSelectedRole = Qt.ItemDataRole.UserRole + 10


class ShotItemModel(QAbstractListModel):
    """Proper Qt Model implementation for shot data.

    This model provides:
    - Efficient data access through Qt's Model/View framework
    - Lazy loading of thumbnails
    - Proper change notifications
    - Memory-efficient virtualization
    - Batch updates support
    """

    # Signals
    shots_updated = Signal()
    thumbnail_loaded = Signal(int)  # row index
    selection_changed = Signal(QModelIndex)

    def __init__(
        self,
        cache_manager: Optional[CacheManager] = None,
        parent: Optional[QObject] = None,
    ):
        """Initialize the shot item model.

        Args:
            cache_manager: Optional cache manager for thumbnails
            parent: Optional parent QObject
        """
        super().__init__(parent)

        self._shots: List[Shot] = []
        self._cache_manager = cache_manager or CacheManager()
        self._thumbnail_cache: Dict[str, QPixmap] = {}
        self._loading_states: Dict[str, str] = {}
        self._selected_index = QPersistentModelIndex()

        # Lazy loading timer for thumbnails
        self._thumbnail_timer = QTimer()
        self._thumbnail_timer.timeout.connect(self._load_visible_thumbnails)
        self._thumbnail_timer.setInterval(100)  # 100ms delay

        # Track visible range for lazy loading
        self._visible_start = 0
        self._visible_end = 0

        logger.info("ShotItemModel initialized with Model/View architecture")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of shots in the model.

        Args:
            parent: Parent index (unused for list model)

        Returns:
            Number of shots
        """
        if parent.isValid():
            return 0  # List models don't have children
        return len(self._shots)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Get data for the given index and role.

        Args:
            index: Model index
            role: Data role

        Returns:
            Data for the role, or None if invalid
        """
        if not index.isValid() or not (0 <= index.row() < len(self._shots)):
            return None

        shot = self._shots[index.row()]

        # Handle standard roles
        if role == Qt.ItemDataRole.DisplayRole:
            return shot.full_name

        elif role == Qt.ItemDataRole.ToolTipRole:
            return f"{shot.show} / {shot.sequence} / {shot.shot}\n{shot.workspace_path}"

        elif role == Qt.ItemDataRole.SizeHintRole:
            # Return size hint for delegates
            return QSize(
                Config.DEFAULT_THUMBNAIL_SIZE, Config.DEFAULT_THUMBNAIL_SIZE + 40
            )

        # Handle custom roles
        elif role == ShotRole.ShotObjectRole:
            return shot

        elif role == ShotRole.ShowRole:
            return shot.show

        elif role == ShotRole.SequenceRole:
            return shot.sequence

        elif role == ShotRole.ShotNameRole:
            return shot.shot

        elif role == ShotRole.FullNameRole:
            return shot.full_name

        elif role == ShotRole.WorkspacePathRole:
            return shot.workspace_path

        elif role == ShotRole.ThumbnailPathRole:
            return str(shot.get_thumbnail_path()) if shot.get_thumbnail_path() else None

        elif role == ShotRole.ThumbnailPixmapRole:
            # Return cached thumbnail if available
            return self._get_thumbnail_pixmap(shot)

        elif role == ShotRole.LoadingStateRole:
            return self._loading_states.get(shot.full_name, "idle")

        elif role == ShotRole.IsSelectedRole:
            return self._selected_index == QPersistentModelIndex(index)

        elif role == Qt.ItemDataRole.DecorationRole:
            # Return thumbnail icon for decoration
            pixmap = self._get_thumbnail_pixmap(shot)
            return QIcon(pixmap) if pixmap else None

        return None

    def roleNames(self) -> Dict[int, bytes]:
        """Get role names for QML compatibility.

        Returns:
            Dictionary mapping role IDs to role names
        """
        roles = super().roleNames()
        roles.update(
            {
                ShotRole.ShotObjectRole: b"shotObject",
                ShotRole.ShowRole: b"show",
                ShotRole.SequenceRole: b"sequence",
                ShotRole.ShotNameRole: b"shotName",
                ShotRole.FullNameRole: b"fullName",
                ShotRole.WorkspacePathRole: b"workspacePath",
                ShotRole.ThumbnailPathRole: b"thumbnailPath",
                ShotRole.ThumbnailPixmapRole: b"thumbnailPixmap",
                ShotRole.LoadingStateRole: b"loadingState",
                ShotRole.IsSelectedRole: b"isSelected",
            }
        )
        return roles

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Get flags for the given index.

        Args:
            index: Model index

        Returns:
            Item flags
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def setData(
        self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        """Set data for the given index and role.

        Args:
            index: Model index
            value: New value
            role: Data role

        Returns:
            True if successful, False otherwise
        """
        if not index.isValid() or not (0 <= index.row() < len(self._shots)):
            return False

        shot = self._shots[index.row()]

        # Handle selection state
        if role == ShotRole.IsSelectedRole:
            if value:
                self._selected_index = QPersistentModelIndex(index)
                self.selection_changed.emit(index)
            else:
                self._selected_index = QPersistentModelIndex()

            # Emit dataChanged for selection update
            self.dataChanged.emit(index, index, [ShotRole.IsSelectedRole])
            return True

        # Handle loading state
        elif role == ShotRole.LoadingStateRole:
            self._loading_states[shot.full_name] = value
            self.dataChanged.emit(index, index, [ShotRole.LoadingStateRole])
            return True

        return False

    @Slot(list)
    def set_shots(self, shots: List[Shot]) -> None:
        """Set the shot list with proper model reset.

        Args:
            shots: List of Shot objects
        """
        self.beginResetModel()

        self._shots = shots
        self._thumbnail_cache.clear()
        self._loading_states.clear()
        self._selected_index = QPersistentModelIndex()

        self.endResetModel()

        self.shots_updated.emit()
        logger.info(f"Model updated with {len(shots)} shots")

    @Slot(int, int)
    def set_visible_range(self, start: int, end: int) -> None:
        """Set the visible range for lazy loading.

        Args:
            start: Start index
            end: End index
        """
        self._visible_start = max(0, start)
        self._visible_end = min(len(self._shots), end)

        # Start thumbnail loading timer
        if not self._thumbnail_timer.isActive():
            self._thumbnail_timer.start()

    def _load_visible_thumbnails(self) -> None:
        """Load thumbnails for visible items only."""
        # Buffer zone for smoother scrolling
        buffer_size = 5
        start = max(0, self._visible_start - buffer_size)
        end = min(len(self._shots), self._visible_end + buffer_size)

        for row in range(start, end):
            shot = self._shots[row]

            # Skip if already loaded or loading
            if shot.full_name in self._thumbnail_cache:
                continue

            if self._loading_states.get(shot.full_name) == "loading":
                continue

            # Start loading
            self._load_thumbnail_async(row, shot)

        # Stop timer if no more loading needed
        all_loaded = all(
            self._shots[i].full_name in self._thumbnail_cache for i in range(start, end)
        )
        if all_loaded:
            self._thumbnail_timer.stop()

    def _load_thumbnail_async(self, row: int, shot: Shot) -> None:
        """Start async thumbnail loading for a shot.

        Args:
            row: Row index
            shot: Shot object
        """
        # Mark as loading
        self._loading_states[shot.full_name] = "loading"
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [ShotRole.LoadingStateRole])

        # Simulate async loading (in real implementation, use QRunnable)
        # For now, load synchronously but emit proper signals
        thumbnail_path = shot.get_thumbnail_path()
        if thumbnail_path and thumbnail_path.exists():
            pixmap = QPixmap(str(thumbnail_path))
            if not pixmap.isNull():
                # Scale to thumbnail size
                pixmap = pixmap.scaled(
                    Config.DEFAULT_THUMBNAIL_SIZE,
                    Config.DEFAULT_THUMBNAIL_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._thumbnail_cache[shot.full_name] = pixmap
                self._loading_states[shot.full_name] = "loaded"

                # Notify view of update
                self.dataChanged.emit(
                    index,
                    index,
                    [
                        ShotRole.ThumbnailPixmapRole,
                        ShotRole.LoadingStateRole,
                        Qt.ItemDataRole.DecorationRole,
                    ],
                )
                self.thumbnail_loaded.emit(row)
            else:
                self._loading_states[shot.full_name] = "failed"
                self.dataChanged.emit(index, index, [ShotRole.LoadingStateRole])
        else:
            self._loading_states[shot.full_name] = "failed"
            self.dataChanged.emit(index, index, [ShotRole.LoadingStateRole])

    def _get_thumbnail_pixmap(self, shot: Shot) -> Optional[QPixmap]:
        """Get cached thumbnail pixmap for a shot.

        Args:
            shot: Shot object

        Returns:
            Cached QPixmap or None
        """
        return self._thumbnail_cache.get(shot.full_name)

    def get_shot_at_index(self, index: QModelIndex) -> Optional[Shot]:
        """Get shot object at the given index.

        Args:
            index: Model index

        Returns:
            Shot object or None if invalid
        """
        if index.isValid() and 0 <= index.row() < len(self._shots):
            return self._shots[index.row()]
        return None

    def refresh_shots(self, shots: List[Shot]) -> RefreshResult:
        """Refresh shots with intelligent updates.

        Args:
            shots: New list of shots

        Returns:
            RefreshResult indicating success and changes
        """
        # Compare with existing shots
        old_shot_names = {shot.full_name for shot in self._shots}
        new_shot_names = {shot.full_name for shot in shots}

        has_changes = old_shot_names != new_shot_names

        if has_changes:
            # Use beginInsertRows/beginRemoveRows for incremental updates
            # For simplicity, doing full reset here, but could be optimized
            self.set_shots(shots)

        return RefreshResult(success=True, has_changes=has_changes)

    def clear_thumbnail_cache(self) -> None:
        """Clear the thumbnail cache to free memory."""
        self._thumbnail_cache.clear()

        # Notify all items that thumbnails need reloading
        if self._shots:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._shots) - 1, 0),
                [ShotRole.ThumbnailPixmapRole, Qt.ItemDataRole.DecorationRole],
            )
