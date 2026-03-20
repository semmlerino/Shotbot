"""Zombie thread registry: module-level functions for ThreadSafeWorker zombie tracking.

All state lives on ThreadSafeWorker ClassVars (kept there for backward compatibility
with tests and callers that access them directly). These functions are the single
authoritative location for zombie-lifecycle logic.
"""

from __future__ import annotations

# Standard library imports
import logging
import os
import time
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import (
    QCoreApplication,
    QMutexLocker,
    QThread,
    QTimer,
)


if TYPE_CHECKING:
    from workers.thread_safe_worker import ThreadSafeWorker


def get_zombie_metrics() -> dict[str, int]:
    """Return zombie metrics for monitoring timeout fix effectiveness."""
    from workers.thread_safe_worker import ThreadSafeWorker

    # fmt: off
    with QMutexLocker(ThreadSafeWorker._zombie_mutex):  # type: ignore[reportPrivateUsage]
        return {
            "created":    ThreadSafeWorker._zombie_created_count,    # type: ignore[reportPrivateUsage]
            "recovered":  ThreadSafeWorker._zombie_recovered_count,  # type: ignore[reportPrivateUsage]
            "terminated": ThreadSafeWorker._zombie_terminated_count, # type: ignore[reportPrivateUsage]
            "current":    len(ThreadSafeWorker._zombie_threads),     # type: ignore[reportPrivateUsage]
        }
    # fmt: on


def safe_terminate(worker: ThreadSafeWorker) -> None:
    """Safely terminate the worker thread (last-resort path).

    This should only be used after request_stop() and wait() fail.
    Avoids terminate() which can cause crashes.
    """
    from workers.thread_safe_worker import ThreadSafeWorker, WorkerState

    state = worker.get_state()

    if state in [WorkerState.STOPPED, WorkerState.DELETED]:
        worker.logger.debug(
            f"Worker {id(worker)}: Already stopped, no termination needed"
        )
        return

    worker.logger.warning(
        f"Worker {id(worker)}: Requesting stop from state {state.name}"
    )

    # Disconnect signals before any termination attempt
    worker.disconnect_all()  # type: ignore[reportAny, no-untyped-call]

    # Set stop flags but NOT state yet - state only changes after confirmed stop
    with QMutexLocker(worker._state_mutex):  # type: ignore[reportPrivateUsage]
        worker._stop_requested = True  # type: ignore[reportPrivateUsage]
        worker._force_stop = True  # type: ignore[reportPrivateUsage]

    # Try graceful shutdown first
    if worker.isRunning():
        # Request interruption - this is the Qt way to interrupt blocking operations
        worker.requestInterruption()

        # Request event loop to quit
        worker.quit()

        # Wait for graceful shutdown with shorter initial timeout
        from timeout_config import TimeoutConfig

        if not worker.wait(TimeoutConfig.WORKER_GRACEFUL_STOP_MS):  # Initial timeout
            worker.logger.warning(
                f"Worker {id(worker)}: Still running after {TimeoutConfig.WORKER_GRACEFUL_STOP_MS}ms, waiting longer...",
            )

            # Try one more time with longer timeout
            if not worker.wait(
                TimeoutConfig.WORKER_TERMINATE_MS * 3,
            ):  # Extended timeout
                # CAPTURE DIAGNOSTICS BEFORE ABANDONMENT
                # Import here to avoid circular imports
                from workers.thread_diagnostics import ThreadDiagnostics

                start_time = ThreadSafeWorker._thread_start_times.get(id(worker))  # type: ignore[reportPrivateUsage]
                report = ThreadDiagnostics.capture_thread_state(worker, start_time)
                ThreadDiagnostics.log_abandonment(
                    worker,
                    f"Failed to stop after {TimeoutConfig.WORKER_GRACEFUL_STOP_MS + TimeoutConfig.WORKER_TERMINATE_MS * 3}ms",
                    report,
                )

                worker.logger.error(
                    f"Worker {id(worker)}: Failed to stop gracefully after 5s total. "
                    "Thread will be abandoned (NOT terminated) to prevent crashes."
                )
                # DO NOT call terminate() - it's unsafe!
                # Instead, mark as zombie and add to class collection to prevent GC
                # NOTE: State stays at previous value - thread is still running!
                with QMutexLocker(worker._state_mutex):  # type: ignore[reportPrivateUsage]
                    worker._zombie = True  # type: ignore[reportPrivateUsage]

                # Add to class-level collection to prevent garbage collection
                # This prevents "QThread: Destroyed while thread is still running" crash
                # FIXED: Don't call cleanup_old_zombies() from within mutex (DEADLOCK!)
                # QMutex is NOT recursive - cleanup_old_zombies() tries to acquire
                # the same mutex again → deadlock. Let periodic cleanup handle it.
                with QMutexLocker(ThreadSafeWorker._zombie_mutex):  # type: ignore[reportPrivateUsage]
                    ThreadSafeWorker._zombie_threads.append(worker)  # type: ignore[reportPrivateUsage]
                    ThreadSafeWorker._zombie_timestamps[id(worker)] = time.time()  # type: ignore[reportPrivateUsage]
                    ThreadSafeWorker._zombie_created_count += 1  # type: ignore[reportPrivateUsage]
                    zombie_count = len(ThreadSafeWorker._zombie_threads)  # type: ignore[reportPrivateUsage]

                worker.logger.warning(
                    f"Worker {id(worker)}: Added to zombie collection "
                    f"({zombie_count} total zombies). "
                    "Periodic cleanup will attempt recovery."
                )
            else:
                # Thread actually stopped - NOW set state to STOPPED
                with QMutexLocker(worker._state_mutex):  # type: ignore[reportPrivateUsage]
                    worker._state = WorkerState.STOPPED  # type: ignore[reportPrivateUsage]
                worker.logger.info(f"Worker {id(worker)}: Stopped after extended wait")
        else:
            # Thread actually stopped - NOW set state to STOPPED
            with QMutexLocker(worker._state_mutex):  # type: ignore[reportPrivateUsage]
                worker._state = WorkerState.STOPPED  # type: ignore[reportPrivateUsage]
            worker.logger.info(f"Worker {id(worker)}: Stopped gracefully")
    else:
        # Thread was already stopped - set state to STOPPED
        with QMutexLocker(worker._state_mutex):  # type: ignore[reportPrivateUsage]
            worker._state = WorkerState.STOPPED  # type: ignore[reportPrivateUsage]


