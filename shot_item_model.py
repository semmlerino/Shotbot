"""Qt Model/View implementation for Shot items.

This module provides a Qt Model implementation specifically for Shot objects,
extending BaseItemModel with shot-specific behavior.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QObject, Signal

from base_item_model import BaseItemModel
from typing_compat import override


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache
    from hide_manager import HideManager
    from notes_manager import NotesManager
    from pin_manager import PinManager
    from shot_model import Shot
    from type_definitions import RefreshResult


class ShotItemModel(BaseItemModel["Shot"]):
    """Qt Model implementation for Shot items.

    Provides Model/View architecture for displaying shots in a grid view,
    with lazy thumbnail loading, selection management, and show filtering.
    """

    # Shot-specific signals
    shots_updated: Signal = Signal()  # Emitted when shots list changes

    def __init__(
        self,
        cache_manager: ThumbnailCache | None = None,
        pin_manager: PinManager | None = None,
        notes_manager: NotesManager | None = None,
        hide_manager: HideManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the shot item model.

        Args:
            cache_manager: Optional cache manager for thumbnails
            pin_manager: Optional pin manager for tracking pinned shots
            notes_manager: Optional notes manager for tracking shot notes
            hide_manager: Optional hide manager for tracking hidden shots
            parent: Optional parent QObject

        """
        super().__init__(cache_manager, parent)

        self._pin_manager: PinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager
        self._hide_manager: HideManager | None = hide_manager

        # Connect generic items_updated to shot-specific signal
        _ = self.items_updated.connect(self.shots_updated)

        self.logger.debug("ShotItemModel initialized")

    # ============= Implement abstract methods =============

    @override
    def get_display_role_data(self, item: Shot) -> str:
        """Get display text for a shot.

        Args:
            item: The shot to get display text for

        Returns:
            Shot's full name (show/sequence/shot)

        """
        return item.full_name

    @override
    def get_tooltip_data(self, item: Shot) -> str:
        """Get tooltip text for a shot.

        Args:
            item: The shot to get tooltip for

        Returns:
            Formatted tooltip with shot details

        """
        return f"{item.show} / {item.sequence} / {item.shot}\n{item.workspace_path}"

    @override
    def get_custom_role_data(self, item: Shot, role: int) -> object:
        """Handle shot-specific custom roles.

        Args:
            item: The shot
            role: The data role

        Returns:
            Data for the role or None

        """
        from base_item_model import BaseItemRole

        if role == BaseItemRole.IsPinnedRole:
            if self._pin_manager:
                return self._pin_manager.is_pinned(item)
            return False

        if role == BaseItemRole.HasNoteRole:
            if self._notes_manager:
                return self._notes_manager.has_note(item)
            return False

        if role == BaseItemRole.FrameRangeRole:
            return item.frame_range_display

        if role == BaseItemRole.IsHiddenRole:
            if self._hide_manager:
                return self._hide_manager.is_hidden(item)
            return False

        return None

    # ============= Shot-specific methods =============

    def set_shots(self, shots: list[Shot]) -> None:
        """Set the shots list.

        Args:
            shots: List of Shot objects

        """
        self.set_items(shots)

    def set_show_filter(self, shot_model: object, show: str | None) -> None:
        """Apply show filter to item model (legacy compatibility).

        Note: In production, filtering is handled by ShotProxyModel.
        This method is retained for test compatibility with direct item model usage.

        Args:
            shot_model: Shot model to get filtered shots from (duck typed)
            show: Show name to filter by or None for all shows

        """
        # Apply filter on the underlying model (duck-typed)
        if hasattr(shot_model, "set_show_filter"):
            shot_model.set_show_filter(show)  # type: ignore[union-attr]

        # Get filtered shots (duck-typed)
        if hasattr(shot_model, "get_filtered_shots"):
            filtered_shots: list[Shot] = shot_model.get_filtered_shots()  # type: ignore[union-attr]
            self.set_items(filtered_shots)  # pyright: ignore[reportUnknownArgumentType]

        filter_display = show if show is not None else "All Shows"
        self.logger.info(f"Applied show filter (compat): {filter_display}")

    def refresh_shots(self, shots: list[Shot]) -> RefreshResult:
        """Refresh with new shots, detecting changes.

        Args:
            shots: New list of shots

        Returns:
            RefreshResult indicating success and whether changes occurred

        """
        # Compare with existing items
        old_names = {item.full_name for item in self._items}
        new_names = {shot.full_name for shot in shots}

        has_changes = old_names != new_names

        if has_changes:
            self.set_shots(shots)

        # Import here to avoid circular imports
        from type_definitions import RefreshResult

        return RefreshResult(success=True, has_changes=has_changes)

    def get_shot_at_index(self, index: QModelIndex) -> Shot | None:
        """Get shot at the given index.

        Args:
            index: Model index

        Returns:
            Shot object or None if invalid

        """
        return self.get_item_at_index(index)

    def _find_shot_by_full_name(self, full_name: str) -> tuple[Shot, int] | None:
        """Find a shot by its full name.

        Args:
            full_name: The full name to search for

        Returns:
            Tuple of (Shot, row_index) if found, None otherwise

        """
        for row, item in enumerate(self._items):
            if item.full_name == full_name:
                return (item, row)
        return None

    def set_pin_manager(self, pin_manager: PinManager) -> None:
        """Set the pin manager.

        Args:
            pin_manager: Pin manager for tracking pinned shots

        """
        self._pin_manager = pin_manager

    def set_hide_manager(self, hide_manager: HideManager) -> None:
        """Set the hide manager.

        Args:
            hide_manager: Hide manager for tracking hidden shots

        """
        self._hide_manager = hide_manager

    def refresh_pin_order(self) -> None:
        """Re-sort shots to reflect pin changes.

        Note: With proxy models, call proxy.refresh_sort() instead.
        Kept for backward compatibility with tests.
        """

    # ============= Properties =============

    @property
    def shots(self) -> list[Shot]:
        """Get shots list.

        Returns:
            List of Shot objects

        """
        return self._items

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
        # Qt's receivers() method is not properly typed in PySide6 stubs
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            if self.items_updated.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                _ = self.items_updated.disconnect()
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            if self.shots_updated.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                _ = self.shots_updated.disconnect()

        self.logger.debug("ShotItemModel cleanup complete")

    @override
    def deleteLater(self) -> None:
        """Override deleteLater to ensure cleanup."""
        self.cleanup()
        super().deleteLater()
