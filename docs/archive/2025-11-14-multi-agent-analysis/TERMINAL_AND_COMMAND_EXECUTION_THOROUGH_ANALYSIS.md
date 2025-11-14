# Terminal and Command Execution System - Very Thorough Analysis

## Executive Summary

Shotbot uses a sophisticated **persistent terminal + dispatcher system** for command execution. The architecture involves:

1. **PersistentTerminalManager** (Python) - Manages terminal lifecycle via FIFO
2. **terminal_dispatcher.sh** (Bash) - Reads commands from FIFO, executes them
3. **CommandLauncher** (Python) - High-level launch API
4. **ProcessExecutor** (Python) - Routes commands to terminal
5. **ProcessVerifier** (Python) - Phase 2 verification of process startup

**Key Challenge**: Coordinating asynchronous I/O (FIFO), subprocess lifecycle, Qt signals, and thread safety across 3 different execution environments (Python, Bash, Qt).

---

## 1. Terminal Session Lifecycle

### 1.1 Session Creation

**Entry Point**: `PersistentTerminalManager.__init__()`

```
User creates PersistentTerminalManager (e.g., in MainWindow)
  ↓
__init__ sets up paths, state variables, locks
  ↓
_ensure_fifo(open_dummy_writer=False)  # Don't open writer yet - no reader running
  ├─ Remove any existing FIFO file (not a real FIFO)
  ├─ os.mkfifo() create new FIFO
  ├─ Verify path is FIFO (stat + S_ISFIFO check)
  └─ DON'T open dummy writer (reader not running yet)
  ↓
ProcessVerifier.cleanup_old_pid_files()  # Phase 2 setup
  ↓
Register instance in _test_instances (for test cleanup)
```

**Critical Detail**: FIFO is created but NOT opened for writing during __init__. Why?

- Opening a write-only FIFO with no reader causes **ENXIO error** (errno 6)
- Dispatcher (reader) hasn't started yet
- Dummy writer FD opened only after dispatcher starts (in restart_terminal())

### 1.2 Terminal Launch

**Triggered By**: First send_command() when terminal not running

```
send_command(cmd, ensure_terminal=True)
  ↓
_ensure_dispatcher_healthy()  # Health check + recovery
  ├─ _is_dispatcher_healthy()  # Check health (return True if already running)
  │  ├─ _is_dispatcher_alive()  # Process exists and not zombie?
  │  ├─ _is_dispatcher_running()  # FIFO has reader?
  │  └─ _check_heartbeat()  # Recent heartbeat?
  │
  └─ If unhealthy:
     ├─ Check restart attempts < max (3 by default)
     ├─ If exceeded: Enter FALLBACK MODE (disabled for 5 minutes)
     └─ Else: restart_terminal()
        │
        ├─ close_terminal()  # Kill existing terminal
        ├─ _close_dummy_writer_fd()  # Close write FD
        │
        ├─ ATOMIC FIFO REPLACEMENT
        │  ├─ Check old FIFO exists
        │  ├─ os.unlink() remove old FIFO
        │  ├─ os.fsync() parent dir (ensure unlink committed to disk)
        │  ├─ os.mkfifo(temp_fifo)  # Create temp with unique name
        │  └─ os.rename(temp_fifo, final_fifo)  # ATOMIC rename
        │
        ├─ _launch_terminal()
        │  ├─ Try multiple terminal emulators (gnome-terminal, konsole, xterm)
        │  ├─ subprocess.Popen([terminal_cmd + dispatcher_script])
        │  ├─ sleep(0.5)  # Give terminal time to start
        │  ├─ Poll for dispatcher PID in child processes (5s timeout)
        │  └─ Emit terminal_started signal with PID
        │
        └─ Wait for _is_dispatcher_running() with timeout (5s)
           ├─ Poll every 0.2s
           └─ Once running:
              ├─ _open_dummy_writer()  # NOW safe to open write-only
              │  ├─ os.open(FIFO, O_WRONLY | O_NONBLOCK)
              │  └─ Store FD in _dummy_writer_fd
              └─ Return True
```

**Resource Management**:
- Terminal subprocess tracked via `self.terminal_process` and `self.terminal_pid`
- Dispatcher PID tracked separately (child of terminal)
- Dummy writer FD tracked in `self._dummy_writer_fd`

**Thread Safety**: Terminal launch runs in worker thread (TerminalOperationWorker) but protected by _write_lock and _state_lock

### 1.3 Session Termination

