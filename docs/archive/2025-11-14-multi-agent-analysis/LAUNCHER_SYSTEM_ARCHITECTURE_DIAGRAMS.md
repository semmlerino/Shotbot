# Launcher System - Architecture Diagrams & Visual Analysis

---

## 1. Component Dependency Graph

```
┌──────────────────────────────────────────────────────────────────────┐
│                        User Application (Qt)                         │
│               launcher_panel.py / launcher_dialog.py                 │
│                                                                      │
│                  User initiates app launch (signal)                 │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                ┌────────────▼──────────────┐
                │  CommandLauncher          │
                │  (902 LOC, main API)      │
                │                           │
                │ • launch_app()            │
                │ • App-specific logic      │
                │ • Fallback mechanism      │
                │ • Error handling          │
                └────────────┬────────┬─────┘
                             │        │
          ┌──────────────────▼──┐    │
          │ ProcessExecutor     │    │
          │ (315 LOC)           │    │
          │                     │    │
          │ • Routing decision  │    │
          │ • GUI app detect    │    │
          │ • Verify spawn      │    │
          └──────┬────────┬─────┘    │
                 │        │          │
        ┌────────▼──┐  ┌──▼──────────▼──────────────┐
        │Persistent │  │ EnvironmentManager +       │
        │Terminal   │  │ CommandBuilder             │
        │Manager    │  │ (330 LOC combined)         │
        │           │  │                            │
        │(1,282 LOC)│  │ • Rez detection           │
        │           │  │ • Terminal detection      │
        │• FIFO     │  │ • Path validation         │
        │• Health   │  │ • Command escaping        │
        │• Recovery │  └────────────────────────────┘
        │• Signals  │
        │• Workers  │
        └─────┬──┬──┘
              │  │
              │  └─────┬──────────────┐
              │        │              │
        ┌─────▼──┐ ┌───▼────────────┐ │
        │ FIFO   │ │ProcessVerifier │ │
        │        │ │ (224 LOC)      │ │
        │/tmp/   │ │                │ │
        │shotbot │ │ • PID polling  │ │
        │_cmds   │ │ • Verify      │ │
        │.fifo   │ │   process      │ │
        └─────┬──┘ └────────────────┘ │
              │                        │
        ┌─────▼──────────────────────┐ │
        │Terminal Dispatcher Script  │ │
        │(terminal_dispatcher.sh)    │ │
        │(400+ LOC bash)             │ │
        │                            │ │
        │• Read FIFO                 │ │
        │• Execute commands          │ │
        │• Background GUI apps       │ │
        │• Write PID files           │ │
        │• Heartbeat response        │ │
        └────────────┬───────────────┘ │
                     │                  │
        ┌────────────▼──────────────────▼───┐
        │     Terminal Session / Shell      │
        │  (gnome-terminal/konsole/xterm)   │
        │                                   │
        │  Hosts dispatcher script           │
        │  Executes user commands            │
        │  Displays app windows              │
        └───────────────────────────────────┘
        
        ┌─────────────────────────────────┐
        │ Launched Application            │
        │ (nuke, maya, 3de, etc.)         │
        │                                 │
        │ User interacts here              │
        └─────────────────────────────────┘
```

---

## 2. PersistentTerminalManager State Machine

