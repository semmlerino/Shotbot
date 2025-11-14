# Launcher System Architecture - Visual Diagrams

Created: 2025-11-14  
References: LAUNCHER_TERMINAL_ARCHITECTURE_OVERVIEW.md

## 1. High-Level System Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Application (Qt)                         │
│                                                                     │
│  launcher_panel.py / launcher_dialog.py                            │
│         ↓                                                          │
│  CommandLauncher.launch_app(app_name, context)                    │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
                ┌───────────────────────────────────┐
                │   CommandLauncher                  │
                │  (973 LOC)                         │
                │                                    │
                │ • Shot validation                  │
                │ • App-specific logic (Nuke/3DE)    │
                │ • Environment setup (Rez)          │
                │ • Error handling & fallback        │
                └───────────────────────────────────┘
                      ↙         ↖
        [Persistent Terminal]  [New Terminal Fallback]
                ↓                      ↓
        ┌──────────────────┐  ┌──────────────────┐
        │PersistentTerminal│  │ProcessExecutor   │
        │Manager           │  │(new terminal)    │
        │(1,408 LOC)       │  │(ProcessVerifier) │
        │                  │  │                  │
        │• FIFO manage.    │  │• Terminal detect │
        │• Health checks   │  │• Process spawn   │
        │• Worker threads  │  │• Immediate crash │
        │• Fallback mode   │  │  detection       │
        └──────────────────┘  └──────────────────┘
                ↓                      ↓
        FIFO write via          subprocess.Popen()
        non-blocking I/O             ↓
                ↓              QTimer.singleShot(100ms)
        ┌──────────────────┐  process.poll()
        │Terminal Dispatcher│
        │(bash script)     │
        │                  │
        │ • Read from FIFO │
        │ • Execute cmds   │
        │ • Background GUI │
        │ • Write PID file │
        └──────────────────┘
                ↓
        ┌──────────────────┐
        │  Launched App    │
        │(nuke/maya/3de)   │
        └──────────────────┘
```

## 2. PersistentTerminalManager State Machine

```
                         ┌─────────────┐
                         │   INIT      │
                         └──────┬──────┘
                                ↓
                    _ensure_fifo(open_dummy_writer=False)
                                ↓
                         ┌─────────────┐
                         │  FIFO READY │
                         └──────┬──────┘
                                ↓
        User calls: send_command() or send_command_async()
                                ↓
        ┌──────────────────────────────────────────────┐
        │                                              │
        ├───────────────────────┬─────────────────────┤
        ↓                       ↓                     ↓
    DISPATCHER       DISPATCHER NOT        FALLBACK MODE
    HEALTHY          HEALTHY              (max retries exceeded)
    ✓ Process        ⚠ Check fails:        │
    ✓ FIFO reader    1. No process        │ ├→ send_command() returns False
    ✓ Heartbeat      2. No FIFO reader    │ ├→ 5 min cooldown timer
    │                3. Stale heartbeat   │ ├→ Auto-recovery on next cmd
    │                                     │ └→ Manual reset available
    └─────────────────────────────────────┘
                         │
          send_command() or send_command_async() OK
                         ↓
        ┌────────────────────────────────┐
        │ COMMAND SENT (to FIFO)         │
        │                                 │
        │ Worker: Phase 1 + 2            │
        │ ├→ command_queued              │
        │ ├→ command_executing           │
        │ ├→ command_verified (success)  │
        │ └→ command_error (failure)     │
        └────────────────────────────────┘
```

## 3. Command Execution Phases

```
PHASE 1: QUEUING & TERMINAL EXECUTION
───────────────────────────────────────

send_command_async(cmd)
        ↓
    emit command_queued(timestamp, cmd)
        ↓
    Create TerminalOperationWorker
        ↓
    worker.start() [Qt thread pool]
        ↓
[Worker Thread]
    ├→ _ensure_dispatcher_healthy()
    │   ├→ Is dispatcher process running?
    │   ├→ Is FIFO readable?
    │   └→ Recent heartbeat?
    │       ├ YES → continue
    │       └ NO → _send_heartbeat_ping()
    │           └ Wait 3s for PONG
    ├→ emit command_executing(timestamp)
    └→ _send_command_direct(cmd)
        ├→ Open FIFO (non-blocking)
        ├→ Write: command + \n
        └→ Close FD


PHASE 2: PROCESS VERIFICATION
──────────────────────────────

