# Threading Analysis Report: Launcher & Terminal Management Systems

**Generated**: 2025-11-14  
**Analyzer**: threading-debugger agent  
**Scope**: PersistentTerminalManager, ThreadSafeWorker, SimplifiedLauncher, LauncherManager, ProcessExecutor

---

## Executive Summary

Comprehensive analysis of threading patterns across 5 launcher/terminal components (3,984 total lines) reveals **good overall thread safety** with several **previously-fixed issues well-documented** and **2 medium-severity recommendations** for improvement.

**Key Findings**:
- ✅ Most critical threading issues have been **fixed and documented**
- ⚠️ **1 nested lock pattern** poses future deadlock risk
- ⚠️ **1 missing explicit connection type** could cause cross-thread issues
- ✅ Excellent use of snapshot pattern, RLock, and signal emission outside locks

---

## 1. Thread Safety Issues

### 1.1 ✅ FIXED: Signal Emission Under Lock (Deadlock Prevention)

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:888-932`

**Original Issue**: Emitting Qt signals while holding `_write_lock` could deadlock if a connected slot tried to call `send_command()` again.

**Fix Applied** (Line 930-933):
```python
# FIXED: Emit signal OUTSIDE lock to prevent deadlock
if command_sent_successfully:
    self.command_sent.emit(command)
    return True
```

**Verification**: Signal now emitted after releasing lock. Comment at line 888-891 documents the fix.

**Severity**: Was CRITICAL, now RESOLVED ✅

---

### 1.2 ✅ FIXED: Cache Access Without Lock

**File**: `/home/gabrielh/projects/shotbot/simplified_launcher.py:736-744`

**Original Issue**: Concurrent cache modifications could corrupt `_ws_cache` dictionary.

**Fix Applied** (Line 737-744):
```python
# FIXED: Protect cache access with lock to prevent race conditions
# Multiple threads could be modifying _ws_cache concurrently
with self._cache_lock:
    keys_to_remove = [k for k in self._ws_cache if pattern in k]
    for key in keys_to_remove:
        del self._ws_cache[key]
```

**Verification**: Comment documents the fix at line 737-738.

**Severity**: Was HIGH, now RESOLVED ✅

---

### 1.3 ⚠️ MEDIUM: Nested Lock Acquisition Risk

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:871-928`

**Issue**: `send_command()` acquires `_write_lock` (line 871), then acquires `_state_lock` (line 911) while still holding the first lock.

**Code Pattern**:
```python
with self._write_lock:  # Line 871
    # ... FIFO operations ...
    
    # Line 911: Nested lock acquisition
    with self._state_lock:
        self.dispatcher_pid = None
```

**Deadlock Scenario**: If future code introduces `_state_lock` → `_write_lock` ordering, classic AB-BA deadlock will occur.

**Current Status**: No deadlock now (no inverse ordering exists), but risky pattern.

**Lock Inventory**:
- `_write_lock`: threading.Lock (line 220) - Serializes FIFO writes
- `_state_lock`: threading.RLock (line 224) - Protects shared state (terminal_pid, dispatcher_pid, etc.)
- `_workers_lock`: threading.Lock (line 228) - Protects worker list

**Recommendation**:
```python
# OPTION 1: Snapshot under _state_lock, then use outside
with self._state_lock:
    dispatcher_pid_snapshot = self.dispatcher_pid

with self._write_lock:
    # Use snapshot instead of accessing shared state
    if dispatcher_pid_snapshot is None:
        # handle...
```

**Severity**: MEDIUM (no current deadlock, but future maintainability risk)

**Code Location**: persistent_terminal_manager.py:911

---

## 2. Deadlock Potential

### 2.1 ✅ FIXED: Zombie Cleanup Recursive Mutex Deadlock

**File**: `/home/gabrielh/projects/shotbot/thread_safe_worker.py:563-573`

**Original Issue**: Calling `cleanup_old_zombies()` from within `_state_mutex` critical section would deadlock (non-recursive mutex).

**Fix Applied** (Line 568-570):
```python
# FIXED: Don't call cleanup_old_zombies() from within mutex (DEADLOCK!)
# QMutex is NOT recursive - cleanup_old_zombies() tries to acquire
# the same mutex again → deadlock. Let periodic cleanup handle it.
```

**Verification**: Comment documents the fix. `cleanup_old_zombies()` is only called via periodic timer (line 657).

**Severity**: Was CRITICAL, now RESOLVED ✅

---

### 2.2 ✅ CORRECT: Signal Emission Outside Mutex

**File**: `/home/gabrielh/projects/shotbot/thread_safe_worker.py:129-169`

**Pattern**: `set_state()` collects signals to emit while holding mutex, then emits OUTSIDE mutex.

