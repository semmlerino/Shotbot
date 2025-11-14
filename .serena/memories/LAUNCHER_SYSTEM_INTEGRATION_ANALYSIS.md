# VERY THOROUGH LAUNCHER/TERMINAL SYSTEM INTEGRATION ANALYSIS

**Document Date**: 2025-11-14  
**Thoroughness Level**: VERY THOROUGH (Comprehensive integration analysis)  
**Analysis Scope**: How PersistentTerminalManager, CommandLauncher, and ProcessExecutor integrate with the entire Shotbot application  

---

## 1. COMPLETE INTEGRATION ARCHITECTURE

### 1.1 Integration Hierarchy

```
PRESENTATION LAYER (Qt UI)
├─ MainWindow (central orchestrator)
│  ├─ Owns: PersistentTerminalManager (singleton-like, one per window)
│  ├─ Owns: CommandLauncher (QObject, parent=MainWindow)
│  ├─ Owns: LauncherController (signals dispatcher to launcher_panel)
│  ├─ Owns: LauncherManager (process pool, parent=MainWindow)
│  └─ Owns: CleanupManager (shutdown orchestrator)
│
├─ LauncherPanel (UI controls)
│  └─ Signal: button_clicked → LauncherController.launch_app()
│
└─ Various Dialogs
   ├─ ThreeDESceneDialog
   ├─ LauncherManagerDialog
   └─ SettingsDialog

CONTROLLERS LAYER
├─ LauncherController
│  ├─ Coordinates: launch_app(), _execute_launch_with_options()
│  ├─ Connects to: CommandLauncher signals (command_executed, command_error)
│  ├─ Manages: Shot context, scene context
│  └─ Emits to UI: Status updates, error notifications
│
├─ ThreeDEController
│  ├─ Launches 3DE with context
│  └─ Uses: CommandLauncher.launch_app(app_name="3de", context=...)
│
└─ SettingsController
    └─ Manages: Config updates, persistence

COORDINATION LAYER
├─ CommandLauncher (973 LOC)
│  ├─ Owns: ProcessExecutor
│  ├─ Owns: EnvironmentManager
│  ├─ Owns: Multiple finders (Nuke, 3DE, Maya, RawPlate)
│  ├─ Connects to: PersistentTerminalManager signals (if present)
│  └─ Emits: command_executed, command_error, command_verified
│
├─ LauncherManager
│  ├─ Owns: LauncherWorker threads
│  ├─ Accesses: ProcessPoolManager (singleton)
│  └─ Manages: Custom launchers
│
├─ RefreshOrchestrator
│  ├─ Coordinates: Shot model refresh, 3DE scene refresh, previous shots refresh
│  └─ Uses: CacheManager, ProcessPoolManager (no launcher dependency)
│
└─ CleanupManager (shutdown orchestrator)
    └─ Orchestrates: Terminal cleanup, Manager shutdown, Model cleanup

SYSTEM INTEGRATION LAYER
├─ ProcessExecutor (in launch/ package)
│  ├─ Routes: Persistent terminal vs new terminal
│  ├─ Owns: ProcessVerifier (Phase 2 verification)
│  ├─ Connects to: PersistentTerminalManager signals
│  └─ Manages: Signal forwarding
│
├─ PersistentTerminalManager (1,408 LOC)
│  ├─ Owns: TerminalOperationWorker threads
│  ├─ Owns: ProcessVerifier
│  ├─ Manages: FIFO, dispatcher process, dummy writer FD
│  ├─ Emits: 9 signals (terminal_*, command_*, operation_*)
│  └─ Tracks: TestInstances for cleanup
│
├─ ProcessPoolManager (singleton)
│  ├─ Manages: Workspace session pool
│  ├─ Executes: Pure bash commands (no UI launch)
│  └─ Independent: From launcher system (different responsibility)
│
└─ CacheManager (singleton)
    ├─ Manages: Multi-level caching (memory, disk, incremental)
    ├─ Used by: ShotModel, ThreeDESceneModel, PreviousShotsModel
    └─ Independent: From launcher system

INFRASTRUCTURE LAYER
├─ Config (global constants)
├─ Singleton Managers
│  ├─ NotificationManager (UI notifications)
│  ├─ ProgressManager (status bar updates)
│  ├─ FilesystemCoordinator (directory caching)
│  └─ Each has: reset() method for test isolation
└─ Mixins & Utilities
```

### 1.2 Signal Flow Chain

```
USER ACTION
  ↓
LauncherPanel: button_clicked(app_name)
  ↓
LauncherController: launch_app(app_name)
  ↓ (validates shot, builds context)
CommandLauncher: launch_app(app_name, context)
  ↓ (app-specific logic: Nuke, 3DE, Maya)
CommandLauncher: _execute_launch(command, app_name)
  ├─ Try Path 1: _try_persistent_terminal(command, app_name)
  │  └─ persistent_terminal.send_command_async(command)
  │     └─ TerminalOperationWorker (background thread)
  │        ├─ Emit: command_queued(timestamp, cmd)
  │        ├─ Emit: command_executing(timestamp)
  │        ├─ Emit: command_verified OR command_error
  │        └─ _on_async_command_finished(success, msg)
  │
  └─ Fallback: _on_persistent_terminal_operation_finished(fail)
     └─ _launch_in_new_terminal(command)
        └─ ProcessExecutor: execute_in_new_terminal()
           └─ subprocess.Popen([terminal, -e, bash, -c, command])

SIGNALS EMITTED (at various stages):
1. command_queued → logged
2. command_executing → logged
3. command_verified → LauncherController._on_command_verified()
   └─ Emit: command_executed (to MainWindow/UI)
4. command_error → LauncherController._on_command_error_internal()
   └─ Emit: command_error (to MainWindow/UI)

UI UPDATES (in MainWindow):
├─ Status bar: updates via ProgressManager
├─ Log viewer: appends output via command_executed signal
├─ Notification: toast via NotificationManager
└─ Error dialog: modal dialog via command_error signal
```

