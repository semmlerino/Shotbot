"""Thread-safe base class for Qt workers with proper lifecycle management."""

# See: docs/THREADING_ARCHITECTURE.md

from __future__ import annotations

import logging

# Standard library imports
import time
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, final

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
from timeout_config import TimeoutConfig
from workers import zombie_registry


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable


@final
class WorkerState(Enum):
    """Thread-safe worker states."""

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    DELETED = "DELETED"
    ERROR = "ERROR"


class ThreadSafeWorker(QThread):
    """Base class for thread-safe workers with proper lifecycle management.

    This class provides:
    - Thread-safe state transitions
    - Safe signal connection tracking
    - Proper cleanup sequence
    - Protection against race conditions

    State machine:
    CREATED -> STARTING -> RUNNING -> STOPPING -> STOPPED -> DELETED
    """

    _cleanup_order: ClassVar[int] = 25
    _singleton_description: ClassVar[str] = "Zombie worker cleanup timer"

    # Lifecycle signals
    worker_started: ClassVar[Signal] = Signal()  # type: ignore[assignment]
    worker_stopping: ClassVar[Signal] = Signal()  # type: ignore[assignment]
    worker_stopped: ClassVar[Signal] = Signal()  # type: ignore[assignment]
    worker_error: ClassVar[Signal] = Signal(str)  # type: ignore[assignment]

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

    # Thread start times for diagnostics (track when each thread started)
    _thread_start_times: ClassVar[dict[int, float]] = {}

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize thread-safe worker.

        Args:
            parent: Optional parent QObject for proper Qt cleanup

        """
        super().__init__(parent)
        self._state_mutex: QMutex = QMutex()
        self._state: WorkerState = WorkerState.CREATED
        self._state_condition: QWaitCondition = QWaitCondition()
        self._stop_requested: bool = False
        self._force_stop: bool = False
        self._connections: list[tuple[SignalInstance, Callable[..., object]]] = []
        self._zombie: bool = False  # Track abandoned threads

        # Set up cleanup on thread finished
        _ = self.finished.connect(
            self._on_finished  # type: ignore[reportAny]
        )

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
        signal_to_emit: SignalInstance | None = None

        with QMutexLocker(self._state_mutex):
            current = self._state

            # Check if transition is valid
            if not force and new_state not in self.VALID_TRANSITIONS.get(current, []):
                try:
                    logger.warning(
                        f"Worker {id(self)}: Invalid transition {current.name} -> {new_state.name}",
                    )
                except (SystemError, RuntimeError):
                    # Can occur during Python shutdown
                    pass
                return False

            # Perform transition
            try:
                logger.debug(
                    f"Worker {id(self)}: {current.name} -> {new_state.name}"
                    + (" (forced)" if force else ""),
                )
            except (SystemError, RuntimeError):
                # Can occur during Python shutdown when enum module is being unloaded
                pass
            self._state = new_state

            # Wake waiting threads
            self._state_condition.wakeAll()

            # Determine which signal to emit (but don't emit inside mutex!)
            # NOTE: ERROR state does NOT emit here - error signals are emitted
            # from exception handlers with actual context (see run() method)
            if new_state == WorkerState.STOPPED:
                signal_to_emit = self.worker_stopped
            # No emission for ERROR - exception handler emits with real details

        # Emit signals outside the mutex to prevent deadlock
        # This prevents any possibility of deadlock if a slot tries to acquire the same mutex
        if signal_to_emit:
            try:
                signal_to_emit.emit()
            except (RuntimeError, SystemError):
                # Signal source may be deleted during shutdown
                pass

        return True

    def request_stop(self) -> bool:
        """Thread-safe stop request.

        Returns:
            True if stop was requested successfully, False if already stopping/stopped

        """
        signal_to_emit: SignalInstance | None = None

        with QMutexLocker(self._state_mutex):
            current = self._state

            if current in [
                WorkerState.STOPPED,
                WorkerState.DELETED,
                WorkerState.STOPPING,
            ]:
                logger.debug(
                    f"Worker {id(self)}: Already stopping/stopped ({current.name})",
                )
                return False

            # Can stop from CREATED, STARTING, or RUNNING states
            if current in [WorkerState.CREATED, WorkerState.STARTING]:
                # Direct transition to STOPPED if not yet running
                self._state = WorkerState.STOPPED
                self._stop_requested = True
                signal_to_emit = self.worker_stopped
                logger.debug(f"Worker {id(self)}: {current.name} -> STOPPED")
            elif current == WorkerState.RUNNING:
                # Normal stop sequence
                self._state = WorkerState.STOPPING
                self._stop_requested = True
                signal_to_emit = self.worker_stopping
                logger.debug(f"Worker {id(self)}: {current.name} -> STOPPING")
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
            logger.debug(f"Worker {id(self)}: Interruption detected")
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
                logger.debug(
                    f"Worker {id(self)}: Skipped duplicate connection for {slot.__name__}"
                )
                return

            self._connections.append(connection)

        # Connect outside mutex to prevent deadlock
        # NOTE: Don't use Qt.ConnectionType.UniqueConnection - it doesn't work with Python callables
        # Application-level deduplication (above) is more reliable for Python/Qt
        _ = signal.connect(slot, connection_type)

        logger.debug(
            f"Worker {id(self)}: Connected signal to {slot.__name__} with {connection_type}"
        )

    @property
    def connection_count(self) -> int:
        """Return the number of tracked signal connections.

        Returns:
            Number of active signal connections tracked by this worker.

        """
        with QMutexLocker(self._state_mutex):
            return len(self._connections)

    @Slot()  # type: ignore[reportAny]
    def disconnect_all(self) -> None:
        """Safely disconnect all tracked signals.

        This is safe to call even if signals are being emitted.
        Thread-safe with mutex protection to prevent race with safe_connect().
        """
        # Atomic copy-and-clear under single lock to prevent TOCTOU race
        # (new connections added between copy and clear would be lost otherwise)
        with QMutexLocker(self._state_mutex):
            connections_to_disconnect = self._connections.copy()
            self._connections.clear()
            connection_count = len(connections_to_disconnect)

        logger.debug(
            f"Worker {id(self)}: Disconnecting {connection_count} signals",
        )

        # Disconnect outside mutex to prevent deadlock
        for signal, slot in connections_to_disconnect:
            # Direct references now - no need to dereference
            try:
                _ = signal.disconnect(slot)
                logger.debug(f"Worker {id(self)}: Disconnected signal")
            except (RuntimeError, TypeError) as e:
                # Already disconnected or object deleted - this is fine
                logger.debug(
                    f"Worker {id(self)}: Signal already disconnected: {e}"
                )

    @Slot()  # type: ignore[reportAny]
    def run(self) -> None:
        """Main thread execution with proper state management.

        Override do_work() in subclasses to implement actual functionality.
        """
        # Track start time for diagnostics
        ThreadSafeWorker._thread_start_times[id(self)] = time.time()

        # Transition to STARTING
        if not self.set_state(WorkerState.STARTING):
            logger.error(f"Worker {id(self)}: Failed to start - invalid state")
            _ = ThreadSafeWorker._thread_start_times.pop(id(self), None)
            return

        # Check if stop was requested before we even started
        if self._stop_requested:
            _ = self.set_state(WorkerState.STOPPED)
            return

        # Emit started signal
        self.worker_started.emit()

        # Transition to RUNNING
        if not self.set_state(WorkerState.RUNNING):
            logger.error(f"Worker {id(self)}: Failed to transition to RUNNING")
            _ = self.set_state(WorkerState.STOPPED)
            return

        # Execute actual work
        try:
            # Check if thread should exit before starting work
            if self._force_stop:
                return
            if self.thread() and self.thread().isInterruptionRequested():
                logger.debug(
                    f"Worker {id(self)}: Interruption requested before work"
                )
                return

            self.do_work()
        except Exception as e:  # noqa: BLE001
            try:
                logger.exception(f"Worker {id(self)}: Exception in do_work")
                _ = self.set_state(WorkerState.ERROR)
                self.worker_error.emit(str(e))
            except (SystemError, RuntimeError):
                # Can occur during Python shutdown
                pass
        finally:
            # Respect the state machine - transition properly to STOPPED
            # Wrap in try/except to handle Python shutdown when enum module is being unloaded
            try:
                current_state = self.get_state()
                if current_state == WorkerState.RUNNING:
                    # Valid transition: RUNNING -> STOPPING -> STOPPED
                    if not self.set_state(WorkerState.STOPPING):
                        logger.warning(
                            "Failed to transition to STOPPING, forcing it"
                        )
                        _ = self.set_state(WorkerState.STOPPING, force=True)
                    # Now transition from STOPPING to STOPPED
                    if not self.set_state(WorkerState.STOPPED):
                        logger.warning(
                            "Failed to transition to STOPPED, forcing it"
                        )
                        _ = self.set_state(WorkerState.STOPPED, force=True)
                elif current_state == WorkerState.ERROR:
                    # Valid transition: ERROR -> STOPPED
                    if not self.set_state(WorkerState.STOPPED):
                        logger.warning(
                            "Failed to transition from ERROR to STOPPED, forcing it",
                        )
                        _ = self.set_state(WorkerState.STOPPED, force=True)
                elif current_state not in [WorkerState.STOPPED, WorkerState.DELETED]:
                    # For other states, try direct transition to STOPPED
                    if not self.set_state(WorkerState.STOPPED):
                        logger.warning(
                            f"Forcing STOPPED state from {current_state}"
                        )
                        _ = self.set_state(WorkerState.STOPPED, force=True)
            except (SystemError, RuntimeError):
                # Can occur during Python shutdown when enum module is being unloaded
                pass
            finally:
                # Clean up start time tracking
                _ = ThreadSafeWorker._thread_start_times.pop(id(self), None)

    def do_work(self) -> None:
        """Override this method with actual work implementation.

        This method should:
        - Periodically check is_stop_requested()
        - Exit gracefully when stop is requested
        - Handle its own exceptions
        """
        msg = "Subclasses must implement do_work()"
        raise NotImplementedError(msg)

    @Slot()  # type: ignore[reportAny]
    def _on_finished(self) -> None:
        """Handle thread finished signal for cleanup.

        This slot is connected to the thread's finished signal.
        Properly decorated with @Slot for Qt efficiency.
        """
        # Disconnect all signals when thread finishes
        self.disconnect_all()  # type: ignore[reportAny, no-untyped-call]

        # Respect state machine transitions - must go through STOPPED first
        with QMutexLocker(self._state_mutex):
            current = self._state

            # Transition to STOPPED first if needed, then to DELETED
            if current == WorkerState.STOPPED:
                # Valid transition: STOPPED -> DELETED
                self._state = WorkerState.DELETED
                logger.debug(
                    f"Worker {id(self)}: STOPPED -> DELETED (on finished)"
                )
            elif current in [WorkerState.RUNNING, WorkerState.STOPPING]:
                # Transition through STOPPED to DELETED
                logger.debug(
                    f"Worker {id(self)}: {current.name} -> STOPPED -> DELETED (on finished)"
                )
                self._state = WorkerState.STOPPED
                # Now complete the transition to DELETED
                self._state = WorkerState.DELETED
            elif current == WorkerState.ERROR:
                # ERROR -> STOPPED -> DELETED
                logger.debug(
                    f"Worker {id(self)}: ERROR -> STOPPED -> DELETED (on finished)"
                )
                self._state = WorkerState.STOPPED
                # Now complete the transition to DELETED
                self._state = WorkerState.DELETED
            elif current in [WorkerState.CREATED, WorkerState.STARTING]:
                # Thread finished before it really started - go to STOPPED -> DELETED
                logger.debug(
                    f"Worker {id(self)}: {current.name} -> STOPPED -> DELETED (on finished)"
                )
                self._state = WorkerState.STOPPED
                # Now complete the transition to DELETED
                self._state = WorkerState.DELETED
            elif current == WorkerState.DELETED:
                # Already deleted, nothing to do
                logger.debug(f"Worker {id(self)}: Already DELETED")
            else:
                logger.warning(
                    f"Worker {id(self)}: Unexpected state {current.name} in _on_finished"
                )

            # Wake any threads waiting on state changes (e.g. safe_wait via wait condition)
            self._state_condition.wakeAll()

    def safe_wait(
        self,
        timeout_ms: int = TimeoutConfig.WORKER_GRACEFUL_STOP_MS,
    ) -> bool:
        """Safely wait for worker to finish with timeout.

        Args:
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            True if worker finished, False if timeout

        Thread-Safe:
            Prevents self-join deadlock by detecting if called from worker's own thread.
        """
        if self.get_state() in [WorkerState.STOPPED, WorkerState.DELETED]:
            return True

        # Prevent self-join deadlock: cannot wait on self from worker thread
        if QThread.currentThread() is self:
            logger.warning(
                "Cannot wait on self from worker thread - returning False"
            )
            return False

        return self.wait(timeout_ms)

    def safe_stop(
        self,
        timeout_ms: int = TimeoutConfig.WORKER_GRACEFUL_STOP_MS,
    ) -> bool:
        """Safely stop worker with timeout.

        Args:
            timeout_ms: Maximum time to wait for stop

        Returns:
            True if stopped successfully, False if timeout

        Thread-Safe:
            Prevents self-join deadlock by detecting if called from worker's own thread.
            If called from worker thread, sets stop flags but does not wait.
        """
        # Prevent self-join deadlock: cannot stop self from worker thread
        if QThread.currentThread() is self:
            logger.warning(
                "Cannot stop self from worker thread - use request_stop() instead"
            )
            # Still set stop flags, just don't wait
            _ = self.request_stop()
            return False

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
            logger.warning(
                f"Worker failed to stop gracefully within {timeout_ms}ms"
            )
            # Use safe termination instead of terminate()
            self.safe_terminate()
            return False

        return True

    def safe_shutdown(
        self,
        timeout_ms: int = TimeoutConfig.WORKER_GRACEFUL_STOP_MS,
    ) -> None:
        """Stop the worker and schedule deletion if not a zombie.

        Callers remain responsible for signal disconnection and mutex management.

        Args:
            timeout_ms: Maximum time to wait for graceful stop in milliseconds.

        """
        _ = self.safe_stop(timeout_ms)
        if self.is_zombie():
            logger.warning(f"Worker {id(self)} is a zombie — skipping deleteLater")
        else:
            self.deleteLater()

    def is_zombie(self) -> bool:
        """Check if the worker thread has been abandoned as a zombie.

        A zombie thread is one that failed to stop gracefully and has been
        abandoned to prevent crashes from unsafe termination.

        Returns:
            True if thread is a zombie, False otherwise

        """
        with QMutexLocker(self._state_mutex):
            return self._zombie

    @classmethod
    def get_zombie_metrics(cls) -> dict[str, int]:
        """Return zombie metrics for monitoring timeout fix effectiveness.

        Use this to track whether the timeout improvements are working:
        - If created stays at 0, the fixes are working
        - If recovered > 0, zombies are finishing naturally (good)
        - If terminated > 0, we're still seeing stuck threads (needs investigation)

        Returns:
            Dictionary with zombie counts for this session

        """
        return zombie_registry.get_zombie_metrics()

    def safe_terminate(self) -> None:
        """Safely terminate the worker thread.

        This should only be used as a last resort after request_stop() and wait() fail.
        This version avoids using terminate() which can cause crashes.
        """
        zombie_registry.safe_terminate(self)

    @classmethod
    def cleanup_old_zombies(cls) -> int:
        """Attempt to clean up old zombie threads with escalating cleanup policy.

        Cleanup stages:
        1. Threads that finished naturally are removed immediately
        2. After _MAX_ZOMBIE_AGE_SECONDS (60s), logs warning
        3. After _ZOMBIE_TERMINATE_AGE_SECONDS (300s), force terminates

        This method should be called periodically to prevent unbounded
        memory growth from zombie thread accumulation.

        Returns:
            Number of zombies cleaned up

        """
        return zombie_registry.cleanup_old_zombies()

    @classmethod
    def start_zombie_cleanup_timer(cls) -> None:
        """Start the periodic zombie cleanup timer.

        This should be called once during application initialization to enable
        automatic cleanup of zombie threads. The timer runs in the main thread
        and calls cleanup_old_zombies() every 60 seconds.

        Thread-Safe:
            Safe to call from any thread. If called from a non-main thread,
            timer creation is deferred to the main thread via QTimer.singleShot.
            Uses mutex to prevent race conditions in timer creation.
        """
        zombie_registry.start_zombie_cleanup_timer()

    @classmethod
    def _create_zombie_timer_impl(cls) -> None:
        """Internal: Create the zombie cleanup timer (must be called on main thread).

        Uses mutex to prevent race conditions when multiple threads attempt
        to start the timer simultaneously.
        """
        zombie_registry.create_zombie_timer_impl()

    @classmethod
    def stop_zombie_cleanup_timer(cls) -> None:
        """Stop the periodic zombie cleanup timer.

        This should be called during application shutdown to cleanly stop
        the cleanup timer.

        Thread-Safe:
            Safe to call from any thread. Uses mutex to prevent race conditions.
        """
        zombie_registry.stop_zombie_cleanup_timer()

    @classmethod
    def reset(cls) -> None:
        """Reset class-level state for testing. INTERNAL USE ONLY.

        This method stops the zombie cleanup timer and clears all zombie
        tracking data. It should only be used in test cleanup to ensure
        test isolation.

        Note: This does NOT terminate running worker instances - that must
        be done separately by calling safe_stop() on each instance.

        Thread-Safe:
            Safe to call from any thread (uses _zombie_mutex).
        """
        import logging

        zombie_registry.reset_for_testing()
        logging.getLogger(__name__).debug("ThreadSafeWorker reset for testing")
