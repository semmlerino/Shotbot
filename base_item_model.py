"""Base Qt Model implementation for item data using QAbstractListModel.

This module provides a base implementation that extracts common functionality
from ShotItemModel, ThreeDEItemModel, and PreviousShotsItemModel, reducing
code duplication by ~70-80%.
"""

from __future__ import annotations

# Standard library imports
from abc import ABC, abstractmethod
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache
    from thumbnail_loader import ThumbnailLoader

# Third-party imports
from PySide6.QtCore import (
    QAbstractListModel,
    QCoreApplication,
    QModelIndex,
    QMutex,
    QMutexLocker,
    QObject,
    QPersistentModelIndex,
    QRunnable,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QIcon, QImage, QPixmap

# Local application imports
from config import Config
from logging_mixin import LoggingMixin, get_module_logger
from protocols import SceneDataProtocol
from qt_abc_meta import QABCMeta
from runnable_tracker import TrackedQRunnable
from typing_compat import override


# Module-level logger for non-LoggingMixin classes in this module
_logger = get_module_logger(__name__)

# Type variable for the data items (Shot or ThreeDEScene)
T = TypeVar("T", bound=SceneDataProtocol)


class QtThreadError(RuntimeError):
    """Raised when Qt operations attempted from wrong thread.

    This exception is raised when a Qt operation that requires main thread
    execution is attempted from a different thread, indicating a threading
    violation in the application.
    """


class ThumbnailLoaderSignals(QObject):
    """Signals for ThumbnailLoaderRunnable.

    Provides thread-safe communication from the background thumbnail loader
    to the main thread via Qt signals.
    """

    finished: ClassVar[Signal] = Signal(str, Path)  # full_name, cached_path
    failed: ClassVar[Signal] = Signal(str)  # full_name


class ThumbnailLoaderRunnable(TrackedQRunnable):
    """Background thumbnail loader using QThreadPool.

    Loads and caches thumbnails in a background thread to avoid blocking
    the main UI thread during thumbnail processing (PIL image decode,
    resize, and encode operations).
    """

    def __init__(
        self,
        full_name: str,
        thumbnail_path: Path,
        show: str,
        sequence: str,
        shot: str,
        cache_manager: ThumbnailCache,
    ) -> None:
        """Initialize the thumbnail loader runnable.

        Args:
            full_name: Unique identifier for the item (e.g., "show/seq/shot")
            thumbnail_path: Path to the source thumbnail image
            show: Show name for cache organization
            sequence: Sequence name for cache organization
            shot: Shot name for cache organization
            cache_manager: ThumbnailCache instance for thumbnail caching

        """
        # Pass auto_delete=False because callbacks need to clean up
        super().__init__(auto_delete=False)
        self.full_name: str = full_name
        self.thumbnail_path: Path = thumbnail_path
        self.show: str = show
        self.sequence: str = sequence
        self.shot: str = shot
        self.cache_manager: ThumbnailCache = cache_manager
        self.signals: ThumbnailLoaderSignals = ThumbnailLoaderSignals()

    @override
    def _do_work(self) -> None:
        """Execute thumbnail caching in background thread."""
        try:
            cached_result = self.cache_manager.cache_thumbnail(
                self.thumbnail_path,
                self.show,
                self.sequence,
                self.shot,
            )
            if isinstance(cached_result, Path) and cached_result.exists():
                self.signals.finished.emit(self.full_name, cached_result)
            else:
                self.signals.failed.emit(self.full_name)
        except Exception:
            _logger.exception(f"Thumbnail cache failed for {self.full_name!r}")
            self.signals.failed.emit(self.full_name)


class BaseItemRole(IntEnum):
    """Common roles shared across all item models."""

    # Standard Qt roles
    DisplayRole = Qt.ItemDataRole.DisplayRole
    DecorationRole = Qt.ItemDataRole.DecorationRole
    ToolTipRole = Qt.ItemDataRole.ToolTipRole
    SizeHintRole = Qt.ItemDataRole.SizeHintRole

    # Common custom roles
    ObjectRole = Qt.ItemDataRole.UserRole + 1
    ShowRole = Qt.ItemDataRole.UserRole + 2
    SequenceRole = Qt.ItemDataRole.UserRole + 3
    # UserRole + 4 is intentionally skipped — reserved to avoid collisions with
    # subclass roles that may have historically used this slot.
    FullNameRole = Qt.ItemDataRole.UserRole + 5
    WorkspacePathRole = Qt.ItemDataRole.UserRole + 6
    ThumbnailPathRole = Qt.ItemDataRole.UserRole + 7
    ThumbnailPixmapRole = Qt.ItemDataRole.UserRole + 8
    LoadingStateRole = Qt.ItemDataRole.UserRole + 9
    IsSelectedRole = Qt.ItemDataRole.UserRole + 10
    IsPinnedRole = Qt.ItemDataRole.UserRole + 11
    FrameRangeRole = Qt.ItemDataRole.UserRole + 12  # Frame range display string

    # Item-specific roles (for backward compatibility with old tests)
    ItemSpecificRole1 = (
        Qt.ItemDataRole.UserRole + 20
    )  # shot.shot for Shot items, scene.shot for ThreeDEScene
    ItemSpecificRole2 = Qt.ItemDataRole.UserRole + 21  # scene.user for ThreeDEScene
    ItemSpecificRole3 = (
        Qt.ItemDataRole.UserRole + 22
    )  # scene.scene_path for ThreeDEScene
    ModifiedTimeRole = Qt.ItemDataRole.UserRole + 23  # File modification timestamp
    HasNoteRole = Qt.ItemDataRole.UserRole + 24
    IsHiddenRole = Qt.ItemDataRole.UserRole + 25  # Whether shot has a note


class BaseItemModel(
    ABC, LoggingMixin, QAbstractListModel, Generic[T], metaclass=QABCMeta
):
    """Base Qt Model implementation for item data.

    This base class provides:
    - Efficient data access through Qt's Model/View framework
    - Lazy loading of thumbnails
    - Proper change notifications
    - Memory-efficient virtualization
    - Thread-safe thumbnail caching
    - Common selection management
    - Show filtering support

    Subclasses must implement abstract methods to provide
    specific behavior for their data types.
    """

    # Timing constants for thumbnail loading and batching
    _THUMBNAIL_DEBOUNCE_MS: ClassVar[int] = 250
    _BATCH_WINDOW_MS: ClassVar[int] = 10
    _INITIAL_LOAD_COUNT: ClassVar[int] = 30
    _INITIAL_LOAD_DELAY_MS: ClassVar[int] = 100

    # Common signals
    items_updated: Signal = Signal()  # Emitted when items list changes
    thumbnail_loaded: Signal = Signal(int)  # row index
    selection_changed: Signal = Signal(QModelIndex)
    show_filter_changed: Signal = Signal(str)  # show name or "All Shows"

    def __init__(
        self,
        cache_manager: ThumbnailCache | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the base item model.

        Args:
            cache_manager: Optional cache manager for thumbnails
            parent: Optional parent QObject

        """
        # Ensure we're in the main thread for Qt model creation
        app = QCoreApplication.instance()
        if app and QThread.currentThread() != app.thread():
            msg = f"{self.__class__.__name__} must be created in the main thread. Current thread: {QThread.currentThread()}, Main thread: {app.thread()}"
            raise RuntimeError(
                msg
            )
        super().__init__(parent)

        # Core data storage
        self._items: list[T] = []
        self._sort_order: str = "date"
        if cache_manager is None:
            from cache.thumbnail_cache import make_default_thumbnail_cache
            cache_manager = make_default_thumbnail_cache()
        self._cache_manager: ThumbnailCache = cache_manager

        # Selection tracking
        self._selected_index: QPersistentModelIndex = QPersistentModelIndex()
        self._selected_item: T | None = None

        # Track visible range for lazy loading
        self._visible_start: int = 0
        self._visible_end: int = 0

        # Thumbnail subsystem — owns all async loading state and timers
        from thumbnail_loader import ThumbnailLoader as _ThumbnailLoader
        self._thumbnail_loader: ThumbnailLoader[T] = _ThumbnailLoader(
            cache_manager,
            get_items=lambda: self._items,
            get_visible_range=lambda: (self._visible_start, self._visible_end),
            parent=self,
        )
        _ = self._thumbnail_loader.data_changed.connect(self._on_thumbnail_data_changed)
        _ = self._thumbnail_loader.thumbnail_ready.connect(self.thumbnail_loaded)

        self.logger.info(
            f"{self.__class__.__name__} initialized with Model/View architecture"
        )

    # ============= Forwarding properties for thumbnail subsystem =============
    # Tests and subclasses access these attributes directly on the model.
    # Properties forward them to the ThumbnailLoader without breaking callers.

    @property
    def _thumbnail_cache(self) -> dict[str, QImage]:
        return self._thumbnail_loader.thumbnail_cache

    @_thumbnail_cache.setter
    def _thumbnail_cache(self, value: dict[str, QImage]) -> None:
        self._thumbnail_loader.thumbnail_cache = value

    @property
    def _pixmap_cache(self) -> dict[str, QPixmap]:
        return self._thumbnail_loader.pixmap_cache

    @_pixmap_cache.setter
    def _pixmap_cache(self, value: dict[str, QPixmap]) -> None:
        self._thumbnail_loader.pixmap_cache = value

    @property
    def _loading_states(self) -> dict[str, str]:
        return self._thumbnail_loader.loading_states

    @_loading_states.setter
    def _loading_states(self, value: dict[str, str]) -> None:
        self._thumbnail_loader.loading_states = value

    @property
    def _cache_mutex(self) -> QMutex:
        return self._thumbnail_loader.cache_mutex

    @property
    def _thumbnail_debounce_timer(self) -> QTimer:
        return self._thumbnail_loader.thumbnail_debounce_timer

    @property
    def _pending_updates(self) -> dict[int, set[int]]:
        return self._thumbnail_loader.pending_updates

    @property
    def _batch_timer(self) -> QTimer:
        return self._thumbnail_loader.batch_timer

    @override
    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex | None = None,
    ) -> int:
        """Return number of items in the model.

        Args:
            parent: Parent index (default None creates invalid index,
                   unused for list models)

        Returns:
            Number of items

        """
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0  # List models don't have children
        return len(self._items)

    @override
    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        """Get data for the given index and role.

        Args:
            index: Model index
            role: Data role

        Returns:
            Data for the role, or None if invalid

        """
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None

        item = self._items[index.row()]

        # Handle standard roles
        if role == Qt.ItemDataRole.DisplayRole:
            return self.get_display_role_data(item)

        if role == Qt.ItemDataRole.ToolTipRole:
            return self.get_tooltip_data(item)

        if role == Qt.ItemDataRole.SizeHintRole:
            return self.get_size_hint()

        # Handle common custom roles
        if role == BaseItemRole.ObjectRole:
            return item

        if role == BaseItemRole.ShowRole:
            return item.show

        if role == BaseItemRole.SequenceRole:
            return item.sequence

        if role == BaseItemRole.FullNameRole:
            return item.full_name

        if role == BaseItemRole.WorkspacePathRole:
            return item.workspace_path

        if role == BaseItemRole.ThumbnailPathRole:
            thumb_path = item.get_thumbnail_path()
            return str(thumb_path) if thumb_path else None

        if role == BaseItemRole.ThumbnailPixmapRole:
            return self._get_thumbnail_pixmap(item)

        if role == BaseItemRole.LoadingStateRole:
            with QMutexLocker(self._cache_mutex):
                return self._loading_states.get(item.full_name, "idle")

        if role == BaseItemRole.IsSelectedRole:
            return self._selected_index == QPersistentModelIndex(index)

        if role == Qt.ItemDataRole.DecorationRole:
            # Return thumbnail icon for decoration
            pixmap = self._get_thumbnail_pixmap(item)
            return QIcon(pixmap) if pixmap else None

        # Let subclass handle model-specific roles
        return self.get_custom_role_data(item, role)

    @override
    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """Get flags for the given index.

        Args:
            index: Model index

        Returns:
            Item flags

        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    @override
    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        """Set data for the given index and role.

        Args:
            index: Model index
            value: New value
            role: Data role

        Returns:
            True if successful, False otherwise

        """
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return False

        item = self._items[index.row()]

        # Handle selection state
        if role == BaseItemRole.IsSelectedRole:
            if value:
                self._selected_index = QPersistentModelIndex(index)
                self._selected_item = item
                self.selection_changed.emit(index)
            else:
                self._selected_index = QPersistentModelIndex()
                self._selected_item = None

            # Emit dataChanged for selection update
            self.dataChanged.emit(index, index, [BaseItemRole.IsSelectedRole])
            return True

        # Handle loading state
        if role == BaseItemRole.LoadingStateRole:
            with QMutexLocker(self._cache_mutex):
                self._loading_states[item.full_name] = (
                    str(value) if value is not None else ""
                )
            self.dataChanged.emit(index, index, [BaseItemRole.LoadingStateRole])
            return True

        # Let subclass handle model-specific data setting
        return self.set_custom_data(item, value, role)

    @Slot(int, int)  # PySide6 Slot decorator type limitation
    def set_visible_range(self, start: int, end: int) -> None:
        """Set the visible range for lazy loading.

        Args:
            start: Start index
            end: End index

        """
        self._visible_start = max(0, start)
        self._visible_end = min(len(self._items) - 1, end) if self._items else 0

        # Schedule debounced thumbnail check
        self._thumbnail_debounce_timer.start()  # Restart delays execution

    def _load_visible_thumbnails(self) -> None:
        """Check if visible range changed and schedule actual load."""
        self._thumbnail_loader.load_visible_thumbnails()

    def _do_load_visible_thumbnails(self) -> None:
        """Actually load thumbnails for visible range."""
        self._thumbnail_loader.do_load_visible_thumbnails()

    def _get_thumbnail_pixmap(self, item: T) -> QPixmap | None:
        """Get cached thumbnail pixmap for an item.

        Thread-safe: Converts QImage to QPixmap in main thread for display.

        Args:
            item: Item object

        Returns:
            QPixmap converted from cached QImage or None

        Raises:
            QtThreadError: If called from non-main thread

        """
        app = QCoreApplication.instance()
        if app and QThread.currentThread() != app.thread():
            msg = (
                f"_get_thumbnail_pixmap() must be called from main thread. "
                f"Current: {QThread.currentThread()}, Main: {app.thread()}"
            )
            raise QtThreadError(
                msg
            )
        return self._thumbnail_loader.get_pixmap(item)

    def _on_thumbnail_data_changed(self, updates: dict[int, set[int]]) -> None:
        """Handle batched dataChanged from ThumbnailLoader."""
        if not updates:
            return

        sorted_rows = sorted(updates.keys())

        i = 0
        while i < len(sorted_rows):
            start_row = sorted_rows[i]
            end_row = start_row
            combined_roles = updates[start_row].copy()

            while i + 1 < len(sorted_rows) and sorted_rows[i + 1] == end_row + 1:
                i += 1
                end_row = sorted_rows[i]
                combined_roles.update(updates[end_row])

            start_index = self.index(start_row, 0)
            end_index = self.index(end_row, 0)
            self.dataChanged.emit(start_index, end_index, list(combined_roles))

            i += 1

    def get_item_at_index(self, index: QModelIndex) -> T | None:
        """Get item object at the given index.

        Args:
            index: Model index

        Returns:
            Item object or None if invalid

        """
        if index.isValid() and 0 <= index.row() < len(self._items):
            return self._items[index.row()]
        return None

    def get_selected_item(self) -> T | None:
        """Get currently selected item.

        Note: This getter acquires _cache_mutex for the read, but writes to
        _selected_item (via setData) happen on the main thread without a lock.
        The mutex here protects against torn reads from background threads, but
        does not provide full write-side protection — callers must not rely on
        this as a fully thread-safe operation.

        Returns:
            Selected item or None

        """
        with QMutexLocker(self._cache_mutex):
            return self._selected_item

    def clear_selection(self) -> None:
        """Clear the current selection."""
        if self._selected_item:
            # Find and update the index
            for i, item in enumerate(self._items):
                if item == self._selected_item:
                    index = self.index(i, 0)
                    _ = self.setData(index, False, BaseItemRole.IsSelectedRole)
                    break

    def clear_thumbnail_cache(self) -> None:
        """Clear the thumbnail cache to free memory."""
        self._thumbnail_loader.clear_thumbnail_cache()

        # Notify all items that thumbnails need reloading
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._items) - 1, 0),
                [BaseItemRole.ThumbnailPixmapRole, Qt.ItemDataRole.DecorationRole],
            )

    def set_items(self, items: list[T]) -> None:
        """Set items with thumbnail cache preservation.

        Preserves cached thumbnails for items that exist in both the old and new
        item lists (matched by full_name). Thumbnails for removed items are
        automatically discarded.

        IMPORTANT BEHAVIORS:
        - Clears current selection (if any)
        - Stops active thumbnail loading timer BEFORE model reset
        - Items with duplicate full_name values share cached thumbnails
        - Emits modelReset signal followed by items_updated signal
        - Safe to call during active loading operations

        Args:
            items: New list of items to display. Can be empty list.

        Raises:
            QtThreadError: If called outside Qt main thread

        """
        # CRITICAL: Verify main thread (Qt requirement)
        app = QCoreApplication.instance()
        if app and QThread.currentThread() != app.thread():
            msg = f"set_items() must be called from main thread. Current: {QThread.currentThread()}, Main: {app.thread()}"
            raise QtThreadError(
                msg
            )

        # CRITICAL: Stop timers FIRST (prevents callback races)
        if self._thumbnail_debounce_timer.isActive():
            self._thumbnail_debounce_timer.stop()

        # Build lookup set BEFORE model reset (exception safety)
        new_item_names = {item.full_name for item in items}

        # NOW safe to begin model reset
        self.beginResetModel()

        try:
            # Update items list (state modification inside try block)
            self._items = items

            # Acquire mutex ONLY for cache filtering (minimize hold time)
            with QMutexLocker(self._cache_mutex):
                old_cache_size = len(self._thumbnail_cache)

                # Filter thumbnail cache - preserve only items still present
                self._thumbnail_cache = {
                    name: image
                    for name, image in self._thumbnail_cache.items()
                    if name in new_item_names
                }

                # Filter loading states - preserve only items still present
                self._loading_states = {
                    name: state
                    for name, state in self._loading_states.items()
                    if name in new_item_names
                }

                new_cache_size = len(self._thumbnail_cache)
            # QMutexLocker automatically releases lock here

            preserved = new_cache_size
            evicted = old_cache_size - new_cache_size

            self.logger.info(
                f"Model updated: {len(items)} items, thumbnails: {preserved} preserved, {evicted} evicted"
            )

            # Clear selection (existing behavior)
            self._selected_index = QPersistentModelIndex()
            self._selected_item = None

        finally:
            # CRITICAL: Always complete model reset
            self.endResetModel()

        # Emit signal AFTER successful update
        self.items_updated.emit()

        # CRITICAL: Trigger initial thumbnail load for visible items
        # Set visible range to a reasonable initial value (view will refine this on first paint)
        # Use min(INITIAL_LOAD_COUNT, item_count) to avoid loading all thumbnails on startup
        if self._items:
            initial_load_count = min(self._INITIAL_LOAD_COUNT, len(self._items))
            self._visible_end = initial_load_count - 1
            # Schedule immediate thumbnail load for initial visible items only
            self.logger.debug(f"Scheduling thumbnail load timer for {initial_load_count} items (total: {len(self._items)})")
            QTimer.singleShot(self._INITIAL_LOAD_DELAY_MS, self._do_load_visible_thumbnails)

    # ============= Abstract methods for subclasses =============

    @abstractmethod
    def get_display_role_data(self, item: T) -> str:
        """Get display text for an item.

        Args:
            item: The item to get display text for

        Returns:
            Display text string

        """

    @abstractmethod
    def get_tooltip_data(self, item: T) -> str:
        """Get tooltip text for an item.

        Args:
            item: The item to get tooltip for

        Returns:
            Tooltip text string

        """

    def get_size_hint(self) -> QSize:
        """Get size hint for items.

        Returns:
            QSize object or None

        Can be overridden by subclasses for custom sizing.

        """
        return QSize(
            Config.DEFAULT_THUMBNAIL_SIZE,
            Config.DEFAULT_THUMBNAIL_SIZE + 40,
        )

    def get_custom_role_data(self, item: T, role: int) -> object | None:
        """Handle model-specific custom roles.

        Args:
            item: The item
            role: The data role

        Returns:
            Data for the role or None

        Override in subclasses to handle model-specific roles.

        """
        return None

    def set_custom_data(self, _item: T, _value: object | None, _role: int) -> bool:
        """Handle model-specific data setting.

        Args:
            item: The item
            value: Value to set
            role: The data role

        Returns:
            True if handled, False otherwise

        Override in subclasses to handle model-specific data setting.

        """
        return False

    def _apply_sort(self, items: list[T]) -> list[T]:
        """Apply current sort order to items. Override in subclasses.

        Args:
            items: List of items to sort

        Returns:
            Sorted list of items (base returns unchanged)

        """
        return items

    def set_sort_order(self, order: str) -> None:
        """Set the sort order and re-sort the current items.

        Args:
            order: Sort order ("name" or "date")

        """
        if order not in ("name", "date"):
            self.logger.warning(f"Invalid sort order '{order}', ignoring")
            return

        if self._sort_order == order:
            return  # No change needed

        self._sort_order = order

        # Re-sort existing items
        if self._items:
            self.layoutAboutToBeChanged.emit()
            self._items = self._apply_sort(self._items)
            self.layoutChanged.emit()
            self.logger.info(f"Re-sorted {len(self._items)} items by {order}")

    def get_sort_order(self) -> str:
        """Get the current sort order.

        Returns:
            Current sort order ("name" or "date")

        """
        return self._sort_order
