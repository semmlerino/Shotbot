"""Worker lifecycle manager for 3DE scene discovery.

Encapsulates thread-safe creation, signal wiring, stopping, and cleanup of
ThreeDESceneWorker instances. ThreeDEController owns an instance of this
class and delegates all worker management through it.
"""

from __future__ import annotations

import logging

# Standard library imports
from collections.abc import Callable
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import (
    Qt,
)

# Runtime imports
from threede import ThreeDESceneWorker
from timeout_config import TimeoutConfig
from utils import safe_disconnect
from workers.worker_host import WorkerHost


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from type_definitions import Shot, ThreeDEScene


@final
class ThreeDEWorkerManager:
    """Manages the lifecycle of a ThreeDESceneWorker.

    Owns the worker instance and the mutex that protects it.  The controller
    passes callbacks for each worker signal; this class wires them up when a
    new worker is started and tears them down on stop/cleanup.

    Attributes:
        _host: Thread-safe container for the current worker reference.

    """

    def __init__(
        self,
        on_discovery_started: Callable[[], None],
        on_discovery_progress: Callable[[int, int, float, str, str], None],
        on_discovery_finished: Callable[[list[ThreeDEScene]], None],
        on_discovery_error: Callable[[str], None],
        on_scan_progress: Callable[[int, int, str], None],
    ) -> None:
        """Initialize the worker manager with signal-handler callbacks.

        Args:
            on_discovery_started: Called when the worker emits
                ``worker_discovery_started``.
            on_discovery_progress: Called when the worker emits ``progress``.
            on_discovery_finished: Called when the worker emits
                ``discovery_finished``.
            on_discovery_error: Called when the worker emits ``error``.
            on_scan_progress: Called when the worker emits ``scan_progress``.

        """
        super().__init__()

        self._on_discovery_started: Callable[[], None] = on_discovery_started
        self._on_discovery_progress: Callable[[int, int, float, str, str], None] = (
            on_discovery_progress
        )
        self._on_discovery_finished: Callable[[list[ThreeDEScene]], None] = (
            on_discovery_finished
        )
        self._on_discovery_error: Callable[[str], None] = on_discovery_error
        self._on_scan_progress: Callable[[int, int, str], None] = on_scan_progress

        self._host: WorkerHost[ThreeDESceneWorker] = WorkerHost()

    # ============================================================================
    # Public Interface
    # ============================================================================

    def start_worker(self, shots: list[Shot]) -> ThreeDESceneWorker:
        """Create, wire, and start a new worker.

        The caller is responsible for ensuring any previous worker has been
        stopped before calling this method.  The new worker reference is stored
        internally and the worker is started before returning.

        Args:
            shots: Active shots used to determine which shows to scan.

        Returns:
            The newly started worker instance.

        """
        worker = ThreeDESceneWorker(
            shots=shots,
            batch_size=None,
        )

        self._host.store(worker)
        self._setup_worker_signals(worker)
        worker.start()
        return worker

    def stop_worker(self) -> None:
        """Stop the current worker if one is running.

        Reads the worker reference under mutex, then stops it outside the
        mutex to prevent deadlocks.
        """
        worker_to_stop = self._host.peek()

        if worker_to_stop is not None and not worker_to_stop.isFinished():
            self._stop_existing_worker(worker_to_stop)

    def cleanup(self) -> None:
        """Stop the current worker and release all resources.

        Intended for application shutdown.  Disconnects signals after the
        worker has stopped, then clears the internal reference.
        """
        worker_to_cleanup = self._host.take()

        if worker_to_cleanup is None:
            return

        # Disconnect signals before shutdown to prevent stale deliveries
        self._disconnect_worker_signals(worker_to_cleanup)

        worker_to_cleanup.safe_shutdown(TimeoutConfig.WORKER_COORDINATION_STOP_MS)

    @property
    def has_active_worker(self) -> bool:
        """Check if there is a currently running worker thread."""
        worker = self._host.peek()
        return worker is not None and not worker.isFinished()

    @property
    def current_worker(self) -> ThreeDESceneWorker | None:
        """Return the current worker reference under mutex protection."""
        return self._host.peek()

    # ============================================================================
    # Private Helpers
    # ============================================================================

    def _stop_existing_worker(self, worker_to_stop: ThreeDESceneWorker) -> None:
        """Stop a running worker thread and release its resources.

        Requests a graceful stop, waits up to the configured timeout, falls
        back to safe termination if the worker does not respond in time, then
        schedules the worker for deletion (unless it is a zombie thread) and
        clears the internal worker reference under mutex protection.

        Args:
            worker_to_stop: The worker thread to stop.  Must not be ``None``.

        """
        # Disconnect signals before shutdown to prevent stale deliveries
        self._disconnect_worker_signals(worker_to_stop)

        worker_to_stop.safe_shutdown(TimeoutConfig.WORKER_COORDINATION_STOP_MS)

        # Clear reference after worker is stopped; only clear if it's still the same worker
        if self._host.peek() is worker_to_stop:
            _ = self._host.take()

    def _setup_worker_signals(self, worker: ThreeDESceneWorker) -> None:
        """Connect all worker signals to the stored callbacks.

        Args:
            worker: The worker thread to connect signals from.

        """
        _ = worker.safe_connect(
            worker.worker_discovery_started,
            self._on_discovery_started,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.progress,
            self._on_discovery_progress,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.scan_progress,
            self._on_scan_progress,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.discovery_finished,
            self._on_discovery_finished,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.error,
            self._on_discovery_error,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        logger.debug("Connected all worker signals to controller")

    def _disconnect_worker_signals(self, worker: ThreeDESceneWorker) -> None:
        """Safely disconnect worker signals.

        Args:
            worker: The worker thread to disconnect signals from.

        """
        safe_disconnect(
            worker.worker_discovery_started,
            worker.progress,
            worker.scan_progress,
            worker.discovery_finished,
            worker.error,
        )
        logger.debug("Disconnected worker signals")