**Triggered By**: 
- User closes app
- Manual call to close_terminal()
- Health check failure with max restarts exceeded

```
close_terminal()
  ├─ If dispatcher running:
  │  ├─ send_command("EXIT_TERMINAL", ensure_terminal=False)  # Graceful
  │  └─ wait(0.5s)
  │
  ├─ If still alive:
  │  ├─ os.kill(terminal_pid, SIGTERM)  # Terminate
  │  ├─ wait(0.5s)
  │  ├─ If still alive:
  │  │  └─ os.kill(terminal_pid, SIGKILL)  # Force kill
  │  └─ Cleanup state variables
  │
  └─ Emit terminal_closed signal
```

**Graceful vs Forced Shutdown**:
- Graceful: Try EXIT_TERMINAL command first (dispatcher cleanup)
- Forced: Kill terminal process (dispatcher dies with it)

---

## 2. FIFO Creation/Deletion Patterns

### 2.1 Race Conditions & Crash Recovery

**Problem**: Terminal crash leaves stale FIFO

**Scenario**:
```
1. Terminal running, FIFO open, reader on FD 3
2. Terminal crashes
3. FIFO still exists (is_fifo=True)
4. But reader is gone (FD 3 closed)
5. Next send_command() gets ENXIO (no reader)
```

**Solution**: Atomic FIFO recreation in restart_terminal()

```
Atomic Replacement:
1. Close dummy writer FD (prevents FIFO from staying alive)
2. os.unlink(FIFO)  # Remove old FIFO
3. os.fsync(parent_dir)  # Force filesystem sync (critical on WSL)
4. os.mkfifo(TEMP_FIFO)  # Create with unique name
5. os.rename(TEMP_FIFO, FINAL_FIFO)  # Atomic swap
```

**Why atomic?**
- Prevents race where dispatcher starts between unlink + mkfifo
- Ensures FIFO state is consistent (either old or new, never partial)

### 2.2 FIFO Lifecycle on Crash

**Before Recovery**:
```
FIFO exists (stale): /tmp/shotbot_commands.fifo
  ├─ Not a true reader/writer situation
  ├─ FD 3 is closed (terminal dead)
  ├─ Write attempts return ENXIO
  └─ Locked out of communication
```

**Recovery Steps**:
1. Close dummy writer FD (_close_dummy_writer_fd)
   - Prevents FIFO from staying alive artificially
2. Delete stale FIFO (os.unlink)
3. fsync parent dir (ensure durability)
4. Create new FIFO via atomic temp→rename
5. Launch new terminal with dispatcher
6. Wait for dispatcher to start
7. Open new dummy writer FD

### 2.3 FIFO vs Dummy Writer

**Dummy Writer FD** (`_dummy_writer_fd`):
- Purpose: Keep FIFO alive to prevent EOF
- Opened ONLY after dispatcher (reader) starts
- Closed when terminal shuts down

**Why Needed?**:
```
FIFO behavior:
- If all readers close: remaining writers get EOF on write
- If all writers close: all readers get EOF
- With no dummy writer: each command closes its write FD
  → Reader could get EOF between commands
  → Next command fails with ENXIO

WITH dummy writer:
- Dummy writer keeps write side open
- Reader never sees EOF between commands
- Commands can keep arriving indefinitely
```

---

## 3. Command Execution Flow (UI to Terminal to Verification)

### 3.1 Complete End-to-End Flow

**Phase 1: Queueing & Execution**

```
User clicks "Launch Nuke" button
  ↓
MainWindow.LauncherPanel signal
  ↓
CommandLauncher.launch_app(app_name="nuke", context=...)
  ├─ Validate shot is selected
  ├─ Build workspace setup + rez wrapping + logging
  ├─ Result: full_command = "rez env nuke -- bash -ilc \"ws /path && nuke\""
  │
  └─ _execute_launch(full_command, app_name="nuke")
     ├─ _try_persistent_terminal(full_command, "nuke")
     │  ├─ Check persistent terminal enabled + not in fallback
     │  ├─ Store in _pending_fallback[timestamp] = (cmd, "nuke")  # For retry
     │  └─ persistent_terminal.send_command_async(full_command)
     │
     └─ If persistent terminal fails → _launch_in_new_terminal()
```

**Async Send in PersistentTerminalManager**:

