"""Modern UI components with improved UX patterns for ShotBot.

This module provides enhanced UI components with proper animations,
loading states, and accessibility features.
"""

from __future__ import annotations

# Standard library imports
import logging

# Third-party imports
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QEnterEvent, QIcon, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from design_system import design_system

# Local imports
from typing_compat import override


logger = logging.getLogger(__name__)


class ModernButton(QPushButton):
    """Enhanced button with animations and proper states."""

    def __init__(
        self,
        text: str = "",
        variant: str = "default",
        icon: QIcon | None = None,
    ) -> None:
        super().__init__(text)
        self.variant: str = variant
        self._setup_style()
        self._setup_animations()

        if icon:
            self.setIcon(icon)
            self.setIconSize(QSize(20, 20))

        # Add keyboard shortcut hint to tooltip
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_style(self) -> None:
        """Apply modern styling based on variant."""

        if self.variant == "primary":
            self.setObjectName("primaryButton")
        elif self.variant == "success":
            self.setObjectName("successButton")
        elif self.variant == "danger":
            self.setObjectName("dangerButton")

        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _setup_animations(self) -> None:
        """Set up hover and click animations."""
        self.opacity_effect: QGraphicsOpacityEffect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)

        self.hover_animation: QPropertyAnimation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.hover_animation.setDuration(design_system.animation.duration_fast)
        self.hover_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Animate on hover."""
        self.hover_animation.setStartValue(1.0)
        self.hover_animation.setEndValue(0.9)
        self.hover_animation.start()
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Animate on leave."""
        self.hover_animation.setStartValue(0.9)
        self.hover_animation.setEndValue(1.0)
        self.hover_animation.start()
        super().leaveEvent(event)

    def set_loading(self, loading: bool) -> None:
        """Show loading state."""
        self.setEnabled(not loading)
        if loading:
            self.setText(f"⏳ {self.text()}")
        else:
            self.setText(self.text().replace("⏳ ", ""))


class LoadingSpinner(QWidget):
    """Animated loading spinner widget."""

    def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size: int = size
        self.angle: int = 0
        self.timer: QTimer = QTimer(self)
        _ = self.timer.timeout.connect(self._rotate)
        self.setFixedSize(size, size)

    def _rotate(self) -> None:
        """Rotate the spinner."""
        self.angle = (self.angle + 10) % 360
        self.update()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the spinner."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw spinning arc
        pen = QPen(QColor(design_system.colors.primary))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        rect = QRect(5, 5, self._size - 10, self._size - 10)
        painter.drawArc(rect, self.angle * 16, 120 * 16)

    def start(self) -> None:
        """Start spinning."""
        self.timer.start(50)
        self.show()

    def stop(self) -> None:
        """Stop spinning."""
        self.timer.stop()
        self.hide()


