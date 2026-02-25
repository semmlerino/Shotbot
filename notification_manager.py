"""Notification system for ShotBot application.

This module provides a comprehensive notification system using Qt widgets for better
user feedback throughout the application. The NotificationManager class handles
different types of notifications including modal dialogs, status bar messages,
and non-blocking toast-style notifications.

The system supports:
    - Error: QMessageBox.critical() for serious errors
    - Warning: QMessageBox.warning() for issues
    - Info: Status bar message for information
    - Success: Status bar with green text/icon
    - Progress: QProgressDialog for long operations
    - Toast: Semi-transparent overlay notifications

Architecture:
    The NotificationManager uses a singleton pattern for easy access throughout
    the application. Toast notifications are stacked and auto-dismiss after a
    configurable timeout. All notifications are properly themed and include
    appropriate icons.

Examples:
    Basic usage:
        >>> NotificationManager.error(
        ...     "Failed to launch Nuke", "Application not found in PATH"
        ... )
        >>> NotificationManager.success("Shots refreshed successfully")
        >>> NotificationManager.progress("Loading 3DE scenes...", cancelable=True)

    Toast notifications:
        >>> NotificationManager.toast("File saved", NotificationType.SUCCESS)
        >>> NotificationManager.toast(
        ...     "Cache cleared", NotificationType.INFO, duration=3000
        ... )

Type Safety:
    This module uses comprehensive type annotations and enum types for
    notification categories to ensure type-safe usage throughout the application.

"""

from __future__ import annotations

from collections.abc import Callable

# Standard library imports
from enum import Enum, auto
from typing import TYPE_CHECKING, ClassVar, final

# Third-party imports
from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStatusBar,
    QWidget,
)

# Local application imports
from design_system import design_system
from logging_mixin import get_module_logger
from typing_compat import override


# Module-level logger
logger = get_module_logger(__name__)

if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable


class NotificationType(Enum):
    """Enumeration of notification types with associated styling."""

    ERROR = auto()
    WARNING = auto()
    INFO = auto()
    SUCCESS = auto()
    PROGRESS = auto()


@final
class ToastNotification(QFrame):
    """Semi-transparent toast-style notification widget.

    Features:
        - Auto-dismiss after configurable timeout
        - Click to dismiss functionality
        - Smooth fade-in/out animations
        - Proper stacking for multiple notifications
        - Themed styling with icons
    """

    # Signal emitted when toast is dismissed
    dismissed = Signal()

    def __init__(
        self,
        message: str,
        notification_type: NotificationType,
        duration: int = 4000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.notification_type = notification_type
        self.duration = duration
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Set up UI
        self._setup_ui(message)
        self._setup_styling()
        self._setup_animations()

        # Auto-dismiss timer
        self.dismiss_timer = QTimer()
        self.dismiss_timer.setSingleShot(True)
        _ = self.dismiss_timer.timeout.connect(self.dismiss)

        # Start timer if duration > 0
        if self.duration > 0:
            self.dismiss_timer.start(self.duration)

    def _setup_ui(self, message: str) -> None:
        """Set up the toast UI elements."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)

        # Icon
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setScaledContents(True)
        layout.addWidget(self.icon_label)

        # Message
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(self.message_label, 1)

        # Close button
        self.close_button = QPushButton("x")
        self.close_button.setFixedSize(20, 20)
        _ = self.close_button.clicked.connect(self.dismiss)
        self.close_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: white;
                font-weight: bold;
                font-size: {design_system.typography.size_h3}px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.2);
                border-radius: 10px;
            }}
        """)
        layout.addWidget(self.close_button)

        self.setLayout(layout)

    def _setup_styling(self) -> None:
        """Apply styling based on notification type."""
        # Color scheme based on type
        colors = {
            NotificationType.ERROR: "#e74c3c",  # Red
            NotificationType.WARNING: "#f39c12",  # Orange
            NotificationType.INFO: "#3498db",  # Blue
            NotificationType.SUCCESS: "#2ecc71",  # Green
            NotificationType.PROGRESS: "#9b59b6",  # Purple
        }

        # Icon names for each type
        icon_chars = {
            NotificationType.ERROR: "✗",
            NotificationType.WARNING: "⚠",
            NotificationType.INFO: "i",
            NotificationType.SUCCESS: "✓",
            NotificationType.PROGRESS: "⟳",
        }

        bg_color = colors.get(self.notification_type, "#3498db")
        icon_char = icon_chars.get(self.notification_type, "i")

        # Set background color with transparency
        self.setStyleSheet(f"""
            ToastNotification {{
                background-color: {bg_color};
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.3);
            }}
        """)

        # Set icon
        self.icon_label.setText(icon_char)
        self.icon_label.setStyleSheet(f"""
            color: white;
            font-size: {design_system.typography.size_h3}px;
            font-weight: bold;
            text-align: center;
        """)

        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

    def _setup_animations(self) -> None:
        """Set up fade-in/out animations."""
        self.fade_in = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in.setDuration(300)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(0.95)
        self.fade_in.setEasingCurve(QEasingCurve.Type.OutQuad)

        self.fade_out = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out.setDuration(200)
        self.fade_out.setStartValue(0.95)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InQuad)
        _ = self.fade_out.finished.connect(self._on_fade_out_finished)

    def show_animated(self) -> None:
        """Show the toast with fade-in animation."""
        self.show()
        self.fade_in.start()

    def dismiss(self) -> None:
        """Dismiss the toast with fade-out animation."""
        if self.dismiss_timer.isActive():
            self.dismiss_timer.stop()

        self.fade_out.start()

    def _on_fade_out_finished(self) -> None:
        """Handle fade-out animation completion."""
        self.hide()
        self.dismissed.emit()
        self.deleteLater()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse clicks to dismiss the toast."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dismiss()
        super().mousePressEvent(event)


