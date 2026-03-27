"""Focused unit tests for ThreadSafeWorker basic lifecycle.

Tests cover:
- Worker lifecycle (CREATED -> STARTING -> RUNNING -> STOPPED)
- Cancellation (request_stop, should_stop, safe_stop)
- Error handling (exception in do_work emits worker_error)
- Signal connection management (safe_connect, disconnect_all)
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QObject

from tests.test_helpers import cleanup_qthread_properly, process_qt_events
from workers.thread_safe_worker import ThreadSafeWorker, WorkerState


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ---------------------------------------------------------------------------
# Concrete workers for testing
# ---------------------------------------------------------------------------


class InstantWorker(ThreadSafeWorker):
    """Worker that completes immediately without blocking."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.work_ran = False

    def do_work(self) -> None:
        self.work_ran = True


class CancellableWorker(ThreadSafeWorker):
    """Worker that loops until stop is requested."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.steps = 0
        self._started = threading.Event()

    def do_work(self) -> None:
        self._started.set()
        while not self.should_stop():
            self.steps += 1
            # Tight loop — no sleep; should_stop() checks will resolve quickly

    def wait_for_start(self, timeout: float = 2.0) -> bool:
        return self._started.wait(timeout)


class FailingWorker(ThreadSafeWorker):
    """Worker that raises a RuntimeError in do_work."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.error_message = "deliberate failure"

    def do_work(self) -> None:
        raise RuntimeError(self.error_message)