```
                           ┌─────────────────────┐
                           │     INITIALIZING    │
                           │                     │
                           │ • Setup paths       │
                           │ • Create FIFO       │
                           │ • Init locks        │
                           │ • Init verifier     │
                           └──────────┬──────────┘
                                      │
                          ┌───────────▼───────────┐
                          │   WAITING_FOR_COMMAND │
                          │                       │
                          │ • No terminal running │
                          │ • FIFO exists (empty) │
                          │ • Dummy writer: None  │
                          └───────┬─────┬─────────┘
                                  │     │
                   ┌──────────────┐│     │┌─────────────┐
                   │ send_command()       │ send_command_async()
                   └──────────────┘│     │└─────────────┘
                                  │     │
                         ┌────────▼─────▼──────────┐
                         │  STARTING_TERMINAL      │
                         │                         │
                         │ • _launch_terminal()    │
                         │ • Spawn emulator        │
                         │ • Start dispatcher      │
                         │ • Poll for ready (5s)   │
                         │ • Open dummy writer     │
                         └────┬──────────┬─────────┘
                              │          │
                          Success    Failure
                              │          │
                ┌─────────────▼──┐   ┌───▼─────────────┐
                │   HEALTHY      │   │ RECOVERY_FAILED │
                │                │   │                 │
                │ • Dispatcher   │   │ Increment retry │
                │   alive        │   │ count           │
                │ • FIFO reader  │   │                 │
                │   active       │   │ If retries < 3: │
                │ • Recent       │   │   → STARTING    │
                │   heartbeat    │   │                 │
                │ • Dummy writer │   │ If retries >= 3:│
                │   open         │   │   Enter fallback│
                └────┬───────────┘   └─────────────────┘
                     │                      ▲
                     │ Can execute commands  │
                     │                       │
            ┌────────▼────────────┐         │
            │  EXECUTING_COMMAND  │         │
            │                     │         │
            │ Phase 1:            │         │
            │ • Emit queued       │         │
            │ • Emit executing    │         │
            │ • Send via FIFO     │         │
            │                     │         │
            │ Phase 2:            │         │
            │ • Wait for PID file │         │
            │ • Verify process    │         │
            │ • Emit verified OR  │         │
            │   emit error        │         │
            │                     │         │
            │ If error → trigger  ├────────┘
            │ health check        │
            └─────────┬───────────┘
                      │
              ┌───────▼────────┐
              │  HEALTHY       │
              │  (loop back)   │
              └────────────────┘
              
┌────────────────────────────────────────┐
│         FALLBACK_MODE (5 min cooldown)  │
│                                        │
│ • send_command() returns False         │
│ • CommandLauncher routes to new        │
│   terminal window (sync fallback)      │
│ • Auto-recovery timer running          │
│ • Manual reset available               │
│                                        │
│ Exit: timeout OR reset_fallback_mode() │
└────────────────────────────────────────┘
```

---

## 3. Command Execution Flow - Sequence Diagram

```
User                CommandLauncher    ProcessExecutor   PersistentTerminal      Dispatcher
  │                       │                  │                  │                    │
  │  Click Launch          │                  │                  │                    │
  ├───────────────────────>│                  │                  │                    │
  │                        │                  │                  │                    │
  │                        │ Validate shot   │                  │                    │
  │                        │ Build command  │                  │                    │
  │                        │                  │                  │                    │
  │                        │ launch_app()    │                  │                    │
  │                        ├─────────────────>│                  │                    │
  │                        │                  │                  │                    │
  │                        │                  │ Can use PT?     │                    │
  │                        │                  ├─────────────────>│                    │
  │                        │                  │     Yes          │                    │
  │                        │                  │<─────────────────┤                    │
  │                        │                  │                  │                    │
  │                        │                  │ send_command_async()                │
  │                        │                  ├─────────────────>│                    │
  │                        │                  │                  │                    │
  │                        │<─────────────────┤                  │                    │
  │      Return (async)    │                  │                  │                    │
  │<───────────────────────┤                  │                  │                    │
  │                        │                  │                  │                    │
  │ [Main thread returns to event loop]      │                  │                    │
  │                        │                  │                  │                    │
  │                        │                  │  [Worker thread]  │                    │
  │                        │                  │                  │                    │
  │                        │                  │  emit command_queued               │
  │                        │                  │<─────────────────│                    │
  │                        │  (connected)    │                  │                    │
  │                        │<─────signal─────┤                  │                    │
  │                        │ on_command_queued                 │                    │
  │                        │                  │                  │                    │
  │                        │                  │  _ensure_dispatcher_healthy()       │
  │                        │                  │                  │                    │
  │                        │                  │  emit command_executing           │
  │                        │                  │<─────────────────│                    │
  │                        │<─────signal─────┤                  │                    │
  │                        │ on_command_executing              │                    │
  │                        │                  │                  │                    │
  │                        │                  │  _send_command_direct()            │
  │                        │                  │     [FIFO write]                   │
  │                        │                  ├────────FIFO──────────────────────>│
  │                        │                  │      command                      │
  │                        │                  │                  │                    │
  │                        │                  │                  │  read -r cmd <&3 │
  │                        │                  │                  │  is_gui_app?    │
  │                        │                  │                  │  eval "$cmd" &  │
  │                        │                  │                  │  Write PID file │
  │                        │                  │                  │                    │
  │                        │                  │  wait_for_process()                 │
  │                        │                  │  Poll PID file (5s timeout)        │
  │                        │                  │  Check mtime >= enqueue_time       │
  │                        │                  │  Verify with psutil                │
  │                        │                  │                  │                    │
  │                        │                  │  emit command_verified            │
  │                        │                  │<─────────────────│                    │
  │                        │<─────signal─────┤                  │                    │
  │                        │ on_command_verified               │                    │
  │                        │                  │                  │                    │
  │                        │ emit command_executed              │                    │
  │<───────signal─────────┤                  │                  │                    │
  │ Log success to UI     │                  │                  │                    │
  │                        │                  │                  │                    │
  │ [User sees app window open - can interact]                  │                    │
  │                        │                  │                  │                    │
```