class NotificationBanner(QFrame):
    """Non-modal notification banner for status messages."""

    closed: Signal = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._setup_animations()
        self.hide()

    def _setup_ui(self) -> None:
        """Set up the banner UI."""
        self.setObjectName("notificationBanner")
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        # Icon label
        self.icon_label: QLabel = QLabel()
        self.icon_label.setFixedSize(24, 24)
        layout.addWidget(self.icon_label)

        # Message label
        self.message_label: QLabel = QLabel()
        self.message_label.setWordWrap(False)
        layout.addWidget(self.message_label, 1)

        # Close button
        self.close_button: QPushButton = QPushButton("✕")
        self.close_button.setFixedSize(24, 24)
        _ = self.close_button.clicked.connect(self.hide_banner)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)
        layout.addWidget(self.close_button)

    def _setup_animations(self) -> None:
        """Set up slide and fade animations."""
        self.opacity_effect: QGraphicsOpacityEffect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)

        # Slide animation
        self.slide_animation: QPropertyAnimation = QPropertyAnimation(self, b"geometry")
        self.slide_animation.setDuration(design_system.animation.duration_normal)
        self.slide_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Fade animation
        self.fade_animation: QPropertyAnimation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(design_system.animation.duration_normal)

        # Group animations
        self.animation_group: QParallelAnimationGroup = QParallelAnimationGroup()
        self.animation_group.addAnimation(self.slide_animation)
        self.animation_group.addAnimation(self.fade_animation)

    def show_message(
        self, message: str, msg_type: str = "info", duration: int = 5000
    ) -> None:
        """Show a notification message."""
        self.message_label.setText(message)

        # Set style based on type
        colors = {
            "info": design_system.colors.info,
            "success": design_system.colors.success,
            "warning": design_system.colors.warning,
            "error": design_system.colors.error,
        }

        icons = {"info": "i", "success": "✓", "warning": "⚠", "error": "✕"}

        bg_color = colors.get(msg_type, design_system.colors.info)
        icon = icons.get(msg_type, "i")

        self.setStyleSheet(f"""
            #notificationBanner {{
                background-color: {bg_color};
                border-radius: {design_system.borders.radius_md}px;
            }}
            QLabel {{
                color: white;
                font-size: {design_system.typography.size_body}px;
            }}
        """)

        self.icon_label.setText(icon)
        self.icon_label.setStyleSheet("font-size: 18px; color: white;")

        # Animate in
        parent_widget = self.parent()
        if isinstance(parent_widget, QWidget):
            parent_rect = parent_widget.rect()
            start_rect = QRect(0, -self.height(), parent_rect.width(), self.height())
            end_rect = QRect(0, 0, parent_rect.width(), self.height())

            self.slide_animation.setStartValue(start_rect)
            self.slide_animation.setEndValue(end_rect)

            self.fade_animation.setStartValue(0.0)
            self.fade_animation.setEndValue(1.0)

            self.show()
            self.animation_group.start()

        # Auto-hide after duration
        if duration > 0:
            QTimer.singleShot(duration, self.hide_banner)

    def hide_banner(self) -> None:
        """Hide the banner with animation."""
        parent_widget = self.parent()
        if isinstance(parent_widget, QWidget):
            parent_rect = parent_widget.rect()
            start_rect = self.geometry()
            end_rect = QRect(0, -self.height(), parent_rect.width(), self.height())

            self.slide_animation.setStartValue(start_rect)
            self.slide_animation.setEndValue(end_rect)

            self.fade_animation.setStartValue(1.0)
            self.fade_animation.setEndValue(0.0)

            _ = self.animation_group.finished.connect(self.hide)
            self.animation_group.start()

            self.closed.emit()


class ProgressOverlay(QWidget):
    """Semi-transparent overlay with progress indicator for long operations."""

    canceled: Signal = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self.hide()

    def _setup_ui(self) -> None:
        """Set up the overlay UI."""
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {design_system.colors.overlay};
            }}
        """)

        # Center content
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card container
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {design_system.colors.bg_tertiary};
                border-radius: {design_system.borders.radius_lg}px;
                padding: {design_system.spacing.xl}px;
            }}
        """)
        card.setFixedSize(300, 200)

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(design_system.spacing.md)

        # Spinner
        self.spinner: LoadingSpinner = LoadingSpinner(40)
        card_layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)

        # Title
        self.title_label: QLabel = QLabel("Processing...")
        self.title_label.setObjectName("heading3")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.title_label)

        # Progress bar
        self.progress_bar: QProgressBar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        card_layout.addWidget(self.progress_bar)

        # Status text
        self.status_label: QLabel = QLabel("")
        self.status_label.setObjectName("hint")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        # Cancel button
        self.cancel_button: ModernButton = ModernButton("Cancel", variant="danger")
        _ = self.cancel_button.clicked.connect(self.canceled.emit)
        card_layout.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(card)

    def show_progress(
        self, title: str = "Processing...", can_cancel: bool = True
    ) -> None:
        """Show the progress overlay."""
        self.title_label.setText(title)
        self.cancel_button.setVisible(can_cancel)
        self.progress_bar.setValue(0)
        self.status_label.setText("")

        parent_widget = self.parent()
        if isinstance(parent_widget, QWidget):
            self.resize(parent_widget.size())

        self.spinner.start()
        self.show()
        self.raise_()

    def update_progress(self, value: int, status: str = "") -> None:
        """Update progress value and status."""
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def hide_progress(self) -> None:
        """Hide the progress overlay."""
        self.spinner.stop()
        self.hide()


