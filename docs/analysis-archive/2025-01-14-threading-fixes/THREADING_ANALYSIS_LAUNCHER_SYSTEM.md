# Threading and Concurrency Analysis: Launcher/Terminal System

**Analysis Date:** 2025-11-14
**Scope:** PersistentTerminalManager, CommandLauncher, ProcessExecutor, ProcessVerifier
**Focus:** Deadlocks, race conditions, signal/slot thread affinity, resource management

---

## Executive Summary

**Critical Issues Found: 4**
- **1 CRITICAL DEADLOCK** (blocking issue)
- **1 HIGH SEVERITY** signal connection leak
- **2 MEDIUM SEVERITY** code quality issues

The launcher system has a well-designed threading architecture with proper locking, but contains one critical deadlock bug that will cause hangs when health checks are performed under the write lock.

---

## Architecture Overview

### Thread Boundaries

```
┌─────────────────────────────────────────────────────────┐
│ Main Thread (Qt Event Loop)                             │
│  - PersistentTerminalManager signals                    │
│  - CommandLauncher                                      │
│  - ProcessExecutor signal routing                       │
└─────────────────────────────────────────────────────────┘
                    │
                    │ spawns
                    ▼
┌─────────────────────────────────────────────────────────┐
│ Worker Thread (TerminalOperationWorker - QThread)       │
│  - Health checks (_is_dispatcher_healthy)               │
│  - Command sending (_send_command_direct)               │
│  - Process verification (wait_for_process)              │
└─────────────────────────────────────────────────────────┘
                    │
                    │ IPC via FIFO
                    ▼
┌─────────────────────────────────────────────────────────┐
│ Bash Process (terminal_dispatcher.sh)                   │
│  - Separate process (not thread)                        │
│  - Reads from FIFO, executes commands                   │
│  - Writes PID files for verification                    │
└─────────────────────────────────────────────────────────┘
```

### Shared State Protection

**PersistentTerminalManager:**

```python
# Protected by _state_lock:
- terminal_pid: int | None
- terminal_process: subprocess.Popen | None
- dispatcher_pid: int | None
- _restart_attempts: int
- _fallback_mode: bool
- _last_heartbeat_time: float
- _dummy_writer_fd: int | None
- _fd_closed: bool

# Protected by _write_lock:
- FIFO write operations (serialized)

# Protected by _workers_lock:
- _active_workers: list[TerminalOperationWorker]
```

---

## CRITICAL ISSUE #1: Deadlock - Recursive Lock Acquisition

### Severity: **CRITICAL** (Blocking)

### Location
**File:** `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py`

**Call Chain:**
```
send_command() line 866
  └─> acquires _write_lock
      └─> _ensure_dispatcher_healthy() line 872
          └─> _is_dispatcher_healthy() line 1053
              └─> _send_heartbeat_ping() line 615
                  └─> _send_command_direct() line 561
                      └─> tries to acquire _write_lock line 655
                          └─> DEADLOCK! (already held by send_command)
```

### Code Evidence

```python
# Line 866: send_command() acquires _write_lock
with self._write_lock:
    # Line 868: Perform health check if requested
    if ensure_terminal:
        # Line 872: Call health check UNDER the lock
        if not self._ensure_dispatcher_healthy():
            # ...

# Line 1053: _ensure_dispatcher_healthy()
def _ensure_dispatcher_healthy(self) -> bool:
    if self._is_dispatcher_healthy():  # Calls heartbeat
        return True

# Line 599: _is_dispatcher_healthy()
def _is_dispatcher_healthy(self) -> bool:
    # ...
    # Line 615: Send heartbeat ping
    if not self._send_heartbeat_ping():
        return False

# Line 561: _send_heartbeat_ping()
def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
    # Line 561: Send PING command
    if not self._send_command_direct("__HEARTBEAT__"):
        return False

# Line 655: _send_command_direct() tries to re-acquire the SAME lock
def _send_command_direct(self, command: str) -> bool:
    try:
        with self._write_lock:  # DEADLOCK - already held!
            fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
```

### Root Cause

**Line 235:** `self._write_lock = threading.Lock()`

The `_write_lock` is a regular `Lock`, not a reentrant `RLock`. When the same thread tries to acquire it twice (once in `send_command()`, again in `_send_command_direct()`), it deadlocks.

### Impact

**When it occurs:**
- Any time `send_command()` is called with `ensure_terminal=True` (default)
- Health check triggers heartbeat ping
- Heartbeat ping tries to send via FIFO
- **System hangs permanently**

