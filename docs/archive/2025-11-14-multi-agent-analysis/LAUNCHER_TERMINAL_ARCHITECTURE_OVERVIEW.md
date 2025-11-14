# Launcher & Terminal System Architecture Overview

**Document Date**: 2025-11-14  
**Thoroughness Level**: MEDIUM  
**Total LOC**: 3,387 lines  

## Executive Summary

Shotbot's launcher system provides robust application launching in VFX production environments with two primary subsystems:

1. **PersistentTerminalManager** (1,408 LOC) - Primary production launcher using FIFO-based IPC
2. **CommandLauncher** (973 LOC) - High-level orchestration with fallback recovery
3. **Launch Components** (289 LOC combined) - Modular helpers for environment, commands, and execution

**Key Achievement**: Unified launcher architecture supporting both persistent terminal (async) and new terminal (sync) modes with automatic fallback recovery.

---

## File Organization

```
shotbot/
├── persistent_terminal_manager.py      (1,408 LOC) - Main persistent terminal implementation
├── command_launcher.py                 (973 LOC)   - High-level application launcher
├── terminal_dispatcher.sh              (330 lines) - Bash dispatcher script
└── launch/
    ├── __init__.py                     (14 LOC)    - Package exports
    ├── process_executor.py             (318 LOC)   - Process execution routing
    ├── process_verifier.py             (249 LOC)   - Phase 2 process verification
    ├── command_builder.py              (289 LOC)   - Command assembly and validation
    └── environment_manager.py          (136 LOC)   - Environment detection (Rez, terminals)
```

---

## Core Component Responsibilities

### 1. PersistentTerminalManager - Terminal Session Management

**Primary Purpose**: Manage a single persistent terminal session with FIFO-based command communication.

**Key Responsibilities**:
- FIFO creation and lifecycle management (atomic replacement)
- Dispatcher process health monitoring and recovery
- Heartbeat-based connectivity verification
- Dummy writer FD management (prevents EOF race conditions)
- Worker thread coordination for background operations
- Fallback mode management (auto-recovery after 5 min cooldown)

**Thread Safety Model**:
- `_write_lock`: Serializes FIFO writes (prevents byte-level corruption)
- `_state_lock`: Protects shared mutable state (PIDs, FDs, flags)
- `_workers_lock`: Manages active worker threads list
- `_test_instances_lock`: Tracks instances for test cleanup

**Architecture Patterns**:

```
User Code
  ↓
CommandLauncher.launch_app()
  ↓
_try_persistent_terminal() 
  ↓
send_command_async()  [returns immediately]
  ↓
TerminalOperationWorker (QThread)
  ├→ _ensure_dispatcher_healthy()
  ├→ _send_command_direct()
  └→ _process_verifier.wait_for_process() [Phase 2]
  ↓
Signals: command_queued, command_executing, command_verified/command_error
```

**Critical Methods**:

| Method | Purpose | Thread-Safe | Blocking |
|--------|---------|-------------|----------|
| `send_command()` | Synchronous command execution | Yes (locks) | Yes |
| `send_command_async()` | Queue command for background execution | Yes | No |
| `_ensure_dispatcher_healthy()` | Recovery orchestration | Yes (calls internal locks) | Yes (up to 5s) |
| `_is_dispatcher_healthy()` | Multi-check health (process, FIFO, heartbeat) | Yes | No (polling) |
| `_send_command_direct()` | Write to FIFO (internal use) | Yes (_write_lock) | No |
| `restart_terminal()` | Kill old, start new, atomic FIFO replacement | No (main thread) | Yes (up to 7s) |

**State Transitions**:

```
STARTING
  ├→ _launch_terminal() - spawn emulator + dispatcher script
  └→ _is_dispatcher_running() - verify reader exists
      ↓
HEALTHY [normal operation]
  ├→ send_command() - works fine
  └→ send_command_async() - queues to worker
      ↓
UNHEALTHY [health check fails]
  └→ _ensure_dispatcher_healthy()
      ├→ if retries < max → _restart_terminal()
      └→ if retries >= max → FALLBACK_MODE
          ↓
FALLBACK_MODE [terminal unavailable]
  ├→ send_command() returns False
  ├→ Auto-recovery after 5 min cooldown
  └→ Manual reset_fallback_mode() available
```

**Critical Issues Addressed**:

