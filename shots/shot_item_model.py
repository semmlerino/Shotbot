"""Qt Model/View implementation for Shot items.

This module provides a Qt Model implementation specifically for Shot objects,
extending BaseItemModel with shot-specific behavior.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from typing_compat import override
from ui.base_item_model import BaseItemModel


if TYPE_CHECKING:
    from cache.thumbnail_cache import ThumbnailCache
    from managers.hide_manager import HideManager
    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from type_definitions import RefreshResult, Shot


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
        pin_manager: ShotPinManager | None = None,
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

        self._pin_manager: ShotPinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager
        self._hide_manager: HideManager | None = hide_manager

        # Connect generic items_updated to shot-specific signal
        _ = self.items_updated.connect(self.shots_updated)

        self.logger.debug("ShotItemModel initialized")

    # ============= Shot-specific custom roles =============

    @override
    def get_custom_role_data(self, item: Shot, role: int) -> object | None:
        """Handle shot-specific custom roles.

        Args:
            item: The shot
            role: The data role

        Returns:
            Data for the role or None

        """
        from ui.base_item_model import BaseItemRole

        if role == BaseItemRole.FrameRangeRole:
            return item.frame_range_display

        if role == BaseItemRole.IsHiddenRole:
            if self._hide_manager:
                return self._hide_manager.is_hidden(item)
            return False

        return super().get_custom_role_data(item, role)

    # ============= Shot-specific methods =============

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

    def set_hide_manager(self, hide_manager: HideManager) -> None:
        """Set the hide manager.

        Args:
            hide_manager: Hide manager for tracking hidden shots

        """
        self._hide_manager = hide_manager

    # ============= Cleanup =============

    @override
    def cleanup(self) -> None:
        """Clean up resources before deletion."""
        super().cleanup()

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