---

## 2. DETAILED INTEGRATION POINTS & DEPENDENCIES

### 2.1 MainWindow → PersistentTerminalManager Dependency

**Type**: Composition (MainWindow owns instance)  
**Created**: Line 296-300 in MainWindow.__init__()

```python
if Config.PERSISTENT_TERMINAL_ENABLED and Config.USE_PERSISTENT_TERMINAL:
    self.persistent_terminal = PersistentTerminalManager(
        fifo_path=Config.PERSISTENT_TERMINAL_FIFO
    )
```

**Risk Level**: MEDIUM
- **Tight Coupling Issue**: MainWindow directly instantiates terminal manager
- **No Interface**: No abstraction/protocol to swap implementations
- **Circular Dependency Risk**: PersistentTerminalManager signals → LauncherController signals → MainWindow UI updates
- **Cleanup Order**: Must cleanup persistent_terminal BEFORE closing MainWindow

**Integration Points**:
- Signal source: PersistentTerminalManager emits 9 signals
- Signal consumers: CommandLauncher, LauncherController, ProcessExecutor
- Shutdown: CleanupManager._cleanup_terminal() calls persistent_terminal.cleanup()
- Test Isolation: PersistentTerminalManager.cleanup_all_instances() in conftest.py

### 2.2 CommandLauncher → PersistentTerminalManager Dependency

**Type**: Dependency Injection + Signal Connection  
**Created**: Line 115 in CommandLauncher.__init__()

```python
self.process_executor = ProcessExecutor(persistent_terminal, Config)

if self.persistent_terminal:
    _ = self.persistent_terminal.command_queued.connect(self._on_command_queued)
    _ = self.persistent_terminal.command_executing.connect(self._on_command_executing)
    _ = self.persistent_terminal.command_verified.connect(self._on_command_verified)
    _ = self.persistent_terminal.command_error.connect(self._on_command_error_internal)
    _ = self.persistent_terminal.operation_finished.connect(
        self._on_persistent_terminal_operation_finished
    )
```

**Risk Level**: MEDIUM
- **Optional Dependency**: Can work with None, but terminal features disabled
- **Tight Coupling via Signals**: 5 signal connections (not easily mockable in tests)
- **Fallback Mechanism**: Stores failed commands in _pending_fallback for retry
- **Timestamp-Based Tracking**: _pending_fallback[timestamp] = (cmd, app_name)

**Integration Points**:
- Receives persistent_terminal as constructor argument
- Passes to ProcessExecutor for routing
- Connects to Phase 1 & 2 signals (queued, executing, verified, error)
- Implements fallback retry via operation_finished signal
- Stores pending commands with timestamp-based cleanup

**Potential Issues**:
1. **Timestamp Collision**: Across day boundary, old commands not cleaned up
2. **30-Second Cleanup Window**: Commands older than 30s cleared
3. **Signal Loss on Disconnect**: If signal not connected, fallback never triggered

### 2.3 ProcessExecutor → PersistentTerminalManager Dependency

**Type**: Dependency Injection + Signal Forwarding  
**Created**: Line 115 in CommandLauncher.__init__()

```python
self.process_executor = ProcessExecutor(persistent_terminal, Config)
```

**Risk Level**: MEDIUM
- **Routing Responsibility**: ProcessExecutor decides persistent vs new terminal
- **Config-Dependent**: Uses Config.PERSISTENT_TERMINAL_ENABLED flag
- **Fallback Handling**: Auto-routes to new terminal if persistent fails
- **Signal Forwarding**: Forwards terminal signals to its own signals

**Integration Points**:
- Receives persistent_terminal in constructor
- Checks is_gui_app() to determine if backgrounding needed
- Routes async (persistent) vs sync (new terminal) execution
- Returns process object for Phase 2 verification
- Emits: execution_progress, execution_completed, execution_error

**Critical Methods**:
1. `_execute_async_with_persistent_terminal()` - Routes to PersistentTerminalManager
2. `_execute_sync_with_new_terminal()` - Fallback execution
3. Automatic fallback if persistent terminal unavailable

### 2.4 LauncherController → CommandLauncher Dependency

**Type**: Composition (window owns it)  
**Created**: Via MainWindow.launcher_controller

```python
self.launcher_controller = LauncherController(self)
# LauncherController receives MainWindow as parameter
# Accesses: window.command_launcher
```

**Risk Level**: LOW
- **Clean Interface**: Uses command_launcher.launch_app() public method
- **Event-Driven**: Connected via signals
- **Validation**: LauncherController validates context before launching

**Integration Points**:
- Reads: current_shot, current_scene from state management
- Calls: command_launcher.launch_app(app_name, context)
- Listens: command_executed, command_error signals
- Emits: Status updates to LauncherPanel

**Signal Connections** (line 116-122):
```python
_ = self.window.command_launcher.command_executed.connect(
    self._on_command_executed
)
_ = self.window.command_launcher.command_error.connect(
    self._on_command_error
)
_ = self.window.command_launcher.command_error.connect(self._on_command_error)
```

### 2.5 CleanupManager → Terminal/Launcher Dependencies

**Type**: Orchestration (cleanup sequence)  
**Entry Point**: MainWindow.closeEvent() → CleanupManager.perform_cleanup()

**Cleanup Sequence** (lines 59-79):
```
1. _mark_closing() - Set _closing flag
2. _cleanup_threede_controller() - Stop 3DE controller
3. _cleanup_session_warmer() - Stop session warmer
4. _cleanup_managers() - Shutdown launchers
   └─ launcher_manager.shutdown() [stops workers]
   └─ cache_manager.shutdown()
5. _cleanup_models() - Stop model refresh
6. _cleanup_terminal() - Stop terminal
   └─ persistent_terminal.cleanup() [stops workers, closes FIFO]
7. _final_cleanup() - Process pool cleanup
```

