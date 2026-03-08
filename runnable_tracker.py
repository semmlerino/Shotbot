"""QRunnable resource tracking system to prevent memory leaks.

This module provides a singleton tracker for QRunnable instances to ensure
proper cleanup and prevent memory leaks from untracked thread pool tasks.
"""
# Standard library imports
import contextlib
import logging
import subprocess
import sys
import threading
import weakref
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, final

# Third-party imports
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from singleton_mixin import SingletonMixin
from typing_compat import override


logger = logging.getLogger(__name__)


@final
class QRunnableTracker(SingletonMixin):
    """Singleton tracker for QRunnable instances.

    Uses weak references to track running QRunnables without preventing
    garbage collection. Provides methods for registration, monitoring,
    and cleanup of thread pool tasks.
    """

    _cleanup_order: ClassVar[int] = 20
    _singleton_description: ClassVar[str] = "Tracks QRunnable lifecycle for cleanup"

    def __init__(self) -> None:
        """Initialize the tracker (only once)."""
        with type(self)._lock:
            if self._is_initialized():
                return

            super().__init__()

            # Thread safety lock for all mutable state (use RLock for consistency with SingletonMixin)
            self._data_lock = threading.Lock()

            self._active_runnables: weakref.WeakSet[QRunnable] = weakref.WeakSet()
            self._runnable_metadata: weakref.WeakKeyDictionary[
                QRunnable, dict[str, object]
            ] = weakref.WeakKeyDictionary()
            self._stats = {
                "total_registered": 0,
                "total_completed": 0,
                "peak_concurrent": 0,
            }

            self._mark_initialized()
            logger.debug("QRunnableTracker initialized")

    def register(
        self, runnable: QRunnable, metadata: Mapping[str, object] | None = None
    ) -> None:
        """Register a QRunnable for tracking.

        Thread-safe: Protected by internal lock.

        Args:
            runnable: The QRunnable instance to track
            metadata: Optional metadata about the runnable (e.g., type, source, timestamp)

        """
        with self._data_lock:
            self._active_runnables.add(runnable)
            if metadata:
                self._runnable_metadata[runnable] = dict(metadata)

            self._stats["total_registered"] += 1
            current_active = len(self._active_runnables)
            self._stats["peak_concurrent"] = max(
                self._stats["peak_concurrent"], current_active
            )
            total_registered = self._stats["total_registered"]

        logger.debug(
            f"Registered {runnable.__class__.__name__} "
            f"(active: {current_active}, total: {total_registered})"
        )

    def unregister(self, runnable: QRunnable) -> None:
        """Unregister a completed QRunnable.

        Thread-safe: Protected by internal lock.

        Args:
            runnable: The QRunnable instance to unregister

        """
        try:
            with self._data_lock:
                self._active_runnables.discard(runnable)
                if runnable in self._runnable_metadata:
                    del self._runnable_metadata[runnable]
                self._stats["total_completed"] += 1
                active_count = len(self._active_runnables)

            logger.debug(
                f"Unregistered {runnable.__class__.__name__} "
                f"(active: {active_count})"
            )
        except Exception:  # noqa: BLE001
            logger.warning("Error unregistering runnable", exc_info=True)

    def get_active_count(self) -> int:
        """Get the number of currently active runnables. Thread-safe."""
        with self._data_lock:
            return len(self._active_runnables)

    def get_active_runnables(self) -> list[QRunnable]:
        """Get a list of currently active runnables. Thread-safe."""
        with self._data_lock:
            return list(self._active_runnables)

    def get_stats(self) -> dict[str, int]:
        """Get tracking statistics. Thread-safe."""
        with self._data_lock:
            return {
                **self._stats,
                "current_active": len(self._active_runnables),
            }

    def wait_for_all(self, timeout_ms: int = 30000) -> bool:
        """Wait for all active runnables to complete.

        Thread-safe: Uses lock only for checking active count, not during sleep.

        Args:
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            True if all completed, False if timeout

        """
        # Standard library imports
        import time

        start_time = time.time()
        timeout_sec = timeout_ms / 1000.0

        while True:
            # Check active count under lock
            with self._data_lock:
                active_count = len(self._active_runnables)
                if active_count == 0:
                    return True

            # Check timeout outside lock
            if time.time() - start_time > timeout_sec:
                logger.warning(
                    f"Timeout waiting for {active_count} runnables to complete"
                )
                return False

            # Sleep outside lock to allow other threads to make progress
            time.sleep(0.1)

    def cleanup_all(self) -> None:
        """Clean up all tracked resources.

        Thread-safe: Uses lock for state access, waits for thread pool outside lock.

        This should be called during application shutdown to ensure
        proper cleanup of any remaining runnables.
        """
        # Check active count under lock
        with self._data_lock:
            active_count = len(self._active_runnables)

        if active_count > 0:
            logger.info(f"Cleaning up {active_count} active runnables")

            # Wait for thread pool to finish (outside lock - blocking operation)
            _ = QThreadPool.globalInstance().waitForDone(5000)

            # Clear tracking data under lock
            with self._data_lock:
                self._active_runnables.clear()
                self._runnable_metadata.clear()

        # Get final stats under lock
        with self._data_lock:
            stats = dict(self._stats)

        logger.info(
            "QRunnableTracker cleanup complete - "
            f"Total: {stats['total_registered']}, "
            f"Completed: {stats['total_completed']}, "
            f"Peak concurrent: {stats['peak_concurrent']}"
        )

    @classmethod
    @override
    def _cleanup_instance(cls) -> None:
        """Clean up all tracked runnables before singleton reset."""
        if cls._instance is not None:
            cls._instance.cleanup_all()


