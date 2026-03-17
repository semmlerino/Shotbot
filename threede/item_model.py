"""Qt Model/View implementation for 3DE Scene items.

This module provides a Qt Model implementation specifically for ThreeDEScene objects,
extending BaseItemModel with 3DE-specific behavior including loading states and progress tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from PySide6.QtCore import QModelIndex, QObject, Signal

from typing_compat import override
from ui.base_item_model import BaseItemModel


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache
    from type_definitions import ThreeDEScene


@final
class ThreeDEItemModel(BaseItemModel["ThreeDEScene"]):
    """Qt Model implementation for 3DE Scene items.

    Provides Model/View architecture for displaying 3DE scenes in a grid view,
    with lazy thumbnail loading, selection management, loading progress tracking,
    and show filtering.
    """

    # ThreeDEScene-specific signals
    scenes_updated = Signal()  # Emitted when scenes list changes
    loading_started = Signal()  # Emitted when scene loading starts
    loading_progress = Signal(int, int)  # current, total
    loading_finished = Signal()  # Emitted when scene loading completes

    def __init__(
        self,
        cache_manager: ThumbnailCache | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the 3DE item model.

        Args:
            cache_manager: Optional cache manager for thumbnails
            parent: Optional parent QObject

        """
        super().__init__(cache_manager, parent)

        # ThreeDEScene-specific state
        self._is_loading = False
        self._updating_filter = False  # Recursion guard for filter updates

        # Connect generic items_updated to scene-specific signal
        _ = self.items_updated.connect(self.scenes_updated)

        self.logger.debug("ThreeDEItemModel initialized")

    # ============= Implement abstract methods =============

    @override
    def get_display_role_data(self, item: ThreeDEScene) -> str:
        """Get display text for a 3DE scene.

        Args:
            item: The scene to get display text for

        Returns:
            Scene's full name

        """
        return item.full_name

    @override
    def get_tooltip_data(self, item: ThreeDEScene) -> str:
        """Get tooltip text for a 3DE scene.

        Args:
            item: The scene to get tooltip for

        Returns:
            Formatted tooltip with scene details

        """
        tooltip = f"Scene: {item.shot}\n"
        tooltip += f"User: {item.user}\n"
        tooltip += f"Path: {item.scene_path}"
        return tooltip

    @override
    def get_custom_role_data(self, item: ThreeDEScene, role: int) -> object:
        """Handle 3DE scene-specific custom roles.

        Args:
            item: The scene
            role: The data role

        Returns:
            Data for the role or None

        """
        # ThreeDEScene-specific roles using Qt.ItemDataRole.UserRole offsets
        from PySide6.QtCore import Qt

        if role == (Qt.ItemDataRole.UserRole + 20):  # ItemSpecificRole1
            # Return shot name
            return item.shot
        if role == (Qt.ItemDataRole.UserRole + 21):  # ItemSpecificRole2
            # Return user
            return item.user
        if role == (Qt.ItemDataRole.UserRole + 22):  # ItemSpecificRole3
            # Return scene path
            return item.scene_path
        if role == (Qt.ItemDataRole.UserRole + 23):  # ModifiedTimeRole
            # Return modification time
            scene_path = item.scene_path
            try:
                return float(scene_path.stat().st_mtime)
            except OSError:
                return 0.0

        return None

    # ============= 3DE Scene-specific methods =============

    def set_scenes(self, scenes: list[ThreeDEScene], reset: bool = True) -> None:
        """Set the scenes list.

        Args:
            scenes: List of ThreeDEScene objects
            reset: Kept for API compatibility; always performs a full model reset.

        """
        _ = reset  # Kept for API compat
        self.set_items(scenes)
        self.logger.info(f"Set {len(scenes)} scenes in model")



    def get_scene(self, index: QModelIndex) -> ThreeDEScene | None:
        """Get scene at the given index.

        Args:
            index: Model index

        Returns:
            ThreeDEScene object or None if invalid

        """
        return self.get_item_at_index(index)

    def set_loading_state(self, loading: bool) -> None:
        """Set loading state.

        Args:
            loading: Whether loading is in progress

        """
        self._is_loading = loading
        if loading:
            self.loading_started.emit()
        else:
            self.loading_finished.emit()

    def update_loading_progress(self, current: int, total: int) -> None:
        """Update loading progress.

        Args:
            current: Current item being loaded
            total: Total items to load

        """
        self.loading_progress.emit(current, total)

    # ============= Properties =============

    @property
    def scenes(self) -> list[ThreeDEScene]:
        """Get scenes list.

        Returns:
            List of ThreeDEScene objects

        """
        return self._items

    @property
    def is_loading(self) -> bool:
        """Check if loading is in progress.

        Returns:
            True if loading, False otherwise

        """
        return self._is_loading

    # ============= Cleanup =============

    def cleanup(self) -> None:
        """Clean up resources before deletion."""
        # Stop thumbnail loader timers
        if hasattr(self, "_thumbnail_loader"):
            self._thumbnail_loader.shutdown()

        # Clear caches
        self.clear_thumbnail_cache()

        # Disconnect signals safely
        # Note: We check receivers() before disconnecting to avoid RuntimeWarnings
        # from Qt when attempting to disconnect signals that have no connections.
        # This is especially important during testing where models may be created
        # without any connected slots.
        # Qt's receivers() method is not properly typed in PySide6 stubs
        signals_to_disconnect = [
            self.items_updated,
            self.scenes_updated,
            self.thumbnail_loaded,
            self.loading_started,
            self.loading_progress,
            self.loading_finished,
        ]

        for signal in signals_to_disconnect:
            try:
                # Only disconnect if there are receivers
                # receivers(None) returns total count of all connections
                # Note: Qt's receivers() method is not properly typed in PySide6 stubs
                if signal.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                    _ = signal.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass  # Already disconnected, no connections, or object deleted

        self.logger.debug("ThreeDEItemModel cleanup complete")

    @override
    def deleteLater(self) -> None:
        """Override deleteLater to ensure cleanup."""
        self.cleanup()
        super().deleteLater()
