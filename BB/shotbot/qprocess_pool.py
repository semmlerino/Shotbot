"""QProcess pool for concurrent process management with resource limits.

This module provides a thread-safe process pool implementation using QProcess
for efficient concurrent command execution with proper resource management.
"""

import enum
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QTimer, Signal

from qprocess_wrapper import (
    ProcessConfig,
    ProcessInfo,
    ProcessObserver,
    QProcessWrapper,
)

# Set up logger for this module
logger = logging.getLogger(__name__)


class PoolState(enum.Enum):
    """Process pool state enumeration."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class PoolStats:
    """Statistics for process pool operation."""

    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_timed_out: int = 0
    current_running: int = 0
    current_queued: int = 0
    average_duration_ms: float = 0.0
    peak_concurrent: int = 0
    last_activity_time: float = field(default_factory=time.time)


@dataclass
class ProcessTask:
    """A task to be executed by the process pool."""

    task_id: str
    config: ProcessConfig
    callback: Optional[Callable[[ProcessInfo], None]] = None
    error_callback: Optional[Callable[[str, str], None]] = None
    priority: int = 0
    submitted_time: float = field(default_factory=time.time)
    started_time: Optional[float] = None
    completed_time: Optional[float] = None


class ProcessPoolObserver(ProcessObserver):
    """Observer for pool-managed processes."""

    def __init__(self, pool: "QProcessPool", task: ProcessTask):
        self.pool = pool
        self.task = task

    def on_started(self, process_id: str) -> None:
        """Handle process start."""
        self.task.started_time = time.time()
        logger.debug(f"Pool task {self.task.task_id} started as process {process_id}")

    def on_output(self, process_id: str, output: str, is_error: bool) -> None:
        """Handle process output."""
        # Pool doesn't handle output directly, let wrapper emit signals
        pass

    def on_finished(self, process_id: str, exit_code: int, exit_status) -> None:
        """Handle process completion."""
        self.task.completed_time = time.time()
        self.pool._handle_task_completion(self.task, process_id)

    def on_error(self, process_id: str, error) -> None:
        """Handle process error."""
        if self.task.error_callback:
            try:
                self.task.error_callback(self.task.task_id, str(error))
            except Exception as e:
                logger.error(f"Error in task error callback: {e}")


class QProcessPool(QObject):
    """Thread-safe process pool for concurrent command execution.

    This pool provides:
    - Configurable concurrency limits
    - Priority-based task scheduling
    - Automatic process recycling
    - Resource usage monitoring
    - Graceful shutdown with timeout
    - Task callbacks for completion/error handling

    Example:
        >>> pool = QProcessPool(max_processes=4)
        >>> pool.task_completed.connect(lambda task_id: print(f"Task {task_id} done"))
        >>> config = ProcessConfig(command="ls", arguments=["-la"])
        >>> task_id = pool.submit(config, priority=1)
        >>> # Wait for all tasks
        >>> pool.wait_all(timeout_ms=10000)
        >>> pool.shutdown()
    """

    # Signals
    task_submitted = Signal(str)  # task_id
    task_started = Signal(str, str)  # task_id, process_id
    task_completed = Signal(str, int)  # task_id, exit_code
    task_failed = Signal(str, str)  # task_id, error_message
    pool_idle = Signal()
    pool_busy = Signal()
    stats_updated = Signal(PoolStats)

    def __init__(
        self,
        max_processes: int = 4,
        max_queue_size: int = 100,
        enable_recycling: bool = True,
        recycle_after: int = 10,
        parent: Optional[QObject] = None,
    ):
        """Initialize process pool.

        Args:
            max_processes: Maximum concurrent processes
            max_queue_size: Maximum queued tasks
            enable_recycling: Recycle processes after N uses
            recycle_after: Number of uses before recycling
            parent: Parent QObject
        """
        super().__init__(parent)

        self.max_processes = max(1, max_processes)
        self.max_queue_size = max_queue_size
        self.enable_recycling = enable_recycling
        self.recycle_after = recycle_after

        # Thread safety
        self._mutex = QMutex()

        # Pool state
        self._state = PoolState.IDLE
        self._stats = PoolStats()

        # Task management
        self._task_queue: Deque[ProcessTask] = deque()
        self._running_tasks: Dict[str, ProcessTask] = {}  # process_id -> task
        self._completed_tasks: Dict[str, ProcessTask] = {}  # task_id -> task

        # Process management
        self._available_processes: List[QProcessWrapper] = []
        self._busy_processes: Dict[str, QProcessWrapper] = {}  # process_id -> wrapper
        self._process_usage: Dict[str, int] = {}  # process_id -> usage_count

        # Monitoring
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._monitor_pool)
        self._monitor_timer.start(1000)  # Check every second

        # Initialize process wrappers
        self._initialize_processes()

    def _initialize_processes(self) -> None:
        """Initialize the pool of process wrappers."""
        for i in range(self.max_processes):
            process_id = f"pool_process_{i}_{uuid.uuid4().hex[:8]}"
            wrapper = QProcessWrapper(process_id=process_id, parent=self)

            # Connect signals for monitoring
            wrapper.finished.connect(self._on_process_finished)
            wrapper.error_occurred.connect(self._on_process_error)

            self._available_processes.append(wrapper)
            self._process_usage[process_id] = 0

        logger.info(f"Initialized process pool with {self.max_processes} processes")

    def submit(
        self,
        config: ProcessConfig,
        task_id: Optional[str] = None,
        priority: int = 0,
        callback: Optional[Callable[[ProcessInfo], None]] = None,
        error_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Optional[str]:
        """Submit a task to the process pool.

        Args:
            config: Process configuration
            task_id: Optional task ID (generated if not provided)
            priority: Task priority (higher = executed sooner)
            callback: Optional callback on completion
            error_callback: Optional callback on error

        Returns:
            Task ID if submitted successfully, None if queue is full
        """
        with QMutexLocker(self._mutex):
            if len(self._task_queue) >= self.max_queue_size:
                logger.warning("Process pool queue is full")
                return None

            if self._state == PoolState.STOPPING:
                logger.warning("Cannot submit tasks while pool is stopping")
                return None

            # Create task
            task_id = task_id or f"task_{uuid.uuid4().hex}"
            task = ProcessTask(
                task_id=task_id,
                config=config,
                priority=priority,
                callback=callback,
                error_callback=error_callback,
            )

            # Add to queue (priority queue behavior)
            self._insert_by_priority(task)

            # Update stats
            self._stats.total_submitted += 1
            self._stats.current_queued = len(self._task_queue)
            self._stats.last_activity_time = time.time()

            # Try to schedule immediately
            self._schedule_next_task()

            # Emit signals
            self.task_submitted.emit(task_id)
            if self._state == PoolState.IDLE:
                self._state = PoolState.RUNNING
                self.pool_busy.emit()

            return task_id

    def _insert_by_priority(self, task: ProcessTask) -> None:
        """Insert task into queue based on priority.

        Args:
            task: Task to insert
        """
        # Higher priority tasks go first
        inserted = False
        for i, existing_task in enumerate(self._task_queue):
            if task.priority > existing_task.priority:
                self._task_queue.insert(i, task)
                inserted = True
                break

        if not inserted:
            self._task_queue.append(task)

    def _schedule_next_task(self) -> None:
        """Schedule the next task if resources are available."""
        # Must be called with mutex locked
        if not self._task_queue or not self._available_processes:
            return

        if self._state != PoolState.RUNNING:
            return

        # Get next task and available process
        task = self._task_queue.popleft()
        wrapper = self._available_processes.pop(0)

        # Update tracking
        self._running_tasks[wrapper.process_id] = task
        self._busy_processes[wrapper.process_id] = wrapper
        self._process_usage[wrapper.process_id] += 1

        # Update stats
        self._stats.current_queued = len(self._task_queue)
        self._stats.current_running = len(self._running_tasks)
        if self._stats.current_running > self._stats.peak_concurrent:
            self._stats.peak_concurrent = self._stats.current_running

        # Add observer
        observer = ProcessPoolObserver(self, task)
        wrapper.add_observer(observer)

        # Start process
        logger.debug(f"Scheduling task {task.task_id} on process {wrapper.process_id}")
        self.task_started.emit(task.task_id, wrapper.process_id)

        # Start outside mutex to avoid blocking
        QTimer.singleShot(
            0, lambda: self._start_task_process(wrapper, task)
        )  # Defer to event loop

    def _start_task_process(self, wrapper: QProcessWrapper, task: ProcessTask) -> None:
        """Start a task's process execution.

        Args:
            wrapper: Process wrapper to use
            task: Task to execute
        """
        success = wrapper.start_process(task.config)
        if not success:
            logger.error(f"Failed to start process for task {task.task_id}")
            self._handle_task_failure(task, wrapper.process_id, "Failed to start")

    def _handle_task_completion(self, task: ProcessTask, process_id: str) -> None:
        """Handle task completion.

        Args:
            task: Completed task
            process_id: Process that completed the task
        """
        with QMutexLocker(self._mutex):
            # Get wrapper and info
            wrapper = self._busy_processes.get(process_id)
            if not wrapper:
                logger.error(f"No wrapper found for process {process_id}")
                return

            info = wrapper.get_info()
            if not info:
                logger.error(f"No info available for process {process_id}")
                return

            # Update task and stats
            task.completed_time = time.time()
            self._completed_tasks[task.task_id] = task

            if info.exit_code == 0:
                self._stats.total_completed += 1
                logger.info(f"Task {task.task_id} completed successfully")
            else:
                self._stats.total_failed += 1
                logger.warning(f"Task {task.task_id} failed with code {info.exit_code}")

            if info.timed_out:
                self._stats.total_timed_out += 1

            # Update average duration
            if task.started_time:
                duration = (task.completed_time - task.started_time) * 1000
                if self._stats.average_duration_ms == 0:
                    self._stats.average_duration_ms = duration
                else:
                    # Running average
                    self._stats.average_duration_ms = (
                        self._stats.average_duration_ms * 0.9 + duration * 0.1
                    )

            # Clean up tracking
            if process_id in self._running_tasks:
                del self._running_tasks[process_id]
            if process_id in self._busy_processes:
                del self._busy_processes[process_id]

            self._stats.current_running = len(self._running_tasks)

            # Check if process needs recycling
            if self._should_recycle_process(process_id):
                self._recycle_process(wrapper)
            else:
                # Make process available again
                wrapper.remove_observer(None)  # Remove all observers
                self._available_processes.append(wrapper)

            # Schedule next task
            self._schedule_next_task()

            # Check if pool is idle
            if not self._running_tasks and not self._task_queue:
                if self._state == PoolState.RUNNING:
                    self._state = PoolState.IDLE
                    self.pool_idle.emit()

        # Call callback outside mutex
        if task.callback and info:
            try:
                task.callback(info)
            except Exception as e:
                logger.error(f"Error in task callback: {e}")

        # Emit completion signal
        self.task_completed.emit(task.task_id, info.exit_code or -1)

    def _handle_task_failure(
        self, task: ProcessTask, process_id: str, error_msg: str
    ) -> None:
        """Handle task failure.

        Args:
            task: Failed task
            process_id: Process that failed
            error_msg: Error message
        """
        with QMutexLocker(self._mutex):
            self._stats.total_failed += 1

            # Clean up
            if process_id in self._running_tasks:
                del self._running_tasks[process_id]
            if process_id in self._busy_processes:
                wrapper = self._busy_processes[process_id]
                del self._busy_processes[process_id]

                # Recycle the failed process
                self._recycle_process(wrapper)

            self._stats.current_running = len(self._running_tasks)

            # Schedule next
            self._schedule_next_task()

        # Call error callback outside mutex
        if task.error_callback:
            try:
                task.error_callback(task.task_id, error_msg)
            except Exception as e:
                logger.error(f"Error in task error callback: {e}")

        # Emit failure signal
        self.task_failed.emit(task.task_id, error_msg)

    def _should_recycle_process(self, process_id: str) -> bool:
        """Check if a process should be recycled.

        Args:
            process_id: Process ID to check

        Returns:
            True if process should be recycled
        """
        if not self.enable_recycling:
            return False

        usage = self._process_usage.get(process_id, 0)
        return usage >= self.recycle_after

    def _recycle_process(self, wrapper: QProcessWrapper) -> None:
        """Recycle a process wrapper.

        Args:
            wrapper: Process wrapper to recycle
        """
        logger.debug(f"Recycling process {wrapper.process_id}")

        # Clean up old wrapper
        old_id = wrapper.process_id
        wrapper.terminate()
        wrapper.deleteLater()

        # Create new wrapper
        new_id = f"pool_process_{uuid.uuid4().hex[:8]}"
        new_wrapper = QProcessWrapper(process_id=new_id, parent=self)
        new_wrapper.finished.connect(self._on_process_finished)
        new_wrapper.error_occurred.connect(self._on_process_error)

        # Update tracking
        if old_id in self._process_usage:
            del self._process_usage[old_id]
        self._process_usage[new_id] = 0

        # Make available
        self._available_processes.append(new_wrapper)

    def _on_process_finished(self, process_id: str, exit_code: int, exit_status):
        """Handle process finished signal.

        Args:
            process_id: Process that finished
            exit_code: Exit code
            exit_status: Exit status
        """
        # Task completion is handled by observer
        pass

    def _on_process_error(self, process_id: str, error_msg: str):
        """Handle process error signal.

        Args:
            process_id: Process that errored
            error_msg: Error message
        """
        with QMutexLocker(self._mutex):
            if task := self._running_tasks.get(process_id):
                self._handle_task_failure(task, process_id, error_msg)

    def _monitor_pool(self) -> None:
        """Monitor pool health and emit statistics."""
        with QMutexLocker(self._mutex):
            # Emit updated stats
            self.stats_updated.emit(self._stats)

            # Log status periodically
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Pool status: {self._stats.current_running} running, "
                    f"{self._stats.current_queued} queued, "
                    f"{self._stats.total_completed} completed"
                )

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a queued task.

        Args:
            task_id: Task to cancel

        Returns:
            True if task was cancelled
        """
        with QMutexLocker(self._mutex):
            # Find and remove from queue
            for i, task in enumerate(self._task_queue):
                if task.task_id == task_id:
                    self._task_queue.remove(task)
                    self._stats.current_queued = len(self._task_queue)
                    logger.info(f"Cancelled queued task {task_id}")
                    return True

            # Check if running
            for process_id, task in self._running_tasks.items():
                if task.task_id == task_id:
                    # Can't cancel running task, but we can terminate it
                    if wrapper := self._busy_processes.get(process_id):
                        wrapper.terminate()
                        logger.info(f"Terminated running task {task_id}")
                        return True

        return False

    def wait_all(self, timeout_ms: int = -1) -> bool:
        """Wait for all tasks to complete.

        Args:
            timeout_ms: Maximum time to wait (-1 for no timeout)

        Returns:
            True if all tasks completed within timeout
        """
        start_time = time.time()

        while True:
            with QMutexLocker(self._mutex):
                if not self._running_tasks and not self._task_queue:
                    return True

            if timeout_ms > 0:
                elapsed_ms = (time.time() - start_time) * 1000
                if elapsed_ms >= timeout_ms:
                    return False

            # Process events to allow signals to be delivered
            QTimer.singleShot(100, lambda: None)
            time.sleep(0.1)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Shutdown the process pool.

        Args:
            timeout_ms: Maximum time to wait for graceful shutdown
        """
        logger.info("Shutting down process pool")

        with QMutexLocker(self._mutex):
            self._state = PoolState.STOPPING

            # Cancel queued tasks
            self._task_queue.clear()
            self._stats.current_queued = 0

        # Wait for running tasks with timeout
        self.wait_all(timeout_ms)

        with QMutexLocker(self._mutex):
            # Terminate all processes
            for wrapper in self._available_processes:
                wrapper.terminate()
                wrapper.deleteLater()

            for wrapper in self._busy_processes.values():
                wrapper.terminate()
                wrapper.deleteLater()

            self._available_processes.clear()
            self._busy_processes.clear()
            self._running_tasks.clear()

            self._state = PoolState.STOPPED

        # Stop monitoring
        self._monitor_timer.stop()

        logger.info("Process pool shutdown complete")

    def get_stats(self) -> PoolStats:
        """Get current pool statistics.

        Returns:
            Current PoolStats
        """
        with QMutexLocker(self._mutex):
            return self._stats

    def is_idle(self) -> bool:
        """Check if pool is idle.

        Returns:
            True if no tasks are running or queued
        """
        with QMutexLocker(self._mutex):
            return not self._running_tasks and not self._task_queue

    def get_queue_size(self) -> int:
        """Get current queue size.

        Returns:
            Number of queued tasks
        """
        with QMutexLocker(self._mutex):
            return len(self._task_queue)
