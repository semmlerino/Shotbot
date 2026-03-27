"""Sort button bar for grid view toolbars."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton


if TYPE_CHECKING:
    from PySide6.QtWidgets import QHBoxLayout, QWidget


class SortButtonBar:
    """Toggle button bar for name/date sorting.

    A plain helper class (not a QWidget) that creates and manages
    sort toggle buttons. Fires a callback when the sort order changes.

    Args:
        on_order_changed: Called with "name" or "date" when user clicks a button.
        parent: Parent QWidget for the QButtonGroup (needed for Qt ownership).
    """

    _on_order_changed: Callable[[str], None]
    _label: QLabel
    _name_btn: QPushButton
    _date_btn: QPushButton
    _button_group: QButtonGroup

    def __init__(
        self,
        on_order_changed: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        self._on_order_changed = on_order_changed

        self._label = QLabel("Sort:")

        self._name_btn = QPushButton("Name")
        self._name_btn.setCheckable(True)
        self._name_btn.setToolTip("Sort by shot name alphabetically")
        self._name_btn.setFixedWidth(50)

        self._date_btn = QPushButton("Date")
        self._date_btn.setCheckable(True)
        self._date_btn.setChecked(True)  # Default: date (newest first)
        self._date_btn.setToolTip("Sort by date (newest first)")
        self._date_btn.setFixedWidth(50)

        self._button_group = QButtonGroup(parent)
        self._button_group.addButton(self._name_btn, 0)
        self._button_group.addButton(self._date_btn, 1)
        _ = self._button_group.idClicked.connect(self._on_clicked)

    def add_to_layout(self, layout: QHBoxLayout) -> None:
        """Add the sort label and buttons to the given layout."""
        layout.addWidget(self._label)
        layout.addWidget(self._name_btn)
        layout.addWidget(self._date_btn)

    def set_order(self, order: str) -> None:
        """Set the active sort order without firing the callback.

        Args:
            order: "name" or "date"
        """
        if order not in ("name", "date"):
            return
        _ = self._button_group.blockSignals(True)
        if order == "name":
            self._name_btn.setChecked(True)
        else:
            self._date_btn.setChecked(True)
        _ = self._button_group.blockSignals(False)

    def _on_clicked(self, button_id: int) -> None:
        """Handle button click, fire callback."""
        order = "name" if button_id == 0 else "date"
        self._on_order_changed(order)
