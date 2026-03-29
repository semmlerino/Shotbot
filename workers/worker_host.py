"""Thread-safe worker reference management.

Provides ``WorkerHost[W]``, a generic helper that encapsulates the
mutex-guarded worker lifecycle pattern shared across the codebase:

- Atomic store/take of a worker reference under a ``QMutex``
- Two-phase cleanup (capture reference under lock, operate outside lock)

Usage example::

    class MyManager():
        def __init__(self) -> None:
            self._host: WorkerHost[MyWorker] = WorkerHost()

        def start(self, shots: list[Shot]) -> None:
            worker = MyWorker(shots)
            worker.finished.connect(self._on_done, Qt.QueuedConnection)
            self._host.store(worker)
            worker.start()

        def stop(self) -> None:
            worker = self._host.take()
            if worker is not None:
                safe_disconnect(worker.some_signal)
                worker.safe_shutdown()

When a caller already owns a ``QMutex`` that must guard both the worker
reference *and* other state (e.g. a ``_loading_in_progress`` flag), pass
that mutex as *shared_mutex*::

    self._lock = QMutex()
    self._host: WorkerHost[MyWorker] = WorkerHost(shared_mutex=self._lock)

    with QMutexLocker(self._lock):
        self._flag = True
        old = self._host.take_unlocked()
        self._host.store_unlocked(new_worker)

"""

from __future__ import annotations

import logging
from typing import Generic, TypeVar

from PySide6.QtCore import QMutex, QMutexLocker


logger = logging.getLogger(__name__)


W = TypeVar("W")


class WorkerHost(Generic[W]):
    """Mutex-guarded container for a single background worker reference.

    Provides atomic store/take primitives so callers can safely capture a
    worker reference under the lock and then perform blocking operations
    (stop, wait, deleteLater) outside the lock — preventing deadlocks.

    By default the host owns a private ``QMutex``.  Pass *shared_mutex* to
    reuse an existing mutex so that the worker reference and other caller-
    owned state can be updated atomically in one lock acquisition.

    Attributes:
        _worker: Current worker instance, or ``None`` when idle.
        _mutex: Mutex protecting ``_worker``.

    """

    def __init__(self, shared_mutex: QMutex | None = None) -> None:
        """Initialise the host.

        Args:
            shared_mutex: If provided, use this mutex instead of creating a
                new one.  The caller is responsible for ensuring the mutex
                outlives the host.

        """
        self._worker: W | None = None
        self._mutex: QMutex = shared_mutex if shared_mutex is not None else QMutex()

    # ------------------------------------------------------------------
    # Locked primitives (acquire the mutex internally)
    # ------------------------------------------------------------------

    def store(self, worker: W) -> None:
        """Store *worker* as the active worker reference.

        Args:
            worker: The worker to store.  Must not be ``None``.

        """
        with QMutexLocker(self._mutex):
            self._worker = worker

    def take(self) -> W | None:
        """Atomically capture and clear the worker reference.

        Returns the current worker (or ``None``) while simultaneously
        setting the internal reference to ``None``.  After this call the
        host is idle.  Callers perform stop/cleanup on the returned value
        *outside* the lock.

        Returns:
            The previous worker, or ``None`` if there was none.

        """
        with QMutexLocker(self._mutex):
            worker = self._worker
            self._worker = None
            return worker

    def peek(self) -> W | None:
        """Return the current worker reference without clearing it.

        Returns:
            The current worker, or ``None`` if there is none.

        """
        with QMutexLocker(self._mutex):
            return self._worker

    # ------------------------------------------------------------------
    # Unlocked primitives (caller already holds the mutex)
    # ------------------------------------------------------------------

    def store_unlocked(self, worker: W) -> None:
        """Store *worker* without acquiring the mutex.

        The caller **must** already hold ``_mutex`` (or the shared mutex
        passed at construction time).

        Args:
            worker: The worker to store.

        """
        self._worker = worker

    def take_unlocked(self) -> W | None:
        """Capture and clear the reference without acquiring the mutex.

        The caller **must** already hold ``_mutex`` (or the shared mutex
        passed at construction time).

        Returns:
            The previous worker, or ``None`` if there was none.

        """
        worker = self._worker
        self._worker = None
        return worker



    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def has_worker(self) -> bool:
        """``True`` if a worker reference is currently stored."""
        with QMutexLocker(self._mutex):
            return self._worker is not None
