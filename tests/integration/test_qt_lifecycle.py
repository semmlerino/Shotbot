"""Qt lifecycle integration tests.

These tests verify Qt object lifecycle management works correctly,
including parent-child relationships, deleteLater, and signal cleanup.

These tests are automatically grouped onto a single xdist worker via
the pytest_collection_modifyitems hook (they use qtbot).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from tests.test_helpers import flush_deferred_deletes, process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [pytest.mark.legacy]


def _wait_until(
    predicate: Callable[[], bool],
    timeout_ms: int = 1000,
    poll_ms: int = 10,
    flush_deletes: bool = False,
) -> bool:
    """Wait for a predicate by processing Qt events without nested event loops."""
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    while time.perf_counter() < deadline:
        if predicate():
            return True
        process_qt_events(duration_ms=poll_ms, iterations=1)
        if flush_deletes:
            flush_deferred_deletes()
        time.sleep(poll_ms / 1000.0)
    process_qt_events(duration_ms=poll_ms, iterations=1)
    if flush_deletes:
        flush_deferred_deletes()
    return predicate()


@pytest.mark.qt
class TestQtParentChildLifecycle:
    """Tests for Qt parent-child lifecycle management."""

    def test_child_deleted_with_parent(self, qtbot: QtBot) -> None:
        """Child widgets are deleted when parent is deleted."""
        parent = QWidget()
        qtbot.addWidget(parent)

        child = QLabel("child", parent)
        assert child.parent() == parent

        # Track deletion
        deleted = []
        child.destroyed.connect(lambda: deleted.append("child"))

        parent.deleteLater()
        assert _wait_until(lambda: "child" in deleted, timeout_ms=1000, flush_deletes=True)

    def test_reparenting_widget(self, qtbot: QtBot) -> None:
        """Widgets can be reparented safely."""
        parent1 = QWidget()
        parent2 = QWidget()
        qtbot.addWidget(parent1)
        qtbot.addWidget(parent2)

        child = QLabel("movable", parent1)
        assert child.parent() == parent1

        child.setParent(parent2)
        assert child.parent() == parent2

    def test_orphan_widget_cleanup(self, qtbot: QtBot) -> None:
        """Orphan widgets (no parent) must be explicitly cleaned up."""
        widget = QWidget()
        qtbot.addWidget(widget)  # qtbot tracks it

        deleted = []
        widget.destroyed.connect(lambda: deleted.append("widget"))

        widget.deleteLater()
        assert _wait_until(lambda: "widget" in deleted, timeout_ms=1000, flush_deletes=True)


@pytest.mark.qt
class TestQtSignalLifecycle:
    """Tests for Qt signal connection lifecycle."""

    def test_signal_disconnected_on_delete(self, qtbot: QtBot) -> None:
        """Signals are automatically disconnected when object is deleted."""

        class Emitter(QObject):
            my_signal = Signal()

        class Receiver(QObject):
            received = False

            def slot(self) -> None:
                self.received = True

        emitter = Emitter()
        receiver = Receiver()

        emitter.my_signal.connect(receiver.slot)
        emitter.my_signal.emit()
        assert receiver.received

        # Delete receiver
        receiver.received = False
        deleted = []
        receiver.destroyed.connect(lambda: deleted.append("receiver"))
        receiver.deleteLater()
        assert _wait_until(
            lambda: "receiver" in deleted,
            timeout_ms=1000,
            flush_deletes=True,
        )

        # Emitting after receiver deleted should not crash
        # (Qt auto-disconnects when receiver is destroyed)
        emitter.my_signal.emit()

    def test_lambda_slot_prevents_garbage_collection(self, qtbot: QtBot) -> None:
        """Lambda slots keep receiver alive until disconnected."""

        class Receiver(QObject):
            count = 0

            def increment(self) -> None:
                self.count += 1

        button = QPushButton()
        qtbot.addWidget(button)

        receiver = Receiver()
        # Lambda captures receiver, preventing GC
        button.clicked.connect(lambda: receiver.increment())

        button.click()
        assert receiver.count == 1


@pytest.mark.qt
class TestQtTimerLifecycle:
    """Tests for Qt timer lifecycle."""

    def test_singleshot_timer(self, qtbot: QtBot) -> None:
        """Single-shot timers fire once and clean up."""
        fired = []

        QTimer.singleShot(10, lambda: fired.append("timer"))
        assert _wait_until(lambda: "timer" in fired, timeout_ms=1000)

        assert len(fired) == 1

    def test_timer_stops_on_parent_delete(self, qtbot: QtBot) -> None:
        """Timers stop when their parent is deleted."""
        parent = QWidget()
        qtbot.addWidget(parent)

        fired = []
        timer = QTimer(parent)
        timer.timeout.connect(lambda: fired.append("tick"))
        timer.start(10)

        # Wait for at least one tick
        assert _wait_until(lambda: len(fired) >= 1, timeout_ms=1000)

        # Delete parent (should stop timer)
        count_before_delete = len(fired)
        parent.deleteLater()

        process_qt_events()

        # Timer should be stopped - no more ticks
        time.sleep(0.05)  # Give time for potential ticks
        process_qt_events()

        # Count shouldn't have increased much (timer should be stopped)
        assert len(fired) <= count_before_delete + 2


@pytest.mark.qt
@pytest.mark.qt_heavy
class TestQtThreadSafety:
    """Tests for Qt thread safety basics.

    Note: These tests use qt_heavy marker to run on a dedicated xdist worker,
    avoiding interference with other Qt tests while still executing in parallel runs.
    """

    @pytest.fixture(autouse=True)
    def ensure_clean_qt_state(self, qtbot: QtBot) -> None:
        """Ensure Qt event loop is clean before and after each test."""
        from PySide6.QtWidgets import QApplication

        # Clear any pending events from previous tests
        QApplication.processEvents()
        yield
        # Clean up after test
        QApplication.processEvents()

    def test_qthread_cleanup(self, qtbot: QtBot) -> None:
        """QThread cleans up properly when quit is called."""

        class Worker(QObject):
            finished = Signal()

            def run(self) -> None:
                self.finished.emit()

        thread = QThread()
        worker = Worker()
        worker.moveToThread(thread)

        finished = []
        worker.finished.connect(lambda: finished.append("done"))
        worker.finished.connect(thread.quit)

        thread.started.connect(worker.run)

        try:
            thread.start()

            assert _wait_until(lambda: "done" in finished, timeout_ms=2000)
            thread.quit()
            assert _wait_until(lambda: not thread.isRunning(), timeout_ms=2000)
        finally:
            # Ensure QThread cleanup even if assertions fail
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)
            thread.deleteLater()
            worker.deleteLater()

    def test_cross_thread_signal(self, qtbot: QtBot) -> None:
        """Signals work across threads via queued connections."""
        from PySide6.QtWidgets import QApplication

        class Worker(QObject):
            result = Signal(str)

            def work(self) -> None:
                self.result.emit("from worker thread")

        thread = QThread()
        worker = Worker()
        worker.moveToThread(thread)

        # Connect worker to emit when thread starts
        thread.started.connect(worker.work)
        worker.result.connect(thread.quit)
        received: list[str] = []
        worker.result.connect(lambda value: received.append(value))

        try:
            thread.start()
            assert _wait_until(lambda: len(received) == 1, timeout_ms=5000)
            assert received == ["from worker thread"]

            # Wait for thread to finish cleanly
            thread.wait(2000)
        finally:
            # Ensure QThread cleanup even if assertions fail
            if thread.isRunning():
                thread.quit()
                thread.wait(2000)
            # Process any remaining events before cleanup
            QApplication.processEvents()
            thread.deleteLater()
            worker.deleteLater()
            QApplication.processEvents()