---

## 4. FIFO Communication Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PersistentTerminalManager                    │
│                          (Python)                                │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ _write_lock (serializes writes + health checks)         │   │
│  │                                                         │   │
│  │ send_command_direct():                                  │   │
│  │   1. Acquire _write_lock                               │   │
│  │   2. fd = os.open(FIFO, O_WRONLY | O_NONBLOCK)        │   │
│  │   3. Write command + "\n"                              │   │
│  │   4. Close FD                                          │   │
│  │   5. Release _write_lock                               │   │
│  │                                                         │   │
│  │ Non-blocking I/O prevents deadlock on full buffer      │   │
│  └──────────────────────┬──────────────────────────────────┘   │
│                         │                                       │
│                         │ Command bytes                         │
│                         ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  FIFO: /tmp/shotbot_commands.fifo                       │   │
│  │  ├─ Kernel-managed circular buffer (~64KB)             │   │
│  │  ├─ Writer FD: os.open(O_WRONLY | O_NONBLOCK)         │   │
│  │  │   └─ Non-blocking to prevent hangs                  │   │
│  │  ├─ Reader FD: bash exec 3< "$FIFO" (persistent)      │   │
│  │  │   └─ Held open across loop iterations              │   │
│  │  ├─ Dummy writer FD: os.open(O_WRONLY | O_NONBLOCK)   │   │
│  │  │   └─ Keeps FIFO alive, prevents reader EOF         │   │
│  │  └─ Critical: If all writers close → reader gets EOF   │   │
│  └──────────────────────┬──────────────────────────────────┘   │
│                         │                                       │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          │ Read from FD 3
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Terminal Dispatcher                            │
│                   (terminal_dispatcher.sh)                       │
│                                                                 │
│  exec 3< "$FIFO"  # Open persistent reader on FD 3             │
│                                                                 │
│  while true; do                                                │
│      read -r cmd <&3  # Block until command received          │
│      # Validate, execute, track PID                           │
│  done                                                          │
│                                                                 │
│  Key: FD 3 held open across iterations                         │
│  ↓ Reader never closes                                         │
│  ↓ FIFO never signals EOF                                      │
│  ↓ Loop continues indefinitely                                │
└──────────────────────────────────────────────────────────────────┘

Atomic FIFO Replacement (on crash recovery):
╔══════════════════════════════════════════════════════════════════╗
║                    CRITICAL: Race Window                         ║
║                                                                  ║
║ UNSAFE approach:                                                │
║   os.unlink(FIFO)          ← FIFO gone                         │
║   [WINDOW: writes fail]                                        │
║   os.mkfifo(FIFO)          ← New FIFO created                 │
║                                                                  ║
║ SAFE approach (atomic):                                         │
║   os.mkfifo(TEMP_FIFO)     ← Create temp name                │
║   os.rename(TEMP_FIFO, FIFO) ← Kernel atomic swap             │
║   [NO WINDOW: FIFO always exists]                             │
╚══════════════════════════════════════════════════════════════════╝