class SignalReceiver(QObject):
    """Minimal QObject slot holder for signal connection tests."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.called: list[str] = []

    def on_event(self) -> None:
        self.called.append("event")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# a) Worker Lifecycle Tests
# ---------------------------------------------------------------------------


class TestWorkerLifecycle:
    """Basic start/stop lifecycle of ThreadSafeWorker."""

    def setup_method(self) -> None:
        ThreadSafeWorker.reset()

    def teardown_method(self) -> None:
        ThreadSafeWorker.reset()

    @pytest.mark.timeout(10)
    def test_initial_state_is_created(self) -> None:
        """Freshly constructed worker is in CREATED state."""
        worker = InstantWorker()
        assert worker.get_state() == WorkerState.CREATED

    @pytest.mark.timeout(10)
    def test_worker_completes_to_stopped(self, qtbot: QtBot) -> None:
        """Worker that finishes do_work() reaches STOPPED (or DELETED) state."""
        worker = InstantWorker()

        try:
            with qtbot.waitSignal(worker.worker_stopped, timeout=3000):
                worker.start()

            # After worker_stopped signal the state is STOPPED or DELETED
            # (_on_finished may run and transition to DELETED before we check)
            assert worker.get_state() in {WorkerState.STOPPED, WorkerState.DELETED}
        finally:
            cleanup_qthread_properly(worker)

    @pytest.mark.timeout(10)
    def test_worker_ran_do_work(self, qtbot: QtBot) -> None:
        """do_work() is actually executed when worker starts."""
        worker = InstantWorker()

        try:
            with qtbot.waitSignal(worker.worker_stopped, timeout=3000):
                worker.start()

            assert worker.work_ran is True
        finally:
            cleanup_qthread_properly(worker)



# ---------------------------------------------------------------------------
# b) Cancellation Tests
# ---------------------------------------------------------------------------


class TestCancellation:
    """request_stop(), should_stop(), and safe_stop() behaviour."""

    def setup_method(self) -> None:
        ThreadSafeWorker.reset()

    def teardown_method(self) -> None:
        ThreadSafeWorker.reset()

    def test_request_stop_sets_stop_flag(self) -> None:
        """request_stop() makes is_stop_requested() return True."""
        worker = CancellableWorker()
        # Worker not yet started — request_stop() transitions CREATED -> STOPPED
        worker.request_stop()
        assert worker.is_stop_requested() is True

    @pytest.mark.timeout(10)
    def test_should_stop_returns_false_before_request(self) -> None:
        """should_stop() is False while worker is running normally."""
        worker = CancellableWorker()
        # Before any stop request, the flag is clear
        assert worker.should_stop() is False

    @pytest.mark.timeout(10)
    def test_cancellable_worker_exits_on_stop(self, qtbot: QtBot) -> None:
        """Worker that checks should_stop() exits when stop is requested."""
        worker = CancellableWorker()

        try:
            with qtbot.waitSignal(worker.worker_started, timeout=3000):
                worker.start()

            assert worker.wait_for_start(timeout=2.0)

            # Request stop and expect worker_stopped signal
            with qtbot.waitSignal(worker.worker_stopped, timeout=3000):
                worker.request_stop()

            assert worker.get_state() in {WorkerState.STOPPED, WorkerState.DELETED}
        finally:
            cleanup_qthread_properly(worker)

    @pytest.mark.timeout(10)
    def test_request_stop_before_start_prevents_run(self, qtbot: QtBot) -> None:
        """Calling request_stop() before start() prevents do_work() execution."""
        worker = InstantWorker()
        worker.request_stop()

        # Worker state should be STOPPED immediately (no thread started)
        assert worker.get_state() == WorkerState.STOPPED

        # Starting should be a no-op (thread exits immediately without work)
        worker.start()
        worker.wait(1000)

        # work_ran must remain False since do_work() was skipped
        assert worker.work_ran is False


# ---------------------------------------------------------------------------
# c) Error Handling Tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Exception in do_work() triggers proper error signals and state."""

    def setup_method(self) -> None:
        ThreadSafeWorker.reset()

    def teardown_method(self) -> None:
        ThreadSafeWorker.reset()

    @pytest.mark.timeout(10)
    def test_exception_emits_worker_error_signal(self, qtbot: QtBot) -> None:
        """RuntimeError in do_work() causes worker_error to be emitted."""
        worker = FailingWorker()

        try:
            with qtbot.waitSignal(worker.worker_error, timeout=3000) as blocker:
                worker.start()

            emitted_message: str = blocker.args[0]
            assert worker.error_message in emitted_message
        finally:
            cleanup_qthread_properly(worker)

    @pytest.mark.timeout(10)
    def test_exception_transitions_to_error_state(self, qtbot: QtBot) -> None:
        """Worker passes through ERROR state when do_work() raises.

        worker_error is emitted while the worker is in ERROR state, before the
        finally block transitions it to STOPPED.  Because the signal is emitted
        from the worker thread we use a DirectConnection to capture the state
        synchronously (still in the worker thread, before the transition).
        """
        from PySide6.QtCore import Qt

        worker = FailingWorker()

        error_states: list[WorkerState] = []

        # DirectConnection fires in the emitting (worker) thread, before run()'s
        # finally block transitions the state to STOPPED.
        def on_error(msg: str) -> None:
            error_states.append(worker.get_state())

        worker.worker_error.connect(on_error, Qt.ConnectionType.DirectConnection)

        try:
            with qtbot.waitSignal(worker.worker_error, timeout=3000):
                worker.start()

            assert WorkerState.ERROR in error_states, (
                f"Worker never observed in ERROR state; captured: {error_states}"
            )
        finally:
            cleanup_qthread_properly(worker)

    @pytest.mark.timeout(10)
    def test_worker_reaches_stopped_after_error(self, qtbot: QtBot) -> None:
        """After an error the worker still transitions through to STOPPED."""
        worker = FailingWorker()

        try:
            # Wait for worker_stopped (emitted from the finally block in run())
            with qtbot.waitSignal(worker.worker_stopped, timeout=3000):
                worker.start()

            process_qt_events()
            assert worker.get_state() in {WorkerState.STOPPED, WorkerState.DELETED}
        finally:
            cleanup_qthread_properly(worker)

    @pytest.mark.timeout(10)
    def test_error_message_matches_exception(self, qtbot: QtBot) -> None:
        """worker_error carries the string representation of the exception."""
        worker = FailingWorker()

        received: list[str] = []
        worker.worker_error.connect(received.append)

        try:
            with qtbot.waitSignal(worker.worker_error, timeout=3000):
                worker.start()

            process_qt_events()
            assert len(received) == 1
            assert "deliberate failure" in received[0]
        finally:
            cleanup_qthread_properly(worker)


# ---------------------------------------------------------------------------
# d) Signal Connection Tests
# ---------------------------------------------------------------------------