```
send_command_async(full_command)
  ├─ Validate command (not empty, ASCII)
  ├─ Check fallback mode (if enabled, return False)
  ├─ Emit command_queued(timestamp, cmd)  # Phase 1
  │
  ├─ Create TerminalOperationWorker(parent=self)  # Qt ownership
  ├─ Store in _active_workers[worker]  # Prevent GC
  │
  ├─ Connect signals:
  │  ├─ worker.progress → _on_progress()
  │  ├─ worker.operation_finished → _on_async_command_finished()
  │  └─ worker.operation_finished → cleanup_worker() (remove from _active_workers)
  │
  ├─ Emit operation_started("send_command")
  └─ worker.start()  # Begin in background thread
```

**Worker Thread Execution**:

```
TerminalOperationWorker.run()  [runs in QThread]
  └─ _run_send_command()
     ├─ Emit progress("Checking terminal health...")
     │
     ├─ _ensure_dispatcher_healthy()  # May restart terminal
     │  └─ This blocks in thread until terminal ready (5s timeout)
     │
     ├─ Emit command_executing(timestamp)  # Phase 1
     ├─ Record enqueue_time = time.time()
     │
     ├─ _send_command_direct(full_command)
     │  ├─ Hold _write_lock
     │  ├─ os.open(FIFO, O_WRONLY | O_NONBLOCK)  # Non-blocking
     │  ├─ fdopen(fd, "wb", buffering=0)  # Binary, unbuffered
     │  ├─ Write command + newline
     │  └─ Release _write_lock
     │
     └─ Call _process_verifier.wait_for_process()  # Phase 2
        ├─ Extract app_name from command ("nuke")
        ├─ Poll for PID file (5s timeout, 0.2s interval)
        │  └─ Check /tmp/shotbot_pids/nuke_YYYYMMDD_HHMMSS.pid
        ├─ Verify process exists (psutil.Process)
        │
        ├─ If success: Emit command_verified(timestamp, f"Process verified (PID: {pid})")
        └─ If fail: Emit command_error(timestamp, f"Verification failed: {reason}")
```

### 3.2 FIFO Write Operation

**Critical Section**:

```python
with self._write_lock:  # Serialize writes + health checks
    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
        fifo_fd = None  # fdopen now owns FD
        fifo.write(command.encode("utf-8"))
        fifo.write(b"\n")
    # fdopen automatically closes FD on exit
```

**Resource Leak Prevention**:
```python
fd = None
try:
    # ...
    with os.fdopen(fd, "wb", buffering=0) as fifo:
        fd = None  # fdopen owns FD now
        # Write happens here
except OSError as e:
    if fd is not None:  # fdopen failed to take ownership
        os.close(fd)  # Clean up manually
    # Handle error
```

**Error Handling**:
- `ENXIO` (errno 6): No reader (dispatcher crashed)
  → Set dispatcher_pid = None (trigger health check next call)
- `EAGAIN` (errno 11): Would block (buffer full)
  → Warning logged, return False
- `ENOENT` (errno 2): FIFO missing
  → Recreate with _ensure_fifo(), retry once

**Thread Safety**:
- _write_lock held during open + write + close
- Prevents interleaved writes (FIFO reads line-oriented)
- Also protects health check + write as atomic operation

### 3.3 Dispatcher Processing

**Bash Loop** (in terminal_dispatcher.sh):

```bash
exec 3< "$FIFO"  # Open persistent reader on FD 3

while true; do
    if read -r cmd <&3; then  # Read from FD 3
        # Sanity checks
        if [ -z "$cmd" ]; then continue; fi  # Skip empty
        if [ ${#cmd} -lt 3 ]; then continue; fi  # Too short
        
        # Special commands
        if [ "$cmd" = "EXIT_TERMINAL" ]; then exit 0; fi
        if [ "$cmd" = "CLEAR_TERMINAL" ]; then clear; continue; fi
        if [ "$cmd" = "__HEARTBEAT__" ]; then echo "PONG" > heartbeat_file; continue; fi
        
        # Execute command
        if is_gui_app "$cmd"; then
            eval "$cmd &"  # Background
            gui_pid=$!
            
            # Phase 2: Write PID file for verification
            app_name=$(extract_app_name "$cmd")
            timestamp=$(date '+%Y%m%d_%H%M%S')
            pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
            echo "$gui_pid" > "$pid_file"
        else
            eval "$cmd"  # Foreground (blocking)
        fi
    else
        break  # EOF on read (all writers closed)
    fi
done
```

**Critical Loop Behavior**:
- FD 3 kept open across iterations
- If command execution closes all write FDs:
  → bash read would get EOF
  → Loop exits
