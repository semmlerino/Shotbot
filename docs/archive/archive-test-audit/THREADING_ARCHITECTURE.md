# Threading Architecture Documentation

This document describes the threading architecture, deadlock prevention strategies, and best practices for the ShotBot application's concurrent components.

## Overview

ShotBot employs a sophisticated threading architecture to ensure thread safety, prevent deadlocks, and provide responsive user interaction. The architecture is built around several key components that work together to manage concurrent operations safely.

## Core Threading Components

### 1. ThreadSafeWorker Base Class
**File**: `thread_safe_worker.py`  
**Purpose**: Provides thread-safe lifecycle management for Qt workers

#### Key Features:
- **State Machine**: Enforces valid state transitions (CREATED → STARTING → RUNNING → STOPPING → STOPPED → DELETED)
- **Mutex Protection**: Uses `QMutex` for thread-safe state access
- **Signal Safety**: Emits signals outside mutex locks to prevent deadlocks
- **Graceful Shutdown**: Supports safe stop with timeout and interruption handling

#### State Transition Rules:
```
CREATED ──→ STARTING ──→ RUNNING ──→ STOPPING ──→ STOPPED ──→ DELETED
     │                      │            │
     └──────────────────────┴────────────┴──→ ERROR ──→ STOPPED
```

### 2. LauncherManager
**File**: `launcher_manager.py`  
**Purpose**: Manages concurrent launcher execution with thread-safe process tracking

#### Threading Features:
- **Atomic State Checking**: Prevents nested locking deadlocks
- **Worker Cleanup**: Thread-safe cleanup of finished workers
- **Process Pool Integration**: Manages process lifecycle safely
- **Cascading Prevention**: Prevents timer cascading in cleanup operations

### 3. CacheManager  
**File**: `cache_manager.py`  
**Purpose**: Thread-safe caching with memory management

#### Threading Features:
- **Instance Variables**: Each instance has separate locks (no shared class variables)
- **RLock Protection**: Uses `threading.RLock` for reentrant access
- **Completion Tracking**: Prevents multiple completion of cache results
- **Memory Limits**: Thread-safe memory usage tracking

## Lock Ordering Protocol

To prevent deadlocks, always acquire locks in the following order:

### Lock Hierarchy (High to Low Priority):
1. **`LauncherManager._process_lock`** (highest priority)
2. **`ThreadSafeWorker._state_mutex`** 
3. **`CacheManager._lock`**
4. **Qt Widget locks** (QMutex, etc.)
5. **Individual resource locks** (lowest priority)

### Rules:
- **Always acquire locks in order**: Never acquire a higher-priority lock while holding a lower-priority lock
- **Release immediately**: Release locks as soon as possible
- **Avoid nested locking**: Use atomic operations where possible

### Example - Correct Lock Ordering:
```python
# CORRECT: Acquire _process_lock first, then worker state
def _check_worker_state_atomic(self, worker_key: str) -> Tuple[str, bool]:
    # Step 1: Get worker reference with _process_lock
    with self._process_lock:
        worker = self._active_workers.get(worker_key)
        if not worker:
            return ("DELETED", False)
    
    # Step 2: Access worker state AFTER releasing _process_lock
    # This prevents nested locking: _process_lock → worker._state_mutex
    try:
        with QMutexLocker(worker._state_mutex):
            state = worker._state
            is_running = worker.isRunning()
            return (state.value, is_running)
    except Exception:
        return ("ERROR", False)
```

### Example - Incorrect Lock Ordering:
```python
# INCORRECT: This can cause deadlock!
def bad_state_check(self, worker_key: str):
    with self._process_lock:  # High priority lock
        worker = self._active_workers.get(worker_key)
        if worker:
            # DEADLOCK RISK: Still holding _process_lock while acquiring worker mutex
            with QMutexLocker(worker._state_mutex):  # Low priority lock
                return worker._state
```

## Signal Emission Rules

Qt signals must be emitted outside of mutex locks to prevent deadlocks.

### Signal Emission Pattern:
```python
def set_state(self, new_state: WorkerState) -> bool:
    signal_to_emit = None
    
    # Step 1: Determine signal inside mutex
    with QMutexLocker(self._state_mutex):
        self._state = new_state
        if new_state == WorkerState.STOPPED:
            signal_to_emit = self.worker_stopped
    
    # Step 2: Emit signal OUTSIDE mutex
    if signal_to_emit:
        QTimer.singleShot(0, signal_to_emit.emit)
    
    return True
```

### Why This Matters:
- Signal handlers may attempt to acquire locks
- Emitting inside mutex can cause circular waiting
- `QTimer.singleShot(0, ...)` queues emission for next event loop iteration

### Signal Safety Checklist:
- ✅ Determine which signal to emit inside mutex
- ✅ Store signal reference in local variable
- ✅ Release mutex before emission
- ✅ Use `QTimer.singleShot(0, signal.emit)` for thread safety
- ❌ Never call `signal.emit()` while holding mutex

