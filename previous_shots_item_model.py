"""Qt Model/View implementation for Previous Shots items.

This module provides a Qt Model implementation specifically for previous shots,
extending BaseItemModel with integration to PreviousShotsModel for data updates.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QObject, Qt, Signal

from base_item_model import BaseItemModel
from typing_compat import override


if TYPE_CHECKING:
    from cache_manager import CacheManager
    from previous_shots_model import PreviousShotsModel
    from shot_model import Shot


class PreviousShotsItemModel(BaseItemModel["Shot"]):
    """Qt Model implementation for Previous Shots items.

    Provides Model/View architecture for displaying previously worked shots,
    with lazy thumbnail loading, selection management, and automatic updates
    from the underlying PreviousShotsModel.
    """

    # Previous shots-specific signals
    shots_updated = Signal()  # Emitted when shots list changes
    show_filter_changed = Signal(
        str
    )  # Emitted when show filter changes (show name or "All Shows")

    def __init__(
        self,
        underlying_model: PreviousShotsModel,
        cache_manager: CacheManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the previous shots item model.

        Args:
            underlying_model: PreviousShotsModel instance providing shot data
            cache_manager: Optional cache manager for thumbnails
            parent: Optional parent QObject
        """
        super().__init__(cache_manager, parent)

        self._underlying_model = underlying_model

        # Connect generic items_updated to shot-specific signal
        self.items_updated.connect(self.shots_updated)

        # Connect to underlying model for automatic updates
        if hasattr(underlying_model, "shots_updated") and hasattr(
            underlying_model.shots_updated, "emit"
        ):
            # Test double - connect without Qt.ConnectionType
            underlying_model.shots_updated.connect(self._on_underlying_shots_updated)
        elif hasattr(underlying_model, "shots_updated"):
            # Real Qt signal - use proper connection type
            underlying_model.shots_updated.connect(
                self._on_underlying_shots_updated,
                Qt.ConnectionType.QueuedConnection,
            )

        # Initialize with current shots
        self._update_from_underlying_model()

        self.logger.info("PreviousShotsItemModel initialized")

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

    def _on_underlying_shots_updated(self) -> None:
        """Handle shots update from underlying model."""
        self._update_from_underlying_model()

    def _update_from_underlying_model(self) -> None:
        """Update items from underlying model."""
        new_shots = self._underlying_model.get_shots()
        self.set_items(new_shots)
        self.logger.debug(f"Updated with {len(new_shots)} previous shots")

    def refresh(self) -> None:
        """Trigger refresh of underlying model."""
        self._underlying_model.refresh_shots()

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

        self._selected_index = QPersistentModelIndex()

        # Disconnect from underlying model
        # Note: We check receivers() before disconnecting to avoid RuntimeWarnings
        # from Qt when attempting to disconnect signals that have no connections.
        # Qt's receivers() method is not properly typed in PySide6 stubs
        if hasattr(self._underlying_model, "shots_updated"):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                if self._underlying_model.shots_updated.receivers(self._on_underlying_shots_updated) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                    self._underlying_model.shots_updated.disconnect(
                        self._on_underlying_shots_updated
                    )

        # Disconnect signals safely
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            if self.items_updated.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                self.items_updated.disconnect()
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            if self.shots_updated.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
                self.shots_updated.disconnect()

        self.logger.info("PreviousShotsItemModel cleanup complete")

    def deleteLater(self) -> None:
        """Override deleteLater to ensure cleanup."""
        self.cleanup()
        super().deleteLater()
