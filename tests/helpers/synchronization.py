"""Synchronization helpers to replace time.sleep() in tests for better performance."""

from __future__ import annotations

# Standard library imports
import gc
import os
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

# Third-party imports
import psutil
from PySide6.QtCore import QEventLoop, QTimer, Signal
from PySide6.QtTest import QSignalSpy


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable
    from pathlib import Path


class SynchronizationHelpers:
    """Helper methods for proper test synchronization without time.sleep()."""

    @staticmethod
    def wait_for_condition(
        condition: Callable[[], bool],
        timeout_ms: int = 1000,
        poll_interval_ms: int = 10,
    ) -> bool:
        """Wait for a condition to become true with polling.

        Args:
            condition: Function that returns True when condition is met
            timeout_ms: Maximum time to wait in milliseconds
            poll_interval_ms: How often to check condition in milliseconds

        Returns:
            True if condition was met, False if timeout

        Example:
            # Instead of: time.sleep(0.1)
            # Use: wait_for_condition(lambda: widget.isVisible(), timeout_ms=100)

        """
        start_time = time.perf_counter()
        timeout_sec = timeout_ms / 1000.0
        poll_interval_sec = poll_interval_ms / 1000.0

        while time.perf_counter() - start_time < timeout_sec:
            if condition():
                return True
            time.sleep(poll_interval_sec)  # Small sleep for polling

        return False

    @staticmethod
    def wait_for_file_operation(
        file_path: Path,
        operation: str = "exists",
        timeout_ms: int = 1000,
    ) -> bool:
        """Wait for a file operation to complete.

        Args:
            file_path: Path to check
            operation: One of "exists", "not_exists", "writable"
            timeout_ms: Maximum time to wait

        Returns:
            True if operation succeeded, False if timeout

        Example:
            # Instead of: time.sleep(0.1)  # Wait for file deletion
            # Use: wait_for_file_operation(path, "not_exists", 100)

        """
        conditions = {
            "exists": lambda: file_path.exists(),
            "not_exists": lambda: not file_path.exists(),
            "writable": lambda: file_path.exists() and file_path.stat().st_mode & 0o200,
        }

        if operation not in conditions:
            raise ValueError(f"Unknown operation: {operation}")

        return SynchronizationHelpers.wait_for_condition(
            conditions[operation],
            timeout_ms,
        )

    @staticmethod
    def wait_for_qt_signal(
        qtbot: Any,
        signal: Signal,
        timeout_ms: int = 1000,
        trigger: Callable | None = None,
    ) -> Any:
        """Wait for a Qt signal to be emitted.

        Args:
            qtbot: pytest-qt fixture
            signal: Qt signal to wait for
            timeout_ms: Maximum time to wait
            trigger: Optional function to call to trigger the signal

        Returns:
            Signal arguments or raises TimeoutError

        Example:
            # Instead of: model.refresh(); time.sleep(0.5)
            # Use: wait_for_qt_signal(qtbot, model.refreshed, 500, model.refresh)

        """
        if trigger:
            with qtbot.waitSignal(signal, timeout=timeout_ms) as blocker:
                trigger()
            return blocker.args
        with qtbot.waitSignal(signal, timeout=timeout_ms) as blocker:
            pass
        return blocker.args

    @staticmethod
    def process_qt_events(_qapp: Any, duration_ms: int = 10) -> None:
        """Process Qt events for a specific duration without blocking.

        Args:
            qapp: QApplication instance
            duration_ms: How long to process events

        Example:
            # Instead of: time.sleep(0.01)  # Let UI update
            # Use: process_qt_events(qapp, 10)

        """
        loop = QEventLoop()
        QTimer.singleShot(duration_ms, loop.quit)
        loop.exec()

    @staticmethod
    @contextmanager
    def wait_for_threads_to_start(
        max_wait_ms: int = 100,
    ) -> Generator[None, None, None]:
        """Context manager to ensure threads have started.

        Example:
            # ❌ WRONG - no cleanup guarantee
            thread.start()
            time.sleep(0.1)  # Anti-pattern

            # ✅ RIGHT - proper wait with cleanup
            thread = QThread()
            with wait_for_threads_to_start():
                thread.start()
            try:
                # ... test code ...
            finally:
                thread.quit()
                thread.wait(1000)

        """
        initial_count = threading.active_count()

        yield

        # Wait for thread count to increase
        SynchronizationHelpers.wait_for_condition(
            lambda: threading.active_count() > initial_count,
            timeout_ms=max_wait_ms,
        )

    @staticmethod
    def wait_for_cache_operation(
        cache_manager: Any,
        operation: str = "thumbnail_exists",
        timeout_ms: int = 100,
        **kwargs,
    ) -> bool:
        """Wait for cache operation to complete.

        Args:
            cache_manager: CacheManager instance
            operation: Type of operation to wait for
            timeout_ms: Maximum wait time
            **kwargs: Arguments for the check (show, sequence, shot)

        Example:
            # Instead of: cache_thumbnail(); time.sleep(0.1)
            # Use: cache_thumbnail(); wait_for_cache_operation(manager, "thumbnail_exists", show=...)

        """
        if operation == "thumbnail_exists":
            show = kwargs.get("show")
            sequence = kwargs.get("sequence")
            shot = kwargs.get("shot")

            return SynchronizationHelpers.wait_for_condition(
                lambda: cache_manager.get_cached_thumbnail(show, sequence, shot)
                is not None,
                timeout_ms=timeout_ms,
            )
        if operation == "directory_exists":
            return SynchronizationHelpers.wait_for_condition(
                lambda: cache_manager.thumbnails_dir.exists(),
                timeout_ms=timeout_ms,
            )
        raise ValueError(f"Unknown operation: {operation}")

    @staticmethod
    def wait_for_process_completion(
        process_manager: Any,
        process_key: str,
        timeout_ms: int = 1000,
    ) -> bool:
        """Wait for a process to complete.

        Args:
            process_manager: Process manager instance
            process_key: Key of the process to wait for
            timeout_ms: Maximum wait time

        Returns:
            True if process completed, False if timeout

        Example:
            # Instead of: launch_process(); time.sleep(0.5)
            # Use: key = launch_process(); wait_for_process_completion(manager, key, 500)

        """
        return SynchronizationHelpers.wait_for_condition(
            lambda: not process_manager.is_process_active(process_key),
            timeout_ms=timeout_ms,
        )

    @staticmethod
    def wait_for_memory_cleanup(
        threshold_mb: float = 100,
        timeout_ms: int = 1000,
    ) -> bool:
        """Wait for memory to be cleaned up after operations.

        Args:
            threshold_mb: Memory threshold in MB
            timeout_ms: Maximum wait time

        Returns:
            True if memory below threshold, False if timeout

        Example:
            # Instead of: del large_object; time.sleep(0.1); gc.collect()
            # Use: del large_object; wait_for_memory_cleanup(100, 1000)

        """
        process = psutil.Process(os.getpid())
        threshold_bytes = threshold_mb * 1024 * 1024

        def check_memory():
            gc.collect()
            return process.memory_info().rss < threshold_bytes

        return SynchronizationHelpers.wait_for_condition(
            check_memory,
            timeout_ms=timeout_ms,
            poll_interval_ms=50,
        )

    @staticmethod
    def simulate_work_without_sleep(duration_ms: int = 10) -> None:
        """Simulate work without using sleep for stress tests.

        Args:
            duration_ms: How long to simulate work

        Example:
            # Instead of: time.sleep(0.01)  # Simulate work
            # Use: simulate_work_without_sleep(10)

        """
        # Use busy-wait with yield to simulate work without blocking
        start = time.perf_counter()
        target = start + (duration_ms / 1000.0)

        while time.perf_counter() < target:
            # Yield to other threads
            time.sleep(0)  # Minimal sleep just to yield

    @staticmethod
    def create_async_waiter(qtbot: Any) -> AsyncWaiter:
        """Create an async waiter for complex multi-signal scenarios.

        Example:
            waiter = create_async_waiter(qtbot)
            waiter.add_signal(model.started)
            waiter.add_signal(model.finished)
            model.start_operation()
            waiter.wait_for_all(timeout_ms=1000)

        """
        return AsyncWaiter(qtbot)