## Worker Lifecycle Procedures

### Worker Creation:
1. Instantiate worker class (inherits from `ThreadSafeWorker`)
2. Connect signals using `safe_connect()` method
3. Set up any required parameters
4. Call `start()` to begin execution

### Worker Execution:
1. State transitions: CREATED → STARTING → RUNNING
2. `do_work()` method executes user code
3. Periodic checks of `should_stop()` for graceful interruption
4. Exception handling transitions to ERROR state

### Worker Shutdown:
1. Call `request_stop()` to signal shutdown
2. Worker transitions: RUNNING → STOPPING → STOPPED
3. Use `safe_wait()` to wait for completion
4. `disconnect_all()` cleans up signal connections
5. Final transition: STOPPED → DELETED

### Emergency Termination:
```python
# Graceful shutdown sequence
def shutdown_worker(worker):
    # Step 1: Request stop
    if worker.request_stop():
        # Step 2: Wait with timeout
        if worker.safe_wait(ThreadingConfig.WORKER_STOP_TIMEOUT_MS):
            return True  # Success
    
    # Step 3: Force termination if needed
    worker.safe_terminate()
    return False  # Had to force
```

## Deadlock Prevention Guidelines

### Common Deadlock Scenarios and Solutions:

#### 1. Nested Locking
**Problem**: Thread A holds Lock1, waits for Lock2. Thread B holds Lock2, waits for Lock1.
**Solution**: Always acquire locks in the same order (see Lock Ordering Protocol above).

#### 2. Signal Emission Deadlock
**Problem**: Emitting signal while holding mutex, signal handler tries to acquire same mutex.
**Solution**: Emit signals outside mutex using `QTimer.singleShot()`.

#### 3. Worker State Deadlock
**Problem**: Checking worker state while holding process lock causes nested locking.
**Solution**: Use atomic state checking pattern (release process lock before accessing worker mutex).

#### 4. Cleanup Race Conditions
**Problem**: Worker removed from tracking before being fully stopped.
**Solution**: Stop worker completely before removing from tracking dictionary.

### Deadlock Detection:
- Use thread sanitizer tools in development
- Add timeout mechanisms to all lock acquisitions
- Log lock acquisition/release for debugging
- Implement deadlock detection timeouts

### Prevention Strategies:
1. **Timeout Everything**: All lock acquisitions should have timeouts
2. **Atomic Operations**: Minimize critical sections
3. **Lock-Free Design**: Use atomic variables where possible
4. **Consistent Ordering**: Always acquire locks in the same order
5. **Quick Release**: Hold locks for minimum time necessary

## Threading Configuration

All threading-related constants are centralized in `ThreadingConfig` class:

```python
class ThreadingConfig:
    # Worker timeouts
    WORKER_STOP_TIMEOUT_MS = 2000
    WORKER_TERMINATE_TIMEOUT_MS = 1000
    WORKER_POLL_INTERVAL = 0.1
    
    # Cleanup timings
    CLEANUP_RETRY_DELAY_MS = 500
    CLEANUP_INITIAL_DELAY_MS = 1000
    
    # Process pool configuration
    SESSION_INIT_TIMEOUT = 2.0
    SESSION_MAX_RETRIES = 5
    SUBPROCESS_TIMEOUT = 30.0
    
    # Polling configuration
    INITIAL_POLL_INTERVAL = 0.01  # 10ms
    MAX_POLL_INTERVAL = 0.5       # 500ms
    POLL_BACKOFF_FACTOR = 1.5
    
    # Cache configuration
    CACHE_MAX_MEMORY_MB = 100
    CACHE_CLEANUP_INTERVAL = 30
    
    # Thread pool settings
    MAX_WORKER_THREADS = 4
    THREAD_POOL_TIMEOUT = 5.0
```

## Best Practices

### Thread Safety Patterns:

#### 1. Atomic State Checking:
```python
def check_worker_safely(self, worker_key: str):
    # Get reference with minimal lock scope
    with self._process_lock:
        worker = self._workers.get(worker_key)
        if not worker:
            return None
    
    # Access worker state outside of process lock
    return worker.get_state()
```

#### 2. Safe Resource Cleanup:
```python
def cleanup_worker(self, worker_key: str):
    with self._process_lock:
        worker = self._workers.get(worker_key)
        if not worker:
            return
        
        # Stop worker while still tracked
        if worker.isRunning():
            worker.safe_stop(ThreadingConfig.WORKER_STOP_TIMEOUT_MS)
        
        # Remove AFTER stopping
        self._workers.pop(worker_key, None)
        
    # Cleanup outside lock
    worker.disconnect_all()
    worker.deleteLater()
```

