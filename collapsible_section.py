"""Reusable collapsible section widget.

Provides a collapsible container with a header that can be expanded/collapsed
by clicking. Used for Files section, Custom Launchers, and Command Log.
"""

from __future__ import annotations

from typing import final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from design_system import design_system
from qt_widget_mixin import QtWidgetMixin


@final
class CollapsibleSection(QtWidgetMixin, QWidget):
    """A collapsible section with a clickable header.

    The header shows a toggle indicator (▶/▼) and title with optional count.
    Content is hidden when collapsed and shown when expanded.

    Attributes:
        expanded_changed: Signal emitted when expansion state changes (bool).
    """

    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the collapsible section.

        Args:
            title: Section title displayed in header
            expanded: Initial expansion state
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self._count: int | None = None
        self._content_widget: QWidget | None = None

        # Style parameters for live refresh
        self._header_color = "#aaa"
        self._header_hover_color = "#ddd"
        self._header_hover_bg = "#2a2a2a"

        self._setup_ui()

        # Connect to scale changes for live updates
        _ = design_system.scale_changed.connect(self._apply_styles)
        self._update_header_text()
        self._update_content_visibility()

    def _setup_ui(self) -> None:
        """Set up the section UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header button (clickable)
        self._header_button = QPushButton()
        self._header_button.setFlat(True)
        self._header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        _ = self._header_button.clicked.connect(self._toggle_expanded)
        self._apply_styles()
        layout.addWidget(self._header_button)

        # Content container
        self._content_container = QWidget()
        self._content_layout = QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        layout.addWidget(self._content_container)

    def _apply_styles(self) -> None:
        """Apply/refresh styles using current design system values."""
        self._header_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 8px 10px;
                font-size: {design_system.typography.size_small}px;
                font-weight: bold;
                color: {self._header_color};
            }}
            QPushButton:hover {{
                background-color: {self._header_hover_bg};
                color: {self._header_hover_color};
            }}
        """)

    def _update_header_text(self) -> None:
        """Update header button text with indicator, title, and count."""
        indicator = "▼" if self._expanded else "▶"
        if self._count is not None:
            text = f"{indicator}  {self._title} ({self._count})"
        else:
            text = f"{indicator}  {self._title}"
        self._header_button.setText(text)

    def _update_content_visibility(self) -> None:
        """Update content visibility based on expanded state."""
        self._content_container.setVisible(self._expanded)

    def _toggle_expanded(self) -> None:
        """Toggle the expanded state."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        """Set the expansion state.

        Args:
            expanded: True to expand, False to collapse
        """
        if self._expanded != expanded:
            self._expanded = expanded
            self._update_header_text()
            self._update_content_visibility()
            self.expanded_changed.emit(expanded)

    def is_expanded(self) -> bool:
        """Return whether the section is expanded."""
        return self._expanded

    def set_title(self, title: str) -> None:
        """Set the section title.

        Args:
            title: New title
        """
        self._title = title
        self._update_header_text()

    def set_count(self, count: int | None) -> None:
        """Set the item count shown in header.

        Args:
            count: Item count, or None to hide count
        """
        self._count = count
        self._update_header_text()

    def set_content(self, widget: QWidget) -> None:
        """Set the content widget.

        Replaces any existing content widget.

        Args:
            widget: Widget to display when expanded
        """
        # Remove existing content
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)

        # Add new content
        self._content_widget = widget
        self._content_layout.addWidget(widget)

    def get_content(self) -> QWidget | None:
        """Return the current content widget, if any."""
        return self._content_widget

    def set_header_style(
        self,
        color: str = "#aaa",
        hover_color: str = "#ddd",
        hover_bg: str = "#2a2a2a",
    ) -> None:
        """Customize the header appearance.

        Args:
            color: Text color
            hover_color: Text color on hover
            hover_bg: Background color on hover
        """
        self._header_color = color
        self._header_hover_color = hover_color
        self._header_hover_bg = hover_bg
        self._apply_styles()
