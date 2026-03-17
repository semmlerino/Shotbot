"""Tests for NotificationManager - User notification and feedback system.

This module provides comprehensive tests for the NotificationManager class,
which handles all user notifications and feedback in the application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from pytestqt.qtbot import QtBot

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStatusBar,
)

from managers.notification_manager import (
    NotificationManager,
    NotificationType,
)


# Test markers for categorization and parallel safety
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # Singleton requires serial execution
]


def _process_events(duration_ms: int = 5, iterations: int = 2) -> None:
    """Drain Qt events without relying on qtbot.wait(), keeping teardown stable."""
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, duration_ms)


@pytest.fixture
def make_manager_with_ui(
    qtbot: QtBot,
) -> Callable[[], tuple[NotificationManager, QMainWindow, QStatusBar]]:
    """Factory for creating NotificationManager with UI components."""

    def _make() -> tuple[NotificationManager, QMainWindow, QStatusBar]:
        main_window = QMainWindow()
        status_bar = QStatusBar()
        main_window.setStatusBar(status_bar)
        qtbot.addWidget(main_window)

        manager = NotificationManager.initialize(main_window, status_bar)
        return manager, main_window, status_bar

    return _make


class TestNotificationManager:
    """Test suite for NotificationManager singleton."""

    @pytest.fixture(autouse=True)
    def cleanup(self) -> Generator[None, None, None]:
        """Clean up NotificationManager after each test."""
        yield
        NotificationManager.cleanup()
        NotificationManager._instance = None

    @pytest.fixture
    def manager_with_ui(
        self,
        make_manager_with_ui: Callable[[], tuple[NotificationManager, QMainWindow, QStatusBar]],
    ) -> tuple[NotificationManager, QMainWindow, QStatusBar]:
        """Create notification manager with UI components."""
        return make_manager_with_ui()

    def test_singleton_pattern(self) -> None:
        """Test that NotificationManager follows singleton pattern."""
        instance1 = NotificationManager()
        instance2 = NotificationManager()

        assert instance1 is instance2

    def test_initialization(
        self, manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar]
    ) -> None:
        """Test proper initialization with UI references."""
        manager, main_window, status_bar = manager_with_ui

        assert NotificationManager._main_window is main_window
        assert NotificationManager._status_bar is status_bar
        assert isinstance(manager, NotificationManager)

    def test_error_notification(
        self,
        manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar],
        qtbot: QtBot,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test error notification display."""
        _manager, main_window, _status_bar = manager_with_ui

        # Use monkeypatch.setattr to override the autouse fixture's mock
        from unittest.mock import MagicMock
        mock_critical = MagicMock(return_value=QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "critical", mock_critical)

        NotificationManager.error("Test Error", "Error message", "Details")

        mock_critical.assert_called_once()
        args = mock_critical.call_args[0]
        assert args[0] is main_window
        assert "Test Error" in args[1]
        assert "Error message" in args[2]

    def test_warning_notification(
        self,
        manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test warning notification display."""
        _manager, main_window, _status_bar = manager_with_ui

        # Use monkeypatch.setattr to override the autouse fixture's mock
        from unittest.mock import MagicMock
        mock_warning = MagicMock(return_value=QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", mock_warning)

        NotificationManager.warning("Test Warning", "Warning message")

        mock_warning.assert_called_once()
        args = mock_warning.call_args[0]
        assert args[0] is main_window
        assert "Test Warning" in args[1]

    def test_info_notification(
        self, manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar], qtbot: QtBot
    ) -> None:
        """Test info message in status bar."""
        _manager, _main_window, status_bar = manager_with_ui

        NotificationManager.info("Info message", timeout=100)

        # Check status bar shows the message
        assert status_bar.currentMessage() == "Info message"

        # Wait for message to clear or remain
        qtbot.waitUntil(
            lambda: status_bar.currentMessage() == ""
            or "Info message" in status_bar.currentMessage(),
            timeout=250,
        )

    def test_success_notification(
        self, manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar]
    ) -> None:
        """Test success notification in status bar."""
        _manager, _main_window, status_bar = manager_with_ui

        NotificationManager.success("Operation successful")

        # Check status bar shows the message
        assert "Operation successful" in status_bar.currentMessage()
        # Success messages include checkmark
        assert "✓" in status_bar.currentMessage()

    def test_progress_notification(
        self,
        manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test progress dialog creation."""
        _manager, _main_window, _status_bar = manager_with_ui

        # Create a mock progress dialog
        mock_progress = MagicMock(spec=QProgressDialog)
        mock_progress_new = MagicMock(return_value=mock_progress)
        monkeypatch.setattr(QProgressDialog, "__new__", mock_progress_new)

        # Show progress - progress() takes title, message, cancelable, callback
        NotificationManager.progress("Loading...", "Processing items", cancelable=True)

        # Check that progress dialog methods were called
        mock_progress.setWindowTitle.assert_called_with("Loading...")
        mock_progress.setModal.assert_called_with(True)
        mock_progress.show.assert_called()

    def test_close_progress(
        self, manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar]
    ) -> None:
        """Test closing progress dialog."""
        _manager, _main_window, _status_bar = manager_with_ui

        # Create mock progress
        mock_progress = MagicMock(spec=QProgressDialog)
        NotificationManager._current_progress = mock_progress

        # Close progress
        NotificationManager.close_progress()

        mock_progress.close.assert_called_once()
        assert NotificationManager._current_progress is None

    def test_notification_without_ui(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test notifications work without UI initialization."""
        # Don't initialize with UI
        NotificationManager()

        # These should not crash - use monkeypatch to override autouse fixture
        from unittest.mock import MagicMock

        mock_critical = MagicMock(return_value=QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "critical", mock_critical)
        NotificationManager.error("Error without UI")
        mock_critical.assert_called_once()

        mock_warning = MagicMock(return_value=QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", mock_warning)
        NotificationManager.warning("Warning without UI")
        mock_warning.assert_called_once()

        # Info without status bar should not crash
        NotificationManager.info("Info without status bar")

    def test_cleanup(
        self, manager_with_ui: tuple[NotificationManager, QMainWindow, QStatusBar]
    ) -> None:
        """Test cleanup of notification resources."""
        _manager, _main_window, _status_bar = manager_with_ui

        mock_progress = MagicMock()
        NotificationManager._current_progress = mock_progress

        # Clean up
        NotificationManager.cleanup()

        # Check everything was cleaned
        assert NotificationManager._main_window is None
        assert NotificationManager._status_bar is None
        assert NotificationManager._current_progress is None
        mock_progress.close.assert_called_once()

    def test_notification_types_enum(self) -> None:
        """Test NotificationType enum values."""
        # Check all expected types exist
        expected_types = [
            NotificationType.ERROR,
            NotificationType.WARNING,
            NotificationType.INFO,
            NotificationType.SUCCESS,
            NotificationType.PROGRESS,
        ]

        for notif_type in expected_types:
            assert isinstance(notif_type, NotificationType)