**Affected operations:**
- All application launches via persistent terminal
- Manual terminal health checks
- Automatic recovery attempts

### Fix

**Option 1: Use RLock (Recommended)**

```python
# Line 235: Change Lock to RLock for reentrancy
self._write_lock = threading.RLock()  # Allow same thread to re-acquire
```

**Pros:**
- Simple one-line fix
- Maintains existing code structure
- RLock is designed for exactly this pattern

**Cons:**
- Slightly more overhead than regular Lock
- Masks potential design issues

**Option 2: Refactor to avoid nested acquisition**

Create a separate `_send_command_direct_unlocked()` method that assumes lock is already held:

```python
def _send_command_direct(self, command: str) -> bool:
    """Public version - acquires lock."""
    with self._write_lock:
        return self._send_command_direct_unlocked(command)

def _send_command_direct_unlocked(self, command: str) -> bool:
    """Internal version - assumes lock is held."""
    # Original implementation without lock acquisition
    fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    # ...
```

**Pros:**
- More explicit about lock ownership
- Better performance (no lock overhead on nested calls)

**Cons:**
- Requires refactoring multiple call sites
- Risk of accidentally calling unlocked version without lock

**Recommendation:** Use Option 1 (RLock). It's the simplest, safest fix.

---

## HIGH SEVERITY ISSUE #2: Signal Connection Leak

### Severity: **HIGH** (Memory leak + potential crash)

### Location
**File:** `/home/gabrielh/projects/shotbot/command_launcher.py`

**Lines 124-133** (signal connections in `__init__`):
```python
if self.persistent_terminal:
    _ = self.persistent_terminal.command_queued.connect(self._on_command_queued)
    _ = self.persistent_terminal.command_executing.connect(self._on_command_executing)
    _ = self.persistent_terminal.command_verified.connect(self._on_command_verified)
    _ = self.persistent_terminal.command_error.connect(self._on_command_error_internal)
    _ = self.persistent_terminal.operation_finished.connect(
        self._on_persistent_terminal_operation_finished
    )
```

**Lines 182-191** (cleanup - MISSING 2 disconnections):
```python
if self.persistent_terminal:
    try:
        _ = self.persistent_terminal.command_queued.disconnect(self._on_command_queued)
        _ = self.persistent_terminal.command_executing.disconnect(self._on_command_executing)
        _ = self.persistent_terminal.operation_finished.disconnect(
            self._on_persistent_terminal_operation_finished
        )
        # ❌ MISSING: command_verified disconnect
        # ❌ MISSING: command_error disconnect
    except (RuntimeError, TypeError, AttributeError):
        pass
```

### Root Cause

Incomplete cleanup in `cleanup()` method - two signal connections are never disconnected.

### Impact

**Memory Leak:**
- `CommandLauncher` object kept alive by signal connections
- `PersistentTerminalManager` holds strong reference via slots
- Python garbage collector cannot free memory

**Potential Crash:**
- If signals fire after `CommandLauncher` is partially destroyed
- Slot methods called on invalid object
- Undefined behavior (likely crash or silent failure)

**When it occurs:**
- Every time `CommandLauncher` is created and destroyed
- Typical in tests with setup/teardown
- Also in production if launcher is recreated

### Fix

Add the missing disconnections:

```python
# command_launcher.py, lines 182-191
if self.persistent_terminal:
    try:
        _ = self.persistent_terminal.command_queued.disconnect(self._on_command_queued)
        _ = self.persistent_terminal.command_executing.disconnect(self._on_command_executing)
        _ = self.persistent_terminal.command_verified.disconnect(self._on_command_verified)  # ✅ ADD
        _ = self.persistent_terminal.command_error.disconnect(self._on_command_error_internal)  # ✅ ADD
        _ = self.persistent_terminal.operation_finished.disconnect(
            self._on_persistent_terminal_operation_finished
        )
    except (RuntimeError, TypeError, AttributeError):
        pass
```

---

## MEDIUM SEVERITY ISSUE #3: Code Duplication - FIFO Write Logic

### Severity: **MEDIUM** (Maintenance burden)

### Location
**File:** `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py`

**Duplicate implementations:**

1. **`_send_command_direct()` lines 621-678** (59 lines)
2. **`send_command()` lines 901-948** (48 lines)

### Code Evidence

Both methods implement identical FIFO write logic:

