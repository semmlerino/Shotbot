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
    from base_shot_model import BaseShotModel
    from cache_manager import CacheManager
    from type_definitions import RefreshResult
    from notes_manager import NotesManager
    from pin_manager import PinManager
    from shot_model import Shot


class ShotItemModel(BaseItemModel["Shot"]):
    """Qt Model implementation for Shot items.

    Provides Model/View architecture for displaying shots in a grid view,
    with lazy thumbnail loading, selection management, and show filtering.
    """

    # Shot-specific signals
    shots_updated: Signal = Signal()  # Emitted when shots list changes
    show_filter_changed: Signal = Signal(
        str
    )  # Emitted when show filter changes (show name or "All Shows")

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        pin_manager: PinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the shot item model.

        Args:
            cache_manager: Optional cache manager for thumbnails
            pin_manager: Optional pin manager for tracking pinned shots
            notes_manager: Optional notes manager for tracking shot notes
            parent: Optional parent QObject

        """
        super().__init__(cache_manager, parent)

        self._pin_manager: PinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager

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

        return None

    # ============= Shot-specific methods =============

    def set_shots(self, shots: list[Shot]) -> None:
        """Set the shots list.

        Sorts shots with pinned shots first (by pin order), then unpinned
        shots alphabetically.

        Args:
            shots: List of Shot objects

        """
        if self._pin_manager:
            # Sort: pinned first (by pin order), then unpinned (alphabetically)
            def sort_key(s: Shot) -> tuple[bool, int, str]:
                is_pinned = self._pin_manager.is_pinned(s)  # type: ignore[union-attr]
                pin_order = (
                    self._pin_manager.get_pin_order(s)  # type: ignore[union-attr]
                    if is_pinned
                    else 999999
                )
                return (not is_pinned, pin_order, s.full_name.lower())

            sorted_shots = sorted(shots, key=sort_key)
        else:
            # Fallback: alphabetical sorting only
            sorted_shots = sorted(shots, key=lambda s: s.full_name.lower())

        self.set_items(sorted_shots)

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

    def get_selected_shot(self) -> Shot | None:
        """Get currently selected shot.

        Returns:
            Selected Shot or None

        """
        return self.get_selected_item()

    def set_show_filter(self, shot_model: BaseShotModel, show: str | None) -> None:
        """Set show filter and update the model.

        Args:
            shot_model: Shot model to get filtered shots from
            show: Show name to filter by or None for all shows

        """
        # Set filter on the shot model
        shot_model.set_show_filter(show)

        # Get filtered shots and update our display
        filtered_shots = shot_model.get_filtered_shots()
        self.set_shots(filtered_shots)

        # Emit filter changed signal for UI updates
        filter_display = show if show is not None else "All Shows"
        self.show_filter_changed.emit(filter_display)
        self.logger.info(
            f"Applied show filter: {filter_display}, {len(filtered_shots)} shots"
        )

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

    def refresh_pin_order(self) -> None:
        """Re-sort shots to reflect pin changes.

        Call this after pinning/unpinning to update the display order.
        """
        if self._items:
            # Re-sort with current items
            self.set_shots(list(self._items))

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
        from PySide6.QtCore import QPersistentModelIndex

        self._selected_index: QPersistentModelIndex = QPersistentModelIndex()

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
