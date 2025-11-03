"""
QRunnable resource tracking system to prevent memory leaks.

This module provides a singleton tracker for QRunnable instances to ensure
proper cleanup and prevent memory leaks from untracked thread pool tasks.
"""
# Standard library imports
import logging
import threading
import weakref
from collections.abc import Mapping
from typing import override

# Third-party imports
from PySide6.QtCore import QRunnable, QThreadPool


logger = logging.getLogger(__name__)


class QRunnableTracker:
    """
    Singleton tracker for QRunnable instances.

    Uses weak references to track running QRunnables without preventing
    garbage collection. Provides methods for registration, monitoring,
    and cleanup of thread pool tasks.
    """

    _instance: "QRunnableTracker | None" = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> "QRunnableTracker":
        """Thread-safe singleton implementation."""
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        """Initialize the tracker (only once)."""
        super().__init__()
        with self._lock:
            if self._initialized:
                return
            self._initialized = True

        self._active_runnables: weakref.WeakSet[QRunnable] = weakref.WeakSet()
        self._runnable_metadata: weakref.WeakKeyDictionary[
            QRunnable, dict[str, object]
        ] = weakref.WeakKeyDictionary()
        self._stats = {
            "total_registered": 0,
            "total_completed": 0,
            "peak_concurrent": 0,
        }
        logger.debug("QRunnableTracker initialized")

    def register(
        self, runnable: QRunnable, metadata: Mapping[str, object] | None = None
    ) -> None:
        """
        Register a QRunnable for tracking.

        Args:
            runnable: The QRunnable instance to track
            metadata: Optional metadata about the runnable (e.g., type, source, timestamp)
        """
        self._active_runnables.add(runnable)
        if metadata:
            self._runnable_metadata[runnable] = dict(metadata)

        self._stats["total_registered"] += 1
        current_active = len(self._active_runnables)
        self._stats["peak_concurrent"] = max(self._stats["peak_concurrent"], current_active)

        logger.debug(

                f"Registered {runnable.__class__.__name__} "
                f"(active: {current_active}, total: {self._stats['total_registered']})"

        )

    def unregister(self, runnable: QRunnable) -> None:
        """
        Unregister a completed QRunnable.

        Args:
            runnable: The QRunnable instance to unregister
        """
        try:
            self._active_runnables.discard(runnable)
            if runnable in self._runnable_metadata:
                del self._runnable_metadata[runnable]
            self._stats["total_completed"] += 1

            logger.debug(

                    f"Unregistered {runnable.__class__.__name__} "
                    f"(active: {len(self._active_runnables)})"

            )
        except Exception as e:
            logger.warning(f"Error unregistering runnable: {e}")

    def get_active_count(self) -> int:
        """Get the number of currently active runnables."""
        return len(self._active_runnables)

    def get_active_runnables(self) -> list[QRunnable]:
        """Get a list of currently active runnables."""
        return list(self._active_runnables)

    def get_stats(self) -> dict[str, int]:
        """Get tracking statistics."""
        return {
            **self._stats,
            "current_active": len(self._active_runnables),
        }

    def wait_for_all(self, timeout_ms: int = 30000) -> bool:
        """
        Wait for all active runnables to complete.

        Args:
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            True if all completed, False if timeout
        """
        # Standard library imports
        import time

        start_time = time.time()
        timeout_sec = timeout_ms / 1000.0

        while self._active_runnables:
            if time.time() - start_time > timeout_sec:
                active_count = len(self._active_runnables)
                logger.warning(
                    f"Timeout waiting for {active_count} runnables to complete"
                )
                return False
            time.sleep(0.1)

        return True

    def cleanup_all(self) -> None:
        """
        Clean up all tracked resources.

        This should be called during application shutdown to ensure
        proper cleanup of any remaining runnables.
        """
        active_count = len(self._active_runnables)
        if active_count > 0:
            logger.info(f"Cleaning up {active_count} active runnables")

            # Wait for thread pool to finish
            _ = QThreadPool.globalInstance().waitForDone(5000)

            # Clear tracking data
            self._active_runnables.clear()
            self._runnable_metadata.clear()

        logger.info(

                f"QRunnableTracker cleanup complete - "
                f"Total: {self._stats['total_registered']}, "
                f"Completed: {self._stats['total_completed']}, "
                f"Peak concurrent: {self._stats['peak_concurrent']}"

        )

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (mainly for testing)."""
        with cls._lock:
            if cls._instance:
                cls._instance.cleanup_all()
            cls._instance = None


class TrackedQRunnable(QRunnable):
    """
    Base class for tracked QRunnables.

    Automatically registers/unregisters with the tracker.
    Subclasses should override the run() method.
    """

    def __init__(self, auto_delete: bool = True) -> None:
        """
        Initialize the tracked runnable.

        Args:
            auto_delete: Whether to auto-delete after running
        """
        super().__init__()
        self.setAutoDelete(auto_delete)
        self._tracker = QRunnableTracker()
        self._metadata = {
            "type": self.__class__.__name__,
            "auto_delete": auto_delete,
        }

    @override
    def run(self) -> None:
        """
        Execute the runnable with automatic tracking.

        Subclasses should override _do_work() instead of this method.
        """
        try:
            self._tracker.register(self, self._metadata)
            self._do_work()
        finally:
            self._tracker.unregister(self)

    def _do_work(self) -> None:
        """
        Override this method to implement the actual work.

        This method is called by run() with automatic tracking.
        """
        raise NotImplementedError("Subclasses must implement _do_work()")


# Global singleton instance for convenience
_tracker_instance = QRunnableTracker()


def get_tracker() -> QRunnableTracker:
    """Get the global QRunnableTracker instance."""
    return _tracker_instance


def register_runnable(
    runnable: QRunnable, metadata: Mapping[str, object] | None = None
) -> None:
    """Convenience function to register a runnable with the global tracker."""
    _tracker_instance.register(runnable, metadata)


def unregister_runnable(runnable: QRunnable) -> None:
    """Convenience function to unregister a runnable from the global tracker."""
    _tracker_instance.unregister(runnable)


def cleanup_all_runnables() -> None:
    """Convenience function to cleanup all runnables via the global tracker."""
    _tracker_instance.cleanup_all()
