# Qt Threading Fixes for ShotBot

## Critical Fixes Required

### 1. Fix Signal Emission Under Lock

**Problem**: Signals emitted while holding locks can cause deadlocks.

**Solution**: Collect data under lock, emit signals after releasing:

```python
# launcher_manager.py - Fix for lines 867-872
def execute_launcher(self, launcher_id: str, ...) -> bool:
    # Check limits and collect error info under lock
    error_msg = None
    with self._process_lock:
        if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
            error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
    
    # Emit signal OUTSIDE the lock
    if error_msg:
        logger.warning(error_msg)
        self.validation_error.emit("general", error_msg)
        return False
```

### 2. Fix Nested Lock Acquisition

**Problem**: Acquiring worker's mutex while holding process lock causes deadlocks.

**Solution**: Never hold multiple locks simultaneously:

```python
def _check_worker_state_atomic(self, worker_key: str) -> Tuple[str, bool]:
    """Check worker state without nested locking."""
    # Get worker reference and release lock immediately
    worker = None
    with self._process_lock:
        worker = self._active_workers.get(worker_key)
    
    if not worker:
        return ("DELETED", False)
    
    # Now access worker state without holding process lock
    try:
        state = worker.get_state()  # This internally uses QMutex safely
        is_running = worker.isRunning()
        return (state.value if hasattr(state, 'value') else str(state), is_running)
    except Exception as e:
        logger.error(f"Failed to check worker {worker_key}: {e}")
        return ("ERROR", False)
```

### 3. Fix Worker Lifecycle Race

**Problem**: Worker added to dict before starting can race with cleanup.

**Solution**: Start worker first, then add to tracking:

```python
def _execute_with_worker(self, launcher_id: str, ...) -> bool:
    try:
        # Create and configure worker
        worker = LauncherWorker(launcher_id, command, working_dir)
        worker_key = f"{launcher_id}_{int(time.time() * 1000)}"
        
        # Connect signals BEFORE starting
        worker.safe_connect(worker.command_started, ...)
        worker.safe_connect(worker.command_finished, self._on_worker_finished, ...)
        worker.safe_connect(worker.command_error, ...)
        
        # Start worker FIRST
        worker.start()
        
        # THEN add to tracking after successful start
        with self._process_lock:
            # Double-check worker is still running
            if worker.isRunning():
                self._active_workers[worker_key] = worker
            else:
                logger.warning(f"Worker {worker_key} stopped before tracking")
                return False
        
        return True
    except Exception as e:
        logger.error(f"Failed to start worker thread: {e}")
        self.execution_finished.emit(launcher_id, False)
        return False
```

### 4. Replace threading.RLock with QMutex

**Problem**: Mixing Python and Qt threading primitives.

**Solution**: Use Qt's threading primitives consistently:

```python
from PySide6.QtCore import QMutex, QMutexLocker, QRecursiveMutex

class LauncherManager(QObject):
    def __init__(self):
        super().__init__()
        # Replace threading.RLock with QRecursiveMutex
        self._process_mutex = QRecursiveMutex()  # Allows re-entrant locking
        self._cleanup_mutex = QMutex()
        
    def some_method(self):
        # Use QMutexLocker for RAII-style locking
        with QMutexLocker(self._process_mutex):
            # Critical section
            pass
```

### 5. Ensure Proper Thread Affinity

**Problem**: LauncherManager doesn't specify thread affinity.

**Solution**: Explicitly move to main thread:

```python
class LauncherManager(QObject):
    def __init__(self):
        super().__init__()
        # Ensure LauncherManager lives in main thread
        from PySide6.QtCore import QCoreApplication
        if QCoreApplication.instance():
            self.moveToThread(QCoreApplication.instance().thread())
```

### 6. Safe Worker Cleanup

**Problem**: Workers removed while potentially still emitting signals.

**Solution**: Ensure worker is fully stopped before removal:

```python
def _remove_worker_safe(self, worker_key: str):
    """Safely remove worker with proper Qt cleanup sequence."""
    worker = None
    with QMutexLocker(self._process_mutex):
        worker = self._active_workers.get(worker_key)
        if not worker:
            return
    
    # Stop worker outside the lock
    if worker.isRunning():
        logger.info(f"Stopping running worker {worker_key}")
        # Request stop and wait
        if worker.request_stop():
            if not worker.wait(ThreadingConfig.WORKER_STOP_TIMEOUT_MS):
                logger.warning(f"Worker {worker_key} didn't stop gracefully")
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(1000):
                    logger.error(f"Worker {worker_key} failed to stop")
    
    # Disconnect all signals before removal
    try:
        worker.disconnect_all()
    except:
        pass
    
    # NOW remove from tracking
    with QMutexLocker(self._process_mutex):
        self._active_workers.pop(worker_key, None)
    
    # Schedule for deletion via Qt's event loop
    worker.deleteLater()
```

## Implementation Priority

1. **IMMEDIATE**: Fix signal emission under lock (High deadlock risk)
2. **HIGH**: Fix nested lock acquisition pattern
3. **HIGH**: Fix worker lifecycle race condition
4. **MEDIUM**: Replace threading.RLock with QMutex
5. **MEDIUM**: Ensure proper thread affinity
6. **LOW**: Improve worker cleanup sequence

## Testing Recommendations

1. **Stress Test**: Launch 100+ concurrent workers rapidly
2. **Race Test**: Start and immediately stop workers in tight loop
3. **Deadlock Test**: Emit signals that trigger slots acquiring same locks
4. **Thread Sanitizer**: Run with Python's threading debug tools
5. **Qt Debug**: Enable Qt's thread checking with `QT_FATAL_WARNINGS=1`

## Signal Connection Best Practices

```python
# ALWAYS specify connection type for cross-thread signals
worker.signal.connect(
    self.slot,
    Qt.ConnectionType.QueuedConnection  # Explicit for thread safety
)

# For same-thread guaranteed connections
self.signal.connect(
    self.local_slot,
    Qt.ConnectionType.DirectConnection  # Only when SURE it's same thread
)

# For blocking cross-thread calls (use sparingly!)
result = worker.signal.connect(
    self.slot,
    Qt.ConnectionType.BlockingQueuedConnection  # Can deadlock!
)
```

## Qt Thread Affinity Rules

1. **Parent and child QObjects MUST live in same thread**
2. **QObjects created in worker thread have that thread's affinity**
3. **Use moveToThread() before connecting signals**
4. **Never move QObject with parent to another thread**
5. **QTimer, QThread cannot be moved after starting**