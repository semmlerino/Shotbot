"""Progress management system for ShotBot application.

This module provides a comprehensive progress management system that integrates
with the existing NotificationManager to provide both blocking and non-blocking
progress indicators for long-running operations.

The ProgressManager supports:
    - Indeterminate progress for operations without known duration
    - Determinate progress with percentage for operations with known steps
    - Cancelable operations with proper cleanup callbacks
    - Nested progress for sub-operations within main operations
    - Status bar progress for non-blocking operations
    - Modal progress dialogs for blocking operations

Architecture:
    The ProgressManager uses a stack-based approach for nested operations and
    integrates seamlessly with Qt's signal-slot mechanism. It builds on top of
    the existing NotificationManager to provide a consistent user experience.

Examples:
    Basic usage with context manager:
        >>> with ProgressManager.operation(
        ...     "Loading shots", cancelable=True
        ... ) as progress:
        ...     progress.set_total(100)
        ...     for i in range(100):
        ...         if progress.is_cancelled():
        ...             break
        ...         progress.update(i, f"Processing shot {i}")

    Manual progress management:
        >>> progress = ProgressManager.start_operation("Scanning files")
        >>> progress.set_indeterminate()
        >>> # ... long operation ...
        >>> ProgressManager.finish_operation(success=True)

    Nested operations:
        >>> with ProgressManager.operation("Main operation") as main:
        ...     main.set_total(2)
        ...     with ProgressManager.operation("Sub-operation 1") as sub:
        ...         sub.set_total(50)
        ...         # ... work ...
        ...     main.update(1)
        ...     with ProgressManager.operation("Sub-operation 2") as sub:
        ...         # ... more work ...
        ...     main.update(2)

Type Safety:
    This module uses comprehensive type annotations with proper enum types and
    optional parameters for flexible progress operation management.

"""

from __future__ import annotations

# Standard library imports
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, ClassVar, final

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker

# Local application imports
from notification_manager import NotificationManager


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from PySide6.QtWidgets import (
        QProgressBar,
        QProgressDialog,
        QPushButton,
        QStatusBar,
    )

# Local application imports
from logging_mixin import get_module_logger


# Module-level logger
logger = get_module_logger(__name__)


@final
class ProgressType(Enum):
    """Types of progress displays available."""

    STATUS_BAR = auto()  # Non-blocking status bar progress
    MODAL_DIALOG = auto()  # Blocking modal progress dialog
    AUTO = auto()  # Automatic selection based on operation type


@final
@dataclass
class ProgressConfig:
    """Configuration for a progress operation."""

    title: str
    cancelable: bool = False
    progress_type: ProgressType = ProgressType.AUTO
    update_interval: int = 100  # Minimum ms between UI updates
    show_eta: bool = True
    cancel_callback: Callable[[], None] | None = None


