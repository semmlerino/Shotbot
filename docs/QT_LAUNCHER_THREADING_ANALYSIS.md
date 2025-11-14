# Qt Launcher/Terminal Threading Analysis

**Date**: 2025-01-14
**Scope**: Launcher and terminal system Qt-specific threading issues
**Status**: Analysis Complete

## Executive Summary

The launcher/terminal system has **excellent signal/slot connection safety** (Phase 3 fixes verified), but uses the **QThread subclassing anti-pattern** in 3 classes, which is against Qt best practices. All cross-thread signal connections correctly use `Qt.ConnectionType.QueuedConnection`. Minor object ownership issues exist but pose no immediate risk.

**Priority Ranking**:
1. **HIGH**: QThread subclassing anti-pattern (Issue #7) - Refactor to moveToThread() pattern
2. **LOW**: Object ownership (missing parent parameters) - Minor cleanup
3. **VERIFIED**: ConnectionType specifications (Issue #8) - Already fixed in Phase 3 ✅

---

## Files Analyzed

1. `persistent_terminal_manager.py` - Terminal session management with worker threads
2. `command_launcher.py` - Application launcher with signal connections
3. `launcher/worker.py` - Launcher worker thread implementation
4. `thread_safe_worker.py` - Base class for thread-safe workers

---

## Issue #1: QThread Subclassing Anti-Pattern (HIGH PRIORITY)

### What is the Anti-Pattern?

Qt documentation explicitly states: **"The simplest way to use QThread is to create a worker QObject subclass, then use QObject::moveToThread() to move the worker to the thread."**

Subclassing QThread and overriding run() is an outdated pattern that:
- Violates Qt's object model (QThread != worker)
- Complicates lifecycle management
- Makes signal/slot connections less obvious
- Reduces code reusability

### Classes Using Anti-Pattern

#### 1. TerminalOperationWorker (persistent_terminal_manager.py:46-179)

```python
class TerminalOperationWorker(QThread):  # ❌ Subclassing QThread
    def run(self) -> None:  # ❌ Overriding run()
        try:
            if self.operation == "health_check":
                self._run_health_check()
            elif self.operation == "send_command":
                self._run_send_command()
        except Exception as e:
            self.operation_finished.emit(False, f"Operation failed: {e!s}")
```

**Issues**:
- Direct QThread subclassing
- run() method override
- Worker thread emits manager's signals (lines 137, 172, 177)

**Current Safety**:
- ✅ Has parent parameter and proper Qt ownership
- ✅ Uses explicit ConnectionType.QueuedConnection for cross-thread signals
- ✅ Manager methods use internal locks for thread safety

#### 2. ThreadSafeWorker (thread_safe_worker.py:47-682)

```python
class ThreadSafeWorker(LoggingMixin, QThread):  # ❌ Subclassing QThread
    def run(self) -> None:  # ❌ Overriding run()
        if not self.set_state(WorkerState.STARTING):
            return
        # ... state machine logic ...
        self.do_work()  # Calls subclass implementation
```

**Issues**:
- Direct QThread subclassing
- run() method with complex state machine
- Base class for other workers (propagates anti-pattern)

**Current Safety**:
- ✅ Has parent parameter and proper Qt ownership
- ✅ Uses QMutex and QWaitCondition correctly
- ✅ Provides safe_connect() with default QueuedConnection

#### 3. LauncherWorker (launcher/worker.py:27-296)

```python
class LauncherWorker(ThreadSafeWorker):  # ❌ Inherits from QThread subclass
    def do_work(self) -> None:  # ❌ Called from run()
        # ... subprocess execution ...
```

**Issues**:
- Inherits anti-pattern from ThreadSafeWorker
- Couples subprocess management with thread lifecycle

**Current Safety**:
- ✅ Has parent parameter and proper Qt ownership
- ✅ Inherits thread-safe lifecycle from ThreadSafeWorker
- ✅ Proper subprocess cleanup in _cleanup_process()

### Why This Still Works

Despite using the anti-pattern, the code functions correctly because:
1. All signal connections use explicit ConnectionType.QueuedConnection ✅
2. Proper Qt parent-child ownership prevents premature deletion ✅
3. Manager methods use internal locks for thread safety ✅
4. No QObjects are created in worker threads ✅

However, the anti-pattern makes the code harder to maintain and understand.

---

## Issue #2: Signal ConnectionType Analysis (VERIFIED ✅)

### Cross-Thread Connections with Explicit ConnectionType

All cross-thread signal connections correctly specify `Qt.ConnectionType.QueuedConnection`:

#### PersistentTerminalManager (persistent_terminal_manager.py)

```python
# Line 1053: Worker progress signal
_ = worker.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)

# Lines 1054-1056: Worker completion signal
_ = worker.operation_finished.connect(
    self._on_async_command_finished, Qt.ConnectionType.QueuedConnection
)

# Line 1069: Cleanup signal
_ = worker.operation_finished.connect(cleanup_worker, Qt.ConnectionType.QueuedConnection)
```

#### CommandLauncher (command_launcher.py)

All ProcessExecutor signal connections use QueuedConnection (lines 128-173):

```python
# Lines 128-131
self.process_executor.execution_progress.connect(
    self._on_execution_progress, Qt.ConnectionType.QueuedConnection
)

# Lines 133-136
self.process_executor.execution_completed.connect(
    self._on_execution_completed, Qt.ConnectionType.QueuedConnection
)

# Lines 138-141
self.process_executor.execution_error.connect(
    self._on_execution_error, Qt.ConnectionType.QueuedConnection
)

# Persistent terminal signals (lines 147-173)
# All use Qt.ConnectionType.QueuedConnection
```

**Verdict**: ✅ **Phase 3 fixes are complete and correct.**

### Same-Thread Connections (AutoConnection is Fine)

```python
# thread_safe_worker.py:106 - QThread.finished to own slot
_ = self.finished.connect(self._on_finished)  # ✅ Same thread (AutoConnection → DirectConnection)

# thread_safe_worker.py:661 - QTimer.timeout in main thread
_ = cls._zombie_cleanup_timer.timeout.connect(cleanup_callback)  # ✅ Main thread (AutoConnection → DirectConnection)
```

These connections don't specify ConnectionType because they're guaranteed same-thread connections, where AutoConnection defaults to DirectConnection (which is correct and efficient).

---

## Issue #3: Object Ownership and Parent Parameters (LOW PRIORITY)

### Missing Parent Parameters

#### ThreadSafeWorker Zombie Cleanup Timer

```python
# thread_safe_worker.py:652
cls._zombie_cleanup_timer = QTimer()  # ❌ No parent
```

**Risk**: Low - Timer is class-level and lives for entire application lifetime.
**Fix**: Pass `QApplication.instance()` as parent for proper cleanup.

#### CommandLauncher Helper Objects

```python
# command_launcher.py:120-124
self.env_manager = EnvironmentManager()  # No parent
self.process_executor = ProcessExecutor(persistent_terminal, Config)  # No parent
self.nuke_handler = NukeLaunchRouter()  # No parent
```

**Risk**: Low - Objects are instance attributes and cleaned up with CommandLauncher.
**Fix**: Pass `self` as parent if these classes support it.

### Good Parent Usage Examples

```python
# persistent_terminal_manager.py:1046
worker = TerminalOperationWorker(self, "send_command", parent=self)  # ✅ Proper parent

# thread_safe_worker.py:96
super().__init__(parent)  # ✅ Parent passed to QThread
```

---

## Issue #4: Thread Affinity and Object Creation (GOOD ✅)

### No QObject Creation in Worker Threads

✅ **Verified**: No QObjects (QTimer, QThread, etc.) are created in worker run() methods.
✅ **Verified**: All QObjects are created in main thread or have correct thread affinity.

### Thread-Safe Manager Method Access

TerminalOperationWorker calls manager methods from worker thread:

```python
# persistent_terminal_manager.py:97, 103, 126, 150, 164
self.manager._is_dispatcher_healthy()  # Uses internal locks ✅
self.manager._ensure_dispatcher_healthy()  # Uses internal locks ✅
self.manager._send_command_direct(self.command)  # Uses _write_lock ✅
```

**Analysis**: These methods are explicitly designed for cross-thread use:
- Use `_write_lock` (RLock) to serialize FIFO writes
- Use `_state_lock` (Lock) to protect shared state
- Use `_restart_lock` (Lock) to serialize restart operations

Comments in code (lines 88-94, 111-117) document thread safety guarantees.

### Signal Emission from Worker Thread

```python
# persistent_terminal_manager.py:137, 172, 177
self.manager.command_executing.emit(timestamp)  # Worker emits manager signal
self.manager.command_verified.emit(timestamp, message)
self.manager.command_error.emit(timestamp, error)
```

**Analysis**: While this works (Qt auto-detects cross-thread and uses QueuedConnection), it's not ideal design:
- ❌ Worker is tightly coupled to manager's signal interface
- ❌ Makes testing and reusability harder
- ✅ Functionally correct due to Qt's automatic thread detection

**Better Design**: Worker should emit its own signals, manager should connect to them.

---

## Issue #5: Event Loop Integration (GOOD ✅)

### No processEvents() in Worker Threads

✅ **Verified**: No `QApplication.processEvents()` calls in worker thread run() methods.
✅ **Verified**: No `QEventLoop` creation in worker threads.

### Production processEvents() Usage

Only two production uses found:

1. **shot_model.py:819** - Inside `if __name__ == "__main__"` demo script ✅
2. **cleanup_manager.py:224** - Application shutdown cleanup (main thread) ✅

Both are acceptable single-threaded uses in main thread context.

### QTimer.singleShot Usage

```python
# command_launcher.py:452
QTimer.singleShot(100, partial(self.process_executor.verify_spawn, process, app_name))
```

✅ **Correct usage**: Callback runs in main thread, uses functools.partial for safe reference capture.

---

## Issue #6: Mutex and Synchronization Patterns (GOOD ✅)

### Correct QMutex Usage

```python
# thread_safe_worker.py:116
with QMutexLocker(self._state_mutex):
    return self._state
```

✅ **RAII pattern**: Uses QMutexLocker for automatic lock/unlock.
✅ **No deadlocks**: Lock ordering is consistent throughout code.
✅ **Recursive locks**: Uses `threading.RLock()` where re-acquisition needed.

### QWaitCondition Counter Pattern

```python
# thread_safe_worker.py:99
self._state_condition: QWaitCondition = QWaitCondition()

# Line 149
self._state_condition.wakeAll()
```

✅ **Correct usage**: Wakes waiting threads on state changes.
✅ **No lost wakeups**: State changes occur under mutex protection.

---

## Recommended Qt Threading Patterns

### Pattern 1: Worker Object with moveToThread() (RECOMMENDED)

This is the **Qt-recommended pattern** for background work:

```python
# Step 1: Create QObject-based worker class
class TerminalWorker(QObject):
    """Worker object for terminal operations (QObject, not QThread)."""

    # Signals
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, manager: PersistentTerminalManager, operation: str) -> None:
        super().__init__()  # No parent - will be moved to thread
        self.manager = manager
        self.operation = operation

    @Slot()
    def execute(self) -> None:
        """Entry point for work (called via signal from thread.started)."""
        try:
            if self.operation == "health_check":
                self._run_health_check()
            elif self.operation == "send_command":
                self._run_send_command()
        except Exception as e:
            self.finished.emit(False, f"Operation failed: {e!s}")

    def _run_health_check(self) -> None:
        # ... existing implementation ...
        pass

# Step 2: Use moveToThread() pattern
def send_command_async(self, command: str) -> None:
    # Create thread
    thread = QThread(parent=self)

    # Create worker (no parent - will be moved)
    worker = TerminalWorker(self, "send_command")
    worker.command = command

    # Move worker to thread BEFORE connecting signals
    worker.moveToThread(thread)

    # Connect lifecycle signals
    thread.started.connect(worker.execute, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(worker.deleteLater, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(thread.deleteLater, Qt.ConnectionType.QueuedConnection)

    # Connect progress signals
    worker.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)

    # Start thread (triggers thread.started → worker.execute)
    thread.start()
```

**Benefits**:
- ✅ Follows Qt best practices
- ✅ Clear separation: QThread = thread, QObject = worker
- ✅ Automatic cleanup via deleteLater
- ✅ Explicit signal connection lifecycle
- ✅ More testable (can test worker without thread)

### Pattern 2: Thread Pool with QRunnable (Alternative)

For simple tasks that don't need signals:

```python
from PySide6.QtCore import QRunnable, QThreadPool

class TerminalTask(QRunnable):
    def __init__(self, manager: PersistentTerminalManager, operation: str) -> None:
        super().__init__()
        self.manager = manager
        self.operation = operation

    def run(self) -> None:
        # Perform work
        pass

# Usage
pool = QThreadPool.globalInstance()
task = TerminalTask(manager, "health_check")
pool.start(task)
```

**When to use**:
- Simple fire-and-forget tasks
- No need for progress signals
- Want automatic thread pool management

**When NOT to use**:
- Need progress/completion signals (requires wrapper class)
- Need fine-grained lifecycle control
- Current TerminalOperationWorker has complex signal emission

---

## Step-by-Step Refactoring Guide

### Phase 1: Refactor TerminalOperationWorker (Highest Impact)

#### Step 1.1: Create New Worker Class

Create new file `terminal_worker.py`:

```python
from PySide6.QtCore import QObject, Signal, Slot
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persistent_terminal_manager import PersistentTerminalManager

class TerminalWorker(QObject):
    """Worker object for terminal operations (moveToThread pattern)."""

    # Signals
    progress = Signal(str)  # Status message
    finished = Signal(bool, str)  # success, message

    def __init__(self, manager: PersistentTerminalManager, operation: str) -> None:
        """Initialize worker.

        Args:
            manager: Terminal manager instance
            operation: Operation name ('health_check' or 'send_command')

        Note:
            Do not pass parent - worker will be moved to thread.
        """
        super().__init__()  # No parent
        self.manager = manager
        self.operation = operation
        self.command: str = ""  # For send_command operation

    @Slot()
    def execute(self) -> None:
        """Execute operation (entry point from thread.started signal)."""
        try:
            if self.operation == "health_check":
                self._run_health_check()
            elif self.operation == "send_command":
                self._run_send_command()
        except Exception as e:
            self.finished.emit(False, f"Operation failed: {e!s}")

    def _run_health_check(self) -> None:
        # ... copy from TerminalOperationWorker._run_health_check() ...
        pass

    def _run_send_command(self) -> None:
        # ... copy from TerminalOperationWorker._run_send_command() ...
        pass
```

#### Step 1.2: Update PersistentTerminalManager

```python
def send_command_async(self, command: str, ensure_terminal: bool = True) -> None:
    """Send command asynchronously using moveToThread pattern."""

    # Create thread with parent for automatic cleanup
    thread = QThread(parent=self)

    # Create worker (no parent - will be moved to thread)
    from terminal_worker import TerminalWorker
    worker = TerminalWorker(self, "send_command")
    worker.command = command

    # CRITICAL: Move worker to thread BEFORE connecting signals
    worker.moveToThread(thread)

    # Connect lifecycle signals (all QueuedConnection for cross-thread safety)
    thread.started.connect(worker.execute, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(worker.deleteLater, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(thread.deleteLater, Qt.ConnectionType.QueuedConnection)

    # Connect progress signals
    worker.progress.connect(
        lambda msg: self.operation_progress.emit("send_command", msg),
        Qt.ConnectionType.QueuedConnection
    )
    worker.finished.connect(
        self._on_async_command_finished,
        Qt.ConnectionType.QueuedConnection
    )

    # Store worker reference to prevent GC (thread-safe)
    with self._workers_lock:
        self._active_workers.append(worker)

    # Cleanup worker from list when finished
    def cleanup_worker() -> None:
        with self._workers_lock:
            if worker in self._active_workers:
                self._active_workers.remove(worker)

    worker.finished.connect(cleanup_worker, Qt.ConnectionType.QueuedConnection)

    # Emit queued signal
    timestamp = datetime.now().strftime("%H:%M:%S")
    self.command_queued.emit(timestamp, command)

    # Emit operation started signal
    self.operation_started.emit("send_command")

    # Start thread (triggers thread.started → worker.execute)
    thread.start()
```

#### Step 1.3: Update cleanup() Method

```python
def cleanup(self) -> None:
    """Clean up resources (workers, FIFO, terminal)."""

    # Stop all workers (threads will quit automatically via thread.quit)
    with self._workers_lock:
        workers_to_stop = list(self._active_workers)
        self._active_workers.clear()

    for worker in workers_to_stop:
        # Get worker's thread
        worker_thread = worker.thread()
        if worker_thread and worker_thread.isRunning():
            # Request worker to stop gracefully
            # (Worker should check for QThread.isInterruptionRequested())
            worker_thread.requestInterruption()

            # Wait for thread to finish
            if not worker_thread.wait(10000):  # 10 second timeout
                self.logger.error(
                    f"Worker thread did not stop after 10s. "
                    "Abandoning to prevent crashes."
                )

    # ... rest of cleanup (terminal, FIFO, etc.) ...
```

#### Step 1.4: Add Interruption Checks to Worker

```python
class TerminalWorker(QObject):
    def _run_send_command(self) -> None:
        """Run send command with interruption checks."""

        # Check for interruption
        if self.thread() and self.thread().isInterruptionRequested():
            self.finished.emit(False, "Operation interrupted")
            return

        # Ensure terminal healthy
        if not self.manager._ensure_dispatcher_healthy():
            self.finished.emit(False, "Terminal not healthy")
            return

        # Check for interruption again
        if self.thread() and self.thread().isInterruptionRequested():
            self.finished.emit(False, "Operation interrupted")
            return

        # Send command
        # ...
```

#### Step 1.5: Remove Old TerminalOperationWorker

After verifying new implementation:
1. Remove `TerminalOperationWorker` class from `persistent_terminal_manager.py`
2. Update all imports and references
3. Run full test suite to verify no regressions

### Phase 2: Refactor ThreadSafeWorker (Most Complex)

This is the most complex refactoring because ThreadSafeWorker is a base class with a state machine.

**Two Options**:

#### Option A: Convert to Composition Pattern

Create separate `WorkerThread` and `WorkerObject` classes:

```python
class WorkerThread(QThread):
    """Thread manager with lifecycle signals."""
    pass

class WorkerObject(QObject):
    """Worker object with state machine (moveToThread pattern)."""
    pass
```

#### Option B: Keep ThreadSafeWorker as Convenience Wrapper

Keep ThreadSafeWorker as a wrapper that creates thread + worker internally:

```python
class ThreadSafeWorker:
    """Convenience wrapper for thread + worker pattern."""

    def __init__(self, parent: QObject | None = None) -> None:
        self.thread = QThread(parent)
        self.worker = WorkerObject()
        self.worker.moveToThread(self.thread)
        # ... connect signals ...
```

**Recommendation**: Option B (wrapper) is less disruptive to existing code.

#### Step 2.1: Create WorkerObject Base Class

```python
class WorkerObject(LoggingMixin, QObject):
    """Base worker object with state machine (moveToThread pattern)."""

    # Lifecycle signals
    worker_started = Signal()
    worker_stopping = Signal()
    worker_stopped = Signal()
    worker_error = Signal(str)

    def __init__(self) -> None:
        """Initialize worker (no parent - will be moved to thread)."""
        super().__init__()  # No parent
        self._state_mutex = QMutex()
        self._state = WorkerState.CREATED
        self._stop_requested = False

    @Slot()
    def execute(self) -> None:
        """Main execution entry point (called from thread.started)."""
        # ... state machine logic ...
        try:
            self.do_work()
        except Exception as e:
            self.worker_error.emit(str(e))
        finally:
            self.worker_stopped.emit()

    def do_work(self) -> None:
        """Override in subclasses."""
        raise NotImplementedError
```

#### Step 2.2: Create ThreadSafeWorker Wrapper

```python
class ThreadSafeWorker:
    """Wrapper for thread + worker pattern."""

    def __init__(self, worker_class: type[WorkerObject], parent: QObject | None = None) -> None:
        self.thread = QThread(parent)
        self.worker = worker_class()

        # Move worker to thread
        self.worker.moveToThread(self.thread)

        # Connect lifecycle
        self.thread.started.connect(self.worker.execute, Qt.ConnectionType.QueuedConnection)
        self.worker.worker_stopped.connect(self.thread.quit, Qt.ConnectionType.QueuedConnection)
        self.worker.worker_stopped.connect(self.worker.deleteLater, Qt.ConnectionType.QueuedConnection)
        self.thread.finished.connect(self.thread.deleteLater, Qt.ConnectionType.QueuedConnection)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.worker.request_stop()
```

#### Step 2.3: Update LauncherWorker

```python
class LauncherWorkerObject(WorkerObject):
    """Launcher worker using moveToThread pattern."""

    # Signals
    command_started = Signal(str, str)
    command_finished = Signal(str, bool, int)
    command_error = Signal(str, str)

    def __init__(self, launcher_id: str, command: str, working_dir: str | None = None) -> None:
        super().__init__()  # No parent
        self.launcher_id = launcher_id
        self.command = command
        self.working_dir = working_dir

    def do_work(self) -> None:
        """Execute launcher command."""
        # ... existing LauncherWorker.do_work() logic ...
```

### Phase 3: Testing and Validation

After each refactoring phase:

1. **Unit Tests**: Test worker object independently of threading
2. **Integration Tests**: Test full moveToThread() pattern
3. **Manual Testing**: Verify no UI freezing or deadlocks
4. **Performance Testing**: Compare with old implementation

---

## Migration Checklist

- [ ] Phase 1: Refactor TerminalOperationWorker
  - [ ] Create TerminalWorker (QObject)
  - [ ] Update PersistentTerminalManager.send_command_async()
  - [ ] Update cleanup() method
  - [ ] Add interruption checks
  - [ ] Remove old TerminalOperationWorker
  - [ ] Run tests: `~/.local/bin/uv run pytest tests/unit/test_persistent_terminal.py -v`

- [ ] Phase 2: Refactor ThreadSafeWorker
  - [ ] Create WorkerObject base class
  - [ ] Create ThreadSafeWorker wrapper
  - [ ] Update LauncherWorker
  - [ ] Run tests: `~/.local/bin/uv run pytest tests/unit/test_launcher_worker.py -v`

- [ ] Phase 3: Testing and Validation
  - [ ] Full test suite: `~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup`
  - [ ] Type checking: `~/.local/bin/uv run basedpyright`
  - [ ] Manual testing: Launch apps via GUI and verify responsiveness
  - [ ] Performance comparison: Measure thread creation/cleanup times

---

## Risk Assessment

### Low Risk

- ✅ All signal connections use QueuedConnection
- ✅ No QObjects created in worker threads
- ✅ Manager methods use proper locks
- ✅ Parent-child ownership prevents crashes

### Medium Risk (Anti-Pattern)

- ⚠️ QThread subclassing makes code harder to maintain
- ⚠️ Worker emitting manager signals couples implementation
- ⚠️ Refactoring requires careful testing

### Mitigation

- Use incremental refactoring (one class at a time)
- Keep old implementation until new version is fully tested
- Add comprehensive tests before refactoring
- Monitor for regressions in parallel test runs

---

## Conclusion

The launcher/terminal system is **functionally correct** despite using the QThread subclassing anti-pattern. Phase 3 signal connection fixes are **complete and verified**. The primary improvement is refactoring to the moveToThread() pattern, which will:

1. **Improve maintainability**: Clear separation between thread and worker
2. **Follow Qt best practices**: Align with official Qt documentation
3. **Enhance testability**: Worker objects can be tested without threading
4. **Reduce coupling**: Workers won't need to emit manager signals

**Recommended Priority**: Refactor during next major feature work, not as urgent hotfix.

---

## References

- [Qt QThread Documentation](https://doc.qt.io/qt-6/qthread.html)
- [Qt Threading Basics](https://doc.qt.io/qt-6/threads-technologies.html)
- [Qt QObject::moveToThread()](https://doc.qt.io/qt-6/qobject.html#moveToThread)
- [PySide6 Threading Example](https://doc.qt.io/qtforpython-6/examples/example_threads_qthreadpool.html)