1. **FIFO EOF Race Condition**
   - Problem: FIFO reader closes between iterations → writes fail with EOF
   - Solution: Persistent FD (exec 3<) in dispatcher keeps reader open
   - Verification: Heartbeat ping confirms dispatcher responsive

2. **Dummy Writer FD Management**
   - Problem: Without writer FD, reader EOF causes FIFO to return EOF to writes
   - Solution: Keep one persistent write FD open in Python code
   - Lifecycle: Open after dispatcher starts, close before FIFO cleanup

3. **Atomic FIFO Recreation**
   - Problem: FIFO unlink + mkfifo window where FIFO missing → ENXIO errors
   - Solution: Create temp FIFO, atomic `os.rename()` to target path
   - Verification: `os.fsync()` on parent directory ensures durability

4. **Stale PID File Filtering**
   - Problem: Old PID files from previous launches confuse process verification
   - Solution: Track command enqueue time, filter PID files by mtime >= enqueue_time
   - Window: Small (creation to read), acceptable due to polling

### 2. CommandLauncher - High-Level Application Orchestration

**Primary Purpose**: High-level API for launching applications with shot context, environment wrapping, and fallback recovery.

**Key Responsibilities**:
- Shot context management and validation
- Application-specific launch logic (Nuke, 3DE, Maya)
- Environment setup (Rez packages, workspace function)
- Fallback retry mechanism (persistent terminal → new terminal)
- Process verification after spawn
- Error handling and user notifications

**Architecture Pattern** (Template Method):

```
launch_app(app_name, context)
  ↓
[Shot + workspace validation]
  ↓
[App-specific logic - Nuke/3DE/Maya scene handling]
  ↓
[Build command: ws + rez + logging redirection]
  ↓
_execute_launch() [Template Method]
  ├→ _try_persistent_terminal()  [async, may fallback]
  └→ _launch_in_new_terminal()   [sync fallback]
  ↓
emit command_executed/command_error signals
```

**Signal Flow** (Phase 1 & 2 Lifecycle):

```
PHASE 1 (Async Execution in Terminal)
├→ command_queued       - when queued for execution
├→ command_executing    - when terminal starts execution
└→ command_verified     - when process verified started (Phase 2)
    or
└→ command_error        - when verification fails (Phase 2)

FALLBACK PATH
└→ _on_persistent_terminal_operation_finished()
    └→ if failed: _launch_in_new_terminal() [new terminal window]
```

**Critical Design Pattern** (Fallback Recovery):

```python
try:
    _try_persistent_terminal()     # async
    # Returns immediately, may fail later in background
    # Registers in _pending_fallback[timestamp] = (cmd, app_name)
except:
    _launch_in_new_terminal()      # sync fallback

# Later: if async failed...
_on_persistent_terminal_operation_finished(operation, success, message)
  if not success and _pending_fallback:
    _launch_in_new_terminal()      # Retry in new terminal
```

**Dependency Injection**:

```
CommandLauncher(
    persistent_terminal=PersistentTerminalManager(),
    parent=widget
)
  ├→ process_executor = ProcessExecutor(persistent_terminal, Config)
  ├→ env_manager = EnvironmentManager()
  ├→ nuke_handler = NukeLaunchRouter()
  ├→ threede_latest_finder = ThreeDELatestFinder()
  ├→ raw_plate_finder = RawPlateFinder()
  ├→ nuke_script_generator = NukeScriptGenerator()
  └→ maya_latest_finder = MayaLatestFinder()
```

### 3. Launch Components (launch/ package)

**ProcessExecutor** (318 LOC)
- Routes commands to persistent terminal or new terminal windows
- Manages signal connections to PersistentTerminalManager
- Provides `verify_spawn()` method for immediate crash detection
- Known GUI apps: nuke, 3de, maya, rv, houdini, mari, katana, clarisse

**ProcessVerifier** (249 LOC) - **Phase 2 Process Verification**
- Polls for PID files written by terminal_dispatcher.sh
- Verifies launched process exists using psutil
- Filters stale PID files by mtime >= enqueue_time
- Configuration: 5s timeout, 0.2s poll interval
- PID file format: `/tmp/shotbot_pids/<app_name>_<timestamp>.pid`

