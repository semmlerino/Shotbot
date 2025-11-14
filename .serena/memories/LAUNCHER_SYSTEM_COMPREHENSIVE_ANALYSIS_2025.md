# Launcher and Terminal System - Comprehensive Architecture Analysis
**Created**: 2025-11-14  
**Status**: Current codebase verified (Nov 14)  
**Scope**: Complete end-to-end analysis including all components  

---

## Executive Summary

ShotBot's launcher system is a **sophisticated multi-layered architecture** for executing VFX applications with proper process lifecycle management, error recovery, and user feedback. The system consists of:

| Component | Type | LOC | Primary Purpose |
|-----------|------|-----|-----------------|
| **PersistentTerminalManager** | Python/Qt | 1,282 | Terminal session lifecycle, FIFO IPC, health monitoring |
| **CommandLauncher** | Python/Qt | 902 | High-level orchestration, shot context, app-specific logic |
| **ProcessExecutor** | Python/Qt | 315 | Routing (persistent terminal vs. new terminal) |
| **ProcessVerifier** | Python | 224 | Phase 2 process verification via PID files |
| **EnvironmentManager** | Python | 130 | Terminal/Rez detection, environment setup |
| **CommandBuilder** | Python | 200 | Command assembly, path validation, escaping |
| **terminal_dispatcher.sh** | Bash | 400+ | Terminal session reader, command execution, PID tracking |

**Total System**: ~3,450 lines of Python + ~400 lines of Bash

---

## 1. System Architecture Overview

### 1.1 High-Level Data Flow

```
User Action (Click "Launch Nuke")
    ↓
LauncherPanel/Dialog
    ↓
CommandLauncher.launch_app(app_name, context)
    ├─ Shot validation
    ├─ App-specific logic (Nuke/3DE/Maya scene handling)
    ├─ Environment setup (Rez packages, workspace function)
    └─ Command assembly
    ↓
_execute_launch(command, app_name)
    ├─ _try_persistent_terminal()  [Primary: async execution]
    └─ _launch_in_new_terminal()   [Fallback: new window, sync]
    ↓
    
PATH A: Persistent Terminal (Primary)
    ├─ ProcessExecutor.execute_in_persistent_terminal()
    ├─ PersistentTerminalManager.send_command_async()
    │  └─ TerminalOperationWorker spawned (Qt worker thread)
    │     ├─ Health check & recovery
    │     ├─ FIFO write (non-blocking)
    │     ├─ Process verification (Phase 2)
    │     └─ Signal emissions
    └─ [Async - returns immediately]

PATH B: New Terminal (Fallback)
    ├─ ProcessExecutor.execute_in_new_terminal()
    ├─ Spawn new terminal emulator (gnome-terminal/konsole/xterm)
    ├─ subprocess.Popen with command
    └─ Immediate crash detection via QTimer
    
Both paths converge:
    ↓
Terminal Dispatcher (terminal_dispatcher.sh)
    ├─ Reads from FIFO (PATH A)
    ├─ Executes command in terminal
    ├─ Backgrounds GUI apps, blocks on CLI
    ├─ Writes PID file for verification
    └─ Reports to heartbeat/logs
    ↓
User sees application window + confirms success
```

### 1.2 Component Relationships

```
┌─────────────────────────────────────────────────────────┐
│  User UI (launcher_panel.py, launcher_dialog.py)       │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  CommandLauncher (973 LOC)                              │
│  ├─ launch_app() orchestration                          │
│  ├─ App-specific handlers (Nuke/3DE/Maya)              │
│  ├─ Fallback retry mechanism                           │
│  └─ Error handling & notifications                      │
└────────────┬───────────────────────────┬────────────────┘
             │                           │
    ┌────────▼─────────┐       ┌─────────▼────────────┐
    │ ProcessExecutor  │       │ EnvironmentManager   │
    │ (315 LOC)        │       │ CommandBuilder       │
    │                  │       │ (330 LOC combined)   │
    │ Routes to:       │       │                      │
    └────────┬──────┬──┘       │ • Rez detection     │
             │      │         │ • Terminal emulator  │
             │      │         │ • Path validation    │
             │      │         │ • Escaping           │
    ┌────────▼──┐  ┌─▼────────└──────────────────────┘
    │ Persistent│  │ New Terminal
    │ Terminal  │  │ Window
    │ Manager   │  │
    │           │  │
    │ (1,282    │  │ subprocess.Popen()
    │ LOC)      │  │ QTimer → verify_spawn()
    │           │  │
    │ • FIFO    │  │
    │ • Health  │  │
    │ • Recovery│  │
    └────────┬──┘  └──────┬──────────┐
             │            │          │
             │     ┌──────▼──────────▼─────┐
             │     │ Terminal Dispatcher   │
             │     │ (400+ LOC bash)       │
             │     │                       │
             │     │ • Read FIFO           │
             │     │ • Execute commands    │
             │     │ • PID tracking        │
             │     │ • Heartbeat response  │
             │     └──────┬────────────────┘
             │            │
             └────┬───────┴────┬──────────────┐
                  │            │              │
             ┌────▼────────────▼────┐  ┌──────▼────┐
             │ ProcessVerifier      │  │ User App  │
             │ (224 LOC)            │  │ (nuke/3de/│
             │                      │  │  maya)    │
             │ Phase 2:             │  └───────────┘
             │ • Poll for PID file  │
             │ • Verify process     │
             │ • Signal completion  │
             └──────────────────────┘
```

---

## 2. Core Components - Detailed Analysis

### 2.1 PersistentTerminalManager (1,282 LOC)

