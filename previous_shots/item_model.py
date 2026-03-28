"""Qt Model/View implementation for Previous Shots items.

This module provides a Qt Model implementation specifically for previous shots,
extending BaseItemModel with integration to PreviousShotsModel for data updates.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import QObject, Qt, Signal
from typing_extensions import override

from ui.base_item_model import BaseItemModel
from utils import safe_disconnect


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache
    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from previous_shots.model import PreviousShotsModel
    from type_definitions import Shot


class PreviousShotsItemModel(BaseItemModel["Shot"]):
    """Qt Model implementation for Previous Shots items.

    Provides Model/View architecture for displaying previously worked shots,
    with lazy thumbnail loading, selection management, and automatic updates
    from the underlying PreviousShotsModel.
    """

    # Previous shots-specific signals
    shots_updated: ClassVar[Signal] = Signal()  # Emitted when shots list changes
    show_filter_changed: ClassVar[Signal] = Signal(
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
            _ = underlying_model.shots_updated.connect(
                self._on_underlying_shots_updated
            )

        # Initialize with current shots
        self._update_from_underlying_model()

        self.logger.debug("PreviousShotsItemModel initialized")

    # ============= Previous shots-specific custom roles =============

    @override
    def get_custom_role_data(self, item: Shot, role: int) -> object:
        """Handle shot-specific custom roles.

        Args:
            item: The shot
            role: The data role

        Returns:
            Data for the role or None

        """
        from ui.base_item_model import BaseItemRole

        # Handle item-specific roles for backward compatibility
        if role == BaseItemRole.ItemSpecificRole1:
            return item.shot  # Shot number/ID

        return super().get_custom_role_data(item, role)

    # ============= Previous shots-specific methods =============

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

    # ============= Cleanup =============

    @override
    def cleanup(self) -> None:
        """Clean up resources before deletion."""
        super().cleanup()

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
        safe_disconnect(self.items_updated, self.shots_updated)

        self.logger.debug("PreviousShotsItemModel cleanup complete")