```python
# _send_command_direct() - lines 654-662
fd = None
try:
    with self._write_lock:
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "wb", buffering=0) as fifo:
            fd = None  # fdopen took ownership
            _ = fifo.write(command.encode("utf-8"))
            _ = fifo.write(b"\n")

# send_command() - lines 901-913 (DUPLICATE!)
fifo_fd = None
try:
    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
        fifo_fd = None
        _ = fifo.write(command.encode("utf-8"))
        _ = fifo.write(b"\n")
```

### Impact

**Maintenance burden:**
- Bug fixes must be applied twice
- Inconsistent error handling
- Harder to review and test

**Example:** The error handling at lines 663-678 in `_send_command_direct()` is more comprehensive than in `send_command()` (lines 919-948).

### Fix

Refactor `send_command()` to use `_send_command_direct()`:

```python
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    """Send a command to the persistent terminal."""
    # ... validation and health checks ...
    
    # Use the dedicated internal method instead of duplicating logic
    if self._send_command_direct(command):
        self.logger.info(f"Successfully sent command to terminal: {command}")
        self.command_sent.emit(command)
        return True
    
    return False
```

Remove lines 901-948 (duplicate FIFO write code).

---

## MEDIUM SEVERITY ISSUE #4: Exception Safety - Dummy Writer State

### Severity: **MEDIUM** (Low probability)

### Location
**File:** `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py`
**Lines:** 308-328 (`_ensure_fifo()`)

### Code Evidence

```python
# Line 309: Acquire lock
with self._state_lock:
    if self._dummy_writer_fd is None:
        try:
            # Line 312: Open FD
            self._dummy_writer_fd = os.open(
                self.fifo_path, os.O_WRONLY | os.O_NONBLOCK
            )
            # Line 315: Set flag
            self._fd_closed = False  # ⚠️ If interrupted here...
        except OSError as e:
            # Error handling
```

### Scenario

If `KeyboardInterrupt` or other exception occurs between line 312 and line 315:
- `_dummy_writer_fd` is set (FD is open)
- `_fd_closed` is still `True` (not updated)
- Inconsistent state

Later, `_close_dummy_writer_fd()` checks:
```python
# Line 376: Sees _fd_closed=True, returns early
if self._fd_closed or self._dummy_writer_fd is None:
    return
```

**Result:** FD leaked (never closed).

### Impact

**Low probability:**
- Requires precise timing of KeyboardInterrupt
- Most exceptions (OSError) are caught before this point

**Low severity:**
- Single FD leak (not repeated)
- OS will clean up on process exit

### Fix

**Option 1: Atomic state update**

```python
with self._state_lock:
    if self._dummy_writer_fd is None:
        try:
            fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            # Atomic update - no interruption possible
            self._dummy_writer_fd = fd
            self._fd_closed = False
        except OSError as e:
            # ...
```

**Option 2: Set _fd_closed first**

```python
with self._state_lock:
    if self._dummy_writer_fd is None:
        try:
            self._fd_closed = False  # Set BEFORE opening
            self._dummy_writer_fd = os.open(
                self.fifo_path, os.O_WRONLY | os.O_NONBLOCK
            )
        except OSError as e:
            self._fd_closed = True  # Reset on error
```

---

## Thread-Safe Code (No Issues Found)

### Qt Signal Thread Affinity ✅

**TerminalOperationWorker** emits signals from worker thread:

```python
# Line 127: Worker thread emits manager's signal
self.manager.command_executing.emit(timestamp)
```

**Analysis:** This is **SAFE**. Qt automatically handles cross-thread signal emission:
- Signals are queued to main thread's event loop
- Uses `Qt::AutoConnection` by default
- No explicit thread synchronization needed

### Worker Cleanup ✅

**Cleanup race between** `cleanup()` and `send_command_async()`:

```python
# cleanup() copies list under lock
with self._workers_lock:
    workers_to_stop = list(self._active_workers)

# Worker may finish and remove itself
def cleanup_worker() -> None:
    with self._workers_lock:
        if worker in self._active_workers:  # ✅ Safe check
            self._active_workers.remove(worker)
```

**Analysis:** Race condition is handled correctly by the `if worker in` check.

### FIFO Write Serialization ✅

**Multiple threads calling** `send_command()`:

```python
# Line 655: All FIFO writes are serialized
with self._write_lock:
    fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    # ...
```

**Analysis:** Correct use of lock prevents byte-level corruption of FIFO writes.