#### Purpose
Manages a single persistent terminal window for executing all commands via FIFO-based IPC, preventing the need to spawn new terminals for each command.

#### Key Responsibilities

**Terminal Lifecycle Management**:
- `__init__()`: Initialize paths, state, locks, and ProcessVerifier
- `_ensure_fifo()`: Create FIFO safely
- `_launch_terminal()`: Spawn terminal emulator with dispatcher script
- `close_terminal()`: Graceful shutdown (EXIT_TERMINAL) + forced kill (SIGKILL)
- `restart_terminal()`: Atomic FIFO recreation + dispatcher restart
- `cleanup()`: Complete resource cleanup for app shutdown

**Health Monitoring**:
- `_is_dispatcher_alive()`: Check process exists, not zombie
- `_is_dispatcher_running()`: FIFO has active reader
- `_send_heartbeat_ping()`: Test responsiveness
- `_check_heartbeat()`: Verify recent heartbeat
- `_is_dispatcher_healthy()`: Composite check (all three above)

**Command Execution (Phase 1 & 2)**:
- `send_command()`: Synchronous execution (blocks during health checks)
- `send_command_async()`: Queue for background execution
- `_send_command_direct()`: Low-level FIFO write
- `_ensure_dispatcher_healthy()`: Recovery mechanism with restart attempts

**Fallback Management**:
- `is_fallback_mode`: Property to check fallback state
- `reset_fallback_mode()`: Manual recovery reset
- Automatic 5-minute cooldown before recovery retry

#### State Variables

```python
# Terminal Process Management
terminal_pid: int | None          # Parent terminal process PID
terminal_process: Popen | None    # subprocess.Popen object
dispatcher_pid: int | None        # Child dispatcher script PID
_dummy_writer_fd: int | None      # Write FD keeping FIFO alive
_fd_closed: bool                  # Track FD state for cleanup

# Health Monitoring
_last_heartbeat_time: float       # Time of last heartbeat response
_heartbeat_timeout: float         # Timeout for heartbeat response
_heartbeat_check_interval: float  # How often to check heartbeat

# Recovery Mechanism
_restart_attempts: int            # Count of restart attempts
_max_restart_attempts: int        # Max before fallback (default: 3)
_fallback_mode: bool              # In fallback mode?
_fallback_entered_at: float | None # When fallback entered

# Thread Safety Locks
_write_lock: threading.Lock       # Serializes FIFO writes
_state_lock: threading.Lock       # Protects terminal_pid, dispatcher_pid, etc.
_restart_lock: threading.Lock     # Serializes restart operations
_workers_lock: threading.Lock     # Protects _active_workers list
_active_workers: list[...]        # References to prevent GC

# Process Verification
_process_verifier: ProcessVerifier # Phase 2 verification

# Path Configuration
fifo_path: str                    # FIFO path
heartbeat_path: str               # Heartbeat file path
dispatcher_path: str              # terminal_dispatcher.sh path
dispatcher_log_path: str           # Debug log path
```

#### Critical Methods

**send_command_async()** (76 lines):
- Validates command (not empty, ASCII safe)
- Checks fallback mode
- Emits `command_queued` signal
- Creates TerminalOperationWorker with parent=self (Qt ownership)
- Adds to `_active_workers` list for GC protection
- Connects operation_finished → cleanup slot
- Starts worker thread
- Returns immediately (non-blocking)

**_ensure_dispatcher_healthy()** (87 lines):
- Core recovery orchestration
- Checks health via `_is_dispatcher_healthy()`
- If unhealthy:
  - Increments `_restart_attempts`
  - If < max: calls `restart_terminal()` (with up to 5s timeout)
  - If >= max: enters FALLBACK_MODE
- On success: resets `_restart_attempts` to 0
- Handles timing and retry logic

**restart_terminal()** (105 lines):
- Closes existing terminal (SIGTERM → SIGKILL)
- Closes dummy writer FD
- **Atomic FIFO recreation**:
  - `os.unlink()` old FIFO
  - `os.fsync()` parent directory
  - Create temp FIFO
  - `os.rename()` temp→final (kernel atomic)
- Launches new dispatcher process
- Waits for dispatcher ready (5s timeout)
- Opens new dummy writer FD
- Returns success/failure

**_send_command_direct()** (58 lines):
- Acquires `_write_lock` (serializes writes)
- Opens FIFO with `O_NONBLOCK | O_WRONLY`
- Writes command + newline
- Handles ENXIO, EAGAIN, ENOENT errors
- Returns success/failure
- Idempotent FD cleanup

#### Thread-Safety Model

**Lock Hierarchy**:
- No circular dependencies
- `_write_lock` held during health checks + FIFO write (atomic)
- `_state_lock` separate from `_write_lock` (not held simultaneously)
- Lock contention minimal (operations < 100ms)

**Worker Thread Safety**:
- TerminalOperationWorker (QThread) runs with parent=self
- Qt parent-child relationship ensures proper cleanup
- Signals auto-convert to queued connections (main thread safe)
- All mutable state access protected by locks

#### Known Implementation Issues

1. **Lock Hierarchy Complexity**: 
   - 4 locks (_write_lock, _state_lock, _restart_lock, _workers_lock) increase complexity
   - No deadlock detected but requires careful maintenance

2. **Heartbeat Mechanism**:
   - File-based implementation (`/tmp/shotbot_heartbeat.txt`)
   - Vulnerable to clock skew or filesystem delays
   - Alternative: Process signal-based heartbeat