class AsyncWaiter:
    """Helper for waiting on multiple async operations."""

    def __init__(self, qtbot: Any) -> None:
        self.qtbot = qtbot
        self.signals = []
        self.conditions = []

    def add_signal(self, signal: Signal) -> AsyncWaiter:
        """Add a signal to wait for."""
        self.signals.append(signal)
        return self

    def add_condition(self, condition: Callable[[], bool]) -> AsyncWaiter:
        """Add a condition to wait for."""
        self.conditions.append(condition)
        return self

    def wait_for_all(self, timeout_ms: int = 1000) -> bool:
        """Wait for all signals and conditions."""
        # Create blockers for all signals
        blockers = []
        for signal in self.signals:
            spy = QSignalSpy(signal)
            blockers.append(spy)

        # Wait for all conditions and signals
        start_time = time.perf_counter()
        timeout_sec = timeout_ms / 1000.0

        while time.perf_counter() - start_time < timeout_sec:
            # Check if all signals received
            signals_done = all(len(blocker) > 0 for blocker in blockers)

            # Check if all conditions met
            conditions_done = all(cond() for cond in self.conditions)

            if signals_done and conditions_done:
                return True

            # Process events
            QEventLoop().processEvents()
            time.sleep(0.001)  # Minimal sleep

        return False


# Convenience functions for direct import
wait_for_condition = SynchronizationHelpers.wait_for_condition
wait_for_file_operation = SynchronizationHelpers.wait_for_file_operation
wait_for_qt_signal = SynchronizationHelpers.wait_for_qt_signal
process_qt_events = SynchronizationHelpers.process_qt_events
wait_for_threads_to_start = SynchronizationHelpers.wait_for_threads_to_start
wait_for_cache_operation = SynchronizationHelpers.wait_for_cache_operation
wait_for_process_completion = SynchronizationHelpers.wait_for_process_completion
wait_for_memory_cleanup = SynchronizationHelpers.wait_for_memory_cleanup
simulate_work_without_sleep = SynchronizationHelpers.simulate_work_without_sleep
create_async_waiter = SynchronizationHelpers.create_async_waiter