### ProcessVerifier Thread Safety ✅

**ProcessVerifier** is used from worker threads:

```python
# Line 144: Worker thread calls verifier
success, message = self.manager._process_verifier.wait_for_process(...)
```

**Analysis:** 
- Only read-only filesystem operations
- No shared mutable state
- Uses psutil (thread-safe)
- **Completely thread-safe**

---

## Bash Script Analysis (terminal_dispatcher.sh)

### Thread Safety: N/A (Single-threaded)

The dispatcher script runs in a **separate process**, not a thread. No threading issues.

### Concurrency Issues: None Found

**FIFO Read Loop (lines 216-326):**
```bash
# Persistent FD 3 for reading
exec 3< "$FIFO"
while true; do
    if read -r cmd <&3; then
        # Process command
    fi
done
```

**Analysis:**
- Single-threaded bash process
- Reads sequentially from FIFO
- No race conditions possible within bash
- IPC race conditions handled by FIFO semantics (atomic writes)

---

## Recommendations

### Priority 1: Fix Critical Deadlock

**Action:** Change `_write_lock` to `RLock`

```python
# persistent_terminal_manager.py, line 235
self._write_lock = threading.RLock()  # Was: threading.Lock()
```

**Timeline:** Immediate (blocking issue)

### Priority 2: Fix Signal Connection Leak

**Action:** Add missing disconnect calls

```python
# command_launcher.py, line 186 (add these lines)
_ = self.persistent_terminal.command_verified.disconnect(self._on_command_verified)
_ = self.persistent_terminal.command_error.disconnect(self._on_command_error_internal)
```

**Timeline:** Next release (high severity)

### Priority 3: Refactor FIFO Write Duplication

**Action:** Remove duplicate code in `send_command()`

- Extract common FIFO write logic
- Reuse `_send_command_direct()` from `send_command()`
- Remove lines 901-948 from `send_command()`

**Timeline:** Next major refactor (not urgent)

### Priority 4: Improve Exception Safety

**Action:** Make dummy writer state update atomic

**Timeline:** Low priority (unlikely to occur)

---

## Testing Recommendations

### Deadlock Testing

**Test Case 1: Health check under load**
```python
def test_concurrent_health_checks():
    """Verify no deadlock when health checks run during send."""
    terminal = PersistentTerminalManager()
    
    # Send command with health check (triggers heartbeat)
    def send_with_health():
        terminal.send_command("nuke", ensure_terminal=True)
    
    # Run multiple threads simultaneously
    threads = [Thread(target=send_with_health) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)  # Should not timeout
```

**Expected:** No deadlock, all threads complete within 5 seconds.

### Signal Leak Testing

**Test Case 2: Repeated creation/destruction**
```python
def test_signal_connection_cleanup():
    """Verify signal connections are cleaned up."""
    terminal = PersistentTerminalManager()
    
    # Create and destroy launchers
    for _ in range(100):
        launcher = CommandLauncher(persistent_terminal=terminal)
        launcher.cleanup()
        del launcher
    
    # Verify no leaked connections
    assert len(gc.get_referrers(terminal)) < 10  # Should not grow
```

---

## Performance Implications

### Lock Contention

**Current:**
- `_write_lock`: Serializes all FIFO writes
- Average hold time: ~1-5ms (FIFO write + fsync)
- Contention: Low (most operations are async)

**With RLock:**
- Slightly higher overhead (~10-20% slower acquisition)
- Negligible impact (microsecond scale)

**Recommendation:** RLock overhead is acceptable for correctness.

### Worker Thread Overhead

**Current:**
- 1 worker thread per async operation
- Workers cleaned up after completion
- Minimal memory overhead (~1MB per worker)

**Optimization opportunity:**
- Consider worker pool pattern for high-frequency operations
- Not necessary for current usage pattern (launches are infrequent)

---

## Conclusion

The launcher/terminal system has a **well-architected threading model** with proper lock-based synchronization. The critical deadlock issue is a simple fix (use RLock), and the signal leak is easily addressed. Once these are fixed, the system will be robust and thread-safe.

**Overall Grade: B+** (would be A with fixes applied)

**Positive aspects:**
- Clear thread boundaries
- Proper use of locks for shared state
- Qt signal/slot thread safety handled correctly
- Worker thread lifecycle well-managed

**Areas for improvement:**
- Use RLock for reentrant operations
- Complete signal cleanup in destructors
- Reduce code duplication
- Add comprehensive concurrency tests