Dummy Writer FD Lifecycle:
┌────────────────────────────────┐
│ __init__: _dummy_writer_fd=None │
├────────────────────────────────┤
│ _launch_terminal(): dispatcher  │
│ starts (reader opened)          │
├────────────────────────────────┤
│ _open_dummy_writer():           │
│ fd = os.open(FIFO, O_WRONLY)   │
│ _dummy_writer_fd = fd           │
├────────────────────────────────┤
│ [Commands execute, readers keep │
│  reading from FD 3]             │
├────────────────────────────────┤
│ close_terminal():               │
│ _close_dummy_writer_fd()        │
│ os.close(_dummy_writer_fd)      │
├────────────────────────────────┤
│ cleanup(): already closed       │
└────────────────────────────────┘
```

---

## 5. Thread Safety & Lock Model

```
Main Thread (Qt Event Loop)              Worker Thread (TerminalOperationWorker)
────────────────────────────────────     ──────────────────────────────────────

User action                              
  │
  ├─ send_command_async()                [Create worker, parent=self]
  │  │                                    │
  │  ├─ Emit command_queued              └─ worker.start()
  │  │                                    
  │  ├─ Create worker                    
  │  ├─ Add to _active_workers           [Worker thread begins]
  │  │                                    │
  │  └─ worker.start()                   ├─ run()
  │     [Returns immediately]            │  ├─ Acquire _state_lock
  │                                      │  │  Read: dispatcher_pid, terminal_pid
  │  [Main thread continues               │  │  Release _state_lock
  │   processing events]                  │  │
  │                                      │  ├─ Acquire _write_lock
  │                                      │  │  Health check
  │                                      │  │  FIFO write
  │                                      │  │  Release _write_lock
  │                                      │  │
  │                                      │  └─ call _process_verifier.wait_for_process()
  │                                      │     (read-only, no locks needed)
  │                                      │
  │                                      ├─ Emit signals (queued to main thread)
  │                                      │  ├─ command_verified
  │                                      │  └─ operation_finished
  │                                      │
  │                                      └─ [Thread completes]
  │
  ├─ [Qt processes queued signals]
  │  ├─ operation_finished received
  │  ├─ cleanup_worker()
  │  │  ├─ Acquire _workers_lock
  │  │  ├─ Remove worker from _active_workers
  │  │  ├─ Release _workers_lock
  │  │  └─ worker.deleteLater()
  │  │
  │  └─ [Qt deferred deletion processes]
  │     └─ Worker deleted in event loop
  │
  └─ [Main thread continues]

Lock Hierarchy Diagram:
═════════════════════════════════════════

                    ┌────────────────────┐
                    │  _write_lock       │
                    │                    │
                    │  Held: 20-100ms    │
                    │  Protects:         │
                    │  • FIFO I/O        │
                    │  • Health check    │
                    └────────────────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │  _state_lock       │
                    │                    │
                    │  Held: <1ms        │
                    │  Protects:         │
                    │  • terminal_pid    │
                    │  • dispatcher_pid  │
                    │  • _restart_*      │
                    │  • _fallback_*     │
                    └────────────────────┘

(Separate locks, no nesting)

                    ┌────────────────────┐
                    │  _restart_lock     │
                    │                    │
                    │  Held: 1-5s        │
                    │  Protects:         │
                    │  • restart ops     │
                    │  • FIFO recreation │
                    └────────────────────┘

                    ┌────────────────────┐
                    │  _workers_lock     │
                    │                    │
                    │  Held: <1ms        │
                    │  Protects:         │
                    │  • _active_workers │
                    │    list            │
                    └────────────────────┘
```

---

## 6. Error Recovery Flow

```
Command Execution
        │
        ▼
