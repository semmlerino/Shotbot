"""QSortFilterProxyModel implementations for filtered/sorted views.

Proxy models sit between item models and views, providing filtering
and sorting without triggering source model resets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSortFilterProxyModel

from typing_compat import override
from ui.base_item_model import BaseItemRole


if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from managers.hide_manager import HideManager
    from type_definitions import Shot, ThreeDEScene


class BaseProxyModel(QSortFilterProxyModel):
    """Base proxy model with shared filtering and pin-first sorting.

    Subclasses override the hook methods to customize behaviour without
    duplicating the common show/text filter and pin-sort skeleton.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._show_filter: str | None = None
        self._text_filter: str | None = None
        self._pin_manager: Any | None = None
        self.setDynamicSortFilter(False)

    # --- Filter property setters ---

    def set_show_filter(self, show: str | None) -> None:
        """Set show filter (None = all shows)."""
        if self._show_filter != show:
            self._show_filter = show
            self.invalidate()

    def set_text_filter(self, text: str | None) -> None:
        """Set text filter (None = no filtering)."""
        normalized = text.strip() if text else None
        if self._text_filter != normalized:
            self._text_filter = normalized
            self.invalidate()

    def set_pin_manager(self, manager: Any | None) -> None:
        """Set the pin manager for pin-aware sorting."""
        self._pin_manager = manager
        self.invalidate()

    def refresh_sort(self) -> None:
        """Re-sort after pin changes."""
        self.invalidate()

    # --- QSortFilterProxyModel overrides ---

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        """Filter rows based on show, text, and any subclass-specific criteria."""
        index = self.sourceModel().index(source_row, 0, source_parent)
        item = index.data(BaseItemRole.ObjectRole)
        if item is None:
            return False

        # Show filter
        if self._show_filter and item.show != self._show_filter:
            return False

        # Text filter
        if self._text_filter and self._text_filter.lower() not in item.full_name.lower():
            return False

        return self._extra_filter(item)

    @override
    def lessThan(
        self, left: QModelIndex | QPersistentModelIndex, right: QModelIndex | QPersistentModelIndex
    ) -> bool:
        """Sort with pinned items first, then delegate to subclass tiebreak."""
        left_item = left.data(BaseItemRole.ObjectRole)
        right_item = right.data(BaseItemRole.ObjectRole)

        if left_item is None or right_item is None:
            return False

        if self._pin_manager is not None:
            left_pinned = self._get_is_pinned(left_item)
            right_pinned = self._get_is_pinned(right_item)

            if left_pinned != right_pinned:
                return left_pinned  # Pinned items sort first

            if left_pinned and right_pinned:
                left_order = self._get_pin_order(left_item)
                right_order = self._get_pin_order(right_item)
                if left_order is not None and right_order is not None:
                    return left_order < right_order

        return self._sort_tiebreak(left_item, right_item)

    # --- Subclass hooks ---

    def _extra_filter(self, item: Any) -> bool:
        """Additional filtering beyond show/text. Override in subclasses."""
        return True

    def _get_is_pinned(self, item: Any) -> bool:
        """Check if item is pinned. Override in subclasses."""
        return False

    def _get_pin_order(self, item: Any) -> int | None:
        """Get pin sort order. Override in subclasses."""
        return None

    def _sort_tiebreak(self, left: Any, right: Any) -> bool:
        """Sort non-pinned items. Override in subclasses."""
        return False


class ShotProxyModel(BaseProxyModel):
    """Proxy model for filtering and sorting shots (My Shots tab).

    Filters by show name, text substring, and hidden state.
    Sorts with pinned shots first, then alphabetically.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hide_manager: HideManager | None = None
        self._show_hidden: bool = False

    def set_show_hidden(self, show: bool) -> None:
        """Set whether hidden shots are visible."""
        if self._show_hidden != show:
            self._show_hidden = show
            self.invalidate()

    def set_hide_manager(self, manager: HideManager | None) -> None:
        """Set the hide manager."""
        self._hide_manager = manager

    @override
    def _extra_filter(self, item: Any) -> bool:
        shot = cast("Shot", item)
        return not (not self._show_hidden and self._hide_manager and self._hide_manager.is_hidden(shot))

    @override
    def _get_is_pinned(self, item: Any) -> bool:
        if self._pin_manager is not None:
            return self._pin_manager.is_pinned(cast("Shot", item))
        return False

    @override
    def _get_pin_order(self, item: Any) -> int | None:
        if self._pin_manager is not None:
            return self._pin_manager.get_pin_order(cast("Shot", item))
        return None

    @override
    def _sort_tiebreak(self, left: Any, right: Any) -> bool:
        return cast("Shot", left).full_name.lower() < cast("Shot", right).full_name.lower()


class PreviousShotsProxyModel(BaseProxyModel):
    """Proxy model for Previous Shots tab.

    Same filtering as ShotProxyModel, plus date-based sort option.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sort_order: str = "date"

    def set_sort_order(self, order: str) -> None:
        """Set sort order ('name' or 'date')."""
        if self._sort_order != order:
            self._sort_order = order
            self.invalidate()

    @override
    def _extra_filter(self, item: Any) -> bool:
        return True

    @override
    def _get_is_pinned(self, item: Any) -> bool:
        if self._pin_manager is not None:
            return self._pin_manager.is_pinned(cast("Shot", item))
        return False

    @override
    def _get_pin_order(self, item: Any) -> int | None:
        if self._pin_manager is not None:
            return self._pin_manager.get_pin_order(cast("Shot", item))
        return None

    @override
    def _sort_tiebreak(self, left: Any, right: Any) -> bool:
        left_shot = cast("Shot", left)
        right_shot = cast("Shot", right)
        if self._sort_order == "name":
            return left_shot.full_name.lower() < right_shot.full_name.lower()
        # Date: newest first (higher discovered_at = earlier in sort)
        return left_shot.discovered_at > right_shot.discovered_at


class ThreeDEProxyModel(BaseProxyModel):
    """Proxy model for 3DE scenes tab.

    Filters by show, artist, and text. Sorts by name or date.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._artist_filter: str | None = None
        self._sort_order: str = "date"

    def set_artist_filter(self, artist: str | None) -> None:
        """Set artist filter."""
        if self._artist_filter != artist:
            self._artist_filter = artist
            self.invalidate()

    def set_sort_order(self, order: str) -> None:
        """Set sort order ('name' or 'date')."""
        if self._sort_order != order:
            self._sort_order = order
            self.invalidate()

    @override
    def _extra_filter(self, item: Any) -> bool:
        scene = cast("ThreeDEScene", item)
        return not (self._artist_filter and scene.user != self._artist_filter)

    @override
    def _get_is_pinned(self, item: Any) -> bool:
        if self._pin_manager is not None:
            return self._pin_manager.is_pinned_by_path(cast("ThreeDEScene", item).workspace_path)
        return False

    @override
    def _get_pin_order(self, item: Any) -> int | None:
        return None

    @override
    def _sort_tiebreak(self, left: Any, right: Any) -> bool:
        left_scene = cast("ThreeDEScene", left)
        right_scene = cast("ThreeDEScene", right)
        if self._sort_order == "name":
            return left_scene.full_name.lower() < right_scene.full_name.lower()
        # Date: newest first (higher modified_time = earlier in sort)
        return left_scene.modified_time > right_scene.modified_time