3. **Stale PID File Filtering**:
   - Current: enqueue_time-based filtering
   - Window: 1-2ms between file creation and verifier reading
   - Acceptable but tight

4. **Terminal Emulator Selection**:
   - Hardcoded order: gnome-terminal → konsole → xterm
   - No VFX environment preferences
   - Falls back to bash -ilc (non-interactive)

### 2.2 CommandLauncher (902 LOC)

#### Purpose
High-level orchestration of application launching with shot context, app-specific logic (Nuke/3DE/Maya), and fallback recovery.

#### Key Responsibilities

**Launch Orchestration**:
- `launch_app()`: Main API for launching applications
- `launch_app_with_scene()`: Launch with scene context
- `launch_app_with_scene_context()`: Low-level with full context
- `_execute_launch()`: Route to persistent or new terminal

**Error Handling**:
- `_try_persistent_terminal()`: Async attempt
- `_launch_in_new_terminal()`: Sync fallback
- `_on_persistent_terminal_operation_finished()`: Fallback trigger
- `_emit_error()`: Centralized error emission

**App-Specific Logic**:
- Nuke handler (scene opening, raw plate, new file creation)
- 3DE handler (latest scene detection)
- Maya handler (latest scene detection)

**Signal Propagation**:
- Connects to ProcessExecutor signals
- Connects to PersistentTerminalManager lifecycle signals
- Emits `command_executed` and `command_error` to UI

#### Fallback Retry Mechanism

```python
_pending_fallback: dict[str, tuple[str, str]]  # timestamp -> (cmd, app_name)
_fallback_lock: threading.Lock                 # Thread-safe access

# Flow:
1. _try_persistent_terminal() stores command in _pending_fallback[timestamp]
2. If async operation succeeds: entry removed, no fallback needed
3. If async operation fails:
   - _on_persistent_terminal_operation_finished() detects failure
   - Checks _pending_fallback for matching timestamp
   - Calls _launch_in_new_terminal() [sync fallback]
   - Removes from _pending_fallback

# Cleanup:
- Entries > 30s old automatically cleared
- Time-based cleanup prevents dict growth
```

#### Critical Methods

**launch_app()** (200 lines):
- Validates shot is selected
- App-specific scene handling (open latest, create new, etc.)
- Builds command with environment
- Validates workspace function available
- Calls `_execute_launch()`

**_execute_launch()** (22 lines):
- Simple branching:
  - If persistent_terminal available: `_try_persistent_terminal()`
  - Else: `_launch_in_new_terminal()`

**_try_persistent_terminal()** (48 lines):
- Checks persistent_terminal exists
- Stores in `_pending_fallback` for retry
- Calls `persistent_terminal.send_command_async()`
- Returns immediately

**_on_persistent_terminal_operation_finished()** (68 lines):
- Checks if operation failed
- Looks up command in `_pending_fallback`
- If found AND failed: calls `_launch_in_new_terminal()`
- Cleans up old entries (> 30s)

#### Dependencies

**Injected**:
```python
persistent_terminal: PersistentTerminalManager | None
parent: QObject | None
```

**Created Internally**:
```python
env_manager: EnvironmentManager
process_executor: ProcessExecutor
nuke_handler: NukeLaunchRouter
_raw_plate_finder: RawPlateFinder
_nuke_script_generator: NukeScriptGenerator
_threede_latest_finder: ThreeDELatestFinder
_maya_latest_finder: MayaLatestFinder
```

### 2.3 ProcessExecutor (315 LOC)

#### Purpose
Route commands to appropriate execution method (persistent terminal vs. new terminal) and verify process startup.

#### Key Responsibilities

**Routing Decision**:
- `can_use_persistent_terminal()`: Check availability + fallback status
- `execute_in_persistent_terminal()`: Queue async command
- `execute_in_new_terminal()`: Spawn new terminal

**GUI App Detection**:
- Known GUI apps: nuke, 3de, maya, rv, houdini, mari, katana, clarisse
- Used by dispatcher to determine backgrounding behavior

**Process Verification**:
- `verify_spawn()`: Check if new terminal process started
- Uses QTimer (non-blocking)
- Immediate crash detection (poll every 100ms, timeout 2.5s)

#### Key Methods

**can_use_persistent_terminal()** (28 lines):
```python
Checks:
1. persistent_terminal object exists
2. Config.PERSISTENT_TERMINAL_ENABLED
3. Config.USE_PERSISTENT_TERMINAL
4. NOT in fallback mode

Returns: bool
```

**execute_in_persistent_terminal()** (37 lines):
```python
Steps:
1. Get full command from builder
2. Build full command with environment
3. Call persistent_terminal.send_command_async()
4. Return success
```

**execute_in_new_terminal()** (44 lines):
```python
Steps:
1. Find available terminal emulator
2. subprocess.Popen([terminal, "-e", bash, command])
3. QTimer to verify_spawn after 100ms
4. Emit execution_progress signals
```

**verify_spawn()** (34 lines):
```python
Polling verification:
- Timeout: 2.5s
- Interval: 0.1s
- Process.is_running() check
- Handles process crashes between polls
```

### 2.4 ProcessVerifier (224 LOC)

#### Purpose
**Phase 2 Process Verification**: Confirm launched process actually started and is running.

#### Key Responsibilities

**PID File Polling**:
- Polls `/tmp/shotbot_pids/<app>_<timestamp>.pid`
- Timeout: 5 seconds
- Interval: 0.2 seconds
- Filters stale files by mtime

**Process Verification**:
- Reads PID from file
- Uses `psutil.Process(pid).is_running()`
- Handles missing processes gracefully

