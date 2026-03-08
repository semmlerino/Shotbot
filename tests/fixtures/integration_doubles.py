"""Test doubles for MainWindow integration tests.

Classes:
    TestProgressContext: Test double for ProgressManager context
    MainWindowTestProgressManager: Test double for ProgressManager (MainWindow scope)
    TestNotificationManager: Test double for NotificationManager
    TestMessageBox: Test double for QMessageBox dialog capture
    ProgressOperationDouble: Test double for ProgressOperation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar


if TYPE_CHECKING:
    from PySide6.QtCore import QObject


class TestProgressContext:
    """Test double for ProgressManager context."""

    __test__ = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.progress_updates: list[dict[str, Any]] = []

    def __enter__(self) -> TestProgressContext:
        return self

    def __exit__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update(self, value: int, message: str = "") -> None:
        self.progress_updates.append({"value": value, "message": message})

    def set_indeterminate(self) -> None:
        self.progress_updates.append(
            {"type": "indeterminate", "value": -1, "message": "Indeterminate"}
        )


class MainWindowTestProgressManager:
    """Test double for ProgressManager following UNIFIED_TESTING_GUIDE."""

    __test__ = False

    def __init__(self) -> None:
        self.operations: list[dict[str, Any]] = []
        self.active_operations: dict[str, TestProgressContext] = {}
        self._next_operation_id = 0

    def operation(self, *args: Any, **kwargs: Any) -> TestProgressContext:
        return TestProgressContext(*args, **kwargs)

    def start_operation(self, config: Any) -> TestProgressContext:
        operation_id = config.title if hasattr(config, "title") else str(config)
        self._next_operation_id += 1
        key = f"{operation_id}_{self._next_operation_id}"
        self.operations.append({"type": "start", "id": operation_id})
        ctx = TestProgressContext()
        self.active_operations[key] = ctx
        return ctx

    def finish_operation(self, success: bool = True, error_message: str = "") -> None:
        self.operations.append({"type": "finish", "success": success})
        if self.active_operations:
            key = list(self.active_operations.keys())[-1]
            del self.active_operations[key]

    def clear(self) -> None:
        self.operations.clear()
        self.active_operations.clear()
        self._next_operation_id = 0


class TestNotificationManager:
    """Test double for NotificationManager following UNIFIED_TESTING_GUIDE.

    All methods are @classmethod to match the real NotificationManager interface.
    """

    __test__ = False

    _notifications: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def _record_notification(
        cls, notif_type: str, title: str, message: str = "", **kwargs: Any
    ) -> None:
        cls._notifications.append(
            {"type": notif_type, "title": title, "message": message, **kwargs}
        )

    @classmethod
    def error(cls, title: str, message: str = "", details: str = "") -> None:
        cls._record_notification("error", title, message, details=details)

    @classmethod
    def warning(cls, title: str, message: str = "", details: str = "") -> None:
        cls._record_notification("warning", title, message, details=details)

    @classmethod
    def info(cls, message: str, timeout: int = 3000) -> None:
        cls._record_notification("info", "", message, timeout=timeout)

    @classmethod
    def success(cls, message: str, timeout: int = 3000) -> None:
        cls._record_notification("success", "", message, timeout=timeout)

    @classmethod
    def get_last_notification(cls) -> dict[str, Any] | None:
        return cls._notifications[-1] if cls._notifications else None

    @classmethod
    def clear(cls) -> None:
        cls._notifications.clear()


class TestMessageBox:
    """Test double for QMessageBox to capture dialogs."""

    __test__ = False

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def warning(self, parent: QObject | None, title: str, message: str) -> None:
        self.messages.append(
            {"type": "warning", "parent": parent, "title": title, "message": message}
        )

    def get_last_message(self) -> dict[str, Any] | None:
        return self.messages[-1] if self.messages else None

    def clear(self) -> None:
        self.messages.clear()


class ProgressOperationDouble:
    """Test double for progress operations with real behavior."""

    def __init__(self) -> None:
        self.is_indeterminate = False
        self.progress_value = 0
        self.is_finished = False
        self.operations: list[tuple] = []

    def set_indeterminate(self, indeterminate: bool = True) -> None:
        self.is_indeterminate = indeterminate
        self.operations.append(("set_indeterminate", indeterminate))

    def update(self, progress: int) -> None:
        self.progress_value = progress
        self.operations.append(("update", progress))

    def finish(self) -> None:
        self.is_finished = True
        self.operations.append(("finish",))