**Code**:
```python
signal_to_emit = None

with QMutexLocker(self._state_mutex):
    # ... state transition ...
    if new_state == WorkerState.STOPPED:
        signal_to_emit = self.worker_stopped

# Emit signals outside the mutex to prevent deadlock
if signal_to_emit:
    signal_to_emit.emit()
```

**Verification**: Same pattern used in `request_stop()` (lines 208-212).

**Severity**: GOOD PRACTICE ✅

---

## 3. Race Conditions

### 3.1 ✅ FIXED: FIFO Recreation Race Condition

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:1248-1286`

**Original Issue**: Multiple threads calling `restart_terminal()` concurrently could create conflicting temporary FIFOs with same name.

**Fix Applied** (Line 1248-1251):
```python
# FIX: Add thread ID and timestamp to prevent temp FIFO name collisions
# Multiple threads can call restart_terminal() concurrently with same PID
temp_fifo = f"{self.fifo_path}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
```

**Verification**: Temp FIFO includes thread ID + nanosecond timestamp for uniqueness.

**Severity**: Was HIGH, now RESOLVED ✅

---

### 3.2 ✅ FIXED: Worker FIFO Access Race

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:1233-1246`

**Original Issue**: Deleting FIFO while workers are writing to it causes OSError in worker threads.

**Fix Applied** (Line 1233-1236):
```python
# FIXED: Stop all active workers BEFORE deleting FIFO
# Workers may be writing to FIFO - deleting it causes OSError in worker threads
with self._workers_lock:
    workers_to_stop = list(self._active_workers)
```

**Verification**: Workers stopped (lines 1241-1245) before FIFO deletion (line 1258).

**Severity**: Was HIGH, now RESOLVED ✅

---

### 3.3 ✅ CORRECT: Snapshot Pattern for Shared State

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:429-436`

**Pattern**: Snapshot shared state under lock, then use snapshot outside lock.

**Code**:
```python
# Snapshot terminal_pid under lock
with self._state_lock:
    terminal_pid = self.terminal_pid

if terminal_pid is None:
    return None
```

**Verification**: Pattern used throughout (e.g., line 405 `_is_terminal_alive()`, line 813 `send_command()`).

**Severity**: GOOD PRACTICE ✅

---

### 3.4 ⚠️ LOW: TOCTOU in Health Checks

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:588-610`

**Issue**: Multi-step health check is not atomic:

```python
# Check 1: Dispatcher process exists
if not self._is_dispatcher_alive():  # Line 588
    return False

# Check 2: FIFO has reader (dispatcher could crash here)
if not self._is_dispatcher_running():  # Line 593
    return False

# Check 3: Recent heartbeat
```

**Impact**: Dispatcher could crash between checks, causing false positive.

**Mitigation**: Health checks are informational, not critical for safety. False positives are acceptable.

**Recommendation**: Document this is a best-effort check, not atomic.

**Severity**: LOW (acceptable for health checks)

---

## 4. Thread Lifecycle Issues

### 4.1 ✅ CORRECT: QThread Parent Parameter

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:974-977`

**Pattern**: Worker created with `parent=None` per Qt documentation.

**Code**:
```python
# FIXED: QThread objects should NOT have a parent when running in different thread
# Qt docs: "QThread objects should not have a parent" - causes crashes during cleanup
# Worker is tracked in _active_workers to prevent garbage collection
worker = TerminalOperationWorker(self, "send_command", parent=None)
```

**Verification**: Worker tracked in `_active_workers` (line 992-993) to prevent GC.

**Severity**: CORRECT ✅

---

### 4.2 ✅ CORRECT: Worker State Machine

**File**: `/home/gabrielh/projects/shotbot/thread_safe_worker.py:316-380`

**Pattern**: State transitions handle race conditions gracefully.

**Race Scenario**: `request_stop()` called during STARTING state.

**Handling**:
```python
# run() tries to transition to RUNNING
if not self.set_state(WorkerState.RUNNING):  # Line 335
    self.logger.error(f"Worker {id(self)}: Failed to transition to RUNNING")
    _ = self.set_state(WorkerState.STOPPED)  # Line 337
    return
```

**Verification**: Failed transition detected and handled (line 337-338).

**Severity**: CORRECT ✅

---

### 4.3 ✅ CORRECT: Worker Cleanup with Closure Capture

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:998-1014`

**Pattern**: Cleanup function captures worker reference via closure (not `sender()`).

**Code**:
```python
# FIX: Use closure to capture worker reference instead of sender()
# sender() can return None if Qt object deleted before signal delivery
def cleanup_worker() -> None:
    """Cleanup specific worker using closure-captured reference."""
    with self._workers_lock:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
```

**Verification**: Comment at line 996-997 documents the fix.

**Severity**: CORRECT ✅

---

## 5. Signal/Slot Thread Safety

