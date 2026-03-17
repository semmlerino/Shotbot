"""Notification system for ShotBot application.

This module provides a notification system using Qt widgets for user feedback
throughout the application. The NotificationManager class handles different
types of notifications including modal dialogs and status bar messages.

The system supports:
    - Error: QMessageBox.critical() for serious errors
    - Warning: QMessageBox.warning() for issues
    - Info: Status bar message for information
    - Success: Status bar with green text/icon
    - Progress: QProgressDialog for long operations

Architecture:
    The NotificationManager uses a singleton pattern for easy access throughout
    the application. All notifications are properly themed and include
    appropriate icons.

Examples:
    Basic usage:
        >>> NotificationManager.error(
        ...     "Failed to launch Nuke", "Application not found in PATH"
        ... )
        >>> NotificationManager.success("Shots refreshed successfully")
        >>> NotificationManager.progress("Loading 3DE scenes...", cancelable=True)

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
    QObject,
    QTimer,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStatusBar,
)

# Local application imports
from logging_mixin import get_module_logger


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
class NotificationManager(QObject):
    """Centralized notification management system.

    This singleton class provides various types of notifications:
    - Modal dialogs for critical errors and warnings
    - Status bar messages for general information
    - Progress dialogs for long-running operations

    The manager maintains references to the main window and status bar
    for proper integration with the application UI.
    """

    _cleanup_order: ClassVar[int] = 10
    _singleton_description: ClassVar[str] = "Status bar messaging and modal dialogs"

    _instance: ClassVar[NotificationManager | None] = None
    _main_window: ClassVar[QMainWindow | None] = None
    _status_bar: ClassVar[QStatusBar | None] = None
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
                cls._current_progress.deleteLater()
            except RuntimeError:
                # Qt C++ object already deleted
                pass
            cls._current_progress = None
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

        # Schedule the QObject for deletion before clearing the reference.
        # Without deleteLater(), the C++ object stays alive but unreachable,
        # causing crashes during Qt's deferred-delete flush at teardown.
        if cls._instance is not None:
            try:
                cls._instance.deleteLater()
            except RuntimeError:
                # C++ object already deleted
                pass

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

        parent = cls._main_window or None
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
    def get_status_bar(cls) -> QStatusBar | None:
        """Get the current status bar reference."""
        return cls._status_bar
