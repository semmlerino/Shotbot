"""Qt Widget Mixin for common widget patterns.

This module provides mixins for common Qt widget functionality,
reducing code duplication across widget classes.

Part of Phase 2 refactoring to eliminate duplicate Qt patterns.
"""

# pyright: reportUninitializedInstanceVariable=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportInvalidCast=false
# pyright: reportAny=false
# File-level suppressions are necessary: this mixin accesses QWidget methods (resize, move,
# restoreGeometry, addAction, closeEvent, etc.) that are only present at runtime via multiple
# inheritance. Pyright cannot resolve them statically without seeing the full MRO of each
# concrete class. Per-line suppression would require 20+ ignore comments — kept file-level.

from __future__ import annotations

# Standard library imports
import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

# Third-party imports
from PySide6.QtCore import (
    QByteArray,
    QCoreApplication,
    QPoint,
    QSettings,
    QSize,
    QThread,
)

# Local application imports
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import (
        QCloseEvent,
    )

T = TypeVar("T")


def require_main_thread(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator that raises RuntimeError if called from non-main thread."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        app = QCoreApplication.instance()
        if app and QThread.currentThread() != app.thread():
            msg = (
                f"{func.__qualname__} must be called from the main thread. "
                f"Current: {QThread.currentThread()}, Main: {app.thread()}"
            )
            raise RuntimeError(msg)
        return func(*args, **kwargs)

    return wrapper


class QtWidgetMixin(LoggingMixin):
    """Mixin for common Qt widget functionality.

    Provides:
    - Window geometry save/restore

    Note: This is a mixin class intended to be used with QWidget subclasses.
    Type errors related to Qt widget methods are expected and suppressed with pyright ignore comments.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize QtWidgetMixin and continue MRO chain.

        This ensures proper multiple inheritance with Qt classes.
        """
        super().__init__(*args, **kwargs)

    def setup_window_geometry(
        self,
        settings_key: str,
        default_size: QSize | None = None,
        default_pos: QPoint | None = None,
    ) -> None:
        """Setup window geometry with save/restore.

        Args:
            settings_key: Settings key for storing geometry
            default_size: Default window size if no settings
            default_pos: Default window position if no settings

        """
        self._geometry_key: str = settings_key
        self._default_size: QSize = default_size or QSize(1200, 800)
        self._default_pos: QPoint | None = default_pos

        # Restore geometry from settings
        settings = QSettings()
        if settings.contains(f"{self._geometry_key}/geometry"):
            geometry_value = settings.value(f"{self._geometry_key}/geometry")
            if isinstance(geometry_value, QByteArray) and hasattr(
                self, "restoreGeometry"
            ):
                self.restoreGeometry(geometry_value)
        else:
            if hasattr(self, "resize"):
                self.resize(self._default_size)
            if self._default_pos and hasattr(self, "move"):
                self.move(self._default_pos)

    def save_window_geometry(self) -> None:
        """Save window geometry to settings."""
        if hasattr(self, "_geometry_key") and hasattr(self, "saveGeometry"):
            settings = QSettings()
            settings.setValue(f"{self._geometry_key}/geometry", self.saveGeometry())
            self.logger.debug(f"Saved window geometry for {self._geometry_key}")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle close event with cleanup."""
        self.save_window_geometry()
        if hasattr(super(), "closeEvent"):
            close_event_method = cast(
                "Callable[[QCloseEvent], None]", super().closeEvent
            )
            close_event_method(event)