**Cleanup**:
- `cleanup_old_pid_files()`: Remove files > 24 hours old

#### Key Methods

**wait_for_process()** (51 lines):
```python
Args:
    command: Full command string
    enqueue_time: time.time() when command queued
    
Returns:
    (success: bool, message: str)
    
Process:
1. Check if GUI app (extract app name)
2. If not GUI: return success immediately
3. Poll for PID file (5s timeout)
4. Filter by mtime >= enqueue_time
5. Verify process exists
6. Return (success, message)
```

**_wait_for_pid_file()** (62 lines):
- Polling loop with timeout
- Filters stale files
- Returns first valid PID found

**_extract_app_name()** (22 lines):
- Parses command to extract app name
- Handles rez/bash wrapper chains
- Example: `"rez env nuke -- bash -ilc \"...\""` → `"nuke"`

---

## 3. FIFO Communication Architecture

### 3.1 FIFO Creation & Lifecycle

**Initialization** (non-blocking):
```
1. _ensure_fifo() called
2. os.mkfifo() creates FIFO file
3. stat + S_ISFIFO verification
4. DON'T open writer FD yet (no reader running)
5. FIFO sits idle waiting for dispatcher
```

**After Dispatcher Starts**:
```
1. Dispatcher: exec 3< "$FIFO" (persistent reader)
2. Python: _open_dummy_writer() (write-only FD)
3. Both FDs open simultaneously
4. FIFO ready for bidirectional communication
```

**On Dispatcher Crash**:
```
1. Reader (FD 3) closes
2. ENXIO error on next write
3. Detected by _send_command_direct()
4. _ensure_dispatcher_healthy() triggered
5. Atomic FIFO recreation + restart
```

### 3.2 Atomic FIFO Replacement

**Problem**: FIFO unlink→mkfifo window causes ENOENT errors

**Solution**: Atomic kernel operation
```bash
# Unsafe (window exists):
unlink(FIFO)
[WINDOW: writes fail with ENOENT]
mkfifo(FIFO)

# Safe (atomic):
mkfifo(TEMP_FIFO)
rename(TEMP_FIFO, FIFO)  # Kernel atomic
[NO WINDOW: FIFO always exists]
```

**Implementation**:
```python
Path(old_fifo).unlink(missing_ok=True)
os.fsync(Path(old_fifo).parent)  # Ensure unlink persisted
temp_fifo = f"{final_fifo}.{os.getpid()}.tmp"
os.mkfifo(temp_fifo, 0o600)
os.rename(temp_fifo, final_fifo)  # Atomic
```

### 3.3 Dummy Writer FD Management

**Purpose**: Keep FIFO write-side open to prevent reader EOF

**Why Needed**:
```
FIFO Behavior:
- All readers closed → writer gets EOF
- All writers closed → reader gets EOF

Without dummy writer:
1. send_command_direct opens FD
2. Writes command
3. Closes FD (all writers gone)
4. Dispatcher's read loop checks for more
5. Gets EOF instead of blocking
6. Dispatcher exits!

With dummy writer:
1. One FD always open (dummy writer)
2. send_command_direct open/write/close
3. Dummy writer still open
4. Dispatcher can keep reading
5. Never sees EOF
```

**Lifecycle**:
```
Manager.__init__: _dummy_writer_fd = None
_launch_terminal: (dispatcher starts)
_open_dummy_writer: _dummy_writer_fd = os.open(FIFO, O_WRONLY | O_NONBLOCK)
[Many commands executed]
close_terminal: _close_dummy_writer_fd() → os.close(_dummy_writer_fd)
cleanup: (already closed above)
```

### 3.4 Command Write Pattern

**Serialization via _write_lock**:
```python
with self._write_lock:  # Prevent interleaving with health checks
    # Health check integrated here
    health_ok = self._is_dispatcher_healthy()
    if not health_ok:
        return False
    
    # Write command to FIFO
    try:
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "wb", buffering=0) as fifo:
            fd = None  # fdopen takes ownership
            fifo.write(command.encode("utf-8"))
            fifo.write(b"\n")
    except OSError as e:
        if fd is not None:
            os.close(fd)
        # Handle error
        return False
    finally:
        pass  # fdopen handles FD closure
```

**Lock-Protected Atomicity**:
- Health check + write are atomic from other thread perspective
- Prevents race: "check healthy" (true) → dispatcher crashes → write (ENXIO)
- If dispatcher crashes during write: ENXIO caught, next command triggers recovery

---

## 4. Terminal Dispatcher Script (terminal_dispatcher.sh)

### 4.1 Initialization Phase

```bash
# Setup
set -o pipefail
trap EXIT/INT/TERM handlers
Create log directory
Create PID directory
Setup debug logging
Check if 'ws' function available
Display welcome banner
```

### 4.2 Main Loop

```bash
exec 3< "$FIFO"  # Persistent reader FD (CRITICAL)

while true; do
    read -r cmd <&3  # Block until command received
    
    # Validation
    [ -z "$cmd" ] && continue  # Skip empty
    [ ${#cmd} -lt 3 ] && continue  # Skip short
    
    # Special commands
    [ "$cmd" = "EXIT_TERMINAL" ] && exit 0
    [ "$cmd" = "CLEAR_TERMINAL" ] && clear && continue
    [ "$cmd" = "__HEARTBEAT__" ] && echo "PONG" > "$HEARTBEAT_FILE" && continue
    
    # Execute
    if is_gui_app "$cmd"; then
        eval "$cmd" &
        gui_pid=$!
        
        # Phase 2: PID file for verification
        app_name=$(extract_app_name "$cmd")
        timestamp=$(date '+%Y%m%d_%H%M%S')
        echo "$gui_pid" > "/tmp/shotbot_pids/${app_name}_${timestamp}.pid"
    else
        eval "$cmd"  # Blocking for non-GUI
    fi
done
```

