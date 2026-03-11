# controllers/filter_helpers.py

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from controllers.filter_coordinator import FilterableItemModel


def apply_show_filter(
    item_model: FilterableItemModel,
    model: object,
    show: str,
    *,
    status_callback: Callable[[str, int], None] | None = None,
    tab_name: str = "",
) -> None:
    """Apply show filter. Optionally notify a status bar callback."""
    show_filter = show or None
    item_model.set_show_filter(model, show_filter)
    if status_callback and tab_name:
        filtered_count = int(item_model.rowCount())
        filter_desc = show or "All Shows"
        status_callback(f"{tab_name}: {filtered_count} shots ({filter_desc})", 2500)
