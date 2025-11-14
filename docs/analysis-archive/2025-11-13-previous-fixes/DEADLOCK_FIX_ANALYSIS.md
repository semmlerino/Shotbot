# Deadlock Fix Analysis - PersistentTerminalManager

## Executive Summary

**Issue**: Test suite hanging with deadlock in `persistent_terminal_manager.py`  
**Root Cause**: Nested lock acquisition using non-reentrant `threading.Lock()`  
**Fix**: Changed `_state_lock` from `threading.Lock()` to `threading.RLock()` at line 224  
**Result**: All 41 tests pass in 31 seconds (previously hanging indefinitely)

---

## Root Cause Analysis

### The Deadlock Pattern

**Thread**: Worker thread executing `_run_send_command()`

**Call Stack Leading to Deadlock**:
```python
1. _run_send_command() 
   → _ensure_dispatcher_healthy()
2. _ensure_dispatcher_healthy() 
   → _is_dispatcher_healthy()
3. _is_dispatcher_healthy() 
   → _is_dispatcher_alive()
4. _is_dispatcher_alive() [LINE 478]
   ↓ ACQUIRES _state_lock
   with self._state_lock:
       if self.dispatcher_pid is None:
           self.dispatcher_pid = self._find_dispatcher_pid()  # LINE 481
                                  ↓
5. _find_dispatcher_pid() [LINE 430]
   ↓ TRIES TO ACQUIRE _state_lock AGAIN
   with self._state_lock:  # DEADLOCK!
       terminal_pid = self.terminal_pid
```

### Why This Causes Deadlock

**Python's `threading.Lock()` is NOT reentrant**:
- A thread cannot acquire the same `Lock()` twice
- If a thread tries to acquire a lock it already holds, it **deadlocks with itself**
- The thread waits forever for itself to release the lock

**Code Location**:
```python
# persistent_terminal_manager.py, line 224 (BEFORE FIX)
self._state_lock = threading.Lock()  # Non-reentrant lock

# Line 478: _is_dispatcher_alive() acquires the lock
with self._state_lock:
    if self.dispatcher_pid is None:
        # Line 481: Calls _find_dispatcher_pid() WHILE HOLDING LOCK
        self.dispatcher_pid = self._find_dispatcher_pid()  # NESTED CALL
        
# Line 430: _find_dispatcher_pid() tries to acquire same lock
with self._state_lock:  # DEADLOCK - same thread, same lock, not reentrant!
    terminal_pid = self.terminal_pid
```

### Why Tests Were Hanging

**During test teardown**:
1. MainThread calls `cleanup()` 
2. `cleanup()` calls `worker.safe_stop(3000)` (blocks waiting for worker)
3. Worker thread is stuck in deadlock trying to acquire `_state_lock`
4. Worker never finishes, `safe_stop()` times out
5. Test hangs indefinitely

---

## The Fix

### Code Change

**File**: `persistent_terminal_manager.py`  
**Line**: 224  
**Change**: `threading.Lock()` → `threading.RLock()`

```python
# BEFORE (Line 224)
self._state_lock = threading.Lock()

# AFTER (Line 224)
self._state_lock = threading.RLock()
```

### Why RLock is the Correct Solution

**`threading.RLock()` (Reentrant Lock)**:
- **Allows same thread to acquire multiple times**
- Tracks acquisition count (must release same number of times)
- **Designed for exactly this use case** (method composition)
- Drop-in replacement for `Lock()` when reentrancy needed

**Benefits**:
1. **Enables natural method composition**: Methods can call each other safely
2. **Same thread safety**: Only the thread holding the lock can re-acquire it
3. **Standard Python pattern**: RLock is the standard solution for nested locking
4. **Minimal code change**: Single line, no architectural refactoring
5. **No side effects**: Maintains all thread-safety guarantees

**Performance**: RLock is slightly slower than Lock (~5-10%), but negligible for this use case (state protection, not hot path).

---

## Verification

### Test Results

```bash
cd ~/projects/shotbot
uv run pytest tests/unit/test_persistent_terminal_manager.py -xvs
```

**Results**:
- ✅ All 41 tests PASSED in 31.07 seconds
- ✅ No deadlocks or hangs
- ✅ No new type errors introduced
- ✅ Cleanup tests that were hanging now pass quickly

**Specific tests verified**:
- `test_cleanup_removes_fifo_and_closes_terminal` - Previously hung, now passes in <1s
- `test_send_command_with_auto_restart` - Previously hung, now passes in <1s
- `test_dispatcher_dead_terminal_alive_triggers_restart` - Previously hung, now passes in <1s

### Type Checking