┌────────────────────────────────┐
│  _ensure_dispatcher_healthy()   │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│  _is_dispatcher_healthy()       │
├────────────────────────────────┤
│ Check 1: Process alive?        │
│   psutil.Process(dispatcher_pid)
│   is_running()                  │
│                                │
│ Check 2: FIFO readable?         │
│   send heartbeat ping           │
│   wait 3s for PONG              │
│                                │
│ Check 3: Recent heartbeat?      │
│   mtime of heartbeat file       │
│   < timeout?                    │
│                                │
│ Result: AND all three           │
└────────┬───────────────────────┘
         │
    ┌────┴─────────────┐
    │ All OK?           │ Some failed?
    │ (healthy)         │
    ▼                   ▼
  Return True      ┌──────────────────┐
                   │ Recovery Attempt  │
                   ├──────────────────┤
                   │                  │
                   │ _restart_attempts┤
                   │    += 1           │
                   │                  │
                   │ If < max (3):     │
                   │   restart_        │
                   │   terminal()      │
                   │   └─ 1-5 sec      │
                   │      operation    │
                   │      with timeout │
                   │                  │
                   │   If succeeds:    │
                   │   _restart_       │
                   │   attempts = 0    │
                   │   Return: True    │
                   │                  │
                   │   If fails:       │
                   │   Return: False   │
                   │                  │
                   │ If >= max (3):    │
                   │   _fallback_mode  │
                   │       = True      │
                   │   _fallback_      │
                   │   entered_at      │
                   │       = now       │
                   │   Return: False   │
                   │                  │
                   │   [5 min cooldown]│
                   └──────────────────┘
        │
        ▼
┌──────────────────────────────┐
│ Command Execution Continues? │
├──────────────────────────────┤
│ If healthy: YES              │
│   Write to FIFO              │
│   Verify process             │
│   Emit signals               │
│                              │
│ If unhealthy: NO             │
│   operation_finished(False)   │
│   CommandLauncher catches    │
│   Routes to new terminal     │
│   (fallback)                 │
└──────────────────────────────┘
```

---

## 7. Process Verification Timeline (Phase 2)

```
Time   Worker Thread                Terminal Dispatcher           ProcessVerifier
───────────────────────────────────────────────────────────────────────────────

T0ms   send_command_async()
       ├─ emit command_queued
       ├─ create worker
       └─ worker.start()
       
       Main thread returns
       [~5ms elapsed]

T5ms   [Background thread starts]
       _ensure_dispatcher_healthy()
       _send_command_direct()
       
       [FIFO write begins]
           │
           ├─ os.open(FIFO, ...)
           ├─ write(command + "\n")    ──────FIFO─────────>  read -r cmd <&3
           └─ close(fd)                                      [Receives command]
       
       [~10ms elapsed]
           │                                 │
           │                                 ├─ Validate
           │                                 ├─ is_gui_app: YES
           │                                 └─ eval "$cmd" &
           │                                    [Nuke spawns in background]
           │                                    gui_pid = 12345
           │
           │                                 ├─ Write PID file
           │                                 │  /tmp/shotbot_pids/
           │                                 │  nuke_20251114_123456.pid
           │                                 │
           │                                 └─ Continue to next read

T10ms  wait_for_process()                    
       ├─ Extract app_name: "nuke"
       ├─ Start polling
       │
       └─ Loop iteration 1 (T10ms):
          ├─ List /tmp/shotbot_pids/nuke_*.pid
          ├─ File mtime >= enqueue_time?
          │  NO - too soon (PID file just written)
          └─ Sleep 200ms

T210ms ├─ Loop iteration 2 (T210ms):
       │  ├─ List /tmp/shotbot_pids/nuke_*.pid
       │  ├─ File mtime >= enqueue_time?
       │     YES - found it!
       │  ├─ Read PID: 12345
       │  ├─ psutil.Process(12345).is_running()?
       │     YES - process running!
       │  ├─ Return: (True, "Process verified (PID: 12345)")
       │  └─ Emit command_verified signal
       │
       └─ operation_finished.emit(True, "Verified...")

T220ms [Main thread processes queued signals]
       ├─ operation_finished slot
       ├─ cleanup_worker()
       ├─ CommandLauncher.command_verified()
       └─ command_executed.emit()
           [UI updates with success]

T225ms Total: ~225ms elapsed
       User sees Nuke window + success notification
       
Timeline Summary:
├─ Command queued: 0-5ms
├─ Execution in terminal: 5-10ms
├─ PID file written: 8-12ms
├─ Polling for PID: 10-220ms (200ms interval until found)
├─ Signal processing: 220-225ms
└─ Total: ~225ms (but UI responsive from T5ms)

Worst case (verification timeout):
├─ Polling continues for 5s (timeout)
├─ PID file never appears
├─ ProcessVerifier returns (False, "PID file not found")
├─ Emit command_error signal
└─ CommandLauncher triggers fallback
```

---

## 8. Fallback Mechanism Flow

```
User attempts launch
        │
        ▼
