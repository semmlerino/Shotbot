"""Progress management system for ShotBot application.

Provides a status-bar progress indicator for long-running operations.
Integrates with NotificationManager for consistent user experience.

Usage:
    # Manual start/finish:
    op = ProgressManager.start_operation("Scanning files", total=100)
    for i in range(100):
        if ProgressManager.is_cancelled():
            break
        ProgressManager.update(i, f"Processing {i}")
    ProgressManager.finish_operation()

    # Context manager:
    with ProgressManager.operation("Loading shots", total=50) as op:
        for i in range(50):
            if op.is_cancelled():
                break
            op.update(i)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, final

from PySide6.QtCore import QMutex, QMutexLocker

from managers.notification_manager import NotificationManager


if TYPE_CHECKING:
    from collections.abc import Iterator

    from PySide6.QtWidgets import QStatusBar

from logging_mixin import get_module_logger


logger = get_module_logger(__name__)


@final
class ProgressOperation:
    """Internal state for a single progress operation."""

    def __init__(self, label: str, total: int) -> None:
        self.label = label
        self.total = total
        self.current = 0
        self.message = label
        self.cancelled = False
        self.start_time = time.time()

    def set_total(self, total: int) -> None:
        """Set (or update) the total step count."""
        self.total = total
        ProgressManager.update_status_bar(self)

    def update(self, value: int, message: str = "") -> None:
        """Update current progress value and optional message."""
        self.current = value
        if message:
            self.message = message
        ProgressManager.update_status_bar(self)

    def is_cancelled(self) -> bool:
        """Return True if the operation was cancelled."""
        return self.cancelled

    def cancel(self) -> None:
        """Mark the operation as cancelled."""
        self.cancelled = True
        logger.info(f"Progress operation cancelled: {self.label}")


@final
class ProgressManager:
    """Centralized, singleton progress indicator backed by the status bar."""

    _cleanup_order: ClassVar[int] = 15
    _singleton_description: ClassVar[str] = "Progress dialogs and operation tracking"

    _instance: ClassVar[ProgressManager | None] = None
    _operation_stack: ClassVar[list[ProgressOperation]] = []
    _stack_lock: ClassVar[QMutex] = QMutex()
    _status_bar: ClassVar[QStatusBar | None] = None

    def __new__(cls) -> ProgressManager:
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
        """Return the singleton instance."""
        return cls()

    @classmethod
    def initialize(cls, status_bar: QStatusBar) -> ProgressManager:
        """Attach the status bar for progress display.

        Args:
            status_bar: Status bar widget to display progress messages.

        Returns:
            The singleton instance.
        """
        instance = cls()
        cls._status_bar = status_bar
        logger.debug("ProgressManager initialized with status bar reference")
        return instance

    @staticmethod
    def _get_status_bar() -> QStatusBar | None:
        if ProgressManager._status_bar is not None:
            return ProgressManager._status_bar
        return NotificationManager.get_status_bar()

    @staticmethod
    def update_status_bar(op: ProgressOperation) -> None:
        """Push a status bar message for the given operation."""
        sb = ProgressManager._get_status_bar()
        if sb is None:
            return
        try:
            if op.total > 0:
                pct = (op.current / op.total) * 100
                sb.showMessage(f"{op.message} ({pct:.1f}%)")
            else:
                sb.showMessage(op.message)
        except RuntimeError:
            # Status bar widget was deleted; clear cached reference
            ProgressManager._status_bar = None

    @classmethod
    def start_operation(cls, label: str, total: int = 0) -> ProgressOperation:
        """Start a new progress operation and push it onto the stack.

        Args:
            label: Human-readable description of the operation.
            total: Total number of steps (0 = indeterminate).

        Returns:
            The new operation object.
        """
        _ = cls()  # ensure singleton is initialized
        op = ProgressOperation(label, total)
        with QMutexLocker(cls._stack_lock):
            cls._operation_stack.append(op)
        sb = cls._get_status_bar()
        if sb is not None:
            try:
                sb.showMessage(label)
            except RuntimeError:
                cls._status_bar = None
        logger.debug(f"Started progress operation: {label}")
        return op

    @classmethod
    def update(cls, value: int, message: str = "") -> None:
        """Update the current (top) progress operation.

        No-op if no operation is active.

        Args:
            value: Current progress value.
            message: Optional status message.
        """
        op = cls.get_current_operation()
        if op is not None:
            op.update(value, message)

    @classmethod
    def finish_operation(cls, success: bool = True, error_message: str = "") -> None:
        """Pop and finish the current progress operation.

        Args:
            success: True if the operation completed successfully.
            error_message: Optional error detail shown on failure.
        """
        _ = cls()  # ensure singleton is initialized
        with QMutexLocker(cls._stack_lock):
            if not cls._operation_stack:
                logger.warning("Attempted to finish operation but stack is empty")
                return
            op = cls._operation_stack.pop()

        if success:
            if op.cancelled:
                NotificationManager.info(f"{op.label} cancelled")
            else:
                elapsed = time.time() - op.start_time
                elapsed_str = (
                    f"({elapsed:.1f}s)" if elapsed < 60 else f"({elapsed / 60:.1f}m)"
                )
                NotificationManager.success(f"{op.label} completed {elapsed_str}")
        else:
            NotificationManager.error("Operation Failed", f"{op.label} failed", error_message)

        logger.debug(f"Finished progress operation: {op.label} (success: {success})")

    @classmethod
    def is_cancelled(cls) -> bool:
        """Return True if the current operation has been cancelled.

        Returns False when no operation is active.
        """
        op = cls.get_current_operation()
        return op.is_cancelled() if op is not None else False

    @classmethod
    @contextmanager
    def operation(
        cls,
        label: str,
        total: int = 0,
        cancelable: bool = False,
    ) -> Iterator[ProgressOperation]:
        """Context manager for a progress operation.

        Args:
            label: Human-readable description.
            total: Total steps (0 = indeterminate).
            cancelable: Unused; kept for call-site compatibility.

        Yields:
            The operation object.
        """
        del cancelable  # no modal dialog; all operations use the status bar
        op = cls.start_operation(label, total)
        try:
            yield op
            cls.finish_operation(success=True)
        except Exception as exc:
            cls.finish_operation(success=False, error_message=str(exc))
            raise

    @classmethod
    def get_current_operation(cls) -> ProgressOperation | None:
        """Return the top-of-stack operation, or None if the stack is empty."""
        _ = cls()  # ensure singleton is initialized
        with QMutexLocker(cls._stack_lock):
            return cls._operation_stack[-1] if cls._operation_stack else None

    @classmethod
    def cancel_current_operation(cls) -> bool:
        """Cancel the current operation.

        Returns:
            True if an operation was cancelled, False if no operation was active.
        """
        op = cls.get_current_operation()
        if op is not None:
            op.cancel()
            return True
        return False

    @classmethod
    def is_operation_active(cls) -> bool:
        """Return True if at least one operation is on the stack."""
        _ = cls()  # ensure singleton is initialized
        with QMutexLocker(cls._stack_lock):
            return len(cls._operation_stack) > 0

    @classmethod
    def clear_all_operations(cls) -> None:
        """Cancel and clear all active operations (emergency cleanup)."""
        _ = cls()  # ensure singleton is initialized
        with QMutexLocker(cls._stack_lock):
            snapshot = list(cls._operation_stack)
            cls._operation_stack.clear()

        for op in snapshot:
            op.cancel()

        NotificationManager.close_progress()
        logger.warning("All progress operations cleared (emergency cleanup)")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY."""
        with QMutexLocker(cls._stack_lock):
            snapshot = list(cls._operation_stack)
            cls._operation_stack.clear()

        if cls._instance is not None:
            for op in snapshot:
                op.cancel()

        with QMutexLocker(cls._stack_lock):
            cls._instance = None
            cls._operation_stack.clear()
            cls._status_bar = None

        logger.debug("ProgressManager reset for testing")
