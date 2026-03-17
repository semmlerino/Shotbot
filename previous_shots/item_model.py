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
    from cache.thumbnail_cache import ThumbnailCache
    from notes_manager import NotesManager
    from previous_shots.model import PreviousShotsModel
    from shot_pin_manager import ShotPinManager
    from type_definitions import Shot


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
        cache_manager: ThumbnailCache | None = None,
        pin_manager: ShotPinManager | None = None,
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
        self._pin_manager: ShotPinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager

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
        self.set_items(shots)


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

    def _on_underlying_shots_updated(self) -> None:
        """Handle shots update from underlying model."""
        self._update_from_underlying_model()

    def _update_from_underlying_model(self) -> None:
        """Update items from underlying model."""
        new_shots = self._underlying_model.get_shots()
        self.set_shots(new_shots)
        self.logger.debug(f"Updated with {len(new_shots)} previous shots")

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
        # Stop thumbnail loader timers
        if hasattr(self, "_thumbnail_loader"):
            self._thumbnail_loader.shutdown()

        # Clear caches
        self.clear_thumbnail_cache()

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