**Risk Level**: MEDIUM
- **Order Dependency**: Terminal cleanup depends on manager cleanup
- **Worker Coordination**: Must stop all workers before terminal cleanup
- **Lock Deadlock Risk**: If workers hold locks, cleanup can deadlock
- **Timeout Handling**: 10-second timeout for worker shutdown (line 1369)

**Critical Code** (cleanup_manager.py:209-216):
```python
def _cleanup_terminal(self) -> None:
    # Terminal cleanup MUST happen after manager cleanup
    # Persistent terminal cleanup stops workers and closes FIFO
    if not Config.KEEP_TERMINAL_ON_EXIT:
        self.main_window.persistent_terminal.cleanup()
    else:
        self.main_window.persistent_terminal.cleanup_fifo_only()
```

---

## 3. RESOURCE MANAGEMENT ACROSS BOUNDARIES

### 3.1 File Descriptor Management

**FIFO File Descriptor Lifecycle**:
```
CREATE: __init__() → _ensure_fifo(open_dummy_writer=False)
        ├─ Creates FIFO at self.fifo_path
        └─ Does NOT open dummy writer yet (no reader)

OPEN WRITER: restart_terminal() → _open_dummy_writer()
             ├─ Called AFTER dispatcher starts
             ├─ os.open(FIFO, O_WRONLY | O_NONBLOCK)
             └─ Stores FD in self._dummy_writer_fd

USE: send_command_direct() → os.open(FIFO, O_WRONLY | O_NONBLOCK)
     ├─ Acquires _write_lock
     ├─ Opens fresh FD (ephemeral)
     ├─ Writes command
     └─ Closes FD immediately (via fdopen context manager)

CLOSE DUMMY WRITER: _close_dummy_writer_fd()
                    ├─ Called during restart or cleanup
                    ├─ os.close(self._dummy_writer_fd)
                    └─ Sets self._dummy_writer_fd = None

DELETE FIFO: cleanup() → Path(fifo_path).unlink()
            └─ Called during app shutdown
```

**Risk Analysis**:
1. **FD Leak Window**: Between send_command_direct() open and close
   - **Mitigation**: Context manager (os.fdopen) guarantees close
   - **Fallback**: Error handling tries to close on exception
   
2. **Dummy Writer FD Leak on Exception**:
   - **Location**: _open_dummy_writer() line ~1250
   - **Scenario**: os.open() succeeds, assignment fails
   - **Current Code**: Assignment before exception-raising code
   - **Status**: SAFE (assignment happens before risk)

3. **FIFO File Orphaning**:
   - **Scenario**: Process crashes, FIFO left in filesystem
   - **Impact**: Next startup tries to recreate, may get EEXIST
   - **Mitigation**: Atomic recreation with temp file + rename (line 1273-1286)
   - **Status**: SAFE (atomic operation prevents race)

### 3.2 Thread Resource Management

**Worker Thread Lifecycle**:
```
CREATE: send_command_async()
        ├─ TerminalOperationWorker(self, operation, parent=self)
        ├─ Stored in _active_workers[worker]
        └─ worker.start() [begins in background thread]

RUN: TerminalOperationWorker.run()
     ├─ _ensure_dispatcher_healthy()
     ├─ _send_command_direct()
     ├─ wait_for_process() [Phase 2]
     └─ Emit finished signal

CLEANUP: _on_async_command_finished() slot
         ├─ Remove from _active_workers[worker]
         ├─ worker.deleteLater() [deferred deletion]
         └─ Qt cleanup after event processing

SHUTDOWN: cleanup()
          ├─ with _workers_lock:
          ├─ workers_to_stop = list(_active_workers)
          ├─ For each worker:
          │  ├─ worker.requestInterruption()
          │  ├─ worker.wait(10000) [10-second timeout]
          │  └─ If timeout: log error, continue (NO terminate())
          └─ Clear _active_workers
```

**Risk Analysis**:
1. **Worker Hang During Cleanup**:
   - **Scenario**: Worker stuck in health check or FIFO I/O
   - **Current Handling**: 10-second timeout, log error
   - **Issue**: Code comment explicitly forbids calling terminate() (causes deadlock)
   - **Status**: ACCEPTABLE (10s timeout is reasonable, prevent deadlock)

2. **Deadlock Prevention**:
   - **Risk**: Worker calls _ensure_dispatcher_healthy() while holding _state_lock
   - **Mitigation**: Lock hierarchy: _write_lock → _state_lock only
   - **Status**: SAFE (no nested lock acquisitions)

3. **Qt Parent-Child Lifecycle**:
   - **Requirement**: All workers MUST have parent=self
   - **Status**: CORRECT (line 1021: parent=self)
   - **Verification**: Tests verify parent parameter
   - **Risk**: Missing parent would cause C++ crashes during cleanup (see CLAUDE.md)

### 3.3 Process Resource Management

**Terminal Process Lifecycle**:
```
LAUNCH: _launch_terminal()
        ├─ Subprocess.Popen([terminal_emulator, bash, dispatcher_script])
        ├─ start_new_session=True [process group leader]
        ├─ Stored in self.terminal_process
        └─ Stored in self.terminal_pid

MONITOR: _is_terminal_alive()
         ├─ Check process exists (os.kill(..., 0))
         ├─ Check not zombie
         └─ Return True/False

SIGNAL HANDLING: restart_terminal() on health check failure
                 ├─ close_terminal() [SIGTERM → SIGKILL]
                 └─ _launch_terminal() [restart]

SHUTDOWN: close_terminal()
          ├─ send_command("EXIT_TERMINAL") [graceful]
          ├─ os.kill(terminal_pid, SIGTERM) [gentle]
          ├─ sleep(0.5)
          ├─ os.kill(terminal_pid, SIGKILL) [forceful]
          └─ Clear terminal_pid, terminal_process
```