### 5.1 ✅ CORRECT: Explicit QueuedConnection for Workers

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:981-989`

**Pattern**: Explicit `Qt.ConnectionType.QueuedConnection` for cross-thread signals.

**Code**:
```python
# FIX: Use explicit QueuedConnection for cross-thread signals to prevent DirectConnection
# Without explicit type, Qt AutoConnection can pick DirectConnection causing crashes/deadlocks
_ = worker.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)
_ = worker.operation_finished.connect(
    self._on_async_command_finished, Qt.ConnectionType.QueuedConnection
)
```

**Verification**: Comment at line 981-983 documents the rationale.

**Severity**: CORRECT ✅

---

### 5.2 ⚠️ MEDIUM: Missing Explicit Connection Type

**File**: `/home/gabrielh/projects/shotbot/launch/process_executor.py:84-90`

**Issue**: Signal connections use implicit AutoConnection instead of explicit QueuedConnection.

**Code**:
```python
if self.persistent_terminal:
    _ = self.persistent_terminal.operation_progress.connect(
        self._on_terminal_progress  # ❌ No explicit connection type
    )
    _ = self.persistent_terminal.command_result.connect(
        self._on_terminal_command_result  # ❌ No explicit connection type
    )
```

**Risk**: If signals emitted from worker threads, AutoConnection may choose DirectConnection instead of QueuedConnection, causing cross-thread slot execution.

**Recommendation**:
```python
_ = self.persistent_terminal.operation_progress.connect(
    self._on_terminal_progress,
    Qt.ConnectionType.QueuedConnection  # ✅ Explicit cross-thread connection
)
```

**Severity**: MEDIUM (Qt AutoConnection usually works, but explicit is safer)

**Code Location**: launch/process_executor.py:85, 88

---

### 5.3 ✅ CORRECT: Connection Deduplication

**File**: `/home/gabrielh/projects/shotbot/thread_safe_worker.py:243-281`

**Pattern**: `safe_connect()` prevents duplicate connections with mutex protection.

**Code**:
```python
# CRITICAL: Atomic check-and-add using mutex to prevent race conditions
with QMutexLocker(self._state_mutex):
    # Prevent duplicate connections at application level
    if connection in self._connections:
        self.logger.debug(
            f"Worker {id(self)}: Skipped duplicate connection for {slot.__name__}"
        )
        return
    
    self._connections.append(connection)
```

**Verification**: Check-and-add is atomic (line 264-272).

**Severity**: CORRECT ✅

---

## 6. Resource Management

### 6.1 ✅ CORRECT: File Descriptor Leak Prevention

**File**: `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py:647-672`

**Pattern**: Track FD before `fdopen()` takes ownership, cleanup on error.

**Code**:
```python
fd = None  # Track FD for cleanup in case of errors
try:
    with self._write_lock:
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "wb", buffering=0) as fifo:
            fd = None  # fdopen took ownership, clear reference
            # ... write operations ...
    return True
except OSError as e:
    # ✅ Clean up fd if fdopen() never took ownership
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
```

**Verification**: Comment at line 638 documents "No file descriptor leaks in any error path".

**Severity**: CORRECT ✅

---

### 6.2 ✅ CORRECT: Subprocess Resource Cleanup

**File**: `/home/gabrielh/projects/shotbot/simplified_launcher.py:601-612`

**Pattern**: Explicitly call `proc.close()` to release file descriptors.

**Code**:
```python
with self._process_lock:
    for pid in finished_pids:
        if pid in self._active_processes:
            proc = self._active_processes[pid]
            del self._active_processes[pid]
            try:
                proc.close()  # ✅ Close subprocess to release file descriptors
            except Exception:
                pass
```

**Severity**: CORRECT ✅

---

### 6.3 ✅ ACCEPTABLE: Zombie Thread Management

**File**: `/home/gabrielh/projects/shotbot/thread_safe_worker.py:563-582`

**Pattern**: Collect abandoned threads to prevent "QThread destroyed while running" crashes.

**Code**:
```python
# Add to class-level collection to prevent garbage collection
with QMutexLocker(ThreadSafeWorker._zombie_mutex):
    ThreadSafeWorker._zombie_threads.append(self)
    ThreadSafeWorker._zombie_timestamps[id(self)] = time.time()
