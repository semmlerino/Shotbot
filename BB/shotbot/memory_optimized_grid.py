"""Memory-optimized grid base class with viewport-based thumbnail loading.

DEPRECATED: This module is deprecated and will be removed in a future version.
The Model/View architecture provides superior memory optimization through
virtualization and delegate-based rendering, eliminating the need for
manual viewport management and widget lifecycle tracking.

Use shot_grid_view.py and shot_item_model.py instead.
"""

from dataclasses import dataclass
from typing import Dict, Set, Tuple, Union

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QScrollArea, QWidget

from config import Config
from shot_model import Shot
from threede_scene_model import ThreeDEScene
from threede_thumbnail_widget import ThreeDEThumbnailWidget
from thumbnail_widget import ThumbnailWidget


@dataclass
class ThumbnailPlaceholder:
    """Placeholder for unloaded thumbnails."""

    index: int
    row: int
    col: int
    data: Union[Shot, ThreeDEScene]


class MemoryOptimizedGrid:
    """Base class for memory-optimized grid implementations.

    Features:
    - Viewport-based loading: Only loads thumbnails visible in viewport
    - Memory management: Unloads thumbnails when scrolled out of view
    - Lazy loading: Defers thumbnail creation until needed
    - Memory limits: Enforces maximum loaded thumbnails
    """

    # Configuration from Config class
    MAX_LOADED_THUMBNAILS = Config.MAX_LOADED_THUMBNAILS
    VIEWPORT_BUFFER = Config.VIEWPORT_BUFFER_ROWS
    UNLOAD_DELAY_MS = Config.THUMBNAIL_UNLOAD_DELAY_MS

    def __init__(self):
        """Initialize memory optimization components."""
        # Loaded thumbnails
        self._loaded_thumbnails: Dict[
            str, Union[ThumbnailWidget, ThreeDEThumbnailWidget]
        ] = {}

        # Placeholders for all items
        self._placeholders: Dict[str, ThumbnailPlaceholder] = {}

        # Track visible indices
        self._visible_indices: Set[int] = set()

        # Unload timer
        self._unload_timer = QTimer()
        self._unload_timer.timeout.connect(self._unload_invisible_thumbnails)
        self._unload_timer.setSingleShot(True)

        # Viewport tracking
        self._last_viewport = QRect()

        # Thumbnail size (to be set by subclass)
        self._thumbnail_size: int = Config.DEFAULT_THUMBNAIL_SIZE

    def _get_item_key(self, item: Union[Shot, ThreeDEScene]) -> str:
        """Get unique key for an item."""
        if isinstance(item, Shot):
            return item.full_name
        else:
            return item.display_name

    def _create_thumbnail(
        self, item: Union[Shot, ThreeDEScene], size: int
    ) -> Union[ThumbnailWidget, ThreeDEThumbnailWidget]:
        """Create appropriate thumbnail widget for item."""
        if isinstance(item, Shot):
            return ThumbnailWidget(item, size)
        else:
            return ThreeDEThumbnailWidget(item, size)

    def _setup_viewport_tracking(self, scroll_area: QScrollArea):
        """Set up viewport change tracking."""
        # Connect to scrollbar changes
        scroll_area.horizontalScrollBar().valueChanged.connect(
            self._on_viewport_changed
        )
        scroll_area.verticalScrollBar().valueChanged.connect(self._on_viewport_changed)

    def _on_viewport_changed(self):
        """Handle viewport changes."""
        # Update visible thumbnails
        self._update_visible_thumbnails()

        # Reset unload timer
        self._unload_timer.stop()
        self._unload_timer.start(self.UNLOAD_DELAY_MS)

    def _get_visible_range(
        self, scroll_area: QScrollArea, grid_columns: int, total_items: int
    ) -> Tuple[int, int]:
        """Calculate range of visible item indices."""
        if total_items == 0:
            return (0, 0)

        # Get viewport rectangle
        viewport = scroll_area.viewport()
        viewport_rect = viewport.rect()

        # Get scroll position
        scroll_x = scroll_area.horizontalScrollBar().value()
        scroll_y = scroll_area.verticalScrollBar().value()

        # Create visible rect in container coordinates
        visible_rect = QRect(
            scroll_x, scroll_y, viewport_rect.width(), viewport_rect.height()
        )

        # Calculate visible rows
        item_height = self._thumbnail_size + Config.THUMBNAIL_SPACING
        top_row = max(0, visible_rect.top() // item_height - self.VIEWPORT_BUFFER)
        bottom_row = (visible_rect.bottom() // item_height) + self.VIEWPORT_BUFFER

        # Convert to indices
        start_idx = top_row * grid_columns
        end_idx = min((bottom_row + 1) * grid_columns, total_items)

        return (start_idx, end_idx)

    def _update_visible_thumbnails(self) -> None:
        """Update which thumbnails are loaded based on viewport."""
        # This method should be implemented by subclasses
        raise NotImplementedError(
            "Subclasses must implement _update_visible_thumbnails"
        )

    def _load_thumbnail_at_index(self, index: int) -> None:
        """Load thumbnail at specific index."""
        # This method should be implemented by subclasses
        raise NotImplementedError("Subclasses must implement _load_thumbnail_at_index")

    def _unload_thumbnail(self, key: str):
        """Unload a thumbnail to free memory."""
        if key in self._loaded_thumbnails:
            thumbnail = self._loaded_thumbnails[key]

            # Remove from grid layout (implemented by subclass)
            self._remove_from_grid(thumbnail)

            # Clean up widget
            thumbnail.deleteLater()

            # Remove from loaded dict
            del self._loaded_thumbnails[key]

    def _remove_from_grid(self, widget: QWidget) -> None:
        """Remove widget from grid layout."""
        # This method should be implemented by subclasses
        raise NotImplementedError("Subclasses must implement _remove_from_grid")

    def _unload_invisible_thumbnails(self):
        """Unload thumbnails that are no longer visible."""
        # Get current visible indices from subclass
        visible_indices = self._get_current_visible_indices()

        # Find thumbnails to unload
        keys_to_unload: list[str] = []
        for key, placeholder in self._placeholders.items():
            if (
                placeholder.index not in visible_indices
                and key in self._loaded_thumbnails
            ):
                keys_to_unload.append(key)

        # Respect memory limit
        current_count = len(self._loaded_thumbnails)
        if current_count > self.MAX_LOADED_THUMBNAILS:
            # Sort by distance from viewport center
            viewport_center = (
                (min(visible_indices) + max(visible_indices)) // 2
                if visible_indices
                else 0
            )
            keys_to_unload.sort(
                key=lambda k: abs(self._placeholders[k].index - viewport_center),
                reverse=True,
            )

            # Unload furthest thumbnails first
            for key in keys_to_unload[: current_count - self.MAX_LOADED_THUMBNAILS]:
                self._unload_thumbnail(key)

    def _get_current_visible_indices(self) -> Set[int]:
        """Get currently visible indices."""
        # This method should be implemented by subclasses
        raise NotImplementedError(
            "Subclasses must implement _get_current_visible_indices"
        )

    def _create_placeholder_widget(self, row: int, col: int) -> QWidget:
        """Create a placeholder widget for unloaded thumbnail position."""
        placeholder = QWidget()
        placeholder.setFixedSize(self._thumbnail_size, self._thumbnail_size)
        placeholder.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        return placeholder

    def get_memory_usage(self) -> Dict[str, int]:
        """Get current memory usage statistics."""
        return {
            "loaded_thumbnails": len(self._loaded_thumbnails),
            "total_items": len(self._placeholders),
            "max_allowed": self.MAX_LOADED_THUMBNAILS,
            "visible_count": len(self._visible_indices),
        }