@final
class NotificationManager(QObject):
    """Centralized notification management system.

    This singleton class provides various types of notifications:
    - Modal dialogs for critical errors and warnings
    - Status bar messages for general information
    - Toast notifications for non-blocking feedback
    - Progress dialogs for long-running operations

    The manager maintains references to the main window and status bar
    for proper integration with the application UI.
    """

    _instance: ClassVar[NotificationManager | None] = None
    _main_window: ClassVar[QMainWindow | None] = None
    _status_bar: ClassVar[QStatusBar | None] = None
    _active_toasts: ClassVar[list[ToastNotification]] = []
    _current_progress: ClassVar[QProgressDialog | None] = None

    @staticmethod
    def _is_qt_object_valid(obj: QObject | None) -> bool:
        """Check if a Qt object's C++ counterpart is still valid.

        When a Qt C++ object is deleted but the Python wrapper still exists,
        accessing any method will raise RuntimeError. This helper detects that
        condition by attempting a safe operation.

        Args:
            obj: The Qt object to check

        Returns:
            True if the object exists and its C++ counterpart is valid

        """
        if obj is None:
            return False
        try:
            # Try accessing a property that exists on all QObjects
            # If the C++ object is deleted, this will raise RuntimeError
            _ = obj.objectName()
            return True
        except RuntimeError:
            return False

    @staticmethod
    def _can_show_dialog() -> bool:
        """Check if it's safe to show a modal dialog.

        Returns False if:
        - QApplication.instance() is None (app not running or shutting down)
        - QApplication C++ object is deleted
        - Application is in teardown (closingDown)

        This prevents crashes during test teardown when Qt is being cleaned up.
        """
        try:
            app = QApplication.instance()
            if app is None:
                return False
            # Check if app is being torn down
            if app.closingDown():
                return False
            # Try to access a property to verify C++ object is valid
            _ = app.applicationName()
            return True
        except (RuntimeError, AttributeError):
            return False

    def __new__(cls) -> NotificationManager:
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        super().__init__()
        self._initialized = True
        logger.debug("NotificationManager initialized")

    @classmethod
    def initialize(
        cls, main_window: QMainWindow, status_bar: QStatusBar
    ) -> NotificationManager:
        """Initialize the notification manager with UI references.

        Args:
            main_window: Main application window for parenting dialogs
            status_bar: Status bar for displaying messages

        Returns:
            NotificationManager: The initialized singleton instance

        """
        instance = cls()
        cls._main_window = main_window
        cls._status_bar = status_bar
        logger.debug("NotificationManager initialized with UI references")
        return instance

    @classmethod
    def cleanup(cls) -> None:
        """Clean up the notification manager resources.

        This should be called during test teardown or application shutdown
        to prevent access to deleted Qt objects.
        """
        cls._main_window = None
        cls._status_bar = None
        if cls._current_progress:
            try:
                _ = cls._current_progress.close()
            except RuntimeError:
                # Qt C++ object already deleted
                pass
            cls._current_progress = None
        for toast in cls._active_toasts:
            try:
                _ = toast.close()
            except RuntimeError:
                # Qt C++ object already deleted
                pass
        cls._active_toasts.clear()
        if cls._instance:
            logger.debug("NotificationManager cleaned up")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY.

        This method clears all notification state and resets the singleton instance.
        It should only be used in test cleanup to ensure test isolation.

        Note: This class uses a custom singleton pattern (not SingletonMixin) because
        it needs to inherit from QObject for Qt signal/slot functionality. The
        SingletonRegistry calls this reset() method directly during test cleanup.
        """
        # Clean up all resources
        cls.cleanup()

        # Reset singleton instance
        cls._instance = None

        logger.debug("NotificationManager reset for testing")

    @classmethod
    def error(cls, title: str, message: str = "", details: str = "") -> None:
        """Show a critical error dialog.

        Args:
            title: Error title/summary
            message: Detailed error message
            details: Optional technical details

        """
        # Always log the error first
        logger.error(f"Error notification: {title} - {message} - {details}")

        # Skip dialog if Qt is shutting down (prevents crashes during test teardown)
        if not cls._can_show_dialog():
            return

        full_message = message
        if details:
            full_message += f"\n\nDetails: {details}"

        # Use valid main window as parent, or None if not available
        parent = cls._main_window if cls._is_qt_object_valid(cls._main_window) else None
        try:
            _ = QMessageBox.critical(parent, f"Error - {title}", full_message or title)
        except RuntimeError:
            # C++ object deleted during dialog creation - just log, don't retry
            cls._main_window = None

    @classmethod
    def warning(cls, title: str, message: str = "", details: str = "") -> None:
        """Show a warning dialog.

        Args:
            title: Warning title/summary
            message: Detailed warning message
            details: Optional technical details

        """
        # Always log the warning first
        logger.warning(f"Warning notification: {title} - {message} - {details}")

        # Skip dialog if Qt is shutting down (prevents crashes during test teardown)
        if not cls._can_show_dialog():
            return

        full_message = message
        if details:
            full_message += f"\n\nDetails: {details}"

        # Use valid main window as parent, or None if not available
        parent = cls._main_window if cls._is_qt_object_valid(cls._main_window) else None
        try:
            _ = QMessageBox.warning(parent, f"Warning - {title}", full_message or title)
        except RuntimeError:
            # C++ object deleted during dialog creation - just log, don't retry
            cls._main_window = None

    @classmethod
    def info(cls, message: str, timeout: int = 3000) -> None:
        """Show an info message in the status bar.

        Args:
            message: Information message to display
            timeout: Duration in milliseconds (0 = permanent)

        """
        if cls._is_qt_object_valid(cls._status_bar):
            assert cls._status_bar is not None  # Type narrowing for pyright
            try:
                cls._status_bar.showMessage(message, timeout)
            except RuntimeError:
                # C++ object deleted between validity check and access
                cls._status_bar = None

        if cls._instance:
            logger.info(f"Info notification: {message}")

    @classmethod
    def success(cls, message: str, timeout: int = 3000) -> None:
        """Show a success message in the status bar with green styling.

        Args:
            message: Success message to display
            timeout: Duration in milliseconds (0 = permanent)

        """
        if cls._is_qt_object_valid(cls._status_bar):
            assert cls._status_bar is not None  # Type narrowing for pyright
            try:
                # Apply green styling for success messages
                original_style = cls._status_bar.styleSheet()
                cls._status_bar.setStyleSheet("""
                    QStatusBar {
                        color: #2ecc71;
                        font-weight: bold;
                    }
                """)
                cls._status_bar.showMessage(f"✓ {message}", timeout)

                # Restore original styling after timeout
                if timeout > 0:

                    def restore_style() -> None:
                        try:
                            if cls._is_qt_object_valid(cls._status_bar):
                                assert cls._status_bar is not None  # Type narrowing
                                cls._status_bar.setStyleSheet(original_style)
                        except RuntimeError:
                            # Status bar was deleted, ignore
                            cls._status_bar = None

                    QTimer.singleShot(timeout, restore_style)
            except RuntimeError:
                # C++ object deleted between validity check and access
                cls._status_bar = None

        if cls._instance:
            logger.info(f"Success notification: {message}")

    @classmethod
    def progress(
        cls,
        title: str,
        message: str = "",
        cancelable: bool = False,
        callback: Callable[[], None] | None = None,
    ) -> QProgressDialog:
        """Show a progress dialog for long operations.

        Args:
            title: Progress dialog title
            message: Progress message
            cancelable: Whether the operation can be canceled
            callback: Optional callback function for cancel button

        Returns:
            QProgressDialog: The progress dialog instance

        """
        # Close existing progress dialog
        if cls._current_progress:
            _ = cls._current_progress.close()

        parent = cls._main_window if cls._main_window else None
        progress = QProgressDialog(
            message or title, "Cancel" if cancelable else "", 0, 0, parent
        )
        progress.setWindowTitle(title)
        progress.setModal(True)
        progress.setMinimumDuration(500)  # Show after 500ms

        if not cancelable:
            progress.setCancelButton(None)
        elif callback:
            _ = progress.canceled.connect(callback)

        progress.show()
        cls._current_progress = progress

        if cls._instance:
            logger.info(f"Progress dialog shown: {title}")
        return progress

    @classmethod
    def close_progress(cls) -> None:
        """Close the current progress dialog."""
        if cls._current_progress:
            _ = cls._current_progress.close()
            cls._current_progress = None

    @classmethod
    def toast(
        cls,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        duration: int = 4000,
    ) -> None:
        """Show a non-blocking toast notification.

        Args:
            message: Message to display
            notification_type: Type of notification (affects styling)
            duration: Auto-dismiss time in milliseconds (0 = no auto-dismiss)

        """
        if not cls._is_qt_object_valid(cls._main_window):
            # Clear stale reference if C++ object was deleted
            if cls._main_window is not None:
                cls._main_window = None
            if cls._instance:
                logger.warning(
                    "Cannot show toast notification: no valid main window reference"
                )
            return

        try:
            # Create toast
            toast = ToastNotification(
                message, notification_type, duration, cls._main_window
            )
            _ = toast.dismissed.connect(lambda: cls._remove_toast(toast))

            # Position the toast
            cls._position_toast(toast)

            # Add to active toasts and show
            cls._active_toasts.append(toast)
            toast.show_animated()
        except RuntimeError:
            # C++ object deleted during toast creation
            cls._main_window = None
            logger.warning("Main window deleted during toast creation")

        if cls._instance:
            logger.debug(
                f"Toast notification shown: {message} ({notification_type.name})"
            )

    @classmethod
    def _position_toast(cls, toast: ToastNotification) -> None:
        """Position a toast notification on screen."""
        if not cls._is_qt_object_valid(cls._main_window):
            return

        assert cls._main_window is not None  # Type narrowing for pyright
        try:
            # Get main window geometry
            main_rect = cls._main_window.geometry()

            # Calculate position (top-right corner with margin)
            margin = 20
            toast_width = 350
            toast_height = 60

            # Stack toasts vertically
            y_offset = margin + len(cls._active_toasts) * (toast_height + 10)

            x = main_rect.x() + main_rect.width() - toast_width - margin
            y = main_rect.y() + y_offset

            toast.setGeometry(x, y, toast_width, toast_height)
        except RuntimeError:
            # C++ object deleted during positioning
            cls._main_window = None

    @classmethod
    def _remove_toast(cls, toast: ToastNotification) -> None:
        """Remove a toast from the active list."""
        if toast in cls._active_toasts:
            cls._active_toasts.remove(toast)

            # Reposition remaining toasts
            cls._reposition_toasts()

    @classmethod
    def _reposition_toasts(cls) -> None:
        """Reposition all active toasts after one is removed."""
        for i, toast in enumerate(cls._active_toasts):
            if not cls._is_qt_object_valid(cls._main_window):
                continue

            assert cls._main_window is not None  # Type narrowing for pyright
            try:
                main_rect = cls._main_window.geometry()
                margin = 20
                toast_width = 350
                toast_height = 60

                y_offset = margin + i * (toast_height + 10)
                x = main_rect.x() + main_rect.width() - toast_width - margin
                y = main_rect.y() + y_offset

                # Animate to new position
                animation = QPropertyAnimation(toast, b"geometry")
                animation.setDuration(200)
                animation.setStartValue(toast.geometry())
                animation.setEndValue(QRect(x, y, toast_width, toast_height))
                animation.setEasingCurve(QEasingCurve.Type.OutQuad)
                animation.start()
            except RuntimeError:
                # C++ object deleted during repositioning
                cls._main_window = None
                break

    @classmethod
    def clear_all_toasts(cls) -> None:
        """Dismiss all active toast notifications."""
        for toast in cls._active_toasts[
            :
        ]:  # Copy list to avoid modification during iteration
            toast.dismiss()

    @classmethod
    def get_status_bar(cls) -> QStatusBar | None:
        """Get the current status bar reference."""
        return cls._status_bar


# Convenience functions for easier usage throughout the application
def error(title: str, message: str = "", details: str = "") -> None:
    """Show an error notification."""
    NotificationManager.error(title, message, details)


def warning(title: str, message: str = "", details: str = "") -> None:
    """Show a warning notification."""
    NotificationManager.warning(title, message, details)


def info(message: str, timeout: int = 3000) -> None:
    """Show an info message."""
    NotificationManager.info(message, timeout)


def success(message: str, timeout: int = 3000) -> None:
    """Show a success message."""
    NotificationManager.success(message, timeout)


def progress(
    title: str, message: str = "", cancelable: bool = False
) -> QProgressDialog:
    """Show a progress dialog."""
    return NotificationManager.progress(title, message, cancelable)


def toast(
    message: str,
    notification_type: NotificationType = NotificationType.INFO,
    duration: int = 4000,
) -> None:
    """Show a toast notification."""
    NotificationManager.toast(message, notification_type, duration)