**CommandBuilder** (289 LOC)
- Validates paths (prevents command injection via normalization + validation)
- Escapes paths with `shlex.quote()` for safe shell usage
- Wraps commands with Rez environment if available
- Adds logging redirection for debugging
- Stateless design (no mutable state)

**EnvironmentManager** (136 LOC)
- Detects Rez availability (checks config, REZ_USED env var, `which rez`)
- Maps application names to Rez packages
- Detects available terminal emulators (preference: gnome-terminal → konsole → xterm)
- Caches detection results for performance

### 4. Terminal Dispatcher (terminal_dispatcher.sh, 330 lines)

**Primary Purpose**: Bash script executed in persistent terminal session. Reads commands from FIFO, executes them, handles special commands.

**Key Responsibilities**:
- FIFO management (persistent FD prevents EOF issues)
- Command execution (GUI apps backgrounded, others blocking)
- Process verification (writes PID files for Phase 2)
- Special commands (EXIT_TERMINAL, CLEAR_TERMINAL, __HEARTBEAT__)
- Heartbeat response (PING → PONG)
- Sanity checks (command length, corruption detection)

**Critical Implementation Details**:

1. **Persistent FIFO Reading**
   ```bash
   exec 3< "$FIFO"
   while true; do
       if read -r cmd <&3; then
           # execute command
       fi
   done
   ```
   - Keeps FD 3 open continuously
   - Prevents "no reader" EOF condition between iterations

2. **GUI App Detection**
   ```bash
   is_gui_app() {
       # Extracts actual app from rez/bash wrapper chains
       # Example: "rez env 3de -- bash -ilc \"ws /path && 3de\""
       # Should detect "3de" not "rez"
       # Handles: rez, bash -ilc, ws wrapper patterns
   }
   ```

3. **PID File Writing** (Phase 2)
   ```bash
   eval "$cmd &"
   gui_pid=$!
   pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
   echo "$gui_pid" > "$pid_file"
   ```
   - Writes PID file AFTER backgrounding
   - ProcessVerifier polls for this file

4. **Heartbeat Mechanism**
   ```bash
   if [ "$cmd" = "__HEARTBEAT__" ]; then
       echo "PONG" > "$HEARTBEAT_FILE"
   fi
   ```
   - Detects dispatcher responsiveness
   - Used for health checks when main reader blocked

---

## Communication Patterns

### FIFO Communication (PersistentTerminalManager ↔ Dispatcher)

```
Python Code                     Terminal Dispatcher
  ↓                                    ↑
_send_command_direct()          read from FD 3
  │                                    │
  ├→ os.open(FIFO, O_WRONLY)    ← ENXIO if no reader
  ├→ write(command + "\n")      ← Read from FIFO
  └→ os.close(fd)                      │
                                       ├→ Execute command
                                       ├→ If GUI: background & write PID
                                       └→ If non-GUI: wait for exit

CRITICAL POINTS:
- Writer: Non-blocking I/O (O_NONBLOCK)
- Reader: Persistent FD (exec 3<) prevents "no reader" EOF
- Dummy writer: Keeps FIFO alive even with no write activity
```

### Heartbeat Communication (Health Check)

```
Python Code                     Terminal Dispatcher
  ↓                                    ↑
_send_heartbeat_ping()          is_dispatcher_healthy() check
  │                                    │
  ├→ Write "__HEARTBEAT__\n"  → read from FD 3
  ├→ Poll for response file         │
  │  (5 retries × 0.2s)             ├→ Detect special command
  │                                 └→ Write "PONG" to heartbeat file
  └→ Check heartbeat file mtime
     & verify "PONG" content

TIMEOUT: 3s for heartbeat response
FALLBACK: If heartbeat fails → restart terminal
```

### Qt Signal Flow (Worker Threads)

```
User Code                   TerminalOperationWorker (QThread)
  ↓                                    ↓
send_command_async()  →  Create worker with parent=self
  │                           │
  ├→ emit command_queued       ├→ run() in background thread
  │                            │
  └→ worker.start()            ├→ _run_send_command()
                               │   ├→ _ensure_dispatcher_healthy()
                               │   ├→ emit command_executing
                               │   ├→ _send_command_direct()
                               │   └→ _process_verifier.wait_for_process()
                               │       └→ emit command_verified/command_error
                               │
                               └→ emit operation_finished

SIGNAL CONNECTIONS:
- operation_finished → _on_async_command_finished()
- cleanup_worker() removes from _active_workers list
```

