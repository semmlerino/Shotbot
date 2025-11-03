"""Base delegate for efficient thumbnail rendering in grid views.

This module provides a base QStyledItemDelegate implementation that handles
custom painting of thumbnails with selection states, loading indicators,
and optimized rendering for large datasets. Subclasses can customize
colors, fonts, and specific data roles.
"""

from __future__ import annotations

# Standard library imports
# Note: Can't use ABC with Qt classes due to metaclass conflict
from dataclasses import dataclass, field
from typing import cast

# Third-party imports
from PySide6.QtCore import (
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)
from typing_extensions import TypedDict

# Local application imports
from config import Config
from logging_mixin import get_module_logger
from typing_compat import override


# Module-level logger
logger = get_module_logger(__name__)


class ThumbnailItemData(TypedDict, total=False):
    """Type definition for thumbnail item data."""

    name: str  # Required - item name
    show: str  # Optional - show name
    sequence: str  # Optional - sequence name
    shot: str  # Optional - shot name
    thumbnail: QPixmap | None  # thumbnail image
    loading_state: str  # Loading state string
    is_selected: bool  # Selection state
    user: str  # Optional - user name
    timestamp: str  # Optional - timestamp


@dataclass
class DelegateTheme:
    """Theme configuration for thumbnail delegates."""

    # Colors (use factory to avoid mutable default issue)
    bg_color: QColor = field(default_factory=lambda: QColor("#2b2b2b"))
    bg_hover_color: QColor = field(default_factory=lambda: QColor("#3a3a3a"))
    bg_selected_color: QColor = field(default_factory=lambda: QColor("#0d7377"))
    border_color: QColor = field(default_factory=lambda: QColor("#444"))
    border_hover_color: QColor = field(default_factory=lambda: QColor("#888"))
    border_selected_color: QColor = field(default_factory=lambda: QColor("#14ffec"))
    text_color: QColor = field(default_factory=lambda: QColor("#ffffff"))
    text_selected_color: QColor = field(default_factory=lambda: QColor("#14ffec"))

    # Additional colors (optional)
    user_color: QColor | None = None

    # Dimensions
    text_height: int = 40
    padding: int = 8
    border_radius: int = 8

    # Font sizes
    name_font_size: int = 9
    info_font_size: int = 8


