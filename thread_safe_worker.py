"""Thread-safe base class for Qt workers with proper lifecycle management."""

from __future__ import annotations

# Standard library imports
import os
import time
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, final

# Third-party imports
from PySide6.QtCore import (
    QCoreApplication,
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    QThread,
    QTimer,
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


@final
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
    worker_started: Signal = Signal()  # type: ignore[assignment]
    worker_stopping: Signal = Signal()  # type: ignore[assignment]
    worker_stopped: Signal = Signal()  # type: ignore[assignment]
    worker_error: Signal = Signal(str)  # type: ignore[assignment]

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
    _zombie_timestamps: ClassVar[dict[int, float]] = {}  # Track when zombified
    _zombie_mutex: ClassVar[QMutex] = QMutex()  # Protects _zombie_threads access
    _zombie_cleanup_timer: ClassVar[QTimer | None] = None  # Periodic cleanup timer
    _MAX_ZOMBIE_AGE_SECONDS: ClassVar[int] = 60  # Log warning after 60s
    _ZOMBIE_TERMINATE_AGE_SECONDS: ClassVar[int] = 300  # Force terminate after 5 min
    _ZOMBIE_CLEANUP_INTERVAL_MS: ClassVar[int] = 60000  # Cleanup every 60s

    # Zombie metrics for monitoring effectiveness of timeout fixes
    _zombie_created_count: ClassVar[int] = 0  # Total zombies created this session
    _zombie_recovered_count: ClassVar[int] = 0  # Zombies that finished naturally
    _zombie_terminated_count: ClassVar[int] = 0  # Zombies force-terminated

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
        self._connections: list[tuple[SignalInstance, object]] = []
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
                    self.logger.warning(
                        f"Worker {id(self)}: Invalid transition {current.name} -> {new_state.name}",
                    )
                except (SystemError, RuntimeError):
                    # Can occur during Python shutdown
                    pass
                return False

            # Perform transition
            try:
                self.logger.debug(
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
            try:
                if new_state == WorkerState.STOPPED:
                    signal_to_emit = self.worker_stopped
                # No emission for ERROR - exception handler emits with real details
            except (SystemError, RuntimeError):
                # Can occur during Python shutdown when enum module is being unloaded
                pass

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

    @Slot()  # type: ignore[reportAny]
    def run(self) -> None:
        """Main thread execution with proper state management.

        Override do_work() in subclasses to implement actual functionality.
        """
        # Track start time for diagnostics
        ThreadSafeWorker._thread_start_times[id(self)] = time.time()

        # Transition to STARTING
        if not self.set_state(WorkerState.STARTING):
            self.logger.error(f"Worker {id(self)}: Failed to start - invalid state")
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
            try:
                self.logger.exception(f"Worker {id(self)}: Exception in do_work")
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

        Thread-Safe:
            Prevents self-join deadlock by detecting if called from worker's own thread.
        """
        if self.get_state() in [WorkerState.STOPPED, WorkerState.DELETED]:
            return True

        # Prevent self-join deadlock: cannot wait on self from worker thread
        if QThread.currentThread() is self:
            self.logger.warning("Cannot wait on self from worker thread - returning False")
            return False

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

        Thread-Safe:
            Prevents self-join deadlock by detecting if called from worker's own thread.
            If called from worker thread, sets stop flags but does not wait.
        """
        # Prevent self-join deadlock: cannot stop self from worker thread
        if QThread.currentThread() is self:
            self.logger.warning(
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
        with QMutexLocker(cls._zombie_mutex):
            return {
                "created": cls._zombie_created_count,
                "recovered": cls._zombie_recovered_count,
                "terminated": cls._zombie_terminated_count,
                "current": len(cls._zombie_threads),
            }

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
        self.disconnect_all()  # type: ignore[reportAny, no-untyped-call]

        # Set stop flags but NOT state yet - state only changes after confirmed stop
        with QMutexLocker(self._state_mutex):
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
                    # CAPTURE DIAGNOSTICS BEFORE ABANDONMENT
                    # Import here to avoid circular imports
                    from thread_diagnostics import ThreadDiagnostics

                    start_time = ThreadSafeWorker._thread_start_times.get(id(self))
                    report = ThreadDiagnostics.capture_thread_state(self, start_time)
                    ThreadDiagnostics.log_abandonment(
                        self,
                        f"Failed to stop after {ThreadingConfig.WORKER_STOP_TIMEOUT_MS + ThreadingConfig.WORKER_TERMINATE_TIMEOUT_MS * 3}ms",
                        report,
                    )

                    self.logger.error(
                        f"Worker {id(self)}: Failed to stop gracefully after 5s total. "
                        "Thread will be abandoned (NOT terminated) to prevent crashes."
                    )
                    # DO NOT call terminate() - it's unsafe!
                    # Instead, mark as zombie and add to class collection to prevent GC
                    # NOTE: State stays at previous value - thread is still running!
                    with QMutexLocker(self._state_mutex):
                        self._zombie = True

                    # Add to class-level collection to prevent garbage collection
                    # This prevents "QThread: Destroyed while thread is still running" crash
                    # FIXED: Don't call cleanup_old_zombies() from within mutex (DEADLOCK!)
                    # QMutex is NOT recursive - cleanup_old_zombies() tries to acquire
                    # the same mutex again → deadlock. Let periodic cleanup handle it.
                    with QMutexLocker(ThreadSafeWorker._zombie_mutex):
                        ThreadSafeWorker._zombie_threads.append(self)
                        ThreadSafeWorker._zombie_timestamps[id(self)] = time.time()
                        ThreadSafeWorker._zombie_created_count += 1  # Track for metrics
                        zombie_count = len(ThreadSafeWorker._zombie_threads)

                    self.logger.warning(
                        f"Worker {id(self)}: Added to zombie collection "
                        f"({zombie_count} total zombies). "
                        "Periodic cleanup will attempt recovery."
                    )
                else:
                    # Thread actually stopped - NOW set state to STOPPED
                    with QMutexLocker(self._state_mutex):
                        self._state = WorkerState.STOPPED
                    self.logger.info(f"Worker {id(self)}: Stopped after extended wait")
            else:
                # Thread actually stopped - NOW set state to STOPPED
                with QMutexLocker(self._state_mutex):
                    self._state = WorkerState.STOPPED
                self.logger.info(f"Worker {id(self)}: Stopped gracefully")
        else:
            # Thread was already stopped - set state to STOPPED
            with QMutexLocker(self._state_mutex):
                self._state = WorkerState.STOPPED

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
        # Import logging here to avoid issues during shutdown
        import logging

        logger = logging.getLogger(__name__)
        cleaned = 0
        current_time = time.time()

        # CRITICAL: Protect all access to shared zombie collections
        # NOTE: This method should NOT be called from within _zombie_mutex critical section
        # as QMutex is NOT recursive and would cause deadlock.
        with QMutexLocker(cls._zombie_mutex):
            zombies_to_keep: list[ThreadSafeWorker] = []

            for zombie in cls._zombie_threads:
                zombie_id = id(zombie)
                age = current_time - cls._zombie_timestamps.get(zombie_id, current_time)

                if not zombie.isRunning():
                    # Thread finished naturally, safe to remove
                    _ = cls._zombie_timestamps.pop(zombie_id, None)
                    cls._zombie_recovered_count += 1  # Track natural recovery
                    cleaned += 1
                    logger.info(f"Zombie {zombie_id} finished naturally after {age:.0f}s")
                elif age > cls._ZOMBIE_TERMINATE_AGE_SECONDS:
                    # CAPTURE DIAGNOSTICS BEFORE ANY TERMINATE
                    # Import here to avoid issues during shutdown
                    from thread_diagnostics import ThreadDiagnostics

                    start_time = cls._thread_start_times.get(zombie_id)
                    report = ThreadDiagnostics.capture_thread_state(zombie, start_time)
                    ThreadDiagnostics.log_abandonment(
                        zombie,
                        f"Zombie timeout after {age:.0f}s",
                        report,
                    )

                    # Only terminate in test mode - production leaves zombies to be
                    # killed on process exit (safer than terminate() which can crash)
                    allow_terminate = os.environ.get("SHOTBOT_TEST_MODE", "0") == "1"

                    if allow_terminate:
                        # Test mode: force terminate to prevent CI hangs
                        logger.warning(
                            f"Force-terminating zombie {zombie_id} after {age:.0f}s (TEST MODE)"
                        )
                        zombie.terminate()
                        _ = zombie.wait(1000)  # Brief wait after terminate
                        _ = cls._zombie_timestamps.pop(zombie_id, None)
                        cls._zombie_terminated_count += 1  # Track force terminations
                        cleaned += 1
                    else:
                        # Production: log but don't terminate (process exit will clean up)
                        logger.warning(
                            f"Zombie {zombie_id} exceeded {cls._ZOMBIE_TERMINATE_AGE_SECONDS}s "
                            "but terminate disabled in production. "
                            "Will be cleaned on process exit."
                        )
                        zombies_to_keep.append(zombie)
                else:
                    # Keep tracking
                    zombies_to_keep.append(zombie)
                    if age > cls._MAX_ZOMBIE_AGE_SECONDS:
                        logger.warning(
                            f"Zombie {zombie_id} still running after {age:.0f}s "
                            f"(will terminate at {cls._ZOMBIE_TERMINATE_AGE_SECONDS}s)"
                        )

            cls._zombie_threads = zombies_to_keep

        return cleaned

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
        app = QCoreApplication.instance()
        if app is None:
            # No QApplication yet, can't create timer
            return

        # If not on main thread, defer to main thread via queued timer
        if QThread.currentThread() is not app.thread():
            # Use QTimer.singleShot with 0ms to defer to main thread's event loop
            QTimer.singleShot(0, cls._create_zombie_timer_impl)
            return

        # Already on main thread, create directly
        cls._create_zombie_timer_impl()

    @classmethod
    def _create_zombie_timer_impl(cls) -> None:
        """Internal: Create the zombie cleanup timer (must be called on main thread).

        Uses mutex to prevent race conditions when multiple threads attempt
        to start the timer simultaneously.
        """
        import logging

        with QMutexLocker(cls._zombie_mutex):
            if cls._zombie_cleanup_timer is not None:
                # Timer already started (check inside lock to prevent race)
                return

            logger = logging.getLogger("ThreadSafeWorker")

            # Create timer in main thread context
            cls._zombie_cleanup_timer = QTimer()
            cls._zombie_cleanup_timer.setInterval(cls._ZOMBIE_CLEANUP_INTERVAL_MS)

            def cleanup_callback() -> None:
                """Periodic cleanup callback."""
                cleaned = cls.cleanup_old_zombies()
                if cleaned > 0:
                    logger.info(f"Periodic zombie cleanup: removed {cleaned} finished threads")

            _ = cls._zombie_cleanup_timer.timeout.connect(cleanup_callback)
            cls._zombie_cleanup_timer.start()

            logger.info(
                f"Started periodic zombie cleanup timer "
                f"(interval: {cls._ZOMBIE_CLEANUP_INTERVAL_MS}ms)"
            )

    @classmethod
    def stop_zombie_cleanup_timer(cls) -> None:
        """Stop the periodic zombie cleanup timer.

        This should be called during application shutdown to cleanly stop
        the cleanup timer.

        Thread-Safe:
            Safe to call from any thread. Uses mutex to prevent race conditions.
        """
        with QMutexLocker(cls._zombie_mutex):
            if cls._zombie_cleanup_timer is not None:
                cls._zombie_cleanup_timer.stop()
                cls._zombie_cleanup_timer = None

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

        cls.stop_zombie_cleanup_timer()
        with QMutexLocker(cls._zombie_mutex):
            cls._zombie_threads.clear()
            cls._zombie_timestamps.clear()
            # Reset metrics counters for test isolation
            cls._zombie_created_count = 0
            cls._zombie_recovered_count = 0
            cls._zombie_terminated_count = 0
        logging.getLogger(__name__).debug("ThreadSafeWorker reset for testing")
