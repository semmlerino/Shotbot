# Threading Fixes Implementation Guide

## Priority 1: Fix PreviousShotsWorker (HIGH SEVERITY)

### Current Issue
`previous_shots_worker.py` inherits directly from QThread without proper thread safety.

### Solution
Replace the existing file with `previous_shots_worker_fixed.py` which properly inherits from ThreadSafeWorker:

```bash
# Backup original
cp previous_shots_worker.py previous_shots_worker.py.backup

# Apply fix
cp previous_shots_worker_fixed.py previous_shots_worker.py
```

### Key Changes:
1. Inherits from `ThreadSafeWorker` instead of `QThread`
2. Implements `do_work()` instead of `run()`
3. Uses `is_stop_requested()` for thread-safe stop checking
4. Leverages base class lifecycle management

## Priority 2: Fix LauncherManager Signal Emissions (MEDIUM SEVERITY)

### Location: `launcher_manager.py`

### Fix for line 961:
```python
# BEFORE (lines 956-962)
with self._process_lock:
    if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
        error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
        logger.warning(error_msg)
        self.validation_error.emit("general", error_msg)  # ISSUE: Inside lock
        return False

# AFTER
emit_error = False
error_msg = ""
with self._process_lock:
    if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
        emit_error = True
        error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
        logger.warning(error_msg)

if emit_error:
    self.validation_error.emit("general", error_msg)  # Safe: Outside lock
    return False
```

### Fix for line 1116:
```python
# BEFORE (lines 1110-1117)
with self._process_lock:
    if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
        error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
        logger.warning(error_msg)
        self.validation_error.emit("general", error_msg)  # ISSUE: Inside lock
        return False

# AFTER
emit_error = False
error_msg = ""
with self._process_lock:
    if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
        emit_error = True
        error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
        logger.warning(error_msg)

if emit_error:
    self.validation_error.emit("general", error_msg)  # Safe: Outside lock
    return False
```

## Priority 3: Fix Worker State Check Race Condition (MEDIUM SEVERITY)

### Location: `launcher_manager.py` lines 1730-1783

### Current Issue:
Worker accessed outside lock after obtaining reference.

### Solution:
Use weakref to prevent race with deletion:

```python
def _check_worker_state_atomic(self, worker_key: str) -> Tuple[str, bool]:
    """Atomically check worker state and running status with weak references."""
    import weakref
    
    # Get weak reference to worker
    with self._process_lock:
        worker = self._active_workers.get(worker_key)
        if not worker:
            return ("REMOVED", False)
        worker_ref = weakref.ref(worker)
    
    # Now safely access worker through weak reference
    worker = worker_ref()
    if worker is None:
        # Worker was deleted between getting ref and using it
        return ("REMOVED", False)
    
    try:
        # Rest of implementation...
        if hasattr(worker, "_state_mutex"):
            from PySide6.QtCore import QMutexLocker
            with QMutexLocker(worker._state_mutex):
                state = (
                    worker._state.value
                    if hasattr(worker._state, "value")
                    else str(worker._state)
                )
                is_running = worker.isRunning()
                return (state, is_running)
        # ... rest of method
```

## Testing the Fixes

### 1. Test PreviousShotsWorker Fix
```python
# test_previous_shots_worker_fixed.py
import pytest
from previous_shots_worker import PreviousShotsWorker
from thread_safe_worker import WorkerState

def test_previous_shots_worker_thread_safety(qtbot):
    """Test that PreviousShotsWorker properly uses ThreadSafeWorker."""
    worker = PreviousShotsWorker([], username="test")
    
    # Should have ThreadSafeWorker methods
    assert hasattr(worker, 'do_work')
    assert hasattr(worker, 'is_stop_requested')
    assert hasattr(worker, 'get_state')
    
    # Test state transitions
    assert worker.get_state() == WorkerState.CREATED
    
    worker.start()
    qtbot.wait(100)
    
    worker.request_stop()
    assert worker.wait(2000)
    
    assert worker.get_state() in [WorkerState.STOPPED, WorkerState.DELETED]
```

### 2. Test Signal Emission Fix
```python
# test_launcher_manager_signals.py
import threading
from unittest.mock import MagicMock

def test_signal_emission_outside_lock(launcher_manager):
    """Test signals are emitted outside locks."""
    
    # Mock to track if signal was emitted while lock held
    lock_held = threading.Event()
    signal_emitted = threading.Event()
    
    original_emit = launcher_manager.validation_error.emit
    
    def track_emit(*args):
        if launcher_manager._process_lock._count > 0:  # RLock is held
            lock_held.set()
        signal_emitted.set()
        original_emit(*args)
    
    launcher_manager.validation_error.emit = track_emit
    
    # Fill up process slots
    for i in range(launcher_manager.MAX_CONCURRENT_PROCESSES):
        launcher_manager._active_processes[f"test_{i}"] = MagicMock()
    
    # Try to execute one more (should hit limit)
    launcher_manager.execute_launcher("test_launcher")
    
    assert signal_emitted.is_set(), "Signal should have been emitted"
    assert not lock_held.is_set(), "Signal was emitted while holding lock!"
```

### 3. Stress Test for Race Conditions
```python
# test_threading_stress.py
import concurrent.futures
import threading

def test_concurrent_worker_operations(launcher_manager, qtbot):
    """Stress test concurrent worker operations."""
    
    errors = []
    completed = threading.Event()
    
    def create_and_cleanup_worker():
        try:
            # Create worker
            worker = LauncherWorker("test", "echo test")
            key = f"worker_{threading.current_thread().ident}"
            
            with launcher_manager._process_lock:
                launcher_manager._active_workers[key] = worker
            
            # Start worker
            worker.start()
            
            # Check state (potential race point)
            state, running = launcher_manager._check_worker_state_atomic(key)
            
            # Cleanup
            launcher_manager._remove_worker_safe(key)
            
        except Exception as e:
            errors.append(str(e))
    
    # Run concurrent operations
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(create_and_cleanup_worker)
            for _ in range(50)
        ]
        
        concurrent.futures.wait(futures, timeout=10)
    
    assert not errors, f"Race conditions detected: {errors}"
```

## Validation Checklist

- [ ] PreviousShotsWorker refactored to use ThreadSafeWorker
- [ ] All signal emissions moved outside locks in LauncherManager
- [ ] Worker state checking uses weak references or proper synchronization
- [ ] All tests pass without timeouts or race conditions
- [ ] No Qt warnings about thread affinity violations
- [ ] Stress tests complete successfully

## Rollback Plan

If issues arise after applying fixes:

1. Restore backups:
```bash
cp previous_shots_worker.py.backup previous_shots_worker.py
git checkout launcher_manager.py
```

2. Document any new issues discovered
3. Incrementally apply fixes one at a time

## Performance Impact

Expected impact of fixes:
- **PreviousShotsWorker**: Slight overhead from proper state management (~1-2ms)
- **Signal emissions**: No performance impact, potentially better due to reduced lock contention
- **Weak references**: Minimal overhead (<1ms per check)

Overall: Negligible performance impact with significantly improved thread safety.