_execute_launch()
        │
        ├─ Try: _try_persistent_terminal()
        │  ├─ Check enabled + not fallback
        │  ├─ Store in _pending_fallback[timestamp] = (cmd, app_name)
        │  └─ persistent_terminal.send_command_async()
        │     [Returns immediately]
        │
        └─ [Main thread returns]

[Background execution]
        │
        ├─ Command queued → executing
        ├─ FIFO write successful
        ├─ Process verification...
        │
        ├─ Success path:
        │  ├─ Emit command_verified
        │  ├─ operation_finished(True, "Verified...")
        │  └─ CommandLauncher removes from _pending_fallback
        │
        └─ Failure path:
           ├─ Health check fails
           ├─ Max restarts exceeded (3)
           ├─ Enter fallback_mode
           ├─ Emit operation_finished(False, "Max restarts")
           │
           └─ CommandLauncher._on_persistent_terminal_operation_finished()
              ├─ Check: operation succeeded? NO
              ├─ Check: _pending_fallback[timestamp]? YES
              └─ Retrieve: (cmd, app_name)
                 │
                 └─ _launch_in_new_terminal(cmd, app_name)
                    ├─ Find terminal emulator
                    │  Try: gnome-terminal
                    │  Try: konsole
                    │  Try: xterm
                    │  Try: x-terminal-emulator
                    │  Fall back: bash -ilc
                    ├─ subprocess.Popen([terminal, "-e", bash, "-c", cmd])
                    ├─ [Sync - waits for process to spawn]
                    ├─ QTimer: verify_spawn after 100ms
                    │  ├─ process.is_running()?
                    │  ├─ YES → emit execution_completed
                    │  └─ NO → emit execution_error
                    └─ Remove from _pending_fallback[timestamp]

Cleanup of old _pending_fallback entries:
├─ Entries > 30s old automatically cleared
├─ Prevents dict growth from many failed attempts
└─ Time-based cleanup (simple, no external services)
```

---

## 9. Configuration & Constants

```
PersistentTerminalManager Configuration:
┌──────────────────────────────────────────────────────────────────┐
│ From config.py / Module Constants                                │
├──────────────────────────────────────────────────────────────────┤
│ FIFO_PATH: "/tmp/shotbot_commands.fifo"                          │
│ HEARTBEAT_PATH: "/tmp/shotbot_heartbeat.txt"                     │
│ HEARTBEAT_TIMEOUT: 10.0 (seconds)                                │
│ HEARTBEAT_CHECK_INTERVAL: 5.0 (seconds)                          │
│ MAX_TERMINAL_RESTART_ATTEMPTS: 3                                  │
│ PERSISTENT_TERMINAL_ENABLED: True                                 │
│ USE_PERSISTENT_TERMINAL: True                                     │
├──────────────────────────────────────────────────────────────────┤
│ Module-Level Timeouts                                            │
├──────────────────────────────────────────────────────────────────┤
│ _TERMINAL_RESTART_DELAY_SECONDS: 0.5                             │
│ _FIFO_READY_TIMEOUT_SECONDS: 2.0                                 │
│ _DISPATCHER_HEALTH_CHECK_TIMEOUT_SECONDS: 3.0                    │
│ _DISPATCHER_STARTUP_TIMEOUT_SECONDS: 5.0                         │
│ _HEARTBEAT_SEND_TIMEOUT_SECONDS: 3.0                             │
│ _WORKER_POLL_INTERVAL_SECONDS: 0.1                               │
│ _CLEANUP_POLL_INTERVAL_SECONDS: 0.2                              │
└──────────────────────────────────────────────────────────────────┘

ProcessVerifier Configuration:
┌──────────────────────────────────────────────────────────────────┐
│ VERIFICATION_TIMEOUT_SEC: 5.0                                    │
│ POLL_INTERVAL_SEC: 0.2                                           │
│ PID_FILE_DIR: "/tmp/shotbot_pids"                                │
│ PID_FILE_CLEANUP_HOURS: 24                                       │
└──────────────────────────────────────────────────────────────────┘

ProcessExecutor Configuration:
┌──────────────────────────────────────────────────────────────────┐
│ GUI_APPS: {                                                      │
│   "3de", "nuke", "maya", "rv",                                   │
│   "houdini", "mari", "katana", "clarisse"                        │
│ }                                                                 │
└──────────────────────────────────────────────────────────────────┘