@final
class ProgressOperation:
    """Represents a single progress operation with cancellation support.

    This class encapsulates all the state and behavior for a single progress
    operation, including progress tracking, cancellation, and UI updates.
    """

    def __init__(self, config: ProgressConfig) -> None:
        """Initialize a progress operation.

        Args:
            config: Configuration for this progress operation

        """
        super().__init__()
        self.config = config
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.current_value = 0
        self.total_value = 0
        self.is_indeterminate = True
        self.is_cancelled_flag = False
        self.current_message = config.title

        # UI elements (will be set by ProgressManager)
        self.progress_dialog: QProgressDialog | None = None
        self.status_bar: QStatusBar | None = None
        self.progress_bar: QProgressBar | None = None
        self.cancel_button: QPushButton | None = None

        # ETA calculation
        self.processing_times: list[float] = []
        self.max_eta_samples = 10

    def set_total(self, total: int) -> None:
        """Set the total number of steps for determinate progress.

        Args:
            total: Total number of steps in the operation

        """
        self.total_value = total
        self.is_indeterminate = False
        self._update_ui()

    def set_indeterminate(self) -> None:
        """Set progress to indeterminate mode (spinner)."""
        self.is_indeterminate = True
        self.total_value = 0
        self._update_ui()

    def update(self, value: int, message: str = "") -> None:
        """Update progress value and optional message.

        Args:
            value: Current progress value
            message: Optional status message

        """
        # Throttle updates to prevent UI blocking
        current_time = time.time()
        if (current_time - self.last_update_time) < (
            self.config.update_interval / 1000.0
        ):
            return

        old_value = self.current_value
        self.current_value = value
        if message:
            self.current_message = message

        # Calculate processing rate for ETA
        if not self.is_indeterminate and value > old_value:
            time_delta = current_time - self.last_update_time
            if time_delta > 0:
                value_delta = value - old_value
                rate = value_delta / time_delta
                self.processing_times.append(rate)
                # Keep only recent samples
                if len(self.processing_times) > self.max_eta_samples:
                    _ = self.processing_times.pop(0)

        self.last_update_time = current_time
        self._update_ui()

    def is_cancelled(self) -> bool:
        """Check if the operation has been cancelled.

        Returns:
            bool: True if operation was cancelled

        """
        return self.is_cancelled_flag

    def cancel(self) -> None:
        """Cancel the operation and trigger cleanup."""
        self.is_cancelled_flag = True

        # Call cancel callback if provided
        if self.config.cancel_callback:
            try:
                self.config.cancel_callback()
            except Exception:
                logger.exception("Error in cancel callback")

        logger.info(f"Progress operation cancelled: {self.config.title}")

    def get_eta_string(self) -> str:
        """Calculate and return ETA string.

        Returns:
            str: Human-readable ETA string or empty if not available

        """
        if (
            not self.config.show_eta
            or self.is_indeterminate
            or not self.processing_times
        ):
            return ""

        if self.current_value >= self.total_value:
            return ""

        # Calculate average processing rate
        avg_rate = sum(self.processing_times) / len(self.processing_times)
        if avg_rate <= 0:
            return ""

        remaining = self.total_value - self.current_value
        eta_seconds = remaining / avg_rate

        # Format ETA string
        if eta_seconds < 60:
            return f"~{int(eta_seconds)}s remaining"
        if eta_seconds < 3600:
            minutes = int(eta_seconds / 60)
            return f"~{minutes}m remaining"
        hours = int(eta_seconds / 3600)
        minutes = int((eta_seconds % 3600) / 60)
        return f"~{hours}h {minutes}m remaining"

    def _update_ui(self) -> None:
        """Update the UI elements associated with this operation."""
        # Update progress dialog if present
        if self.progress_dialog:
            if self.is_indeterminate:
                self.progress_dialog.setRange(0, 0)  # Indeterminate
            else:
                self.progress_dialog.setRange(0, self.total_value)
                self.progress_dialog.setValue(self.current_value)

            # Update message with ETA
            display_message = self.current_message
            eta = self.get_eta_string()
            if eta:
                display_message += f" ({eta})"

            self.progress_dialog.setLabelText(display_message)

        # Update status bar if present - check it's not None (Qt lifecycle safety)
        if self.status_bar is not None:
            try:
                display_message = self.current_message

                if not self.is_indeterminate:
                    percentage = (
                        (self.current_value / self.total_value) * 100
                        if self.total_value > 0
                        else 0
                    )
                    display_message += f" ({percentage:.1f}%)"

                eta = self.get_eta_string()
                if eta:
                    display_message += f" - {eta}"

                self.status_bar.showMessage(display_message)
            except RuntimeError:
                # Status bar was deleted - clear reference
                self.status_bar = None


