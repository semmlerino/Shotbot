"""Contract tests for ProcessPoolManager.

These tests verify that the real ProcessPoolManager behaves as expected,
particularly around thread-safety and UI-thread guards. They serve as
a contract that TestProcessPool should also respect.

The tests exercise the real implementation to catch regressions that
test doubles might mask.

NOTE: These tests are marked with @pytest.mark.real_subprocess to bypass
the autouse mock_process_pool_manager fixture, allowing them to test
the actual ProcessPoolManager implementation.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from process_pool_manager import ProcessPoolManager


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


# Mark the entire module to use real subprocess (bypasses autouse mocking)
pytestmark = [pytest.mark.integration, pytest.mark.real_subprocess]


@pytest.fixture(autouse=True)
def cleanup_process_pool():
    """Ensure ProcessPoolManager is reset after each test."""
    yield
    if ProcessPoolManager._instance is not None:
        try:
            ProcessPoolManager._instance.shutdown(timeout=2.0)
        except Exception:
            pass
        ProcessPoolManager._instance = None
        ProcessPoolManager._initialized = False


@pytest.mark.qt
class TestProcessPoolManagerUIThreadGuard:
    """Contract tests for UI-thread guard behavior.

    The real ProcessPoolManager.execute_workspace_command() MUST:
    1. Raise RuntimeError when called from the main Qt thread
    2. Work correctly when called from a background thread

    These tests verify the guard works correctly so tests using
    TestProcessPool can trust that the guard exists in production.
    """

    def test_ui_thread_guard_rejects_main_thread(self, qtbot: QtBot) -> None:
        """Contract: execute_workspace_command raises on UI thread."""
        from PySide6.QtCore import QCoreApplication, QThread

        manager = ProcessPoolManager()

        # Verify we're on main thread
        assert QThread.currentThread() == QCoreApplication.instance().thread()

        # Must raise RuntimeError when called from UI thread
        with pytest.raises(RuntimeError, match="cannot be called on the main"):
            manager.execute_workspace_command("ws -sg")

    def test_background_thread_allowed(self, qtbot: QtBot) -> None:
        """Contract: execute_workspace_command works from background thread.

        This test runs the command in a background thread to verify it's
        allowed (even though the subprocess may fail).
        """
        manager = ProcessPoolManager()

        result_holder: dict[str, object] = {"result": None, "error": None}

        def run_in_background():
            try:
                # Command will likely fail, but shouldn't raise RuntimeError
                manager.execute_workspace_command("echo test", timeout=2)
                result_holder["result"] = "success"
            except RuntimeError as e:
                if "cannot be called on the main" in str(e):
                    result_holder["error"] = "UI thread guard triggered incorrectly"
                else:
                    # Other RuntimeErrors are OK (command failure, etc.)
                    result_holder["result"] = "command_failed_ok"
            except Exception as e:
                # Timeout, subprocess errors, etc. are expected
                result_holder["result"] = f"expected_error: {type(e).__name__}"

        thread = threading.Thread(target=run_in_background)
        thread.start()
        thread.join(timeout=5.0)

        # The UI thread guard should NOT have triggered
        assert result_holder["error"] is None, result_holder["error"]
        assert result_holder["result"] is not None


@pytest.mark.qt
class TestProcessPoolManagerSignals:
    """Contract tests for signal emission behavior.

    The real ProcessPoolManager signals MUST:
    1. Be Qt Signal instances (not plain Python)
    2. Emit from the correct thread context

    These tests verify signal behavior so tests using SignalDouble
    or QtSignalDouble can trust the real behavior.
    """

    def test_signals_are_qt_signals(self, qtbot: QtBot) -> None:
        """Contract: command_completed and command_failed are Qt Signals."""
        from PySide6.QtCore import SignalInstance

        manager = ProcessPoolManager()

        # Both signals should be SignalInstance (bound Qt Signal)
        assert isinstance(manager.command_completed, SignalInstance)
        assert isinstance(manager.command_failed, SignalInstance)

    def test_signal_connection_works(self, qtbot: QtBot) -> None:
        """Contract: signals can be connected and disconnected."""
        manager = ProcessPoolManager()

        received: list[tuple[str, object]] = []

        def on_completed(cmd: str, result: object) -> None:
            received.append((cmd, result))

        # Connect should work without error
        manager.command_completed.connect(on_completed)

        # Disconnect should work without error
        manager.command_completed.disconnect(on_completed)

        # No emissions recorded (we didn't run any commands)
        assert len(received) == 0