def cleanup_old_zombies() -> int:
    """Attempt to clean up old zombie threads with escalating cleanup policy.

    Cleanup stages:
    1. Threads that finished naturally are removed immediately
    2. After _MAX_ZOMBIE_AGE_SECONDS (60s), logs warning
    3. After _ZOMBIE_TERMINATE_AGE_SECONDS (300s), force terminates

    Returns:
        Number of zombies cleaned up

    """
    from workers.thread_safe_worker import ThreadSafeWorker

    logger = logging.getLogger(__name__)
    cleaned = 0
    current_time = time.time()

    # CRITICAL: Protect all access to shared zombie collections
    # NOTE: This method should NOT be called from within _zombie_mutex critical section
    # as QMutex is NOT recursive and would cause deadlock.
    with QMutexLocker(ThreadSafeWorker._zombie_mutex):  # type: ignore[reportPrivateUsage]
        zombies_to_keep: list[ThreadSafeWorker] = []

        for zombie in ThreadSafeWorker._zombie_threads:  # type: ignore[reportPrivateUsage]
            zombie_id = id(zombie)
            age = current_time - ThreadSafeWorker._zombie_timestamps.get(zombie_id, current_time)  # type: ignore[reportPrivateUsage]

            if not zombie.isRunning():
                # Thread finished naturally, safe to remove
                _ = ThreadSafeWorker._zombie_timestamps.pop(zombie_id, None)  # type: ignore[reportPrivateUsage]
                ThreadSafeWorker._zombie_recovered_count += 1  # type: ignore[reportPrivateUsage]
                cleaned += 1
                logger.info(f"Zombie {zombie_id} finished naturally after {age:.0f}s")
            elif age > ThreadSafeWorker._ZOMBIE_TERMINATE_AGE_SECONDS:  # type: ignore[reportPrivateUsage]
                # CAPTURE DIAGNOSTICS BEFORE ANY TERMINATE
                from workers.thread_diagnostics import ThreadDiagnostics

                start_time = ThreadSafeWorker._thread_start_times.get(zombie_id)  # type: ignore[reportPrivateUsage]
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
                    _ = ThreadSafeWorker._zombie_timestamps.pop(zombie_id, None)  # type: ignore[reportPrivateUsage]
                    ThreadSafeWorker._zombie_terminated_count += 1  # type: ignore[reportPrivateUsage]
                    cleaned += 1
                else:
                    # Production: log but don't terminate (process exit will clean up)
                    logger.warning(
                        f"Zombie {zombie_id} exceeded {ThreadSafeWorker._ZOMBIE_TERMINATE_AGE_SECONDS}s "  # type: ignore[reportPrivateUsage]
                        "but terminate disabled in production. "
                        "Will be cleaned on process exit."
                    )
                    zombies_to_keep.append(zombie)
            else:
                # Keep tracking
                zombies_to_keep.append(zombie)
                if age > ThreadSafeWorker._MAX_ZOMBIE_AGE_SECONDS:  # type: ignore[reportPrivateUsage]
                    logger.warning(
                        f"Zombie {zombie_id} still running after {age:.0f}s "
                        f"(will terminate at {ThreadSafeWorker._ZOMBIE_TERMINATE_AGE_SECONDS}s)"  # type: ignore[reportPrivateUsage]
                    )

        ThreadSafeWorker._zombie_threads = zombies_to_keep  # type: ignore[reportPrivateUsage]

    return cleaned