- **Solution**: Dummy writer FD keeps one write-only FD open always

### 3.4 Process Verification (Phase 2)

**Dispatcher Writes PID**:
```bash
# After backgrounding GUI app
echo "$gui_pid" > "/tmp/shotbot_pids/nuke_20251114_123456.pid"
```

**ProcessVerifier Polls**:

```python
wait_for_process(command, enqueue_time=time.time())
  ├─ Extract app_name = "nuke"
  ├─ Start polling
  │
  └─ Loop for timeout (5s):
     ├─ List /tmp/shotbot_pids/nuke_*.pid
     ├─ For each file:
     │  ├─ Check file mtime > enqueue_time  # Skip stale PIDs
     │  ├─ Parse PID from file
     │  ├─ psutil.Process(pid).is_running()  # Verify exists
     │  │
     │  └─ If found + running:
     │     └─ Return (True, f"Process verified (PID: {pid})")
     │
     ├─ Sleep 0.2s
     └─ Retry
```

**Why enqueue_time?**
- Multiple Nuke instances may run
- PID files accumulate (not cleaned up immediately)
- enqueue_time filters out stale files from previous launches
- Conservative estimate: current_time - timeout if not provided

---

## 4. Error Propagation & Handling

### 4.1 Error Signal Path

```
send_command_async() fails
  ↓
Worker thread catches exception
  │
  ├─ operation_finished.emit(False, error_msg)
  │
  ├─ Propagated to:
  │  ├─ CommandLauncher._on_persistent_terminal_operation_finished()
  │  │  ├─ Check if in _pending_fallback
  │  │  └─ If failed: retry with _launch_in_new_terminal()
  │  │
  │  ├─ MainWindow (connected to PersistentTerminalManager signals)
  │  │  └─ Update UI (status bar, log viewer)
  │  │
  │  └─ Test fixtures (for cleanup)
  │
  └─ Results in:
     ├─ Fallback terminal window launched
     ├─ User sees error in log viewer
     └─ Next command may retry persistent terminal
```

### 4.2 Health Check Failure Handling

```
_is_dispatcher_healthy() returns False
  ├─ _restart_attempts += 1
  │
  ├─ If _restart_attempts > max (3):
  │  ├─ _fallback_mode = True
  │  ├─ _fallback_entered_at = time.time()
  │  └─ Return False (fallback activated)
  │
  └─ Else:
     ├─ Close existing terminal (force kill)
     ├─ restart_terminal()
     ├─ Wait for recovery (5s timeout)
     ├─ If successful: _restart_attempts = 0 (reset counter)
     └─ Return True/False
```

**Fallback Recovery**:
- After 5 minutes cooldown, next send_command() checks cooldown expiry
- If expired: Attempts one recovery attempt
- If successful: Leaves fallback mode, resumes persistent terminal

### 4.3 Common Errors & Resolution

| Error | Errno | Cause | Resolution |
|-------|-------|-------|-----------|
| ENXIO | 6 | No reader (dispatcher dead) | Set dispatcher_pid=None, trigger health check |
| EAGAIN | 11 | FIFO buffer full | Logged, command fails |
| ENOENT | 2 | FIFO missing | Recreate with _ensure_fifo() |
| EBADF | 9 | FD already closed | Idempotent close, no error |
| EPIPE | 32 | Reader closed write | Signals error in dispatcher |

---

## 5. Signal Connections & Slot Implementations

### 5.1 Signal Hierarchy

```
PersistentTerminalManager (source of truth)
  ├─ terminal_started(int)  # PID
  ├─ terminal_closed()
  ├─ command_sent(str)
  ├─ command_queued(str, str)        # Phase 1: timestamp, cmd
  ├─ command_executing(str)          # Phase 1: timestamp
  ├─ command_verified(str, str)      # Phase 2: timestamp, message
  ├─ command_error(str, str)         # Phase 2: timestamp, error
  ├─ operation_progress(str, str)    # operation_name, message
  ├─ operation_finished(str, bool, str)  # operation_name, success, message
  └─ command_result(bool, str)       # Backward compat

    ↓ Connected to

CommandLauncher
  ├─ command_queued → _on_command_queued()
  ├─ command_executing → _on_command_executing()
  ├─ command_verified → _on_command_verified() [emits command_executed]
  ├─ command_error → _on_command_error_internal() [emits command_error]
  └─ operation_finished → _on_persistent_terminal_operation_finished() [fallback retry]

    ↓ Connected to

MainWindow
  ├─ command_executed → log_viewer.append()
  ├─ command_error → show_error_notification()
  └─ operation_* → update UI status

    ↓ Also connected to

ProcessExecutor
  ├─ command_result → _on_terminal_command_result()
  └─ operation_progress → _on_terminal_progress()
```