class BaseThumbnailDelegate(QStyledItemDelegate):
    """Base delegate for rendering thumbnails in a grid.

    This delegate provides:
    - Custom painting with state handling
    - Loading indicators during thumbnail fetch
    - Selection and hover effects
    - Optimized rendering with clipping
    - Memory-efficient painting (no widget creation)

    Subclasses must implement:
    - get_item_data() to extract model data
    - get_theme() to provide theme configuration
    """

    # Signals
    thumbnail_clicked = Signal(QModelIndex)
    thumbnail_double_clicked = Signal(QModelIndex)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the delegate.

        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)

        # Get theme from subclass
        self.theme = self.get_theme()

        # Appearance settings
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE

        # Fonts
        self._name_font = QFont()
        self._name_font.setPointSize(self.theme.name_font_size)
        self._name_font.setBold(False)

        self._info_font = QFont()
        self._info_font.setPointSize(self.theme.info_font_size)

        # Cache for expensive calculations
        self._metrics_cache: dict[str, QSize] = {}

        # Loading animation
        self._loading_angle = 0
        self._loading_timer: QTimer | None = None

        logger.debug(f"{self.__class__.__name__} initialized with optimized painting")

    def get_theme(self) -> DelegateTheme:
        """Get the theme configuration for this delegate.

        Returns:
            Theme configuration

        Note:
            Subclasses must override this method.
        """
        raise NotImplementedError("Subclasses must implement get_theme()")

    def get_item_data(
        self, _index: QModelIndex | QPersistentModelIndex
    ) -> ThumbnailItemData:
        """Extract item data from model index.

        Args:
            index: Model index

        Returns:
            Dictionary with item data including:
            - name: Item name
            - show: Show name (optional)
            - sequence: Sequence name (optional)
            - thumbnail: QPixmap or None
            - loading_state: Loading state string
            - is_selected: Selection state
            - user: User name (optional)
            - timestamp: Timestamp (optional)

        Note:
            Subclasses must override this method.
        """
        raise NotImplementedError("Subclasses must implement get_item_data()")

    @override
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Paint the thumbnail with custom rendering.

        Args:
            painter: QPainter instance
            option: Style options
            index: Model index to paint
        """
        if not index.isValid():
            return

        # Extract attributes from option
        # PySide6 type stubs missing .rect and .state attributes on QStyleOptionViewItem
        # These attributes exist at runtime and are documented in Qt API
        rect = cast("QRect", option.rect)  # pyright: ignore[reportAttributeAccessIssue]
        state = cast("QStyle.StateFlag", option.state)  # pyright: ignore[reportAttributeAccessIssue]

        painter.save()

        try:
            # Enable antialiasing for smooth rendering
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Get item data from subclass
            data = self.get_item_data(index)

            # Determine state
            is_hover = bool(state & QStyle.StateFlag.State_MouseOver)
            is_selected = data.get("is_selected", False) or bool(
                state & QStyle.StateFlag.State_Selected
            )

            # Draw background
            self._draw_background(painter, rect, is_hover, is_selected)

            # Draw thumbnail or loading indicator
            thumbnail_rect = self._get_thumbnail_rect(rect)

            loading_state = data.get("loading_state", "idle")

            if loading_state == "loading":
                self._draw_loading_indicator(painter, thumbnail_rect)
            elif thumbnail := data.get("thumbnail"):
                self._draw_thumbnail(painter, thumbnail_rect, thumbnail)
            elif loading_state == "failed":
                self._draw_failed_placeholder(painter, thumbnail_rect)
            else:
                self._draw_placeholder(painter, thumbnail_rect)

            # Draw text
            self._draw_text(painter, rect, data, is_selected)

            # Draw border
            self._draw_border(painter, rect, is_hover, is_selected)

        finally:
            painter.restore()

    def _draw_background(
        self, painter: QPainter, rect: QRect, is_hover: bool, is_selected: bool
    ) -> None:
        """Draw the background with appropriate color."""
        if is_selected:
            bg_color = self.theme.bg_selected_color
        elif is_hover:
            bg_color = self.theme.bg_hover_color
        else:
            bg_color = self.theme.bg_color

        # Create rounded rectangle path
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(rect), self.theme.border_radius, self.theme.border_radius
        )

        # Fill background
        painter.fillPath(path, QBrush(bg_color))

    def _draw_border(
        self, painter: QPainter, rect: QRect, is_hover: bool, is_selected: bool
    ) -> None:
        """Draw the border with appropriate color and width."""
        if is_selected:
            border_color = self.theme.border_selected_color
            border_width = 2
        elif is_hover:
            border_color = self.theme.border_hover_color
            border_width = 1
        else:
            border_color = self.theme.border_color
            border_width = 1

        # Create rounded rectangle path
        path = QPainterPath()
        # Adjust rect to account for border width
        adjusted_rect = rect.adjusted(
            border_width // 2,
            border_width // 2,
            -border_width // 2,
            -border_width // 2,
        )
        path.addRoundedRect(
            QRectF(adjusted_rect), self.theme.border_radius, self.theme.border_radius
        )

        # Draw border
        pen = QPen(border_color, border_width)
        painter.setPen(pen)
        painter.drawPath(path)

    def _get_thumbnail_rect(self, rect: QRect) -> QRect:
        """Calculate the rectangle for the thumbnail image."""
        # Calculate thumbnail rect with padding
        return QRect(
            rect.x() + self.theme.padding,
            rect.y() + self.theme.padding,
            rect.width() - 2 * self.theme.padding,
            rect.height() - self.theme.text_height - 2 * self.theme.padding,
        )

    def _draw_thumbnail(
        self, painter: QPainter, rect: QRect, thumbnail: QPixmap
    ) -> None:
        """Draw the thumbnail image scaled to fit."""
        if thumbnail and not thumbnail.isNull():
            # Scale pixmap to fit while maintaining aspect ratio
            scaled_pixmap = thumbnail.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            # Center the pixmap in the rect
            x = rect.x() + (rect.width() - scaled_pixmap.width()) // 2
            y = rect.y() + (rect.height() - scaled_pixmap.height()) // 2

            # Draw with clipping for rounded corners
            painter.setClipRect(rect)
            painter.drawPixmap(x, y, scaled_pixmap)
            # Clear clipping to allow text drawing below
            painter.setClipping(False)

    def _draw_placeholder(self, painter: QPainter, rect: QRect) -> None:
        """Draw a placeholder when no thumbnail is available."""
        # Draw a darker rectangle as placeholder
        placeholder_color = QColor("#1a1a1a")
        painter.fillRect(rect, placeholder_color)

        # Draw placeholder text
        painter.setPen(QPen(QColor("#666")))
        painter.setFont(self._info_font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No Thumbnail")

    def _draw_failed_placeholder(self, painter: QPainter, rect: QRect) -> None:
        """Draw a placeholder when thumbnail loading failed."""
        # Draw a darker rectangle with red tint as placeholder
        placeholder_color = QColor("#2a1a1a")  # Slight red tint
        painter.fillRect(rect, placeholder_color)

        # Draw error icon (X symbol)
        painter.setPen(QPen(QColor("#cc4444"), 3))  # Red color
        center = rect.center()
        size = min(rect.width(), rect.height()) // 4
        x_rect = QRect(
            center.x() - size // 2,
            center.y() - size // 2,
            size,
            size,
        )
        # Draw X
        painter.drawLine(x_rect.topLeft(), x_rect.bottomRight())
        painter.drawLine(x_rect.topRight(), x_rect.bottomLeft())

        # Draw error text
        painter.setPen(QPen(QColor("#cc4444")))
        painter.setFont(self._info_font)
        text_rect = QRect(rect.x(), rect.bottom() - 20, rect.width(), 20)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "Failed to load")

    def _draw_loading_indicator(self, painter: QPainter, rect: QRect) -> None:
        """Draw an animated loading indicator."""
        # Draw spinning arc
        center = rect.center()
        radius = min(rect.width(), rect.height()) // 4

        painter.setPen(QPen(QColor("#888"), 2))
        painter.drawArc(
            center.x() - radius,
            center.y() - radius,
            radius * 2,
            radius * 2,
            self._loading_angle * 16,
            120 * 16,
        )

        # Start animation timer if not running
        if not self._loading_timer:
            self._loading_timer = QTimer()
            _ = self._loading_timer.timeout.connect(self._update_loading_animation)
            self._loading_timer.start(50)

    def _draw_text(
        self, painter: QPainter, rect: QRect, data: ThumbnailItemData, is_selected: bool
    ) -> None:
        """Draw the text labels below the thumbnail."""
        text_rect = QRect(
            rect.x() + self.theme.padding,
            rect.bottom() - self.theme.text_height,
            rect.width() - 2 * self.theme.padding,
            self.theme.text_height,
        )

        # Draw name with shadow for better readability
        painter.setFont(self._name_font)
        name_rect = QRect(text_rect.x(), text_rect.y(), text_rect.width(), 25)

        name = data.get("name", "Unknown")
        elided_name = painter.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, name_rect.width()
        )

        # Draw text with drop shadow for better contrast
        self._draw_text_with_shadow(painter, name_rect, elided_name, is_selected)

        # Draw additional info (show/sequence or user/timestamp)
        painter.setFont(self._info_font)
        info_rect = QRect(text_rect.x(), text_rect.y() + 25, text_rect.width(), 25)

        # Build info text based on available data
        info_parts: list[str] = []
        if show := data.get("show"):
            info_parts.append(show)
        if sequence := data.get("sequence"):
            info_parts.append(sequence)
        if user := data.get("user"):
            # Use user color if available
            if self.theme.user_color:
                painter.setPen(QPen(self.theme.user_color))
            info_parts.append(user)

        if info_parts:
            info_text = " • ".join(info_parts)
            elided_info = painter.fontMetrics().elidedText(
                info_text, Qt.TextElideMode.ElideRight, info_rect.width()
            )

            # Draw info text with shadow for better readability
            self._draw_text_with_shadow(
                painter, info_rect, elided_info, is_selected, is_info=True
            )

    def _draw_text_with_shadow(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        is_selected: bool,
        is_info: bool = False,
    ) -> None:
        """Draw text with drop shadow for better readability against thumbnails."""
        # Draw shadow first (offset by 1 pixel down and right)
        shadow_rect = QRect(rect.x() + 1, rect.y() + 1, rect.width(), rect.height())
        painter.setPen(QPen(QColor(0, 0, 0, 180)))  # Semi-transparent black shadow
        painter.drawText(
            shadow_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

        # Draw main text on top
        if is_selected:
            text_color = self.theme.text_selected_color
        elif is_info and self.theme.user_color:
            text_color = self.theme.user_color
        else:
            text_color = self.theme.text_color

        painter.setPen(QPen(text_color))
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, text
        )

    def _update_loading_animation(self) -> None:
        """Update the loading animation with targeted repaints."""
        self._loading_angle = (self._loading_angle + 10) % 360

        # Replace parent.update() with targeted updates for only loading items
        # Get model from parent view (QListView/QTreeView)
        parent = self.parent()
        if not parent:
            return

        # Check if parent is a view with a model() method
        if not isinstance(parent, QAbstractItemView):
            return

        model = parent.model()
        if not model:
            return

        # Only repaint items that are actually loading
        for row in self._get_loading_rows():
            index = model.index(row, 0)
            model.dataChanged.emit(
                index, index, [Qt.ItemDataRole.DecorationRole]
            )

    def _get_loading_rows(self) -> list[int]:
        """Get rows currently in loading state.

        Returns:
            List of row indices that are currently loading thumbnails
        """
        loading_rows: list[int] = []

        # Get model from parent view
        parent = self.parent()
        if not parent:
            return loading_rows

        # Check if parent is a view with a model() method
        if not isinstance(parent, QAbstractItemView):
            return loading_rows

        model = parent.model()
        if not model:
            return loading_rows

        # Import here to avoid circular imports at module level
        from base_item_model import BaseItemRole

        for row in range(model.rowCount()):
            index = model.index(row, 0)
            # Check loading state via model data
            loading_state = index.data(BaseItemRole.LoadingStateRole)
            if loading_state == "loading":
                loading_rows.append(row)

        return loading_rows

    @override
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Return the size hint for an item.

        Args:
            option: Style options
            index: Model index

        Returns:
            Recommended size for the item
        """
        return QSize(
            self._thumbnail_size + 2 * self.theme.padding,
            self._thumbnail_size + self.theme.text_height + 2 * self.theme.padding,
        )

    def set_thumbnail_size(self, size: int) -> None:
        """Update the thumbnail size.

        Args:
            size: New thumbnail size in pixels
        """
        self._thumbnail_size = size
        # Clear metrics cache as sizes have changed
        self._metrics_cache.clear()

        # Trigger layout update
        if (parent := self.parent()) and isinstance(parent, QWidget):
            parent.update()

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._loading_timer:
            self._loading_timer.stop()
            self._loading_timer.deleteLater()
            self._loading_timer = None
        self._metrics_cache.clear()