**Risk Analysis**:
1. **Process Leak on Exception**:
   - **Scenario**: Popen raises FileNotFoundError, process partially created
   - **Mitigation**: Assignment under lock immediately (line ~700)
   - **Status**: SAFE (OS cleans up orphaned processes)

2. **Zombie Process Risk**:
   - **Scenario**: Terminal killed but child dispatcher not reaped
   - **Handling**: start_new_session=True prevents zombie propagation
   - **Status**: SAFE (process group isolation)

3. **Resource Cleanup Order**:
   - **Order**: Close FIFO dummy writer BEFORE killing terminal
   - **Why**: Dispatcher might use dummy writer in exit handler
   - **Status**: CORRECT (cleanup_fifo_only separates concerns)

### 3.4 Singleton Manager Integration

**Singleton Managers Used**:
1. **ProcessPoolManager** (independent of launcher system)
   - Used for workspace commands (not app launching)
   - Singleton with reset() for tests
   
2. **NotificationManager** (notification display)
   - Used by LauncherController and ProcessExecutor
   - Shows errors and status
   - Singleton with reset() for tests

3. **ProgressManager** (progress indication)
   - Updates status bar
   - Singleton with reset() for tests

4. **FilesystemCoordinator** (directory caching)
   - Independent of launcher system

**Integration Risk**:
- **Notification Coupling**: LauncherController depends on NotificationManager.error()
- **Mitigation**: NotificationManager is always initialized in MainWindow (line 475)
- **Status**: SAFE (hard dependency, but initialized early)

---

## 4. RACE CONDITIONS & TIMING DEPENDENCIES

### 4.1 Terminal Startup Race Condition

**Scenario**: Multiple threads try to start terminal simultaneously

```python
Thread A: send_command() → _is_dispatcher_healthy() → False
          ├─ Waits for _restart_lock
          └─ restart_terminal()

Thread B: send_command_async() → _ensure_dispatcher_healthy() → False
          ├─ Waits for _restart_lock
          └─ restart_terminal()

RACE WINDOW:
1. A acquires _restart_lock
2. A: close_terminal()
3. A: _launch_terminal() [waiting for dispatcher to start]
4. B: Waiting for _restart_lock...
5. A: Opens dummy writer FD
6. B: Acquires _restart_lock, calls close_terminal()
7. PROBLEM: B closes A's dummy writer FD!
```

**Mitigation**: _restart_lock serializes all terminal operations

**Current Protection** (line 1271):
```python
with self._restart_lock:
    # All restart operations serialized
    close_terminal()  # SIGTERM → SIGKILL
    _launch_terminal()
    # Wait for dispatcher ready
    while not _is_dispatcher_running():
        time.sleep(0.1)
    _open_dummy_writer()
```

**Status**: SAFE (lock prevents concurrent restarts)

### 4.2 Health Check During Send Command

**Scenario**: Health check and FIFO write race

```
Thread A (send_command):
  ├─ Acquire _write_lock
  ├─ _is_dispatcher_healthy() → True
  │  ├─ Release _write_lock temporarily for poll?
  │  └─ NO - Health check doesn't release lock
  └─ Write to FIFO

Expected behavior: Health check + write are atomic
```

**Current Code** (line 891):
```python
with self._write_lock:
    # Atomic: health check + write are serial relative to other threads
    if not self._ensure_dispatcher_healthy():
        return False
    # ... write to FIFO
```

**Status**: SAFE (write_lock held during entire operation)

### 4.3 Dummy Writer FD State Race

**Scenario**: Close and use dummy writer FD concurrently

```
Thread A (restart_terminal):
  ├─ _close_dummy_writer_fd()
  │  └─ os.close(_dummy_writer_fd)
  │  └─ Set to None

Thread B (send_command) [parallel]:
  ├─ Wants to keep FIFO alive
  └─ Uses dummy writer FD?
     └─ NO - Only internal, not used elsewhere
```

**Status**: SAFE (dummy writer only internal state, not accessed directly)

### 4.4 PID File Race Condition (Phase 2)

**Scenario**: Multiple instances of same app, PID file filtering

```
Dispatcher writes: /tmp/shotbot_pids/nuke_20251114_123456.pid

ProcessVerifier checks:
  ├─ enqueue_time = T0.600
  ├─ List /tmp/shotbot_pids/nuke_*.pid
  │  └─ Find multiple PIDs from different launches
  ├─ Filter by mtime >= enqueue_time
  │  └─ Only recent PID files match
  └─ Return first match
```

**Risk**: Stale PID file from previous launch might match

**Mitigation** (process_verifier.py:~100):
```python
def wait_for_process(self, command, enqueue_time):
    # Filter by file modification time >= enqueue_time
    # Conservative: filters old files
    # Window: ~1-2ms between command enqueue and file write
    
    for pid_file in glob.glob(f"{PID_DIR}/{app_name}_*.pid"):
        if pid_file.stat().st_mtime >= enqueue_time:
            # This is a recent file, likely ours
            return verify_process(pid)
```

**Status**: SAFE (time-based filtering prevents false positives)

**Known Limitation**: If ProcessVerifier hangs, old PID files accumulate
**Mitigation**: cleanup_old_pid_files(max_age_hours=24) on startup

### 4.5 Fallback Retry Timestamp Race

**Scenario**: Timestamp collision across day boundary

```
Command fails at 23:59:59 on Day 1
  └─ Stored: _pending_fallback["20251114_235959"] = (cmd, "nuke")

App continues to Day 2 (00:00:00)
  └─ New command fails: _pending_fallback["20251114_235959"] = (cmd, "maya")
  └─ COLLISION! Same timestamp, different command

Cleanup after 30s:
  └─ Removes BOTH commands (oops, maya command lost)
```

**Current Code** (command_launcher.py):
```python
# Store with timestamp
timestamp = str(time.time())  # Float, not formatted time
_pending_fallback[timestamp] = (cmd, app_name)

# Clean old after 30s
for ts, (cmd, app_name) in list(self._pending_fallback.items()):
    if time.time() - float(ts) > 30:
        del self._pending_fallback[ts]
```

