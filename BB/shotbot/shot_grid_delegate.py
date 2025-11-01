"""Custom delegate for efficient shot thumbnail rendering in grid views.

This module provides a QStyledItemDelegate implementation that handles
custom painting of shot thumbnails with selection states, loading indicators,
and optimized rendering for large datasets.
"""

import logging
from typing import Optional

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from config import Config
from shot_item_model import ShotRole

logger = logging.getLogger(__name__)


class ShotGridDelegate(QStyledItemDelegate):
    """Efficient delegate for rendering shot thumbnails in a grid.

    This delegate provides:
    - Custom painting with state handling
    - Loading indicators during thumbnail fetch
    - Selection and hover effects
    - Optimized rendering with clipping
    - Memory-efficient painting (no widget creation)
    """

    # Signals
    thumbnail_clicked = Signal(QModelIndex)
    thumbnail_double_clicked = Signal(QModelIndex)

    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize the delegate.

        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)

        # Appearance settings
        self._thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE
        self._padding = 8
        self._text_height = 40
        self._border_radius = 8

        # Colors
        self._bg_color = QColor("#2b2b2b")
        self._bg_hover_color = QColor("#3a3a3a")
        self._bg_selected_color = QColor("#0d7377")
        self._border_color = QColor("#444")
        self._border_hover_color = QColor("#888")
        self._border_selected_color = QColor("#14ffec")
        self._text_color = QColor("#ffffff")
        self._text_selected_color = QColor("#14ffec")

        # Fonts
        self._name_font = QFont()
        self._name_font.setPointSize(9)
        self._name_font.setBold(False)

        self._info_font = QFont()
        self._info_font.setPointSize(8)

        # Cache for expensive calculations
        self._metrics_cache = {}

        # Loading animation state
        self._loading_angle = 0

        logger.debug("ShotGridDelegate initialized with optimized painting")

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        """Paint the shot thumbnail with custom rendering.

        Args:
            painter: QPainter instance
            option: Style options
            index: Model index to paint
        """
        if not index.isValid():
            return

        painter.save()

        try:
            # Enable antialiasing for smooth rendering
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Get item data
            shot_name = index.data(ShotRole.FullNameRole)
            show = index.data(ShotRole.ShowRole)
            sequence = index.data(ShotRole.SequenceRole)
            thumbnail = index.data(ShotRole.ThumbnailPixmapRole)
            loading_state = index.data(ShotRole.LoadingStateRole)
            is_selected = index.data(ShotRole.IsSelectedRole)

            # Determine state
            is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
            is_focused = bool(option.state & QStyle.StateFlag.State_HasFocus)

            # Override with model selection state
            if is_selected is not None:
                is_selected = bool(is_selected)
            else:
                is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

            # Draw background
            self._paint_background(painter, option.rect, is_selected, is_hover)

            # Calculate regions
            thumbnail_rect = self._calculate_thumbnail_rect(option.rect)
            text_rect = self._calculate_text_rect(option.rect)

            # Draw thumbnail or loading indicator
            if isinstance(thumbnail, QPixmap) and not thumbnail.isNull():
                self._paint_thumbnail(painter, thumbnail_rect, thumbnail)
            elif loading_state == "loading":
                self._paint_loading_indicator(painter, thumbnail_rect)
            else:
                self._paint_placeholder(painter, thumbnail_rect)

            # Draw text
            self._paint_text(painter, text_rect, shot_name, show, sequence, is_selected)

            # Draw focus indicator if needed
            if is_focused:
                self._paint_focus_indicator(painter, option.rect)

        except Exception as e:
            logger.error(f"Error painting delegate: {e}")
        finally:
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Provide size hint for the item.

        Args:
            option: Style options
            index: Model index

        Returns:
            Recommended size for the item
        """
        width = self._thumbnail_size + 2 * self._padding
        height = self._thumbnail_size + self._text_height + 2 * self._padding
        return QSize(width, height)

    def _paint_background(
        self, painter: QPainter, rect: QRect, is_selected: bool, is_hover: bool
    ) -> None:
        """Paint the background with state-based styling.

        Args:
            painter: QPainter instance
            rect: Item rectangle
            is_selected: Selection state
            is_hover: Hover state
        """
        # Choose colors based on state
        if is_selected:
            bg_color = self._bg_selected_color
            border_color = self._border_selected_color
            border_width = 3
        elif is_hover:
            bg_color = self._bg_hover_color
            border_color = self._border_hover_color
            border_width = 2
        else:
            bg_color = self._bg_color
            border_color = self._border_color
            border_width = 2

        # Create rounded rectangle path
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self._border_radius, self._border_radius)

        # Fill background
        painter.fillPath(path, QBrush(bg_color))

        # Draw border
        pen = QPen(border_color, border_width)
        painter.setPen(pen)
        painter.drawPath(path)

    def _paint_thumbnail(self, painter: QPainter, rect: QRect, pixmap: QPixmap) -> None:
        """Paint the thumbnail image with proper scaling.

        Args:
            painter: QPainter instance
            rect: Thumbnail rectangle
            pixmap: Thumbnail pixmap
        """
        if pixmap.isNull():
            return

        # Scale pixmap to fit while maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Center the pixmap in the rect
        x = rect.x() + (rect.width() - scaled_pixmap.width()) // 2
        y = rect.y() + (rect.height() - scaled_pixmap.height()) // 2

        # Draw with rounded corners using clipping
        painter.save()

        # Create clipping path for rounded corners
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(rect), 4, 4)
        painter.setClipPath(clip_path)

        # Draw the pixmap
        painter.drawPixmap(x, y, scaled_pixmap)

        painter.restore()

    def _paint_loading_indicator(self, painter: QPainter, rect: QRect) -> None:
        """Paint a loading spinner animation.

        Args:
            painter: QPainter instance
            rect: Rectangle for the indicator
        """
        painter.save()

        # Calculate center and radius
        center = rect.center()
        radius = min(rect.width(), rect.height()) // 4

        # Set up pen for spinner
        pen = QPen(self._border_selected_color, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Draw spinning arc
        painter.translate(center)
        painter.rotate(self._loading_angle)

        arc_rect = QRect(-radius, -radius, radius * 2, radius * 2)
        painter.drawArc(arc_rect, 0, 270 * 16)  # 270 degree arc

        painter.restore()

        # Update angle for next frame
        self._loading_angle = (self._loading_angle + 10) % 360

    def _paint_placeholder(self, painter: QPainter, rect: QRect) -> None:
        """Paint a placeholder when no thumbnail is available.

        Args:
            painter: QPainter instance
            rect: Rectangle for the placeholder
        """
        # Draw a subtle gradient or pattern
        painter.fillRect(rect, QColor("#1a1a1a"))

        # Draw a camera icon or text
        painter.setPen(QPen(QColor("#666"), 1))

        font = QFont()
        font.setPointSize(24)
        painter.setFont(font)

        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "📷")

    def _paint_text(
        self,
        painter: QPainter,
        rect: QRect,
        shot_name: str,
        show: str,
        sequence: str,
        is_selected: bool,
    ) -> None:
        """Paint the text labels with proper formatting.

        Args:
            painter: QPainter instance
            rect: Text rectangle
            shot_name: Shot full name
            show: Show name
            sequence: Sequence name
            is_selected: Selection state
        """
        if not shot_name:
            return

        # Set text color
        text_color = self._text_selected_color if is_selected else self._text_color
        painter.setPen(text_color)

        # Draw main shot name
        painter.setFont(self._name_font)

        # Calculate text rect with padding
        text_rect = rect.adjusted(4, 2, -4, -2)

        # Draw shot name with elision if needed
        metrics = QFontMetrics(self._name_font)
        elided_text = metrics.elidedText(
            shot_name, Qt.TextElideMode.ElideRight, text_rect.width()
        )

        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
            elided_text,
        )

        # Draw show/sequence info if space available
        if text_rect.height() > 25:
            painter.setFont(self._info_font)
            info_text = f"{show} / {sequence}"

            info_rect = text_rect.adjusted(0, 18, 0, 0)
            metrics = QFontMetrics(self._info_font)
            elided_info = metrics.elidedText(
                info_text, Qt.TextElideMode.ElideRight, info_rect.width()
            )

            painter.setPen(QColor("#999") if not is_selected else text_color)
            painter.drawText(
                info_rect,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                elided_info,
            )

    def _paint_focus_indicator(self, painter: QPainter, rect: QRect) -> None:
        """Paint focus indicator around the item.

        Args:
            painter: QPainter instance
            rect: Item rectangle
        """
        pen = QPen(self._border_selected_color, 1)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)

        focus_rect = rect.adjusted(2, 2, -2, -2)
        painter.drawRoundedRect(
            focus_rect, self._border_radius - 2, self._border_radius - 2
        )

    def _calculate_thumbnail_rect(self, item_rect: QRect) -> QRect:
        """Calculate the thumbnail area within the item rect.

        Args:
            item_rect: Full item rectangle

        Returns:
            Rectangle for thumbnail display
        """
        x = item_rect.x() + self._padding
        y = item_rect.y() + self._padding
        size = self._thumbnail_size

        return QRect(x, y, size, size)

    def _calculate_text_rect(self, item_rect: QRect) -> QRect:
        """Calculate the text area within the item rect.

        Args:
            item_rect: Full item rectangle

        Returns:
            Rectangle for text display
        """
        x = item_rect.x() + self._padding
        y = item_rect.y() + self._padding + self._thumbnail_size
        width = self._thumbnail_size
        height = self._text_height

        return QRect(x, y, width, height)

    def set_thumbnail_size(self, size: int) -> None:
        """Update the thumbnail size.

        Args:
            size: New thumbnail size in pixels
        """
        self._thumbnail_size = max(
            Config.MIN_THUMBNAIL_SIZE, min(size, Config.MAX_THUMBNAIL_SIZE)
        )

        # Clear metrics cache as sizes changed
        self._metrics_cache.clear()

    def editorEvent(self, event, model, option, index):
        """Handle mouse events for custom interaction.

        Args:
            event: QEvent
            model: QAbstractItemModel
            option: QStyleOptionViewItem
            index: QModelIndex

        Returns:
            True if event was handled
        """
        # This enables click detection on thumbnails
        # Actual click handling would be done in the view
        return super().editorEvent(event, model, option, index)
