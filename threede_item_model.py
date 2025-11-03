"""Qt Model/View implementation for 3DE Scene items.

This module provides a Qt Model implementation specifically for ThreeDEScene objects,
extending BaseItemModel with 3DE-specific behavior including loading states and progress tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, Signal

from base_item_model import BaseItemModel, BaseItemRole
from typing_compat import override


if TYPE_CHECKING:
    from cache_manager import CacheManager
    from threede_scene_model import ThreeDEScene, ThreeDESceneModel


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
        cache_manager: CacheManager | None = None,
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

        self.logger.info("ThreeDEItemModel initialized")

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

        # Legacy roles for backward compatibility
        elif role == (Qt.ItemDataRole.UserRole + 5):  # Legacy UserRole
            return item.user
        elif role == (Qt.ItemDataRole.UserRole + 6):  # Legacy ScenePathRole
            return item.scene_path
        elif role == (Qt.ItemDataRole.UserRole + 11):  # Legacy ModifiedTimeRole
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
            reset: If True, perform full model reset (default).
                   If False, incremental update (for future optimization)
        """
        if reset:
            self.set_items(scenes)
        else:
            # Incremental update (more complex, for future optimization)
            self.beginResetModel()
            self._items = list(scenes)
            self.endResetModel()
            self.scenes_updated.emit()
        self.logger.info(f"Set {len(scenes)} scenes in model")

    def set_show_filter(
        self, threede_scene_model: ThreeDESceneModel, show: str | None
    ) -> None:
        """Set show filter and update the model.

        Args:
            threede_scene_model: Model to get filtered scenes from
            show: Show name to filter by or None for all shows
        """
        # Set filter on the model
        threede_scene_model.set_show_filter(show)

        # Get filtered scenes and update our display
        filtered_scenes = threede_scene_model.get_filtered_scenes()
        self.set_scenes(filtered_scenes)

        # Emit filter changed signal for UI updates
        filter_display = show if show is not None else "All Shows"
        self.show_filter_changed.emit(filter_display)
        self.logger.info(
            f"Applied show filter: {filter_display}, {len(filtered_scenes)} scenes"
        )

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

    def set_selected(self, index: QModelIndex) -> None:
        """Set selected item with proper notification.

        Args:
            index: Index to select
        """
        # Convert to QPersistentModelIndex for proper comparison
        persistent_index = QPersistentModelIndex(index)
        if self._selected_index != persistent_index:
            # Clear old selection
            if self._selected_index.isValid():
                # QPersistentModelIndex automatically converts to QModelIndex when needed
                self.dataChanged.emit(
                    self._selected_index,
                    self._selected_index,
                    [BaseItemRole.IsSelectedRole],
                )

            # Set new selection
            self._selected_index = QPersistentModelIndex(index)
            if index.isValid():
                self.dataChanged.emit(index, index, [BaseItemRole.IsSelectedRole])
                self._selected_item = self.get_item_at_index(index)
            else:
                self._selected_item = None

            self.selection_changed.emit(index)

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
        # Stop timers
        if hasattr(self, "_thumbnail_timer"):
            self._thumbnail_timer.stop()
            self._thumbnail_timer.deleteLater()

        if hasattr(self, "_thumbnail_debounce_timer"):
            self._thumbnail_debounce_timer.stop()
            self._thumbnail_debounce_timer.deleteLater()

        # Clear caches
        self.clear_thumbnail_cache()

        # Clear selection
        self._selected_index = QPersistentModelIndex()

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
            self.selection_changed,
            self.loading_started,
            self.loading_progress,
            self.loading_finished,
        ]

        for signal in signals_to_disconnect:
            try:
                # Only disconnect if there are receivers
                # receivers(None) returns total count of all connections
                # Note: Qt's receivers() method is not properly typed in PySide6 stubs
                if signal.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                    _ = signal.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass  # Already disconnected, no connections, or object deleted

        self.logger.info("ThreeDEItemModel cleanup complete")

    @override
    def deleteLater(self) -> None:
        """Override deleteLater to ensure cleanup."""
        self.cleanup()
        super().deleteLater()