**Status**: SAFE (uses float timestamp, not formatted string)
**Why**: float(time.time()) = 1731533999.123456 (very precise)
**Collision Risk**: < 1 in billion per second

---

## 5. COUPLING ANALYSIS

### 5.1 Tight Coupling Issues

**Issue 1: MainWindow → PersistentTerminalManager Direct Instantiation**
- **Type**: Hard dependency
- **Mitigation**: Could use factory pattern or config flag
- **Current**: Config.PERSISTENT_TERMINAL_ENABLED flag
- **Impact**: HIGH - No way to swap implementation
- **Recommendation**: Create TerminalManagerFactory interface

**Issue 2: CommandLauncher → ProcessExecutor Tight Binding**
- **Type**: Composition, not injection
- **Code** (line 115):
  ```python
  self.process_executor = ProcessExecutor(persistent_terminal, Config)
  ```
- **Impact**: MEDIUM - Can't use different executor
- **Recommendation**: Would be internal; ProcessExecutor part of CommandLauncher responsibility

**Issue 3: Signal-Based Integration**
- **Type**: Loose coupling via signals
- **Signals**: 9 signals from PersistentTerminalManager
- **Subscribers**: LauncherController, ProcessExecutor, CommandLauncher
- **Impact**: LOW - Signals are proper Qt pattern
- **Risk**: Missing connection → silent failure
- **Recommendation**: Document all signal consumers

**Issue 4: Config Dependency**
- **Type**: Global state coupling
- **Config Used**:
  - PERSISTENT_TERMINAL_ENABLED
  - USE_PERSISTENT_TERMINAL
  - PERSISTENT_TERMINAL_FIFO
  - MAX_TERMINAL_RESTART_ATTEMPTS
  - HEARTBEAT_TIMEOUT
  - KEEP_TERMINAL_ON_EXIT
- **Impact**: MEDIUM - Global state hard to test
- **Recommendation**: Already using dependency injection (pass Config to ProcessExecutor)

### 5.2 Loose Coupling (Good)

**Advantage 1: Qt Signal/Slot Architecture**
- PersistentTerminalManager emits signals
- Consumers connect in __init__
- Thread-safe cross-thread delivery
- Clean separation of concerns

**Advantage 2: ProcessExecutor Abstraction**
- Hides terminal routing logic
- Presents unified execute() interface
- Handles persistent vs new terminal internally

**Advantage 3: CommandLauncher Orchestration**
- Handles fallback retry logic
- Decouples app-specific launch logic
- Maintains shot context separately

---

## 6. POTENTIAL ARCHITECTURAL WEAKNESSES

### 6.1 Singleton Anti-Pattern (PersistentTerminalManager)

**Issue**: Not a true singleton, but acts like one
- **Created**: Once per MainWindow instance
- **Stored**: self.persistent_terminal in MainWindow
- **Cleanup**: Via CleanupManager
- **Test Tracking**: _test_instances for cleanup

**Problem**: No central registry
- Multiple MainWindow instances = multiple managers
- But application only has one MainWindow
- In tests, _test_instances grows during parallel execution

**Mitigation**:
```python
with cls._test_instances_lock:
    cls._test_instances.append(self)

# In conftest.py:
PersistentTerminalManager.cleanup_all_instances()
```

**Recommendation**: Document as "quasi-singleton" not true singleton

### 6.2 Fallback Mechanism Complexity

**Issue**: Multiple layers of fallback

```
Layer 1: Persistent terminal in fallback mode
         └─ Disabled for 5 minutes if max restarts exceeded

Layer 2: CommandLauncher fallback retry
         └─ If persistent terminal signal fails, retry in new terminal

Layer 3: ProcessExecutor routing
         └─ Automatically tries persistent, falls back to new terminal
```

**Risk**: Unclear which layer handles what
- Is failure from persistent terminal or new terminal?
- Which layer is responsible for notification?
- What if persistent terminal recovers mid-command?

**Current Responsibility**:
1. PersistentTerminalManager: Enter fallback_mode after 3 restarts
2. ProcessExecutor: Route persistent vs new terminal based on flags
3. CommandLauncher: Implement pending_fallback retry logic

**Recommendation**: Document fallback state machine clearly

### 6.3 Terminal Dispatcher Script Dependency

**Issue**: Bash script critical for functionality
- **File**: terminal_dispatcher.sh (330 lines)
- **Location**: Found relative to module (Path(__file__).parent)
- **Risk**: Script missing = entire system fails
- **Testing**: Hard to test without actual terminal

**Potential Issues**:
1. **Path Resolution**: Relative path might fail in some environments
2. **Permissions**: Script must be executable
3. **Bash Compatibility**: Assumes bash available
4. **Shell Features**: Uses bash-specific features (arrays, pattern matching)

**Current Verification** (test_persistent_terminal_manager.py):
```python
# Tests verify dispatcher exists and is executable
assert Path(manager.dispatcher_path).exists()
assert os.access(manager.dispatcher_path, os.X_OK)
```

**Recommendation**: Bundle dispatcher into package, make unexecutable script executable on first use

### 6.4 No Explicit Timeout on Terminal Operations

**Issue**: Some operations can hang indefinitely
- Health checks: 3-second timeout + polling
- FIFO writes: O_NONBLOCK (returns immediately or EAGAIN)
- Dispatcher startup: 5-second timeout + 0.2s polling
- Process verification: 5-second timeout + 0.2s polling

**Missing Timeouts**:
1. Worker shutdown during cleanup: 10-second timeout (GOOD)
2. Terminal kill signal: No timeout, relies on OS
3. FIFO read/write: Non-blocking, returns immediately

**Status**: ACCEPTABLE (most operations have timeouts)

### 6.5 Resource Leak in Edge Cases