@final
class TrackedQRunnable(QRunnable):
    """Base class for tracked QRunnables.

    Automatically registers/unregisters with the tracker.
    Subclasses should override the run() method.
    """

    def __init__(self, auto_delete: bool = True) -> None:
        """Initialize the tracked runnable.

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
        """Execute the runnable with automatic tracking.

        Subclasses should override _do_work() instead of this method.
        """
        try:
            self._tracker.register(self, self._metadata)
            self._do_work()
        finally:
            self._tracker.unregister(self)

    def _do_work(self) -> None:
        """Override this method to implement the actual work.

        This method is called by run() with automatic tracking.
        """
        msg = "Subclasses must implement _do_work()"
        raise NotImplementedError(msg)


def get_tracker() -> QRunnableTracker:
    """Get the global QRunnableTracker instance."""
    return QRunnableTracker()


def register_runnable(
    runnable: QRunnable, metadata: Mapping[str, object] | None = None
) -> None:
    """Convenience function to register a runnable with the global tracker."""
    QRunnableTracker().register(runnable, metadata)


def unregister_runnable(runnable: QRunnable) -> None:
    """Convenience function to unregister a runnable from the global tracker."""
    QRunnableTracker().unregister(runnable)


def cleanup_all_runnables() -> None:
    """Convenience function to cleanup all runnables via the global tracker."""
    QRunnableTracker().cleanup_all()


class FolderOpenerSignals(QObject):
    """Signals for the folder opener worker."""

    error: Signal = Signal(str)
    success: Signal = Signal()


class FolderOpenerWorker(QRunnable):
    """Worker to open folders in a non-blocking way."""

    def __init__(self, folder_path: str) -> None:
        """Initialize the worker.

        Args:
            folder_path: Path to the folder to open

        """
        super().__init__()
        self.folder_path: str = folder_path
        self.signals: FolderOpenerSignals = FolderOpenerSignals()

    @override
    def run(self) -> None:
        """Open the folder using the appropriate method for the platform."""
        tracker = get_tracker()
        metadata = {
            "type": "FolderOpenerWorker",
            "folder_path": self.folder_path,
        }
        tracker.register(self, metadata)

        try:
            # Ensure we have a proper absolute path
            folder_path = self.folder_path
            if not folder_path.startswith("/"):
                folder_path = "/" + folder_path

            # Check if path exists
            if not Path(folder_path).exists():
                # Safe signal emission
                if hasattr(self, "signals") and self.signals:
                    with contextlib.suppress(RuntimeError):
                        self.signals.error.emit(f"Path does not exist: {folder_path}")
                return

            # Try Qt method first (cross-platform)
            url = QUrl()
            url.setScheme("file")
            url.setPath(folder_path)

            logger.debug(f"Opening folder: {folder_path} with URL: {url.toString()}")

            # Use QDesktopServices but with proper error handling
            success = QDesktopServices.openUrl(url)

            if not success:
                # Fallback to system-specific commands
                logger.debug("QDesktopServices failed, trying system command")

                if sys.platform == "darwin":  # macOS
                    _ = subprocess.run(["open", folder_path], check=True)
                elif sys.platform == "win32":  # Windows
                    _ = subprocess.run(["explorer", folder_path], check=True)
                else:  # Linux/Unix
                    # Try xdg-open first, then alternatives
                    try:
                        _ = subprocess.run(["xdg-open", folder_path], check=True)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        # Try gio as fallback
                        _ = subprocess.run(["gio", "open", folder_path], check=True)

            # Safe signal emission
            if hasattr(self, "signals") and self.signals:
                with contextlib.suppress(RuntimeError):
                    self.signals.success.emit()

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to open folder: {e}"
            logger.error(error_msg)
            # Safe signal emission
            if hasattr(self, "signals") and self.signals:
                with contextlib.suppress(RuntimeError):
                    self.signals.error.emit(error_msg)
        except FileNotFoundError as e:
            error_msg = f"File manager not found: {e}"
            logger.error(error_msg)
            # Safe signal emission
            if hasattr(self, "signals") and self.signals:
                with contextlib.suppress(RuntimeError):
                    self.signals.error.emit(error_msg)
        except Exception as e:  # noqa: BLE001
            error_msg = f"Unexpected error opening folder: {e}"
            logger.error(error_msg)
            # Safe signal emission
            if hasattr(self, "signals") and self.signals:
                with contextlib.suppress(RuntimeError):
                    self.signals.error.emit(error_msg)
        finally:
            # Always unregister from tracker when done
            tracker.unregister(self)