Terminal Emulator Detection Order:
┌──────────────────────────────────────────────────────────────────┐
│ 1. gnome-terminal (GNOME desktop)                                │
│ 2. konsole (KDE desktop)                                          │
│ 3. xterm (X11 fallback)                                          │
│ 4. x-terminal-emulator (Debian/Ubuntu generic)                   │
│ 5. bash -ilc (Last resort, non-interactive)                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. Resource Lifecycle Tracking

```
┌─────────────────────────────────────────────────────────────────┐
│            PersistentTerminalManager Resource Lifecycle          │
└─────────────────────────────────────────────────────────────────┘

FIFO Resource:
├─ Created: __init__ via _ensure_fifo()
├─ Location: /tmp/shotbot_commands.fifo
├─ Status: Recreated atomically on crash
└─ Destroyed: cleanup_fifo_only() or cleanup()

Terminal Process:
├─ Started: _launch_terminal()
│  └─ Type: subprocess.Popen (start_new_session=True)
├─ Tracked: self.terminal_pid, self.terminal_process
├─ Restarted: restart_terminal() (SIGTERM → SIGKILL)
└─ Killed: close_terminal()

Dispatcher Process (bash script):
├─ Started: Spawned by terminal emulator
├─ Tracked: self.dispatcher_pid
├─ Monitored: _is_dispatcher_alive() polls psutil
├─ Killed: Dies with terminal process
└─ Respawned: restart_terminal() relaunches terminal

Dummy Writer FD:
├─ Opened: _open_dummy_writer()
├─ Tracked: self._dummy_writer_fd
├─ Purpose: Keep FIFO alive (prevent reader EOF)
├─ Closed: _close_dummy_writer_fd() or cleanup()
└─ Cleanup: os.close() with error handling

Heartbeat File:
├─ Path: /tmp/shotbot_heartbeat.txt
├─ Created: Dispatcher writes on __HEARTBEAT__ command
├─ Checked: _check_heartbeat() reads mtime
└─ Cleaned: Dispatcher removes on exit

PID Files:
├─ Path: /tmp/shotbot_pids/
├─ Format: <app_name>_<timestamp>.pid
├─ Created: Dispatcher after spawning GUI app
├─ Read: ProcessVerifier during verification
├─ Cleaned: Auto on init (> 24h old)

Active Workers:
├─ Tracked: self._active_workers list
├─ Protected: _workers_lock
├─ Added: send_command_async()
├─ Removed: cleanup_worker() callback
└─ Destroyed: deleteLater() (Qt deferred deletion)

Locks (threading.Lock):
├─ _write_lock: FIFO operation serialization
├─ _state_lock: Terminal/dispatcher PID protection
├─ _restart_lock: Restart operation serialization
└─ _workers_lock: Active workers list protection

Test Instances (class-level):
├─ Tracked: _test_instances (classvar list)
├─ Protected: _test_instances_lock
├─ Added: __init__
├─ Removed: cleanup()
└─ Destroyed: cleanup_all_instances() (test cleanup)

Cleanup Sequence on App Exit:
┌──────────────────────────────────────────┐
│ 1. STOP ALL WORKERS FIRST                │
│    ├─ requestInterruption() on each      │
│    ├─ wait(2s) for graceful stop         │
│    ├─ terminate() if not stopped         │
│    └─ wait(1s) for forceful stop         │
│                                          │
│ 2. CLOSE TERMINAL                        │
│    ├─ send_command("EXIT_TERMINAL")      │
│    ├─ wait(0.5s) for graceful shutdown   │
│    ├─ os.kill(terminal_pid, SIGTERM)     │
│    ├─ wait(0.5s)                         │
│    └─ os.kill(terminal_pid, SIGKILL)     │
│                                          │
│ 3. CLOSE DUMMY WRITER FD                 │
│    ├─ os.close(_dummy_writer_fd)         │
│    └─ Set _fd_closed = True              │
│                                          │
│ 4. UNLINK FIFO                           │
│    └─ Path(_fifo_path).unlink()          │
└──────────────────────────────────────────┘
```

---

**End of Diagrams**
