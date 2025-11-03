"""Loading indicator widget for thumbnails."""

from __future__ import annotations

# Third-party imports
from PySide6.QtCore import Property, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget


class ThumbnailLoadingIndicator(QWidget):
    """A simple loading spinner widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer()
        _ = self._timer.timeout.connect(self._rotate)
        self.setFixedSize(40, 40)

        # Make widget transparent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def start(self) -> None:
        """Start the loading animation."""
        self._timer.start(50)  # Update every 50ms
        self.show()

    def stop(self) -> None:
        """Stop the loading animation."""
        self._timer.stop()
        self.hide()

    def _rotate(self) -> None:
        """Rotate the spinner."""
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the spinner."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate center
        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = min(center_x, center_y) - 5

        # Draw spinning arc
        pen = QPen(QColor("#14ffec"), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Draw partial circle
        painter.translate(center_x, center_y)
        painter.rotate(self._angle)

        # Draw 270 degree arc
        rect = QRect(-radius, -radius, radius * 2, radius * 2)
        painter.drawArc(rect, 0, 270 * 16)  # Qt uses 1/16th of a degree

        painter.end()


class ShimmerLoadingIndicator(QWidget):
    """A shimmer/skeleton loading effect widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shimmer_position: int = 0
        self._animation = QPropertyAnimation(self, b"shimmerPosition")
        self._animation.setDuration(1500)
        self._animation.setStartValue(-100)
        self._animation.setEndValue(self.width() + 100)
        self._animation.setLoopCount(-1)  # Infinite loop

        # Make widget transparent for mouse events
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _get_shimmer_position(self) -> int:
        """Get shimmer position."""
        return self._shimmer_position

    def _set_shimmer_position(self, value: int) -> None:
        """Set shimmer position."""
        self._shimmer_position = value
        self.update()

    # Create property using Property
    shimmerPosition = Property(int, _get_shimmer_position, _set_shimmer_position)

    def start(self) -> None:
        """Start the shimmer animation."""
        self._animation.setEndValue(self.width() + 100)
        self._animation.start()
        self.show()

    def stop(self) -> None:
        """Stop the shimmer animation."""
        self._animation.stop()
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the shimmer effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Base color
        base_color = QColor("#2b2b2b")
        painter.fillRect(self.rect(), base_color)

        # Shimmer gradient
        gradient_width = 100
        if -gradient_width <= self._shimmer_position <= self.width() + gradient_width:
            shimmer_rect = QRect(
                self._shimmer_position - gradient_width // 2,
                0,
                gradient_width,
                self.height(),
            )

            # Create gradient effect
            for i in range(gradient_width):
                alpha = int(
                    255 * (1 - abs(i - gradient_width / 2) / (gradient_width / 2)),
                )
                color = QColor(255, 255, 255, int(alpha * 0.15))
                painter.fillRect(
                    shimmer_rect.x() + i,
                    shimmer_rect.y(),
                    1,
                    shimmer_rect.height(),
                    color,
                )

        painter.end()