---

## Thread Boundaries & Ownership

### Main Thread (Qt Event Loop)

**Responsibilities**:
- User API calls (send_command, launch_app)
- Signal connections and emissions
- GUI updates
- Process executor verification (via QTimer.singleShot)

**Unsafe Operations**:
- Direct FIFO access without lock
- Modifying _active_workers list without lock
- Changing terminal_pid/dispatcher_pid without lock

### Worker Threads (TerminalOperationWorker)

**Responsibilities**:
- Health checks (_is_dispatcher_healthy)
- Terminal restarts (restart_terminal)
- Process verification (wait_for_process)

**Safe Operations**:
- Call methods with internal locks (_ensure_dispatcher_healthy)
- Read PID files (filesystem only)
- Check psutil (read-only OS calls)

**Unsafe Operations**:
- Directly modify state without acquiring locks
- Call non-thread-safe methods

### Lock Hierarchy

```
No nested locks allowed!

_state_lock only ever used for:
  1. Read PIDs/flags
  2. Modify PIDs/flags
  3. NEVER called while holding _write_lock

_write_lock only ever used for:
  1. FIFO operations
  2. NEVER calls methods that need _state_lock
```

---

## Process Lifecycle Management

### Phase 1: Command Queuing & Execution

```
send_command_async(command)
  ├→ Validate command (non-empty, no corruption)
  ├→ Check fallback mode
  ├→ emit command_queued(timestamp, command)
  ├→ Create TerminalOperationWorker(parent=self)
  ├→ Connect operation_finished → _on_async_command_finished()
  ├→ Add to _active_workers list
  └→ worker.start()

RETURN IMMEDIATELY - no blocking!
```

### Phase 2: Process Verification

```
_process_verifier.wait_for_process(command, enqueue_time)
  ├→ Check if GUI app
  ├→ Extract app name from command
  ├→ Poll for PID file (5s timeout, 0.2s interval)
  │   └→ Filter: mtime >= enqueue_time
  ├→ Read PID from file
  └→ Verify process exists with psutil.pid_exists(pid)

RESULT: (success, message) tuple
  ├→ True: "Process verified (PID: 1234)"
  └→ False: "PID file not found" or "Process not found"
```

### Recovery Mechanisms

**Automatic Health Recovery**:
1. Health check fails
2. Increment _restart_attempts
3. If < MAX (default 3):
   - Kill old terminal (SIGKILL)
   - restart_terminal() with atomic FIFO recreation
   - Wait up to 5s for dispatcher ready
   - Reset _restart_attempts on success
4. If >= MAX:
   - Enter FALLBACK_MODE
   - Auto-recovery attempt after 5 min cooldown

**Manual Reset**:
```python
persistent_terminal.reset_fallback_mode()
  └→ Clear _fallback_mode and _restart_attempts
      Re-enable automatic recovery
```

---

## Error Handling & Edge Cases

### Critical Error Scenarios

| Scenario | Handler | Recovery |
|----------|---------|----------|
| FIFO doesn't exist | _send_command_direct() | Try recreate FIFO (2 attempts) |
| ENXIO (no reader) | _ensure_dispatcher_healthy() | Restart terminal with health check |
| Dispatcher crash | _is_dispatcher_healthy() | Kill + restart if retries < max |
| Process verification timeout | Phase 2 logic | Emit command_error, allow fallback |
| Too many restarts | _ensure_dispatcher_healthy() | Enter fallback mode, 5 min cooldown |
| Dummy writer open fails | _open_dummy_writer() | Log warning, continue (non-fatal) |
| FIFO unlink fails | restart_terminal() | Log warning, try cleanup anyway |

### Resource Cleanup

**Worker Cleanup**:
```python
def cleanup():
    # 1. STOP ALL WORKERS FIRST (prevents deadlock)
    for worker in _active_workers:
        worker.requestInterruption()
        worker.wait(2000)
        if not finished:
            worker.terminate()
    
    # 2. THEN cleanup terminal resources
    close_terminal()
    _close_dummy_writer_fd()
    remove_FIFO()
```

**Order Matters**: Workers must stop before acquiring _state_lock to prevent deadlock.

---

## Testing Considerations

### Key Testing Patterns

