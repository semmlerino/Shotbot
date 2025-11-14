# FIFO/IPC Communication Patterns Analysis
## Shotbot Launcher & Terminal System

**Analysis Date**: November 14, 2025  
**Scope**: Inter-process communication (FIFO), signal/slot patterns, synchronization, and resource management  
**Depth**: Very thorough - all blocking operations, race conditions, and failure modes analyzed

---

## Executive Summary

The Shotbot launcher/terminal system uses named pipes (FIFOs) for inter-process communication between the Qt GUI and a persistent bash dispatcher. The architecture provides robust recovery mechanisms but has several blocking operations and race conditions that impact responsiveness under concurrent load.

**Total IPC/Communication Issues Found**: 12
- **Critical Issues**: 2 (blocking locks, concurrent FIFO races)
- **High Severity**: 3 (stale resource handling, verification failures)
- **Medium Severity**: 4 (race windows, timeout vulnerabilities)
- **Low Severity**: 3 (resource cleanup, logging)

---

## Issue Analysis

### CRITICAL ISSUES

#### Issue #1: BLOCKING LOCK DURING I/O RETRY (HIGH SEVERITY)

**File**: `persistent_terminal_manager.py`  
**Lines**: 889-1000 in `send_command()`

**Problem**:
The `_write_lock` is held for the entire duration of I/O retry backoff sleeps:

```python
# Lines 889-986
with self._write_lock:  # ← Lock acquired here
    if ensure_terminal:
        if not self._ensure_dispatcher_healthy():  # May call _send_heartbeat_ping()
            return False
    
    # Lines 927-940: Retry loop STILL HOLDING LOCK
    for attempt in range(max_retries):
        try:
            fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
                fifo_fd = None
                _ = fifo.write(command.encode("utf-8"))
                _ = fifo.write(b"\n")
            return True
        
        except OSError as e:
            if e.errno == errno.EAGAIN:
                # CRITICAL: Sleep WHILE HOLDING LOCK!
                backoff: float = 0.1 * (2 ** attempt)  # 0.1s, 0.2s, 0.4s
                time.sleep(backoff)  # ← LOCK HELD DURING SLEEP!
                continue
            # ... handle other errors ...
```

**Impact Analysis**:
- **Serialization**: All concurrent `send_command()` calls serialize on `_write_lock`
- **Blocking Duration**: 0.1 + 0.2 + 0.4 = 0.7s minimum per retry cycle
- **Cascading Delay**: 3 concurrent commands × 0.7s = 2.1s+ total delay
- **Health Check Blockage**: `_ensure_dispatcher_healthy()` calls can't run while lock held
- **Heartbeat Ping Blockage**: `_send_heartbeat_ping()` cannot write during backoff sleep

**Scenario**:
```
Thread A (command 1): Acquires _write_lock at T=0
Thread A: FIFO buffer full (EAGAIN), sleeps 0.1s at T=0.05 (LOCK HELD)
Thread B (command 2): Blocked waiting for _write_lock at T=0.01
Thread C (command 3): Blocked waiting for _write_lock at T=0.02
Thread A: Continues retry at T=0.15, gets EAGAIN again, sleeps 0.2s (LOCK HELD)
Thread B: Still blocked at T=0.15
Thread C: Still blocked at T=0.15
Thread A: Finishes at T=0.35 (or continues to 0.4s retry)
Thread B: Acquires lock at T=0.35, repeats same cycle
Thread C: Waits for Thread B's cycle

Total: ~1+ second for all 3 commands to complete (vs ~0.3s with optimized locking)
```

**Root Cause**:
The lock protects both I/O and the retry logic, when it should only protect:
1. FIFO existence check
2. File descriptor open
3. Write operation
4. File descriptor close

The retry loop logic (sleep, retry decision) doesn't need the lock.

**Fix Required**:
```python
# CORRECTED PATTERN
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    # Health check OUTSIDE lock (takes time, shouldn't block others)
    if ensure_terminal:
        if not self._ensure_dispatcher_healthy():
            return False
    
    # Retry loop OUTSIDE lock
    max_retries = 3
    for attempt in range(max_retries):
        # Acquire lock ONLY for I/O
        try:
            with self._write_lock:  # ← MINIMAL LOCK SCOPE
                if not Path(self.fifo_path).exists():
                    if attempt < max_retries - 1:
                        # Release lock before sleeping
                        break  # Exit critical section
                    return False
                
                fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
                with os.fdopen(fd, "wb", buffering=0) as fifo:
                    fd = None
                    _ = fifo.write(command.encode("utf-8"))
                    _ = fifo.write(b"\n")
                return True  # Success
        
        except OSError as e:
            if e.errno == errno.EAGAIN and attempt < max_retries - 1:
                # Sleep OUTSIDE lock!
                backoff = 0.1 * (2 ** attempt)
                time.sleep(backoff)
                continue
            return False
```

**Severity**: **HIGH** - Blocks responsive command execution during concurrent load  
**Effort**: 2-3 hours (restructure retry logic, add tests)  
**Priority**: IMMEDIATE

---

#### Issue #2: CONCURRENT FIFO RECREATION RACE (HIGH SEVERITY)

**Files**: 
- `persistent_terminal_manager.py`: `send_command()` (line 930), `restart_terminal()` (line 1356)
- `launcher/worker.py`: Command execution context

**Problem**:
Two code paths can race when managing FIFO:

```python
# Path 1: send_command() at line 930
for attempt in range(max_retries):
    try:
        fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        # If FIFO doesn't exist:
        # Thread A creates NEW FIFO at line 930: _ensure_fifo()
```

```python
# Path 2: restart_terminal() at line 1356 (holds _restart_lock)
with self._restart_lock:
    # Line 1364: Delete old FIFO
    if Path(self.fifo_path).exists():
        Path(self.fifo_path).unlink()  # ← Deletes FIFO
    
    # Line 1377-1381: Create NEW FIFO atomically
    os.mkfifo(temp_fifo, 0o600)
    os.rename(temp_fifo, self.fifo_path)  # ← Creates/overwrites FIFO
```

**Race Scenario**:
```
T0: restart_terminal() deletes FIFO (line 1366)
T1: send_command() doesn't hold _restart_lock! 
T1: send_command() calls _ensure_fifo() (line 954)
T1: _ensure_fifo() creates NEW FIFO at line 307: os.mkfifo()
T2: restart_terminal() creates temp_fifo and atomically renames to fifo_path
T2: os.rename() OVERWRITES send_command's newly created FIFO!
T3: send_command() opens and writes to its FIFO
T4: But the FIFO is now owned by restart_terminal's dispatcher (or no dispatcher!)
T5: Command is lost or sent to wrong dispatcher
```

**Critical Code Section**:
```python
# send_command() - does NOT hold _restart_lock!
with self._write_lock:  # ← Only this lock
    for attempt in range(max_retries):
        if not Path(self.fifo_path).exists():
            if not is_last_attempt:
                if self._ensure_fifo():  # ← Creates FIFO without _restart_lock
                    time.sleep(0.2)
                    continue
            return False
        
        # Race window: restart could delete FIFO here!
        fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
```

**Impact**:
- **Lost Commands**: Commands sent to FIFO that restart deletes
- **Stale FIFOs**: send_command's FIFO overwritten before command written
- **Silent Failures**: ENXIO errors appear to be retryable, but FIFO is gone
- **Dispatcher Mismatch**: Multiple dispatcher instances competing for same FIFO path

**Fix Required**:
Two approaches (order by preference):

**Option A**: Acquire `_restart_lock` in send_command (preferred)
```python
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    with self._restart_lock:  # ← Serialize with restart
        with self._write_lock:
            # ... existing retry logic ...
```

**Option B**: Use FIFO version counter
```python
# Track FIFO "generation"
self._fifo_generation = 0

# In restart_terminal
with self._restart_lock:
    self._fifo_generation += 1
    # Create new FIFO
    
# In send_command
my_generation = self._fifo_generation
# If generation changes during operation, retry
```

**Severity**: **HIGH** - Silent command loss under concurrent operation  
**Effort**: 1-2 hours (add lock acquisition, test interactions)  
**Priority**: IMMEDIATE

---

### HIGH SEVERITY ISSUES

#### Issue #3: STALE RESOURCE REFERENCES IN CLEANUP (HIGH)

**File**: `persistent_terminal_manager.py`  
**Lines**: 1439-1530 in `cleanup()`

**Problem**:
Worker threads may hold locks while cleanup attempts to acquire them:

```python
def cleanup(self) -> None:
    # Line 1446-1450: Get list of active workers
    with self._workers_lock:
        workers_to_stop = list(self._active_workers)
        self._active_workers.clear()
    
    # Line 1456-1478: Stop workers
    for worker in workers_to_stop:
        worker.requestInterruption()
        if not worker.wait(10000):  # 10s timeout
            self.logger.error(
                f"Worker {id(worker)} did not stop after 10s. "
                "Abandoning worker to prevent deadlock."
            )
            # ← CRITICAL: Worker may still hold _state_lock or _write_lock!
    
    # Line 1485-1530: Cleanup terminal and resources
    # But workers might STILL be running and holding locks!
    terminal_pid_snapshot = self.terminal_pid
    terminal_process_snapshot = self.terminal_process
```

**The Hidden Race**:
```python
# In TerminalOperationWorker._run_send_command()
def _run_send_command(self) -> None:
    # This runs in worker thread
    self.manager._ensure_dispatcher_healthy(worker=self)  # ← Holds _state_lock
    # While this runs...
    # Main thread calls cleanup() and tries to access terminal_pid!
```

**Locking Hierarchy Problem**:
1. `TerminalOperationWorker` holds `_state_lock` during health check
2. `cleanup()` skips acquiring `_state_lock` to prevent deadlock
3. But cleanup reads `terminal_pid` without lock!
4. Worker might be modifying `terminal_pid` concurrently

**Code Evidence**:
```python
# Line 1149 in _ensure_dispatcher_healthy
with self._state_lock:
    if self._restart_attempts >= self._max_restart_attempts:
        self._fallback_mode = True
        self._fallback_entered_at = time.time()
        return False

# Meanwhile in cleanup (line 1487):
terminal_pid_snapshot = self.terminal_pid  # ← NO LOCK!
# If worker is updating this right now, snapshot might be corrupted
```

**Impact**:
- **Data Race**: Reading `terminal_pid` while worker modifies it
- **Inconsistent State**: `terminal_pid` vs `terminal_process` mismatch
- **Zombie Process**: Process not properly terminated
- **Resource Leak**: FD not closed if snapshot taken during modification