@final
class ProgressManager:
    """Centralized progress management system.

    This singleton class provides various types of progress indicators and
    manages a stack of nested operations. It integrates with the existing
    NotificationManager for consistent user experience.
    """

    _cleanup_order: ClassVar[int] = 15
    _singleton_description: ClassVar[str] = "Progress dialogs and operation tracking"

    _instance: ClassVar[ProgressManager | None] = None
    _operation_stack: ClassVar[list[ProgressOperation]] = []
    _stack_lock: ClassVar[QMutex] = QMutex()  # Thread safety for operation stack
    _status_bar: ClassVar[QStatusBar | None] = None

    def __new__(cls) -> ProgressManager:
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        ProgressManager._operation_stack = []
        ProgressManager._status_bar = None
        logger.debug("ProgressManager initialized")

    @classmethod
    def get_instance(cls) -> ProgressManager:
        """Get the singleton instance.

        This method provides a consistent API with other singleton managers
        like ProcessPoolManager and FilesystemCoordinator.

        Returns:
            ProgressManager: The singleton instance

        Examples:
            >>> manager = ProgressManager.get_instance()
            >>> # Equivalent to: manager = ProgressManager()

        """
        return cls()  # Calls __new__() which returns the singleton

    @classmethod
    def initialize(cls, status_bar: QStatusBar) -> ProgressManager:
        """Initialize the progress manager with UI references.

        Args:
            status_bar: Status bar for displaying progress messages

        Returns:
            ProgressManager: The initialized singleton instance

        """
        instance = cls()
        cls._status_bar = status_bar
        logger.debug("ProgressManager initialized with status bar reference")
        return instance

    @staticmethod
    def _get_status_bar() -> QStatusBar | None:
        """Lazily get status bar from NotificationManager.

        If initialize() was called with an explicit status bar, that takes
        precedence. Otherwise, falls through to NotificationManager.
        """
        if ProgressManager._status_bar is not None:
            return ProgressManager._status_bar
        return NotificationManager.get_status_bar()

    @classmethod
    @contextmanager
    def operation(
        cls,
        title: str,
        cancelable: bool = False,
        progress_type: ProgressType = ProgressType.AUTO,
        update_interval: int = 100,
        show_eta: bool = True,
        cancel_callback: Callable[[], None] | None = None,
    ) -> Iterator[ProgressOperation]:
        """Context manager for progress operations.

        Args:
            title: Title/description of the operation
            cancelable: Whether the operation can be cancelled
            progress_type: Type of progress display to use
            update_interval: Minimum milliseconds between UI updates
            show_eta: Whether to show estimated time remaining
            cancel_callback: Optional callback when operation is cancelled

        Yields:
            ProgressOperation: The progress operation object

        Examples:
            >>> with ProgressManager.operation(
            ...     "Loading files", cancelable=True
            ... ) as progress:
            ...     progress.set_total(100)
            ...     for i in range(100):
            ...         if progress.is_cancelled():
            ...             break
            ...         progress.update(i, f"Loading file {i}")

        """
        config = ProgressConfig(
            title=title,
            cancelable=cancelable,
            progress_type=progress_type,
            update_interval=update_interval,
            show_eta=show_eta,
            cancel_callback=cancel_callback,
        )

        operation = cls.start_operation(config)
        try:
            yield operation
            # Operation completed successfully
            cls.finish_operation(success=True)
        except Exception as e:
            # Operation failed
            cls.finish_operation(success=False, error_message=str(e))
            raise

    @classmethod
    def start_operation(cls, config: ProgressConfig | str) -> ProgressOperation:
        """Start a new progress operation.

        Args:
            config: Progress configuration or simple title string

        Returns:
            ProgressOperation: The started operation

        """
        instance = cls()

        # Handle simple string title
        if isinstance(config, str):
            config = ProgressConfig(title=config)

        operation = ProgressOperation(config)
        with QMutexLocker(cls._stack_lock):
            instance._operation_stack.append(operation)

        # Determine progress type
        progress_type = config.progress_type
        if progress_type == ProgressType.AUTO:
            # Use modal dialog for blocking operations, status bar for others
            # Heuristic: if operation is cancelable, it's probably long-running
            progress_type = (
                ProgressType.MODAL_DIALOG
                if config.cancelable
                else ProgressType.STATUS_BAR
            )

        # Create appropriate UI
        if progress_type == ProgressType.MODAL_DIALOG:
            operation.progress_dialog = NotificationManager.progress(
                title=config.title,
                message=config.title,
                cancelable=config.cancelable,
                callback=operation.cancel if config.cancelable else None,
            )
        elif progress_type == ProgressType.STATUS_BAR:
            operation.status_bar = cls._get_status_bar()
            if operation.status_bar is not None:
                try:
                    operation.status_bar.showMessage(config.title)
                except RuntimeError:
                    # Status bar was deleted - clear reference
                    operation.status_bar = None

        logger.debug(
            f"Started progress operation: {config.title} (type: {progress_type.name})"
        )
        return operation

    @classmethod
    def finish_operation(cls, success: bool = True, error_message: str = "") -> None:
        """Finish the current progress operation.

        Args:
            success: Whether the operation completed successfully
            error_message: Optional error message if operation failed

        """
        instance = cls()

        with QMutexLocker(cls._stack_lock):
            if not instance._operation_stack:
                logger.warning("Attempted to finish operation but stack is empty")
                return
            operation = instance._operation_stack.pop()

        # Close UI elements
        if operation.progress_dialog:
            NotificationManager.close_progress()

        # Show completion notification
        if success:
            if operation.is_cancelled():
                NotificationManager.info(f"{operation.config.title} cancelled")
            else:
                elapsed = time.time() - operation.start_time
                elapsed_str = (
                    f"({elapsed:.1f}s)" if elapsed < 60 else f"({elapsed / 60:.1f}m)"
                )
                NotificationManager.success(
                    f"{operation.config.title} completed {elapsed_str}"
                )
        else:
            NotificationManager.error(
                "Operation Failed", f"{operation.config.title} failed", error_message
            )

        logger.debug(
            f"Finished progress operation: {operation.config.title} (success: {success})"
        )

    @classmethod
    def get_current_operation(cls) -> ProgressOperation | None:
        """Get the current (top-level) progress operation.

        Returns:
            ProgressOperation | None: Current operation or None if stack is empty

        """
        instance = cls()
        with QMutexLocker(cls._stack_lock):
            return instance._operation_stack[-1] if instance._operation_stack else None

    @classmethod
    def cancel_current_operation(cls) -> bool:
        """Cancel the current progress operation.

        Returns:
            bool: True if an operation was cancelled, False if no operation active

        """
        operation = cls.get_current_operation()
        if operation and operation.config.cancelable:
            operation.cancel()
            return True
        return False

    @classmethod
    def is_operation_active(cls) -> bool:
        """Check if any progress operation is currently active.

        Returns:
            bool: True if operations are active, False otherwise

        """
        instance = cls()
        with QMutexLocker(cls._stack_lock):
            return len(instance._operation_stack) > 0

    @classmethod
    def clear_all_operations(cls) -> None:
        """Clear all active operations (emergency cleanup)."""
        instance = cls()

        # Take snapshot and clear under lock, then operate on snapshot
        with QMutexLocker(cls._stack_lock):
            operations_snapshot = list(instance._operation_stack)
            instance._operation_stack.clear()

        # Cancel all operations (outside lock to avoid holding lock during callbacks)
        for operation in operations_snapshot:
            if operation.config.cancelable:
                operation.cancel()

        # Close any open dialogs
        NotificationManager.close_progress()

        logger.warning("All progress operations cleared (emergency cleanup)")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY.

        This method clears all progress state and resets the singleton instance.
        It should only be used in test cleanup to ensure test isolation.
        """
        # Take snapshot and clear under lock
        with QMutexLocker(cls._stack_lock):
            operations_snapshot = list(cls._operation_stack)
            cls._operation_stack.clear()

        # Clear all active operations (outside lock to avoid holding during callbacks)
        if cls._instance is not None:
            for operation in operations_snapshot:
                if operation.config.cancelable:
                    operation.cancel()
                if operation.progress_dialog:
                    NotificationManager.close_progress()

        # Reset class variables (under lock to prevent race with start_operation)
        with QMutexLocker(cls._stack_lock):
            cls._instance = None
            # Use clear() again instead of reassignment to avoid orphaning
            # any operations added between first lock release and now
            cls._operation_stack.clear()
            cls._status_bar = None

        logger.debug("ProgressManager reset for testing")


# Convenience functions for easier usage throughout the application
def start_progress(title: str, cancelable: bool = False) -> ProgressOperation:
    """Start a simple progress operation."""
    return ProgressManager.start_operation(
        ProgressConfig(title=title, cancelable=cancelable)
    )


def finish_progress(success: bool = True, error_message: str = "") -> None:
    """Finish the current progress operation."""
    ProgressManager.finish_operation(success, error_message)


def update_progress(value: int, message: str = "") -> None:
    """Update the current progress operation."""
    operation = ProgressManager.get_current_operation()
    if operation:
        operation.update(value, message)


def set_progress_total(total: int) -> None:
    """Set total for the current progress operation."""
    operation = ProgressManager.get_current_operation()
    if operation:
        operation.set_total(total)


def set_progress_indeterminate() -> None:
    """Set current progress operation to indeterminate."""
    operation = ProgressManager.get_current_operation()
    if operation:
        operation.set_indeterminate()


def is_progress_cancelled() -> bool:
    """Check if current progress operation is cancelled."""
    operation = ProgressManager.get_current_operation()
    return operation.is_cancelled() if operation else False
