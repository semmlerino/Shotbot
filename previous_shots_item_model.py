"""Qt Model/View implementation for Previous Shots items.

This module provides a Qt Model implementation specifically for previous shots,
extending BaseItemModel with integration to PreviousShotsModel for data updates.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QObject, Qt, Signal

from base_item_model import BaseItemModel
from typing_compat import override


if TYPE_CHECKING:
    from cache_manager import CacheManager
    from notes_manager import NotesManager
    from pin_manager import PinManager
    from previous_shots_model import PreviousShotsModel
    from shot_model import Shot


class PreviousShotsItemModel(BaseItemModel["Shot"]):
    """Qt Model implementation for Previous Shots items.

    Provides Model/View architecture for displaying previously worked shots,
    with lazy thumbnail loading, selection management, and automatic updates
    from the underlying PreviousShotsModel.
    """

    # Previous shots-specific signals
    shots_updated: Signal = Signal()  # Emitted when shots list changes
    show_filter_changed: Signal = Signal(
        str
    )  # Emitted when show filter changes (show name or "All Shows")

    # Type annotation for inherited attribute (required for non-final classes)
    _items: list[Shot]

    def __init__(
        self,
        underlying_model: PreviousShotsModel,
        cache_manager: CacheManager | None = None,
        pin_manager: PinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the previous shots item model.

        Args:
            underlying_model: PreviousShotsModel instance providing shot data
            cache_manager: Optional cache manager for thumbnails
            pin_manager: Optional pin manager for tracking pinned shots
            notes_manager: Optional notes manager for tracking shot notes
            parent: Optional parent QObject

        """
        super().__init__(cache_manager, parent)

        self._underlying_model: PreviousShotsModel = underlying_model
        self._pin_manager: PinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager
        self._sort_order: str = "date"  # Default: newest first by discovered_at

        # Connect generic items_updated to shot-specific signal
        _ = self.items_updated.connect(self.shots_updated)

        # Connect to underlying model for automatic updates
        if hasattr(underlying_model, "shots_updated") and hasattr(
            underlying_model.shots_updated, "emit"
        ):
            # Real Qt signal - use QueuedConnection
            _ = underlying_model.shots_updated.connect(
                self._on_underlying_shots_updated,
                Qt.ConnectionType.QueuedConnection,
            )
        elif hasattr(underlying_model, "shots_updated"):
            # Test double - connect without ConnectionType
            _ = underlying_model.shots_updated.connect(self._on_underlying_shots_updated)

        # Initialize with current shots
        self._update_from_underlying_model()

        self.logger.debug("PreviousShotsItemModel initialized")

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
        # Import here to avoid circular dependency
        from base_item_model import BaseItemRole

        if role == BaseItemRole.IsPinnedRole:
            if self._pin_manager:
                return self._pin_manager.is_pinned(item)
            return False

        if role == BaseItemRole.HasNoteRole:
            if self._notes_manager:
                return self._notes_manager.has_note(item)
            return False

        # Handle item-specific roles for backward compatibility
        if role == BaseItemRole.ItemSpecificRole1:
            return item.shot  # Shot number/ID

        return None

    # ============= Previous shots-specific methods =============

    def set_shots(self, shots: list[Shot]) -> None:
        """Set the shots list.

        Args:
            shots: List of Shot objects

        """
        # Apply sorting before setting items
        sorted_shots = self._apply_sort(shots)
        self.set_items(sorted_shots)

    def _apply_sort(self, shots: list[Shot]) -> list[Shot]:
        """Apply current sort order to a list of shots.

        Pinned shots are always sorted to the front (by pin order),
        then unpinned shots are sorted by the current sort order.

        Args:
            shots: List of shots to sort

        Returns:
            Sorted list of shots

        """
        if self._pin_manager:
            # Sort: pinned first (by pin order), then unpinned (by sort order)
            def sort_key(s: Shot) -> tuple[bool, int, float | str]:
                is_pinned = self._pin_manager.is_pinned(s)  # type: ignore[union-attr]
                pin_order = (
                    self._pin_manager.get_pin_order(s)  # type: ignore[union-attr]
                    if is_pinned
                    else 999999
                )
                if self._sort_order == "name":
                    secondary: float | str = s.full_name.lower()
                else:
                    # "date" - use negative timestamp for newest first
                    secondary = -s.discovered_at
                return (not is_pinned, pin_order, secondary)

            return sorted(shots, key=sort_key)

        # No pin manager - use original sort logic
        if self._sort_order == "name":
            return sorted(shots, key=lambda s: s.full_name.lower())
        # "date" - newest first
        return sorted(shots, key=lambda s: s.discovered_at, reverse=True)

    def set_sort_order(self, order: str) -> None:
        """Set the sort order and re-sort the current shots.

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
            self.logger.info(f"Re-sorted {len(self._items)} shots by {order}")

    def get_sort_order(self) -> str:
        """Get the current sort order.

        Returns:
            Current sort order ("name" or "date")

        """
        return self._sort_order

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

    def set_show_filter(
        self, previous_shots_model: PreviousShotsModel, show: str | None
    ) -> None:
        """Set show filter and update the model.

        Args:
            previous_shots_model: Model to get filtered shots from
            show: Show name to filter by or None for all shows

        """
        # Set filter on the model
        previous_shots_model.set_show_filter(show)

        # Get filtered shots and update our display
        filtered_shots = previous_shots_model.get_filtered_shots()
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

    def _on_underlying_shots_updated(self) -> None:
        """Handle shots update from underlying model."""
        self._update_from_underlying_model()

    def _update_from_underlying_model(self) -> None:
        """Update items from underlying model."""
        new_shots = self._underlying_model.get_shots()
        # Apply sorting through set_shots()
        self.set_shots(new_shots)
        self.logger.debug(f"Updated with {len(new_shots)} previous shots (sorted by {self._sort_order})")

    def refresh(self) -> None:
        """Trigger refresh of underlying model."""
        _ = self._underlying_model.refresh_shots()

    def get_underlying_model(self) -> PreviousShotsModel:
        """Get underlying model.

        Returns:
            PreviousShotsModel instance

        """
        return self._underlying_model

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
        # Stop timers - wrap in try/except since C++ object may already be deleted
        if hasattr(self, "_thumbnail_timer"):
            try:
                self._thumbnail_timer.stop()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
                self._thumbnail_timer.deleteLater()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            except RuntimeError:
                pass  # Timer already deleted at C++ level

        if hasattr(self, "_thumbnail_debounce_timer"):
            try:
                self._thumbnail_debounce_timer.stop()
                self._thumbnail_debounce_timer.deleteLater()
            except RuntimeError:
                pass  # Timer already deleted at C++ level

        # Clear caches
        self.clear_thumbnail_cache()

        # Clear selection
        from PySide6.QtCore import QPersistentModelIndex

        self._selected_index: QPersistentModelIndex = QPersistentModelIndex()

        # Disconnect from underlying model
        # Use try/except pattern instead of receivers() check, as PySide6's
        # receivers() doesn't accept slot arguments.
        # Suppress RuntimeWarning that PySide6 emits when disconnecting signals
        # with no receivers connected.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            if hasattr(self._underlying_model, "shots_updated"):
                try:
                    _ = self._underlying_model.shots_updated.disconnect(
                        self._on_underlying_shots_updated
                    )
                except (RuntimeError, TypeError, AttributeError):
                    pass  # Signal not connected or already disconnected

            # Disconnect signals safely
            try:
                _ = self.items_updated.disconnect()
            except (RuntimeError, TypeError):
                pass  # No connections to disconnect
            try:
                _ = self.shots_updated.disconnect()
            except (RuntimeError, TypeError):
                pass  # No connections to disconnect

        self.logger.debug("PreviousShotsItemModel cleanup complete")

    @override
    def deleteLater(self) -> None:
        """Override deleteLater to ensure cleanup."""
        self.cleanup()
        super().deleteLater()