### 5.2 Signal Thread Safety

**Qt Signal/Slot Mechanism** (Queued Connection):
```
Worker Thread                          Main Thread
  │
  ├─ signal.emit(...)                 
  │  └─ Queue event to main thread     Main event loop
  │                                      ├─ Process queued events
  │  Slot triggered in main thread     └─ Call slot (safe)
  │
  └─ Continue immediately (returns)
```

**Why Safe**:
- Signals auto-convert to Qt::QueuedConnection when emitted from different thread
- Slot always runs in main thread (where UI updates are safe)
- No race conditions on Qt objects

**Signals Used from Worker Thread**:
- `operation_finished` (emitted by worker in run())
- `command_executing` (emitted by worker in run())
- `command_verified` (emitted by worker in run())
- `command_error` (emitted by worker in run())

---

## 6. Background Process Tracking & Cleanup

### 6.1 Active Workers Lifecycle

**Creation**:
```python
worker = TerminalOperationWorker(self, "send_command", parent=self)
worker.command = command

with self._workers_lock:
    self._active_workers.append(worker)  # Prevent GC

worker.start()  # Launch in background thread
```

**Connections**:
```python
worker.operation_finished.connect(self._on_async_command_finished)
worker.operation_finished.connect(cleanup_worker)
```

**Cleanup**:
```python
def cleanup_worker() -> None:
    with self._workers_lock:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
    worker.deleteLater()  # Qt deferred deletion
```

**Why Deferred Deletion?**
- Worker might still be running when slot called
- deleteLater() marks for deletion after current event processed
- Prevents "deleting object while thread running" crash

### 6.2 Cleanup Sequence on App Exit

**Order Matters**:

```python
def cleanup():
    # 1. STOP ALL WORKERS FIRST
    with _workers_lock:
        workers = list(_active_workers)
    
    for worker in workers:
        worker.requestInterruption()
        if not worker.wait(2000):  # 2s timeout
            worker.terminate()
            worker.wait(1000)  # 1s for termination
    
    _active_workers.clear()
    
    # 2. THEN cleanup terminal
    if _is_terminal_alive():
        close_terminal()
    
    _close_dummy_writer_fd()
    
    # 3. FINALLY cleanup FIFO
    unlink(FIFO)
```

**Why This Order?**
1. Workers might call manager methods (_ensure_dispatcher_healthy, etc.)
2. If workers keep running during terminal cleanup → deadlock on locks
3. Need state locks to remain valid until workers stop

### 6.3 Resource Cleanup Guarantees

**File Descriptors**:
- Dummy writer FD: Closed in _close_dummy_writer_fd() (idempotent)
- FIFO write FDs: Closed by context manager in _send_command_direct()
- FIFO read FD: Closed by dispatcher on shutdown

**Processes**:
- Terminal process: Killed by close_terminal() (SIGTERM then SIGKILL)
- Dispatcher: Dies with terminal
- Backgrounded GUI apps: Not killed (intentional - user continues working)

**FIFO File**:
- Removed in cleanup() (idempotent)
- Left in __del__() to support terminal staying open after app exit

---

## 7. Edge Cases & Race Conditions

### 7.1 FIFO EOF Race

**Scenario**:
```
1. Worker thread calls _send_command_direct()
2. Command writes to FIFO
3. Dispatcher finishes processing (eval completes)
4. Dispatcher's reader loops back to read -r cmd <&3
5. Meanwhile: Main thread calls close_terminal()
6. close_terminal() closes dummy writer FD
7. Dispatcher sees EOF on FD 3
8. Loop exits, dispatcher dies
9. Next _send_command_direct() gets ENXIO
```

**Mitigation**:
- Lock serialization (_write_lock) ensures atomic health check + write
- Health check verifies dispatcher alive BEFORE write attempt
- If dispatcher dies between check and write: ENXIO caught, health check triggered on next command
- Fallback mechanism eventually activated if restarts exceed max

### 7.2 Interleaved Command Corruption

