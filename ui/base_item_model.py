"""Base Qt Model implementation for item data using QAbstractListModel.

This module provides a base implementation that extracts common functionality
from ShotItemModel, ThreeDEItemModel, and PreviousShotsItemModel, reducing
code duplication by ~70-80%.
"""

from __future__ import annotations

# Standard library imports
from abc import ABC
from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar, cast


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache
    from cache.thumbnail_loader import LoadingState, ThumbnailLoader
    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager

# Third-party imports
from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QMutexLocker,
    QObject,
    QPersistentModelIndex,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QIcon, QPixmap

# Local application imports
from config import Config
from logging_mixin import LoggingMixin, get_module_logger
from protocols import SceneDataProtocol
from qt_abc_meta import QABCMeta
from typing_compat import override
from ui.qt_widget_mixin import require_main_thread


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
    IsHiddenRole = Qt.ItemDataRole.UserRole + 25  # Whether shot is hidden


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
    items_updated: ClassVar[Signal] = Signal()  # Emitted when items list changes
    thumbnail_loaded: ClassVar[Signal] = Signal(int)  # row index
    show_filter_changed: ClassVar[Signal] = Signal(str)  # show name or "All Shows"

    @require_main_thread
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
        super().__init__(parent)

        # Core data storage
        self._items: list[T] = []
        self._sort_order: str = "date"
        if cache_manager is None:
            from cache.thumbnail_cache import make_default_thumbnail_cache
            cache_manager = make_default_thumbnail_cache()
        self._cache_manager: ThumbnailCache = cache_manager

        # Track visible range for lazy loading
        self._visible_start: int = 0
        self._visible_end: int = 0

        # Shared pin/notes managers (used by Shot-based subclasses)
        self._pin_manager: ShotPinManager | None = None
        self._notes_manager: NotesManager | None = None

        # Thumbnail subsystem — owns all async loading state and timers
        from cache.thumbnail_loader import ThumbnailLoader as _ThumbnailLoader
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
            with QMutexLocker(self._thumbnail_loader.cache_mutex):
                return self._thumbnail_loader.loading_states.get(item.full_name, "idle")

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

        # Handle loading state
        if role == BaseItemRole.LoadingStateRole:
            with QMutexLocker(self._thumbnail_loader.cache_mutex):
                self._thumbnail_loader.loading_states[item.full_name] = cast(
                    "LoadingState", str(value) if value is not None else "idle"
                )
            self.dataChanged.emit(index, index, [BaseItemRole.LoadingStateRole])
            return True

        # Let subclass handle model-specific data setting
        return self.set_custom_data(item, value, role)

    @Slot(int, int)  # pyright: ignore[reportAny]  # PySide6 Slot decorator type limitation
    def set_visible_range(self, start: int, end: int) -> None:
        """Set the visible range for lazy loading.

        Args:
            start: Start index
            end: End index

        """
        self._visible_start = max(0, start)
        self._visible_end = min(len(self._items) - 1, end) if self._items else 0

        # Schedule debounced thumbnail check
        self._thumbnail_loader.thumbnail_debounce_timer.start()  # Restart delays execution

    def _load_visible_thumbnails(self) -> None:
        """Check if visible range changed and schedule actual load."""
        self._thumbnail_loader.load_visible_thumbnails()

    def _do_load_visible_thumbnails(self) -> None:
        """Actually load thumbnails for visible range."""
        self._thumbnail_loader.do_load_visible_thumbnails()  # pyright: ignore[reportAny]

    @require_main_thread
    def _get_thumbnail_pixmap(self, item: T) -> QPixmap | None:
        """Get cached thumbnail pixmap for an item.

        Thread-safe: Converts QImage to QPixmap in main thread for display.

        Args:
            item: Item object

        Returns:
            QPixmap converted from cached QImage or None

        Raises:
            RuntimeError: If called from non-main thread

        """
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

    @require_main_thread
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
            RuntimeError: If called outside Qt main thread

        """
        # CRITICAL: Stop timers FIRST (prevents callback races)
        if self._thumbnail_loader.thumbnail_debounce_timer.isActive():
            self._thumbnail_loader.thumbnail_debounce_timer.stop()

        # Build lookup set BEFORE model reset (exception safety)
        new_item_names = {item.full_name for item in items}

        # NOW safe to begin model reset
        self.beginResetModel()

        try:
            # Update items list (state modification inside try block)
            self._items = items

            # Acquire mutex ONLY for cache filtering (minimize hold time)
            with QMutexLocker(self._thumbnail_loader.cache_mutex):
                old_cache_size = len(self._thumbnail_loader.thumbnail_cache)

                # Filter thumbnail cache - preserve only items still present
                self._thumbnail_loader.thumbnail_cache = {
                    name: image
                    for name, image in self._thumbnail_loader.thumbnail_cache.items()
                    if name in new_item_names
                }

                # Filter loading states - preserve only items still present
                self._thumbnail_loader.loading_states = {
                    name: state
                    for name, state in self._thumbnail_loader.loading_states.items()
                    if name in new_item_names
                }

                new_cache_size = len(self._thumbnail_loader.thumbnail_cache)
            # QMutexLocker automatically releases lock here

            preserved = new_cache_size
            evicted = old_cache_size - new_cache_size

            self.logger.info(
                f"Model updated: {len(items)} items, thumbnails: {preserved} preserved, {evicted} evicted"
            )

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

    # ============= Shared shot-model methods =============

    def get_display_role_data(self, item: T) -> str:
        """Get display text for an item.

        Args:
            item: The item to get display text for

        Returns:
            Item's full name (show/sequence/shot)

        """
        return item.full_name

    def get_tooltip_data(self, item: T) -> str:
        """Get tooltip text for an item.

        Args:
            item: The item to get tooltip for

        Returns:
            Formatted tooltip with item details

        """
        return f"{item.show} / {item.sequence} / {item.shot}\n{item.workspace_path}"

    def set_shots(self, shots: list[T]) -> None:
        """Set the shots list.

        Args:
            shots: List of Shot objects

        """
        self.set_items(shots)

    def get_shot_at_index(self, index: QModelIndex) -> T | None:
        """Get shot at the given index.

        Args:
            index: Model index

        Returns:
            Shot object or None if invalid

        """
        return self.get_item_at_index(index)

    def _find_shot_by_full_name(self, full_name: str) -> tuple[T, int] | None:
        """Find a shot by its full name.

        Args:
            full_name: The full name to search for

        Returns:
            Tuple of (item, row_index) if found, None otherwise

        """
        for row, item in enumerate(self._items):
            if item.full_name == full_name:
                return (item, row)
        return None

    def set_pin_manager(self, pin_manager: ShotPinManager) -> None:
        """Set the pin manager.

        Args:
            pin_manager: Pin manager for tracking pinned shots

        """
        self._pin_manager = pin_manager

    def refresh_pin_order(self) -> None:
        """Re-sort shots to reflect pin changes.

        Note: With proxy models, call proxy.refresh_sort() instead.
        Kept for backward compatibility with tests.
        """

    @property
    def shots(self) -> list[T]:
        """Get shots list.

        Returns:
            List of Shot objects

        """
        return self._items

    # ============= Custom role hooks =============

    def get_custom_role_data(self, item: T, role: int) -> object | None:
        """Handle model-specific custom roles.

        Handles IsPinnedRole and HasNoteRole using the shared pin/notes managers.
        Override in subclasses to add additional model-specific roles; call
        super().get_custom_role_data(item, role) for unhandled roles.

        Args:
            item: The item
            role: The data role

        Returns:
            Data for the role or None

        """
        if role == BaseItemRole.IsPinnedRole:
            if self._pin_manager:
                return self._pin_manager.is_pinned(item)  # pyright: ignore[reportArgumentType]
            return False

        if role == BaseItemRole.HasNoteRole:
            if self._notes_manager:
                return self._notes_manager.has_note(item)  # pyright: ignore[reportArgumentType]
            return False

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

    # ============= Cleanup =============

    def cleanup(self) -> None:
        """Clean up shared resources before deletion.

        Stops the thumbnail loader and clears the thumbnail cache.
        Subclasses should call super().cleanup() then perform their own
        signal disconnections and additional teardown.
        """
        # Stop thumbnail loader timers
        if hasattr(self, "_thumbnail_loader"):
            self._thumbnail_loader.shutdown()

        # Clear caches
        self.clear_thumbnail_cache()

    @override
    def deleteLater(self) -> None:
        """Override deleteLater to ensure cleanup."""
        self.cleanup()
        super().deleteLater()
