"""Thumbnail loading subsystem extracted from BaseItemModel.

Owns all thumbnail state and async loading logic so that BaseItemModel
can focus on the Qt model protocol methods.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, Literal, TypeVar


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache

from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QImage, QPixmap

from config import Config
from logging_mixin import LoggingMixin, get_module_logger
from protocols import SceneDataProtocol
from typing_compat import override


_logger = get_module_logger(__name__)

T = TypeVar("T", bound=SceneDataProtocol)

LoadingState = Literal["idle", "loading", "loaded", "failed"]


from workers.runnable_tracker import TrackedQRunnable


class _ThumbnailLoaderSignals(QObject):
    finished: ClassVar[Signal] = Signal(str, Path)
    failed: ClassVar[Signal] = Signal(str)


class _ThumbnailLoaderRunnable(TrackedQRunnable):
    def __init__(
        self,
        full_name: str,
        thumbnail_path: Path,
        show: str,
        sequence: str,
        shot: str,
        cache_manager: ThumbnailCache,
    ) -> None:
        super().__init__(auto_delete=False)
        self.full_name: str = full_name
        self.thumbnail_path: Path = thumbnail_path
        self.show: str = show
        self.sequence: str = sequence
        self.shot: str = shot
        self.cache_manager: ThumbnailCache = cache_manager
        self.signals: _ThumbnailLoaderSignals = _ThumbnailLoaderSignals()

    @override
    def _do_work(self) -> None:
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


class ThumbnailLoader(QObject, LoggingMixin, Generic[T]):
    """Owns all thumbnail state and async loading logic.

    Receives callable injections so it has no direct reference to the model.
    Emits data_changed with a dict[int, set[int]] mapping row -> set of role ints
    when batched thumbnail updates are ready.
    """

    THUMBNAIL_DEBOUNCE_MS: ClassVar[int] = 250
    BATCH_WINDOW_MS: ClassVar[int] = 10

    data_changed: ClassVar[Signal] = Signal(object)
    thumbnail_ready: ClassVar[Signal] = Signal(int)  # row index, emitted immediately

    def __init__(
        self,
        cache_manager: ThumbnailCache,
        get_items: Callable[[], list[T]],
        get_visible_range: Callable[[], tuple[int, int]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._cache_manager: ThumbnailCache = cache_manager
        self._get_items: Callable[[], list[T]] = get_items
        self._get_visible_range: Callable[[], tuple[int, int]] = get_visible_range

        self._thumbnail_cache: dict[str, QImage] = {}
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._loading_states: dict[str, LoadingState] = {}
        self._cache_mutex: QMutex = QMutex()

        self._thumbnail_pool: QThreadPool = QThreadPool.globalInstance()
        self._pending_loads: set[str] = set()
        self._pending_loads_mutex: QMutex = QMutex()
        self._active_runnables: dict[str, _ThumbnailLoaderRunnable] = {}

        self._last_visible_range: tuple[int, int] = (-1, -1)
        self._thumbnail_debounce_timer: QTimer = QTimer(self)
        self._thumbnail_debounce_timer.setSingleShot(True)
        self._thumbnail_debounce_timer.setInterval(self.THUMBNAIL_DEBOUNCE_MS)
        _ = self._thumbnail_debounce_timer.timeout.connect(self.load_visible_thumbnails)

        self._pending_updates: dict[int, set[int]] = {}
        self._batch_timer: QTimer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.setInterval(self.BATCH_WINDOW_MS)
        _ = self._batch_timer.timeout.connect(self._emit_batched_updates)

    # ============= Public accessors for BaseItemModel forwarding properties =============
    # BaseItemModel exposes these attributes on itself for test/subclass access.

    @property
    def thumbnail_cache(self) -> dict[str, QImage]:
        """The in-memory QImage cache."""
        return self._thumbnail_cache

    @thumbnail_cache.setter
    def thumbnail_cache(self, value: dict[str, QImage]) -> None:
        self._thumbnail_cache = value

    @property
    def pixmap_cache(self) -> dict[str, QPixmap]:
        """The converted QPixmap cache."""
        return self._pixmap_cache

    @pixmap_cache.setter
    def pixmap_cache(self, value: dict[str, QPixmap]) -> None:
        self._pixmap_cache = value

    @property
    def loading_states(self) -> dict[str, LoadingState]:
        """Per-item loading state strings."""
        return self._loading_states

    @loading_states.setter
    def loading_states(self, value: dict[str, LoadingState]) -> None:
        self._loading_states = value

    @property
    def cache_mutex(self) -> QMutex:
        """Mutex guarding the thumbnail/pixmap/loading_states dicts."""
        return self._cache_mutex

    @property
    def thumbnail_debounce_timer(self) -> QTimer:
        """Timer that debounces visible-range thumbnail checks."""
        return self._thumbnail_debounce_timer

    @property
    def pending_updates(self) -> dict[int, set[int]]:
        """Pending batched data-changed updates."""
        return self._pending_updates

    @property
    def batch_timer(self) -> QTimer:
        """Timer that batches data-changed emissions."""
        return self._batch_timer

    def get_pixmap(self, item: T) -> QPixmap | None:
        with QMutexLocker(self._cache_mutex):
            pixmap = self._pixmap_cache.get(item.full_name)
            if pixmap:
                return pixmap
            qimage = self._thumbnail_cache.get(item.full_name)

        if qimage:
            pixmap = QPixmap.fromImage(qimage)
            with QMutexLocker(self._cache_mutex):
                self._pixmap_cache[item.full_name] = pixmap
            return pixmap
        return None

    def get_loading_state(self, full_name: str) -> LoadingState:
        with QMutexLocker(self._cache_mutex):
            return self._loading_states.get(full_name, "idle")

    def clear_thumbnail_cache(self) -> None:
        with QMutexLocker(self._cache_mutex):
            self._thumbnail_cache.clear()
            self._pixmap_cache.clear()
            self._loading_states.clear()

    def load_visible_thumbnails(self) -> None:
        visible_range = self._get_visible_range()

        if visible_range == self._last_visible_range:
            self.logger.debug(
                f"load_visible_thumbnails: range unchanged ({visible_range[0]}-{visible_range[1]}), skipping"
            )
            return

        self._last_visible_range = visible_range
        self.do_load_visible_thumbnails()

    def do_load_visible_thumbnails(self) -> None:
        visible_start, visible_end = self._get_visible_range()
        items = self._get_items()

        buffer_size = 5
        start = max(0, visible_start - buffer_size)
        end = min(len(items), visible_end + buffer_size)

        if items:
            self.logger.debug(
                f"do_load_visible_thumbnails: checking {end - start} items (range {start}-{end}, total items: {len(items)})"
            )

        items_to_load: list[tuple[int, T]] = []

        with QMutexLocker(self._cache_mutex):
            for row in range(start, end):
                item = items[row]

                if item.full_name in self._thumbnail_cache:
                    continue

                state = self._loading_states.get(item.full_name)
                if state in ("loading", "failed"):
                    continue

                self._loading_states[item.full_name] = "loading"
                items_to_load.append((row, item))

        for row, item in items_to_load:
            self.logger.debug(
                f"Starting thumbnail load for item {row}: {item.full_name}"
            )
            self._load_thumbnail_async(row, item)

    def _load_thumbnail_async(self, row: int, item: T) -> None:
        from ui.base_item_model import BaseItemRole

        self._schedule_data_changed(row, [BaseItemRole.LoadingStateRole])

        thumbnail_path = item.get_thumbnail_path()
        if thumbnail_path and thumbnail_path.exists():
            with QMutexLocker(self._pending_loads_mutex):
                if item.full_name in self._pending_loads:
                    return
                self._pending_loads.add(item.full_name)

            runnable = _ThumbnailLoaderRunnable(
                item.full_name,
                thumbnail_path,
                item.show,
                item.sequence,
                item.shot,
                self._cache_manager,
            )

            with QMutexLocker(self._pending_loads_mutex):
                self._active_runnables[item.full_name] = runnable

            def on_finished(name: str, path: Path, captured_row: int = row) -> None:
                try:
                    self._on_thumbnail_loaded(name, path, captured_row)
                except RuntimeError:
                    pass  # ThumbnailLoader deleted before callback fired

            def on_failed(name: str, captured_row: int = row) -> None:
                try:
                    self._on_thumbnail_failed(name, captured_row)
                except RuntimeError:
                    pass  # ThumbnailLoader deleted before callback fired

            _ = runnable.signals.finished.connect(
                on_finished,
                Qt.ConnectionType.QueuedConnection,
            )
            _ = runnable.signals.failed.connect(
                on_failed,
                Qt.ConnectionType.QueuedConnection,
            )

            self._thumbnail_pool.start(runnable)
        else:
            with QMutexLocker(self._cache_mutex):
                self._loading_states[item.full_name] = "failed"
            self._schedule_data_changed(row, [BaseItemRole.LoadingStateRole])

    def _cleanup_thumbnail_load(self, full_name: str) -> None:
        with QMutexLocker(self._pending_loads_mutex):
            _ = self._active_runnables.pop(full_name, None)
            self._pending_loads.discard(full_name)

    def _on_thumbnail_loaded(self, full_name: str, cached_path: Path, row: int) -> None:
        self._cleanup_thumbnail_load(full_name)

        items = self._get_items()
        if row >= len(items):
            return
        item = items[row]
        if item.full_name != full_name:
            for i, it in enumerate(items):
                if it.full_name == full_name:
                    row = i
                    item = it
                    break
            else:
                return

        self._load_cached_pixmap(cached_path, row, item)

    def _on_thumbnail_failed(self, full_name: str, row: int) -> None:
        self._cleanup_thumbnail_load(full_name)

        with QMutexLocker(self._cache_mutex):
            self._loading_states[full_name] = "failed"

        from ui.base_item_model import BaseItemRole

        items = self._get_items()
        if row < len(items):
            self._schedule_data_changed(row, [BaseItemRole.LoadingStateRole])

    def _load_cached_pixmap(self, cached_path: Path, row: int, item: T) -> None:
        from ui.base_item_model import BaseItemRole

        pixmap = QPixmap(str(cached_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                Config.DEFAULT_THUMBNAIL_SIZE,
                Config.DEFAULT_THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            with QMutexLocker(self._cache_mutex):
                self._thumbnail_cache[item.full_name] = pixmap.toImage()
                self._loading_states[item.full_name] = "loaded"
            self.logger.debug(f"Loaded thumbnail for {item.full_name} from cache")

            self._schedule_data_changed(
                row,
                [
                    BaseItemRole.ThumbnailPixmapRole,
                    BaseItemRole.LoadingStateRole,
                    Qt.ItemDataRole.DecorationRole,
                ],
            )
            self.thumbnail_ready.emit(row)
        else:
            self.logger.warning(
                f"Failed to load cached thumbnail pixmap from {cached_path}"
            )
            with QMutexLocker(self._cache_mutex):
                self._loading_states[item.full_name] = "failed"
            self._schedule_data_changed(row, [BaseItemRole.LoadingStateRole])

    def _schedule_data_changed(self, row: int, roles: list[int]) -> None:
        if row not in self._pending_updates:
            self._pending_updates[row] = set()
        self._pending_updates[row].update(roles)

        try:
            self._batch_timer.start()
        except RuntimeError:
            pass

    def _emit_batched_updates(self) -> None:
        if not self._pending_updates:
            return

        updates = self._pending_updates.copy()
        self._pending_updates.clear()
        self.data_changed.emit(updates)

    def shutdown(self) -> None:
        try:
            self._thumbnail_debounce_timer.stop()
        except RuntimeError:
            pass
        try:
            self._batch_timer.stop()
        except RuntimeError:
            pass