class EmptyStateWidget(QWidget):
    """Widget shown when there's no content to display."""

    action_clicked: Signal = Signal()

    def __init__(
        self,
        icon: str = "📁",
        title: str = "No items",
        description: str = "",
        action_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._setup_ui(icon, title, description, action_text)

    def _setup_ui(
        self, icon: str, title: str, description: str, action_text: str
    ) -> None:
        """Set up the empty state UI."""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(design_system.spacing.md)

        # Icon
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"""
            font-size: 48px;
            color: {design_system.colors.text_disabled};
        """)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Title
        title_label = QLabel(title)
        title_label.setObjectName("heading3")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"color: {design_system.colors.text_secondary};")
        layout.addWidget(title_label)

        # Description
        if description:
            desc_label = QLabel(description)
            desc_label.setObjectName("hint")
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setWordWrap(True)
            desc_label.setMaximumWidth(300)
            layout.addWidget(desc_label)

        # Action button
        if action_text:
            action_button = ModernButton(action_text, variant="primary")
            _ = action_button.clicked.connect(self.action_clicked.emit)
            layout.addWidget(action_button, 0, Qt.AlignmentFlag.AlignCenter)


class ThumbnailPlaceholder(QLabel):
    """Placeholder widget shown while thumbnail is loading."""

    def __init__(self, size: int = 200) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {design_system.colors.bg_tertiary};
                border: 2px dashed {design_system.colors.border_default};
                border-radius: {design_system.borders.radius_md}px;
            }}
        """)

        # Create shimmer effect animation
        self.shimmer_effect: QGraphicsOpacityEffect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.shimmer_effect)

        self.shimmer_animation: QPropertyAnimation = QPropertyAnimation(self.shimmer_effect, b"opacity")
        self.shimmer_animation.setDuration(1500)
        self.shimmer_animation.setStartValue(0.3)
        self.shimmer_animation.setEndValue(1.0)
        self.shimmer_animation.setLoopCount(-1)  # Infinite loop
        self.shimmer_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.shimmer_animation.start()

    def set_error(self) -> None:
        """Show error state."""
        self.shimmer_animation.stop()
        self.setText("❌\nFailed to load")
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {design_system.colors.bg_tertiary};
                border: 2px solid {design_system.colors.error};
                border-radius: {design_system.borders.radius_md}px;
                color: {design_system.colors.text_disabled};
            }}
        """)


class FloatingActionButton(QPushButton):
    """Material Design style floating action button."""

    def __init__(self, icon: str = "+", parent: QWidget | None = None) -> None:
        super().__init__(icon, parent)
        self._setup_style()
        self._setup_animations()
        self._position_button()

    def _setup_style(self) -> None:
        """Apply FAB styling."""
        self.setFixedSize(56, 56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {design_system.colors.primary};
                color: white;
                border: none;
                border-radius: 28px;
                font-size: 24px;
                font-weight: {design_system.typography.weight_bold};
            }}
            QPushButton:hover {{
                background-color: {design_system.colors.primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {design_system.colors.primary_pressed};
            }}
        """)

        # Add shadow
        # Third-party imports
        from PySide6.QtWidgets import QGraphicsDropShadowEffect

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

    def _setup_animations(self) -> None:
        """Set up hover animations."""
        self.hover_animation: QPropertyAnimation = QPropertyAnimation(self, b"geometry")
        self.hover_animation.setDuration(design_system.animation.duration_fast)
        self.hover_animation.setEasingCurve(QEasingCurve.Type.OutBack)

    def _position_button(self) -> None:
        """Position the FAB in bottom-right corner."""
        parent_widget = self.parent()
        if isinstance(parent_widget, QWidget):
            parent_rect = parent_widget.rect()
            x = parent_rect.width() - self.width() - 24
            y = parent_rect.height() - self.height() - 24
            self.move(x, y)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Scale up on hover."""
        current_rect = self.geometry()
        expanded_rect = QRect(
            current_rect.x() - 2,
            current_rect.y() - 2,
            current_rect.width() + 4,
            current_rect.height() + 4,
        )
        self.hover_animation.setStartValue(current_rect)
        self.hover_animation.setEndValue(expanded_rect)
        self.hover_animation.start()
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Scale back on leave."""
        current_rect = self.geometry()
        normal_rect = QRect(
            current_rect.x() + 2,
            current_rect.y() + 2,
            current_rect.width() - 4,
            current_rect.height() - 4,
        )
        self.hover_animation.setStartValue(current_rect)
        self.hover_animation.setEndValue(normal_rect)
        self.hover_animation.start()
        super().leaveEvent(event)