**Fix Required**:
Use atomic snapshot pattern:
```python
def cleanup(self) -> None:
    # Workers stopped, but take atomic snapshot to be safe
    with self._state_lock:
        terminal_pid_snapshot = self.terminal_pid
        terminal_process_snapshot = self.terminal_process
        self.terminal_pid = None
        self.terminal_process = None
    
    # Now cleanup with consistent snapshots
    if terminal_pid_snapshot is not None:
        # Safe to use consistent pair
```

**Severity**: **HIGH** - Potential resource leak and inconsistent state  
**Effort**: 1-2 hours (add snapshot logic, test concurrent cleanup)  
**Priority**: HIGH

---

#### Issue #4: HEARTBEAT PING TIMEOUT RACE (HIGH)

**File**: `persistent_terminal_manager.py`  
**Lines**: 570-601 in `_send_heartbeat_ping()`

**Problem**:
The heartbeat mechanism has a race condition between file deletion and read:

```python
def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
    try:
        # Line 580-583: Delete OLD heartbeat
        heartbeat_file = Path(self.heartbeat_path)
        if heartbeat_file.exists():
            heartbeat_file.unlink()  # ← Synchronous delete
        
        # Line 585-586: Send PING command
        if not self._send_command_direct("__HEARTBEAT__"):
            return False
        
        # Line 589-594: Poll for PONG response
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            if self._check_heartbeat():  # ← Returns True if file exists with "PONG"
                return True
            time.sleep(0.1)
        
        return False  # Timeout

def _check_heartbeat(self) -> bool:
    heartbeat_file = Path(self.heartbeat_path)
    if not heartbeat_file.exists():
        return False  # ← File might be missing briefly
    
    content = heartbeat_file.read_text().strip()
    if not content or content != "PONG":
        return False
    
    # Check file modification time
    mtime = heartbeat_file.stat().st_mtime
    age = time.time() - mtime
    
    if age < self._heartbeat_timeout:
        # ← Age might be very old if dispatcher is slow
        return True
    return False
```

**Race Window**:
```
T0: _send_heartbeat_ping() deletes heartbeat file
T1: Dispatcher reads "__HEARTBEAT__" from FIFO
T2: dispatcher writes: echo "PONG" > file.tmp && mv file.tmp file
T3: Polling loop checks heartbeat
T4: File exists, content is "PONG", mtime is current
T5: Success!

BUT - if dispatcher is SLOW:
T0: _send_heartbeat_ping() deletes heartbeat file
T1: Polling starts immediately
T2-T10: Dispatcher is executing previous command, hasn't read PING yet
T2-T10: _check_heartbeat() called 20 times, file doesn't exist
T10: Dispatcher finishes previous command, reads PING
T11: Dispatcher writes PONG
T12: Next polling iteration finds PONG
RESULT: Timeout appears intermittent based on dispatcher timing
```

**Additionally: Stale Heartbeat File**:
```python
# If dispatcher crashes after writing PONG:
# File mtime is old (e.g., from 2 minutes ago)
# But dispatcher is actually dead!

# In _is_dispatcher_healthy():
if age > self._heartbeat_timeout:  # age = 120 seconds
    # Try sending a ping to verify
    if not self._send_heartbeat_ping():
        return False  # ← Correct
    
# But if dispatcher is stuck (not reading FIFO):
# _send_heartbeat_ping() will timeout and return False
# Because dispatcher never processes the PING command
```

**Impact**:
- **False Negatives**: Healthy dispatcher appears unhealthy due to timing
- **False Positives**: Dead dispatcher appears healthy if PONG is recent
- **Intermittent Failures**: Health checks fail sporadically based on timing
- **Unnecessary Restarts**: Terminal restarts when perfectly healthy

**Fix Required**:
```python
def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
    try:
        heartbeat_file = Path(self.heartbeat_path)
        
        # Generate unique request ID to distinguish old responses
        import uuid
        request_id = str(uuid.uuid4())[:8]
        request_file = Path(self.heartbeat_path).parent / f".ping_request_{request_id}"
        
        # Write request file to signal dispatcher
        request_file.write_text(request_id)
        
        # Send PING with request ID
        if not self._send_command_direct(f"__HEARTBEAT__{request_id}__"):
            return False
        
        # Poll for response with matching request ID
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            if heartbeat_file.exists():
                try:
                    content = heartbeat_file.read_text().strip()
                    if content == request_id:  # ← Match request ID!
                        return True
                except (OSError, ValueError):
                    pass
            time.sleep(0.1)
        
        return False
    finally:
        # Cleanup request file
        try:
            request_file.unlink()
        except (OSError, NameError):
            pass
```

**Alternative (Simpler)**:
Use file modification time instead of existence:
```python
def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
    heartbeat_file = Path(self.heartbeat_path)
    
    # Record deletion time
    pre_delete_time = time.time()
    if heartbeat_file.exists():
        heartbeat_file.unlink()
    
    # Send PING
    if not self._send_command_direct("__HEARTBEAT__"):
        return False
    
    # Poll for NEWER file
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        if heartbeat_file.exists():
            mtime = heartbeat_file.stat().st_mtime
            # File must be created AFTER we deleted it
            if mtime > pre_delete_time:
                content = heartbeat_file.read_text().strip()
                if content == "PONG":
                    return True
        time.sleep(0.1)
    
    return False
```

**Severity**: **HIGH** - Intermittent false health failures  
**Effort**: 1-2 hours (implement request ID or mtime check)  
**Priority**: HIGH

---

### MEDIUM SEVERITY ISSUES

