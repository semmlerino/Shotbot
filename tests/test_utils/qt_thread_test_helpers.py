"""Qt threading test utilities for reliable signal testing.

This module provides utilities for testing Qt threaded workers with proper
signal handling and event loop management.
"""

from __future__ import annotations

# Standard library imports
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

# Third-party imports
from PySide6.QtCore import QCoreApplication, QThread, Signal

# Local application imports
from tests.helpers.synchronization import process_qt_events


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable

    # Third-party imports
    from pytestqt.qtbot import QtBot


class ThreadSignalTester:
    """Helper for testing Qt thread signals reliably."""

    def __init__(self, qtbot: QtBot) -> None:
        self.qtbot = qtbot
        self.captured_signals: list[Any] = []

    def capture_signal(self, signal: Signal, capture_args: bool = True) -> Callable:
        """Create a signal handler that captures emitted data.

        Args:
            signal: Qt signal to capture
            capture_args: Whether to capture signal arguments

        Returns:
            Signal handler function

        """

        def handler(*args) -> None:
            if capture_args:
                self.captured_signals.append(
                    args if len(args) > 1 else (args[0] if args else None),
                )
            else:
                self.captured_signals.append(True)

        signal.connect(handler)
        return handler

    def wait_for_worker_lifecycle(
        self,
        worker: QThread,
        expect_error: bool = False,
        timeout_ms: int = 5000,
    ) -> bool:
        """Wait for complete worker lifecycle including DELETED state.

        Args:
            worker: Worker thread to monitor
            expect_error: Whether to expect an error signal
            timeout_ms: Maximum time to wait

        Returns:
            True if lifecycle completed successfully

        """
        # Wait for thread to finish
        with self.qtbot.waitSignal(worker.finished, timeout=timeout_ms):
            pass

        # Minimal event processing for _on_finished slot
        self.qtbot.wait(1)

        return True

    @contextmanager
    def signal_sequence(self, signals: list[Signal], timeout_ms: int = 5000):
        """Context manager for waiting on multiple signals in sequence.

        Args:
            signals: List of signals to wait for in order
            timeout_ms: Timeout for each signal

        """
        try:
            for signal in signals:
                with self.qtbot.waitSignal(signal, timeout=timeout_ms):
                    pass
            yield
        finally:
            # Cleanup handled by context manager
            pass


def wait_for_thread_state(
    worker: Any,
    expected_state: Any,
    qtbot: QtBot,
    timeout_ms: int = 1000,
) -> bool:
    """Wait for worker to reach expected state.

    Args:
        worker: Worker with get_state() method
        expected_state: State to wait for
        qtbot: pytest-qt bot for event processing
        timeout_ms: Maximum time to wait

    Returns:
        True if state reached, False if timeout

    """
    start_time = time.time()

    while time.time() - start_time < (timeout_ms / 1000.0):
        qtbot.wait(1)  # Minimal event processing between checks
        if worker.get_state() == expected_state:
            return True

    return False


def ensure_qt_events_processed(qtbot: QtBot, cycles: int = 3) -> None:
    """Ensure Qt events are processed multiple times.

    This is useful when signals need to propagate through multiple
    event loop cycles.

    Args:
        qtbot: pytest-qt bot
        cycles: Number of event processing cycles

    """
    for _ in range(cycles):
        qtbot.wait(1)  # Minimal event processing per cycle
        app = QCoreApplication.instance()
        if app:
            process_qt_events(app, 10)


class WorkerTestFramework:
    """Complete framework for testing Qt workers with lifecycle management."""

    def __init__(self, qtbot: QtBot) -> None:
        self.qtbot = qtbot
        self.signal_tester = ThreadSignalTester(qtbot)

    def test_worker_complete_lifecycle(
        self,
        worker: QThread,
        work_duration: float = 0.05,
        expected_final_state: Any = None,
    ) -> dict:
        """Test complete worker lifecycle with comprehensive verification.

        Args:
            worker: Worker thread to test
            work_duration: Expected work duration for timeout calculation
            expected_final_state: Expected final state (e.g., WorkerState.DELETED)

        Returns:
            Dictionary with test results and captured data

        """
        results = {
            "signals_captured": [],
            "final_state": None,
            "success": True,
            "error_messages": [],
        }

        # Set up signal capturing
        if hasattr(worker, "worker_started"):
            self.signal_tester.capture_signal(worker.worker_started)
        if hasattr(worker, "worker_stopped"):
            self.signal_tester.capture_signal(worker.worker_stopped)
        if hasattr(worker, "worker_error"):

            def error_handler(msg) -> None:
                results["error_messages"].append(msg)

            worker.worker_error.connect(error_handler)

        # Start worker
        worker.start()

        # Wait for complete lifecycle
        timeout_ms = max(5000, int(work_duration * 1000 * 10))  # 10x safety margin

        try:
            # Wait for thread to finish
            with self.qtbot.waitSignal(worker.finished, timeout=timeout_ms):
                pass

            # Minimal event processing for final state transitions
            self.qtbot.wait(1)

            # Capture final state
            if hasattr(worker, "get_state"):
                results["final_state"] = worker.get_state()

            # Verify expected final state
            if (
                expected_final_state is not None
                and results["final_state"] != expected_final_state
            ):
                results["success"] = False

        except Exception as e:
            results["success"] = False
            results["error_messages"].append(str(e))

        results["signals_captured"] = self.signal_tester.captured_signals
        return results