### 4.3 GUI App Detection

**Problem**: Extract actual app from complex chains
```
Input: "rez env nuke -- bash -ilc \"ws /path && nuke -open file.nk\""
Should detect: "nuke"
Not: "rez" or "bash"
```

**Solution**: Parse command to extract final executable
```bash
is_gui_app() {
    local cmd="$1"
    
    # Remove rez wrapper if present
    # Remove bash -ilc if present  
    # Extract final command before quotes
    
    # Check against known GUI apps
    [[ $cmd =~ (3de|nuke|maya|rv|...) ]]
}
```

### 4.4 PID File Writing (Phase 2)

**After backgrounding GUI app**:
```bash
eval "$cmd" &
gui_pid=$!  # Capture PID

# Extract app name (e.g., "nuke")
app_name=$(extract_app_name "$cmd")

# Get current timestamp
timestamp=$(date '+%Y%m%d_%H%M%S')

# Write PID to file
pid_file="/tmp/shotbot_pids/${app_name}_${timestamp}.pid"
echo "$gui_pid" > "$pid_file"

# ProcessVerifier will find this file
# and verify process is running
```

---

## 5. Command Execution Lifecycle - Complete Trace

### 5.1 User Action → Terminal Execution (T0-T0.5s)

```
T0.0: User clicks "Launch Nuke"
  └─ LauncherPanel emits signal

T0.1: CommandLauncher.launch_app(app_name="nuke")
  ├─ Validate shot selected: ✓
  ├─ Build command: "rez env nuke -- bash -ilc \"ws /path && nuke\""
  └─ Call _execute_launch()

T0.2: _execute_launch()
  └─ persistent_terminal.send_command_async(full_command)

T0.3: PersistentTerminalManager.send_command_async()
  ├─ Validate command (ASCII, length)
  ├─ Emit command_queued(timestamp, cmd)
  ├─ Create TerminalOperationWorker(parent=self)
  └─ worker.start()  [Returns immediately]

T0.4: [Main Thread returns to event loop]
  └─ UI responsive (command queued)

[BACKGROUND THREAD BEGINS]

T0.5: TerminalOperationWorker.run()
  ├─ Check interruption: ✓
  ├─ _ensure_dispatcher_healthy()
  │  ├─ _is_dispatcher_healthy()
  │  │  ├─ Process alive? ✓
  │  │  ├─ FIFO readable? ✓
  │  │  └─ Recent heartbeat? ✓
  │  └─ Return: healthy
  │
  ├─ Emit command_executing(timestamp)  [Phase 1]
  ├─ Record: enqueue_time = time.time()
  │
  ├─ _send_command_direct(cmd)
  │  ├─ Acquire _write_lock
  │  ├─ os.open(FIFO, O_WRONLY | O_NONBLOCK)
  │  ├─ Write: full_command + "\n"
  │  └─ Close FD
  │
  └─ _process_verifier.wait_for_process()  [Phase 2]
     ├─ Extract app_name: "nuke"
     ├─ Poll for /tmp/shotbot_pids/nuke_*.pid (5s)
     │  └─ Filter by mtime >= enqueue_time
     ├─ Read PID from file
     ├─ Verify process exists
     │
     └─ Emit:
        ├─ command_verified(timestamp, "Process verified (PID: 12345)")
        │  OR
        └─ command_error(timestamp, "Verification failed: ...")
```

### 5.2 Terminal Processing (T0.6-T0.8s)

```
T0.6: Terminal Dispatcher receives command via FIFO

Dispatcher main loop:
├─ read -r cmd <&3  [Blocks until receives]
├─ Receive: "rez env nuke -- bash -ilc \"ws /path && nuke\""
├─ Validate
├─ is_gui_app check: YES
└─ eval "$cmd" &
   ├─ Nuke process spawns
   ├─ gui_pid = (process ID)
   ├─ Dispatch to background
   └─ Continue loop

PID File Writing:
├─ app_name = "nuke"
├─ timestamp = "20251114_123456"
├─ pid_file = "/tmp/shotbot_pids/nuke_20251114_123456.pid"
└─ Write: echo "12345" > "$pid_file"

T0.7: Nuke window appears (user can interact)

T0.8: ProcessVerifier detects PID file
├─ List /tmp/shotbot_pids/nuke_*.pid
├─ Check mtime >= enqueue_time (T0.5)
├─ Read PID: 12345
├─ psutil.Process(12345).is_running()
└─ Return: (True, "Process verified (PID: 12345)")
```

### 5.3 Fallback Scenario (Persistent Terminal Fails)