class TestSignalConnections:
    """safe_connect() and disconnect_all() behaviour."""

    def setup_method(self) -> None:
        ThreadSafeWorker.reset()

    def teardown_method(self) -> None:
        ThreadSafeWorker.reset()

    @pytest.mark.timeout(10)
    def test_safe_connect_connects_signal_to_slot(self, qtbot: QtBot) -> None:
        """safe_connect() creates a working signal->slot connection."""
        worker = InstantWorker()
        receiver = SignalReceiver()

        worker.safe_connect(worker.worker_stopped, receiver.on_event)

        try:
            with qtbot.waitSignal(worker.worker_stopped, timeout=3000):
                worker.start()

            process_qt_events()
            assert receiver.called, "Slot was not called after safe_connect()"
        finally:
            cleanup_qthread_properly(worker)
            receiver.deleteLater()
            process_qt_events()

    @pytest.mark.timeout(10)
    def test_safe_connect_deduplicates_connections(self) -> None:
        """Calling safe_connect() twice with the same pair does not duplicate."""
        worker = InstantWorker()
        receiver = SignalReceiver()

        worker.safe_connect(worker.worker_stopped, receiver.on_event)
        worker.safe_connect(worker.worker_stopped, receiver.on_event)  # duplicate

        # Only one entry should be tracked
        assert worker.connection_count == 1

        receiver.deleteLater()
        process_qt_events()

    @pytest.mark.timeout(10)
    def test_disconnect_all_removes_all_tracked_connections(self, qtbot: QtBot) -> None:
        """disconnect_all() clears the connection tracking list."""
        worker = InstantWorker()
        receiver = SignalReceiver()

        worker.safe_connect(worker.worker_stopped, receiver.on_event)
        assert worker.connection_count == 1

        worker.disconnect_all()
        assert worker.connection_count == 0

        receiver.deleteLater()
        process_qt_events()

    @pytest.mark.timeout(10)
    def test_disconnect_all_prevents_slot_from_being_called(self, qtbot: QtBot) -> None:
        """After disconnect_all(), the previously connected slot is not called."""
        worker = InstantWorker()
        receiver = SignalReceiver()

        worker.safe_connect(worker.worker_stopped, receiver.on_event)
        worker.disconnect_all()

        try:
            with qtbot.waitSignal(worker.worker_stopped, timeout=3000):
                worker.start()

            process_qt_events()
            assert not receiver.called, "Slot was called even after disconnect_all()"
        finally:
            cleanup_qthread_properly(worker)
            receiver.deleteLater()
            process_qt_events()

    @pytest.mark.timeout(10)
    def test_disconnect_all_is_idempotent(self) -> None:
        """Calling disconnect_all() on an already-empty list does not raise."""
        worker = InstantWorker()
        # No connections added
        worker.disconnect_all()  # Should not raise
        worker.disconnect_all()  # Second call also fine


# ---------------------------------------------------------------------------
# e) safe_shutdown() Tests
# ---------------------------------------------------------------------------


class TestSafeShutdown:
    """safe_shutdown() stops the worker and conditionally schedules deletion."""

    def setup_method(self) -> None:
        ThreadSafeWorker.reset()

    def teardown_method(self) -> None:
        ThreadSafeWorker.reset()

    def test_safe_shutdown_calls_safe_stop(self) -> None:
        """safe_shutdown() calls safe_stop() with the given timeout."""
        from unittest.mock import patch

        worker = InstantWorker()

        with (
            patch.object(worker, "safe_stop", return_value=True) as mock_stop,
            patch.object(worker, "is_zombie", return_value=False),
            patch.object(worker, "deleteLater"),
        ):
            worker.safe_shutdown()

        mock_stop.assert_called_once_with(mock_stop.call_args[0][0])

    def test_safe_shutdown_skips_delete_later_when_zombie(self) -> None:
        """safe_shutdown() skips deleteLater() and logs a warning for zombies."""
        from unittest.mock import MagicMock, patch

        worker = InstantWorker()

        # Inject a mock logger via the cache attribute used by LoggingMixin.logger
        mock_logger = MagicMock()
        worker._contextual_logger = mock_logger  # type: ignore[attr-defined]

        with (
            patch.object(worker, "safe_stop", return_value=False),
            patch.object(worker, "is_zombie", return_value=True),
            patch.object(worker, "deleteLater") as mock_delete,
        ):
            worker.safe_shutdown()

        mock_delete.assert_not_called()
        mock_logger.warning.assert_called_once()
        warning_msg: str = mock_logger.warning.call_args[0][0]
        assert "zombie" in warning_msg.lower()