[Still in Worker Thread]
    capture enqueue_time = time.time()
        ↓
    ProcessVerifier.wait_for_process(cmd, enqueue_time)
        ├→ Is GUI app? (nuke/3de/maya/etc)
        │   └ NO → emit verified immediately
        ├→ Extract app name (3de, nuke, etc)
        ├→ Poll for PID file (5s timeout)
        │   └ /tmp/shotbot_pids/<app>_<timestamp>.pid
        │   └ Filter: mtime >= enqueue_time
        └→ Verify PID exists with psutil
            ├ YES → emit command_verified(pid)
            └ NO → emit command_error("PID not found")
```

## 4. Terminal Dispatcher Flow

```
Terminal Emulator Started (gnome-terminal/konsole/xterm)
        ↓
terminal_dispatcher.sh launched with bash -il
        ↓
Setup:
├→ Create $PID_DIR (/tmp/shotbot_pids)
├→ Create debug log
├→ Log startup info
├→ Display welcome banner
└→ Check if 'ws' function available
        ↓
[Persistent FIFO Setup]
exec 3< "$FIFO"  ← Keep reader FD open continuously!
        ↓
MAIN LOOP (while true):
        ├─ read -r cmd <&3     ← Read from persistent FD 3
        │   (blocks until line received)
        │
        ├─ Validate command
        │   ├ Length check (>3 chars)
        │   └ Content check (has letters)
        │
        ├─ Special commands?
        │   ├ EXIT_TERMINAL → exit dispatcher
        │   ├ CLEAR_TERMINAL → clear screen
        │   └ __HEARTBEAT__ → echo "PONG" to file
        │
        ├─ GUI app detection
        │   ├ Extract from rez wrapper chains
        │   ├ Handle "bash -ilc \"...\""
        │   └ Check against known GUI list
        │
        ├─ Execution:
        │   ├ GUI app → eval "$cmd &" (background)
        │   │           sleep 0.5
        │   │           Write PID file
        │   └ Non-GUI → eval "$cmd" (blocking)
        │              Report exit code
        │
        └─ LOOP
```

## 5. Thread Safety Architecture

```
┌──────────────────────────────────────────────────────────┐
│           MAIN THREAD (Qt Event Loop)                     │
│                                                          │
│  Safe Operations:                                        │
│  • User API calls: send_command, send_command_async    │
│  • Qt signal emissions                                   │
│  • GUI updates                                          │
│  • Create/start workers                                 │
│                                                          │
│  Unsafe Directly:                                        │
│  ✗ Direct FIFO access                                   │
│  ✗ Modifying _active_workers list                       │
│  ✗ Changing terminal_pid/dispatcher_pid                 │
│                                                          │
│ send_command_async() [API]                             │
│    ↓                                                    │
│ Create TerminalOperationWorker(parent=self)            │
│    ↓                                                    │
│ worker.start() [returns immediately]                   │
│    ↓ [background]                                      │
│ [Worker Thread Spawned]                                │
└──────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────┐
│      WORKER THREAD (TerminalOperationWorker)             │
│                                                          │
│  Safe Operations:                                        │
│  • Call _ensure_dispatcher_healthy() [has locks]       │
│  • Call wait_for_process() [read-only]                 │
│  • psutil calls [read-only OS]                         │
│                                                          │
│  Protection:                                            │
│  ├─ _write_lock: Serializes FIFO writes               │
│  │   [prevents byte-level corruption]                  │
│  │                                                      │
│  ├─ _state_lock: Protects shared mutable state        │
│  │   [terminal_pid, dispatcher_pid, flags]            │
│  │                                                      │
│  └─ _workers_lock: List of active workers             │
│      [cleanup_worker() removes self]                   │
│                                                          │
│  run() method:                                          │
│  ├─ _ensure_dispatcher_healthy()                       │
│  │   [acquires _state_lock internally]                │
│  ├─ _send_command_direct()                            │
│  │   [acquires _write_lock internally]                │
│  └─ wait_for_process()                                │
│      [read-only, no locks needed]                      │
│                                                          │
│  Cleanup:                                               │
│  └─ deleteLater() called by operation_finished signal   │
│     └─ Remove from _active_workers in cleanup_worker()  │
└──────────────────────────────────────────────────────────┘
```

## 6. FIFO Communication Sequence

```
Main Thread                    FIFO                    Dispatcher (Bash)
    │                           │                             │
    │  _send_command_direct()   │                             │
    │                           │                             │
    ├─ acquire _write_lock      │                             │
    │                           │                             │
    ├─ os.open(FIFO,            │                             │
    │    O_WRONLY|O_NONBLOCK)   │                             │
    │  ├─ SUCCESS: fd created   │                             │
    │  └─ ENXIO: no reader!     │                             │
    │      (dispatcher crashed) │                             │
    │                           │                             │
    ├─ os.fdopen(fd)            │                             │
    │  & write(cmd + "\n")      │                             ├─ Persistent read
    ├──────────────────────────→ FIFO buffer ───────────────→ read -r cmd <&3
    │                           │                             │
    ├─ Close FD                 │                             ├─ Process command
    │                           │                             │
    └─ release _write_lock      │                             └─ Write PID file