#### 3. Completion Prevention:
```python
class ThumbnailCacheResult:
    def __init__(self):
        self._completed = False
        self._completed_lock = threading.Lock()
    
    def complete(self, future, pixmap):
        with self._completed_lock:
            if self._completed:
                return  # Prevent multiple completion
            self._completed = True
            self.future = future
            self.pixmap = pixmap
```

### Code Review Checklist:

#### Threading Safety:
- [ ] All shared state protected by appropriate locks
- [ ] Lock ordering follows hierarchy
- [ ] Signals emitted outside of mutexes
- [ ] Timeouts used for all blocking operations
- [ ] Resources cleaned up properly
- [ ] No shared class variables between instances

#### Performance:
- [ ] Critical sections minimized
- [ ] Lock-free operations used where possible
- [ ] Exponential backoff for polling
- [ ] ThreadingConfig constants used instead of magic numbers

#### Error Handling:
- [ ] Exception handling doesn't leave locks held
- [ ] Graceful degradation on timeout
- [ ] Proper error state transitions
- [ ] Resource cleanup on all exit paths

## Debugging Threading Issues

### Tools and Techniques:

#### 1. Thread Sanitizer:
```bash
# Enable thread sanitizer (if available)
export TSAN_OPTIONS="detect_deadlocks=1:detect_lock_order_inversion=1"
python -m pytest tests/threading/
```

#### 2. Lock Debugging:
```python
# Add lock acquisition logging
def debug_lock_acquire(lock_name):
    logger.debug(f"Thread {threading.current_thread().name} acquiring {lock_name}")
    
def debug_lock_release(lock_name):
    logger.debug(f"Thread {threading.current_thread().name} releasing {lock_name}")
```

#### 3. Deadlock Detection:
```python
# Implement timeout-based deadlock detection
def safe_acquire_with_timeout(lock, timeout=5.0):
    if not lock.acquire(timeout=timeout):
        current_thread = threading.current_thread().name
        logger.error(f"Potential deadlock: {current_thread} couldn't acquire lock within {timeout}s")
        # Log stack trace, active threads, etc.
        return False
    return True
```

#### 4. State Tracking:
```python
# Track worker states for debugging
def log_worker_state_transition(worker_id, old_state, new_state):
    logger.debug(f"Worker {worker_id}: {old_state} → {new_state}")
```

## Integration Testing

### Thread Safety Tests:
- Concurrent worker creation/destruction
- Simultaneous cache operations
- Multiple cleanup operations
- Signal emission under load

### Stress Testing:
- High-frequency state transitions
- Memory pressure scenarios
- Timeout edge cases
- Resource exhaustion handling

### Performance Testing:
- Lock contention measurement
- Critical section timing
- Memory usage tracking
- CPU utilization monitoring

## Maintenance Guidelines

### Adding New Threading Components:
1. Follow existing patterns (inherit from ThreadSafeWorker if applicable)
2. Use ThreadingConfig constants
3. Implement proper lock ordering
4. Add comprehensive tests
5. Document threading implications

### Modifying Existing Components:
1. Verify lock ordering is maintained
2. Check signal emission safety
3. Update tests for new behavior
4. Review resource cleanup
5. Test under concurrent load

### Performance Optimization:
1. Profile lock contention
2. Minimize critical sections
3. Use atomic operations where possible
4. Implement lock-free algorithms when beneficial
5. Monitor memory usage patterns

## Known Issues and Limitations

### Current Limitations:
- Qt signal emission requires event loop integration
- Process termination can be delayed on some platforms
- Memory cleanup depends on Qt's garbage collection
- Some operations cannot be made fully atomic

### Future Improvements:
- Implement lock-free data structures for high-frequency operations
- Add comprehensive deadlock detection
- Optimize cache memory management
- Improve process lifecycle tracking

## References

### Threading Documentation:
- [Qt Threading Documentation](https://doc.qt.io/qt-6/thread-basics.html)
- [Python Threading Documentation](https://docs.python.org/3/library/threading.html)
- [PySide6 Threading Guide](https://doc.qt.io/qtforpython/overviews/threads-technologies.html)

### Deadlock Prevention:
- [Lock Ordering](https://en.wikipedia.org/wiki/Lock_ordering)
- [Banker's Algorithm](https://en.wikipedia.org/wiki/Banker%27s_algorithm)
- [Deadlock Prevention Strategies](https://www.geeksforgeeks.org/deadlock-prevention/)

### Testing Resources:
- [Thread Sanitizer](https://clang.llvm.org/docs/ThreadSanitizer.html)
- [Race Condition Detection](https://www.valgrind.org/docs/manual/hg-manual.html)
- [Concurrency Testing Best Practices](https://testing.googleblog.com/2008/06/taming-grizzly-bear.html)

---

*This document should be updated whenever threading-related changes are made to the codebase. All developers should be familiar with these guidelines before modifying concurrent code.*