```
T0.0-T0.4: Same as above

T0.5: TerminalOperationWorker.run()
  ├─ _ensure_dispatcher_healthy()
  │  └─ FIFO health check fails (dispatcher not responding)
  ├─ _restart_attempts++
  ├─ restart_terminal()  [Complex recovery]
  │  ├─ close_terminal()
  │  ├─ Atomic FIFO recreation
  │  ├─ _launch_terminal()
  │  └─ Wait for dispatcher ready
  │
  ├─ If recovery succeeds: Return healthy, continue with command
  ├─ If recovery fails:
  │  ├─ _restart_attempts >= max (3)?
  │  ├─ YES → Enter FALLBACK_MODE
  │  └─ operation_finished.emit(False, "Max restarts exceeded")

T0.7: CommandLauncher._on_persistent_terminal_operation_finished()
  ├─ Check: operation_failed = True
  ├─ Check: _pending_fallback[timestamp] exists
  ├─ YES → Call _launch_in_new_terminal()
  │
  └─ _launch_in_new_terminal()
     ├─ Find terminal emulator (gnome-terminal/konsole/xterm)
     ├─ subprocess.Popen([terminal, "-e", bash, "-c", command])
     ├─ QTimer singleShot 100ms
     └─ verify_spawn(): Check if process started

T0.8: New terminal window appears
  └─ User continues (fallback successful)
```

---

## 6. Error Handling & Recovery

### 6.1 Health Check Failure Scenarios

| Failure | Check Method | Recovery | Timeout |
|---------|--------------|----------|---------|
| Process zombie | `_is_dispatcher_alive()` | Kill + restart | 0.5s |
| FIFO no reader | `_is_dispatcher_running()` | Restart terminal | 2s + 5s restart |
| No heartbeat | `_check_heartbeat()` | Health check fails | 3s |
| Restart exceeds max | Counter check | Enter fallback mode | 5min cooldown |

### 6.2 FIFO Write Error Handling

```python
_send_command_direct(cmd):
    try:
        fd = os.open(FIFO, O_WRONLY | O_NONBLOCK)
    except OSError as e:
        if e.errno == errno.ENXIO:  # No reader
            dispatcher_pid = None  # Trigger health check on next command
            return False
        elif e.errno == errno.EAGAIN:  # Buffer full
            logger.warning("FIFO buffer full, command not sent")
            return False
        elif e.errno == errno.ENOENT:  # FIFO disappeared
            logger.debug("FIFO missing, will recreate")
            self._ensure_fifo()  # Recreate FIFO
            return False
        else:
            logger.error(f"Unexpected FIFO error: {e}")
            return False
```

### 6.3 Fallback Mode

**Entry Conditions**:
- `_restart_attempts >= _max_restart_attempts` (default: 3)

**Exit Conditions**:
- Manual: `reset_fallback_mode()`
- Automatic: After 5 minute cooldown, next `send_command()` retries recovery

**Behavior in Fallback**:
- `send_command()` returns False
- `send_command_async()` returns False
- CommandLauncher routes to `_launch_in_new_terminal()`

---

## 7. Thread Safety & Synchronization

### 7.1 Lock Analysis

**_write_lock** (threading.Lock):
```
Purpose: Serialize FIFO writes
Protects: FIFO fd operations + atomic health check
Held for: 20-100ms per operation
Contention risk: LOW (single terminal, serial commands)

Usage:
  with self._write_lock:
      if not self._is_dispatcher_healthy():
          return False
      # Then write to FIFO
```

**_state_lock** (threading.Lock):
```
Purpose: Protect terminal_pid, dispatcher_pid, flags
Protects: Self.terminal_pid, dispatcher_pid, _restart_attempts, _fallback_mode
Held for: <1ms per operation
Contention risk: LOW (brief reads/updates)

Usage:
  with self._state_lock:
      self._restart_attempts += 1
```

**_restart_lock** (threading.Lock):
```
Purpose: Serialize restart_terminal operations
Protects: Full restart operation (FIFO, launch, wait)
Held for: 1-5s per restart
Contention risk: MEDIUM (if multiple restarts attempted simultaneously)

Usage:
  with self._restart_lock:
      # Complex multi-step restart
```

**_workers_lock** (threading.Lock):
```
Purpose: Protect _active_workers list
Protects: List of running worker threads
Held for: <1ms per operation
Contention risk: LOW (minimal activity)

Usage:
  with self._workers_lock:
      self._active_workers.append(worker)
```

### 7.2 No Deadlock Analysis

**Lock Ordering**:
```
_write_lock > _state_lock (write_lock acquired first, then state_lock inside)
No circular dependencies possible
```

**Worker Thread Safety**:
```
TerminalOperationWorker(parent=self)  # Qt parent-child
  ├─ Run in background thread
  ├─ Call _ensure_dispatcher_healthy()  [acquires _state_lock internally]
  ├─ Call _send_command_direct()  [acquires _write_lock internally]
  ├─ Emit signals  [queued to main thread via Qt]
  └─ On operation_finished, main thread removes from _active_workers

Qt parent-child cleanup ensures:
  - Worker doesn't persist beyond manager
  - Proper cleanup order (workers before manager destruction)
```

### 7.3 Potential Race Conditions

**Race 1: Terminal crash between health check and write**
```
Thread A: _write_lock acquired
          _is_dispatcher_healthy() → True (dispatcher alive)
[Dispatcher crashes]
          os.open(FIFO) → ENXIO (no reader)
          
Resolution: Caught by except OSError, sets dispatcher_pid=None
            Next health check will trigger restart
```

**Race 2: Multiple workers attempt restart simultaneously**
```
Thread A: _restart_attempts < max → acquire _restart_lock
          restart_terminal()  [1-5s operation]
          
Thread B: Meanwhile hits timeout, tries restart
          Waits on _restart_lock
          Eventually gets it, restarts (redundant but safe)
          
Resolution: Both complete, one finishes first
            Both update same state safely (locks protect)
```