def start_zombie_cleanup_timer() -> None:
    """Start the periodic zombie cleanup timer.

    Should be called once during application initialization. The timer runs
    in the main thread and calls cleanup_old_zombies() every 60 seconds.

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
        QTimer.singleShot(0, lambda: create_zombie_timer_impl())
        return

    # Already on main thread, create directly
    create_zombie_timer_impl()


def create_zombie_timer_impl() -> None:
    """Internal: Create the zombie cleanup timer (must be called on main thread).

    Uses mutex to prevent race conditions when multiple threads attempt
    to start the timer simultaneously.
    """
    from workers.thread_safe_worker import ThreadSafeWorker

    with QMutexLocker(ThreadSafeWorker._zombie_mutex):  # type: ignore[reportPrivateUsage]
        if ThreadSafeWorker._zombie_cleanup_timer is not None:  # type: ignore[reportPrivateUsage]
            # Timer already started (check inside lock to prevent race)
            return

        logger = logging.getLogger("ThreadSafeWorker")

        # Create timer in main thread context
        ThreadSafeWorker._zombie_cleanup_timer = QTimer()  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_cleanup_timer.setInterval(ThreadSafeWorker._ZOMBIE_CLEANUP_INTERVAL_MS)  # type: ignore[reportPrivateUsage]

        def cleanup_callback() -> None:
            """Periodic cleanup callback."""
            cleaned = cleanup_old_zombies()
            if cleaned > 0:
                logger.info(f"Periodic zombie cleanup: removed {cleaned} finished threads")

        _ = ThreadSafeWorker._zombie_cleanup_timer.timeout.connect(cleanup_callback)  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_cleanup_timer.start()  # type: ignore[reportPrivateUsage]

        logger.info(
            f"Started periodic zombie cleanup timer "
            f"(interval: {ThreadSafeWorker._ZOMBIE_CLEANUP_INTERVAL_MS}ms)"  # type: ignore[reportPrivateUsage]
        )


def stop_zombie_cleanup_timer() -> None:
    """Stop the periodic zombie cleanup timer.

    Thread-Safe:
        Safe to call from any thread. Uses mutex to prevent race conditions.
    """
    from workers.thread_safe_worker import ThreadSafeWorker

    with QMutexLocker(ThreadSafeWorker._zombie_mutex):  # type: ignore[reportPrivateUsage]
        if ThreadSafeWorker._zombie_cleanup_timer is not None:  # type: ignore[reportPrivateUsage]
            ThreadSafeWorker._zombie_cleanup_timer.stop()  # type: ignore[reportPrivateUsage]
            ThreadSafeWorker._zombie_cleanup_timer.deleteLater()  # type: ignore[reportPrivateUsage]
            ThreadSafeWorker._zombie_cleanup_timer = None  # type: ignore[reportPrivateUsage]


def reset_for_testing() -> None:
    """Reset zombie tracking state for test isolation.

    Stops the cleanup timer and clears all zombie tracking data.
    Should only be called from ThreadSafeWorker.reset().
    """
    from workers.thread_safe_worker import ThreadSafeWorker

    stop_zombie_cleanup_timer()
    with QMutexLocker(ThreadSafeWorker._zombie_mutex):  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_threads.clear()  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_timestamps.clear()  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_created_count = 0  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_recovered_count = 0  # type: ignore[reportPrivateUsage]
        ThreadSafeWorker._zombie_terminated_count = 0  # type: ignore[reportPrivateUsage]
