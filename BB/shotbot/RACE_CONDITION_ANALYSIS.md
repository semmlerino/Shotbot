# Race Condition Analysis and Fix for launcher_manager.py

## Executive Summary

Fixed critical race conditions in `launcher_manager.py` that caused "dictionary changed size during iteration" errors. The root cause was iterating over mutable dictionaries while performing blocking operations that released the GIL, allowing concurrent modifications.

## Root Cause Analysis

### 1. Primary Race Condition (Lines 1425, 1137, 1177)

**Problem**: Direct iteration over dictionary items while performing blocking operations
```python
# BEFORE (BROKEN):
with self._process_lock:
    for worker_key, worker in self._active_workers.items():  # Direct iteration
        worker.wait(100)  # Blocking operation releases GIL!
        # Another thread can modify _active_workers here
```

**Race Timeline**:
1. Thread A acquires lock and starts iterating over dictionary
2. Thread A calls `worker.wait()` which releases the GIL
3. Thread B acquires lock and modifies dictionary
4. Thread A resumes with invalidated iterator → **RuntimeError**

### 2. Lock Scope Issues

**Problem**: Holding locks during blocking I/O operations
- `worker.wait(100)` - blocks for up to 100ms
- `worker.wait(500)` - blocks for up to 500ms
- `process.poll()` - can block on system calls

### 3. Multiple Concurrent Entry Points

**Problem**: Cleanup triggered from multiple sources simultaneously:
- QTimer.singleShot (Qt event loop thread)
- Periodic timer (every 30 seconds)
- get_active_process_count() (UI thread)
- get_active_process_info() (UI thread)
- _on_worker_finished() (worker thread signals)

### 4. Nested Cleanup Calls

**Problem**: `_periodic_cleanup()` was calling both cleanup methods while holding the lock:
```python
# BEFORE (BROKEN):
with self._process_lock:
    self._cleanup_finished_processes()  # Could block
    self._cleanup_finished_workers()    # Could block
```

## Solution Implementation

### Fix 1: Snapshot Pattern for Safe Iteration

**Principle**: Create a snapshot of the dictionary before iteration
```python
# AFTER (FIXED):
# Step 1: Take snapshot with lock
with self._process_lock:
    workers_to_check = dict(self._active_workers)  # Snapshot

# Step 2: Iterate over snapshot (no lock needed)
for worker_key, worker in workers_to_check.items():
    # Safe to do blocking operations here
    worker.wait(100)

# Step 3: Modify original dictionary with lock
with self._process_lock:
    for key in finished_workers:
        if key in self._active_workers:
            del self._active_workers[key]
```

### Fix 2: Prevent Concurrent Cleanup

**Added cleanup synchronization**:
```python
self._cleanup_in_progress = threading.Event()

def _cleanup_finished_workers(self):
    if self._cleanup_in_progress.is_set():
        return  # Skip if cleanup already running
    
    self._cleanup_in_progress.set()
    try:
        # Do cleanup
    finally:
        self._cleanup_in_progress.clear()
```

### Fix 3: Minimize Lock Hold Time

**Principle**: Never hold locks during blocking operations
- Take snapshot with lock
- Release lock for blocking operations
- Re-acquire lock for modifications

### Fix 4: Proper Lock Granularity

**Changed nested calls to independent operations**:
```python
# AFTER (FIXED):
def _periodic_cleanup(self):
    # Each method handles its own locking
    self._cleanup_finished_processes()
    self._cleanup_finished_workers()
    
    # Separate lock scope for old entries
    with self._process_lock:
        processes_snapshot = list(self._active_processes.items())
```

## Applied Changes

### Modified Methods

1. **`_cleanup_finished_workers()`** (Lines 1434-1500)
   - Added cleanup synchronization flag
   - Implemented 3-phase cleanup (snapshot, check, modify)
   - Moved blocking operations outside lock

2. **`_cleanup_finished_processes()`** (Lines 1129-1159)
   - Implemented snapshot pattern
   - Separated checking from modification

3. **`_periodic_cleanup()`** (Lines 1165-1215)
   - Removed nested lock acquisition
   - Fixed indentation and structure
   - Each cleanup handles own locking

4. **`stop_all_workers()`** (Lines 1487-1498)
   - Snapshot workers before stopping
   - Blocking operations outside lock

5. **`get_active_process_count()`** (Lines 1216-1227)
   - Cleanup calls moved outside lock
   - Return statement uses separate lock

6. **`get_active_process_info()`** (Lines 1229-1259)
   - Cleanup call moved outside lock
   - Info gathering uses separate lock

## Testing

Created `test_race_condition_fix.py` to verify:
1. Concurrent execution and cleanup operations
2. Dictionary iteration safety during modifications
3. Multiple simultaneous cleanup triggers
4. Qt timer and thread interactions

## Performance Impact

- **Minimal overhead**: Snapshot creation is O(n) but dictionaries are small (<100 entries)
- **Better concurrency**: Reduced lock contention by minimizing hold time
- **Prevented deadlocks**: No blocking operations while holding locks

## Recommendations

1. **Code Review**: Review all dictionary iterations in the codebase
2. **Testing**: Run stress tests under high concurrency
3. **Monitoring**: Add metrics for cleanup frequency and duration
4. **Documentation**: Document threading model and lock hierarchy

## Conclusion

The race conditions have been successfully eliminated by:
1. Using snapshot pattern for safe iteration
2. Preventing concurrent cleanup operations
3. Minimizing lock hold time
4. Proper lock granularity

The solution maintains thread safety while improving concurrency and preventing the "dictionary changed size during iteration" errors.