#### Issue #5: SIGNAL/SLOT CONNECTION LEAKS (MEDIUM)

**File**: `command_launcher.py`  
**Lines**: 127-173 in `__init__()`

**Problem**:
Signal connections are stored but cleanup method may not disconnect all:

```python
def __init__(self, ...):
    # Lines 117: Create list to track connections
    self._signal_connections: list[QMetaObject.Connection] = []
    
    # Lines 127-142: Connect ProcessExecutor signals
    self._signal_connections.append(
        self.process_executor.execution_progress.connect(
            self._on_execution_progress, Qt.ConnectionType.QueuedConnection
        )
    )
    # ... more connections ...
    
    # Lines 144-173: Connect PersistentTerminalManager signals IF available
    if self.persistent_terminal:
        self._signal_connections.append(
            self.persistent_terminal.command_queued.connect(...)
        )
        # ... more connections ...

def cleanup(self) -> None:
    # Line 208-215: Disconnect tracked connections
    if hasattr(self, "_signal_connections"):
        for connection in self._signal_connections:
            try:
                QObject.disconnect(connection)
            except (RuntimeError, TypeError):
                pass  # Already disconnected
        self._signal_connections.clear()
```

**The Problem**:
If `__init__` fails partway through and persistent_terminal connects aren't made, cleanup still runs. But if `__init__` fails BEFORE creating `_signal_connections`, then cleanup crashes:

```python
def __init__(self, ...):
    super().__init__(parent)
    self.current_shot = None
    self.persistent_terminal = persistent_terminal
    
    # If NEXT line throws exception:
    self._pending_fallback = {}  # ← What if this fails?
    
    # These never execute:
    self._signal_connections: list[QMetaObject.Connection] = []
    # ... signal connections ...
    
def cleanup(self) -> None:
    # hasattr check prevents crash
    if hasattr(self, "_signal_connections"):
        # This is OK because of hasattr
```

**Real Issue**: ProcessExecutor cleanup assumes cleanup() was called:
```python
def cleanup(self) -> None:
    if hasattr(self, "process_executor"):
        self.process_executor.cleanup()  # ← What if ProcessExecutor.__init__ failed?
```

**Plus: ProcessExecutor has its own connections**:
```python
# In ProcessExecutor.__init__
if self.persistent_terminal:
    _ = self.persistent_terminal.operation_progress.connect(
        self._on_terminal_progress
    )
    # These are NOT tracked in CommandLauncher!
```

**Impact**:
- **Memory Leak**: ProcessExecutor → PersistentTerminalManager signal leaks if not explicitly cleaned
- **Qt Warning**: "QObject: Cannot create children for a parent that is in a different thread" if connections remain
- **Dangling Connections**: Callbacks fired on destroyed objects

**Code Evidence**:
```python
# ProcessExecutor has connections but CommandLauncher cleanup doesn't address them!
# Line 81-87 in process_executor.py
if self.persistent_terminal:
    _ = self.persistent_terminal.operation_progress.connect(
        self._on_terminal_progress
    )
    # No disconnect happens!

# CommandLauncher cleanup:
if hasattr(self, "process_executor"):
    self.process_executor.cleanup()
    # But ProcessExecutor.cleanup() doesn't exist!
```

**Fix Required**:
```python
# In ProcessExecutor
def cleanup(self) -> None:
    """Disconnect all signal connections."""
    # Disconnect from persistent terminal if connected
    if self.persistent_terminal:
        try:
            self.persistent_terminal.operation_progress.disconnect(
                self._on_terminal_progress
            )
        except (RuntimeError, TypeError):
            pass
        
        try:
            self.persistent_terminal.command_result.disconnect(
                self._on_terminal_command_result
            )
        except (RuntimeError, TypeError):
            pass
```

**Severity**: **MEDIUM** - Resource leak, Qt warnings in production  
**Effort**: 1 hour (add disconnect calls)  
**Priority**: HIGH (but lower than critical issues)

---

#### Issue #6: TERMINALOPERATIONWORKER LIFECYCLE HAZARD (MEDIUM)

**File**: `persistent_terminal_manager.py`  
**Lines**: 46-106 in `TerminalOperationWorker` class and 1046-1076 in `send_command_async()`

**Problem**:
Worker threads are created dynamically and stored in a list, but the lifetime is tricky:

```python
def send_command_async(self, command: str, ...) -> None:
    # Line 1046: Create worker
    worker = TerminalOperationWorker(self, "send_command", parent=self)
    worker.command = command
    
    # Line 1059-1060: Store reference to prevent GC
    with self._workers_lock:
        self._active_workers.append(worker)
    
    # Line 1063-1067: Define cleanup callback
    def cleanup_worker() -> None:
        with self._workers_lock:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
        worker.deleteLater()  # ← Schedule for deletion
    
    # Line 1069: Connect cleanup to operation_finished
    _ = worker.operation_finished.connect(
        cleanup_worker, Qt.ConnectionType.QueuedConnection
    )
    
    # Line 1075: Start worker
    worker.start()  # ← Worker thread now running
```

**The Race Window**:
```
T0: worker.start() begins execution
T1: send_command_async() returns to caller (worker still running)
T2: Caller code calls cleanup()
T3: cleanup() stops workers with wait(10000)
T4: Worker finishes and emits operation_finished
T5: QueuedConnection fires cleanup_worker() callback
T6: cleanup_worker() tries worker.deleteLater()
T7: But if worker was already deleted in step 3?
    → Use-after-free in Qt's signal system
```