**Problem**:
```
Thread A calls send_command_direct("command_a")
  ├─ Opens FD, starts writing
  ├─ Writes: "com"
  │
  └─ Thread B calls send_command_direct("command_b")
     └─ Opens new FD, writes: "mand_bcommand_a_rest"
       → Dispatcher reads corrupted: "command_bcommand_a_rest"
```

**Solution**: _write_lock serializes ALL writes
```python
with self._write_lock:
    fd = os.open(FIFO, O_WRONLY | O_NONBLOCK)
    with os.fdopen(fd, "wb", buffering=0) as fifo:
        fifo.write(...)  # Atomic from other thread perspective
```

### 7.3 Terminal Restart During Send

**Scenario**:
```
1. send_command() acquires _write_lock
2. Health check passes (dispatcher alive)
3. Meanwhile: Worker thread calls _ensure_dispatcher_healthy()
   ├─ Health check fails (timeout)
   ├─ Waits for _state_lock (held in send_command)
   └─ DEADLOCK potential!
```

**Mitigation**:
- _write_lock held DURING health check + FIFO write (atomic)
- _state_lock separate from _write_lock (no nested lock requirements)
- If _state_lock contested: one thread waits, other proceeds
- No circular wait possible (well-ordered locks)

### 7.4 Test Isolation Issue

**Problem**: Singleton PersistentTerminalManager persists between tests
- Previous test's terminal subprocess left running
- Next test creates new manager instance
- Old terminal and FIFO conflict with new one

**Solution**:
```python
# In conftest.py
@pytest.fixture(autouse=True)
def cleanup_managers():
    yield
    PersistentTerminalManager.cleanup_all_instances()

# In PersistentTerminalManager
@classmethod
def cleanup_all_instances(cls):
    with cls._test_instances_lock:
        instances = list(cls._test_instances)
    
    for instance in instances:
        instance.cleanup()
```

---

## 8. Implementation Issues & Concerns

### 8.1 Potential Issues

| Issue | Severity | Location | Impact |
|-------|----------|----------|--------|
| FIFO disappears after unlink race | MEDIUM | restart_terminal() | Next write gets ENOENT |
| Worker cleanup timing | MEDIUM | cleanup() | Deadlock if workers block |
| Dummy writer FD leak on exception | LOW | _ensure_fifo() | FD accumulation |
| Stale PID files accumulate | LOW | terminal_dispatcher.sh | Storage waste |
| Heartbeat file not cleaned on crash | LOW | terminal_dispatcher.sh | File accumulation |

### 8.2 Race Condition Matrix

```
Scenario: Terminal crashes, multiple threads try to send

Thread A (send_command)        Thread B (worker health check)
  ├─ _write_lock acquired
  ├─ Health check starts
  │  └─ _is_dispatcher_healthy() → False
  │
  ├─ Waits for _state_lock        ← Thread B tries _state_lock
  │  (held by Thread B)              └─ Waits for Thread A to exit
  │
  └─ POTENTIAL DEADLOCK
     (if _write_lock held while acquiring _state_lock)

ACTUAL CODE:
  _write_lock
    └─ _ensure_dispatcher_healthy()
       └─ Calls _state_lock
          └─ _restart_attempts += 1

NO DEADLOCK because:
  - _state_lock only held during brief updates
  - No circular wait (_write_lock → _state_lock is unidirectional)
  - _state_lock operations are fast (< 1ms)
```

### 8.3 Resource Leak Scenarios

**Dummy Writer FD Leak**:
```
_open_dummy_writer() called but fails
  └─ os.open() returns FD
  └─ Exception raised BEFORE storing in _dummy_writer_fd
  └─ FD leaked (never closed)

CURRENT CODE:
  try:
      self._dummy_writer_fd = os.open(...)  # Assignment happens
      self._fd_closed = False
      return True
  except OSError:
      return False  # FD not assigned, not leaked

SAFE because assignment happens before exception risk
```

**Subprocess Leak on Exception**:
```
_launch_terminal() in Popen exception handler
  ├─ FileNotFoundError raised
  ├─ proc object partially created
  └─ pid tracked but process NOT cleaned up

CURRENT CODE:
  for cmd in terminal_commands:
      try:
          proc = subprocess.Popen(cmd, start_new_session=True)
          pid = proc.pid
          # Store immediately under lock
          with self._state_lock:
              self.terminal_process = proc
              self.terminal_pid = pid
          # Process now tracked for cleanup
      except FileNotFoundError:
          continue  # Try next terminal

SAFE because even failed Popen processes cleaned up by OS
```

---

## 9. Verification Points

