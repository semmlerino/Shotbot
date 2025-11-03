"""Thread-safe base class for Qt workers with proper lifecycle management."""

from __future__ import annotations

# Standard library imports
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    QThread,
    QWaitCondition,
    Signal,
    SignalInstance,
    Slot,
)

# Local application imports
from config import ThreadingConfig
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable


class WorkerState(LoggingMixin, Enum):
    """Thread-safe worker states."""

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    DELETED = "DELETED"
    ERROR = "ERROR"


class ThreadSafeWorker(LoggingMixin, QThread):
    """Base class for thread-safe workers with proper lifecycle management.

    This class provides:
    - Thread-safe state transitions
    - Safe signal connection tracking
    - Proper cleanup sequence
    - Protection against race conditions

    State machine:
    CREATED -> STARTING -> RUNNING -> STOPPING -> STOPPED -> DELETED
    """

    # Lifecycle signals
    worker_started = Signal()
    worker_stopping = Signal()
    worker_stopped = Signal()
    worker_error = Signal(str)

    # Valid state transitions
    VALID_TRANSITIONS: ClassVar[dict[WorkerState, list[WorkerState]]] = {
        WorkerState.CREATED: [WorkerState.STARTING, WorkerState.STOPPED],
        WorkerState.STARTING: [
            WorkerState.RUNNING,
            WorkerState.STOPPED,
            WorkerState.ERROR,
        ],
        WorkerState.RUNNING: [WorkerState.STOPPING, WorkerState.ERROR],
        WorkerState.STOPPING: [WorkerState.STOPPED],
        WorkerState.STOPPED: [WorkerState.DELETED],
        WorkerState.ERROR: [WorkerState.STOPPED],
        WorkerState.DELETED: [],  # Terminal state
    }

    # Class-level collection to prevent garbage collection of zombie threads
    # This prevents "QThread: Destroyed while thread is still running" crashes
    _zombie_threads: ClassVar[list[ThreadSafeWorker]] = []
    _zombie_mutex: ClassVar[QMutex] = QMutex()  # Protects _zombie_threads access

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize thread-safe worker.

        Args:
            parent: Optional parent QObject for proper Qt cleanup
        """
        super().__init__(parent)
        self._state_mutex = QMutex()
        self._state = WorkerState.CREATED
        self._state_condition = QWaitCondition()
        self._stop_requested = False
        self._force_stop = False
        self._connections: list[tuple[SignalInstance, object]] = []
        self._zombie = False  # Track abandoned threads

        # Set up cleanup on thread finished
        _ = self.finished.connect(self._on_finished)

    def get_state(self) -> WorkerState:
        """Thread-safe state getter.

        Returns:
            Current WorkerState
        """
        with QMutexLocker(self._state_mutex):
            return self._state

    def set_state(self, new_state: WorkerState, force: bool = False) -> bool:
        """Thread-safe state setter with validation.

        Args:
            new_state: State to transition to
            force: Force transition even if invalid (emergency stop)

        Returns:
            True if transition was valid and executed, False otherwise
        """
        signal_to_emit = None

        with QMutexLocker(self._state_mutex):
            current = self._state

            # Check if transition is valid
            if not force and new_state not in self.VALID_TRANSITIONS.get(current, []):
                self.logger.warning(
                    f"Worker {id(self)}: Invalid transition {current.name} -> {new_state.name}",
                )
                return False

            # Perform transition
            self.logger.debug(
                f"Worker {id(self)}: {current.name} -> {new_state.name}"
                + (" (forced)" if force else ""),
            )
            self._state = new_state

            # Wake waiting threads
            self._state_condition.wakeAll()

            # Determine which signal to emit (but don't emit inside mutex!)
            if new_state == WorkerState.STOPPED:
                signal_to_emit = self.worker_stopped
            elif new_state == WorkerState.ERROR:
                # Store error message for emission outside mutex
                signal_to_emit = (self.worker_error, "State error")

        # Emit signals outside the mutex to prevent deadlock
        # This prevents any possibility of deadlock if a slot tries to acquire the same mutex
        if signal_to_emit:
            if isinstance(signal_to_emit, tuple):
                # Signal with arguments
                signal, *args = signal_to_emit
                signal.emit(*args)
            else:
                # Signal without arguments
                signal_to_emit.emit()

        return True

    def request_stop(self) -> bool:
        """Thread-safe stop request.

        Returns:
            True if stop was requested successfully, False if already stopping/stopped
        """
        signal_to_emit = None

        with QMutexLocker(self._state_mutex):
            current = self._state

            if current in [
                WorkerState.STOPPED,
                WorkerState.DELETED,
                WorkerState.STOPPING,
            ]:
                self.logger.debug(
                    f"Worker {id(self)}: Already stopping/stopped ({current.name})",
                )
                return False

            # Can stop from CREATED, STARTING, or RUNNING states
            if current in [WorkerState.CREATED, WorkerState.STARTING]:
                # Direct transition to STOPPED if not yet running
                self._state = WorkerState.STOPPED
                self._stop_requested = True
                signal_to_emit = self.worker_stopped
                self.logger.debug(f"Worker {id(self)}: {current.name} -> STOPPED")
            elif current == WorkerState.RUNNING:
                # Normal stop sequence
                self._state = WorkerState.STOPPING
                self._stop_requested = True
                signal_to_emit = self.worker_stopping
                self.logger.debug(f"Worker {id(self)}: {current.name} -> STOPPING")
            else:
                return False

        # Emit signal OUTSIDE mutex to prevent deadlock
        # Direct emission is safe here since we're outside the mutex
        if signal_to_emit:
            signal_to_emit.emit()

        return True

    def is_stop_requested(self) -> bool:
        """Check if stop has been requested.

        Returns:
            True if stop was requested
        """
        with QMutexLocker(self._state_mutex):
            return self._stop_requested

    def should_stop(self) -> bool:
        """Check if the worker should stop (either stop requested or thread interrupted).

        This is the recommended method to check in do_work() implementations.

        Returns:
            True if the worker should stop, False otherwise
        """
        # Check for stop request
        if self.is_stop_requested():
            return True

        # Check for thread interruption (from safe_terminate)
        if self.isInterruptionRequested():
            self.logger.debug(f"Worker {id(self)}: Interruption detected")
            return True

        return False

    def safe_connect(
        self,
        signal: SignalInstance,
        slot: Callable[..., object],
        connection_type: Qt.ConnectionType = Qt.ConnectionType.QueuedConnection,
    ) -> None:
        """Track signal connections for safe cleanup with deduplication.

        This method ensures connections are unique - calling it multiple times
        with the same signal/slot pair will not create duplicate connections.

        Args:
            signal: Signal to connect (runtime SignalInstance)
            slot: Slot to connect to
            connection_type: Qt connection type (default: QueuedConnection for thread safety)
        """
        # Store direct references - Qt signals don't support weak references
        # The connections will be cleaned up in disconnect_all()
        connection = (signal, slot)

        # CRITICAL: Atomic check-and-add using mutex to prevent race conditions
        with QMutexLocker(self._state_mutex):
            # Prevent duplicate connections at application level
            if connection in self._connections:
                self.logger.debug(
                    f"Worker {id(self)}: Skipped duplicate connection for {slot.__name__}"
                )
                return

            self._connections.append(connection)

        # Connect outside mutex to prevent deadlock
        # NOTE: Don't use Qt.ConnectionType.UniqueConnection - it doesn't work with Python callables
        # Application-level deduplication (above) is more reliable for Python/Qt
        _ = signal.connect(slot, connection_type)

        self.logger.debug(
            f"Worker {id(self)}: Connected signal to {slot.__name__} with {connection_type}"
        )

    @Slot()
    def disconnect_all(self) -> None:
        """Safely disconnect all tracked signals.

        This is safe to call even if signals are being emitted.
        Thread-safe with mutex protection to prevent race with safe_connect().
        """
        # Copy connections list under mutex protection
        with QMutexLocker(self._state_mutex):
            connections_to_disconnect = self._connections.copy()
            connection_count = len(connections_to_disconnect)

        self.logger.debug(
            f"Worker {id(self)}: Disconnecting {connection_count} signals",
        )

        # Disconnect outside mutex to prevent deadlock
        for signal, slot in connections_to_disconnect:
            # Direct references now - no need to dereference
            try:
                _ = signal.disconnect(slot)
                self.logger.debug(f"Worker {id(self)}: Disconnected signal")
            except (RuntimeError, TypeError) as e:
                # Already disconnected or object deleted - this is fine
                self.logger.debug(
                    f"Worker {id(self)}: Signal already disconnected: {e}"
                )

        # Clear the connections list under mutex protection
        with QMutexLocker(self._state_mutex):
            self._connections.clear()

    @Slot()
    def run(self) -> None:
        """Main thread execution with proper state management.

        Override do_work() in subclasses to implement actual functionality.
        """
        # Transition to STARTING
        if not self.set_state(WorkerState.STARTING):
            self.logger.error(f"Worker {id(self)}: Failed to start - invalid state")
            return

        # Check if stop was requested before we even started
        if self._stop_requested:
            _ = self.set_state(WorkerState.STOPPED)
            return

        # Emit started signal
        self.worker_started.emit()

        # Transition to RUNNING
        if not self.set_state(WorkerState.RUNNING):
            self.logger.error(f"Worker {id(self)}: Failed to transition to RUNNING")
            _ = self.set_state(WorkerState.STOPPED)
            return

        # Execute actual work
        try:
            # Check if thread should exit before starting work
            if self._force_stop:
                return
            if self.thread() and self.thread().isInterruptionRequested():
                self.logger.debug(
                    f"Worker {id(self)}: Interruption requested before work"
                )
                return

            self.do_work()
        except Exception as e:
            self.logger.exception(f"Worker {id(self)}: Exception in do_work")
            _ = self.set_state(WorkerState.ERROR)
            self.worker_error.emit(str(e))
        finally:
            # Respect the state machine - transition properly to STOPPED
            current_state = self.get_state()
            if current_state == WorkerState.RUNNING:
                # Valid transition: RUNNING -> STOPPING -> STOPPED
                if not self.set_state(WorkerState.STOPPING):
                    self.logger.warning("Failed to transition to STOPPING, forcing it")
                    _ = self.set_state(WorkerState.STOPPING, force=True)
                # Now transition from STOPPING to STOPPED
                if not self.set_state(WorkerState.STOPPED):
                    self.logger.warning("Failed to transition to STOPPED, forcing it")
                    _ = self.set_state(WorkerState.STOPPED, force=True)
            elif current_state == WorkerState.ERROR:
                # Valid transition: ERROR -> STOPPED
                if not self.set_state(WorkerState.STOPPED):
                    self.logger.warning(
                        "Failed to transition from ERROR to STOPPED, forcing it",
                    )
                    _ = self.set_state(WorkerState.STOPPED, force=True)
            elif current_state not in [WorkerState.STOPPED, WorkerState.DELETED]:
                # For other states, try direct transition to STOPPED
                if not self.set_state(WorkerState.STOPPED):
                    self.logger.warning(f"Forcing STOPPED state from {current_state}")
                    _ = self.set_state(WorkerState.STOPPED, force=True)

    def do_work(self) -> None:
        """Override this method with actual work implementation.

        This method should:
        - Periodically check is_stop_requested()
        - Exit gracefully when stop is requested
        - Handle its own exceptions
        """
        raise NotImplementedError("Subclasses must implement do_work()")

    @Slot()
    def _on_finished(self) -> None:
        """Handle thread finished signal for cleanup.

        This slot is connected to the thread's finished signal.
        Properly decorated with @Slot for Qt efficiency.
        """
        # Disconnect all signals when thread finishes
        self.disconnect_all()

        # Respect state machine transitions - must go through STOPPED first
        with QMutexLocker(self._state_mutex):
            current = self._state

            # Transition to STOPPED first if needed, then to DELETED
            if current == WorkerState.STOPPED:
                # Valid transition: STOPPED -> DELETED
                self._state = WorkerState.DELETED
                self.logger.debug(
                    f"Worker {id(self)}: STOPPED -> DELETED (on finished)"
                )
            elif current in [WorkerState.RUNNING, WorkerState.STOPPING]:
                # Transition through STOPPED to DELETED
                self.logger.debug(
                    f"Worker {id(self)}: {current.name} -> STOPPED -> DELETED (on finished)"
                )
                self._state = WorkerState.STOPPED
                # Now complete the transition to DELETED
                self._state = WorkerState.DELETED
            elif current == WorkerState.ERROR:
                # ERROR -> STOPPED -> DELETED
                self.logger.debug(
                    f"Worker {id(self)}: ERROR -> STOPPED -> DELETED (on finished)"
                )
                self._state = WorkerState.STOPPED
                # Now complete the transition to DELETED
                self._state = WorkerState.DELETED
            elif current in [WorkerState.CREATED, WorkerState.STARTING]:
                # Thread finished before it really started - go to STOPPED -> DELETED
                self.logger.debug(
                    f"Worker {id(self)}: {current.name} -> STOPPED -> DELETED (on finished)"
                )
                self._state = WorkerState.STOPPED
                # Now complete the transition to DELETED
                self._state = WorkerState.DELETED
            elif current == WorkerState.DELETED:
                # Already deleted, nothing to do
                self.logger.debug(f"Worker {id(self)}: Already DELETED")
            else:
                self.logger.warning(
                    f"Worker {id(self)}: Unexpected state {current.name} in _on_finished"
                )

    def safe_wait(
        self,
        timeout_ms: int = ThreadingConfig.WORKER_STOP_TIMEOUT_MS,
    ) -> bool:
        """Safely wait for worker to finish with timeout.

        Args:
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            True if worker finished, False if timeout
        """
        if self.get_state() in [WorkerState.STOPPED, WorkerState.DELETED]:
            return True

        return self.wait(timeout_ms)

    def safe_stop(
        self,
        timeout_ms: int = ThreadingConfig.WORKER_STOP_TIMEOUT_MS,
    ) -> bool:
        """Safely stop worker with timeout.

        Args:
            timeout_ms: Maximum time to wait for stop

        Returns:
            True if stopped successfully, False if timeout
        """
        # Use request_stop() to properly set stop flags
        if not self.request_stop():
            # If request_stop failed, try to force stop
            with QMutexLocker(self._state_mutex):
                self._stop_requested = True
                self._force_stop = True
        else:
            # Also set force stop for additional safety
            with QMutexLocker(self._state_mutex):
                self._force_stop = True

        # Wake any waiting threads
        self._state_condition.wakeAll()

        # Wait for thread to finish
        if not self.wait(timeout_ms):
            self.logger.warning(
                f"Worker failed to stop gracefully within {timeout_ms}ms"
            )
            # Use safe termination instead of terminate()
            self.safe_terminate()
            return False

        return True

    def is_zombie(self) -> bool:
        """Check if the worker thread has been abandoned as a zombie.

        A zombie thread is one that failed to stop gracefully and has been
        abandoned to prevent crashes from unsafe termination.

        Returns:
            True if thread is a zombie, False otherwise
        """
        with QMutexLocker(self._state_mutex):
            return self._zombie

    def safe_terminate(self) -> None:
        """Safely terminate the worker thread.

        This should only be used as a last resort after request_stop() and wait() fail.
        This version avoids using terminate() which can cause crashes.
        """
        state = self.get_state()

        if state in [WorkerState.STOPPED, WorkerState.DELETED]:
            self.logger.debug(
                f"Worker {id(self)}: Already stopped, no termination needed"
            )
            return

        self.logger.warning(
            f"Worker {id(self)}: Requesting stop from state {state.name}"
        )

        # Disconnect signals before any termination attempt
        self.disconnect_all()

        # Force state transition
        with QMutexLocker(self._state_mutex):
            self._state = WorkerState.STOPPED
            self._stop_requested = True
            self._force_stop = True

        # Try graceful shutdown first
        if self.isRunning():
            # Request interruption - this is the Qt way to interrupt blocking operations
            self.requestInterruption()

            # Request event loop to quit
            self.quit()

            # Wait for graceful shutdown with shorter initial timeout
            if not self.wait(ThreadingConfig.WORKER_STOP_TIMEOUT_MS):  # Initial timeout
                self.logger.warning(
                    f"Worker {id(self)}: Still running after {ThreadingConfig.WORKER_STOP_TIMEOUT_MS}ms, waiting longer...",
                )

                # Try one more time with longer timeout
                if not self.wait(
                    ThreadingConfig.WORKER_TERMINATE_TIMEOUT_MS * 3,
                ):  # Extended timeout
                    self.logger.error(
                        f"Worker {id(self)}: Failed to stop gracefully after 5s total. "
                         "Thread will be abandoned (NOT terminated) to prevent crashes."
                    )
                    # DO NOT call terminate() - it's unsafe!
                    # Instead, mark as zombie and add to class collection to prevent GC
                    with QMutexLocker(self._state_mutex):
                        self._zombie = True

                    # Add to class-level collection to prevent garbage collection
                    # This prevents "QThread: Destroyed while thread is still running" crash
                    with QMutexLocker(ThreadSafeWorker._zombie_mutex):
                        ThreadSafeWorker._zombie_threads.append(self)
                        zombie_count = len(ThreadSafeWorker._zombie_threads)

                    self.logger.warning(
                        f"Worker {id(self)}: Added to zombie collection "
                         f"({zombie_count} total zombies)"
                    )
                else:
                    self.logger.info(f"Worker {id(self)}: Stopped after extended wait")
            else:
                self.logger.info(f"Worker {id(self)}: Stopped gracefully")
