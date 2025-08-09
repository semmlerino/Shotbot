"""Thread-safe process and resource management architecture.

This module provides production-ready thread safety patterns and resource management
utilities for the shotbot application.
"""

import contextlib
import functools
import logging
import queue
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from PySide6.QtCore import QMutex, QProcess, QThread

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProcessState(Enum):
    """Process lifecycle states."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    COMPLETED = "completed"


class LockHierarchy(Enum):
    """Lock hierarchy levels to prevent deadlocks.

    Lower values must be acquired before higher values.
    """

    GLOBAL = 1  # Global state locks
    COLLECTION = 2  # Collection-level locks (processes, workers, cache)
    RESOURCE = 3  # Individual resource locks
    ITEM = 4  # Item-level locks


@dataclass
class LockContext:
    """Context for a lock with deadlock prevention."""

    name: str
    level: LockHierarchy
    lock: Union[threading.RLock, QMutex]
    acquired_at: Optional[datetime] = None
    thread_id: Optional[int] = None
    timeout: float = 30.0  # Default timeout in seconds


class DeadlockPreventingLockManager:
    """Manager that enforces lock hierarchy to prevent deadlocks."""

    def __init__(self):
        self._thread_locks: Dict[int, List[LockContext]] = {}
        self._lock = threading.RLock()

    def acquire(self, context: LockContext, timeout: Optional[float] = None) -> bool:
        """Acquire a lock following hierarchy rules.

        Args:
            context: Lock context to acquire
            timeout: Optional timeout in seconds

        Returns:
            True if lock acquired, False if would violate hierarchy or timeout
        """
        thread_id = threading.get_ident()
        timeout = timeout or context.timeout

        with self._lock:
            # Check hierarchy
            thread_contexts = self._thread_locks.get(thread_id, [])
            for held_context in thread_contexts:
                if held_context.level.value > context.level.value:
                    logger.error(
                        f"Lock hierarchy violation: Thread {thread_id} holds "
                        f"{held_context.name} (level {held_context.level.value}) "
                        f"but trying to acquire {context.name} (level {context.level.value})"
                    )
                    return False

            # Try to acquire the lock
            acquired = False
            if isinstance(context.lock, threading.RLock):
                acquired = context.lock.acquire(timeout=timeout)
            elif isinstance(context.lock, QMutex):
                acquired = context.lock.tryLock(int(timeout * 1000))

            if acquired:
                context.acquired_at = datetime.now()
                context.thread_id = thread_id
                if thread_id not in self._thread_locks:
                    self._thread_locks[thread_id] = []
                self._thread_locks[thread_id].append(context)
                logger.debug(f"Thread {thread_id} acquired lock {context.name}")
                return True
            else:
                logger.warning(
                    f"Thread {thread_id} failed to acquire lock {context.name} "
                    f"within {timeout}s timeout"
                )
                return False

    def release(self, context: LockContext):
        """Release a lock and update tracking."""
        thread_id = threading.get_ident()

        with self._lock:
            if thread_id in self._thread_locks:
                try:
                    self._thread_locks[thread_id].remove(context)
                    if not self._thread_locks[thread_id]:
                        del self._thread_locks[thread_id]
                except ValueError:
                    logger.warning(
                        f"Thread {thread_id} tried to release lock {context.name} "
                        "but didn't hold it"
                    )

            # Release the actual lock
            if isinstance(context.lock, threading.RLock):
                context.lock.release()
            elif isinstance(context.lock, QMutex):
                context.lock.unlock()

            logger.debug(f"Thread {thread_id} released lock {context.name}")

    @contextlib.contextmanager
    def lock_context(self, context: LockContext, timeout: Optional[float] = None):
        """Context manager for safe lock acquisition and release."""
        acquired = self.acquire(context, timeout)
        if not acquired:
            raise RuntimeError(f"Failed to acquire lock {context.name}")
        try:
            yield
        finally:
            self.release(context)


# Global lock manager instance
_lock_manager = DeadlockPreventingLockManager()


class ThreadSafeCollection(Generic[T]):
    """Thread-safe collection with iteration safety."""

    def __init__(self, name: str = "collection"):
        self.name = name
        self._items: OrderedDict[str, T] = OrderedDict()
        self._lock_context = LockContext(
            name=f"{name}_collection",
            level=LockHierarchy.COLLECTION,
            lock=threading.RLock(),
        )
        self._iteration_lock = threading.RLock()
        self._iterating_threads: Set[int] = set()

    def add(self, key: str, item: T) -> bool:
        """Add an item to the collection."""
        with _lock_manager.lock_context(self._lock_context):
            if key in self._items:
                logger.warning(f"Key {key} already exists in {self.name}")
                return False
            self._items[key] = item
            logger.debug(f"Added {key} to {self.name}")
            return True

    def remove(self, key: str) -> Optional[T]:
        """Remove and return an item from the collection."""
        with _lock_manager.lock_context(self._lock_context):
            if key not in self._items:
                return None
            item = self._items.pop(key)
            logger.debug(f"Removed {key} from {self.name}")
            return item

    def get(self, key: str) -> Optional[T]:
        """Get an item without removing it."""
        with _lock_manager.lock_context(self._lock_context):
            return self._items.get(key)

    def get_all(self) -> Dict[str, T]:
        """Get a snapshot of all items."""
        with _lock_manager.lock_context(self._lock_context):
            return dict(self._items)

    def keys(self) -> List[str]:
        """Get list of all keys."""
        with _lock_manager.lock_context(self._lock_context):
            return list(self._items.keys())

    def values(self) -> List[T]:
        """Get list of all values."""
        with _lock_manager.lock_context(self._lock_context):
            return list(self._items.values())

    def items(self) -> List[Tuple[str, T]]:
        """Get list of all key-value pairs."""
        with _lock_manager.lock_context(self._lock_context):
            return list(self._items.items())

    def clear(self):
        """Clear all items."""
        with _lock_manager.lock_context(self._lock_context):
            self._items.clear()
            logger.debug(f"Cleared {self.name}")

    def size(self) -> int:
        """Get number of items."""
        with _lock_manager.lock_context(self._lock_context):
            return len(self._items)

    @contextlib.contextmanager
    def safe_iteration(self) -> Iterator[Dict[str, T]]:
        """Context manager for safe iteration.

        Yields:
            Snapshot of items for safe iteration
        """
        thread_id = threading.get_ident()

        with self._iteration_lock:
            self._iterating_threads.add(thread_id)

        try:
            # Get snapshot under lock
            with _lock_manager.lock_context(self._lock_context):
                snapshot = dict(self._items)
            yield snapshot
        finally:
            with self._iteration_lock:
                self._iterating_threads.discard(thread_id)


@dataclass
class ProcessInfo:
    """Enhanced process information with state tracking."""

    process_id: str
    launcher_id: str
    launcher_name: str
    command: str
    state: ProcessState = ProcessState.PENDING
    process: Optional[Union[QProcess, Any]] = None  # QProcess or subprocess.Popen
    worker: Optional[QThread] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    output_buffer: List[str] = field(default_factory=list)
    max_output_lines: int = 1000

    def add_output(self, line: str):
        """Add output line with buffer management."""
        self.output_buffer.append(line)
        if len(self.output_buffer) > self.max_output_lines:
            # Keep only last N lines
            self.output_buffer = self.output_buffer[-self.max_output_lines :]

    def get_runtime(self) -> Optional[timedelta]:
        """Get process runtime."""
        if self.started_at:
            end_time = self.stopped_at or datetime.now()
            return end_time - self.started_at
        return None

    def is_running(self) -> bool:
        """Check if process is in a running state."""
        return self.state in (ProcessState.STARTING, ProcessState.RUNNING)

    def is_finished(self) -> bool:
        """Check if process is in a finished state."""
        return self.state in (
            ProcessState.STOPPED,
            ProcessState.FAILED,
            ProcessState.COMPLETED,
        )


class ThreadSafeProcessManager:
    """Thread-safe process manager with lifecycle management."""

    def __init__(self, max_processes: int = 100):
        self.max_processes = max_processes
        self._processes = ThreadSafeCollection[ProcessInfo]("processes")
        self._state_lock = LockContext(
            name="process_state",
            level=LockHierarchy.GLOBAL,
            lock=threading.RLock(),
        )
        self._shutdown = False
        self._cleanup_interval = 30  # seconds
        self._last_cleanup = datetime.now()

    def can_start_process(self) -> bool:
        """Check if a new process can be started."""
        with _lock_manager.lock_context(self._state_lock):
            if self._shutdown:
                return False

            # Count running processes
            running_count = sum(1 for p in self._processes.values() if p.is_running())
            return running_count < self.max_processes

    def register_process(self, process_info: ProcessInfo) -> bool:
        """Register a new process."""
        if not self.can_start_process():
            logger.warning(
                f"Cannot start process {process_info.process_id}: "
                f"limit reached or shutting down"
            )
            return False

        success = self._processes.add(process_info.process_id, process_info)
        if success:
            process_info.state = ProcessState.STARTING
            process_info.started_at = datetime.now()
            logger.info(f"Registered process {process_info.process_id}")
        return success

    def update_process_state(
        self,
        process_id: str,
        state: ProcessState,
        exit_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        """Update process state with proper transitions."""
        process_info = self._processes.get(process_id)
        if not process_info:
            logger.warning(f"Process {process_id} not found for state update")
            return

        # Validate state transition
        valid_transitions = {
            ProcessState.PENDING: [ProcessState.STARTING, ProcessState.FAILED],
            ProcessState.STARTING: [ProcessState.RUNNING, ProcessState.FAILED],
            ProcessState.RUNNING: [
                ProcessState.STOPPING,
                ProcessState.COMPLETED,
                ProcessState.FAILED,
            ],
            ProcessState.STOPPING: [ProcessState.STOPPED, ProcessState.FAILED],
            # Terminal states
            ProcessState.STOPPED: [],
            ProcessState.FAILED: [],
            ProcessState.COMPLETED: [],
        }

        if state not in valid_transitions.get(process_info.state, []):
            logger.warning(
                f"Invalid state transition for {process_id}: "
                f"{process_info.state} -> {state}"
            )
            return

        # Update state
        old_state = process_info.state
        process_info.state = state

        if exit_code is not None:
            process_info.exit_code = exit_code

        if error_message:
            process_info.error_message = error_message

        if state in (ProcessState.STOPPED, ProcessState.FAILED, ProcessState.COMPLETED):
            process_info.stopped_at = datetime.now()

        logger.info(f"Process {process_id} state changed: {old_state} -> {state}")

    def terminate_process(self, process_id: str, force: bool = False) -> bool:
        """Terminate a process safely."""
        process_info = self._processes.get(process_id)
        if not process_info:
            return False

        if process_info.is_finished():
            logger.debug(f"Process {process_id} already finished")
            return True

        # Update state
        self.update_process_state(process_id, ProcessState.STOPPING)

        # Terminate the actual process
        try:
            if process_info.worker and isinstance(process_info.worker, QThread):
                # Stop Qt worker thread
                if process_info.worker.isRunning():
                    process_info.worker.quit()
                    if not process_info.worker.wait(5000):  # 5 second timeout
                        process_info.worker.terminate()
                        process_info.worker.wait()

            elif process_info.process:
                if isinstance(process_info.process, QProcess):
                    # Terminate QProcess
                    if process_info.process.state() != QProcess.ProcessState.NotRunning:
                        if force:
                            process_info.process.kill()
                        else:
                            process_info.process.terminate()
                        if not process_info.process.waitForFinished(5000):
                            process_info.process.kill()
                else:
                    # Terminate subprocess.Popen
                    if process_info.process.poll() is None:
                        if force:
                            process_info.process.kill()
                        else:
                            process_info.process.terminate()
                        try:
                            process_info.process.wait(timeout=5)
                        except (subprocess.TimeoutExpired, TimeoutError):
                            process_info.process.kill()

            self.update_process_state(process_id, ProcessState.STOPPED)
            return True

        except Exception as e:
            logger.error(f"Error terminating process {process_id}: {e}")
            self.update_process_state(
                process_id, ProcessState.FAILED, error_message=str(e)
            )
            return False

    def cleanup_finished_processes(self, force: bool = False):
        """Clean up finished processes."""
        now = datetime.now()

        # Check if cleanup is needed
        if not force and (now - self._last_cleanup).seconds < self._cleanup_interval:
            return

        self._last_cleanup = now
        cleaned_count = 0

        # Use safe iteration
        with self._processes.safe_iteration() as snapshot:
            for process_id, process_info in snapshot.items():
                if process_info.is_finished():
                    # Check if process has been finished for a while
                    if process_info.stopped_at:
                        age = (now - process_info.stopped_at).seconds
                        if age > 60:  # Keep finished processes for 1 minute
                            self._processes.remove(process_id)
                            cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} finished processes")

    def get_process_stats(self) -> Dict[str, Any]:
        """Get process statistics."""
        stats = {
            "total": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "average_runtime": None,
        }

        runtimes = []
        for process_info in self._processes.values():
            stats["total"] += 1

            if process_info.state == ProcessState.RUNNING:
                stats["running"] += 1
            elif process_info.state == ProcessState.COMPLETED:
                stats["completed"] += 1
            elif process_info.state == ProcessState.FAILED:
                stats["failed"] += 1

            runtime = process_info.get_runtime()
            if runtime:
                runtimes.append(runtime.total_seconds())

        if runtimes:
            stats["average_runtime"] = sum(runtimes) / len(runtimes)

        return stats

    def shutdown(self):
        """Shutdown the process manager."""
        logger.info("Shutting down process manager...")
        self._shutdown = True

        # Terminate all running processes
        with self._processes.safe_iteration() as snapshot:
            for process_id, process_info in snapshot.items():
                if process_info.is_running():
                    self.terminate_process(process_id)

        # Final cleanup
        self.cleanup_finished_processes(force=True)
        logger.info("Process manager shutdown complete")


class ResourcePool(Generic[T]):
    """Thread-safe resource pool with automatic cleanup."""

    def __init__(
        self,
        name: str,
        factory: Callable[[], T],
        max_size: int = 10,
        max_idle_time: int = 300,  # 5 minutes
        cleanup_func: Optional[Callable[[T], None]] = None,
    ):
        self.name = name
        self.factory = factory
        self.max_size = max_size
        self.max_idle_time = max_idle_time
        self.cleanup_func = cleanup_func

        self._pool: queue.Queue[Tuple[T, datetime]] = queue.Queue(maxsize=max_size)
        self._in_use: Set[int] = set()  # Track resources by id
        self._lock = threading.RLock()
        self._shutdown = False

    def acquire(self, timeout: float = 5.0) -> Optional[T]:
        """Acquire a resource from the pool."""
        if self._shutdown:
            return None

        with self._lock:
            # Try to get from pool
            while not self._pool.empty():
                try:
                    resource, last_used = self._pool.get_nowait()

                    # Check if resource is still valid
                    age = (datetime.now() - last_used).seconds
                    if age > self.max_idle_time:
                        # Resource too old, clean it up
                        if self.cleanup_func:
                            self.cleanup_func(resource)
                        continue

                    # Mark as in use
                    self._in_use.add(id(resource))
                    return resource

                except queue.Empty:
                    break

            # Create new resource if under limit
            if len(self._in_use) < self.max_size:
                try:
                    resource = self.factory()
                    self._in_use.add(id(resource))
                    return resource
                except Exception as e:
                    logger.error(f"Failed to create resource in {self.name}: {e}")
                    return None

        # Wait for resource to become available
        try:
            resource, _ = self._pool.get(timeout=timeout)
            with self._lock:
                self._in_use.add(id(resource))
            return resource
        except queue.Empty:
            logger.warning(f"Timeout acquiring resource from {self.name}")
            return None

    def release(self, resource: T):
        """Release a resource back to the pool."""
        if self._shutdown:
            if self.cleanup_func:
                self.cleanup_func(resource)
            return

        with self._lock:
            resource_id = id(resource)
            if resource_id not in self._in_use:
                logger.warning(f"Releasing resource not from pool: {self.name}")
                return

            self._in_use.discard(resource_id)

            try:
                self._pool.put_nowait((resource, datetime.now()))
            except queue.Full:
                # Pool is full, clean up resource
                if self.cleanup_func:
                    self.cleanup_func(resource)

    @contextlib.contextmanager
    def resource(self, timeout: float = 5.0):
        """Context manager for resource acquisition and release."""
        resource = self.acquire(timeout)
        if resource is None:
            raise RuntimeError(f"Failed to acquire resource from {self.name}")
        try:
            yield resource
        finally:
            self.release(resource)

    def cleanup_idle_resources(self):
        """Clean up idle resources."""
        with self._lock:
            cleaned = 0
            temp_items = []

            while not self._pool.empty():
                try:
                    resource, last_used = self._pool.get_nowait()
                    age = (datetime.now() - last_used).seconds

                    if age > self.max_idle_time:
                        if self.cleanup_func:
                            self.cleanup_func(resource)
                        cleaned += 1
                    else:
                        temp_items.append((resource, last_used))
                except queue.Empty:
                    break

            # Put back valid resources
            for item in temp_items:
                try:
                    self._pool.put_nowait(item)
                except queue.Full:
                    if self.cleanup_func:
                        self.cleanup_func(item[0])

            if cleaned > 0:
                logger.info(f"Cleaned {cleaned} idle resources from {self.name}")

    def shutdown(self):
        """Shutdown the pool and clean up all resources."""
        self._shutdown = True

        with self._lock:
            # Clean up pooled resources
            while not self._pool.empty():
                try:
                    resource, _ = self._pool.get_nowait()
                    if self.cleanup_func:
                        self.cleanup_func(resource)
                except queue.Empty:
                    break

            logger.info(f"Resource pool {self.name} shutdown complete")


def with_timeout(timeout: float):
    """Decorator to add timeout to functions."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout)

            if thread.is_alive():
                logger.error(f"Function {func.__name__} timed out after {timeout}s")
                raise TimeoutError(f"Function timed out after {timeout}s")

            if exception[0]:
                raise exception[0]

            return result[0]

        return wrapper

    return decorator


class AtomicCounter:
    """Thread-safe atomic counter."""

    def __init__(self, initial: int = 0):
        self._value = initial
        self._lock = threading.RLock()

    def increment(self, delta: int = 1) -> int:
        """Increment and return new value."""
        with self._lock:
            self._value += delta
            return self._value

    def decrement(self, delta: int = 1) -> int:
        """Decrement and return new value."""
        with self._lock:
            self._value -= delta
            return self._value

    def get(self) -> int:
        """Get current value."""
        with self._lock:
            return self._value

    def set(self, value: int):
        """Set value."""
        with self._lock:
            self._value = value

    def compare_and_swap(self, expected: int, new_value: int) -> bool:
        """Atomic compare and swap."""
        with self._lock:
            if self._value == expected:
                self._value = new_value
                return True
            return False
