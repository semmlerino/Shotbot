"""Thread-safe base class for Qt workers with proper lifecycle management."""

import logging
import weakref
from typing import Any, List, Tuple

from PySide6.QtCore import QMutex, QMutexLocker, Qt, QThread, Signal

logger = logging.getLogger(__name__)


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

    # Lifecycle signals
    worker_started = Signal()
    worker_stopping = Signal()
    worker_stopped = Signal()
    worker_error = Signal(str)

    # Valid state transitions
    VALID_TRANSITIONS = {
        "CREATED": ["STARTING"],
        "STARTING": ["RUNNING", "STOPPED"],  # Can stop before fully started
        "RUNNING": ["STOPPING"],
        "STOPPING": ["STOPPED"],
        "STOPPED": ["DELETED"],
    }

    def __init__(self, parent=None):
        """Initialize thread-safe worker.

        Args:
            parent: Optional parent QObject for proper Qt cleanup
        """
        super().__init__(parent)
        self._state_mutex = QMutex()
        self._state = "CREATED"
        self._stop_requested = False
        self._connections: List[Tuple[weakref.ref, weakref.ref]] = []
        self._zombie = False  # Track abandoned threads

        # Set up cleanup on thread finished
        self.finished.connect(self._on_finished)

    def get_state(self) -> str:
        """Thread-safe state getter.

        Returns:
            Current state string
        """
        with QMutexLocker(self._state_mutex):
            return self._state

    def set_state(self, new_state: str) -> bool:
        """Thread-safe state setter with validation.

        Args:
            new_state: State to transition to

        Returns:
            True if transition was valid and executed, False otherwise
        """
        with QMutexLocker(self._state_mutex):
            current = self._state
            valid_next_states = self.VALID_TRANSITIONS.get(current, [])

            if new_state in valid_next_states:
                logger.debug(f"Worker {id(self)}: {current} -> {new_state}")
                self._state = new_state
                return True
            else:
                logger.warning(
                    f"Worker {id(self)}: Invalid transition {current} -> {new_state}"
                )
                return False

    def request_stop(self) -> bool:
        """Thread-safe stop request.

        Returns:
            True if stop was requested successfully, False if already stopping/stopped
        """
        with QMutexLocker(self._state_mutex):
            current = self._state

            if current in ["STOPPED", "DELETED", "STOPPING"]:
                logger.debug(f"Worker {id(self)}: Already stopping/stopped ({current})")
                return False

            # Can stop from CREATED, STARTING, or RUNNING states
            if current in ["CREATED", "STARTING"]:
                # Direct transition to STOPPED if not yet running
                self._state = "STOPPED"
                self._stop_requested = True
                self.worker_stopped.emit()
                return True
            elif current == "RUNNING":
                # Normal stop sequence
                self._state = "STOPPING"
                self._stop_requested = True
                self.worker_stopping.emit()
                return True

            return False

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
        signal: Any,  # SignalInstance at runtime, Signal in type checking
        slot: Any,
        connection_type: Qt.ConnectionType = Qt.ConnectionType.QueuedConnection,
    ) -> None:
        """Track signal connections for safe cleanup.

        Args:
            signal: Signal to connect
            slot: Slot to connect to
            connection_type: Qt connection type (default: QueuedConnection for thread safety)
        """
        # Store direct references - Qt signals don't support weak references
        # The connections will be cleaned up in disconnect_all()
        connection = (signal, slot)
        self._connections.append(connection)
        signal.connect(slot, connection_type)
        logger.debug(f"Worker {id(self)}: Connected signal with {connection_type}")

    def disconnect_all(self) -> None:
        """Safely disconnect all tracked signals.

        This is safe to call even if signals are being emitted.
        """
        logger.debug(
            f"Worker {id(self)}: Disconnecting {len(self._connections)} signals"
        )

        for signal, slot in self._connections:
            # Direct references now - no need to dereference
            try:
                signal.disconnect(slot)
                logger.debug(f"Worker {id(self)}: Disconnected signal")
            except (RuntimeError, TypeError) as e:
                # Already disconnected or object deleted - this is fine
                logger.debug(f"Worker {id(self)}: Signal already disconnected: {e}")

        self._connections.clear()

    def run(self) -> None:
        """Main thread execution with proper state management.

        Override do_work() in subclasses to implement actual functionality.
        """
        # Transition to STARTING
        if not self.set_state("STARTING"):
            logger.error(f"Worker {id(self)}: Failed to start - invalid state")
            return

        # Check if stop was requested before we even started
        if self._stop_requested:
            self.set_state("STOPPED")
            self.worker_stopped.emit()
            return

        # Emit started signal
        self.worker_started.emit()

        # Transition to RUNNING
        if not self.set_state("RUNNING"):
            logger.error(f"Worker {id(self)}: Failed to transition to RUNNING")
            self.set_state("STOPPED")
            self.worker_stopped.emit()
            return

        # Execute actual work
        try:
            # Check if thread should exit before starting work
            if self.thread() and self.thread().isInterruptionRequested():
                logger.debug(f"Worker {id(self)}: Interruption requested before work")
                return

            self.do_work()
        except Exception as e:
            logger.exception(f"Worker {id(self)}: Exception in do_work")
            self.worker_error.emit(str(e))
        finally:
            # Ensure we transition to STOPPED
            with QMutexLocker(self._state_mutex):
                if self._state != "STOPPED":
                    self._state = "STOPPED"

            self.worker_stopped.emit()

    def do_work(self) -> None:
        """Override this method with actual work implementation.

        This method should:
        - Periodically check is_stop_requested()
        - Exit gracefully when stop is requested
        - Handle its own exceptions
        """
        raise NotImplementedError("Subclasses must implement do_work()")

    def _on_finished(self) -> None:
        """Handle thread finished signal for cleanup."""
        # Disconnect all signals when thread finishes
        self.disconnect_all()

        # Transition to final state
        self.set_state("DELETED")

    def safe_wait(self, timeout_ms: int = 5000) -> bool:
        """Safely wait for worker to finish with timeout.

        Args:
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            True if worker finished, False if timeout
        """
        if self.get_state() in ["STOPPED", "DELETED"]:
            return True

        return self.wait(timeout_ms)

    def safe_terminate(self) -> None:
        """Safely terminate the worker thread.

        This should only be used as a last resort after request_stop() and wait() fail.
        This version avoids using terminate() which can cause crashes.
        """
        state = self.get_state()

        if state in ["STOPPED", "DELETED"]:
            logger.debug(f"Worker {id(self)}: Already stopped, no termination needed")
            return

        logger.warning(f"Worker {id(self)}: Requesting stop from state {state}")

        # Disconnect signals before any termination attempt
        self.disconnect_all()

        # Force state transition
        with QMutexLocker(self._state_mutex):
            self._state = "STOPPED"
            self._stop_requested = True

        # Try graceful shutdown first
        if self.isRunning():
            # Request interruption - this is the Qt way to interrupt blocking operations
            self.requestInterruption()

            # Request event loop to quit
            self.quit()

            # Wait for graceful shutdown with shorter initial timeout
            if not self.wait(2000):  # 2 second initial timeout
                logger.warning(
                    f"Worker {id(self)}: Still running after 2s, waiting longer..."
                )

                # Try one more time with longer timeout
                if not self.wait(3000):  # 3 more seconds
                    logger.error(
                        f"Worker {id(self)}: Failed to stop gracefully after 5s total. "
                        "Thread will be abandoned (NOT terminated) to prevent crashes."
                    )
                    # DO NOT call terminate() - it's unsafe!
                    # Instead, mark as zombie and let Python GC eventually clean up
                    self._zombie = True
                else:
                    logger.info(f"Worker {id(self)}: Stopped after extended wait")
            else:
                logger.info(f"Worker {id(self)}: Stopped gracefully")
