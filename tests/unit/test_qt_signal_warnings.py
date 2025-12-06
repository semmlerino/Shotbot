"""Test that Qt signal connections don't produce runtime warnings.

This test catches issues like UniqueConnection with Python callables
that only manifest as runtime warnings.
"""

import sys
from io import StringIO

import pytest
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from thread_safe_worker import ThreadSafeWorker
from typing_compat import override


class DummyWorker(ThreadSafeWorker):
    """Minimal worker for testing signal connections."""

    test_signal = Signal(str)

    @override
    def do_work(self) -> None:
        """Dummy work implementation."""
        self.test_signal.emit("test")


def test_safe_connect_produces_no_qt_warnings(qapp: QApplication, qtbot) -> None:
    """Test that safe_connect doesn't produce Qt unique connection warnings.

    Qt warnings like "unique connections require a pointer to member function"
    indicate the code is trying to use features that don't work with Python.
    """
    # Capture stderr where Qt warnings appear
    old_stderr = sys.stderr
    sys.stderr = captured_stderr = StringIO()

    try:
        worker = DummyWorker()
        slot_called = []

        def test_slot(msg: str) -> None:
            slot_called.append(msg)

        # Connect signal using safe_connect
        worker.safe_connect(
            worker.test_signal,
            test_slot,
            Qt.ConnectionType.QueuedConnection,
        )

        # Emit signal and wait for queued connection to be processed
        worker.test_signal.emit("hello")
        qtbot.waitUntil(lambda: len(slot_called) > 0, timeout=100)

        # Check no Qt warnings were produced
        stderr_output = captured_stderr.getvalue()
        assert "unique connections require" not in stderr_output, (
            f"Qt warning detected in stderr:\n{stderr_output}"
        )
        assert "QObject::connect" not in stderr_output, (
            f"Qt connection warning detected:\n{stderr_output}"
        )

        # Verify connection actually worked
        assert slot_called == ["hello"], "Signal should have triggered slot"

        # Test cleanup
        worker.disconnect_all()
        qtbot.waitUntil(lambda: True, timeout=50)  # Drain event queue

    finally:
        sys.stderr = old_stderr


def test_safe_connect_deduplication(qapp: QApplication, qtbot) -> None:
    """Test that duplicate connections are prevented at application level."""
    worker = DummyWorker()
    call_count = []

    def counting_slot(msg: str) -> None:
        call_count.append(msg)

    # Connect same slot twice
    worker.safe_connect(worker.test_signal, counting_slot)
    worker.safe_connect(worker.test_signal, counting_slot)  # Should be ignored

    # Emit and wait for slot to be called
    worker.test_signal.emit("test")
    qtbot.waitUntil(lambda: len(call_count) > 0, timeout=100)

    # Should only be called once due to deduplication
    assert len(call_count) == 1, "Duplicate connection should be prevented"

    worker.disconnect_all()


def test_disconnect_produces_no_warnings(qapp: QApplication, qtbot) -> None:
    """Test that disconnect_all doesn't produce RuntimeWarnings."""
    old_stderr = sys.stderr
    sys.stderr = captured_stderr = StringIO()

    try:
        worker = DummyWorker()

        def dummy_slot(msg: str) -> None:
            pass

        worker.safe_connect(worker.test_signal, dummy_slot)

        # Disconnect should be silent
        worker.disconnect_all()
        qtbot.waitUntil(lambda: True, timeout=50)  # Drain event queue

        stderr_output = captured_stderr.getvalue()
        assert "Failed to disconnect" not in stderr_output, (
            f"Disconnect warning detected:\n{stderr_output}"
        )
        assert "RuntimeWarning" not in stderr_output, (
            f"RuntimeWarning detected:\n{stderr_output}"
        )

    finally:
        sys.stderr = old_stderr