```

**Cleanup**: Periodic timer (line 652-667) runs `cleanup_old_zombies()` every 60s to remove finished threads.

**Memory Leak Risk**: Bounded - only accumulates truly stuck threads (rare).

**Severity**: ACCEPTABLE ✅

---

## 7. Summary of Recommendations

### Critical (Must Fix)
**None** - All critical issues have been fixed.

---

### High Priority (Should Fix)
**None** - All high-priority issues have been fixed.

---

### Medium Priority (Recommended)

1. **Eliminate Nested Lock Acquisition** (persistent_terminal_manager.py:911)
   - **Risk**: Future code could introduce deadlock
   - **Fix**: Use snapshot pattern instead of nested locks
   - **Effort**: 1-2 hours

2. **Add Explicit QueuedConnection** (launch/process_executor.py:85, 88)
   - **Risk**: AutoConnection may choose DirectConnection for worker signals
   - **Fix**: Add `Qt.ConnectionType.QueuedConnection` parameter
   - **Effort**: 5 minutes

---

### Low Priority (Nice to Have)

1. **Document TOCTOU in Health Checks** (persistent_terminal_manager.py:588)
   - Add comment explaining non-atomic health checks are acceptable
   - **Effort**: 5 minutes

---

## 8. Good Practices Identified

The codebase demonstrates **excellent threading practices**:

1. ✅ **Signal Emission Outside Locks** (persistent_terminal_manager.py:930, thread_safe_worker.py:158-168)
2. ✅ **Snapshot Pattern for Shared State** (persistent_terminal_manager.py:405, 431, 813)
3. ✅ **RLock for Re-entrant Operations** (_state_lock in persistent_terminal_manager.py:224)
4. ✅ **Explicit QueuedConnection for Workers** (persistent_terminal_manager.py:986)
5. ✅ **Worker Reference Tracking** (persistent_terminal_manager.py:992)
6. ✅ **FD Leak Prevention** (persistent_terminal_manager.py:659)
7. ✅ **Comprehensive Fix Documentation** (Comments explain WHY fixes were needed)
8. ✅ **QThread Parent Handling** (persistent_terminal_manager.py:977)
9. ✅ **Zombie Thread Management** (thread_safe_worker.py:589-667)
10. ✅ **Connection Deduplication** (thread_safe_worker.py:264-272)

---

## 9. Verification Status

| Component | Lines | Issues Found | Issues Fixed | Status |
|-----------|-------|--------------|--------------|--------|
| PersistentTerminalManager | 1416 | 4 | 3 | ⚠️ 1 medium |
| ThreadSafeWorker | 682 | 2 | 2 | ✅ Clean |
| SimplifiedLauncher | 820 | 1 | 1 | ✅ Clean |
| ProcessExecutor | 322 | 1 | 0 | ⚠️ 1 medium |
| LauncherManager | 680 | 0 | 0 | ✅ Clean |
| CommandLauncher | 864 | 0 | 0 | ✅ Clean |
| **TOTAL** | **4784** | **8** | **6** | **2 medium** |

---

## 10. Testing Recommendations

### Thread Safety Test Coverage

Create tests for:

1. **Concurrent send_command() Calls** (persistent_terminal_manager.py)
   - 10 threads calling `send_command()` simultaneously
   - Verify no deadlocks, all commands execute

2. **Worker Lifecycle Edge Cases** (thread_safe_worker.py)
   - Stop worker immediately after start
   - Stop worker during STARTING state
   - Verify state machine handles races gracefully

3. **FIFO Restart Race Conditions** (persistent_terminal_manager.py)
   - Multiple threads calling `restart_terminal()` concurrently
   - Verify atomic FIFO creation, no collisions

4. **Cache Concurrent Access** (simplified_launcher.py)
   - Concurrent get/set/invalidate operations
   - Verify no corruption, consistent state

5. **Signal Emission Stress Test** (persistent_terminal_manager.py)
   - Rapid signal emissions from multiple worker threads
   - Verify no crashes, all signals delivered

---

## 11. Conclusion

The launcher and terminal management systems demonstrate **strong thread safety practices** with comprehensive fixes for previously-identified issues. The code includes excellent documentation of WHY fixes were applied, making maintenance easier.

**Overall Grade**: **A- (Very Good)**

**Remaining Work**:
- 2 medium-priority improvements (nested lock, explicit connection type)
- 1 low-priority documentation addition

**Key Strengths**:
- Excellent fix documentation
- Proper snapshot pattern usage
- Signal emission outside locks
- Comprehensive resource cleanup
- Worker lifecycle management

**Next Steps**:
1. Apply medium-priority fixes (estimated 2 hours)
2. Add threading stress tests
3. Document TOCTOU acceptance in health checks

---

**Report Generated By**: threading-debugger agent  
**Analysis Duration**: Comprehensive review of 4,784 lines across 6 components  
**Files Analyzed**:
- /home/gabrielh/projects/shotbot/persistent_terminal_manager.py
- /home/gabrielh/projects/shotbot/thread_safe_worker.py
- /home/gabrielh/projects/shotbot/simplified_launcher.py
- /home/gabrielh/projects/shotbot/launcher_manager.py
- /home/gabrielh/projects/shotbot/command_launcher.py
- /home/gabrielh/projects/shotbot/launch/process_executor.py