1. **Singleton Reset Pattern**
   ```python
   @pytest.fixture(autouse=True)
   def cleanup_instances():
       yield
       PersistentTerminalManager.cleanup_all_instances()
   ```

2. **Mock FIFO Operations**
   ```python
   @patch('os.open')
   @patch('os.close')
   def test_fifo_write(mock_close, mock_open):
       manager.send_command("test")
   ```

3. **Worker Thread Verification**
   ```python
   manager.send_command_async("test")
   # Wait for worker completion
   qtbot.wait(500)
   # Verify signals emitted
   ```

4. **Qt Parent-Child Lifecycle**
   - ALL QThread workers MUST have parent parameter
   - Prevents C++ crashes during cleanup
   - Required for parallel test execution (-n auto)

### Known Issues in Tests

1. **Stale FIFO from Crashed Dispatcher**
   - Solution: Atomic FIFO recreation in restart_terminal()
   - Verification: Test orphaned FIFO scenarios

2. **PID File Leakage**
   - Solution: cleanup_old_pid_files(max_age_hours=24) on startup
   - Tests: Verify old files removed after 24h

3. **Worker Not Stopping Gracefully**
   - Solution: requestInterruption() + wait() + terminate() as fallback
   - Timeout: 2s for graceful, 1s for forceful

---

## Performance Characteristics

### Latency Profile

| Operation | Typical | Max | Blocking |
|-----------|---------|-----|----------|
| send_command() | <50ms | 3s | Yes (health check) |
| send_command_async() | <5ms | - | No |
| _is_dispatcher_healthy() | <100ms | 3s | No (polling) |
| _send_heartbeat_ping() | <100ms | 3s | No (polling) |
| restart_terminal() | 1-2s | 7s | Yes |
| process verification | <500ms | 5s | No (polling) |

### Resource Usage

- **FIFO**: 2 file descriptors (read + dummy write)
- **Terminal Process**: 1 xterm/gnome-terminal subprocess
- **PID Files**: ~1 file per launch (cleaned after 24h)
- **Workers**: 1 QThread per async operation (cleaned after completion)

---

## Known Limitations & TODO Items

### From CLAUDE.md TODO Section

```python
def restart_terminal(self) -> bool:
    """Restart the persistent terminal with atomic FIFO recreation.
    
    TODO: Add tests for:
      - TerminalOperationWorker Qt lifecycle with parent parameter ✓ DONE
      - Atomic FIFO recreation under race conditions
      - FD leak prevention in _send_command_direct() ✓ DONE
    """
```

### Identified Problem Areas

1. **Heartbeat Implementation**
   - Currently: File-based (write→read mtime check)
   - Issue: Vulnerable to clock skew
   - Future: Consider process-based heartbeat (signal response)

2. **Fallback Retry Mechanism**
   - Currently: Uses timestamp-based FIFO queue
   - Issue: Timestamp collision possible across day boundary
   - Limitation: 30s window for clearing old commands

3. **PID File Filtering**
   - Currently: Filters by mtime >= enqueue_time
   - Window: File creation to verifier reading (~1-2ms)
   - Acceptable: Small window, verification compensates

4. **Terminal Detection Order**
   - Current: gnome-terminal → konsole → xterm → x-terminal-emulator
   - Issue: No preference config for VFX environments
   - Potential Fix: Add terminal preference to Config

---

## Summary

### Strengths

✅ **Robust**: Multiple fallback layers (persistent → new terminal → manual fallback)  
✅ **Async-First**: Non-blocking operations preserve UI responsiveness  
✅ **Process-Safe**: Atomic FIFO recreation, proper FD management  
✅ **Thread-Safe**: Lock hierarchy prevents deadlocks, workers properly parented  
✅ **Production-Proven**: Handles VFX environment complexities (Rez, multiple shells)  

### Weaknesses

⚠️ **Complexity**: 3,387 LOC across 6 files, tightly coupled  
⚠️ **Bash Dependency**: Dispatcher script adds shell compatibility risk  
⚠️ **Limited Diagnostics**: FIFO EOF issues hard to debug in production  
⚠️ **No Metrics**: No built-in telemetry for failure rates  

### Recommended Next Steps

1. Add comprehensive logging to dispatcher script
2. Implement fallback retry metrics/telemetry
3. Consider process-based heartbeat mechanism
4. Add VFX environment-specific terminal preferences
5. Document dispatcher log locations clearly for debugging