### 9.1 Phase 1 (Command Queuing & Execution)

**Signals Emitted**:
1. `command_queued(timestamp, cmd)` - Command queued for execution
2. `command_executing(timestamp)` - Execution started in terminal

**Guarantees**:
- Command written to FIFO
- Dispatcher read and began processing
- GUI app backgrounded (if applicable)

### 9.2 Phase 2 (Process Verification)

**Signals Emitted**:
1. `command_verified(timestamp, message)` - Process started successfully
2. `command_error(timestamp, error)` - Process failed to start or verification timeout

**Guarantees**:
- GUI app PID found in /tmp/shotbot_pids/
- Process exists (verified with psutil)
- User can interact with application

### 9.3 Fallback Mechanism

**Triggers**:
- Persistent terminal in fallback mode
- Operation fails + pending command exists

**Behavior**:
- Stores failed command in `_pending_fallback[timestamp]`
- On failure, retries with new terminal window (synchronous)
- Older pending commands cleared after 30s (time-based cleanup)

---

## 10. Complete Command Lifecycle Trace

### User Initiates "Launch Nuke"

```
T0.0:  User clicks "Launch Nuke" button
  ↓
T0.1:  MainWindow.LauncherPanel emits signal
  ↓
T0.2:  CommandLauncher.launch_app(app_name="nuke")
       ├─ Validate shot selected: ✓
       ├─ Build command: "rez env nuke -- bash -ilc \"ws /path && nuke\""
       ├─ Emit to log: "Using rez environment with packages: nuke"
       └─ Call _execute_launch()
  ↓
T0.3:  _try_persistent_terminal(full_cmd, "nuke")
       ├─ Check enabled: ✓
       ├─ Check not fallback: ✓
       ├─ Store in _pending_fallback[T0.3] = (cmd, "nuke")
       └─ persistent_terminal.send_command_async(cmd)
  ↓
T0.4:  PersistentTerminalManager.send_command_async()
       ├─ Validate command: ✓ (not empty, ASCII)
       ├─ Emit command_queued(T0.4, cmd[:100]...)
       ├─ Create TerminalOperationWorker(parent=self)
       ├─ Store in _active_workers
       ├─ Connect signals
       └─ worker.start()  # Begin in background thread
  ↓
T0.5:  [Main Thread] Emit operation_started("send_command")
       └─ UI shows "Sending command..."
  ↓
T0.6:  [Worker Thread] TerminalOperationWorker.run()
       ├─ _run_send_command()
       │  ├─ Emit progress("Sending command: ws /path...")
       │  ├─ _ensure_dispatcher_healthy()
       │  │  ├─ _is_dispatcher_healthy(): Check if alive
       │  │  ├─ _is_dispatcher_alive(): Check process exists
       │  │  └─ _is_dispatcher_running(): Send heartbeat ping
       │  │
       │  ├─ If healthy: Continue
       │  ├─ If unhealthy:
       │  │  ├─ _restart_attempts += 1
       │  │  ├─ If attempts > 3: Enter FALLBACK MODE
       │  │  └─ Else: restart_terminal()
       │  │     ├─ close_terminal()
       │  │     ├─ Atomic FIFO recreation
       │  │     └─ _launch_terminal()
       │  │        ├─ Popen([gnome-terminal, bash, dispatcher.sh])
       │  │        ├─ Poll for dispatcher PID
       │  │        └─ Emit terminal_started(new_pid)
       │  │
       │  ├─ Emit command_executing(T0.6)
       │  ├─ Record enqueue_time = T0.6
       │  │
       │  └─ _send_command_direct(cmd)
       │     ├─ Acquire _write_lock
       │     ├─ os.open(FIFO, O_WRONLY | O_NONBLOCK)
       │     ├─ Write command + newline
       │     └─ Release _write_lock
       │     └─ Return True
       │
       └─ _process_verifier.wait_for_process(cmd, enqueue_time=T0.6)
          ├─ Extract app_name = "nuke"
          ├─ Poll /tmp/shotbot_pids/nuke_*.pid (5s timeout)
          │
          └─ If found + running:
             ├─ Emit command_verified(T0.7, "Process verified (PID: 12345)")
             ├─ Return (True, "...")
             │
             └─ operation_finished.emit(True, "Verified: ...")
  ↓
T0.7:  [Main Thread] _on_async_command_finished(True, "Verified...")
       ├─ command_result.emit(True, "")
       ├─ operation_finished.emit("send_command", True, "...")
       └─ cleanup_worker()
          ├─ Remove worker from _active_workers
          └─ worker.deleteLater()
  ↓
T0.8:  [Main Thread] CommandLauncher._on_command_verified(T0.7, "Process verified (PID: 12345)")
       └─ command_executed.emit(T0.7, "✓ Command verified: Process verified (PID: 12345)")
  ↓
T0.9:  [Main Thread] MainWindow receives signals
       ├─ log_viewer.append("[T0.7] ✓ Command verified: Process verified (PID: 12345)")
       └─ UI shows command executed
  ↓
T0.10: [Dispatcher] Processes command
       ├─ read -r cmd <&3  # Read: "rez env nuke -- bash ..."
       ├─ is_gui_app? Yes
       ├─ eval "rez env nuke -- bash -ilc \"ws /path && nuke\""  &
       │  └─ Nuke process launches, backgrounded
       │  └─ gui_pid = 12345
       ├─ extract_app_name = "nuke"
       ├─ Write PID file: /tmp/shotbot_pids/nuke_20251114_123456.pid
       │  └─ Contains: 12345
       └─ Display: "✓ Launched in background (PID: 12345)"
  ↓
T0.11: Nuke window appears
       └─ User can interact with application
```