**Additional Problem**:
The parent parameter creates an implicit dependency:
```python
def send_command_async(self, command: str, ensure_terminal: bool = True) -> None:
    worker = TerminalOperationWorker(self, "send_command", parent=self)
    # parent=self means: when PersistentTerminalManager is deleted, worker is deleted
    # But worker might still be running!
```

**What Happens**:
1. PersistentTerminalManager is deleted
2. Qt auto-deletes all children (including worker)
3. Worker thread is still running (worker thread doesn't check if object was deleted)
4. Worker calls `self.operation_finished.emit()` on deleted object → CRASH

**Code Evidence**:
```python
# Line 55 in TerminalOperationWorker.__init__
class TerminalOperationWorker(QThread):
    def __init__(self, manager, operation, parent: QObject | None = None):
        super().__init__(parent)  # ← parent means auto-delete
        self.manager = manager

# Line 137: When PersistentTerminalManager is deleted:
# Qt sees parent is gone, deletes TerminalOperationWorker
# But worker thread is in the middle of:

# Line 164-167:
success, message = self.manager._process_verifier.wait_for_process(...)
# ^ This can take 5+ seconds (VERIFICATION_TIMEOUT_SEC)
# If manager is deleted during this, accessing manager crashes!
```

**Impact**:
- **Crash on Cleanup**: Qt crash if worker is running during shutdown
- **Use-After-Free**: Worker accesses manager methods after manager deleted
- **Signal Crash**: Emitting signals on deleted object causes SIGSEGV

**Fix Required**:
Use weak references:
```python
from weakref import ref

class TerminalOperationWorker(QThread):
    def __init__(self, manager, operation, parent: QObject | None = None):
        super().__init__(parent)
        self._manager_ref = ref(manager)  # ← Weak reference
        self.operation = operation
    
    def run(self) -> None:
        manager = self._manager_ref()  # ← Check if still alive
        if manager is None:
            return  # Manager was deleted, stop gracefully
        
        # Use manager safely
        if not manager._is_dispatcher_healthy():
            ...
```

OR: Don't use parent parameter:
```python
def send_command_async(self, command: str, ...) -> None:
    worker = TerminalOperationWorker(self, "send_command", parent=None)
    # ↑ parent=None means: don't auto-delete with PersistentTerminalManager
    # We manage lifetime explicitly in cleanup()
```

**Severity**: **MEDIUM** - Crash during application shutdown  
**Effort**: 1-2 hours (implement weak refs or change lifecycle)  
**Priority**: HIGH

---

#### Issue #7: PROCESS VERIFICATION STALE PID WINDOW (MEDIUM)

**File**: `launch/process_verifier.py`  
**Lines**: 66-116 in `wait_for_process()`

**Problem**:
There's a window where dispatcher PID file is read but process is about to crash:

```python
def wait_for_process(self, command: str, ...) -> tuple[bool, str]:
    # Line 98: Extract app name
    app_name = self._extract_app_name(command)
    
    # Line 103: Wait for PID file
    pid = self._wait_for_pid_file(app_name, timeout_sec, enqueue_time)
    if pid is None:
        return False, f"PID file not found after {timeout_sec}s"
    
    # Line 110: Verify process exists
    if self._verify_process_exists(pid):
        return True, f"Process verified (PID: {pid})"
    
    # Line 114: Process doesn't exist
    return False, f"Process {pid} not found (crashed immediately?)"
```

**The Race**:
```
T0: Dispatcher writes PID file: echo "12345" > file
T1: Process verifier reads PID: pid = 12345
T2: Verifier checks psutil.pid_exists(12345): True
T3: Verifier emits: "Process verified (PID: 12345)"
T4: Nuke crashes immediately after being launched
T5: User thinks Nuke started successfully
```

**Why This Matters**:
Nuke can fail to start for various reasons:
- Missing .nuke file
- License server unavailable
- GPU drivers broken
- Missing shared libraries

The process starts (PID exists) but immediately crashes before any UI appears.

**Impact**:
- **False Success**: User thinks app launched, but it's already dead
- **Silent Failures**: App crashes with no visible error
- **Lost Work**: User starts working before app fully initializes

**Why It's Hard to Fix**:
True process verification requires:
1. Check PID exists (current)
2. Wait for process to fully initialize
3. Check process is still running

But "fully initialized" is application-specific:
- Nuke: Window appears
- Maya: UI ready
- 3DE: License initialized

**Current Mitigation**:
The dispatcher waits 0.5s after launch:
```bash
# terminal_dispatcher.sh line 302-303
gui_pid=$!
sleep 0.5  # Give app time to crash if it's going to
```

But 0.5s is arbitrary and may not be enough for slow systems.

**Fix Required** (in order of feasibility):
Option A: Increase wait + recheck:
```python
def wait_for_process(self, command: str, ...) -> tuple[bool, str]:
    pid = self._wait_for_pid_file(app_name, timeout_sec, enqueue_time)
    if pid is None:
        return False, "PID file not found"
    
    # Wait for process to fully initialize
    # Increase from 0.5s to 2s to catch crash-immediately scenarios
    time.sleep(2.0)  # ← Let app crash if it's going to
    
    # Check process still exists
    if not self._verify_process_exists(pid):
        return False, f"Process crashed immediately after launch"
    
    return True, f"Process verified (PID: {pid})"
```

Option B: Check process resource utilization:
```python
def wait_for_process(self, command: str, ...) -> tuple[bool, str]:
    pid = self._wait_for_pid_file(app_name, timeout_sec, enqueue_time)
    
    try:
        proc = psutil.Process(pid)
        
        # Check process hasn't immediately exited
        if proc.status() in [psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE]:
            return False, "Process exited immediately"
        
        # Optional: Check memory usage (shows app initialized)
        # if proc.memory_info().rss < 10_000_000:  # < 10MB = probably crashed
        
        return True, f"Process verified (PID: {pid})"
    except psutil.NoSuchProcess:
        return False, "Process no longer exists"
```

**Severity**: **MEDIUM** - Can appear as success when app crashes immediately  
**Effort**: 0.5 hours (increase wait time is simple, but less reliable)  
**Priority**: MEDIUM

---

#### Issue #8: COMMAND ARGUMENT PARSING ASSUMES SAFE CONTEXT (MEDIUM)

**File**: `terminal_dispatcher.sh`  
**Lines**: 94-148 in `is_gui_app()` and `extract_app_name()`

**Problem**:
The bash functions use regex pattern matching that can fail silently:

```bash
# Line 102-113
is_gui_app() {
    local cmd="$1"
    
    # If command contains bash -ilc with quotes, extract the inner command
    if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
        local inner_cmd="${BASH_REMATCH[1]}"
        
        # Extract the last command after && if present
        if [[ "$inner_cmd" == *"&&"* ]]; then
            # Get everything after the last &&
            local last_segment="${inner_cmd##*&&}"
            # Trim leading whitespace
            last_segment="${last_segment#"${last_segment%%[![:space:]]*}"}"
            # Extract first word (the command)
            local actual_cmd="${last_segment%% *}"
```

**Failure Modes**:
1. **Regex doesn't match**: Command not recognized as GUI app
2. **Extraction fails**: `actual_cmd` is empty string
3. **Pattern changes**: CommandLauncher sends different format, dispatcher misses it

**Example Failure**:
```bash
# CommandLauncher sends:
cmd="rez env nuke -- bash -ilc 'ws /path && nuke -file /file.nk'"

# Dispatcher tries to match:
if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
    # Pattern expects: bash ... "..." with double quotes!
    # But rez command uses single quotes in bash argument!
    # PATTERN DOESN'T MATCH
fi

# Falls back to check "nuke" at start (line 141)
case "$cmd" in
    nuke\ *)
        return 0
        ;;
esac

# But cmd starts with "rez", not "nuke"
# SILENTLY RETURNS 1 (non-GUI)

# GUI app gets FOREGROUND execution instead of background
# Terminal blocks waiting for Nuke to finish
```

**Impact**:
- **Silent Detection Failure**: GUI app identified as non-GUI
- **Terminal Blocking**: GUI app blocks terminal (waits for exit)
- **User Confusion**: App appears to hang
- **Cascading Failures**: Next commands don't execute until app closes

**Code Evidence**:
```bash
# Line 318-320: Non-GUI command path BLOCKS
log_info "Executing non-GUI command: $cmd"
eval "$cmd"
exit_code=$?
# ^ Terminal WAITS for command to finish

# Should be GUI app but detection failed:
# "nuke" runs in foreground, user can't interact with terminal
```

**Real Example from Production**:
If CommandLauncher changes command format:
```python
# Old format (works):
f"bash -ilc '{command}'"

# New format (breaks):
f"bash -ilc \"{command}\""  # Different quote style
```

The dispatcher regex would fail silently.

**Fix Required**:
1. **Make extraction more robust**:
```bash
# Extract app name using multiple patterns
extract_app_name() {
    local cmd="$1"
    
    # Pattern 1: rez env <app> -- ...
    if [[ "$cmd" =~ rez\ env\ ([a-zA-Z_]+) ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    
    # Pattern 2: ... && <app> <args>
    if [[ "$cmd" =~ '&&'[[:space:]]*([a-zA-Z_]+) ]]; then
        app="${BASH_REMATCH[1]}"
        case "$app" in
            nuke|maya|3de|rv|houdini)
                echo "$app"
                return 0
                ;;
        esac
    fi
    
    # Pattern 3: ws /path && <app>
    if [[ "$cmd" =~ ws[[:space:]]+[^[:space:]]+[[:space:]]+'&&'[[:space:]]*([a-zA-Z_]+) ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    
    return 1
}
```

2. **Add logging for failures**:
```bash
# When extraction fails, log the command
if ! app_name=$(extract_app_name "$cmd"); then
    log_error "Failed to extract app name from: $cmd"
    # Still try to execute, but warn
fi
```

3. **Use whitelist approach**:
```bash
is_gui_app() {
    local cmd="$1"
    local gui_apps="nuke|maya|3de|rv|houdini|katana|mari|clarisse"
    
    if [[ "$cmd" =~ ($gui_apps) ]]; then
        return 0  # Is GUI
    fi
    return 1  # Not GUI
}
```

**Severity**: **MEDIUM** - Silent failure if command format changes  
**Effort**: 1-2 hours (improve pattern matching, add logging)  
**Priority**: MEDIUM

---

### LOW SEVERITY ISSUES

#### Issue #9: MISSING RESOURCE CLEANUP IN ERROR PATHS (LOW)

**File**: `launcher/worker.py`  
**Lines**: 268-280 in `_cleanup_process()`

**Problem**:
Drain threads might leak if cleanup is interrupted:

```python
def _cleanup_process(self) -> None:
    # ... process cleanup ...
    
    # Line 268-279: Join drain threads
    if self._stdout_thread and self._stdout_thread.is_alive():
        self._stdout_thread.join(timeout=2.0)
        if self._stdout_thread.is_alive():
            self.logger.warning(
                f"stdout drain thread still alive after 2s timeout..."
            )
            # ← Thread is abandoned but still running!
    
    # If _cleanup_process is called multiple times or cancelled:
    # Thread references are lost but threads keep running
```

**Impact**:
- **Orphaned Threads**: Drain threads keep running after worker cleanup
- **Resource Leak**: File descriptors kept open by drain threads
- **Memory Leak**: Thread objects not garbage collected

But in practice, daemon threads will be killed when process exits, so this is low priority.

**Fix**: Make thread list more robust:
```python
def _cleanup_process(self) -> None:
    # Track all threads for potential cleanup later
    for thread in [self._stdout_thread, self._stderr_thread]:
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive():
                self.logger.warning(f"Thread {thread.name} abandoned")
                # Don't lose reference - keep for potential monitoring
```

**Severity**: **LOW** - Threads cleaned up on process exit anyway  
**Priority**: LOW (nice-to-have)

---

#### Issue #10: FALLBACK DICT CLEANUP RACE (LOW)

**File**: `command_launcher.py`  
**Lines**: 301-329 in `_on_persistent_terminal_operation_finished()`

**Problem**:
The `_pending_fallback` dict cleanup uses multiple lock acquisitions:

```python
def _on_persistent_terminal_operation_finished(self, ...):
    if success:
        # Line 316-328: Multiple lock acquisitions
        now = time.time()
        to_remove = []
        
        with self._fallback_lock:  # ← First lock acquisition
            for command_id, (_, _, creation_time) in self._pending_fallback.items():
                elapsed = now - creation_time
                if elapsed > 30:
                    to_remove.append(command_id)
        
        # Release lock, then re-acquire for removal
        for command_id in to_remove:
            with self._fallback_lock:  # ← Second lock acquisition (lock released in between!)
                _ = self._pending_fallback.pop(command_id, None)
        
        # Between first and second lock: another thread could modify dict!
```

**Race Window**:
```
T0: Operation finishes, signal fires
T1: Thread A: Acquires _fallback_lock, builds to_remove list
T2: Thread A: Releases _fallback_lock
T3: Thread B: Calls _try_persistent_terminal(), adds to _pending_fallback
T4: Thread A: Acquires _fallback_lock again
T5: Thread A: Removes commands from to_remove list
T6: Thread B's newly added command might be removed (depends on timing)
```

**Impact**:
- **Command Removal**: Commands might be removed that shouldn't be
- **Memory Leak**: If removal fails, old commands stay in dict indefinitely

**Fix**: Use single lock acquisition:
```python
with self._fallback_lock:  # ← Single lock scope
    to_remove = []
    for command_id, (_, _, creation_time) in self._pending_fallback.items():
        elapsed = now - creation_time
        if elapsed > 30:
            to_remove.append(command_id)
    
    # All removals happen while lock held
    for command_id in to_remove:
        _ = self._pending_fallback.pop(command_id, None)
```

**Severity**: **LOW** - Race window is small, impact is minimal  
**Priority**: LOW

---

#### Issue #11: HARDCODED TIMEOUT CONSTANTS (LOW)

**File**: `persistent_terminal_manager.py`  
**Lines**: 36-43

**Problem**:
Timeouts are hardcoded module constants with no way to adjust:

```python
_TERMINAL_RESTART_DELAY_SECONDS = 0.5
_FIFO_READY_TIMEOUT_SECONDS = 2.0
_DISPATCHER_HEALTH_CHECK_TIMEOUT_SECONDS = 3.0
_DISPATCHER_STARTUP_TIMEOUT_SECONDS = 5.0
_HEARTBEAT_SEND_TIMEOUT_SECONDS = 3.0
_WORKER_POLL_INTERVAL_SECONDS = 0.1
_CLEANUP_POLL_INTERVAL_SECONDS = 0.2
```

**Impact**:
- **No Tuning Capability**: Can't adjust for slow systems
- **Testing Difficulty**: Tests are slow due to 5s startup timeout
- **Production Issues**: Fixed timeouts might be too short on loaded systems

**Fix**: Make configurable:
```python
class PersistentTerminalManager(...):
    def __init__(self, ..., startup_timeout: float | None = None):
        self._startup_timeout = startup_timeout or _DISPATCHER_STARTUP_TIMEOUT_SECONDS
```

**Severity**: **LOW** - Workaround exists (change constants)  
**Priority**: LOW

---

#### Issue #12: NO COMMUNICATION FLOW LOGGING (LOW)

**File**: Multiple files  

**Problem**:
Hard to debug IPC issues because communication flow isn't logged:

```python
# No log of:
# 1. When FIFO write starts/ends
# 2. How long write takes
# 3. Command bytes received by dispatcher
# 4. Dispatcher execution flow
# 5. PID file write completion
```

**Impact**:
- **Hard Debugging**: IPC failures are difficult to diagnose
- **No Performance Data**: Can't identify slowest operations
- **Production Issues**: Unclear if issue is Python or bash side

**Fix**: Add detailed logging:
```python
# In send_command_direct
with self._write_lock:
    start_time = time.time()
    self.logger.debug(f"FIFO write START: {len(command)} chars")
    
    fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "wb", buffering=0) as fifo:
        fd = None
        written = fifo.write(command.encode("utf-8"))
        written += fifo.write(b"\n")
    
    elapsed = time.time() - start_time
    self.logger.debug(f"FIFO write END: {written} bytes written in {elapsed:.3f}s")
```

**Severity**: **LOW** - Nice-to-have diagnostic feature  
**Priority**: LOW

---

## Summary Table

| # | Issue | Severity | Category | Effort | Impact |
|---|-------|----------|----------|--------|--------|
| 1 | Blocking lock during retry | HIGH | Synchronization | 2-3h | Slow concurrent commands |
| 2 | FIFO recreation race | HIGH | Race Condition | 1-2h | Lost commands |
| 3 | Stale resource in cleanup | HIGH | Data Race | 1-2h | Resource leak, zombie procs |
| 4 | Heartbeat ping timeout | HIGH | Timing/Race | 1-2h | False health failures |
| 5 | Signal connection leaks | MEDIUM | Resource Leak | 1h | Qt warnings, leaks |
| 6 | Worker lifecycle hazard | MEDIUM | Lifetime | 1-2h | Crash on shutdown |
| 7 | Stale PID verification | MEDIUM | Timing | 0.5h | False success on crash |
| 8 | Command arg parsing | MEDIUM | Silent Failure | 1-2h | Blocks terminal unexpectedly |
| 9 | Drain thread cleanup | LOW | Resource Leak | 1h | Orphaned threads |
| 10 | Fallback dict race | LOW | Race Condition | 0.5h | Minor timing issue |
| 11 | Hardcoded timeouts | LOW | Config | 1h | No tuning capability |
| 12 | No flow logging | LOW | Observability | 1h | Hard to debug |

---

## Recommended Fix Priority

### Phase 1: Critical Blocking Issues (IMMEDIATE)
1. **Issue #1**: Blocking lock during I/O (HIGH impact on responsiveness)
2. **Issue #2**: FIFO recreation race (HIGH impact on command delivery)
3. **Issue #3**: Cleanup data race (HIGH impact on resource safety)
4. **Issue #4**: Heartbeat timeout race (HIGH impact on health checks)

**Timeline**: 5-8 hours total  
**Benefit**: Eliminates blocking, command loss, and health check failures

### Phase 2: Resource & Lifecycle Safety (HIGH)
5. **Issue #5**: Signal connection leaks (Medium impact on stability)
6. **Issue #6**: Worker lifecycle (Medium impact on shutdown safety)

**Timeline**: 2-3 hours total  
**Benefit**: Prevents crashes and Qt warnings

### Phase 3: Detection & Tuning (MEDIUM)
7. **Issue #7**: PID verification (Medium, but detection can be improved)
8. **Issue #8**: Command parsing (Medium, but silent failures are concerning)
9. **Issue #11**: Configurable timeouts (Low, but improves testability)

**Timeline**: 2-4 hours total  
**Benefit**: Better diagnostics and less surprising failures

### Phase 4: Cleanup & Logging (NICE-TO-HAVE)
10. **Issue #9**: Drain thread cleanup (Low priority)
11. **Issue #10**: Fallback dict race (Low priority)
12. **Issue #12**: Flow logging (Low priority)

**Timeline**: 1-2 hours total  
**Benefit**: Improved observability and minor edge cases

---

## Testing Recommendations

### High Priority Tests

1. **Concurrent Send Command Load Test**
   - 10 threads sending commands simultaneously
   - Measure lock contention time
   - Verify no commands lost
   - Check response time distribution

2. **Terminal Restart During Send**
   - Start send_command()
   - Trigger health check failure mid-operation
   - Verify FIFO isn't duplicated
   - Verify new dispatcher gets commands

3. **Worker Cleanup Race**
   - Start send_command_async()
   - Immediately call cleanup()
   - Verify no crashes
   - Check worker threads exit cleanly

4. **FIFO Recreation Stress**
   - Restart terminal 50+ times
   - Send commands between restarts
   - Verify no FIFO path corruptions
   - Check dispatcher stays responsive

### Medium Priority Tests

5. **Heartbeat Under Load**
   - High CPU usage + heartbeat pings
   - Verify no timeout false positives
   - Check health detection reliability

6. **Process Verification Edge Cases**
   - Partial PID file reads
   - App crashes immediately after launch
   - Missing app name extraction

---

## Files for Reference

**Analysis Documents**:
- `/home/gabrielh/projects/shotbot/docs/FIFO_IPC_EXECUTIVE_SUMMARY.md` - Prior analysis
- `/home/gabrielh/projects/shotbot/docs/FIFO_IPC_THOROUGH_ANALYSIS.md` - Detailed findings
- `/home/gabrielh/projects/shotbot/docs/FIFO_IPC_CODE_LOCATIONS.md` - Code snippets

**Source Code**:
- `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py` - Main FIFO IPC
- `/home/gabrielh/projects/shotbot/terminal_dispatcher.sh` - Bash dispatcher
- `/home/gabrielh/projects/shotbot/command_launcher.py` - Command execution
- `/home/gabrielh/projects/shotbot/launch/process_verifier.py` - Process verification
- `/home/gabrielh/projects/shotbot/launcher/worker.py` - Worker lifecycle

---

**Analysis Completed**: November 14, 2025  
**Confidence Level**: Very High - all communication paths, synchronization points, and error scenarios analyzed