**Scenario 1**: Terminal crashes during restart
```
1. restart_terminal() called
2. close_terminal() kills process
3. _launch_terminal() starts new process
4. Dispatcher startup timeout → exception
5. _open_dummy_writer() never called
6. Result: No dummy writer FD, but terminal running
7. Next send_command() gets ENXIO
```

**Current Handling**: Next send_command() detects unhealthy, attempts recovery

**Scenario 2**: Worker interrupted during FIFO write
```
1. Worker writing to FIFO
2. requestInterruption() called during cleanup
3. Write in progress, might be partial
4. FIFO might contain corrupted command
```

**Current Handling**: Worker checks requestInterruption() regularly

**Status**: ACCEPTABLE (edge cases handled with recovery mechanisms)

---

## 7. INTEGRATION WITH Qt EVENT LOOP

### 7.1 Signal/Slot Delivery

**Pattern**: Cross-thread signal delivery via Qt::QueuedConnection

```
Worker Thread (TerminalOperationWorker)
  ├─ operation_finished.emit(success, message)
  │  └─ Signal object enqueued in main thread's event queue
  │
Main Thread (Qt Event Loop)
  ├─ Process pending events
  ├─ Call slot: _on_async_command_finished(success, message)
  │  ├─ Safe to access MainWindow widgets
  │  ├─ Safe to access UI state
  │  └─ All Qt operations safe
```

**Guarantee**: Qt ensures queued signals delivered in order

**Risk Analysis**:
1. **Signal Loss on Disconnect**: If connection made after emit
   - **Status**: LOW (connections made in __init__)
2. **Signal Delivered After MainWindow Destroyed**: 
   - **Status**: LOW (deleteLater prevents early destruction)
3. **Multiple Signals Overtake Each Other**:
   - **Status**: LOW (signals queued in order)

### 7.2 Qt Parent-Child Lifecycle

**Pattern**: Parent owns children, deletes them on destruction

```
MainWindow (QMainWindow)
  ├─ Owns: PersistentTerminalManager (parent=self)
  │  ├─ Owns: TerminalOperationWorker (parent=self) [created dynamically]
  │  │  └─ Owns: ProcessVerifier (not QObject, no parent)
  │  └─ Owns: ProcessVerifier (not QObject, no parent)
  │
  ├─ Owns: CommandLauncher (parent=self)
  │  ├─ Owns: ProcessExecutor (parent=None, but created once)
  │  └─ Owns: Various finders (parent=None)
  │
  ├─ Owns: LauncherManager (parent=self)
  │  └─ Owns: LauncherWorker threads (parent=self)
  │
  └─ Owns: CleanupManager (parent=None, but holds reference to MainWindow)
```

**Parent-Child Benefits**:
1. Qt automatically deletes children when parent deleted
2. Signals/slots disconnected when parent deleted
3. Event loop prevents crashes from use-after-delete

**Parent-Child Risks**:
1. Circular reference: CleanupManager holds reference to MainWindow
   - **Mitigation**: CleanupManager is not parented to MainWindow
   - **Status**: SAFE (manual cleanup in closeEvent)
2. Missing parent parameter:
   - **Status**: ALL checked, parent parameter always provided
   - **Tests**: Verify parent parameter in test_persistent_terminal_manager.py

### 7.3 Qt Event Loop Blocking

**Pattern**: Some operations block the event loop

```
Main Thread (Qt Event Loop)
  ├─ Process events
  ├─ Call: command_launcher.launch_app()
  │  ├─ Validates shot context
  │  ├─ Builds launch command
  │  ├─ Calls: persistent_terminal.send_command_async()
  │  │  └─ Returns immediately (creates worker thread)
  │  └─ Returns to caller [EVENT LOOP CONTINUES]
  │
  └─ Continue processing events [NON-BLOCKING]
```

**Blocking Operations** (if any):
1. send_command() - BLOCKING, waits for FIFO write
   - **Used**: Rarely, mostly for terminal control (EXIT_TERMINAL)
   - **Risk**: LOW (not used for app launching)
2. _is_dispatcher_healthy() - BLOCKING, polls with sleep
   - **Duration**: Up to 3 seconds
   - **Risk**: MEDIUM if called from main thread (not done)
   - **Status**: Only called from worker thread

**Status**: SAFE (async-first design, blocking operations avoided on main thread)

---

## 8. CONFIGURATION & INITIALIZATION PATTERNS

### 8.1 Initialization Order Dependencies

**Order Matters**:
```
1. QApplication created (done by test framework or main.py)
2. MainWindow.__init__()
   ├─ CacheManager created
   ├─ Models created (ShotModel, ThreeDESceneModel)
   ├─ PersistentTerminalManager created (FIFO created, dispatcher NOT started)
   ├─ CommandLauncher created (connects to terminal signals)
   ├─ LauncherController created (connects to launcher signals)
   ├─ UI created (_setup_ui())
   ├─ Controllers initialized (ThreeDEController, LauncherController)
   ├─ Signals connected (_connect_signals())
   └─ Initial load (_initial_load())

CRITICAL: Terminal signals must be connected BEFORE any commands sent
```

**Current Verification**:
```python
# Line 296-300: Terminal created
self.persistent_terminal = PersistentTerminalManager(...)

# Line 302-304: CommandLauncher created (connects to signals)
self.command_launcher = CommandLauncher(
    persistent_terminal=self.persistent_terminal,
    parent=self
)

# Line 336: Launcher controller created (connects to launcher signals)
self.launcher_controller = LauncherController(self)
```

**Status**: CORRECT (order is correct)

### 8.2 Configuration Dependencies

**Config Values Used**:

| Config | Used By | Impact |
|--------|---------|--------|
| PERSISTENT_TERMINAL_ENABLED | MainWindow | Terminal created |
| USE_PERSISTENT_TERMINAL | ProcessExecutor | Routing decision |
| PERSISTENT_TERMINAL_FIFO | PersistentTerminalManager | FIFO path |
| MAX_TERMINAL_RESTART_ATTEMPTS | PersistentTerminalManager | Fallback trigger |
| HEARTBEAT_TIMEOUT | PersistentTerminalManager | Health check |
| KEEP_TERMINAL_ON_EXIT | CleanupManager | Cleanup type |
| DEFAULT_APP | LauncherPanel | Default app |

**Initialization Risk**:
- Config must be valid before MainWindow created
- No validation of config values
- Invalid paths → silent failures

**Recommendation**: Add config validation in MainWindow.__init__()

---

## 9. INTEGRATION WITH SINGLETONS

### 9.1 NotificationManager Integration

**Usage**:
```python
# In LauncherController._on_command_error():
from notification_manager import NotificationManager
NotificationManager.error(title, error_message)

# In ProcessExecutor:
NotificationManager.toast(message)
```

**Risk**:
- Notification failures don't propagate to launcher system
- Silent failures if NotificationManager not initialized
- Coupled to global singleton

**Mitigation**:
- NotificationManager initialized in MainWindow.__init__ (line 475)
- Always initialized before launcher system
- Has reset() method for test isolation

**Status**: SAFE (always initialized before use)

### 9.2 ProgressManager Integration

**Usage**:
```python
# Not directly used by launcher system
# But ProcessExecutor might emit progress signals
# that MainWindow connects to status bar
```

**Integration**: INDIRECT (via signals, not direct calls)

**Status**: SAFE (no direct coupling)

### 9.3 ProcessPoolManager Integration

**Usage**:
```python
# In MainWindow:
self._process_pool = ProcessPoolManager.get_instance()

# In ShotModel:
self.process_pool = ProcessPoolManager.get_instance()

# NOT used by launcher system (different responsibility)
```

**Separation of Concerns**:
- ProcessPoolManager: Pure bash commands, session management
- PersistentTerminalManager: App launching, GUI state

**Status**: GOOD SEPARATION (no coupling)

---

## 10. CRITICAL BUGS & ARCHITECTURAL WEAKNESSES

### 10.1 CRITICAL: Missing Signal Connection Verification

**Issue**: If signal connection fails, silent failure

```python
# In CommandLauncher.__init__ (line 126-131):
if self.persistent_terminal:
    _ = self.persistent_terminal.command_queued.connect(self._on_command_queued)
    _ = self.persistent_terminal.command_executing.connect(self._on_command_executing)
    # ... more connections
```

**Risk**:
1. If signal signature mismatch, connection fails silently (connection returns False)
2. Code doesn't check return value
3. Fallback retry mechanism never triggered

**Current Code**:
```python
result = signal.connect(slot)  # Returns bool (success/failure)
_ = result  # Ignored!
```

**Fix**:
```python
assert self.persistent_terminal.command_queued.connect(self._on_command_queued)
assert self.persistent_terminal.command_executing.connect(self._on_command_executing)
# ... etc
```

**Severity**: HIGH
**Recommendation**: Add assertions for all signal connections

### 10.2 CRITICAL: Cleanup Lock Acquisition During Worker Shutdown

**Issue**: cleanup() waits for workers with lock held

**Code** (persistent_terminal_manager.py:1359-1380):
```python
def cleanup(self) -> None:
    with self._workers_lock:
        workers_to_stop = list(self._active_workers)
    
    for worker in workers_to_stop:
        worker.requestInterruption()
        if not worker.wait(10000):  # 10 second timeout
            self.logger.error("Worker did not stop after 10s")
            # NO terminate() - causes deadlock!
    
    with self._workers_lock:
        self._active_workers.clear()
```

**Risk**:
1. If worker hangs during wait(), cleanup blocks for 10 seconds
2. If multiple workers hang, cleanup blocks for 30+ seconds
3. Application exit hangs

**Current Mitigation**: Explicit comment forbids terminate()
```python
# CRITICAL: Do NOT call terminate() - it kills threads holding locks
# This causes permanent deadlock.
```

**Status**: ACCEPTABLE (with 10-second timeout)
**Recommendation**: Make timeout configurable, add progress logging

### 10.3 MEDIUM: Terminal Initialization Race

**Issue**: Dispatcher might not be ready when dummy writer opened

```python
restart_terminal():
  1. _launch_terminal()  # Spawns bash with dispatcher
  2. sleep(0.5)        # Give terminal time to start
  3. Poll for dispatcher PID (5s timeout)
  4. _open_dummy_writer()
  
RACE WINDOW: Between sleep(0.5) and dispatcher actually ready
             Opening dummy writer might fail with ENXIO
```

**Current Handling** (line 1290-1310):
```python
# Wait for dispatcher to be ready
while not self._is_dispatcher_running() and elapsed < 5:
    time.sleep(0.2)
    elapsed += 0.2

# Now safe to open dummy writer
self._open_dummy_writer()
```

**Status**: SAFE (polls until dispatcher ready)

### 10.4 MEDIUM: FIFO EOF Race Condition

**Issue**: Dispatcher sees EOF, exits, terminal dies

```
Scenario:
1. send_command() writes to FIFO
2. Dispatcher processes command
3. Dispatcher loops back to read
4. MainWindow.closeEvent() calls cleanup()
5. cleanup() closes dummy writer FD
6. Dispatcher's read() returns EOF
7. Dispatcher exits, terminal dies
8. Next send_command() gets ENXIO

Race Window: Small (dispatcher processing command), acceptable
```

**Mitigation**: Proper cleanup sequence
```python
# 1. Stop workers first
# 2. Close terminal (graceful with EXIT_TERMINAL)
# 3. Close dummy writer FD
# 4. Unlink FIFO
```

**Status**: SAFE (cleanup sequence correct)

### 10.5 MEDIUM: No PID File Cleanup on Dispatcher Crash

**Issue**: PID files accumulate if dispatcher crashes

