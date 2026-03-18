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
from typing import TYPE_CHECKING, cast

# Third-party imports
from PySide6.QtCore import QByteArray, QPoint, QSettings, QSize, Qt, QTimer
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

# Local application imports
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable

    # Third-party imports
    from PySide6.QtGui import (
        QCloseEvent,
        QKeyEvent,
    )
    from PySide6.QtWidgets import QStyle


class QtWidgetMixin(LoggingMixin):
    """Mixin for common Qt widget functionality.

    Provides:
    - Window geometry save/restore
    - Common event handler patterns
    - Context menu creation helpers
    - Standard keyboard shortcuts
    - Window state management
    - Safe timer patterns
    - Common dialog helpers

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
            if isinstance(geometry_value, QByteArray) and hasattr(self, "restoreGeometry"):
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

    def setup_auto_save_timer(self, interval: int = 60000) -> None:
        """Setup timer for auto-saving settings.

        Args:
            interval: Save interval in milliseconds (default 60 seconds)

        """
        if not hasattr(self, "_auto_save_timer"):
            self._auto_save_timer: QTimer = QTimer()
            _ = self._auto_save_timer.timeout.connect(self._on_auto_save)
            self._auto_save_timer.start(interval)
            self.logger.debug(f"Auto-save timer started with {interval}ms interval")

    def _on_auto_save(self) -> None:
        """Auto-save callback."""
        self.save_window_geometry()
        # Subclasses can override to save additional state
        if hasattr(self, "save_state"):
            save_state_method = cast("Callable[[], None]", self.save_state)
            save_state_method()

    def create_context_menu(
        self,
        actions: list[tuple[str, Callable[[], None], str | None]],
        parent: QWidget | None = None,
    ) -> QMenu:
        """Create a context menu with standard actions.

        Args:
            actions: List of (text, callback, icon_name) tuples
            parent: Parent widget for the menu

        Returns:
            Configured QMenu

        """
        menu = QMenu(parent)

        for action_text, callback, icon_name in actions:
            if action_text == "-":
                _ = menu.addSeparator()
            else:
                action = menu.addAction(action_text)
                _ = action.triggered.connect(callback)

                if icon_name and hasattr(self, "style"):
                    from PySide6.QtWidgets import QStyle

                    icon_map: dict[str, int] = {
                        "copy": 61,  # QStyle.StandardPixmap.SP_FileDialogDetailedView
                        "paste": 14,  # QStyle.StandardPixmap.SP_DialogApplyButton
                        "delete": 3,  # QStyle.StandardPixmap.SP_TrashIcon
                        "refresh": 27,  # QStyle.StandardPixmap.SP_BrowserReload
                        "open": 5,  # QStyle.StandardPixmap.SP_DirOpenIcon
                    }
                    if icon_name in icon_map:
                        style_method = cast("Callable[[], QStyle]", self.style)
                        icon = style_method().standardIcon(
                            QStyle.StandardPixmap(icon_map[icon_name])
                        )
                        action.setIcon(icon)

        return menu

    def setup_standard_shortcuts(self) -> None:
        """Setup standard keyboard shortcuts."""
        if not hasattr(self, "addAction"):
            return

        shortcuts = self._get_standard_shortcuts()
        for key_sequence, callback in shortcuts.items():
            from PySide6.QtGui import QAction, QKeySequence

            action = QAction(cast("QWidget", self))
            action.setShortcut(QKeySequence(key_sequence))
            _ = action.triggered.connect(callback)
            self.addAction(action)

    def _get_standard_shortcuts(self) -> dict[str, Callable[[], None]]:
        """Get standard keyboard shortcuts.

        Subclasses can override to provide custom shortcuts.
        """
        shortcuts: dict[str, Callable[[], None]] = {}

        # Add standard shortcuts if methods exist
        if hasattr(self, "refresh"):
            shortcuts["F5"] = cast("Callable[[], None]", self.refresh)
        if hasattr(self, "close"):
            shortcuts["Ctrl+W"] = cast("Callable[[], None]", self.close)
        if hasattr(self, "copy"):
            shortcuts["Ctrl+C"] = cast("Callable[[], None]", self.copy)
        if hasattr(self, "paste"):
            shortcuts["Ctrl+V"] = cast("Callable[[], None]", self.paste)

        return shortcuts

    def safe_close(self) -> bool:
        """Safe close with confirmation if needed.

        Returns:
            True if close should proceed

        """
        # Check if there are unsaved changes
        if hasattr(self, "has_unsaved_changes"):
            has_unsaved = cast("Callable[[], bool]", self.has_unsaved_changes)
            if has_unsaved():
                # QMessageBox.question returns int (StandardButton enum value)
                reply_int: int = cast(
                    "int",
                    QMessageBox.question(
                        cast("QWidget", self),
                        "Unsaved Changes",
                        "You have unsaved changes. Do you want to save before closing?",
                        QMessageBox.StandardButton.Save
                        | QMessageBox.StandardButton.Discard
                        | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Save,
                    ),
                )
                reply = QMessageBox.StandardButton(reply_int)

                if reply == QMessageBox.StandardButton.Save:
                    if hasattr(self, "save"):
                        save_method = cast("Callable[[], None]", self.save)
                        save_method()
                    return True
                return reply == QMessageBox.StandardButton.Discard

        return True

    def cleanup_timers(self) -> None:
        """Cleanup all timers safely."""
        for attr_name, attr_value in vars(self).items():
            if isinstance(attr_value, QTimer):
                attr_value.stop()
                self.logger.debug(f"Stopped timer: {attr_name}")

    def show_error(self, title: str, message: str, details: str | None = None) -> None:
        """Show error message dialog.

        Args:
            title: Dialog title
            message: Main error message
            details: Optional detailed error information

        """
        msg = QMessageBox(cast("QWidget", self))
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(title)
        msg.setText(message)

        if details:
            msg.setDetailedText(details)

        _ = msg.exec()
        self.logger.error(f"{title}: {message}")

    def show_info(self, title: str, message: str) -> None:
        """Show information message dialog.

        Args:
            title: Dialog title
            message: Information message

        """
        _ = QMessageBox.information(cast("QWidget", self), title, message)
        self.logger.info(f"{title}: {message}")

    def confirm_action(self, title: str, message: str) -> bool:
        """Show confirmation dialog.

        Args:
            title: Dialog title
            message: Confirmation message

        Returns:
            True if user confirmed

        """
        # QMessageBox.question returns int (StandardButton enum value)
        reply_int: int = cast(
            "int",
            QMessageBox.question(
                cast("QWidget", self),
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ),
        )
        reply = QMessageBox.StandardButton(reply_int)

        confirmed: bool = reply == QMessageBox.StandardButton.Yes
        self.logger.debug(f"Confirmation '{title}': {confirmed}")
        return confirmed

    # Common event handlers that can be overridden

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle close event with cleanup."""
        if self.safe_close():
            self.save_window_geometry()
            self.cleanup_timers()
            event.accept()
            self.logger.debug("Window closed successfully")
            # Call parent implementation to maintain MRO chain
            if hasattr(super(), "closeEvent"):
                close_event_method = cast("Callable[[QCloseEvent], None]", super().closeEvent)
                close_event_method(event)
        else:
            event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events with standard shortcuts."""
        # Handle Escape key
        if event.key() == Qt.Key.Key_Escape:
            if hasattr(self, "cancel") and callable(getattr(self, "cancel", None)):
                cancel_method = cast("Callable[[], None]", self.cancel)
                cancel_method()
            elif hasattr(self, "close"):
                close_method = cast("Callable[[], bool]", self.close)
                _ = close_method()

        # Let parent handle other keys
        if hasattr(super(), "keyPressEvent"):
            key_press_method = cast("Callable[[QKeyEvent], None]", super().keyPressEvent)
            key_press_method(event)