CRITICAL: Dummy Writer FD
───────────────────────────

Without dummy writer:
    Dispatcher reads EOF
    FIFO → closed
    Next write → EOF error

With dummy writer:
    Python keeps FD open (non-blocking)
    Dispatcher reads continuously
    Writes always succeed (ENXIO only if dispatcher gone)
```

## 7. Error Handling Tree

```
send_command_async(cmd)
    ↓
TerminalOperationWorker.run()
    ├─ _ensure_dispatcher_healthy()
    │   ├ _is_dispatcher_healthy()
    │   │   ├ _is_dispatcher_alive()
    │   │   ├ _is_dispatcher_running()
    │   │   │   ├─ _send_heartbeat_ping()
    │   │   │   │   ├ timeout 3s → False
    │   │   │   │   └ PONG received → True
    │   │   │   └─ (result used for health)
    │   │   └ _check_heartbeat()
    │   │       └ Check mtime < timeout
    │   │
    │   └─ if unhealthy:
    │       ├ Check _restart_attempts < max (3)
    │       │   ├─ YES:
    │       │   │   ├─ _restart_attempts++
    │       │   │   ├─ close_terminal() + SIGKILL
    │       │   │   └─ restart_terminal()
    │       │   │       ├─ Close dummy writer FD
    │       │   │       ├─ Atomic FIFO replacement
    │       │   │       ├─ _launch_terminal()
    │       │   │       └─ Wait for dispatcher ready
    │       │   │           ├ success → reset counter → return True
    │       │   │           └ timeout → return False
    │       │   └─ NO:
    │       │       ├─ Enter FALLBACK_MODE
    │       │       ├─ Set cooldown timestamp
    │       │       └─ Return False
    │       │
    │       └─ emit command_error + cleanup
    │
    ├─ _send_command_direct(cmd)
    │   ├─ Open FIFO (non-blocking)
    │   │   ├ ENXIO → dispatcher not running
    │   │   ├ EAGAIN → buffer full
    │   │   └ ENOENT → FIFO disappeared
    │   ├─ Write command
    │   └─ Close FD
    │
    └─ ProcessVerifier.wait_for_process()
        ├─ Not GUI app? → return success immediately
        ├─ Is GUI app:
        │   ├─ Extract app name
        │   ├─ Poll 5s for PID file
        │   │   ├ Not found → emit command_error
        │   │   └ Found → read PID
        │   └─ Verify with psutil.pid_exists(pid)
        │       ├ True → emit command_verified
        │       └ False → emit command_error
        │
        └─ Fallback Path:
            └─ CommandLauncher._on_persistent_terminal_operation_finished()
                └─ if failed && _pending_fallback:
                    └─ _launch_in_new_terminal() [sync fallback]
```

## 8. Atomic FIFO Replacement

```
Scenario: Terminal crashed, need to restart

Step 1: Close Existing FIFO
────────────────────────────
├─ close_terminal() [SIGKILL if needed]
├─ _close_dummy_writer_fd()
└─ Path.unlink(FIFO) [remove old FIFO]
    └─ os.fsync(parent_dir) [ensure durability]


Step 2: Atomic Creation
──────────────────────
├─ Create temp FIFO:
│   └─ temp_fifo = "/tmp/shotbot_commands.fifo.12345.tmp"
│   └─ os.mkfifo(temp_fifo, 0o600)
│
├─ Atomic rename:
│   └─ os.rename(temp_fifo, FIFO) [kernel atomic]
│
└─ On error:
    └─ Cleanup temp FIFO if exists


Step 3: Launch Dispatcher
─────────────────────────
├─ FIFO now guaranteed to exist
├─ _launch_terminal()
│   └─ subprocess.Popen([terminal, dispatcher_script, FIFO])
└─ Wait for dispatcher ready:
    ├─ _is_dispatcher_running()
    │   └─ _send_heartbeat_ping()
    └─ if timeout:
        └─ Continue anyway (dispatcher may need more time)


CRITICAL: No window where FIFO missing!
────────────────────────────────────────
Without atomic rename:
  unlink → window → mkfifo
  ↑                   ↓
  Writes fail with ENOENT

With atomic rename:
  mkfifo(temp) → rename(temp, target)
  └ No window!
```