```
Scenario:
1. Dispatcher crashes (killed, segfault, etc.)
2. PID file left at /tmp/shotbot_pids/nuke_*.pid
3. Next launch, ProcessVerifier finds stale PID
4. Stale PID doesn't exist, returns error

Accumulation:
- Multiple crashes → multiple PID files
- No automatic cleanup
```

**Current Mitigation** (process_verifier.py):
```python
def cleanup_old_pid_files(max_age_hours=24):
    # Called on PersistentTerminalManager.__init__
    # Removes files older than 24 hours
```

**Recommendation**: Also cleanup on successful process verification

---

## 11. TESTING & MOCKABILITY

### 11.1 Tight Coupling Issues for Testing

**Issue 1: Direct Instantiation**
```python
# Hard to test without actual terminal
manager = PersistentTerminalManager(fifo_path="/tmp/test.fifo")
```

**Mitigation**: Use @patch decorators in tests
```python
@patch('os.open')
@patch('subprocess.Popen')
def test_command(mock_popen, mock_open):
    manager = PersistentTerminalManager()
```

**Issue 2: Signal Connections**
```python
# Hard to test signal connections
launcher = CommandLauncher(persistent_terminal=manager)
# All 5 signals connected, hard to mock
```

**Mitigation**: Use qtbot signal spying
```python
qtbot.spy(launcher.command_executed)
launcher.launch_app("nuke")
assert qtbot.spy.call_count > 0
```

### 11.2 Test Isolation

**Issue**: Singletons persist between tests

```python
def test_one():
    manager = PersistentTerminalManager()
    # manager added to _test_instances

def test_two():
    manager = PersistentTerminalManager()  # Same FIFO path!
    # Conflict with test_one's FIFO
```

**Mitigation** (conftest.py:398-417):
```python
@pytest.fixture(autouse=True)
def cleanup_persistent_terminals():
    yield
    PersistentTerminalManager.cleanup_all_instances()
```

**Status**: SAFE (autouse fixture ensures cleanup)

---

## 12. INTEGRATION POINTS SUMMARY TABLE

| Component | Dependency | Type | Risk | Status |
|-----------|-----------|------|------|--------|
| MainWindow | PersistentTerminalManager | Composition | MEDIUM | Owned, cleaned up |
| MainWindow | CommandLauncher | Composition | LOW | Owned, signals connected |
| MainWindow | LauncherController | Composition | LOW | Owned, protocols implemented |
| MainWindow | CleanupManager | Composition | LOW | Owned, orchestrates cleanup |
| CommandLauncher | PersistentTerminalManager | DI + signals | MEDIUM | Optional, fallback available |
| CommandLauncher | ProcessExecutor | Composition | LOW | Internal, well-isolated |
| ProcessExecutor | PersistentTerminalManager | DI + signals | MEDIUM | Optional, fallback available |
| LauncherController | CommandLauncher | Reference | LOW | Via window, signals connected |
| CleanupManager | PersistentTerminalManager | Reference | LOW | Via window, cleanup only |
| CleanupManager | CommandLauncher | Reference | LOW | Via window, no cleanup |
| PersistentTerminalManager | NotificationManager | Global | LOW | Optional, always initialized |
| PersistentTerminalManager | ProcessPoolManager | None | N/A | Independent systems |
| LauncherController | NotificationManager | Global | LOW | Directly calls for errors |
| ProcessExecutor | NotificationManager | Global | LOW | Directly calls for toasts |

---

## 13. ARCHITECTURE RECOMMENDATIONS

### 13.1 Immediate Fixes (High Priority)

1. **Add Signal Connection Assertions**
   - File: command_launcher.py
   - Add assertions to verify all signal connections succeed
   - Prevent silent failures

2. **Add Config Validation**
   - File: config.py or MainWindow.__init__
   - Validate PERSISTENT_TERMINAL_FIFO path is writable
   - Validate dispatcher_path exists and is executable

3. **Document Fallback State Machine**
   - File: docs/ or CLAUDE.md
   - Create state diagram showing fallback transitions
   - Document expected signal flow

### 13.2 Medium-Term Improvements

1. **Extract TerminalManagerInterface**
   - File: terminal_manager_interface.py
   - Create protocol for terminal managers
   - Allow swapping implementations

2. **Simplify Fallback Logic**
   - Currently spans 3 layers (Terminal, ProcessExecutor, CommandLauncher)
   - Consolidate in single component
   - Clearer responsibility

3. **Add Metrics/Telemetry**
   - Track: restart counts, fallback activations, command failure rates
   - Help diagnose production issues
   - No performance impact (optional logging)

### 13.3 Long-Term Refactoring

1. **Decompose MainWindow**
   - Extract LauncherUIManager
   - Extract SettingsUIManager
   - Reduce from 1,563 to ~900 LOC

2. **Create LauncherFactory**
   - Support multiple terminal implementations
   - Allow per-environment configuration

3. **Extract ProcessVerifier to ProcessVerifierManager**
   - Make it singleton
   - Centralize PID file management
   - Handle cleanup systematically

---

## 14. INTEGRATION SUMMARY

### Key Strengths
✅ Qt signal/slot pattern properly used  
✅ Proper thread boundaries (main vs workers)  
✅ Parent-child relationships correct  
✅ Fallback mechanisms in place  
✅ Cleanup sequence correct  
✅ Test isolation working  

### Key Risks
⚠️ Tight coupling to PersistentTerminalManager  
⚠️ Complex fallback logic across 3 layers  
⚠️ No signal connection verification  
⚠️ Terminal dispatcher bash script dependency  
⚠️ No config validation  

### Integration Health
- **Signal Flow**: HEALTHY (proper queuing)
- **Resource Management**: HEALTHY (proper cleanup)
- **Thread Safety**: HEALTHY (locks correct)
- **Coupling**: ACCEPTABLE (Qt patterns)
- **Testability**: GOOD (with mocking)
- **Overall Rating**: 7.5/10 (Well-integrated, some simplification needed)
