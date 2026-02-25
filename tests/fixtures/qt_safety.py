"""Qt safety fixtures to prevent common test failures.

This module provides autouse fixtures that prevent Qt-related test failures
by suppressing modal dialogs and preventing application exit calls that
would corrupt the event loop.

These fixtures are ALWAYS active (autouse=True) because the issues they
prevent can cascade through the entire test suite.

Fixtures:
    suppress_qmessagebox: Auto-dismiss modal dialogs (autouse), returns DialogRecorder
    prevent_qapp_exit: Prevent QApplication exit/quit calls (autouse)
    expect_dialog: Assert at least one dialog shown (opt-in)
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

        # Test Cancel/No code paths:
        def test_cancel_aborts(suppress_qmessagebox):
            from PySide6.QtWidgets import QMessageBox
            suppress_qmessagebox.set_return_value("question", QMessageBox.StandardButton.No)
            result = confirm_action()
            assert result is False  # Cancel path taken
    """

    calls: list[dict[str, Any]] = field(default_factory=list)
    _return_values: dict[str, Any] = field(default_factory=dict)

    def set_return_value(self, method: str, value: Any) -> None:
        """Set return value for a specific dialog method.

        This allows testing Cancel/No code paths that would otherwise be
        bypassed by the default Ok/Yes returns.

        Args:
            method: Dialog method name ("information", "warning", "critical",
                "question", "exec")
            value: Return value (e.g., QMessageBox.StandardButton.No)

        Example:
            from PySide6.QtWidgets import QMessageBox
            suppress_qmessagebox.set_return_value("question", QMessageBox.StandardButton.No)
            # Code that shows question dialog will now get "No" response

        """
        self._return_values[method] = value

    def get_return_value(self, method: str, default: Any) -> Any:
        """Get configured return value for method, or default if not set."""
        return self._return_values.get(method, default)

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
def suppress_qmessagebox(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> DialogRecorder:
    """Auto-dismiss modal dialogs to prevent blocking tests.

    This autouse fixture provides default mocks for QMessageBox to prevent
    real dialogs from appearing. Individual tests can override these mocks
    with their own monkeypatch calls - test-specific patches take priority.

    Returns a DialogRecorder that can be used to assert dialog behavior.

    STRICT MODE: If a test triggers dialogs without explicit handling, the test
    will FAIL after completion. This catches untested Cancel/No code paths.

    To acknowledge dialogs, use one of:
    - @pytest.mark.allow_dialogs - suppress the check (dialog is expected side-effect)
    - expect_dialog fixture - verify at least one dialog shown
    - expect_no_dialogs fixture - verify no dialogs shown (will fail if any appear)

    Critical for:
    - Preventing real widgets from appearing ("getting real widgets" issue)
    - Avoiding timeouts from modal dialogs waiting for user input
    - Preventing resource exhaustion under high parallel load
    - Catching untested dialog code paths (Yes/No, Ok/Cancel branches)

    Usage:
        # Dialogs explicitly expected:
        @pytest.mark.allow_dialogs
        def test_something_with_dialogs():
            ...  # dialogs allowed, test won't fail

        # Assert dialogs were shown:
        def test_error_shows_dialog(expect_dialog):
            trigger_error()
            expect_dialog.assert_shown("critical", "Error occurred")

        # Assert NO dialogs shown:
        def test_quiet_operation(expect_no_dialogs):
            perform_operation()
            # Auto-checked on teardown
    """
    from PySide6.QtWidgets import QMessageBox

    recorder = DialogRecorder()

    # Check if test has explicit dialog handling
    has_explicit_handling = (
        "expect_dialog" in request.fixturenames
        or "expect_no_dialogs" in request.fixturenames
        or request.node.get_closest_marker("allow_dialogs") is not None
    )

    def _record_and_ok(method_name: str):
        def wrapper(*args, **kwargs):
            recorder.calls.append({"method": method_name, "args": args, "kwargs": kwargs})
            return recorder.get_return_value(method_name, QMessageBox.StandardButton.Ok)

        return wrapper

    def _record_and_yes(method_name: str):
        def wrapper(*args, **kwargs):
            recorder.calls.append({"method": method_name, "args": args, "kwargs": kwargs})
            return recorder.get_return_value(method_name, QMessageBox.StandardButton.Yes)

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

    yield recorder

    # STRICT: Fail if dialogs were shown without explicit handling
    # This catches untested Cancel/No code paths that auto-return Yes/Ok
    if recorder.calls and not has_explicit_handling:
        dialog_summary = []
        for call in recorder.calls:
            method = call["method"]
            args = call.get("args", ())
            # Extract meaningful info from args (typically parent, title, message)
            if len(args) >= 3:
                dialog_summary.append(f"{method}(title={args[1]!r}, msg={args[2]!r})")
            elif len(args) >= 2:
                dialog_summary.append(f"{method}(arg={args[1]!r})")
            else:
                dialog_summary.append(f"{method}({args})")

        pytest.fail(
            f"Dialog(s) shown without explicit expectation:\n"
            f"  {chr(10).join(dialog_summary)}\n\n"
            f"This test triggers dialogs that auto-return Yes/Ok, potentially\n"
            f"bypassing Cancel/No code paths. Fix by adding ONE of:\n\n"
            f"  @pytest.mark.allow_dialogs      # Dialog is expected side-effect\n"
            f"  def test_...(expect_dialog):    # Verify dialog was shown\n"
            f"  def test_...(expect_no_dialogs): # Verify NO dialogs shown\n"
        )


@pytest.fixture(autouse=True)
def prevent_qapp_exit(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    """Prevent tests from calling QApplication.exit() or quit() which poisons event loops.

    pytest-qt explicitly warns that calling QApplication.exit() in one test
    breaks subsequent tests because it corrupts the event loop state.
    This monkeypatch ensures tests can't accidentally poison the event loop.

    This is critical for large test suites where one bad test can cascade
    failures to all subsequent tests in the same process.

    See: https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html#warning-about-qapplication-exit

    Scope Notes:
        This is a function-scoped fixture that depends on session-scoped `qapp`.
        Pytest guarantees session-scoped fixtures are created before any function-scoped
        fixtures, so this dependency is safe. However, do not change this fixture to
        module or session scope without careful review - the monkeypatch fixture
        is function-scoped and would need to be changed first.

    Args:
        monkeypatch: Pytest monkeypatch fixture
        qapp: QApplication fixture from conftest (session-scoped)

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


# ==============================================================================
# OPT-IN DIALOG ASSERTION FIXTURES
# ==============================================================================
# Use these fixtures when you need to explicitly verify dialog behavior


@pytest.fixture
def expect_dialog(suppress_qmessagebox: DialogRecorder):
    """Assert at least one dialog shown - auto-checks after test.

    This convenience fixture wraps suppress_qmessagebox and automatically
    verifies at least one dialog was shown. Use for tests that must trigger
    user-facing dialogs (error messages, confirmations, etc.).

    The fixture yields the DialogRecorder, so you can also use assert_shown()
    for more specific assertions about which dialog appeared.

    Example:
        def test_error_shows_message(expect_dialog):
            trigger_error()
            # Fixture ensures at least one dialog shown
            # Optionally verify specific dialog:
            expect_dialog.assert_shown("critical", "Error occurred")

        # If NO dialog shown, test fails with:
        # AssertionError: Expected at least one dialog but none were shown

    """
    yield suppress_qmessagebox
    assert suppress_qmessagebox.calls, "Expected at least one dialog but none were shown"


