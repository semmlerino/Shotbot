"""Qt test fixtures: cleanup, safety, and event-loop helpers.

Consolidated from:
- qt_cleanup.py: Qt thread/event cleanup between tests
- qt_safety.py:  Dialog suppression and QApplication exit prevention

Fixtures:
    qt_cleanup:          Clean Qt state between tests (not autouse — dispatcher-activated)
    suppress_qmessagebox: Dismiss modal dialogs, returns DialogRecorder
    prevent_qapp_exit:   Prevent QApplication exit/quit calls
    expect_dialog:       Assert at least one dialog shown (opt-in)
    expect_no_dialogs:   Assert no dialogs shown (opt-in)

Exported helpers:
    get_thread_leak_summary: Collect session-end thread-leak report
    DialogRecorder:          Records QMessageBox calls for test assertions
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# qt_cleanup contents
# ---------------------------------------------------------------------------
import logging
import os
import time as _time
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt


if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

    from PySide6.QtWidgets import QApplication

_logger = logging.getLogger(__name__)
_REAL_MONOTONIC = _time.monotonic
_REAL_SLEEP = _time.sleep

# Strict mode fails on cleanup exceptions (useful for debugging)
# Auto-enabled in CI environments to catch thread leaks early
STRICT_CLEANUP = (
    os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"
    or os.environ.get("CI") == "true"
    or os.environ.get("GITHUB_ACTIONS") == "true"
)

# Fail mode: pytest.fail() on thread leaks
# Enabled by default to catch thread leaks early in development
# STRICT_CLEANUP only logs warnings; FAIL_ON_THREAD_LEAK makes tests fail
# Opt-out with SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1 for quick local runs
FAIL_ON_THREAD_LEAK = (
    os.environ.get("SHOTBOT_TEST_ALLOW_THREAD_LEAKS", "0") != "1"
    and os.environ.get("SHOTBOT_TEST_FAIL_ON_THREAD_LEAK", "1") == "1"
)

# Thread count tolerance - reduced from 2 to 1 to catch single-thread leaks
# Daemon threads and pytest internals may vary, but tolerance of 2 masked leaks
_THREAD_TOLERANCE = 1

# Thread wait timeout in ms - configurable via env var for slow CI runners
# Increased from 100ms to 500ms to handle real QThreadPool workloads
_THREAD_WAIT_TIMEOUT_MS = int(os.environ.get("SHOTBOT_TEST_THREAD_WAIT_MS", "500"))

# Thread name allowlist: Known harmless daemon threads that may persist
# These are system/library threads outside our control, not application leaks
_EXPECTED_THREAD_PREFIXES: frozenset[str] = frozenset(
    {
        "_GC_Monitor",  # Python garbage collector monitor (some builds)
        "pytest_timeout",  # pytest-timeout watchdog thread
        "QDBusConnection",  # Qt D-Bus integration thread
        "PoolThread-",  # QThreadPool internal threads (expected to drain)
        # Thread- daemon threads are allowed at the detection site, not here
        "pydevd.",  # PyCharm/debugger threads
        "Dummy-",  # Threading module dummy threads
    }
)

# Session-level leak tracking (populated in CI/strict mode)
# Collects leak info for summary at session end instead of per-test spam
_thread_leak_summary: list[dict[str, Any]] = []


def get_thread_leak_summary() -> str | None:
    """Get formatted thread leak summary for session end.

    Returns:
        Formatted summary string if leaks were detected, None otherwise.
        Also clears the leak list after generating summary.

    """
    if not _thread_leak_summary:
        return None

    # Group by surviving thread names for actionable insights
    thread_counts: dict[str, int] = {}
    for leak in _thread_leak_summary:
        for thread in leak.get("threads", []):
            thread_counts[thread] = thread_counts.get(thread, 0) + 1

    sorted_threads = sorted(thread_counts.items(), key=lambda x: -x[1])

    lines = [
        "",
        "=" * 70,
        f"THREAD LEAK SUMMARY: {len(_thread_leak_summary)} test(s) had thread leaks",
        "=" * 70,
        "",
        "Most common surviving threads (fix these first):",
    ]
    for thread, count in sorted_threads[:10]:
        lines.append(f"  {count:3d}x  {thread}")

    if len(_thread_leak_summary) <= 5:
        lines.append("")
        lines.append("Affected tests:")
        lines.extend(f"  - {leak['test']}" for leak in _thread_leak_summary)
    else:
        lines.append("")
        lines.append(f"First 5 affected tests (of {len(_thread_leak_summary)}):")
        lines.extend(f"  - {leak['test']}" for leak in _thread_leak_summary[:5])
        lines.append("")
        lines.append(
            "Run with SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1 to suppress thread leak failures."
        )

    lines.append("=" * 70)
    lines.append("")

    # Clear for next session
    _thread_leak_summary.clear()

    return "\n".join(lines)


def _is_expected_thread(thread_name: str) -> bool:
    """Check if a thread name matches known harmless patterns.

    Args:
        thread_name: The thread name to check (e.g., "Thread-1", "pytest_timeout")

    Returns:
        True if the thread is expected/harmless, False if it's a potential leak

    """
    return any(thread_name.startswith(prefix) for prefix in _EXPECTED_THREAD_PREFIXES)


def _read_zombie_baseline() -> dict[str, int]:
    """Snapshot current zombie metrics. Returns empty dict if zombie_registry unavailable."""
    try:
        from workers.zombie_registry import get_zombie_metrics

        return dict(get_zombie_metrics())
    except (ImportError, AttributeError, TypeError):
        return {}


def _zombies_created_during(before: dict[str, int], after: dict[str, int]) -> int:
    """Return how many new zombies were created between two metric snapshots."""
    return after.get("created", 0) - before.get("created", 0)


@pytest.fixture  # Not autouse — activated by _qt_auto_fixtures dispatcher
def qt_cleanup(qapp: QApplication, request: pytest.FixtureRequest) -> Iterator[None]:
    """Ensure Qt state is clean between tests.

    This fixture implements proper Qt test hygiene to prevent
    test-hygiene issues that cause crashes in large test suites:

    1. Flushes deferred deletes (deleteLater()) to prevent dangling signals/slots
    2. Clears Qt caches (QPixmapCache) to prevent memory accumulation
    3. Waits for background threads to prevent use-after-free
    4. Processes events multiple times to ensure complete cleanup
    5. (STRICT MODE) Detects thread leaks by comparing baseline counts

    Qt's object model is robust - it doesn't "accumulate leaks" from creating
    thousands of widgets. Crashes in large suites are from test-hygiene issues,
    not Qt corruption. This fixture ensures proper cleanup between tests.

    In CI environments (or with SHOTBOT_TEST_STRICT_CLEANUP=1), thread leaks
    are logged with surviving thread names to help identify the source.

    See Qt Test best practices: doc.qt.io/qt-6/qttest-index.html

    Args:
        qapp: QApplication fixture from qt_bootstrap

    """
    import threading

    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtGui import QPixmapCache

    def _has_unexpected_python_threads() -> bool:
        for thread in threading.enumerate():
            if thread.name == "MainThread":
                continue
            if _is_expected_thread(thread.name) or (
                thread.name.startswith("Thread-") and thread.daemon
            ):
                continue
            return True
        return False

    # Capture baseline thread counts BEFORE test
    # Used for leak detection after cleanup
    baseline_python_threads = threading.active_count()
    baseline_pool_threads = QThreadPool.globalInstance().activeThreadCount()

    # BEFORE TEST: Wait for background threads from previous test FIRST
    # This prevents crashes from processing events while threads are still running
    # Only wait if there are actually active threads (performance optimization)
    pool = QThreadPool.globalInstance()
    if pool.activeThreadCount() > 0:
        pool.waitForDone(500)

    # Wrap event processing in try-except to prevent crashes from leaked objects
    try:
        # Now clean up state from previous test
        # 1 round is sufficient; post-test cleanup of the previous test already handled most state
        QCoreApplication.processEvents()
        # Flush deferred deletes explicitly (deleteLater() calls)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Clear Qt caches to prevent memory accumulation
        QPixmapCache.clear()
    except (RuntimeError, SystemError) as e:
        _logger.warning(
            "Qt cleanup before-test exception (check for orphaned Qt objects): %s", e
        )
        if STRICT_CLEANUP:
            raise

    zombie_baseline = _read_zombie_baseline()

    yield

    # AFTER TEST: Wait for background threads FIRST before processing events
    # This prevents crashes from processing events while threads are still running
    # Only wait if there are actually active threads (performance optimization)
    pool = QThreadPool.globalInstance()
    if pool.activeThreadCount() > 0:
        # Cancel pending runnables from queue (if supported - some Qt builds may lack clear())
        if hasattr(pool, "clear"):
            pool.clear()
        pool.waitForDone(
            _THREAD_WAIT_TIMEOUT_MS
        )  # Configurable via SHOTBOT_TEST_THREAD_WAIT_MS

        # Backoff loop if still active - handles slow thread shutdowns
        if pool.activeThreadCount() > 0:
            for backoff_ms in [100, 200, 500]:
                pool.waitForDone(backoff_ms)
                if pool.activeThreadCount() == 0:
                    break

    # Also wait for any Python threading.Thread instances to complete
    # Some tests use threading.Thread in addition to QThreadPool
    # Use time.sleep() (not processEvents) to avoid C++ segfaults from
    # delivering DeferredDelete events to already-destroyed Qt objects
    # while threads are still active. The subsequent cleanup pass below
    # handles event processing safely after all threads have completed.
    if _has_unexpected_python_threads():
        start_time = _REAL_MONOTONIC()
        timeout = 0.5
        while (
            _has_unexpected_python_threads()
            and (_REAL_MONOTONIC() - start_time) < timeout
        ):
            _REAL_SLEEP(0.01)

    # Wrap event processing in try-except to prevent crashes from leaked objects
    try:
        # Now that threads are done, clean up Qt resources
        # 2 rounds: first processes deleteLater() objects, second handles cascading deletes
        for _ in range(2):
            QCoreApplication.processEvents()
            # Flush deferred deletes - prevents dangling signals/slots
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Clear Qt caches again after test
        QPixmapCache.clear()
    except (RuntimeError, SystemError) as e:
        _logger.warning(
            "Qt cleanup after-test exception (check for orphaned Qt objects): %s", e
        )
        if STRICT_CLEANUP:
            raise

    # THREAD LEAK DETECTION: Compare current thread counts to baseline
    # Collects to session summary instead of per-test logging (reduces noise)
    if STRICT_CLEANUP or FAIL_ON_THREAD_LEAK:
        final_pool_threads = QThreadPool.globalInstance().activeThreadCount()
        final_python_threads = threading.active_count()

        # Track if any leaks detected
        pool_leaked = final_pool_threads > baseline_pool_threads
        python_leaked = (
            final_python_threads > baseline_python_threads + _THREAD_TOLERANCE
        )

        # Collect surviving thread info for analysis
        all_surviving: list[str] = []
        unexpected_threads: list[str] = []
        if pool_leaked or python_leaked:
            for t in threading.enumerate():
                if t.name == "MainThread":
                    continue
                thread_info = f"{t.name} (daemon={t.daemon})"
                all_surviving.append(thread_info)
                # Only flag unexpected threads as leaks
                # Thread- daemon threads are expected (stdlib creates these)
                is_expected = _is_expected_thread(t.name) or (
                    t.name.startswith("Thread-") and t.daemon
                )
                if not is_expected:
                    unexpected_threads.append(thread_info)

            # Only report leak if there are UNEXPECTED threads
            # Expected daemon threads (pytest_timeout, etc.) are not leaks
            if unexpected_threads:
                # Collect leak info for session-end summary (no per-test spam)
                _thread_leak_summary.append(
                    {
                        "test": request.node.nodeid,
                        "pool": (baseline_pool_threads, final_pool_threads),
                        "python": (baseline_python_threads, final_python_threads),
                        "threads": unexpected_threads,
                        "all_threads": all_surviving,  # Full list for debugging
                    }
                )

        # FAIL_ON_THREAD_LEAK: Make tests fail immediately (enabled by default)
        # Only fail if there are UNEXPECTED threads (not just daemon count increase)
        # Skip failure for tests marked with @pytest.mark.thread_leak_ok
        has_leak_ok_marker = "thread_leak_ok" in [
            m.name for m in request.node.iter_markers()
        ]
        if FAIL_ON_THREAD_LEAK and unexpected_threads and not has_leak_ok_marker:
            pytest.fail(
                f"THREAD LEAK DETECTED (FAIL_ON_THREAD_LEAK is enabled by default)\n"
                f"QThreadPool: {baseline_pool_threads} -> {final_pool_threads} "
                f"(+{final_pool_threads - baseline_pool_threads})\n"
                f"Python threads: {baseline_python_threads} -> {final_python_threads} "
                f"(+{final_python_threads - baseline_python_threads})\n"
                f"Unexpected threads: {unexpected_threads}\n"
                f"(Expected threads filtered: {_EXPECTED_THREAD_PREFIXES})\n"
                f"To opt-out, add @pytest.mark.thread_leak_ok or set "
                f"SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1",
                pytrace=False,
            )

        zombie_after = _read_zombie_baseline()
        new_zombies = _zombies_created_during(zombie_baseline, zombie_after)
        if new_zombies > 0 and FAIL_ON_THREAD_LEAK:
            marker = request.node.get_closest_marker("thread_leak_ok")
            if marker is None:
                pytest.fail(
                    f"{new_zombies} worker(s) were abandoned to the zombie registry during this test. "
                    f"Use cleanup_qthread_properly() or mark the test @pytest.mark.thread_leak_ok.",
                    pytrace=False,
                )


# ---------------------------------------------------------------------------
# qt_safety contents
# ---------------------------------------------------------------------------

from collections.abc import Iterator
from dataclasses import dataclass, field


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

        assert matching, (
            f"No {method or 'any'} dialog was shown. Recorded: {self.calls}"
        )

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


@pytest.fixture
def suppress_qmessagebox(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> DialogRecorder:
    """Dismiss modal dialogs to prevent blocking tests.

    This fixture provides default mocks for QMessageBox to prevent
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
            recorder.calls.append(
                {"method": method_name, "args": args, "kwargs": kwargs}
            )
            return recorder.get_return_value(method_name, QMessageBox.StandardButton.Ok)

        return wrapper

    def _record_and_yes(method_name: str):
        def wrapper(*args, **kwargs):
            recorder.calls.append(
                {"method": method_name, "args": args, "kwargs": kwargs}
            )
            return recorder.get_return_value(
                method_name, QMessageBox.StandardButton.Yes
            )

        return wrapper

    # Static method patches
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, _record_and_ok(name), raising=True)
    monkeypatch.setattr(
        QMessageBox, "question", _record_and_yes("question"), raising=True
    )

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