---

## 11. Known Limitations & TODOs

### 11.1 Open Tickets (from code comments)

**Line 1218-1221** (restart_terminal):
```python
# TODO: Add tests for:
#   - TerminalOperationWorker Qt lifecycle with parent parameter
#   - Atomic FIFO recreation under race conditions
#   - FD leak prevention in _send_command_direct()
```

### 11.2 Architectural Decisions

**Single Write Lock** vs **Per-FIFO Lock**:
- Current: Single _write_lock for all FIFO operations
- Pro: Simple, prevents interleaving
- Con: All threads serialize on same lock (contention)
- Alternative: Per-cache-type locks (more complex)

**FIFO Capacity**:
- Linux default: 65536 bytes (system-dependent)
- No backpressure handling if buffer full
- Long commands might fail with EAGAIN

**Terminal Emulator Selection**:
- Tries: gnome-terminal, konsole, xterm, x-terminal-emulator
- If all fail: Fallback to bash -ilc (non-interactive)
- No verification that terminal actually showed window

---

## 12. Summary Table

| Component | Lifecycle | Thread Safe | Resource Management |
|-----------|-----------|-------------|-------------------|
| **PersistentTerminalManager** | Init → Idle → Exec → Cleanup | Yes (_write_lock, _state_lock) | Terminal process, FIFO, dummy writer FD |
| **TerminalOperationWorker** | Create → Run → Finished → Delete | Yes (signals queued to main) | Worker thread, subprocess during launch |
| **FIFO** | Created on init, recreated on crash | Yes (atomic replacement) | File at /tmp/shotbot_commands.fifo |
| **Terminal Process** | Launched, restarted on failure, killed on exit | Yes (tracked, killed by process PID) | Subprocess + child processes |
| **Dispatcher Script** | Runs in terminal, killed with terminal | Yes (signal handlers in bash) | Bash process, heartbeat file |
| **Process Verification** | Polled after send, cleared on verify | Yes (read-only filesystem ops) | PID files in /tmp/shotbot_pids/ |

---

## 13. Conclusions

### Key Strengths
✅ **Robust crash recovery** - Atomic FIFO recreation prevents race conditions
✅ **Async execution** - UI stays responsive, no blocking on terminal operations
✅ **Fallback mechanism** - Automatic recovery to new terminal on persistent terminal failure
✅ **Process verification** - Phase 2 ensures processes actually started
✅ **Thread safety** - Multiple locks protect shared state from races
✅ **Resource cleanup** - Proper worker shutdown sequence prevents deadlock

### Key Risks
⚠️ **Terminal emulator dependency** - Fails if none available
⚠️ **FIFO buffer capacity** - Long commands might overflow
⚠️ **Heartbeat mechanism** - Relies on dispatcher responsiveness
⚠️ **PID file accumulation** - No automatic cleanup of old PID files
⚠️ **Complex state machine** - Many transitions (healthy → unhealthy → fallback → recovery)

### Recommended Improvements
1. Add automatic PID file cleanup (remove files > 24h old)
2. Add FIFO capacity monitoring / command chunking
3. Add explicit terminal window verification (check window appeared)
4. Add metrics logging (average command latency, failure rates)
5. Add comprehensive integration tests for all failure scenarios