**Race 3: Main thread calls close_terminal() while worker sending**
```
Main thread: close_terminal()
             ├─ Send EXIT_TERMINAL (if alive)
             ├─ Close dummy writer FD
             └─ os.unlink(FIFO)
             
Worker thread: _send_command_direct()
               └─ os.open(FIFO) → ENOENT (FIFO deleted)
               
Resolution: Handled as expected error
            Worker will attempt recovery next command
            Main thread cleanup doesn't hold locks
```

---

## 8. Signal Flow & Qt Integration

### 8.1 Signal Hierarchy

```
PersistentTerminalManager
  ├─ terminal_started(int)                    # Terminal PID
  ├─ terminal_closed()                        # Terminal shutdown
  ├─ command_queued(str, str)                 # Phase 1: timestamp, cmd
  ├─ command_executing(str)                   # Phase 1: timestamp
  ├─ command_verified(str, str)               # Phase 2: timestamp, message
  ├─ command_error(str, str)                  # Phase 2: timestamp, error
  ├─ operation_started(str)                   # operation_name
  ├─ operation_progress(str, str)             # operation_name, message
  ├─ operation_finished(str, bool, str)       # operation_name, success, message
  └─ command_result(bool, str)                # Backward compat

CommandLauncher (receives from above)
  ├─ command_executed(str, str)               # timestamp, message
  └─ command_error(str, str)                  # timestamp, error

ProcessExecutor (receives from above)
  ├─ execution_progress(str, str)             # timestamp, message
  ├─ execution_completed(bool, str)           # success, error
  └─ execution_error(str, str)                # timestamp, error
```

### 8.2 Worker Thread Signal Emission

**Thread Safety**:
- Worker emits signals from background thread
- Qt auto-converts to **QueuedConnection**
- Slot always runs in main thread (GUI thread safe)
- No explicit locking needed for signal emission

**Signal Flow**:
```
TerminalOperationWorker (background thread)
  ├─ run()
  └─ _run_send_command()
     ├─ emit progress("Sending...")
     ├─ emit command_executing()  [Phase 1]
     ├─ emit command_verified()  [Phase 2 - success]
     │ OR
     └─ emit command_error()     [Phase 2 - failure]
        
        [These signals queued to main thread]
        
Main thread event loop
  ├─ Processes queued signals
  ├─ Calls connected slots (command_verified → signal to UI)
  └─ Updates GUI
```

---

## 9. Architectural Issues & Concerns

### 9.1 Critical Issues (High Priority)

**Issue 1: Complex Lock Hierarchy**
- **Severity**: MEDIUM
- **Description**: 4 locks (_write_lock, _state_lock, _restart_lock, _workers_lock) increase maintenance burden
- **Impact**: Higher risk of deadlock during future changes
- **Recommendation**: Document lock ordering, consider consolidation

**Issue 2: Heartbeat Implementation**
- **Severity**: MEDIUM
- **Description**: File-based heartbeat (`/tmp/shotbot_heartbeat.txt`) vulnerable to:
  - Clock skew (system time changes)
  - Filesystem delays (NFS, WSL)
  - Stale files from crashed dispatcher
- **Impact**: False health check failures, unnecessary restarts
- **Recommendation**: Use signal-based heartbeat (kill(pid, 0)) or IPC

**Issue 3: FIFO Buffer Capacity**
- **Severity**: LOW
- **Description**: Linux default FIFO buffer: 65536 bytes
  - Long commands (>65KB) may fail with EAGAIN
  - No backpressure handling or command chunking
- **Impact**: Very long commands fail silently
- **Recommendation**: Monitor command length, warn on oversized commands

### 9.2 Design Concerns

**Concern 1: Bash Dispatcher Dependency**
- **Risk**: Shell incompatibilities across VFX systems
- **Mitigation**: Currently well-tested, handles multiple shells
- **Future**: Could rewrite in Python, but Bash simplicity has value

**Concern 2: Terminal Emulator Detection**
- **Risk**: Unknown terminal emulator → defaults to bash (non-interactive)
- **Mitigation**: Preference order matches common VFX environments
- **Future**: Add config option for terminal preference

**Concern 3: PID File Accumulation**
- **Risk**: `/tmp/shotbot_pids/` grows unbounded
- **Mitigation**: 24-hour auto-cleanup on verifier init
- **Future**: More aggressive cleanup (hourly, or per-launch)

**Concern 4: Single FIFO Design**
- **Limitation**: One terminal per Python process
- **Workaround**: Spawn multiple PersistentTerminalManager instances (tests do this)
- **Trade-off**: Simplicity vs. scalability

### 9.3 Testing Challenges

**Challenge 1: FIFO Race Conditions**
- Hard to reproduce in unit tests
- Requires timing-dependent scenarios
- Solution: Mock FIFO operations in tests

**Challenge 2: Qt Parent-Child Cleanup**
- Workers must have proper parent parameter
- Crash if parent deleted while worker running
- Solution: Use @pytest.fixture to cleanup instances

**Challenge 3: Terminal Emulator Availability**
- Tests may not have gnome-terminal/konsole
- Falls back to bash -ilc
- Solution: Mock terminal launcher in tests

---

## 10. Performance Characteristics

### 10.1 Latency Profile

| Operation | Typical | Maximum | Blocking |
|-----------|---------|---------|----------|
| send_command_async() | 5ms | - | No |
| send_command() | 50ms | 3s | Yes |
| Health check | 100ms | 3s | No (polling) |
| Restart terminal | 1-2s | 7s | Yes |
| Process verification | 200ms | 5s | No (polling) |
| FIFO write | 5ms | 50ms | No |

### 10.2 Resource Usage