```bash
uv run basedpyright persistent_terminal_manager.py
```

**Results**:
- ✅ 0 errors, 1 warning (pre-existing), 3 notes (pre-existing)
- ✅ No new type issues introduced

---

## Prevention Strategy

### Guidelines to Avoid Similar Issues

**1. Use RLock When Methods Call Each Other**:
```python
# GOOD: Use RLock for state that's accessed by methods calling each other
self._state_lock = threading.RLock()

def outer_method(self):
    with self._state_lock:
        self.inner_method()  # Safe with RLock
        
def inner_method(self):
    with self._state_lock:  # Same thread can re-acquire
        # Access state
        pass
```

**2. Extract Lock-Free Internal Methods**:
```python
# ALTERNATIVE: Create non-locking internal versions
def _find_dispatcher_pid(self):
    """Public method with lock."""
    with self._state_lock:
        return self._find_dispatcher_pid_unlocked()
        
def _find_dispatcher_pid_unlocked(self):
    """Internal method without lock (caller must hold lock)."""
    # Access state without acquiring lock
    pass
```

**3. Document Lock Acquisition Order**:
```python
# Document which locks a method acquires
def method_name(self):
    """Do something.
    
    Thread-Safe: Acquires _state_lock (reentrant safe).
    """
    with self._state_lock:
        # ...
```

**4. Use Lock Timeout for Debugging**:
```python
# During development, use timeout to detect deadlocks early
if not self._state_lock.acquire(timeout=5.0):
    self.logger.error("Deadlock detected!")
    raise RuntimeError("Lock acquisition timeout")
```

**5. Prefer RLock for State Protection**:
- **Use `Lock()`**: For simple mutual exclusion (e.g., FIFO writes)
- **Use `RLock()`**: For state protection across multiple methods
- **Rule of thumb**: If methods call each other, use RLock

### Testing for Deadlocks

**Add timeout to tests**:
```python
@pytest.mark.timeout(30)  # Fail after 30 seconds
def test_cleanup():
    # Test that might deadlock
    manager.cleanup()
```

**Use `pytest-timeout` plugin** (already configured):
```toml
# pyproject.toml
[tool.pytest.ini_options]
timeout = 120  # Global timeout for all tests
```

---

## Technical Details

### Lock Comparison

| Feature | `threading.Lock()` | `threading.RLock()` |
|---------|-------------------|---------------------|
| **Reentrant** | ❌ No | ✅ Yes |
| **Same thread re-acquire** | ❌ Deadlock | ✅ Safe |
| **Acquisition count** | Binary (0/1) | Counted (0/1/2/...) |
| **Performance** | Faster (~100ns) | Slightly slower (~110ns) |
| **Use case** | Simple mutual exclusion | Method composition |

### Why Non-Reentrant Locks Exist

**Design trade-off**:
- `Lock()` is simpler and faster (no acquisition counting)
- `RLock()` adds overhead but enables method composition
- Python provides both for different use cases

**When to use each**:
- `Lock()`: FIFO writes, simple counters, independent operations
- `RLock()`: State machines, method call chains, object state

---

## Related Code Patterns

### Other Locks in PersistentTerminalManager

**`_write_lock` (line 220)**: 
- Protects FIFO write operations
- Simple mutual exclusion (no method calls while holding lock)
- **Correctly uses `Lock()`** (no nested acquisition)

**`_workers_lock` (line 228)**:
- Protects worker list access
- Simple list operations only
- **Correctly uses `Lock()`** (no nested acquisition)

**`_state_lock` (line 224)**:
- Protects complex state (terminal_pid, dispatcher_pid, etc.)
- Methods call each other while holding lock
- **Now correctly uses `RLock()`** (allows nested acquisition)

---

## Conclusion

**The deadlock was caused by a classic nested lock acquisition pattern**:
1. Method A acquires lock, calls Method B
2. Method B tries to acquire same lock
3. Non-reentrant lock causes deadlock

**The fix is simple and correct**:
- Change `threading.Lock()` to `threading.RLock()`
- Allows same thread to re-acquire the lock safely
- Standard Python pattern for this exact scenario

**Impact**:
- ✅ All tests now pass without hanging
- ✅ No architectural changes needed
- ✅ No side effects or regressions
- ✅ Improved code robustness

**Prevention**:
- Use RLock for state protection when methods call each other
- Document lock acquisition patterns
- Use timeouts during development to detect deadlocks early

---

## File Modified

- `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py` (line 224)

## Tests Verified

- All 41 tests in `tests/unit/test_persistent_terminal_manager.py`
- Runtime: 31.07 seconds (previously hung indefinitely)
- Status: All PASSED ✅