@pytest.fixture
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
    assert suppress_qmessagebox.calls, (
        "Expected at least one dialog but none were shown"
    )


@pytest.fixture
def expect_no_dialogs(suppress_qmessagebox: DialogRecorder) -> Iterator[DialogRecorder]:
    """Explicitly assert no dialogs are shown during this test.

    Satisfies the 'has_explicit_handling' check in suppress_qmessagebox,
    suppressing the fallback guidance message. Asserts on teardown that
    no dialogs were recorded.
    """
    yield suppress_qmessagebox
    suppress_qmessagebox.assert_not_shown()


# ==============================================================================
# QT MOCK FACTORIES
# ==============================================================================
# Reusable factories for common Qt mock objects used across test files.


def make_mock_index(
    row: int = 0,
    column: int = 0,
    data: Any = None,
    is_valid: bool = True,
) -> Any:
    """Factory for QModelIndex mocks with common defaults.

    Args:
        row: Row value for the index
        column: Column value for the index
        data: Return value for index.data() calls
        is_valid: Whether the index reports as valid

    Returns:
        Configured MagicMock with QModelIndex spec
    """
    from unittest.mock import MagicMock

    from PySide6.QtCore import QModelIndex

    index = MagicMock(spec=QModelIndex)
    index.row.return_value = row
    index.column.return_value = column
    index.isValid.return_value = is_valid
    if data is not None:
        index.data.return_value = data
    return index


def make_mock_wheel_event(
    delta: int = 120,
    modifiers: Qt.KeyboardModifier | None = None,
) -> Any:
    """Factory for QWheelEvent mocks.

    Args:
        delta: Scroll delta (positive = up, negative = down). Default 120 = one notch up.
        modifiers: Keyboard modifiers (e.g. ControlModifier for Ctrl+scroll).
            Defaults to NoModifier.

    Returns:
        Configured MagicMock with QWheelEvent spec configured for angleDelta().y()
    """
    from unittest.mock import MagicMock

    from PySide6.QtGui import QWheelEvent

    if modifiers is None:
        modifiers = Qt.KeyboardModifier.NoModifier

    event = MagicMock(spec=QWheelEvent)

    # Configure angleDelta to return a mock QPoint that supports .y() method
    angle_delta_point = MagicMock()
    angle_delta_point.y.return_value = delta
    event.angleDelta.return_value = angle_delta_point

    event.modifiers.return_value = modifiers
    return event
