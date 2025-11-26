"""Qt safety fixtures to prevent common test failures.

This module provides autouse fixtures that prevent Qt-related test failures
by suppressing modal dialogs and preventing application exit calls that
would corrupt the event loop.

These fixtures are ALWAYS active (autouse=True) because the issues they
prevent can cascade through the entire test suite.

Fixtures:
    suppress_qmessagebox: Auto-dismiss modal dialogs (autouse), returns DialogRecorder
    prevent_qapp_exit: Prevent QApplication exit/quit calls (autouse)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


@dataclass
class DialogRecorder:
    """Records QMessageBox calls for assertion in tests.

    This class is returned by the suppress_qmessagebox fixture, allowing
    tests to assert that specific dialogs were shown (or not shown).

    Usage:
        def test_error_shows_dialog(suppress_qmessagebox):
            do_something_that_shows_error()
            suppress_qmessagebox.assert_shown("critical", "Error occurred")

        def test_no_dialogs_shown(suppress_qmessagebox):
            do_something_quiet()
            suppress_qmessagebox.assert_not_shown()
    """

    calls: list[dict[str, Any]] = field(default_factory=list)

    def assert_shown(
        self, method: str | None = None, text_contains: str | None = None
    ) -> None:
        """Assert a dialog was shown.

        Args:
            method: Optional method name to filter by ("information", "warning",
                "critical", "question", "exec")
            text_contains: Optional text that must appear in the dialog arguments

        Raises:
            AssertionError: If no matching dialog was found
        """
        if method is None:
            matching = self.calls
        else:
            matching = [c for c in self.calls if c["method"] == method]

        assert matching, f"No {method or 'any'} dialog was shown. Recorded: {self.calls}"

        if text_contains:
            found = any(text_contains in str(c["args"]) for c in matching)
            assert found, (
                f"No dialog contained '{text_contains}'. "
                f"Recorded dialogs: {[str(c['args']) for c in matching]}"
            )

    def assert_not_shown(self) -> None:
        """Assert no dialogs were shown.

        Raises:
            AssertionError: If any dialogs were recorded
        """
        assert not self.calls, f"Unexpected dialogs: {self.calls}"

    def clear(self) -> None:
        """Clear recorded calls."""
        self.calls.clear()


@pytest.fixture(autouse=True)
def suppress_qmessagebox(monkeypatch: pytest.MonkeyPatch) -> DialogRecorder:
    """Auto-dismiss modal dialogs to prevent blocking tests.

    This autouse fixture provides default mocks for QMessageBox to prevent
    real dialogs from appearing. Individual tests can override these mocks
    with their own monkeypatch calls - test-specific patches take priority.

    Returns a DialogRecorder that can be used to assert dialog behavior.
    Tests that don't need to assert can ignore the return value.

    Critical for:
    - Preventing real widgets from appearing ("getting real widgets" issue)
    - Avoiding timeouts from modal dialogs waiting for user input
    - Preventing resource exhaustion under high parallel load

    Usage:
        # Just suppress (most tests):
        def test_something():
            ...  # dialogs are auto-suppressed

        # Assert dialogs were shown:
        def test_error_shows_dialog(suppress_qmessagebox):
            trigger_error()
            suppress_qmessagebox.assert_shown("critical", "Error occurred")
    """
    from PySide6.QtWidgets import QMessageBox

    recorder = DialogRecorder()

    def _record_and_ok(method_name: str):
        def wrapper(*args, **kwargs):
            recorder.calls.append({"method": method_name, "args": args, "kwargs": kwargs})
            return QMessageBox.StandardButton.Ok

        return wrapper

    def _record_and_yes(method_name: str):
        def wrapper(*args, **kwargs):
            recorder.calls.append({"method": method_name, "args": args, "kwargs": kwargs})
            return QMessageBox.StandardButton.Yes

        return wrapper

    # Static method patches
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, _record_and_ok(name), raising=True)
    monkeypatch.setattr(QMessageBox, "question", _record_and_yes("question"), raising=True)

    # Instance-style dialog patches (catch .exec() and .open() usage)
    monkeypatch.setattr(QMessageBox, "exec", _record_and_ok("exec"), raising=True)
    monkeypatch.setattr(
        QMessageBox, "open", lambda *_args, **_kwargs: None, raising=True
    )

    return recorder


@pytest.fixture(autouse=True)
def prevent_qapp_exit(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    """Prevent tests from calling QApplication.exit() or quit() which poisons event loops.

    pytest-qt explicitly warns that calling QApplication.exit() in one test
    breaks subsequent tests because it corrupts the event loop state.
    This monkeypatch ensures tests can't accidentally poison the event loop.

    This is critical for large test suites where one bad test can cascade
    failures to all subsequent tests in the same process.

    See: https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html#warning-about-qapplication-exit

    Args:
        monkeypatch: Pytest monkeypatch fixture
        qapp: QApplication fixture from qt_bootstrap
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    def _noop(*args, **kwargs) -> None:
        """No-op exit/quit - tests shouldn't exit the application."""

    # Patch both exit and quit (instance + class methods)
    # Code often calls Q(Core)Application.quit() in addition to exit()
    monkeypatch.setattr(qapp, "exit", _noop)
    monkeypatch.setattr(QApplication, "exit", _noop)
    monkeypatch.setattr(qapp, "quit", _noop)
    monkeypatch.setattr(QApplication, "quit", _noop)
    # Also patch QCoreApplication (some code paths use this)
    monkeypatch.setattr(QCoreApplication, "exit", _noop)
    monkeypatch.setattr(QCoreApplication, "quit", _noop)