| Resource | Count | Cleanup |
|----------|-------|---------|
| FDs (FIFO) | 2 | On cleanup() |
| Terminal process | 1 | On cleanup() |
| Worker threads | 1 per async command | Auto (deleteLater) |
| PID files | 1 per launch | Auto (24h) |
| Heartbeat file | 1 | On dispatch exit |

### 10.3 Scalability Limits

- **Commands per session**: Unlimited (dispatcher loop)
- **Concurrent launches**: One at a time (FIFO serializes)
- **Workers per manager**: Limited by Qt thread pool (typically 4-8)
- **Total system capacity**: 10s of commands per minute (typical)

---

## 11. Architectural Strengths

✅ **Robust Recovery**: Multiple fallback layers + automatic restart

✅ **Async-First Design**: Non-blocking operations keep UI responsive

✅ **Phase 2 Verification**: Ensures processes actually started (not just accepted)

✅ **Thread-Safe**: Multiple locks protect concurrent access

✅ **Production-Proven**: Handles VFX environment complexities (Rez, shells)

✅ **Flexible Routing**: Persistent terminal (async) + fallback (sync)

✅ **Clean Separation**: CommandLauncher → ProcessExecutor → PersistentTerminal

✅ **Comprehensive Signals**: Full lifecycle visibility to UI

---

## 12. Architectural Weaknesses

⚠️ **Complexity**: 3,400+ LOC distributed across 7 files

⚠️ **Bash Dependency**: Dispatcher script adds shell compatibility risk

⚠️ **Lock Contention**: Multiple locks increase maintenance burden

⚠️ **Limited Diagnostics**: FIFO EOF errors hard to debug in production

⚠️ **File-Based Heartbeat**: Vulnerable to clock skew/filesystem delays

⚠️ **Single Terminal**: One manager = one terminal (scaling requires instances)

⚠️ **Terminal Hardcoding**: No VFX environment preferences for emulator selection

---

## 13. Recommendations for Improvement

### Phase 1: Immediate (0-2 weeks)

1. **Enhance Logging**:
   - Add comprehensive logging to dispatcher script
   - Log all FIFO operations in manager
   - Save logs to predictable location for debugging

2. **Document Lock Hierarchy**:
   - Diagram lock dependencies
   - Add comments to each lock site
   - Create lock ordering documentation

3. **Improve Cleanup**:
   - Add more aggressive PID file cleanup
   - Log cleanup activities
   - Monitor file accumulation

### Phase 2: Short-term (1-2 months)

1. **Metrics & Telemetry**:
   - Count command successes/failures
   - Track average latency
   - Monitor restart attempts
   - Dashboard for system health

2. **Heartbeat Improvement**:
   - Replace file-based with signal-based (kill(pid, 0))
   - Eliminate clock skew vulnerability
   - Faster detection (avoid file I/O)

3. **Terminal Preferences**:
   - Add Config option for preferred terminal emulator
   - VFX environment-specific defaults
   - User override mechanism

### Phase 3: Long-term (3-6 months)

1. **Command Queuing**:
   - Queue multiple commands (don't block on FIFO)
   - Chunking for long commands
   - Priority levels

2. **Process Monitoring**:
   - Track launched processes
   - Graceful shutdown on app exit
   - Resource usage monitoring

3. **Alternative Dispatcher**:
   - Consider Python-based dispatcher (eliminate bash dependency)
   - Socket-based communication (instead of FIFO)
   - Better error reporting

---

## 14. Summary Table

| Aspect | Current State | Maturity | Risk |
|--------|---------------|----------|------|
| **Core Launcher** | Robust, tested | Production | LOW |
| **FIFO Communication** | Atomic, safe | Production | LOW |
| **Health Monitoring** | File-based | Acceptable | MEDIUM |
| **Recovery Mechanism** | Auto-restart | Production | LOW |
| **Process Verification** | PID polling | Production | LOW |
| **Thread Safety** | Multiple locks | Production | MEDIUM |
| **Fallback System** | Async → Sync | Production | LOW |
| **Bash Dispatcher** | Well-tested | Production | LOW |
| **Terminal Detection** | Hardcoded order | Production | MEDIUM |
| **Error Handling** | Comprehensive | Production | LOW |

---

## 15. Glossary

**FIFO**: Named pipe at `/tmp/shotbot_commands.fifo` for command communication

**Dispatcher**: `terminal_dispatcher.sh` - reads from FIFO, executes commands, manages session

**Dummy Writer FD**: Write-only file descriptor keeping FIFO alive (prevents EOF)

**Phase 1**: Command queuing & execution in terminal (signal: command_executing)

**Phase 2**: Process verification after launch (signals: command_verified or command_error)

**Fallback Mode**: Persistent terminal disabled, routes to new terminal windows

**Heartbeat**: Periodic health check via special `__HEARTBEAT__` command

**PID File**: File written by dispatcher after spawning GUI app, polled by ProcessVerifier

**Health Check**: Multi-point validation (process alive, FIFO readable, recent heartbeat)

**Atomic FIFO**: Temp FIFO + kernel rename() prevents create/delete race window

---

## 16. Files & LOC Summary

```
persistent_terminal_manager.py    1,282 LOC  Core terminal management
command_launcher.py                 902 LOC  High-level orchestration
launch/process_executor.py           315 LOC  Execution routing
launch/process_verifier.py           224 LOC  Process verification
launch/environment_manager.py        130 LOC  Env detection
launch/command_builder.py            200 LOC  Command assembly
terminal_dispatcher.sh               400+ LOC Bash dispatcher
─────────────────────────────────────────────
Total                              ~3,450    Python + Bash
```

---

**Document End**
